"""Shared fixtures and contract parity tests for /timenarratives v1."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from timenarratives_schema import published_schema_accepts as _schema_accepts

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))

canonical_sha256 = importlib.import_module("canonical_json").canonical_sha256
validate_structure = importlib.import_module("structural_contracts").validate_structure

SCHEMAS = ROOT / "skills" / "core" / "timenarratives" / "schemas"
CONTRACT_SCHEMAS = ROOT / "packages" / "contracts" / "schemas"

SCHEMA_NAMES = (
    "timenarratives-map.schema.json",
    "timenarratives-confirmation.schema.json",
    "timenarratives-deliverable.schema.json",
)


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_packet(*, source_class: str = "documentary_supported") -> dict[str, Any]:
    text = "Prepared claim analysis for Meridian."
    packet: dict[str, Any] = {
        "schemaVersion": "timenarratives.packet.v1",
        "runId": "run-001",
        "requestDigestSha256": "a" * 64,
        "actor": {"id": "ACTOR1", "name": "James Cockburn", "aliases": []},
        "matter": {"id": "MATTER1", "client": None, "aliases": []},
        "filters": {
            "sourceTypes": ["text"],
            "since": None,
            "until": None,
            "asOf": "2026-08-21T12:00:00Z",
        },
        "status": "ready_for_semantic_analysis",
        "limits": {
            "selectedRoots": 30,
            "selectedContainerBytes": 25 * 1024 * 1024,
            "selectedPacketBytes": 100 * 1024 * 1024,
            "derivedContainers": 100,
            "terminalUnits": 1000,
            "modelVisibleUtf8Bytes": 300 * 1024,
        },
        "roots": [
            {
                "rootId": "S0001",
                "selectionIndex": 0,
                "kind": "file",
                "selectedPath": "source.txt",
                "containerId": "C0001",
                "disposition": "ready",
                "reason": None,
            }
        ],
        "containers": [
            {
                "containerId": "C0001",
                "parentContainerId": None,
                "rootId": "S0001",
                "originLocator": "selection:0",
                "sourceType": "text"
                if source_class != "user_attested"
                else "user_note",
                "mediaType": "text/plain",
                "displayName": "source.txt",
                "byteLength": len(text.encode()),
                "rawSha256": _text_sha(text),
                "sourceTime": None,
                "sourceTimeKind": None,
                "filterDisposition": "included",
                "disposition": "ready",
                "reason": None,
                "sourceAuthor": "James Cockburn",
            }
        ],
        "mimeLeaves": [],
        "parts": [],
        "units": [
            {
                "unitId": "C0001-U0001",
                "containerId": "C0001",
                "originId": "C0001",
                "kind": "text_block"
                if source_class != "user_attested"
                else "user_note",
                "role": "current" if source_class != "user_attested" else "attested",
                "locator": "text:utf8:0-37",
                "canonicalText": text,
                "canonicalUtf8Sha256": _text_sha(text),
                "utf8Start": 0,
                "utf8End": len(text.encode()),
                "eligibility": "eligible",
                "coverageDisposition": "pending",
                "sourceClass": source_class,
                "sourceAuthor": "James Cockburn",
                "assertedByActorId": "ACTOR1"
                if source_class == "user_attested"
                else None,
                "sourceTime": None,
            }
        ],
        "partitions": {
            "selectedRoots": {
                "ready": ["S0001"],
                "requiresConfirmation": [],
                "exactDuplicate": [],
                "excluded": [],
                "unreadable": [],
                "expanded": [],
            },
            "containers": {
                "ready": ["C0001"],
                "requiresConfirmation": [],
                "exactDuplicate": [],
                "excluded": [],
                "unreadable": [],
                "expanded": [],
            },
            "mimeLeaves": {
                "ready": [],
                "requiresConfirmation": [],
                "exactDuplicate": [],
                "excluded": [],
                "unreadable": [],
                "expanded": [],
            },
            "parts": {
                "ready": [],
                "requiresConfirmation": [],
                "exactDuplicate": [],
                "excluded": [],
                "unreadable": [],
                "expanded": [],
            },
        },
        "budget": {
            "modelVisibleUtf8Bytes": len(text.encode()),
            "modelVisibleUtf8Limit": 300 * 1024,
            "withinLimit": True,
        },
        "errors": [],
        "limitations": [],
    }
    packet["packetDigestSha256"] = canonical_sha256(packet)
    return packet


def make_map(packet: dict[str, Any] | None = None) -> dict[str, Any]:
    packet = make_packet() if packet is None else packet
    text = packet["units"][0]["canonicalText"]
    raw = text.encode("utf-8")
    return {
        "schemaVersion": "timenarratives.map.v1",
        "runId": packet["runId"],
        "packetDigest": packet["packetDigestSha256"],
        "unitAssessment": [
            {"unitId": "C0001-U0001", "disposition": "used", "reason": None}
        ],
        "atoms": [
            {
                "atomId": "ATOM1",
                "unitId": "C0001-U0001",
                "startByte": 0,
                "endByte": len(raw),
                "spanSha256": hashlib.sha256(raw).hexdigest(),
                "components": ["actor", "action", "object", "matter"],
            }
        ],
        "events": [
            {
                "eventId": "EVENT1",
                "assertedBy": "James Cockburn",
                "performedByActorId": "ACTOR1",
                "namedTimekeeperActorId": "ACTOR1",
                "action": "Prepared",
                "object": "claim analysis",
                "purpose": None,
                "matterId": "MATTER1",
                "workstreamId": "WORK1",
                "atomIds": ["ATOM1"],
            }
        ],
        "workstreams": [
            {
                "workstreamId": "WORK1",
                "label": "Claim analysis",
                "category": "substantive",
            }
        ],
        "clauses": [
            {
                "clauseId": "CLAUSE1",
                "workstreamId": "WORK1",
                "clauseOwnerActorId": "ACTOR1",
                "eventIds": ["EVENT1"],
                "text": "Prepared claim analysis for the Meridian proceedings.",
            }
        ],
    }


def make_confirmation(
    packet: dict[str, Any], mapping: dict[str, Any]
) -> dict[str, Any]:
    digest = canonical_sha256(mapping)
    return {
        "schemaVersion": "timenarratives.confirmation.v1",
        "runId": packet["runId"],
        "packetDigest": packet["packetDigestSha256"],
        "mapDigest": digest,
        "decision": "confirmed",
        "recording": "session_recorded_user_confirmation",
        "confirmationToken": f"TN-{digest[:16]}",
    }


def schema_accepts(schema_name: str, instance: object) -> bool:
    return _schema_accepts(SCHEMAS / schema_name, instance)


def test_contract_copies_are_byte_equal_and_strict() -> None:
    for name in SCHEMA_NAMES:
        skill_schema = SCHEMAS / name
        contract_schema = CONTRACT_SCHEMAS / name
        assert skill_schema.read_bytes() == contract_schema.read_bytes()
        schema = json.loads(skill_schema.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["additionalProperties"] is False


def test_map_schema_and_python_contract_accept_the_same_fixture() -> None:
    mapping = make_map()
    assert schema_accepts("timenarratives-map.schema.json", mapping)
    assert validate_structure("map", mapping) == []


def test_schema_and_python_contract_both_reject_unknown_and_missing_fields() -> None:
    for mutation in ("unknown", "missing"):
        mapping = make_map()
        if mutation == "unknown":
            mapping["status"] = "ready"
        else:
            del mapping["unitAssessment"]
        assert not schema_accepts("timenarratives-map.schema.json", mapping)
        assert validate_structure("map", mapping)


def test_schema_one_of_still_enforces_sibling_required_fields() -> None:
    mapping = make_map()
    del mapping["unitAssessment"][0]["unitId"]
    assert not schema_accepts("timenarratives-map.schema.json", mapping)
    assert validate_structure("map", mapping)


def test_map_python_contract_rejects_non_string_components_without_crashing() -> None:
    mapping = make_map()
    mapping["atoms"][0]["components"] = [{}]
    assert not schema_accepts("timenarratives-map.schema.json", mapping)
    assert validate_structure("map", mapping)


def test_map_python_contract_does_not_treat_boolean_as_integer() -> None:
    mapping = make_map()
    mapping["atoms"][0]["startByte"] = True
    assert not schema_accepts("timenarratives-map.schema.json", mapping)
    assert validate_structure("map", mapping)


@pytest.mark.parametrize(
    ("section", "field", "length"),
    [
        ("events", "assertedBy", 201),
        ("events", "action", 301),
        ("events", "object", 301),
        ("events", "purpose", 501),
        ("workstreams", "label", 161),
    ],
)
def test_map_python_contract_matches_schema_text_bounds(
    section: str, field: str, length: int
) -> None:
    mapping = make_map()
    mapping[section][0][field] = "x" * length
    assert not schema_accepts("timenarratives-map.schema.json", mapping)
    assert validate_structure("map", mapping)


def test_confirmation_contract_is_closed() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    confirmation = make_confirmation(packet, mapping)
    assert schema_accepts("timenarratives-confirmation.schema.json", confirmation)
    assert validate_structure("confirmation", confirmation) == []
    bad = copy.deepcopy(confirmation)
    bad["signature"] = "not-a-signature"
    assert not schema_accepts("timenarratives-confirmation.schema.json", bad)
    assert validate_structure("confirmation", bad)
