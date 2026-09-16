"""PRD-06 acceptance: my-lq-moment — explain first, practice stays practice,
the result in plain words."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SKILL = ROOT / "skills" / "companion" / "my-lq-moment" / "SKILL.md"
DISCLAIMER = "CODEX for Legal is a workflow aid, not legal advice."


def flat() -> str:
    return " ".join(SKILL.read_text(encoding="utf-8").split())


def test_explain_first_block_precedes_the_consent_flow():
    t = flat()
    assert t.index("Explain before evidence") < t.index("Before reading any evidence")
    upfront = t[: t.index("## 2.")]
    assert "plain words" in upfront
    assert "clearly labelled practice example" in upfront
    # the training exclusion is stated up front, not discovered after consent
    assert "can never qualify" in upfront
    assert "never discover the training exclusion" in upfront


def test_practice_labelling_covers_story_and_image():
    t = flat()
    assert '"Practice example — fictional training"' in t
    assert "wherever they appear" in t
    # the label reaches the branded asset too
    assert 'alongside the "My LQ Moment" signature' in t


def test_practice_is_never_persisted_as_a_real_moment():
    t = flat()
    assert "never qualifies, and it is never saved" in t  # the §2 outcome
    assert "Practice is never saved" in t
    assert "earned moments only" in t  # the §3.5 line stays earned-only


def test_result_opens_with_the_plain_achievement():
    t = flat()
    receipt = t.index("You managed to")
    evidence = "what the lawyer directed, the method, the checked outputs"
    assert evidence in t[receipt:]


def test_estimates_are_labelled_never_measured():
    t = flat()
    assert "label it as an estimate" in t
    assert "never as measured time saved" in t
    assert "labelled as an estimate, never measured time saved" in t
    assert "Time savings are labelled as estimates, never measured" in t


def test_refusal_and_door_placement_regression():
    t = flat()
    assert "in one sentence grounded in the rubric" in t  # §4 why, one sentence
    assert "one concrete pointer" in t
    # the PRD-02 door is earned-only: honest-no and practice carry none
    assert "no door" in t.lower()
    assert "$lq-apply" in t
    ending = t.lower().split("## the ending")[1]
    assert "connect" not in ending  # no universal connect ending (ruled)


def test_no_store_taxonomy_change():
    t = flat()
    # earned_moment / practice_moment taxonomy is out of scope (PRD-03)
    assert "practice_moment" not in t
    assert "earned_moment" not in t
    assert "store contract" in t  # the PRD-03 shape-only save, unchanged


def test_disclaimer_stays_last():
    t = flat()
    assert DISCLAIMER in t
    assert t.endswith('The judgement stays yours."')
