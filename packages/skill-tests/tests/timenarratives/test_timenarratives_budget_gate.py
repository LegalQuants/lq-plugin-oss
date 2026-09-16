"""Semantic refusal of breached compiler caps without blocking partial sources."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_timenarratives_contracts import make_confirmation, make_map, make_packet

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
VALIDATOR = SCRIPTS / "validate_map.py"
RENDERER = SCRIPTS / "render_deliverable.py"
sys.path.insert(0, str(SCRIPTS))
canonical_sha256 = importlib.import_module("canonical_json").canonical_sha256
validate_map = importlib.import_module("map_semantics").validate_map
build_rendered = importlib.import_module("render_deliverable").build_rendered

CAP_ERRORS = [
    "selected_container_bytes_exceeded",
    "selected_packet_bytes_exceeded",
    "derived_container_cap_exceeded",
    "terminal_unit_cap_exceeded",
    "model_visible_budget_exceeded",
]


def _rebind(packet: dict, mapping: dict) -> None:
    packet.pop("packetDigestSha256")
    packet["packetDigestSha256"] = canonical_sha256(packet)
    mapping["packetDigest"] = packet["packetDigestSha256"]


def _codes(result: dict) -> set[str]:
    return {fault["code"] for fault in result["faults"]}


def test_false_model_budget_refuses_semantic_use_with_rebound_digest() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    packet["limits"]["modelVisibleUtf8Bytes"] = 1
    packet["budget"].update(modelVisibleUtf8Limit=1, withinLimit=False)
    packet["status"] = "incomplete"
    _rebind(packet, mapping)
    assert "packet_budget_exceeded" in _codes(validate_map(packet, mapping))
    confirmation = make_confirmation(packet, mapping)
    rendered = build_rendered(packet, mapping, confirmation)
    assert rendered["deliverable"] is None and rendered["markdown"] is None


@pytest.mark.parametrize("error", CAP_ERRORS)
def test_every_compiler_cap_error_refuses_semantic_use(error: str) -> None:
    packet = make_packet()
    mapping = make_map(packet)
    packet["errors"] = [error]
    packet["status"] = "incomplete"
    _rebind(packet, mapping)
    assert "packet_cap_exceeded" in _codes(validate_map(packet, mapping))


def _with_ordinary_unreadable_source() -> tuple[dict, dict]:
    packet = make_packet()
    packet["roots"].append(
        {
            "rootId": "S0002",
            "selectionIndex": 1,
            "kind": "file",
            "selectedPath": "unreadable.txt",
            "containerId": "C0002",
            "disposition": "unreadable",
            "reason": "SourceReadError",
        }
    )
    packet["containers"].append(
        {
            "containerId": "C0002",
            "parentContainerId": None,
            "rootId": "S0002",
            "originLocator": "selection",
            "sourceType": "text",
            "mediaType": "text/plain",
            "displayName": "unreadable.txt",
            "byteLength": None,
            "rawSha256": None,
            "sourceTime": None,
            "sourceTimeKind": None,
            "filterDisposition": "included",
            "disposition": "unreadable",
            "reason": "SourceReadError",
            "sourceAuthor": None,
        }
    )
    packet["partitions"]["selectedRoots"]["unreadable"].append("S0002")
    packet["partitions"]["containers"]["unreadable"].append("C0002")
    packet["errors"] = ["selected_source_unreadable"]
    packet["status"] = "incomplete"
    mapping = make_map(packet)
    _rebind(packet, mapping)
    return packet, mapping


def test_ordinary_unreadable_source_allows_partial_output() -> None:
    packet, mapping = _with_ordinary_unreadable_source()
    assert validate_map(packet, mapping)["faults"] == []
    confirmation = make_confirmation(packet, mapping)
    result = build_rendered(packet, mapping, confirmation)
    assert result["faults"] == []
    assert result["deliverable"]["status"] == "partial_withheld"


def test_cap_fault_clis_write_no_validation_or_render_artifacts(
    tmp_path: Path,
) -> None:
    packet = make_packet()
    mapping = make_map(packet)
    packet["errors"] = ["terminal_unit_cap_exceeded"]
    packet["status"] = "incomplete"
    _rebind(packet, mapping)
    confirmation = make_confirmation(packet, mapping)
    paths = {}
    for name, value in (
        ("packet", packet),
        ("map", mapping),
        ("confirmation", confirmation),
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        paths[name] = path
    validation = tmp_path / "validation.json"
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    output_dir = tmp_path / "output"
    validator = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--packet",
            str(paths["packet"]),
            "--map",
            str(paths["map"]),
            "--out",
            str(validation),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    renderer = subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            "--request",
            str(request),
            "--source-root",
            str(tmp_path),
            "--packet",
            str(paths["packet"]),
            "--map",
            str(paths["map"]),
            "--confirmation",
            str(paths["confirmation"]),
            "--out-dir",
            str(output_dir),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    assert validator.returncode == renderer.returncode == 1
    assert "packet_cap_exceeded" in {
        fault["code"] for fault in json.loads(validator.stdout)["faults"]
    }
    assert not validation.exists() and not output_dir.exists()
