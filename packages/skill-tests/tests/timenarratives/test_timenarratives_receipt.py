"""Exact, redacted exception-ledger receipt tests."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
from pathlib import Path

from test_timenarratives_contracts import (
    make_confirmation,
    make_map,
    make_packet,
    schema_accepts,
)

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "skills" / "core" / "timenarratives" / "scripts"))
canonical_sha256 = importlib.import_module("canonical_json").canonical_sha256
build_rendered = importlib.import_module("render_deliverable").build_rendered
validate_structure = importlib.import_module("structural_contracts").validate_structure


def _render_with_every_exception_kind() -> dict:
    packet = make_packet()
    packet["roots"].append(
        {
            "rootId": "S0002",
            "selectionIndex": 1,
            "kind": "file",
            "selectedPath": "filtered-source.txt",
            "containerId": "C0002",
            "disposition": "excluded",
            "reason": "source_type_filter",
        }
    )
    packet["containers"].append(
        {
            "containerId": "C0002",
            "parentContainerId": None,
            "rootId": "S0002",
            "originLocator": "selection:1",
            "sourceType": "text",
            "mediaType": "text/plain",
            "displayName": "filtered-source.txt",
            "byteLength": 0,
            "rawSha256": hashlib.sha256(b"").hexdigest(),
            "sourceTime": None,
            "sourceTimeKind": None,
            "filterDisposition": "excluded",
            "disposition": "excluded",
            "reason": "source_type_filter",
            "sourceAuthor": None,
        }
    )
    packet["mimeLeaves"].append(
        {
            "mimeLeafId": "MIME0002",
            "containerId": "C0002",
            "locator": "mime:1",
            "parentLocator": None,
            "contentType": "application/octet-stream",
            "contentDisposition": "attachment",
            "filename": "private-attachment.bin",
            "contentId": None,
            "payloadSha256": None,
            "byteLength": None,
            "role": "attachment",
            "childContainerId": None,
            "disposition": "unreadable",
            "reason": "malformed_mime",
            "sourceAuthor": None,
        }
    )
    packet["parts"].append(
        {
            "partId": "PART0002",
            "containerId": "C0002",
            "locator": "word/duplicate.xml",
            "mediaType": "application/xml",
            "rawSha256": "e" * 64,
            "byteLength": 0,
            "role": "structural",
            "unitIds": [],
            "disposition": "exactDuplicate",
            "reason": "raw_sha256_match",
        }
    )
    second = copy.deepcopy(packet["units"][0])
    private_text = "Private filename source.txt must remain packet-only."
    second.update(
        unitId="C0001-U0002",
        canonicalText=private_text,
        canonicalUtf8Sha256=hashlib.sha256(private_text.encode()).hexdigest(),
        utf8End=len(private_text.encode()),
    )
    packet["units"].append(second)
    packet["budget"]["modelVisibleUtf8Bytes"] += len(private_text.encode())
    packet["partitions"]["selectedRoots"]["excluded"].append("S0002")
    packet["partitions"]["containers"]["excluded"].append("C0002")
    packet["partitions"]["mimeLeaves"]["unreadable"].append("MIME0002")
    packet["partitions"]["parts"]["exactDuplicate"].append("PART0002")
    packet.pop("packetDigestSha256")
    packet["packetDigestSha256"] = canonical_sha256(packet)
    mapping = make_map(packet)
    mapping["unitAssessment"].append(
        {
            "unitId": "C0001-U0002",
            "disposition": "read_but_unused",
            "reason": "not_relevant",
        }
    )
    confirmation = make_confirmation(packet, mapping)
    result = build_rendered(packet, mapping, confirmation)
    assert result["faults"] == []
    return result["deliverable"]


def test_receipt_ledger_covers_every_exception_and_non_used_assessment() -> None:
    deliverable = _render_with_every_exception_kind()
    assert deliverable["receipt"]["exceptionLedger"] == [
        {
            "itemType": "root",
            "itemId": "S0002",
            "disposition": "excluded",
            "reason": "source_type_filter",
        },
        {
            "itemType": "container",
            "itemId": "C0002",
            "disposition": "excluded",
            "reason": "source_type_filter",
        },
        {
            "itemType": "mimeLeaf",
            "itemId": "MIME0002",
            "disposition": "unreadable",
            "reason": "malformed_mime",
        },
        {
            "itemType": "part",
            "itemId": "PART0002",
            "disposition": "exactDuplicate",
            "reason": "raw_sha256_match",
        },
        {
            "itemType": "unitAssessment",
            "itemId": "C0001-U0002",
            "disposition": "read_but_unused",
            "reason": "not_relevant",
        },
    ]
    assert deliverable["receipt"]["counts"]["exceptionLedgerItems"] == 5


def test_exception_ledger_is_strict_and_contains_no_packet_only_text() -> None:
    deliverable = _render_with_every_exception_kind()
    serialized = json.dumps(deliverable)
    assert "source.txt" not in serialized
    assert "Private filename" not in serialized
    assert "James Cockburn" not in serialized
    assert schema_accepts("timenarratives-deliverable.schema.json", deliverable)
    assert validate_structure("deliverable", deliverable) == []
    deliverable["receipt"]["exceptionLedger"][0]["filename"] = "source.txt"
    assert not schema_accepts("timenarratives-deliverable.schema.json", deliverable)
    assert validate_structure("deliverable", deliverable)
