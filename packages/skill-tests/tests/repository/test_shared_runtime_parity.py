"""DocReview and Diligence ship the same shared review runtime."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DOCREVIEW = ROOT / "skills/litigation/docreview"
DILIGENCE = ROOT / "skills/transactional/diligence"


def relative_files(root: Path) -> set[Path]:
    return {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def test_shared_scripts_are_byte_identical() -> None:
    left = DOCREVIEW / "scripts/shared"
    right = DILIGENCE / "scripts/shared"
    assert relative_files(left) == relative_files(right)
    for relative in sorted(relative_files(left)):
        assert (left / relative).read_bytes() == (right / relative).read_bytes()


def test_shared_references_are_byte_identical() -> None:
    left = DOCREVIEW / "references/shared"
    right = DILIGENCE / "references/shared"
    assert relative_files(left) == relative_files(right)
    for relative in sorted(relative_files(left)):
        assert (left / relative).read_bytes() == (right / relative).read_bytes()
