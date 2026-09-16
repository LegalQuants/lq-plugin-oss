"""PRD-05 acceptance: assess — plain summary, verified doors, no archetype saves."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SKILL = ROOT / "skills" / "companion" / "lq-mirror" / "SKILL.md"
DISCLAIMER = "CODEX for Legal is a workflow aid, not legal advice."


def skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


def norm(t: str) -> str:
    return " ".join(t.split())


def test_no_file_format_vocabulary_in_the_skill():
    low = skill_text().lower()
    assert "markdown" not in low
    assert "card" not in low


def test_plain_summary_offer_replaces_the_card():
    t = norm(skill_text())
    assert "short summary you can save or share" in t
    assert "paste it anywhere" in t
    # verbatim-show + explicit yes per write, then save where they say
    assert "Show the summary first; on their yes, save it where they say" in t
    assert "complete even if saving is declined" in t


def test_no_recording_the_archetype_section_or_store_write():
    t = skill_text()
    assert "Recording the archetype" not in t
    assert "fluency.archetype" not in t
    # the settled ruling is stated instead: in-session only, never saved
    n = norm(t)
    assert "never recorded anywhere" in n
    assert "stays in the room" in n
    assert "no archetype label" in n.lower()


def test_formal_assessment_is_asked_not_offered():
    t = norm(skill_text())
    assert "Never bring up LQ Assess" in t
    assert "never propose `$lq:assess` by default" in t
    assert "https://assess.legalquants.com" in t  # the honest one-line answer
    assert "`$lq-apply` is where to prepare" in t
    assert "only after verifying" not in t
    assert "where it is installed" not in t
    # a concrete available alternative is named when no door verifies
    low = t.lower()
    assert "reflect on a chosen project" in low
    assert "connect to a peer" in low


def test_no_slash_invocation_of_the_formal_assessment():
    assert "`/lq:assess`" not in skill_text()


def test_prd02_first_skill_ending_is_untouched():
    t = skill_text()
    assert "## The ending" in t
    assert "live catalog" in t
    assert "never from memory" in t


def test_disclaimer_remains_last():
    t = norm(skill_text())
    assert DISCLAIMER in t
    assert t.endswith('The judgement stays yours."')
