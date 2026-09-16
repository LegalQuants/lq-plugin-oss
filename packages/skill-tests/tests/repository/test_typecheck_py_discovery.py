"""Python typecheck covers every first-party tree, not a hardcoded skill name."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "packages/pluginctl/scripts/typecheck-py.sh"


def test_refresh_goldens_regenerates_without_staging_or_amending() -> None:
    text = (ROOT / "packages/pluginctl/githooks/refresh-goldens").read_text(
        encoding="utf-8"
    )
    assert "plugin-pack" in text
    assert "plugin-pack:check" in text
    assert "git add" not in text
    assert "git commit" not in text


def test_package_json_uses_discovery_script() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    command = package["scripts"]["typecheck:py"]
    assert "packages/pluginctl/scripts/typecheck-py.sh" in command
    assert "skills/litigation/cite-check" not in command


def test_ci_uses_the_same_discovery_script() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    script = (ROOT / "packages/pluginctl/scripts/typecheck-py.sh").read_text(
        encoding="utf-8"
    )
    assert "pnpm check" in workflow
    assert "uv run ty check skills/litigation/cite-check" not in workflow
    assert "skills/*/skill.yaml" not in script


def test_discovery_lists_first_party_trees_and_skill_script_paths(
    tmp_path: Path,
) -> None:
    (tmp_path / "skills/core/alpha/scripts").mkdir(parents=True)
    (tmp_path / "skills/core/alpha/scripts/shared").mkdir()
    (tmp_path / "skills/core/alpha/SKILL.md").write_text("# alpha\n", encoding="utf-8")
    (tmp_path / "skills/litigation/gamma/scripts").mkdir(parents=True)
    (tmp_path / "skills/litigation/gamma/SKILL.md").write_text(
        "# gamma\n", encoding="utf-8"
    )
    (tmp_path / "skills/transactional/beta").mkdir(parents=True)
    (tmp_path / "skills/transactional/beta/SKILL.md").write_text(
        "# beta\n", encoding="utf-8"
    )
    (tmp_path / "packages/skill-tests/tests").mkdir(parents=True)
    (tmp_path / "packages/pluginctl/hooks").mkdir(parents=True)

    result = subprocess.run(
        ["sh", str(SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "TYPECHECK_ROOT": str(tmp_path), "TYPECHECK_PY_PRINT": "1"},
    )
    paths = result.stdout.split()

    assert paths[:2] == ["skills", "packages"]
    assert "skills/transactional/beta" not in paths
    extra_paths = [
        paths[index + 1]
        for index, token in enumerate(paths)
        if token == "--extra-search-path"
    ]
    assert extra_paths == [
        "skills/core/alpha/scripts",
        "skills/litigation/gamma/scripts",
        "skills/core/alpha/scripts/shared",
    ]
