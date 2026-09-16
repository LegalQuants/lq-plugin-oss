"""Hook installation is explicit, idempotent, and preserves global dispatchers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
INSTALLER = ROOT / "packages/pluginctl/scripts/install-git-hooks.mjs"


def _git_env(global_config: Path | None = None) -> dict[str, str]:
    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": str(global_config) if global_config else os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }


def _init_repo(tmp_path: Path, env: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )
    return repo


def _install(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(INSTALLER)],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _local_hooks_path(repo: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip()


def test_installs_repo_hooks_when_no_dispatcher_exists(tmp_path: Path) -> None:
    env = _git_env()
    repo = _init_repo(tmp_path, env)

    first = _install(repo, env)
    second = _install(repo, env)

    assert _local_hooks_path(repo, env) == "packages/pluginctl/githooks"
    assert "Installed repository hooks" in first.stdout
    assert "already installed" in second.stdout


def test_preserves_an_existing_global_hooks_path(tmp_path: Path) -> None:
    global_config = tmp_path / "global.gitconfig"
    global_config.write_text(
        "[core]\n\thooksPath = /existing/identity-hooks\n", encoding="utf-8"
    )
    env = _git_env(global_config)
    repo = _init_repo(tmp_path, env)

    result = _install(repo, env)

    assert _local_hooks_path(repo, env) == ""
    assert "Existing core.hooksPath left unchanged" in result.stdout
    assert "/existing/identity-hooks" in result.stdout


def test_preserves_hooks_installed_in_the_default_git_directory(tmp_path: Path) -> None:
    env = _git_env()
    repo = _init_repo(tmp_path, env)
    hooks_directory = Path(
        subprocess.run(
            ["git", "rev-parse", "--git-path", "hooks"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout.strip()
    )
    if not hooks_directory.is_absolute():
        hooks_directory = repo / hooks_directory
    existing = hooks_directory / "pre-commit"
    existing.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    result = _install(repo, env)

    assert _local_hooks_path(repo, env) == ""
    assert "Existing hooks" in result.stdout
    assert "pre-commit" in result.stdout


def test_package_exposes_one_command_installer() -> None:
    package = (ROOT / "package.json").read_text(encoding="utf-8")

    assert (
        '"hooks:install": "node packages/pluginctl/scripts/install-git-hooks.mjs"'
        in package
    )
