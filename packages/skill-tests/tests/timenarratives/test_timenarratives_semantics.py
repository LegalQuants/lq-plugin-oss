"""Semantic graph and provenance gates for /timenarratives."""

from __future__ import annotations

import copy
import hashlib
import importlib
import sys
from pathlib import Path

import pytest
from test_timenarratives_contracts import make_confirmation, make_map, make_packet

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "skills" / "core" / "timenarratives" / "scripts"))

validate_map = importlib.import_module("map_semantics").validate_map
canonical_sha256 = importlib.import_module("canonical_json").canonical_sha256
build_packet = importlib.import_module("build_packet")
build_rendered = importlib.import_module("render_deliverable").build_rendered


def codes(result: dict) -> set[str]:
    return {issue["code"] for issue in result["faults"]}


def _compiled_note_map(tmp_path: Path) -> tuple[dict, dict]:
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
    packet = build_packet.compile_packet(request, tmp_path)
    mapping = make_map(packet)
    unit_id = packet["units"][0]["unitId"]
    mapping["unitAssessment"][0]["unitId"] = unit_id
    mapping["atoms"][0]["unitId"] = unit_id
    mapping["events"][0]["assertedBy"] = "Avery Example"
    return packet, mapping


def test_compiled_user_note_can_support_a_proposal_map(tmp_path: Path) -> None:
    packet, mapping = _compiled_note_map(tmp_path)
    assert packet["units"][0]["eligibility"] == "requires_confirmation"
    result = validate_map(packet, mapping)
    assert result["faults"] == []
    assert result["eventSupport"] == {"EVENT1": "user_attested"}


def test_compiled_user_note_still_requires_exact_final_confirmation(
    tmp_path: Path,
) -> None:
    packet, mapping = _compiled_note_map(tmp_path)
    absent = build_rendered(packet, mapping, {})
    assert absent["deliverable"] is None and absent["markdown"] is None
    confirmation = make_confirmation(packet, mapping)
    mapping["clauses"][0]["text"] = "Changed after confirmation."
    stale = build_rendered(packet, mapping, confirmation)
    assert stale["deliverable"] is None and stale["markdown"] is None
    assert "stale_map_confirmation" in codes(stale)


def test_documentary_requires_confirmation_unit_cannot_support_an_event() -> None:
    packet = make_packet()
    packet["units"][0]["eligibility"] = "requires_confirmation"
    packet.pop("packetDigestSha256")
    packet["packetDigestSha256"] = canonical_sha256(packet)
    mapping = make_map(packet)
    assert "ineligible_atom_unit" in codes(validate_map(packet, mapping))


def test_valid_documentary_map_derives_support_without_model_field() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    result = validate_map(packet, mapping)
    assert result["faults"] == []
    assert result["eventSupport"] == {"EVENT1": "documentary_supported"}
    assert "status" not in mapping and "supportClass" not in mapping["events"][0]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda value: value["events"].append(copy.deepcopy(value["events"][0])),
            "duplicate_id",
        ),
        (
            lambda value: value["events"][0].update(workstreamId="MISSING"),
            "unresolved_workstream",
        ),
        (
            lambda value: value["events"][0].update(performedByActorId="OTHER"),
            "wrong_performed_actor",
        ),
        (
            lambda value: value["events"][0].update(assertedBy="Unknown source"),
            "asserted_by_not_source_bound",
        ),
        (lambda value: value["events"][0].update(matterId="OTHER"), "wrong_matter"),
        (
            lambda value: value["clauses"][0].update(clauseOwnerActorId="OTHER"),
            "wrong_clause_owner",
        ),
        (
            lambda value: value["atoms"][0].update(components=["actor", "action"]),
            "missing_event_limb",
        ),
    ],
)
def test_graph_faults_fail_closed(mutate, expected: str) -> None:
    packet = make_packet()
    mapping = make_map(packet)
    mutate(mapping)
    assert expected in codes(validate_map(packet, mapping))


def test_unit_assessment_is_exact_partition_of_analyzable_units() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    mapping["unitAssessment"] = []
    assert "unit_partition" in codes(validate_map(packet, mapping))
    mapping["unitAssessment"] = [
        {
            "unitId": "C0001-U0001",
            "disposition": "read_but_unused",
            "reason": "not_relevant",
        }
    ]
    assert "atom_unit_not_used" in codes(validate_map(packet, mapping))


def test_duplicate_packet_unit_ids_are_rejected() -> None:
    packet = make_packet()
    packet["units"].append(copy.deepcopy(packet["units"][0]))
    packet.pop("packetDigestSha256")
    packet["packetDigestSha256"] = canonical_sha256(packet)
    mapping = make_map(packet)
    assert "duplicate_id" in codes(validate_map(packet, mapping))


def test_malformed_packet_unit_inventory_fails_closed_without_crashing() -> None:
    packet = make_packet()
    packet["units"] = None
    packet.pop("packetDigestSha256")
    packet["packetDigestSha256"] = canonical_sha256(packet)
    mapping = make_map()
    mapping["packetDigest"] = packet["packetDigestSha256"]
    assert "packet_structure" in codes(validate_map(packet, mapping))


def test_unit_and_map_graph_ids_cannot_collide() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    mapping["atoms"][0]["atomId"] = "C0001-U0001"
    mapping["events"][0]["atomIds"] = ["C0001-U0001"]
    assert "duplicate_id" in codes(validate_map(packet, mapping))


