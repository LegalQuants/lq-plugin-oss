"""PRD-02 acceptance: per-skill endings — every door from the table, no others."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
COMPANION = ROOT / "skills" / "companion"
TABLE = COMPANION / "legalquants" / "references" / "endings.md"
DISCLAIMER = "CODEX for Legal is a workflow aid, not legal advice."


def text(skill: str) -> str:
    return (COMPANION / skill / "SKILL.md").read_text(encoding="utf-8")


def test_endings_table_exists_and_names_every_door():
    table = TABLE.read_text(encoding="utf-8")
    for skill in ("lq-apply", "lq-ask", "lq-reflect", "lq-mirror", "my-lq-moment"):
        assert f"`{skill}`" in table
    assert "legalquants.substack.com" in table
    assert "legal-workflow skills" in table and "none" in table


def test_apply_ends_at_the_website():
    t = text("lq-apply")
    assert "## The ending" in t  # the section, not the pre-existing §3 mention
    assert "https://assess.legalquants.com" in t  # the application is LQ Assess
    assert "endings.md" in t


def test_ask_ends_at_the_paid_substack_with_honest_scope():
    t = text("lq-ask")
    assert "## The ending" in t
    assert "legalquants.substack.com" in t
    assert "public library" in t  # the source-disclosure half of the door


def test_reflects_connect_door_is_conditional_on_stuck():
    t = text("lq-reflect").lower()
    assert "## the ending" in t
    assert "$lq-connect" in t
    assert "stuck" in t or "unresolved" in t
    assert "never invent a stuck" in t


def test_assess_ends_with_a_first_skill_from_the_live_catalog():
    t = text("lq-mirror")
    assert "## The ending" in t
    assert "live catalog" in t
    assert "never from memory" in t


def test_my_lq_moment_ends_at_apply_for_earned_moments_only():
    t = text("my-lq-moment")
    assert "## The ending" in t
    assert "$lq-apply" in t
    assert "no door" in t.lower()  # the honest-no path carries none


def test_connect_and_start_carry_no_door():
    assert "## The ending" not in text("lq-connect")
    start = (ROOT / "skills" / "core" / "lq-start" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "## The ending" not in start
    assert "endings.md" not in start


# lq-connect finds a person; nothing it says could be mistaken for legal
# advice, so it carries no disclaimer (Jamie, 6 Sep 2026).
NO_DISCLAIMER = {"lq-connect"}


def test_disclaimer_is_present_and_last_in_every_companion_skill():
    for skill_md in COMPANION.glob("*/SKILL.md"):
        if skill_md.parent.name in NO_DISCLAIMER:
            continue
        t = " ".join(skill_md.read_text(encoding="utf-8").split())
        assert DISCLAIMER in t, skill_md
        assert t.endswith('The judgement stays yours."'), skill_md


def test_the_substack_url_lives_only_in_asks_ending():
    for skill_md in (ROOT / "skills").glob("*/*/SKILL.md"):
        if skill_md.parent.name == "lq-ask":
            continue
        assert "substack" not in skill_md.read_text(encoding="utf-8").lower(), skill_md
