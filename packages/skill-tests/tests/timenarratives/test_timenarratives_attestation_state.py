"""Compiler-authored user-note state and transition invariants."""

from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

import pytest
from test_timenarratives_contracts import make_map, make_packet

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))
build_packet = importlib.import_module("build_packet")
packet_sha256 = importlib.import_module("canonical_json").packet_sha256
validate_boundary = importlib.import_module(
    "structural_contracts"
).validate_packet_semantic_boundary
validate_map = importlib.import_module("map_semantics").validate_map


def compiled_note(tmp_path: Path) -> dict:
    request = {
        "schemaVersion": "timenarratives.request.v1",
        "runId": "run-001",
        "actor": {"id": "ACTOR1", "name": "Avery Example", "aliases": []},
        "matter": {
            "id": "MATTER1",
            "client": "Synthetic Client",
            "aliases": [],
        },
        "selections": [
            {
                "kind": "user_note",
                "text": "Avery Example analysed the synthetic issue for MATTER1.",
            }
        ],
        "filters": {
            "sourceTypes": ["user_note"],
            "since": None,
            "until": None,
            "asOf": "2026-08-21T12:00:00+01:00",
        },
    }
    return build_packet.compile_packet(request, tmp_path)


def test_user_note_with_time_filter_is_refused_at_intake(tmp_path: Path) -> None:
    request = {
        "schemaVersion": "timenarratives.request.v1",
        "runId": "run-001",
        "actor": {"id": "ACTOR1", "name": "Avery Example", "aliases": []},
        "matter": {"id": "MATTER1", "client": "Synthetic Client", "aliases": []},
        "selections": [{"kind": "user_note", "text": "Reviewed the draft."}],
        "filters": {
            "sourceTypes": ["user_note"],
            "since": "2026-08-21T09:00:00+01:00",
            "until": None,
            "asOf": "2026-08-21T12:00:00+01:00",
        },
    }

    with pytest.raises(
        build_packet.PacketBuildError,
        match="user_note selections cannot be combined with time filters",
    ):
        build_packet.compile_packet(request, tmp_path)


def note_map(packet: dict) -> dict:
    mapping = make_map(packet)
    unit = packet["units"][0]
    mapping["unitAssessment"][0]["unitId"] = unit["unitId"]
    mapping["atoms"][0]["unitId"] = unit["unitId"]
    mapping["events"][0]["assertedBy"] = unit["sourceAuthor"]
    return mapping


def _rebind(packet: dict) -> None:
    packet["packetDigestSha256"] = packet_sha256(packet)


def _codes(packet: dict) -> set[str]:
    return {fault["code"] for fault in validate_boundary(packet)}


def test_real_compiler_note_has_the_only_valid_pre_map_attestation_state(
    tmp_path: Path,
) -> None:
    packet = compiled_note(tmp_path)
    assert validate_boundary(packet) == []
    unit = packet["units"][0]
    assert (
        unit["kind"],
        unit["sourceClass"],
        unit["role"],
        unit["eligibility"],
        unit["assertedByActorId"],
        unit["sourceAuthor"],
    ) == (
        "user_note",
        "user_attested",
        "attested",
        "requires_confirmation",
        packet["actor"]["id"],
        packet["actor"]["name"],
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda packet: packet["units"][0].update(eligibility="eligible"),
        lambda packet: packet["units"][0].update(sourceClass="documentary_supported"),
        lambda packet: packet["units"][0].update(role="current"),
        lambda packet: packet["units"][0].update(kind="text_block"),
        lambda packet: packet["units"][0].update(assertedByActorId="OTHER"),
        lambda packet: packet["units"][0].update(sourceAuthor="Other Person"),
        lambda packet: packet["containers"][0].update(sourceAuthor="Avery Example"),
        lambda packet: packet["containers"][0].update(sourceType="text"),
        lambda packet: packet["roots"][0].update(
            kind="file", selectedPath="fabricated.txt"
        ),
    ],
)
def test_rehashed_note_state_relabelling_is_refused(tmp_path: Path, mutation) -> None:
    packet = compiled_note(tmp_path)
    mutation(packet)
    _rebind(packet)
    assert "invalid_user_note_state" in _codes(packet)
    mapping = note_map(packet)
    assert "invalid_user_note_state" in {
        fault["code"] for fault in validate_map(packet, mapping)["faults"]
    }


def test_documentary_unit_cannot_be_relabelled_user_attested() -> None:
    packet = make_packet()
    packet["units"][0].update(
        sourceClass="user_attested",
        assertedByActorId=packet["actor"]["id"],
    )
    _rebind(packet)
    assert "invalid_user_note_state" in _codes(packet)


def test_validation_never_promotes_or_changes_source_class(tmp_path: Path) -> None:
    packet = compiled_note(tmp_path)
    before = copy.deepcopy(packet)
    assert validate_map(packet, note_map(packet))["faults"] == []
    assert packet == before
