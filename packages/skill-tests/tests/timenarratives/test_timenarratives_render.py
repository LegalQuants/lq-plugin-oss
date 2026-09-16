"""Deterministic final rendering and receipt tests."""

from __future__ import annotations

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
_renderer = importlib.import_module("render_deliverable")
packet_sha256 = importlib.import_module("canonical_json").packet_sha256
build_rendered = _renderer.build_rendered
validate_structure = importlib.import_module("structural_contracts").validate_structure


def test_rendered_narrative_and_receipt_are_packet_derived() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    mapping["clauses"][0]["text"] = (
        "Prepared the supported claim analysis for the selected proceedings.\n\n"
        "Organised the resulting issues into a matter-focused summary for review."
    )
    confirmation = make_confirmation(packet, mapping)
    result = build_rendered(packet, mapping, confirmation)
    assert result["faults"] == []
    deliverable = result["deliverable"]
    assert deliverable["status"] == "ready_for_user_review"
    assert len(deliverable["narratives"]) == 1
    narrative = deliverable["narratives"][0]
    assert narrative["supportClass"] == "documentary_supported"
    paragraphs = narrative["text"].split("\n\n")
    assert len(paragraphs) == 2
    assert all(len(paragraph.split()) <= 60 for paragraph in paragraphs)
    assert narrative["text"] in result["markdown"]
    receipt = deliverable["receipt"]
    assert receipt["packetScope"] == "expressly_selected_only"
    assert receipt["packetReconciliation"] == "complete"
    assert receipt["workdayCompleteness"] == "not_assessed"
    assert receipt["postingState"] == "unposted_draft"
    assert receipt["supportCounts"] == {
        "documentarySupported": 1,
        "userAttested": 0,
    }
    assert receipt["counts"] == {
        "selectedRoots": 1,
        "containers": 1,
        "mimeLeaves": 0,
        "parts": 0,
        "units": 1,
        "accountedUnits": 1,
        "analyzableUnits": 1,
        "assessedUnits": 1,
        "usedUnits": 1,
        "needsConfirmationUnits": 0,
        "events": 1,
        "workstreams": 1,
        "narratives": 1,
        "packetErrors": 0,
        "packetLimitations": 0,
        "exceptionLedgerItems": 0,
    }
    assert receipt["exceptionLedger"] == []
    serialized = json.dumps(deliverable)
    assert "source.txt" not in serialized
    assert "Prepared claim analysis for Meridian." not in serialized


def test_deliverable_schema_and_python_validator_stay_in_parity() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    confirmation = make_confirmation(packet, mapping)
    deliverable = build_rendered(packet, mapping, confirmation)["deliverable"]
    assert schema_accepts("timenarratives-deliverable.schema.json", deliverable)
    assert validate_structure("deliverable", deliverable) == []
    deliverable["narratives"][0]["duration"] = "one hour"
    assert not schema_accepts("timenarratives-deliverable.schema.json", deliverable)
    assert validate_structure("deliverable", deliverable)


def test_deliverable_python_contract_rejects_non_string_ids_without_crashing() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    confirmation = make_confirmation(packet, mapping)
    deliverable = build_rendered(packet, mapping, confirmation)["deliverable"]
    deliverable["narratives"][0]["eventIds"] = [{}]
    assert not schema_accepts("timenarratives-deliverable.schema.json", deliverable)
    assert validate_structure("deliverable", deliverable)


def test_confirmation_question_derives_partial_withheld_status() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    mapping["events"] = []
    mapping["workstreams"] = []
    mapping["clauses"] = []
    mapping["atoms"] = []
    mapping["unitAssessment"][0] = {
        "unitId": "C0001-U0001",
        "disposition": "needs_confirmation",
        "reason": "actor_unclear",
    }
    confirmation = make_confirmation(packet, mapping)
    result = build_rendered(packet, mapping, confirmation)
    assert result["faults"] == []
    assert result["deliverable"]["status"] == "incomplete"
    assert result["deliverable"]["checkQuestions"] == [
        {"unitId": "C0001-U0001", "reason": "actor_unclear", "source": "source.txt"}
    ]


def test_check_questions_name_the_source_and_partial_reason() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    mapping["events"] = []
    mapping["workstreams"] = []
    mapping["clauses"] = []
    mapping["atoms"] = []
    mapping["unitAssessment"][0] = {
        "unitId": "C0001-U0001",
        "disposition": "needs_confirmation",
        "reason": "source_partially_read",
    }
    confirmation = make_confirmation(packet, mapping)
    result = build_rendered(packet, mapping, confirmation)
    assert result["faults"] == []
    question = result["deliverable"]["checkQuestions"][0]
    assert question["reason"] == "source_partially_read"
    assert question["source"] == "source.txt"
    assert "source.txt: part of this source could not be read" in result["markdown"]
    assert "C0001-U0001" not in result["markdown"]
    assert schema_accepts(
        "timenarratives-deliverable.schema.json", result["deliverable"]
    )


def test_prohibited_model_text_withholds_every_rendered_output() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    mapping["clauses"][0]["text"] = "Worked for an hour on claim analysis."
    confirmation = make_confirmation(packet, mapping)
    result = build_rendered(packet, mapping, confirmation)
    assert "duration_data" in {fault["code"] for fault in result["faults"]}
    assert result["deliverable"] is None
    assert result["markdown"] is None


def test_markdown_leads_with_entries_and_ends_with_the_record() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    confirmation = make_confirmation(packet, mapping)
    markdown = build_rendered(packet, mapping, confirmation)["markdown"]
    lines = markdown.splitlines()
    assert lines[0] == "# Time Narratives"
    assert lines[2] == "## Draft entries"
    first_entry = next(i for i, line in enumerate(lines) if line.startswith("### "))
    status_at = next(i for i, line in enumerate(lines) if line.startswith("Status: "))
    assert first_entry < status_at
    assert "Checked only the sources you selected" in markdown
    assert markdown.rstrip().endswith("Exceptions recorded: 0")
    assert "## Record" in markdown


def test_empty_result_markdown_says_so_under_draft_entries() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    mapping["events"] = []
    mapping["workstreams"] = []
    mapping["clauses"] = []
    mapping["atoms"] = []
    mapping["unitAssessment"][0] = {
        "unitId": "C0001-U0001",
        "disposition": "read_but_unused",
        "reason": "not_relevant",
    }
    confirmation = make_confirmation(packet, mapping)
    result = build_rendered(packet, mapping, confirmation)
    assert result["faults"] == []
    lines = result["markdown"].splitlines()
    assert lines[2] == "## Draft entries"
    assert lines[4].startswith("No supportable work")


def test_source_label_with_prohibited_tokens_falls_back_to_the_container_id() -> None:
    packet = make_packet()
    packet["containers"][0]["displayName"] = "Invoice 2.5 hours GBP 450.docx"
    packet["packetDigestSha256"] = packet_sha256(packet)
    mapping = make_map(packet)
    mapping["events"] = []
    mapping["workstreams"] = []
    mapping["clauses"] = []
    mapping["atoms"] = []
    mapping["unitAssessment"][0] = {
        "unitId": "C0001-U0001",
        "disposition": "needs_confirmation",
        "reason": "actor_unclear",
    }
    confirmation = make_confirmation(packet, mapping)
    result = build_rendered(packet, mapping, confirmation)
    assert result["faults"] == []
    assert result["deliverable"]["checkQuestions"][0]["source"] == "C0001"
    assert "2.5 hours" not in result["markdown"]
