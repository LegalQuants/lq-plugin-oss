"""Contract checks for the nontechnical lawyer-facing /cite-check journey."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
SKILL = ROOT / "skills/litigation/cite-check"
WORKFLOW = SKILL / "references/lawyer-workflow.md"
FIXTURES = ROOT / "packages/skill-tests/tests/cite-check/fixtures/lawyer-workflow"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _fixture(name: str) -> dict[str, Any]:
    value = json.loads(_read(FIXTURES / name))
    assert isinstance(value, dict)
    return value


def test_common_sections_route_a_lawyer_through_progressive_disclosure() -> None:
    skill = _read(SKILL / "SKILL.md")

    assert "lawyer-workflow.md" in skill
    assert "getting-authorities.md" in skill
    assert "For United States case law, search CourtListener" in skill
    assert "jurisdiction-specific authority sources" in skill
    assert (
        "license permits using the downloaded material with external AI products"
        in skill
    )
    assert "separate, complete, readable authority files" in skill
    assert "not proof of official publication" in skill
    assert "document-context.md" in skill
    assert "architecture.md" not in skill
    assert "assets/report-template.html" in skill
    assert "citation_as_written_in_unit" in skill
    assert "Never read or write `lqprofile.md`" in skill


def test_workflow_has_source_bound_westlaw_route_and_no_credential_request() -> None:
    text = _read(SKILL / "references/getting-authorities.md")
    required = (
        "separate, complete, readable authority files",
        "underlying authority text",
        "complete readable text",
        "Keep separate files when the interface permits",
        "stable `sourceId`",
        "use it as a locator and obtain the underlying documents separately",
        "Keep the target brief separate from the downloaded authorities",
        "extract it outside the review and upload the readable files",
    )
    assert all(fragment in text for fragment in required)
    lowered = text.lower()
    for forbidden in ("send your password", "paste your password"):
        assert forbidden not in lowered
    assert "Use the authority files, not an account password or token." in text
    assert "Go to **Tools**, then **Litigation Document Analyzer**." not in text
    assert "use Westlaw's Litigation Document Analyzer to produce" not in text


def test_workflow_avoids_an_unverified_westlaw_interface() -> None:
    text = _read(SKILL / "references/getting-authorities.md")
    required_fragments = (
        "products, subscriptions, and interfaces vary",
        "does not establish a universal click path",
        "outcome-based acquisition guidance",
        "rather than unverified interface instructions",
    )
    assert all(fragment in text for fragment in required_fragments)


def test_workflow_preserves_nuanced_advocacy_and_candor_boundary() -> None:
    text = _read(WORKFLOW)
    text += _read(SKILL / "references/document-context.md")
    text += _read(SKILL / "references/getting-authorities.md")
    required = (
        "objectively false statement",
        "material misstatement",
        "overstatement",
        "distinguish adverse authority",
        "preserve an issue",
        "principal arguments",
        "peripheral or unraised point needs rebuttal",
        "Evidence preservation is a separate obligation",
        "do not alter, destroy, or conceal material evidence",
        "Do not assume that every omission is unethical",
        "ex parte",
        "discovery or preservation order",
        "does not adjudicate",
        "Do not infer knowledge, intent, materiality, or misconduct",
    )
    assert all(fragment in text for fragment in required)


def test_workflow_public_lookup_has_three_simple_outcomes_and_stays_source_bound() -> (
    None
):
    text = _read(WORKFLOW)
    text += _read(SKILL / "references/document-context.md")
    text += _read(SKILL / "references/getting-authorities.md")
    required = (
        "search was unavailable",
        "case was not found and may be hallucinated",
        "case was found but not supplied for substantive checking",
        "does not verify what the case says",
        "Authority status is limited to what the source visibly identifies",
        "supplied treatment evidence",
    )
    assert all(fragment in text for fragment in required)


def test_complete_cold_start_fixture_can_begin_without_local_setup() -> None:
    expected = _fixture("complete-intake.json")["expected"]
    assert expected["canBeginReview"] is True
    assert expected["mustAskBeforeReview"] == []
    assert expected["executionFallback"] == "native-workers-or-sequential"


def test_missing_cold_start_fixture_requests_only_material_context_and_sources() -> (
    None
):
    expected = _fixture("missing-authorities.json")["expected"]
    assert expected["canBeginReview"] is False
    assert set(expected["mustAskBeforeReview"]) == {
        "intendedUse",
        "tribunal",
        "jurisdiction",
        "proceduralPosture",
    }
    assert expected["offerAuthorityRoutes"] == [
        "Westlaw-download",
        "user-supplied-files",
        "automatic-public-case-search",
    ]
    assert expected["mustNotAskFor"] == [
        "Westlaw password",
        "API key",
        "terminal setup",
    ]
