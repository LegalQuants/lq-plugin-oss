"""Event assertion provenance must bind the actor and action limbs."""

from __future__ import annotations

import copy
import hashlib
import importlib
import sys
from pathlib import Path

from test_timenarratives_contracts import make_map, make_packet

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "skills" / "core" / "timenarratives" / "scripts"))
packet_sha256 = importlib.import_module("canonical_json").packet_sha256
validate_map = importlib.import_module("map_semantics").validate_map


def _two_author_map() -> tuple[dict, dict]:
    packet = make_packet()
    text = "Another source corroborated the selected matter."
    encoded = text.encode("utf-8")
    unit = copy.deepcopy(packet["units"][0])
    unit.update(
        unitId="C0001-U0002",
        canonicalText=text,
        canonicalUtf8Sha256=hashlib.sha256(encoded).hexdigest(),
        utf8Start=0,
        utf8End=len(encoded),
        sourceAuthor="Ancillary Author",
    )
    packet["units"].append(unit)
    packet["budget"]["modelVisibleUtf8Bytes"] += len(encoded)
    packet["packetDigestSha256"] = packet_sha256(packet)
    mapping = make_map(packet)
    mapping["unitAssessment"].append(
        {"unitId": unit["unitId"], "disposition": "used", "reason": None}
    )
    atom = copy.deepcopy(mapping["atoms"][0])
    atom.update(
        atomId="ATOM2",
        unitId=unit["unitId"],
        startByte=0,
        endByte=len(encoded),
        spanSha256=hashlib.sha256(encoded).hexdigest(),
        components=["matter"],
    )
    mapping["atoms"].append(atom)
    mapping["events"][0]["atomIds"].append("ATOM2")
    return packet, mapping


def test_ancillary_atom_author_cannot_be_event_asserted_by() -> None:
    packet, mapping = _two_author_map()
    mapping["events"][0]["assertedBy"] = "Ancillary Author"
    result = validate_map(packet, mapping)
    assert "asserted_by_not_source_bound" in {
        fault["code"] for fault in result["faults"]
    }


def test_actor_and_action_from_asserted_author_allow_other_limb_corroboration() -> None:
    packet, mapping = _two_author_map()
    mapping["atoms"][0]["components"] = ["actor", "action", "object"]
    assert validate_map(packet, mapping)["faults"] == []
