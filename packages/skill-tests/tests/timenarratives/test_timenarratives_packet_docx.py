# ruff: noqa: E501 - synthetic OOXML is intentionally literal and inspectable
"""Packet-boundary integration for the strict DOCX parser contract."""

from __future__ import annotations

import hashlib
import importlib
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))

build_packet = importlib.import_module("build_packet")
docx_units = importlib.import_module("docx_units")


def _request(path: str = "selected.docx") -> dict:
    return {
        "schemaVersion": "timenarratives.request.v1",
        "runId": "Run_DOCX",
        "actor": {"id": "james", "name": "James Cockburn", "aliases": []},
        "matter": {"id": "M-100", "client": None, "aliases": []},
        "selections": [{"kind": "file", "path": path}],
        "filters": {
            "sourceTypes": ["docx"],
            "since": None,
            "until": None,
            "asOf": "2026-08-21T12:00:00+01:00",
        },
    }


def _part(index: int, name: str, unit_ids: list[str]) -> dict:
    return {
        "partId": f"S0001-P{index:04d}",
        "containerId": "S0001",
        "locator": f"docx:{name}",
        "mediaType": "application/xml",
        "rawSha256": hashlib.sha256(name.encode()).hexdigest(),
        "byteLength": 4,
        "role": "story",
        "unitIds": unit_ids,
        "disposition": "ready",
        "reason": None,
    }


def _unit(index: int, part_index: int, name: str, text: str) -> dict:
    return {
        "unitId": f"S0001-U{index:04d}",
        "containerId": "S0001",
        "originId": f"S0001-P{part_index:04d}",
        "kind": "docx_accepted",
        "role": "accepted",
        "locator": f"docx:{name}#body/p[1]",
        "canonicalText": text,
        "canonicalUtf8Sha256": hashlib.sha256(text.encode()).hexdigest(),
        "utf8Start": 0,
        "utf8End": len(text.encode()),
        "eligibility": "eligible",
        "coverageDisposition": "pending",
        "sourceClass": "documentary_supported",
        "sourceAuthor": None,
        "sourceTime": "2026-08-20T10:00:00Z",
        "assertedByActorId": None,
        "metadata": {"partName": name},
    }


def _aligned_result(
    status: str, reason: str | None = None, affected: list[str] | None = None
) -> dict:
    return {
        "disposition": status,
        "reason": reason,
        "sourceTime": "2026-08-20T10:00:00Z",
        "sourceTimeKind": "docx_core_modified",
        "sourceAuthor": None,
        "parts": [
            _part(1, "word/document.xml", ["S0001-U0001"]),
            _part(2, "word/footnotes.xml", ["S0001-U0002"]),
        ],
        "units": [
            _unit(1, 1, "word/document.xml", "Drafted pleading"),
            _unit(2, 2, "word/footnotes.xml", "Checked the authority"),
        ],
        "limitations": [],
        "notes": [],
        "affectedParts": affected or [],
    }


def _image_only_docx() -> bytes:
    content_types = """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>"""
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"""
    document = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:drawing/></w:r></w:p></w:body></w:document>"""
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/media/image1.png", b"PNG")
    return output.getvalue()


def test_adapter_preserves_aligned_parts_units_and_argument_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"PK\x03\x04selected-docx"
    (tmp_path / "selected.docx").write_bytes(raw)
    parsed = _aligned_result("ready")
    calls: list[tuple[bytes, str]] = []

    def parse_docx(data: bytes, container_id: str) -> dict:
        calls.append((data, container_id))
        return parsed

    monkeypatch.setattr(docx_units, "parse_docx", parse_docx)
    result = build_packet.compile_packet(_request(), tmp_path)

    assert calls == [(raw, "S0001")]
    assert result["parts"] == parsed["parts"]
    assert result["units"] == parsed["units"]


def test_genuine_image_only_docx_propagates_unreadable(tmp_path: Path) -> None:
    (tmp_path / "selected.docx").write_bytes(_image_only_docx())

    result = build_packet.compile_packet(_request(), tmp_path)

    assert result["roots"][0]["disposition"] == "unreadable"
    assert result["containers"][0]["disposition"] == "unreadable"
    assert result["containers"][0]["reason"] == "no_extractable_text"
    assert result["parts"]
    assert "docx_unreadable" in result["errors"]
    assert result["status"] == "incomplete"


def test_partial_docx_is_incomplete_and_requires_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "selected.docx").write_bytes(b"PK\x03\x04partial")
    monkeypatch.setattr(
        docx_units,
        "parse_docx",
        lambda _data, _container_id: _aligned_result(
            "partial", "unparsed_text_bearing_content", affected=["word/document.xml"]
        ),
    )

    result = build_packet.compile_packet(_request(), tmp_path)

    assert result["roots"][0]["disposition"] == "requiresConfirmation"
    assert result["containers"][0]["disposition"] == "requiresConfirmation"
    assert result["units"][0]["eligibility"] == "requires_confirmation"
    assert result["status"] == "incomplete"
    assert "docx_partial" in result["errors"]


def test_partial_docx_downgrades_only_units_in_affected_parts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "selected.docx").write_bytes(b"PK\x03\x04partial")
    parsed = _aligned_result(
        "partial", "unparsed_text_bearing_content", affected=["word/document.xml"]
    )
    monkeypatch.setattr(docx_units, "parse_docx", lambda _d, _c: parsed)

    result = build_packet.compile_packet(_request(), tmp_path)

    by_part = {u["metadata"]["partName"]: u["eligibility"] for u in result["units"]}
    assert by_part["word/document.xml"] == "requires_confirmation"
    assert by_part["word/footnotes.xml"] == "eligible"
    assert result["containers"][0]["disposition"] == "requiresConfirmation"
    assert result["containers"][0]["reason"] == "unparsed_text_bearing_content"
    assert "docx_partial" in result["errors"]


def test_ready_docx_with_notes_stays_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "selected.docx").write_bytes(b"PK\x03\x04noted")
    parsed = _aligned_result("ready")
    parsed["notes"] = ["image_not_ocr"]
    monkeypatch.setattr(docx_units, "parse_docx", lambda _d, _c: parsed)

    result = build_packet.compile_packet(_request(), tmp_path)

    assert result["containers"][0]["disposition"] == "ready"
    assert result["limitations"] == []
    assert all(u["eligibility"] == "eligible" for u in result["units"])
    assert result["status"] == "ready_for_semantic_analysis"


def test_parser_result_without_affected_parts_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "selected.docx").write_bytes(b"PK\x03\x04old")
    parsed = _aligned_result("ready")
    del parsed["affectedParts"]
    monkeypatch.setattr(docx_units, "parse_docx", lambda _d, _c: parsed)

    result = build_packet.compile_packet(_request(), tmp_path)

    assert result["roots"][0]["disposition"] == "unreadable"
    assert "docx_parser_status_invalid" in result["errors"]


def test_unknown_docx_parser_status_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "selected.docx").write_bytes(b"PK\x03\x04unknown")
    monkeypatch.setattr(
        docx_units,
        "parse_docx",
        lambda _data, _container_id: _aligned_result("read"),
    )

    result = build_packet.compile_packet(_request(), tmp_path)

    assert result["roots"][0]["disposition"] == "unreadable"
    assert result["parts"] == []
    assert result["units"] == []
    assert "docx_parser_status_invalid" in result["errors"]
