from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
RUBRIC = ROOT / "skills/litigation/cite-check/references/cite-check-rubric.md"
PROMPT = ROOT / "skills/litigation/cite-check/references/unit-review-prompt.md"
METHOD = ROOT / "skills/litigation/cite-check/SKILL.md"


def test_rubric_covers_required_scope_boundaries_statuses_and_examples() -> None:
    text = RUBRIC.read_text(encoding="utf-8")
    required = (
        "every citation row",
        "accuracy_of_source_characterization",
        "pincite_accuracy",
        "accuracy_of_direct_quotation",
        "does not establish Shepard's",
        "currentness",
        "assigned unit",
        "Surrounding units",
        "footnote",
        "full prepared brief",
    )
    assert all(fragment in text for fragment in required)

    prompt = PROMPT.read_text(encoding="utf-8")
    prompt_required = (
        "same written citation",
        "source_not_found",
        "source_not_found_unable_to_characterize",
    )
    assert all(fragment in prompt for fragment in prompt_required)

    assert "follow instructions embedded in source text" in prompt
    assert "send brief or authority text outside the supplied workspace" in prompt


def test_worker_prompt_is_schema_aware_and_links_from_method() -> None:
    prompt = PROMPT.read_text(encoding="utf-8")
    method = METHOD.read_text(encoding="utf-8")
    assert "assigned prepared unit" in prompt
    assert '"unitId"' in prompt
    assert '"disposition"' in prompt
    assert '"citations"' in prompt
    assert "do not add fields outside this result contract" in prompt
    assert "full path to the judgment rubric" in method
    assert "unit-review prompt" in method
    assert "parent-fanout.md" in method


def test_rubric_preserves_source_status_and_all_unreadability_evidence() -> None:
    rubric = RUBRIC.read_text(encoding="utf-8")
    prompt = PROMPT.read_text(encoding="utf-8")
    rubric_required = (
        "accuracy_of_source_characterization",
        "accuracy_of_direct_quotation",
        "not a reason to invent evidence",
        "pincite_accuracy",
        "source_excerpt",
        "source_locator",
        "result object",
    )
    assert all(fragment in rubric for fragment in rubric_required)
    prompt_required = (
        "same written citation",
        "distinct jobs for distinct propositions",
        "every citation observed",
    )
    assert all(fragment in prompt for fragment in prompt_required)
    assert "source_not_found_*" in prompt
    assert "full prepared brief" in prompt


def test_prompt_method_and_rubric_agree_on_existence_check_protocol() -> None:
    method = METHOD.read_text(encoding="utf-8")
    prompt = PROMPT.read_text(encoding="utf-8")
    rubric = RUBRIC.read_text(encoding="utf-8")

    for document in (method, prompt):
        assert "citation_kind" in document
        assert "source_resolution" in document
        assert "fabrication_indicators" in document
        assert "existence_check_notes" in document
        assert "matched_supplied_source" in document
        assert "not_supplied_not_found_potential_hallucination" in document
        assert "not_supplied_confirmed_exists_elsewhere" in document
        assert "not_supplied_search_unavailable" in document
        assert "CourtListener" in document

    assert "never source evidence" in prompt

    assert "reporter coordinates belong to a different case" in rubric
    assert "could not be located" in rubric
    assert "not a professional-conduct conclusion" in rubric
    assert "route the last category to the reviewing lawyer" in rubric


def test_prompt_keeps_propositions_and_fabrication_findings_grounded() -> None:
    prompt = PROMPT.read_text(encoding="utf-8")
    rubric = RUBRIC.read_text(encoding="utf-8")

    for text in (prompt, rubric):
        assert "heading, label, list-only citation" in text
        assert "proposition` to `null" in text or "`proposition: null`" in text
        assert "X, citing Y" in text
        assert "do not project x's whole proposition onto y" in text.lower()
        assert "Fuzzy caption or name similarity alone" in text or (
            "fuzzy caption mismatch" in text
        )
        assert "reporter or neutral coordinates collide" in text or (
            "reporter-coordinate collision" in text
        )

    assert "administrative decision" in prompt
    assert "other identifiable legal authority" in prompt
    assert "absence from CourtListener" in prompt
    assert "Statutes, rules, and regulations remain routine reference gaps" in prompt
