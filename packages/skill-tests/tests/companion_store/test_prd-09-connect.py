"""PRD-09 acceptance: connect — honestly timed, honest links."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SKILL = ROOT / "skills" / "companion" / "lq-connect" / "SKILL.md"


def skill() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_upfront_latency_warning_precedes_the_search():
    t = skill().lower()
    assert "minute or two" in t
    # the warning is stated before the directory search is described
    assert t.index("minute or two") < t.index("read the public directory")


def test_long_searches_emit_progress_beats_never_silence():
    t = skill().lower()
    assert "progress beats" in t
    assert "still looking" in t and "widening" in t
    assert "never silent" in t


def test_honest_links_and_no_invented_booking():
    t = skill().lower()
    assert "request an intro" in t
    assert "public profile link suffices" in t
    assert "never invent calendar" in t
    assert "no booking mechanics" in t  # the post-#141 rule stays


def test_fewer_matches_never_pad():
    t = skill().lower()
    assert "never pad" in t
    assert "fewer when" in t


def test_no_disclaimer_on_a_people_finder():
    # Decided 6 Sep 2026: connect hands over profile links; no reader could
    # take that for legal advice, so the suite-wide closing line is dropped.
    assert "not legal advice" not in skill()
