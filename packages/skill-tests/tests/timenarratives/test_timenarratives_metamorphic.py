"""Bounded metamorphic integrity controls."""

from __future__ import annotations

import copy
import hashlib
import importlib
import sys
from pathlib import Path

from test_timenarratives_contracts import make_confirmation, make_map, make_packet

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "skills" / "core" / "timenarratives" / "scripts"))
canonical_sha256 = importlib.import_module("canonical_json").canonical_sha256
_semantics = importlib.import_module("map_semantics")
validate_confirmation = _semantics.validate_confirmation
validate_map = _semantics.validate_map


def test_source_removal_changes_packet_identity_and_stales_old_confirmation() -> None:
    packet = make_packet()
    second_text = "Prepared a separate synthetic note."
    second_root = copy.deepcopy(packet["roots"][0])
    second_root.update(
        rootId="S0002",
        selectionIndex=1,
        selectedPath="second.txt",
        containerId="C0002",
    )
    packet["roots"].append(second_root)
    second_container = copy.deepcopy(packet["containers"][0])
    second_container.update(
        containerId="C0002",
        rootId="S0002",
        originLocator="selection:1",
        displayName="second.txt",
        byteLength=len(second_text.encode()),
        rawSha256=hashlib.sha256(second_text.encode()).hexdigest(),
    )
    packet["containers"].append(second_container)
    second_unit = copy.deepcopy(packet["units"][0])
    second_unit.update(
        unitId="C0002-U0001",
        containerId="C0002",
        originId="C0002",
        locator=f"text:utf8:0-{len(second_text.encode())}",
        canonicalText=second_text,
        canonicalUtf8Sha256=hashlib.sha256(second_text.encode()).hexdigest(),
        utf8End=len(second_text.encode()),
    )
    packet["units"].append(second_unit)
    packet["partitions"]["selectedRoots"]["ready"].append("S0002")
    packet["partitions"]["containers"]["ready"].append("C0002")
    packet["budget"]["modelVisibleUtf8Bytes"] += len(second_text.encode())
    packet.pop("packetDigestSha256")
    packet["packetDigestSha256"] = canonical_sha256(packet)
    mapping = make_map(packet)
    mapping["unitAssessment"].append(
        {"unitId": "C0002-U0001", "disposition": "read_but_unused", "reason": None}
    )
    confirmation = make_confirmation(packet, mapping)
    removed = copy.deepcopy(packet)
    removed["units"] = removed["units"][:1]
    removed["containers"] = removed["containers"][:1]
    removed["roots"] = removed["roots"][:1]
    removed["partitions"]["selectedRoots"]["ready"] = ["S0001"]
    removed["partitions"]["containers"]["ready"] = ["C0001"]
    removed["budget"]["modelVisibleUtf8Bytes"] -= len(second_text.encode())
    removed.pop("packetDigestSha256")
    removed["packetDigestSha256"] = canonical_sha256(removed)
    assert removed["packetDigestSha256"] != packet["packetDigestSha256"]
    remapped = copy.deepcopy(mapping)
    remapped["packetDigest"] = removed["packetDigestSha256"]
    remapped["unitAssessment"] = remapped["unitAssessment"][:1]
    remap_result = validate_map(removed, remapped)
    assert remap_result["faults"] == []
    assert remap_result["mapDigest"] != confirmation["mapDigest"]
    result = validate_confirmation(removed, mapping, confirmation)
    assert {issue["code"] for issue in result["faults"]} >= {
        "stale_packet_confirmation"
    }


def test_source_reordering_changes_packet_digest_and_never_reuses_confirmation() -> (
    None
):
    packet = make_packet()
    second = copy.deepcopy(packet["units"][0])
    second["unitId"] = "C0001-U0002"
    packet["units"].append(second)
    packet.pop("packetDigestSha256")
    packet["packetDigestSha256"] = canonical_sha256(packet)
    mapping = make_map(packet)
    mapping["unitAssessment"].append(
        {"unitId": second["unitId"], "disposition": "read_but_unused", "reason": None}
    )
    confirmation = make_confirmation(packet, mapping)
    reordered = copy.deepcopy(packet)
    reordered["units"].reverse()
    reordered.pop("packetDigestSha256")
    reordered["packetDigestSha256"] = canonical_sha256(reordered)
    result = validate_confirmation(reordered, mapping, confirmation)
    assert "stale_packet_confirmation" in {issue["code"] for issue in result["faults"]}


def test_canonical_object_key_order_does_not_change_digest() -> None:
    mapping = make_map()
    reordered = {key: mapping[key] for key in reversed(mapping)}
    assert canonical_sha256(reordered) == canonical_sha256(mapping)
