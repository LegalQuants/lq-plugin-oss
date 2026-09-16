"""Digest-bound, session-recorded confirmation tests."""

from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

from test_timenarratives_contracts import make_confirmation, make_map, make_packet

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "skills" / "core" / "timenarratives" / "scripts"))
canonical_sha256 = importlib.import_module("canonical_json").canonical_sha256
validate_confirmation = importlib.import_module("map_semantics").validate_confirmation


def issue_codes(result: dict) -> set[str]:
    return {issue["code"] for issue in result["faults"]}


def test_exact_confirmation_passes_and_is_not_described_as_signature() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    confirmation = make_confirmation(packet, mapping)
    result = validate_confirmation(packet, mapping, confirmation)
    assert result["faults"] == []
    assert confirmation["recording"] == "session_recorded_user_confirmation"
    assert set(confirmation) == {
        "schemaVersion",
        "runId",
        "packetDigest",
        "mapDigest",
        "decision",
        "recording",
        "confirmationToken",
    }


def test_map_edit_invalidates_digest_and_token() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    confirmation = make_confirmation(packet, mapping)
    mapping["clauses"][0]["text"] = "Changed after confirmation."
    found = issue_codes(validate_confirmation(packet, mapping, confirmation))
    assert "stale_map_confirmation" in found
    assert "confirmation_token" in found


def test_packet_change_invalidates_confirmation() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    confirmation = make_confirmation(packet, mapping)
    changed = copy.deepcopy(packet)
    changed["units"][0]["canonicalText"] += " Removed source changed."
    changed.pop("packetDigestSha256")
    changed["packetDigestSha256"] = canonical_sha256(changed)
    found = issue_codes(validate_confirmation(changed, mapping, confirmation))
    assert "stale_packet_confirmation" in found


def test_wrong_recording_or_decision_is_rejected() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    confirmation = make_confirmation(packet, mapping)
    confirmation["recording"] = "cryptographic_signature"
    confirmation["decision"] = "rejected"
    found = issue_codes(validate_confirmation(packet, mapping, confirmation))
    assert {"confirmation_recording", "confirmation_decision"} <= found
