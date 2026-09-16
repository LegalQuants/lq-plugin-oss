"""Make the closing-bible scripts and this folder's helpers importable, and
hand every test a synthetic closing folder under tmp_path.

The skill's `scripts/` dir goes
on sys.path so `from closing_bible import models` works the way the CLI
imports it; this folder goes on too so `pdfgen` and `cb_support` resolve.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = REPO_ROOT / "skills" / "transactional" / "closing-bible" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from cb_support import Audit, Folder  # noqa: E402


@pytest.fixture
def folder(tmp_path: Path) -> Folder:
    """An empty synthetic closing folder. Tests add PDFs with `folder.pdf(...)`."""

    return Folder(tmp_path / "closing")


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    """Where the CLI writes. Outside the closing folder so the tree hash holds."""

    path = tmp_path / "out"
    path.mkdir()
    return path


@pytest.fixture
def audit(folder: Folder) -> Callable[..., Audit]:
    """census → families over `folder`, with the expected-set inputs a row needs."""

    def build(
        *,
        checklist: dict[str, Any] | None = None,
        sigpack: dict[str, Any] | None = None,
        sigpack_dir: Path | None = None,
        sigpack_path: Path | None = None,
    ) -> Audit:
        if sigpack is not None and sigpack_dir is None:
            sigpack_dir = sigpack_path.parent if sigpack_path else folder.root
        return Audit(
            folder.root,
            checklist=checklist,
            sigpack=sigpack,
            sigpack_dir=sigpack_dir,
            sigpack_path=sigpack_path,
        )

    return build
