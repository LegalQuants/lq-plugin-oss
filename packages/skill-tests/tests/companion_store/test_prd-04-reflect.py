"""PRD-04 acceptance: reflect — purpose-first, fixed output shape, journey lane.

Text checks on skills/lq-reflect/SKILL.md: the purpose paragraph
lands before any scope/consent step, the report leads with the fixed three
items, and "what next?" stays in the learning journey. R4 regression: the
PRD-02 conditional connect door is untouched.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SKILL = ROOT / "skills" / "companion" / "lq-reflect" / "SKILL.md"


def text() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_purpose_paragraph_comes_before_any_scope_or_consent_step():
    t = text()
    purpose = t.index("it is not a legal or governance audit")
    assert "I can use selected sessions to show what helped" in t
    assert "one change for next time" in t
    # the consent gates of both postures sit later in the document
    assert purpose < t.index("**Scope, honestly, then permission.**")
    assert purpose < t.index("## Live mode")


def test_what_it_adds_over_an_ordinary_chat_is_named_without_superiority():
    t = text().lower()
    assert "bounded evidence review" in t
    assert "explicit coverage" in t
    assert "optional" in t and "saved lesson" in t
    assert "later check on whether that lesson" in t
    assert "never claim" in t  # no superiority claim without a comparison


def test_report_leads_with_the_fixed_three_items():
    t = " ".join(
        text().split()
    )  # whitespace-normalized: prose rewraps must not break this
    section = t.index("## The report, as they see it")
    did_well = t.index("one thing they did well", section)
    change = t.index("one concrete change to try", section)
    why = t.index("why that change helps their actual work", section)
    assert did_well < change < why
    chronology = t.index("detailed chronology", section)
    assert "only when they ask" in t[chronology : chronology + 400]


def test_journey_lane_rule_is_stated():
    t = text().lower()
    lane = t.index("## the journey lane")
    body = t[lane:]
    assert "what next?" in body
    assert "learning journey" in body
    assert "never take over engineering work" in body
    assert "does not join the build" in body


def test_regression_prd02_connect_door_still_conditional_on_stuck():
    t = text().lower()
    assert "## the ending" in t
    assert "$lq-connect" in t
    assert "stuck" in t
    assert "never invent a stuck" in t
    # the overruled universal connect ending must not come back
    assert "required next connection" not in t
    assert "always suggest" not in t
