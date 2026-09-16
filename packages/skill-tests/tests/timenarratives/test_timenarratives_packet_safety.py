"""Fail-closed packet validation and unsupported-source regressions."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))

build_packet = importlib.import_module("build_packet")
packet_core = importlib.import_module("packet_core")


def _request(selections: list[dict], **filters: object) -> dict:
    source_filters = {
        "sourceTypes": ["text", "email", "docx", "user_note"],
        "since": None,
        "until": None,
        "asOf": "2026-08-21T12:00:00+01:00",
    }
    source_filters.update(filters)
    return {
        "schemaVersion": "timenarratives.request.v1",
        "runId": "Run_Safety",
        "actor": {"id": "james", "name": "James Cockburn", "aliases": []},
        "matter": {"id": "M-100", "client": None, "aliases": []},
        "selections": selections,
        "filters": source_filters,
    }


@pytest.mark.parametrize("extension", ["msg", "pst"])
def test_unsupported_mail_containers_are_unreadable(
    tmp_path: Path, extension: str
) -> None:
    path = f"selected.{extension}"
    (tmp_path / path).write_bytes(b"unsupported selected bytes")

    result = build_packet.compile_packet(
        _request([{"kind": "file", "path": path}]), tmp_path
    )

    assert result["roots"][0]["disposition"] == "unreadable"
    assert result["containers"][0]["reason"] == "unsupported_format"
    assert "unsupported_format" in result["errors"]


def test_user_notes_obey_container_and_packet_byte_caps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(packet_core.LIMITS, "selectedContainerBytes", 5)
    monkeypatch.setitem(packet_core.LIMITS, "selectedPacketBytes", 8)

    result = build_packet.compile_packet(
        _request(
            [
                {"kind": "user_note", "text": "first"},
                {"kind": "user_note", "text": "other"},
                {"kind": "user_note", "text": "123456"},
            ]
        ),
        tmp_path,
    )

    assert result["roots"][1]["reason"] == "selected_packet_bytes_exceeded"
    assert result["roots"][2]["reason"] == "selected_container_bytes_exceeded"
    assert {unit["containerId"] for unit in result["units"]} == {"S0001"}


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"since": "2026-08-22T00:00:00+01:00"},
            "filters.since is after filters.asOf",
        ),
        (
            {"since": "2026-08-20 00:00:00+01:00"},
            "RFC3339",
        ),
    ],
)
def test_time_filters_reject_future_windows_and_non_rfc3339_forms(
    tmp_path: Path, overrides: dict, message: str
) -> None:
    value = _request([{"kind": "user_note", "text": "note"}], **overrides)

    with pytest.raises(build_packet.PacketBuildError, match=message):
        build_packet.compile_packet(value, tmp_path)
