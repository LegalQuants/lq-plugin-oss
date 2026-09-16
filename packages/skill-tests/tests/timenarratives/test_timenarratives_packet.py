from __future__ import annotations

import hashlib
import importlib
import json
import sys
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path

import pytest
from timenarratives_schema import (
    assert_published_schema_valid,
    published_schema_accepts,
)

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
SKILL_SCHEMAS = ROOT / "skills" / "core" / "timenarratives" / "schemas"
CONTRACT_SCHEMAS = ROOT / "packages" / "contracts" / "schemas"
sys.path.insert(0, str(SCRIPTS))


def packet_module():
    path = SCRIPTS / "build_packet.py"
    assert path.is_file(), "build_packet.py has not been implemented"
    return importlib.import_module("build_packet")


def request(selections: list[dict], **filter_overrides: object) -> dict:
    filters = {
        "sourceTypes": ["text", "email", "docx", "user_note"],
        "since": None,
        "until": None,
        "asOf": "2026-08-21T12:00:00+01:00",
    }
    filters.update(filter_overrides)
    return {
        "schemaVersion": "timenarratives.request.v1",
        "runId": "Run_001",
        "actor": {"id": "james", "name": "James Cockburn", "aliases": []},
        "matter": {"id": "M-100", "client": "Example Client", "aliases": []},
        "selections": selections,
        "filters": filters,
    }


def canonical_digest(value: dict) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _logical_lines(text: str) -> int:
    return sum(
        bool(line.strip()) and not line.lstrip().startswith("#")
        for line in text.splitlines()
    )


def _assert_schema_valid(tmp_path: Path, name: str, value: dict) -> None:
    del tmp_path
    assert_published_schema_valid(SKILL_SCHEMAS / name, value)


def test_legacy_authority_flag_is_optional_and_not_emitted(tmp_path: Path) -> None:
    packet = packet_module()
    value = request([{"kind": "user_note", "text": "Reviewed draft"}])
    value["authorityConfirmed"] = True

    result = packet.compile_packet(value, tmp_path)
    assert published_schema_accepts(
        SKILL_SCHEMAS / "timenarratives-request.schema.json", value
    )
    assert "authorityConfirmed" not in result


def test_legacy_authority_flag_rejects_false(tmp_path: Path) -> None:
    packet = packet_module()
    value = request([{"kind": "user_note", "text": "Reviewed draft"}])
    value["authorityConfirmed"] = False

    with pytest.raises(packet.PacketBuildError, match="authorityConfirmed"):
        packet.compile_packet(value, tmp_path)
    assert not published_schema_accepts(
        SKILL_SCHEMAS / "timenarratives-request.schema.json", value
    )


def test_explicit_order_is_preserved_and_user_note_requires_confirmation(
    tmp_path: Path,
) -> None:
    packet = packet_module()
    (tmp_path / "selected.txt").write_text("Drafted letter", encoding="utf-8")
    (tmp_path / "not-selected.txt").write_text("must not appear", encoding="utf-8")
    value = request(
        [
            {"kind": "file", "path": "selected.txt"},
            {"kind": "user_note", "text": "Discussed strategy by telephone"},
        ]
    )

    result = packet.compile_packet(value, tmp_path)

    assert [root["rootId"] for root in result["roots"]] == ["S0001", "S0002"]
    assert [root["kind"] for root in result["roots"]] == ["file", "user_note"]
    assert result["roots"][1]["disposition"] == "requiresConfirmation"
    note = next(unit for unit in result["units"] if unit["kind"] == "user_note")
    assert note["sourceClass"] == "user_attested"
    assert note["eligibility"] == "requires_confirmation"
    assert "not-selected.txt" not in json.dumps(result)
    assert result["status"] == "requires_confirmation"


def test_exact_duplicate_roots_remain_distinct_and_partitioned(tmp_path: Path) -> None:
    packet = packet_module()
    (tmp_path / "a.txt").write_text("same", encoding="utf-8")
    (tmp_path / "b.txt").write_text("same", encoding="utf-8")

    result = packet.compile_packet(
        request(
            [
                {"kind": "file", "path": "a.txt"},
                {"kind": "file", "path": "b.txt"},
            ]
        ),
        tmp_path,
    )

    assert len(result["roots"]) == 2
    assert result["containers"][0]["rawSha256"] == result["containers"][1]["rawSha256"]
    assert result["partitions"]["selectedRoots"]["ready"] == ["S0001"]
    assert result["partitions"]["selectedRoots"]["exactDuplicate"] == ["S0002"]
    assert result["partitions"]["containers"]["exactDuplicate"] == ["S0002"]
    assert {unit["containerId"] for unit in result["units"]} == {"S0001"}


def test_time_filter_uses_email_date_and_never_filesystem_time(tmp_path: Path) -> None:
    packet = packet_module()
    message = EmailMessage()
    message["From"] = "one@example.test"
    message["Date"] = "Thu, 20 Aug 2026 15:30:00 +0100"
    message.set_content("Email work")
    (tmp_path / "mail.eml").write_bytes(message.as_bytes(policy=SMTP))
    (tmp_path / "note.txt").write_text("Undated file", encoding="utf-8")
    value = request(
        [
            {"kind": "file", "path": "mail.eml"},
            {"kind": "file", "path": "note.txt"},
        ],
        since="2026-08-20T00:00:00+01:00",
        until="2026-08-20T23:59:59+01:00",
    )

    result = packet.compile_packet(value, tmp_path)

    assert result["containers"][0]["filterDisposition"] == "included"
    assert result["containers"][0]["sourceTimeKind"] == "eml_date"
    assert result["containers"][1]["sourceTime"] is None
    assert result["containers"][1]["filterDisposition"] == "filter_indeterminate"
    assert result["roots"][1]["disposition"] == "requiresConfirmation"


