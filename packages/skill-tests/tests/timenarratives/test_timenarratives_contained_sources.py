"""Selected-root filters must not silently discard supported descendants."""

from __future__ import annotations

import hashlib
import importlib
import sys
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))
build_packet = importlib.import_module("build_packet")
docx_units = importlib.import_module("docx_units")
reconciliation = importlib.import_module("structural_contracts")


def _request() -> dict:
    return {
        "schemaVersion": "timenarratives.request.v1",
        "runId": "Contained_01",
        "actor": {"id": "lawyer", "name": "Evaluation Lawyer", "aliases": []},
        "matter": {"id": "MATTER-1", "client": None, "aliases": []},
        "selections": [{"kind": "file", "path": "selected.eml"}],
        "filters": {
            "sourceTypes": ["email"],
            "since": "2026-08-20T00:00:00+01:00",
            "until": "2026-08-20T23:59:59+01:00",
            "asOf": "2026-08-21T12:00:00+01:00",
        },
    }


def _outer_message() -> EmailMessage:
    message = EmailMessage()
    message["From"] = "lead@example.test"
    message["Date"] = "Thu, 20 Aug 2026 15:30:00 +0100"
    message.set_content("Selected root body")
    return message


def test_included_email_inspects_text_and_out_of_window_nested_email(
    tmp_path: Path,
) -> None:
    message = _outer_message()
    message.add_attachment(
        b"Contained text work", maintype="text", subtype="plain", filename="work.txt"
    )
    nested = EmailMessage()
    nested["From"] = "forwarded@example.test"
    nested["Date"] = "Wed, 19 Aug 2026 10:00:00 +0100"
    nested.set_content("Contained nested work")
    wrapper = EmailMessage()
    wrapper.set_type("message/rfc822")
    wrapper.set_payload([nested])
    message.attach(wrapper)
    (tmp_path / "selected.eml").write_bytes(message.as_bytes(policy=SMTP))

    packet = build_packet.compile_packet(_request(), tmp_path)

    assert packet["roots"][0]["disposition"] == "ready"
    assert [row["sourceType"] for row in packet["containers"]] == [
        "email",
        "text",
        "email",
    ]
    assert all(row["disposition"] == "ready" for row in packet["containers"])
    assert {unit["containerId"] for unit in packet["units"]} == {
        "S0001",
        "S0001-A0001",
        "S0001-A0002",
    }
    assert packet["status"] == "ready_for_semantic_analysis"


def test_included_email_inspects_docx_child_without_expanding_root_filters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    message = _outer_message()
    message.add_attachment(
        b"PK\x03\x04synthetic-docx",
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="work.docx",
    )
    (tmp_path / "selected.eml").write_bytes(message.as_bytes(policy=SMTP))
    calls: list[str] = []

    def parse_docx(_data: bytes, container_id: str) -> dict:
        calls.append(container_id)
        text = "Contained DOCX work"
        return {
            "disposition": "ready",
            "reason": None,
            "sourceTime": "2020-01-01T00:00:00Z",
            "sourceTimeKind": "docx_core_modified",
            "sourceAuthor": None,
            "parts": [],
            "units": [
                {
                    "unitId": f"{container_id}-U0001",
                    "containerId": container_id,
                    "originId": container_id,
                    "kind": "docx_accepted",
                    "role": "accepted",
                    "locator": "docx:word/document.xml#body/p[1]",
                    "canonicalText": text,
                    "canonicalUtf8Sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "utf8Start": 0,
                    "utf8End": len(text.encode()),
                    "eligibility": "eligible",
                    "coverageDisposition": "pending",
                    "sourceClass": "documentary_supported",
                    "sourceAuthor": None,
                    "sourceTime": "2020-01-01T00:00:00Z",
                    "assertedByActorId": None,
                    "metadata": {"partName": "word/document.xml"},
                }
            ],
            "limitations": [],
            "notes": [],
            "affectedParts": [],
        }

    monkeypatch.setattr(docx_units, "parse_docx", parse_docx)
    packet = build_packet.compile_packet(_request(), tmp_path)

    assert calls == ["S0001-A0001"]
    child = packet["containers"][1]
    assert child["sourceType"] == "docx"
    assert child["disposition"] == "ready"
    assert child["filterDisposition"] == "included"
    assert any(unit["containerId"] == child["containerId"] for unit in packet["units"])


def test_unsupported_attachment_stays_unreadable_and_reconciled(
    tmp_path: Path,
) -> None:
    message = _outer_message()
    message.add_attachment(
        b"unsupported", maintype="application", subtype="octet-stream", filename="x.bin"
    )
    (tmp_path / "selected.eml").write_bytes(message.as_bytes(policy=SMTP))

    packet = build_packet.compile_packet(_request(), tmp_path)

    attachment = next(
        leaf for leaf in packet["mimeLeaves"] if leaf["role"] == "attachment"
    )
    assert attachment["disposition"] == "unreadable"
    assert attachment["reason"] == "unsupported_attachment_format"
    assert attachment["childContainerId"] is None
    assert packet["roots"][0]["disposition"] == "requiresConfirmation"
    assert reconciliation.validate_packet_reconciliation(packet) == []
