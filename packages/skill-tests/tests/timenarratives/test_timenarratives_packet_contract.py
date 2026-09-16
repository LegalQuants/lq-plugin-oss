"""Packet JSON Schema/manual trust-boundary parity tests."""

from __future__ import annotations

import copy
import hashlib
import importlib
import sys
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path

import pytest
from test_timenarratives_contracts import make_confirmation, make_map
from timenarratives_schema import published_schema_accepts

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
SCHEMA = (
    ROOT
    / "skills"
    / "core"
    / "timenarratives"
    / "schemas"
    / "timenarratives-packet.schema.json"
)
sys.path.insert(0, str(SCRIPTS))
build_packet = importlib.import_module("build_packet")
canonical_sha256 = importlib.import_module("canonical_json").canonical_sha256
validate_map = importlib.import_module("map_semantics").validate_map
build_rendered = importlib.import_module("render_deliverable").build_rendered
validate_schema_subset = importlib.import_module("schema_subset").validate_schema_subset
validate_packet_semantic_boundary = importlib.import_module(
    "structural_contracts"
).validate_packet_semantic_boundary


def _compiled_note_map(tmp_path: Path) -> tuple[dict, dict]:
    request = {
        "schemaVersion": "timenarratives.request.v1",
        "runId": "run-packet-contract",
        "actor": {"id": "ACTOR1", "name": "Avery Example", "aliases": []},
        "matter": {
            "id": "MATTER1",
            "client": "Synthetic Client",
            "aliases": [],
        },
        "selections": [{"kind": "user_note", "text": "Analysed synthetic issue."}],
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


def _edge_packet() -> tuple[dict, dict]:
    from test_timenarratives_contracts import make_packet

    packet = make_packet()
    text = packet["units"][0]["canonicalText"]
    packet["mimeLeaves"] = [
        {
            "mimeLeafId": "MIME1",
            "containerId": "C0001",
            "locator": "mime:body",
            "parentLocator": None,
            "contentType": "text/plain",
            "contentDisposition": None,
            "filename": None,
            "contentId": None,
            "payloadSha256": hashlib.sha256(text.encode()).hexdigest(),
            "byteLength": len(text.encode()),
            "role": "current",
            "childContainerId": None,
            "disposition": "ready",
            "reason": None,
            "sourceAuthor": "James Cockburn",
        },
        {
            "mimeLeafId": "MIME2",
            "containerId": "C0001",
            "locator": "mime:attachment",
            "parentLocator": None,
            "contentType": "text/plain",
            "contentDisposition": "attachment",
            "filename": "synthetic.txt",
            "contentId": None,
            "payloadSha256": hashlib.sha256(b"derived").hexdigest(),
            "byteLength": 7,
            "role": "attachment",
            "childContainerId": "C0002",
            "disposition": "expanded",
            "reason": None,
            "sourceAuthor": "James Cockburn",
        },
    ]
    derived = copy.deepcopy(packet["containers"][0])
    derived.update(
        containerId="C0002",
        parentContainerId="C0001",
        originLocator="mime:attachment",
        displayName="synthetic.txt",
        byteLength=7,
        rawSha256=hashlib.sha256(b"derived").hexdigest(),
    )
    packet["containers"].append(derived)
    packet["parts"] = [
        {
            "partId": "PART1",
            "containerId": "C0001",
            "locator": "package:metadata",
            "mediaType": "application/xml",
            "rawSha256": hashlib.sha256(b"").hexdigest(),
            "byteLength": 0,
            "role": "structural",
            "unitIds": [],
            "disposition": "ready",
            "reason": None,
        }
    ]
    packet["units"][0]["originId"] = "MIME1"
    packet["partitions"]["containers"]["ready"].append("C0002")
    packet["partitions"]["mimeLeaves"]["ready"] = ["MIME1"]
    packet["partitions"]["mimeLeaves"]["expanded"] = ["MIME2"]
    packet["partitions"]["parts"]["ready"] = ["PART1"]
    packet.pop("packetDigestSha256")
    packet["packetDigestSha256"] = canonical_sha256(packet)
    return packet, make_map(packet)


def _duplicate(packet: dict, field: str, partition: str) -> None:
    packet[field].append(copy.deepcopy(packet[field][0]))
    disposition = packet[field][0]["disposition"]
    identifier = {
        "roots": "rootId",
        "containers": "containerId",
        "mimeLeaves": "mimeLeafId",
        "parts": "partId",
    }[field]
    packet["partitions"][partition][disposition].append(packet[field][0][identifier])


def _unlink_derived(packet: dict) -> None:
    leaf = packet["mimeLeaves"][1]
    leaf.update(childContainerId=None, disposition="ready")
    packet["partitions"]["mimeLeaves"]["expanded"] = []
    packet["partitions"]["mimeLeaves"]["ready"].append("MIME2")


PROVENANCE_MUTATIONS = [
    pytest.param(lambda p: _duplicate(p, "roots", "selectedRoots"), id="root-id"),
    pytest.param(
        lambda p: _duplicate(p, "containers", "containers"), id="container-id"
    ),
    pytest.param(lambda p: _duplicate(p, "mimeLeaves", "mimeLeaves"), id="mime-id"),
    pytest.param(lambda p: _duplicate(p, "parts", "parts"), id="part-id"),
    pytest.param(
        lambda p: p["units"].append(copy.deepcopy(p["units"][0])), id="unit-id"
    ),
    pytest.param(lambda p: p["roots"][0].update(containerId="MISSING"), id="root-edge"),
    pytest.param(lambda p: p["containers"][1].update(rootId="MISSING"), id="root-ref"),
    pytest.param(
        lambda p: p["containers"][1].update(parentContainerId="C0002"), id="cycle"
    ),
    pytest.param(_unlink_derived, id="derived-child-link"),
    pytest.param(
        lambda p: p["mimeLeaves"][1].update(disposition="ready"), id="expanded-edge"
    ),
    pytest.param(
        lambda p: p["parts"][0].update(unitIds=["C0001-U0001"]), id="part-units"
    ),
    pytest.param(
        lambda p: p["units"][0].update(originId="C0002"), id="cross-container-origin"
    ),
    pytest.param(
        lambda p: p["units"][0].update(canonicalUtf8Sha256="0" * 64), id="text-hash"
    ),
    pytest.param(
        lambda p: p["units"][0].update(utf8End=p["units"][0]["utf8End"] + 1),
        id="byte-bounds",
    ),
    pytest.param(lambda p: p["budget"].update(modelVisibleUtf8Bytes=1), id="budget"),
]


def _schema_accepts(tmp_path: Path, value: dict) -> bool:
    del tmp_path
    return published_schema_accepts(SCHEMA, value)


def test_compiled_packet_has_schema_and_python_structural_parity(
    tmp_path: Path,
) -> None:
    packet, mapping = _compiled_note_map(tmp_path)
    assert _schema_accepts(tmp_path, packet)
    assert validate_map(packet, mapping)["faults"] == []


def test_schema_subset_rejects_an_unimplemented_keyword() -> None:
    with pytest.raises(ValueError, match="unsupported JSON Schema keyword"):
        validate_schema_subset({}, {"type": "object", "allOf": []})


def test_schema_subset_requires_exactly_one_one_of_branch() -> None:
    schema = {
        "oneOf": [
            {"type": "object", "required": ["left"]},
            {"type": "object", "required": ["right"]},
        ]
    }
    assert validate_schema_subset({"left": 1}, schema) == []
    assert validate_schema_subset({}, schema)
    assert validate_schema_subset({"left": 1, "right": 1}, schema)


def test_valid_provenance_graph_is_accepted(tmp_path: Path) -> None:
    packet, mapping = _edge_packet()
    assert _schema_accepts(tmp_path, packet)
    assert validate_map(packet, mapping)["faults"] == []


def test_compiler_exact_duplicate_attachment_retains_a_valid_child_edge(
    tmp_path: Path,
) -> None:
    message = EmailMessage()
    message["From"] = "Synthetic Correspondent <source@example.invalid>"
    message["Date"] = "Thu, 20 Aug 2026 09:00:00 +0000"
    message["Subject"] = "Synthetic duplicate attachments"
    message.set_content("Synthetic envelope.")
    message.add_attachment("same payload", subtype="plain", filename="first.txt")
    message.add_attachment("same payload", subtype="plain", filename="second.txt")
    (tmp_path / "duplicates.eml").write_bytes(message.as_bytes(policy=SMTP))
    request = {
        "schemaVersion": "timenarratives.request.v1",
        "runId": "run-duplicate-attachment",
        "actor": {"id": "ACTOR1", "name": "Avery Example", "aliases": []},
        "matter": {
            "id": "MATTER1",
            "client": "Synthetic Client",
            "aliases": [],
        },
        "selections": [{"kind": "file", "path": "duplicates.eml"}],
        "filters": {
            "sourceTypes": ["email", "text"],
            "since": None,
            "until": None,
            "asOf": "2026-08-21T12:00:00+01:00",
        },
    }
    packet = build_packet.compile_packet(request, tmp_path)
    duplicate_leaves = [
        leaf for leaf in packet["mimeLeaves"] if leaf["disposition"] == "exactDuplicate"
    ]
    assert len(duplicate_leaves) == 1
    assert duplicate_leaves[0]["childContainerId"] is not None
    assert validate_packet_semantic_boundary(packet) == []


@pytest.mark.parametrize("mutate", PROVENANCE_MUTATIONS)
def test_packet_provenance_tampering_refuses_map_and_render(
    tmp_path: Path, mutate
) -> None:
    packet, mapping = _edge_packet()
    mutate(packet)
    packet.pop("packetDigestSha256")
    packet["packetDigestSha256"] = canonical_sha256(packet)
    mapping["packetDigest"] = packet["packetDigestSha256"]
    confirmation = make_confirmation(packet, mapping)
    assert _schema_accepts(tmp_path, packet)
    result = validate_map(packet, mapping)
    assert "packet_provenance" in {fault["code"] for fault in result["faults"]}
    rendered = build_rendered(packet, mapping, confirmation)
    assert rendered["deliverable"] is None and rendered["markdown"] is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda packet: packet["roots"][0].update(absolutePath="C:/private.txt"),
        lambda packet: packet["containers"][0].pop("sourceType"),
        lambda packet: packet["units"][0].update(utf8Start="0"),
    ],
)
def test_schema_invalid_packet_is_refused_before_semantic_or_render_use(
    tmp_path: Path, mutate
) -> None:
    packet, mapping = _compiled_note_map(tmp_path)
    mutate(packet)
    packet.pop("packetDigestSha256")
    packet["packetDigestSha256"] = canonical_sha256(packet)
    mapping["packetDigest"] = packet["packetDigestSha256"]
    confirmation = make_confirmation(packet, mapping)
    assert not _schema_accepts(tmp_path, packet)
    map_result = validate_map(packet, mapping)
    assert "packet_structure" in {fault["code"] for fault in map_result["faults"]}
    rendered = build_rendered(packet, mapping, confirmation)
    assert rendered["deliverable"] is None and rendered["markdown"] is None
