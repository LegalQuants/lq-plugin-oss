"""Terminal unit receipt coverage and confirmed-attestation status."""

from __future__ import annotations

import copy
import hashlib
import importlib
import sys
from pathlib import Path

from test_timenarratives_attestation_state import compiled_note, note_map
from test_timenarratives_contracts import (
    make_confirmation,
    make_map,
    make_packet,
    schema_accepts,
)

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))
packet_sha256 = importlib.import_module("canonical_json").packet_sha256
build_rendered = importlib.import_module("render_deliverable").build_rendered
validate_structure = importlib.import_module("structural_contracts").validate_structure


def test_context_only_unit_is_terminally_accounted_by_safe_id() -> None:
    packet = make_packet()
    text = "Quoted context retained only for packet reconciliation."
    encoded = text.encode("utf-8")
    unit = copy.deepcopy(packet["units"][0])
    unit.update(
        unitId="C0001-U0002",
        canonicalText=text,
        canonicalUtf8Sha256=hashlib.sha256(encoded).hexdigest(),
        utf8Start=0,
        utf8End=len(encoded),
        role="quoted",
        eligibility="context_only",
        sourceAuthor="Context Author",
    )
    packet["units"].append(unit)
    packet["budget"]["modelVisibleUtf8Bytes"] += len(encoded)
    packet["packetDigestSha256"] = packet_sha256(packet)
    mapping = make_map(packet)
    confirmation = make_confirmation(packet, mapping)
    result = build_rendered(packet, mapping, confirmation)
    assert result["faults"] == []
    deliverable = result["deliverable"]
    assert deliverable["receipt"]["counts"]["accountedUnits"] == 2
    assert {
        (row["itemType"], row["itemId"], row["disposition"], row["reason"])
        for row in deliverable["receipt"]["exceptionLedger"]
    } == {("unit", "C0001-U0002", "context_only", "context_only")}
    assert schema_accepts("timenarratives-deliverable.schema.json", deliverable)
    assert validate_structure("deliverable", deliverable) == []


def test_ineligible_unit_reconciles_from_map_through_render() -> None:
    packet = make_packet()
    text = "DATE"
    encoded = text.encode("utf-8")
    unit = copy.deepcopy(packet["units"][0])
    unit.update(
        unitId="C0001-U0002",
        originId="C0001-P0001",
        kind="docx_annotation",
        role="context",
        locator="docx:word/document.xml#field-instruction[1]",
        canonicalText=text,
        canonicalUtf8Sha256=hashlib.sha256(encoded).hexdigest(),
        utf8Start=0,
        utf8End=len(encoded),
        eligibility="ineligible",
        sourceAuthor=None,
        metadata={
            "partName": "word/document.xml",
            "fieldInstructions": "DATE",
        },
    )
    packet["parts"].append(
        {
            "partId": "C0001-P0001",
            "containerId": "C0001",
            "locator": "docx:word/document.xml",
            "mediaType": "application/xml",
            "rawSha256": hashlib.sha256(b"synthetic part").hexdigest(),
            "byteLength": len(b"synthetic part"),
            "role": "story",
            "unitIds": [unit["unitId"]],
            "disposition": "ready",
            "reason": None,
        }
    )
    packet["partitions"]["parts"]["ready"].append("C0001-P0001")
    packet["units"].append(unit)
    packet["budget"]["modelVisibleUtf8Bytes"] += len(encoded)
    packet["packetDigestSha256"] = packet_sha256(packet)
    mapping = make_map(packet)

    result = build_rendered(packet, mapping, make_confirmation(packet, mapping))

    assert result["faults"] == []
    deliverable = result["deliverable"]
    assert deliverable["receipt"]["counts"]["accountedUnits"] == 2
    assert {
        (row["itemType"], row["itemId"], row["disposition"], row["reason"])
        for row in deliverable["receipt"]["exceptionLedger"]
    } == {("unit", "C0001-U0002", "ineligible", "ineligible")}
    assert schema_accepts("timenarratives-deliverable.schema.json", deliverable)
    assert validate_structure("deliverable", deliverable) == []


def test_receipt_rejects_false_terminal_unit_arithmetic() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    result = build_rendered(packet, mapping, make_confirmation(packet, mapping))
    deliverable = result["deliverable"]
    deliverable["receipt"]["counts"]["accountedUnits"] = 0
    assert "receipt_arithmetic" in {
        fault["code"] for fault in validate_structure("deliverable", deliverable)
    }


def test_confirmed_note_only_run_is_ready_and_attestation_stays_distinct(
    tmp_path: Path,
) -> None:
    packet = compiled_note(tmp_path)
    mapping = note_map(packet)
    result = build_rendered(packet, mapping, make_confirmation(packet, mapping))
    assert result["faults"] == []
    deliverable = result["deliverable"]
    assert deliverable["status"] == "ready_for_user_review"
    assert deliverable["checkQuestions"] == []
    assert deliverable["receipt"]["supportCounts"] == {
        "documentarySupported": 0,
        "userAttested": 1,
    }
    assert {
        (row["itemType"], row["disposition"], row["reason"])
        for row in deliverable["receipt"]["exceptionLedger"]
    } == {
        ("root", "attestation_confirmed", "user_attestation"),
        ("container", "attestation_confirmed", "user_attestation"),
    }
    assert packet["units"][0]["sourceClass"] == "user_attested"


def test_documentary_confirmation_ambiguity_remains_incomplete() -> None:
    packet = make_packet()
    packet["status"] = "requires_confirmation"
    packet["roots"][0].update(
        disposition="requiresConfirmation", reason="email_content_ambiguity"
    )
    packet["containers"][0].update(
        disposition="requiresConfirmation", reason="email_content_ambiguity"
    )
    packet["units"][0]["eligibility"] = "requires_confirmation"
    for partition in ("selectedRoots", "containers"):
        identifier = packet["partitions"][partition]["ready"].pop()
        packet["partitions"][partition]["requiresConfirmation"].append(identifier)
    packet["packetDigestSha256"] = packet_sha256(packet)
    mapping = make_map(packet)
    mapping["unitAssessment"][0].update(
        disposition="needs_confirmation", reason="actor_unclear"
    )
    for field in ("atoms", "events", "workstreams", "clauses"):
        mapping[field] = []
    result = build_rendered(packet, mapping, make_confirmation(packet, mapping))
    assert result["faults"] == []
    deliverable = result["deliverable"]
    assert deliverable["status"] == "incomplete"
    assert any(
        row["disposition"] == "requiresConfirmation"
        for row in deliverable["receipt"]["exceptionLedger"]
    )