def test_missing_email_date_requires_confirmation_without_promoting_quotes(
    tmp_path: Path,
) -> None:
    packet = packet_module()
    message = EmailMessage()
    message["From"] = "one@example.test"
    message.set_content("Current work\n> Quoted history\n")
    (tmp_path / "undated.eml").write_bytes(message.as_bytes(policy=SMTP))

    result = packet.compile_packet(
        request(
            [{"kind": "file", "path": "undated.eml"}],
            since="2026-08-20T00:00:00+01:00",
            until="2026-08-20T23:59:59+01:00",
        ),
        tmp_path,
    )

    by_role = {unit["role"]: unit for unit in result["units"]}
    assert by_role["current"]["eligibility"] == "requires_confirmation"
    assert by_role["quoted"]["eligibility"] == "context_only"
    assert result["roots"][0]["reason"] == "source_time_missing"
    assert result["status"] == "requires_confirmation"


def test_divergent_email_alternatives_block_semantic_readiness(tmp_path: Path) -> None:
    packet = packet_module()
    message = EmailMessage()
    message["From"] = "one@example.test"
    message.set_content("Plain draft")
    message.add_alternative("<p>Different final text</p>", subtype="html")
    (tmp_path / "alternatives.eml").write_bytes(message.as_bytes(policy=SMTP))

    result = packet.compile_packet(
        request([{"kind": "file", "path": "alternatives.eml"}]), tmp_path
    )

    assert result["roots"][0]["disposition"] == "requiresConfirmation"
    assert result["containers"][0]["reason"] == "email_content_ambiguity"
    assert result["status"] == "requires_confirmation"


def test_source_type_filter_only_filters_selected_roots(tmp_path: Path) -> None:
    packet = packet_module()
    (tmp_path / "selected.txt").write_text("Text", encoding="utf-8")

    result = packet.compile_packet(
        request(
            [{"kind": "file", "path": "selected.txt"}],
            sourceTypes=["email"],
        ),
        tmp_path,
    )

    assert result["roots"][0]["disposition"] == "excluded"
    assert result["containers"][0]["reason"] == "source_type_filter"
    assert result["units"] == []


def test_model_budget_failure_keeps_all_text_and_refuses_readiness(
    tmp_path: Path,
) -> None:
    packet = packet_module()
    text = "x" * (300 * 1024 + 1)
    (tmp_path / "large.txt").write_text(text, encoding="utf-8")

    result = packet.compile_packet(
        request([{"kind": "file", "path": "large.txt"}]), tmp_path
    )

    reconstructed = "".join(unit["canonicalText"] for unit in result["units"])
    assert reconstructed == text
    assert result["budget"] == {
        "modelVisibleUtf8Bytes": 300 * 1024 + 1,
        "modelVisibleUtf8Limit": 300 * 1024,
        "withinLimit": False,
    }
    assert result["status"] == "incomplete"
    assert "model_visible_budget_exceeded" in result["errors"]


def test_packet_digests_use_canonical_full_sha256(tmp_path: Path) -> None:
    packet = packet_module()
    value = request([{"kind": "user_note", "text": "Call with client"}])

    result = packet.compile_packet(value, tmp_path)

    assert result["requestDigestSha256"] == canonical_digest(value)
    digest = result.pop("packetDigestSha256")
    assert digest == canonical_digest(result)
    assert len(digest) == 64


def test_skill_and_shared_contract_schemas_are_byte_identical() -> None:
    for name in (
        "timenarratives-request.schema.json",
        "timenarratives-packet.schema.json",
    ):
        skill = SKILL_SCHEMAS / name
        shared = CONTRACT_SCHEMAS / name
        assert skill.is_file(), f"missing {skill}"
        assert shared.is_file(), f"missing {shared}"
        assert skill.read_bytes() == shared.read_bytes()
        assert (
            json.loads(skill.read_text(encoding="utf-8"))["additionalProperties"]
            is False
        )


def test_compiled_request_and_packet_validate_against_strict_schemas(
    tmp_path: Path,
) -> None:
    value = request([{"kind": "user_note", "text": "Reviewed authorities"}])
    packet = packet_module().compile_packet(value, tmp_path)

    _assert_schema_valid(tmp_path, "timenarratives-request.schema.json", value)
    _assert_schema_valid(tmp_path, "timenarratives-packet.schema.json", packet)


def test_timenarratives_python_sources_stay_within_logical_line_cap() -> None:
    assert _logical_lines("# comment\n\nvalue = 1\n") == 1
    paths = sorted(SCRIPTS.glob("*.py")) + sorted(
        (ROOT / "packages/skill-tests/tests/timenarratives").glob("test_*.py")
    )
    over_limit = {
        str(path.relative_to(ROOT)): _logical_lines(path.read_text(encoding="utf-8"))
        for path in paths
        if _logical_lines(path.read_text(encoding="utf-8")) > 300
    }
    assert over_limit == {}


def test_compile_to_directory_writes_private_packet(tmp_path: Path) -> None:
    packet = packet_module()
    source_root = tmp_path / "source"
    source_root.mkdir()
    run_dir = tmp_path / "run"

    result = packet.compile_packet_to_directory(
        request([{"kind": "user_note", "text": "Reviewed authorities"}]),
        source_root,
        run_dir,
    )

    stored_path = run_dir / "artifacts" / "packet.private.json"
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    assert stored == result
    assert list(run_dir.iterdir()) == [run_dir / "artifacts"]
