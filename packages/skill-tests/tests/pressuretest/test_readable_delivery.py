"""Reading-view regressions: priority, terminology and source identity."""

import copy
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[4] / "skills/litigation/pressuretest/scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).parent))

from chat_result import READING_GUIDE  # noqa: E402
from render_brief import render  # noqa: E402
from render_fixtures import internal  # noqa: E402
from test_chat_delivery import all_findings, chat_fixture  # noqa: E402


@pytest.mark.parametrize("output_format", ["chat", "document"])
def test_reading_explanation_precedes_issues_and_distinguishes_supported_points(
    output_format,
):
    data = chat_fixture(verdict="pressure_points", findings=all_findings())
    text = render(data, output_format=output_format)
    assert text.count(READING_GUIDE) == 1
    assert text.index(data["brief"]["summary"]) < text.index(READING_GUIDE)
    assert text.index(READING_GUIDE) < text.index("### Issues requiring attention")
    assert "objections answered by the documents" in READING_GUIDE
    assert (
        "not an additional problem or proof that the whole position is correct"
        in READING_GUIDE
    )


@pytest.mark.parametrize("output_format", ["chat", "document"])
def test_summary_prioritises_problems_and_follow_up_without_inflating_objections(
    output_format,
):
    data = chat_fixture(verdict="pressure_points", findings=all_findings())
    for index, finding in enumerate(data["findings"]):
        finding["statement"] = f"Distinct finding {index}: {finding['statement']}"
    text = render(data, output_format=output_format)
    opening = text.split("**Position tested:**")[0]
    assert "## Summary" in opening
    assert data["brief"]["summary"] in opening
    assert "### Issues requiring attention" in opening
    for finding in data["findings"]:
        if finding["classification"] in ("defeated", "weakens_route"):
            assert finding["title"] not in opening
        else:
            assert finding["title"] in opening
    headings = [
        "## Problems with the position",
        "## Contradictions to correct",
        "## Evidence still needed",
        "## Practical points and qualifications",
        "## The strongest argument supporting the position",
        "## Objections the documents answer",
        "## Arguments that fail without changing the conclusion",
    ]
    assert [text.index(h) for h in headings] == sorted(text.index(h) for h in headings)
    for finding in data["findings"]:
        assert text.count(finding["statement"]) == 1


@pytest.mark.parametrize("output_format", ["chat", "document"])
def test_generated_labels_do_not_require_methodology_glossary(output_format):
    text = render(
        chat_fixture(verdict="pressure_points", findings=all_findings()),
        output_format=output_format,
    )
    for jargon in (
        "pressure point",
        "attacks answered",
        "defeated —",
        "flip statement",
    ):
        assert jargon not in text.lower()
    assert "The documents answer this objection" in text
    assert "One argument fails; another still supports the conclusion" in text
    assert "(A7)" not in text


def test_internal_contradiction_does_not_report_failed_conclusion():
    data = chat_fixture(verdict="pressure_points", findings=[internal()])
    opening = render(data).split("**Position tested:**")[0]
    assert "The conclusion remains supported" in opening
    assert "not supported in full" not in opening


def test_answered_objection_does_not_claim_failed_position_is_supported():
    data = chat_fixture(verdict="pressure_points", findings=all_findings())
    text = render(data)
    answered = text.split("## Objections the documents answer")[1].split(
        "## Arguments that fail without changing the conclusion"
    )[0]
    assert "Why this objection is answered" in answered
    assert "Why the conclusion remains supported" not in answered


def test_incomplete_reason_is_visible_before_any_detailed_analysis():
    data = chat_fixture(verdict="incomplete", incomplete_reason="The annex is unread.")
    text = render(data)
    assert "this review is incomplete" in text.split("**Position tested:**")[0]
    assert data["incomplete_reason"] in text.split("**Position tested:**")[0]


def test_descriptive_item_reference_keeps_original_code_date_page_and_quote():
    data = chat_fixture()
    anchor = data["findings"][0]["anchors"][0]
    anchor["locator"] = (
        "buyer's firm offer dated 3 September 2026 (correspondence item C13), PDF p.6"
    )
    text = render(data)
    assert f"{anchor['locator']}**\n\n> {anchor['quote']}" in text


def test_calculator_receipts_remain_in_record_without_raw_transcript_in_view():
    data = chat_fixture()
    receipt = {"statement": "Raw calculator output", "limit_date": "2026-09-21"}
    data["findings"][0]["calculation_receipts"] = [receipt]
    data["findings"][0]["statement"] = (
        "Ten business days after receipt ends on 21 September."
    )
    before = copy.deepcopy(data)
    text = render(data)
    assert data == before
    assert "21 September" in text
    assert "Raw calculator output" not in text
    assert json.loads(json.dumps(data))["findings"][0]["calculation_receipts"] == [
        receipt
    ]
