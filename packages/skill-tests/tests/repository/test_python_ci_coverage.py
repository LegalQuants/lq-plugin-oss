"""Python typecheck and ruff gates cover the whole first-party tree."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
RUFF_PATHS = ("skills", "packages")


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_ty_has_no_file_exclusions() -> None:
    src = _pyproject()["tool"]["ty"]["src"]
    assert "exclude" not in src
    include = src["include"]
    for tree in ("skills", "packages"):
        assert tree in include


def test_ty_extra_paths_cover_every_skill_scripts_dir() -> None:
    extra = _pyproject()["tool"]["ty"]["environment"]["extra-paths"]
    shared_dirs = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "skills").glob("*/*/scripts/shared")
        if path.is_dir()
    )
    scripts_dirs = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "skills").glob("*/*/scripts")
        if path.is_dir()
    )
    assert extra == shared_dirs + scripts_dirs


def test_ruff_src_includes_packages_and_drops_missing_trees() -> None:
    ruff = _pyproject()["tool"]["ruff"]
    assert "packages" in ruff["src"]
    assert "skills/redline" not in ruff["extend-exclude"]


def test_ruff_commands_use_the_same_path_set() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    lint_py = package["scripts"]["lint:py"]
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    pre_commit = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    hook = (ROOT / "packages/pluginctl/githooks" / "pre-commit").read_text(
        encoding="utf-8"
    )
    expected = " ".join(RUFF_PATHS)
    assert f"ruff format --check {expected}" in lint_py
    assert f"ruff check {expected}" in lint_py
    assert "pnpm lint:py" in pre_commit
    assert "pnpm lint:py" in hook
    assert "run: pnpm lint:py" in workflow
