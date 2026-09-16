"""The pre-commit package hook regenerates safely and never stages output."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HOOK = ROOT / "packages/pluginctl/githooks/refresh-goldens"


def _run(
    repo: Path,
    *args: str,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


def _repo(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    isolated_env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    _run(repo, "git", "init", "--initial-branch=main", env=isolated_env)
    _run(repo, "git", "config", "user.name", "Hook Test", env=isolated_env)
    _run(repo, "git", "config", "user.email", "hook@example.test", env=isolated_env)

    (repo / ".githooks").mkdir()
    shutil.copy2(HOOK, repo / ".githooks/refresh-goldens")
    source = repo / "skills/core/demo/SKILL.md"
    package = repo / "plugins/legalquants-litigation/skills/demo/SKILL.md"
    source.parent.mkdir(parents=True)
    package.parent.mkdir(parents=True)
    source.write_text("canonical v1\n", encoding="utf-8")
    package.write_text("canonical v1\n", encoding="utf-8")
    (repo / ".gitignore").write_text(
        "plugins/legalquants-litigation/.scratch\n", encoding="utf-8"
    )

    bin_dir = repo / "test-bin"
    bin_dir.mkdir()
    pnpm = bin_dir / "pnpm"
    pnpm.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$HOOK_LOG"
case "$1" in
  plugin-pack)
    cp skills/core/demo/SKILL.md plugins/legalquants-litigation/skills/demo/SKILL.md
    ;;
  plugin-pack:check)
    cmp skills/core/demo/SKILL.md plugins/legalquants-litigation/skills/demo/SKILL.md
    ;;
  *)
    exit 2
    ;;
esac
""",
        encoding="utf-8",
    )
    pnpm.chmod(0o755)

    _run(repo, "git", "add", ".", env=isolated_env)
    _run(repo, "git", "commit", "-m", "fixture", env=isolated_env)
    log = repo / "hook.log"
    hook_env = {
        **isolated_env,
        "HOOK_LOG": str(log),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    return repo, hook_env, log


def _hook(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _run(
        repo,
        "sh",
        ".githooks/refresh-goldens",
        check=False,
        env=env,
    )


def test_regenerates_then_stops_for_review_before_accepting_staged_output(
    tmp_path: Path,
) -> None:
    repo, env, log = _repo(tmp_path)
    source = repo / "skills/core/demo/SKILL.md"
    package = repo / "plugins/legalquants-litigation/skills/demo/SKILL.md"
    source.write_text("canonical v2\n", encoding="utf-8")
    _run(repo, "git", "add", str(source), env=env)

    first = _hook(repo, env)

    assert first.returncode == 1
    assert "Review and stage plugins/legalquants-*" in first.stderr
    assert package.read_text(encoding="utf-8") == "canonical v2\n"
    assert _run(repo, "git", "diff", "--name-only", env=env).stdout.splitlines() == [
        "plugins/legalquants-litigation/skills/demo/SKILL.md"
    ]
    assert log.read_text(encoding="utf-8").splitlines() == ["plugin-pack"]

    _run(repo, "git", "add", str(package), env=env)
    second = _hook(repo, env)

    assert second.returncode == 0
    assert log.read_text(encoding="utf-8").splitlines() == [
        "plugin-pack",
        "plugin-pack:check",
    ]


def test_refuses_to_generate_from_partially_staged_inputs(tmp_path: Path) -> None:
    repo, env, log = _repo(tmp_path)
    source = repo / "skills/core/demo/SKILL.md"
    source.write_text("staged source\n", encoding="utf-8")
    _run(repo, "git", "add", str(source), env=env)
    source.write_text("unstaged source\n", encoding="utf-8")

    result = _hook(repo, env)

    assert result.returncode == 1
    assert "partially staged inputs" in result.stderr
    assert not log.exists()


def test_staged_manual_package_edit_is_validated_without_overwrite(
    tmp_path: Path,
) -> None:
    repo, env, log = _repo(tmp_path)
    package = repo / "plugins/legalquants-litigation/skills/demo/SKILL.md"
    package.write_text("manual edit\n", encoding="utf-8")
    _run(repo, "git", "add", str(package), env=env)

    result = _hook(repo, env)

    assert result.returncode != 0
    assert package.read_text(encoding="utf-8") == "manual edit\n"
    assert log.read_text(encoding="utf-8").splitlines() == ["plugin-pack:check"]


def test_rejects_staged_package_when_canonical_input_is_unstaged(
    tmp_path: Path,
) -> None:
    repo, env, log = _repo(tmp_path)
    source = repo / "skills/core/demo/SKILL.md"
    package = repo / "plugins/legalquants-litigation/skills/demo/SKILL.md"
    source.write_text("canonical v2\n", encoding="utf-8")
    package.write_text("canonical v2\n", encoding="utf-8")
    _run(repo, "git", "add", str(package), env=env)

    result = _hook(repo, env)

    assert result.returncode == 1
    assert "partially staged inputs" in result.stderr
    assert not log.exists()


def test_refuses_to_delete_ignored_files_in_generated_tree(tmp_path: Path) -> None:
    repo, env, log = _repo(tmp_path)
    source = repo / "skills/core/demo/SKILL.md"
    scratch = repo / "plugins/legalquants-litigation/.scratch"
    source.write_text("canonical v2\n", encoding="utf-8")
    scratch.write_text("preserve me\n", encoding="utf-8")
    _run(repo, "git", "add", str(source), env=env)

    result = _hook(repo, env)

    assert result.returncode == 1
    assert "refusing to overwrite" in result.stderr
    assert scratch.read_text(encoding="utf-8") == "preserve me\n"
    assert not log.exists()


def test_unrelated_commit_skips_package_work(tmp_path: Path) -> None:
    repo, env, log = _repo(tmp_path)
    notes = repo / "notes.txt"
    notes.write_text("unrelated\n", encoding="utf-8")
    _run(repo, "git", "add", str(notes), env=env)

    result = _hook(repo, env)

    assert result.returncode == 0
    assert not log.exists()


def test_pluginctl_hook_source_is_a_generator_input(tmp_path: Path) -> None:
    repo, env, log = _repo(tmp_path)
    source = repo / "packages/pluginctl/hooks/banner.py"
    source.parent.mkdir(parents=True)
    source.write_text("banner = 'synthetic'\n", encoding="utf-8")
    _run(repo, "git", "add", str(source), env=env)

    result = _hook(repo, env)

    assert result.returncode == 0
    assert log.read_text(encoding="utf-8").splitlines() == [
        "plugin-pack",
        "plugin-pack:check",
    ]


def test_framework_hook_covers_every_generator_boundary() -> None:
    hook = (ROOT / "packages/pluginctl/githooks/refresh-goldens").read_text(
        encoding="utf-8"
    )

    for boundary in (
        "^(skills/",
        "AGENTS\\.md$",
        "packages/pluginctl/(src|assets|hooks)/",
        "^plugins/(legalquants-litigation|legalquants-transactional|legalquants-companion)/",
        "\\.claude-plugin/marketplace\\.json",
        "\\.agents/plugins/marketplace\\.json",
        "plugin\\.release\\.yaml",
    ):
        assert boundary in hook


def test_ci_runs_the_public_check_command() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "run: pnpm check" in workflow
    assert "Validate manifests and committed Claude package freshness" not in workflow
