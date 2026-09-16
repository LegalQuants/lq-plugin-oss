"""Repo-root tmp/ scratch must stay out of git status, Biome, ruff, and pytest."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_gitignore_excludes_repo_root_tmp() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "tmp/" in gitignore.splitlines()


def test_biome_includes_exclude_tmp() -> None:
    biome = json.loads((ROOT / "biome.json").read_text(encoding="utf-8"))
    includes = biome["files"]["includes"]
    assert "!**/tmp" in includes
    assert biome["vcs"]["useIgnoreFile"] is True


def test_ruff_excludes_tmp() -> None:
    excluded = _pyproject()["tool"]["ruff"]["extend-exclude"]
    assert "tmp" in excluded


def test_pytest_does_not_collect_from_tmp() -> None:
    assert _pyproject()["tool"]["pytest"]["ini_options"]["testpaths"] == [
        "packages/skill-tests/tests"
    ]
