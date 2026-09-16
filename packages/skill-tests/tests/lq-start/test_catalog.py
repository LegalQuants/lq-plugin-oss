"""The front door reads the shelf from the skills' own files, never from a list."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SKILLS = ROOT / "skills"
CATALOG = SKILLS / "core" / "lq-start" / "scripts" / "catalog.py"


def _run(*args: str, skills_root: Path = SKILLS) -> str:
    result = subprocess.run(
        [sys.executable, str(CATALOG), "--skills-root", str(skills_root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _shipping_names() -> set[str]:
    return {path.parent.name for path in SKILLS.glob("*/*/SKILL.md")}


def test_catalog_lists_every_shipping_skill_but_itself() -> None:
    listed = json.loads(_run("--format", "json"))
    names = {s["name"] for s in listed}
    assert names == _shipping_names() - {"lq-start"}
    for skill in listed:
        assert skill["summary"], skill["name"]
        assert skill["display_name"], skill["name"]
        assert skill["plugin"], skill["name"]


def test_catalog_names_the_plugin_each_skill_came_from(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    for plugin, name in (("lq-lit", "cite-check"), ("lq-txn", "read-redline")):
        skill = plugins / plugin / "skills" / name
        skill.mkdir(parents=True)
        (plugins / plugin / ".claude-plugin").mkdir()
        (plugins / plugin / ".claude-plugin" / "plugin.json").write_text("{}")
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: A skill. Use when needed.\n---\n",
            encoding="utf-8",
        )
    listed = json.loads(
        _run(
            "--all-plugins",
            "--format",
            "json",
            skills_root=plugins / "lq-lit" / "skills",
        )
    )
    assert {s["name"]: s["plugin"] for s in listed} == {
        "cite-check": "lq-lit",
        "read-redline": "lq-txn",
    }


def test_catalog_picks_up_a_new_skill_folder(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    shutil.copytree(SKILLS, root, ignore=shutil.ignore_patterns("__pycache__"))
    fake = root / "zz-fake"
    fake.mkdir()
    (fake / "SKILL.md").write_text(
        "---\nname: zz-fake\ndescription: A skill added after the front door shipped. "
        "Use when the shelf must prove it is read at run time.\n---\n# Fake\n",
        encoding="utf-8",
    )
    md = _run(skills_root=root)
    assert "**/zz-fake**" in md
    assert "A skill added after the front door shipped" in md


def test_markdown_and_line_formats_agree() -> None:
    md = _run("--format", "md")
    line = _run("--format", "line")
    md_names = re.findall(r"\*\*/([a-z0-9-]+)\*\*", md)
    assert [f"/{n}" for n in md_names] == line.strip().split(" · ")


def test_prefix_renders_the_host_form() -> None:
    line = _run("--format", "line", "--prefix", "$")
    assert line.startswith("$")
    assert "/" not in line
    md = _run("--format", "md", "--prefix", "$")
    assert "**$" in md and "**/" not in md


def _fake_plugin(
    plugins: Path, plugin: str, skill: str, *, manifest: bool = True
) -> Path:
    folder = plugins / plugin / "skills" / skill
    folder.mkdir(parents=True)
    if manifest:
        (plugins / plugin / ".codex-plugin").mkdir(exist_ok=True)
        manifest_path = plugins / plugin / ".codex-plugin" / "plugin.json"
        manifest_path.write_text("{}", encoding="utf-8")
    (folder / "SKILL.md").write_text(
        f"---\nname: {skill}\ndescription: Fixture skill {skill}. Use in tests.\n---\n",
        encoding="utf-8",
    )
    return plugins / plugin / "skills"


def test_all_plugins_walks_sibling_plugins(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    root_a = _fake_plugin(plugins, "plugin-a", "alpha")
    _fake_plugin(plugins, "plugin-b", "beta")
    _fake_plugin(plugins, "plugin-b", "alpha")  # core skill shipped twice

    own = _run("--format", "names", skills_root=root_a).split()
    assert own == ["alpha"]

    everything = _run("--format", "names", "--all-plugins", skills_root=root_a).split()
    assert everything == ["alpha", "beta"], "siblings read once, duplicates dropped"


def test_all_plugins_falls_back_when_alone(tmp_path: Path) -> None:
    lonely = _fake_plugin(tmp_path / "somewhere", "only", "solo")
    names = _run("--format", "names", "--all-plugins", skills_root=lonely).split()
    assert names == ["solo"]


def test_all_plugins_ignores_folders_without_a_manifest(tmp_path: Path) -> None:
    """A repo checkout beside other repos must not sweep their skills in."""
    plugins = tmp_path / "Documents"
    mine = _fake_plugin(plugins, "this-repo", "alpha", manifest=False)
    _fake_plugin(plugins, "other-repo", "stranger", manifest=False)
    names = _run("--format", "names", "--all-plugins", skills_root=mine).split()
    assert names == ["alpha"]


def test_all_plugins_reads_the_canonical_tree_alone() -> None:
    names = set(_run("--format", "names", "--all-plugins").split())
    assert names == _shipping_names() - {"lq-start"}


def test_debrief_text_names_no_other_skill() -> None:
    """The debrief recommends from the catalog output, never from its own text."""
    others = _shipping_names() - {"lq-start", "lq-reflect"}
    text = (SKILLS / "companion" / "lq-reflect" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    # Relative filesystem pointers (../legalquants/references/…) are not
    # invocations; strip them before the hard-coded-name check.
    for name in others:
        text = text.replace(f"../{name}/", "").replace(f"../../companion/{name}/", "")
    for name in others:
        assert f"/{name}" not in text, f"SKILL.md hard-codes /{name}"


def _cached_plugin(
    codex_home: Path,
    plugin: str,
    skill: str,
    *,
    version: str = "0.1.0",
    marketplace: str = "lq",
) -> Path:
    """A plugin laid out as Codex installs it: cache/<marketplace>/<id>/<version>."""
    folder = codex_home / "plugins" / "cache" / marketplace / plugin / version
    (folder / ".codex-plugin").mkdir(parents=True)
    (folder / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": plugin, "interface": {"displayName": plugin.title()}}),
        encoding="utf-8",
    )
    skill_dir = folder / "skills" / skill
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill}\ndescription: Fixture skill {skill}. Use in tests.\n---\n",
        encoding="utf-8",
    )
    return folder / "skills"


def _run_codex(codex_home: Path, skills_root: Path) -> list[dict]:
    env = {**os.environ, "CODEX_HOME": str(codex_home)}
    result = subprocess.run(
        [
            sys.executable,
            str(CATALOG),
            "--skills-root",
            str(skills_root),
            "--all-plugins",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return json.loads(result.stdout)


def test_all_plugins_walks_the_versioned_codex_cache(tmp_path: Path) -> None:
    """Codex caches plugins as cache/<marketplace>/<id>/<version>/skills, one
    level deeper than a marketplace checkout. Live finding, 2026-09-08: the
    three Start entries each saw only their own plugin."""
    home = tmp_path / "codex"
    mine = _cached_plugin(home, "lq-companion", "legalquants")
    _cached_plugin(home, "lq-litigation", "cite-check")
    listed = _run_codex(home, mine)
    assert {s["name"]: s["plugin"] for s in listed} == {
        "legalquants": "lq-companion",
        "cite-check": "lq-litigation",
    }
    assert {s["plugin_name"] for s in listed} == {"Lq-Companion", "Lq-Litigation"}


def test_only_the_newest_cached_version_counts(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    mine = _cached_plugin(home, "lq-companion", "legalquants")
    old = _cached_plugin(home, "lq-litigation", "stale-skill", version="0.0.9")
    new = _cached_plugin(home, "lq-litigation", "cite-check", version="0.1.0")
    os.utime(old.parent, (1, 1))
    os.utime(new.parent, None)
    names = {s["name"] for s in _run_codex(home, mine)}
    assert names == {"legalquants", "cite-check"}


def test_a_disabled_codex_plugin_is_not_installed(tmp_path: Path) -> None:
    """Codex keeps disabled plugins in the cache; the config says which are on."""
    home = tmp_path / "codex"
    mine = _cached_plugin(home, "lq-companion", "legalquants")
    _cached_plugin(home, "lq-litigation", "cite-check")
    _cached_plugin(home, "lq-old", "retired-skill")
    (home / "config.toml").write_text(
        '[plugins."lq-companion@lq"]\nenabled = true\n\n'
        '[plugins."lq-old@lq"]\nenabled = false\n\n'
        '[plugins."lq-litigation@lq"]\nenabled = true\n',
        encoding="utf-8",
    )
    names = {s["name"] for s in _run_codex(home, mine)}
    assert names == {"legalquants", "cite-check"}
