"""PRD-07 acceptance: apply v2 — the builder profile. Evidence, never adjectives."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SKILL = ROOT / "skills" / "companion" / "lq-apply" / "SKILL.md"
FORMATS = ROOT / "skills" / "companion" / "lq-apply" / "references" / "formats.md"


def text() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_source_routes_lightest_first_with_confirmed_handle():
    t = " ".join(text().split())
    assert "Sources — lightest first" in t
    assert "confirmed GitHub or public portfolio handle" in t
    assert "confirm it belongs to them" in t
    assert "never open private repositories without authorization" in t
    assert "never guess an identity" in t


def test_inventory_before_highlights():
    t = " ".join(text().split())
    assert "## 2. Inventory before highlights" in text()
    assert "Never stop after the first three hits" in t
    assert "what was found, what was read, what remains uncovered" in t


def test_attribution_categories_are_separated():
    t = " ".join(text().split()).lower()
    for word in ("built", "co-built", "forked", "tested", "deployed", "used"):
        assert word in t
    assert "repo ownership is not authorship" in t


def test_declared_inferred_gap_before_ready():
    t = " ".join(text().split())
    assert "Declared and inferred — the gap, before ready" in text()
    assert "declared" in t and "inferred" in t
    assert "surface the gap for correction before the draft is called ready" in t
    assert "Nothing inference-only enters the public draft" in t


def test_no_archetype_anywhere_in_the_output_contract():
    t = " ".join(text().split())
    assert "fluency level/archetype" not in t  # the old usable-evidence phrasing
    assert "No archetype, anywhere" in t
    assert "No archetype, score, rank, or percentile" in t
    for line in text().splitlines():
        if "archetype" in line.lower():
            assert "never" in line.lower() or "no archetype" in line.lower(), line


def test_application_is_provisional_when_the_site_is_unreachable():
    t = " ".join(FORMATS.read_text(encoding="utf-8").split())
    assert "provisional" in t
    assert "never claim a fixed question count" in t


def test_contract_and_endings_pointers_present():
    t = text()
    assert "store-contract.md" in t
    assert "endings.md" in t
    assert "legalquants.com" in t


def test_private_evidence_notes_stay_separate():
    t = " ".join(text().split())
    assert "separate evidence-notes file" in t
    assert "never inside copy meant to be pasted publicly" in t
