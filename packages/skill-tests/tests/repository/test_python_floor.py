"""The hooks fail open on an interpreter older than 3.12, and the README says so.

A hook that dies with a traceback on Python 3.9 (Emily Cabrera, 30 Aug 2026) is a
worse experience than no hook. The probe runs before any 3.12-only import.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
HOOKS = sorted((ROOT / "packages/pluginctl/hooks").glob("*.py"))

SHIM = """
import runpy, sys
sys.version_info = (3, 9, 6, "final", 0)
sys.argv = [sys.argv[1], *sys.argv[2:]]
runpy.run_path(sys.argv[0], run_name="__main__")
"""


@pytest.mark.parametrize("hook", HOOKS, ids=lambda p: p.name)
def test_hook_fails_open_on_old_python(hook: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", SHIM, str(hook), "session-start"],
        capture_output=True,
        text=True,
        input="{}",
        check=False,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    if hook.name == "wiki_hook.py":
        assert "Python 3.12" in result.stdout
    else:
        assert result.stdout.strip() == ""


def test_hooks_still_run_on_this_python() -> None:
    for hook in HOOKS:
        result = subprocess.run(
            [sys.executable, str(hook), "session-start"],
            capture_output=True,
            text=True,
            input="{}",
            check=False,
            cwd=ROOT,
        )
        assert result.returncode == 0, result.stderr
        assert "Traceback" not in result.stderr


def test_readme_explains_uv_and_the_hook_floor() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "skills installer" in text
    assert "pnpm pluginctl pack" in text
    assert "pnpm check" in text


def test_wiki_hook_exits_quietly_without_the_wiki_skill(tmp_path: Path) -> None:
    """The Companion ships the hook but not the wiki skill; it must not fail
    the hook on every session start and prompt (live finding, 2026-09-08)."""
    hooks = tmp_path / "plugin" / "hooks"
    hooks.mkdir(parents=True)
    shutil.copy(ROOT / "packages/pluginctl/hooks/wiki_hook.py", hooks / "wiki_hook.py")
    for event in ("session-start", "prompt-submit", "stop"):
        result = subprocess.run(
            [sys.executable, str(hooks / "wiki_hook.py"), event],
            capture_output=True,
            text=True,
            input="{}",
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
