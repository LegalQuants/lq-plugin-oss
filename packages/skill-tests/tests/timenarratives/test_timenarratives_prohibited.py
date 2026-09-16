"""Pre- and post-render prohibited-output controls."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from test_timenarratives_contracts import make_map

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "skills" / "core" / "timenarratives" / "scripts"))
_prohibited = importlib.import_module("prohibited_output")
scan_model_output = _prohibited.scan_model_output
scan_rendered = _prohibited.scan_rendered
scan_text = _prohibited.scan_text


@pytest.mark.parametrize(
    "text",
    [
        "Reviewed the papers for 2.5 hours.",
        "Reviewed the papers for 1.2h.",
        "Reviewed the papers for 30 min.",
        "Worked for two hours on the reply.",
        "Worked for an hour on the reply.",
        "Worked for twenty-five minutes on the reply.",
        "Worked for one and a half hours on the reply.",
        "Worked from 09:30 to 11:00.",
        "Applied a rate of £450 per hour.",
        "The fee was GBP 1,250.",
        "Use billing code L120.",
        "Classified this as billable.",
        "Post the time entry to billing.",
        "The billing entry should be posted.",
        "Submit this entry for invoicing.",
        "Worked for 90m.",
        "Applied L120.",
        "Classified the work as chargeable.",
        "Recorded the time entry.",
        "The consideration was one hundred pounds.",
        "Reviewed disclosure (90m).",
        "Worked one hundred minutes.",
        "Worked half an hour.",
        "Worked one-and-a-half hours.",
        "Worked 1h30m.",
        "The fee was a hundred pounds.",
        "The fee was one million pounds.",
        "The fee was four hundred and fifty pounds.",
        "The fee was £1m.",
        "The fee was 100 pence.",
        "The consideration was one million pounds.",
        "The consideration was a million pounds.",
        "The consideration was 100 pence.",
        "The consideration was 100 cents.",
    ],
)
def test_prohibited_model_text_is_detected(text: str) -> None:
    assert scan_text(text, "$.clauses[0].text")


@pytest.mark.parametrize(
    "text",
    [
        "Reviewed the order dated 21 August 2026.",
        "Analysed costs consequences and CPR 44.2.",
        "Considered claim reference L120-2026.",
        "Reviewed the costs budget assumptions.",
        "Reviewed Task 2026 correspondence.",
        "Reviewed one unit of the disclosure set.",
        "Considered the amount of one creditor's admitted claim.",
        "Considered CPR 90M and claim reference L120-2026.",
    ],
)
def test_reserved_legal_wording_is_deliberately_refused(text: str) -> None:
    assert scan_text(text, "$.clauses[0].text")


@pytest.mark.parametrize(
    "text",
    [
        "Reviewed the procedural order and prepared the response.",
        "Analysed costs consequences and the claimant's position.",
        "Considered the claim reference and disclosure index.",
        "Reviewed correspondence concerning the admitted claim.",
    ],
)
def test_benign_authored_text_without_reserved_tokens_passes(text: str) -> None:
    assert scan_text(text, "$.clauses[0].text") == []


@pytest.mark.parametrize(
    ("text", "expected_code"),
    [
        ("Reviewed one issue.", "numeric_data"),
        ("Reviewed exhibit Ⅳ.", "numeric_data"),
        ("Reviewed exhibit 四.", "numeric_data"),
        ("Reviewed the million-document corpus.", "numeric_data"),
        ("Review lasted 90m.", "duration_data"),
        ("The session ran 09h30 to 10h30.", "duration_data"),
        ("Settlement value was £five million.", "money_data"),
        ("Settlement value was five million sterling.", "money_data"),
        ("The UTBMS classification was L120.", "billing_code"),
        ("Reviewed the bil\u200bling dispute.", "billing_code"),
        ("This is chargeable work.", "billability_decision"),
        ("Prepared the invoice.", "posting_decision"),
        ("The time entry was lodged with billing.", "posting_decision"),
    ],
)
def test_controlled_vocabulary_rejects_without_phrase_inference(
    text: str, expected_code: str
) -> None:
    assert expected_code in {issue["code"] for issue in scan_text(text, "$")}


def test_every_model_authored_string_is_scanned() -> None:
    mapping = make_map()
    mapping["workstreams"][0]["label"] = "Billable claim work"
    found = scan_model_output(mapping)
    assert any(issue["path"] == "$.workstreams[0].label" for issue in found)


def test_raw_packet_text_is_not_a_model_output_scan_input() -> None:
    mapping = make_map()
    assert scan_model_output(mapping) == []


def test_non_authored_map_fields_are_outside_the_guard() -> None:
    mapping = make_map()
    mapping["events"][0]["assertedBy"] = "Billing Code L120"
    mapping["events"][0]["eventId"] = "EVENT2026"
    mapping["atoms"][0]["spanSha256"] = "1" * 64

    assert scan_model_output(mapping) == []


def test_all_authored_map_fields_are_inside_the_guard() -> None:
    mapping = make_map()
    mapping["events"][0].update(
        action="Billing dispute",
        object="Billing dispute",
        purpose="Billing dispute",
    )
    mapping["workstreams"][0]["label"] = "Billing dispute"
    mapping["clauses"][0]["text"] = "Billing dispute"

    paths = {issue["path"] for issue in scan_model_output(mapping)}
    assert paths == {
        "$.events[0].action",
        "$.events[0].object",
        "$.events[0].purpose",
        "$.workstreams[0].label",
        "$.clauses[0].text",
    }


def test_render_guard_ignores_receipt_ids_hashes_and_counts() -> None:
    deliverable = {
        "runId": "RUN2026",
        "narratives": [
            {
                "workstreamId": "WORK120",
                "text": "Prepared the claim analysis.",
                "eventIds": ["EVENT120"],
                "supportClass": "documentary_supported",
            }
        ],
        "receipt": {
            "diagnostic": "Billing Code L120",
            "packetDigest": "1" * 64,
            "counts": {"units": 120},
        },
    }
    markdown = (
        "# Time Narratives\n\n### WORK120\n\nPrepared the claim analysis.\n\n"
        "Support: documentary_supported\n\nExceptions recorded: 120\n"
    )

    assert scan_rendered(deliverable, markdown) == []


def test_render_guard_scans_the_markdown_narrative_block() -> None:
    deliverable = {
        "narratives": [
            {
                "workstreamId": "WORK",
                "text": "Prepared the claim analysis.",
            }
        ]
    }
    markdown = (
        "# Time Narratives\n\n### WORK\n\nReview lasted 90m.\n\n"
        "Support: documentary_supported\n"
    )

    assert "duration_data" in {
        issue["code"] for issue in scan_rendered(deliverable, markdown)
    }
