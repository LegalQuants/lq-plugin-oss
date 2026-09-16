"""anchor_map resolves quoted evidence to byte spans and validates in one pass."""

from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

from test_timenarratives_contracts import make_map, make_packet

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))
anchor_map = importlib.import_module("anchor_map")
validate_map = importlib.import_module("map_semantics").validate_map


def _draft(mapping: dict, packet: dict) -> dict:
    units = {unit["unitId"]: unit for unit in packet["units"]}
    draft = copy.deepcopy(mapping)
    for atom in draft["atoms"]:
        raw = units[atom["unitId"]]["canonicalText"].encode("utf-8")
        atom["quote"] = raw[atom["startByte"] : atom["endByte"]].decode("utf-8")
        for key in ("startByte", "endByte", "spanSha256"):
            del atom[key]
    return draft


def test_round_trip_reproduces_the_validated_map() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    assert validate_map(packet, mapping)["faults"] == []
    resolved, faults = anchor_map.resolve(packet, _draft(mapping, packet))
    assert faults == []
    assert resolved == mapping


def test_missing_quote_is_a_named_fault_with_context() -> None:
    packet = make_packet()
    draft = _draft(make_map(packet), packet)
    draft["atoms"][0]["quote"] = "text that is not in the unit"
    _resolved, faults = anchor_map.resolve(packet, draft)
    assert faults[0]["code"] == "quote_not_found"
    assert faults[0]["path"] == "$.atoms[0].quote"
    assert faults[0]["nearest"]


def test_ambiguous_quote_is_refused_not_guessed() -> None:
    packet = make_packet()
    packet["units"][0]["canonicalText"] = "same words. same words."
    draft = _draft(make_map(make_packet()), packet)
    draft["atoms"][0]["quote"] = "same words."
    _resolved, faults = anchor_map.resolve(packet, draft)
    assert faults[0]["code"] == "quote_ambiguous"


def test_absent_quote_field_is_a_named_fault() -> None:
    packet = make_packet()
    draft = _draft(make_map(packet), packet)
    del draft["atoms"][0]["quote"]
    _resolved, faults = anchor_map.resolve(packet, draft)
    assert faults[0]["code"] == "quote_missing"


def test_cli_writes_a_validated_map_and_never_replaces(tmp_path: Path) -> None:
    packet = make_packet()
    mapping = make_map(packet)
    (tmp_path / "packet.json").write_text(json.dumps(packet), encoding="utf-8")
    (tmp_path / "draft.json").write_text(
        json.dumps(_draft(mapping, packet)), encoding="utf-8"
    )
    source_root = tmp_path / "selected"
    source_root.mkdir()
    out = tmp_path / "map.json"

    def args(target: Path) -> list[str]:
        return [
            "--packet",
            str(tmp_path / "packet.json"),
            "--draft",
            str(tmp_path / "draft.json"),
            "--source-root",
            str(source_root),
            "--out",
            str(target),
        ]

    assert anchor_map.main(args(out)) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == mapping
    assert anchor_map.main(args(out)) == 2
    assert json.loads(out.read_text(encoding="utf-8")) == mapping
    assert anchor_map.main(args(source_root / "map.json")) == 2
    assert not (source_root / "map.json").exists()


def test_malformed_unit_id_is_a_fault_not_a_crash() -> None:
    packet = make_packet()
    draft = _draft(make_map(packet), packet)
    draft["atoms"][0]["unitId"] = ["x"]
    _resolved, faults = anchor_map.resolve(packet, draft)
    assert faults[0]["code"] == "unresolved_atom_unit"


def test_resolve_does_not_mutate_the_draft() -> None:
    packet = make_packet()
    draft = _draft(make_map(packet), packet)
    before = copy.deepcopy(draft)
    anchor_map.resolve(packet, draft)
    assert draft == before
