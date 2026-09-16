"""Blind forward checks for the nontechnical lawyer-facing cite-check path."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
SKILL = ROOT / "skills/litigation/cite-check"
CONTEXT = SKILL / "references/document-context.md"
WORKFLOW_FIXTURES = (
    ROOT / "packages/skill-tests/tests/cite-check/fixtures/lawyer-workflow"
)


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_missing_intake_is_a_short_source_and_context_handoff() -> None:
    user = _json(WORKFLOW_FIXTURES / "missing-authorities.json")["user"]
    context = _text(CONTEXT).lower()

    assert user["request"] == "Please check the brief before I file it."
    assert user["target"] and user["authorities"]
    assert "which target and authority files were readable" in context
    assert "api key" not in context
    assert "terminal command" not in context
    assert "native workers" in context
    assert "one-at-a-time processing" in context


def test_nontechnical_invocation_is_exact_and_does_not_require_setup() -> None:
    workflow = _text(SKILL / "references/lawyer-workflow.md")
    flat_workflow = " ".join(workflow.split())

    assert (
        "A useful opening is: “Please cite-check this filing against the authorities "
        in workflow
    )
    assert "Do not burden a nontechnical lawyer with runtime setup" in flat_workflow


def test_codex_manifest_keeps_packaged_runner_and_fallbacks_explicit() -> None:
    skill = _text(SKILL / "SKILL.md")
    flat_skill = " ".join(skill.split())

    assert "name: cite-check" in skill
    assert "scripts/cite_check.py" in skill
    assert "scripts/probe_environment.py" in skill
    assert "Run the packaged `scripts/cite_check.py`" in skill
    assert "same one-unit assignments with host workers" in skill
    assert "process those assignments one at a time" in flat_skill
    assert "one fresh Codex session" in skill
    assert "provider switching" not in skill
    assert "Pause for approval" not in skill
    assert "3–12 logical segments" not in skill
    assert "parent-fanout.md" in skill


def test_preparation_requires_content_identity_over_filenames() -> None:
    context = _text(CONTEXT)

    assert "Treat filenames and URLs as hints only" in context
    assert "content identity cues" in context


def test_incomplete_coverage_stays_visible_to_the_lawyer() -> None:
    context = _text(CONTEXT)

    assert "remains visible as incomplete" in context
    assert "appendix may not" in context


def test_fallbacks_use_the_same_units_and_result_contract() -> None:
    context = _text(CONTEXT).lower()
    prompt = _text(SKILL / "references/unit-review-prompt.md")

    assert "scripted fan-out, native workers, and one-at-a-time processing" in context
    assert "same prepared units" in context
    assert '"unitId"' in prompt
    assert '"disposition"' in prompt
    assert '"citations"' in prompt