def test_packet_partition_must_close_before_receipt_can_claim_complete() -> None:
    packet = make_packet()
    packet["partitions"]["containers"]["ready"] = []
    packet.pop("packetDigestSha256")
    packet["packetDigestSha256"] = canonical_sha256(packet)
    mapping = make_map(packet)
    assert "packet_partition" in codes(validate_map(packet, mapping))


def test_selected_source_packet_without_authority_flag_validates() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    assert validate_map(packet, mapping)["faults"] == []


def test_needs_confirmation_requires_a_question_reason() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    mapping["atoms"] = []
    mapping["events"] = []
    mapping["workstreams"] = []
    mapping["clauses"] = []
    mapping["unitAssessment"][0].update(disposition="needs_confirmation", reason=None)
    assert "assessment_reason" in codes(validate_map(packet, mapping))


def test_utf8_byte_span_must_be_exact_decodable_and_hash_bound() -> None:
    packet = make_packet()
    encoded = "Émailed analysis".encode()
    packet["units"][0]["canonicalText"] = encoded.decode()
    packet["units"][0]["canonicalUtf8Sha256"] = hashlib.sha256(encoded).hexdigest()
    packet["units"][0]["utf8End"] = len(encoded)
    packet["budget"]["modelVisibleUtf8Bytes"] = len(encoded)
    packet.pop("packetDigestSha256")
    packet["packetDigestSha256"] = canonical_sha256(packet)
    mapping = make_map(packet)
    mapping["atoms"][0].update(startByte=1, endByte=5, spanSha256="0" * 64)
    result = validate_map(packet, mapping)
    assert {"atom_utf8_boundary", "atom_span_hash"} & codes(result)


def test_quoted_or_context_only_unit_cannot_support_an_event() -> None:
    packet = make_packet()
    packet["units"][0].update(role="quoted", eligibility="context_only")
    packet.pop("packetDigestSha256")
    packet["packetDigestSha256"] = canonical_sha256(packet)
    mapping = make_map(packet)
    assert "ineligible_atom_unit" in codes(validate_map(packet, mapping))


def test_user_attested_limb_prevents_documentary_promotion(tmp_path: Path) -> None:
    packet, mapping = _compiled_note_map(tmp_path)
    result = validate_map(packet, mapping)
    assert result["faults"] == []
    assert result["eventSupport"] == {"EVENT1": "user_attested"}


def test_user_attested_essential_limbs_downgrade_mixed_support(
    tmp_path: Path,
) -> None:
    packet, mapping = _compiled_note_map(tmp_path)
    template = make_packet()
    root = copy.deepcopy(template["roots"][0])
    root.update(rootId="S0002", selectionIndex=1, containerId="C0002")
    container = copy.deepcopy(template["containers"][0])
    container.update(containerId="C0002", rootId="S0002", originLocator="selection:1")
    unit = copy.deepcopy(template["units"][0])
    unit.update(unitId="C0002-U0001", containerId="C0002", originId="C0002")
    packet["roots"].append(root)
    packet["containers"].append(container)
    packet["units"].append(unit)
    packet["partitions"]["selectedRoots"]["ready"].append("S0002")
    packet["partitions"]["containers"]["ready"].append("C0002")
    packet["budget"]["modelVisibleUtf8Bytes"] += len(
        unit["canonicalText"].encode("utf-8")
    )
    packet["packetDigestSha256"] = canonical_sha256(
        {key: value for key, value in packet.items() if key != "packetDigestSha256"}
    )
    mapping["packetDigest"] = packet["packetDigestSha256"]
    mapping["unitAssessment"].append(
        {"unitId": "C0002-U0001", "disposition": "used", "reason": None}
    )
    mapping["atoms"][0]["components"] = ["actor", "action"]
    second_atom = copy.deepcopy(mapping["atoms"][0])
    raw = unit["canonicalText"].encode("utf-8")
    second_atom.update(
        atomId="ATOM2",
        unitId="C0002-U0001",
        endByte=len(raw),
        spanSha256=hashlib.sha256(raw).hexdigest(),
        components=["object", "matter"],
    )
    mapping["atoms"].append(second_atom)
    mapping["events"][0]["atomIds"].append("ATOM2")
    result = validate_map(packet, mapping)
    assert result["faults"] == []
    assert result["eventSupport"] == {"EVENT1": "user_attested"}


def test_user_attested_unit_must_be_bound_to_the_confirmed_actor(
    tmp_path: Path,
) -> None:
    packet, mapping = _compiled_note_map(tmp_path)
    packet["units"][0]["assertedByActorId"] = "OTHER"
    packet.pop("packetDigestSha256")
    packet["packetDigestSha256"] = canonical_sha256(packet)
    mapping["packetDigest"] = packet["packetDigestSha256"]
    assert "invalid_user_note_state" in codes(validate_map(packet, mapping))


def test_event_and_clause_membership_are_exactly_once() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    mapping["clauses"].append(
        {
            "clauseId": "CLAUSE2",
            "workstreamId": "WORK1",
            "clauseOwnerActorId": "ACTOR1",
            "eventIds": ["EVENT1"],
            "text": "Also prepared the claim analysis.",
        }
    )
    found = codes(validate_map(packet, mapping))
    assert "workstream_clause_count" in found
    assert "event_clause_count" in found
