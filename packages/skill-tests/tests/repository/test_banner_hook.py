"""The startup banner never writes, never breaks, and says the right thing."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BANNER = ROOT / "packages/pluginctl/hooks/banner.py"


def _run(
    lq_home: Path,
    *,
    claude: bool = False,
    stdin: str = "{}",
    banner_dir: Path | None = None,
    banner: Path = BANNER,
) -> str:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_ROOT"}
    env["LQ_HOME"] = str(lq_home)
    if claude:
        env["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
    if banner_dir is not None:
        env["LQ_BANNER_DIR"] = str(banner_dir)
    return subprocess.run(
        [sys.executable, str(banner)],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        input=stdin,
    ).stdout


def _card(payload: str) -> list[str]:
    data = json.loads(payload)
    context = data["hookSpecificOutput"]["additionalContext"]
    assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    return context.split("\n\n", 1)[0].splitlines()


def test_new_user_sees_the_invitation(tmp_path: Path) -> None:
    payload = _run(tmp_path / "missing")
    card = _card(payload)
    assert len(card) == 4
    assert "CODEX FOR LEGAL" in card[0]
    assert "New here? $lq-start" in card[1]
    assert card[2].endswith("Shelf: $lq-start")
    assert "Not legal advice" in card[3]
    assert json.loads(payload)["systemMessage"].startswith("CODEX for Legal · New here")
    assert not (tmp_path / "missing").exists()


def _packaged(tmp_path: Path, first_move: str | None) -> Path:
    """A plugin laid out as pack emits it: hooks/ beside skills/, one bundle."""
    plugin = tmp_path / "plugins" / "legalquants-litigation"
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / ".codex-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    hooks = plugin / "hooks"
    hooks.mkdir()
    shutil.copy(BANNER, hooks / "banner.py")
    if first_move is not None:
        (hooks / "banner.json").write_text(
            json.dumps({"plugin": "Litigators", "first_move": first_move}),
            encoding="utf-8",
        )
    catalog = ROOT / "skills" / "core" / "lq-start" / "scripts" / "catalog.py"
    dest = plugin / "skills" / "lq-start" / "scripts"
    dest.mkdir(parents=True)
    shutil.copy(catalog, dest / "catalog.py")
    (plugin / "skills" / "lq-start" / "SKILL.md").write_text(
        "---\nname: lq-start\ndescription: The door.\n---\n", encoding="utf-8"
    )
    for name in ("cite-check", "regulatory"):
        (plugin / "skills" / name).mkdir()
        (plugin / "skills" / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: A skill. Use when needed.\n---\n",
            encoding="utf-8",
        )
    return hooks / "banner.py"


def _run_packaged(banner: Path, lq_home: Path) -> str:
    return _run(lq_home, banner=banner)


def _sibling(tmp_path: Path, plugin: str, skill: str) -> None:
    """A second packaged plugin beside the one ``_packaged`` builds."""
    folder = tmp_path / "plugins" / plugin
    (folder / ".codex-plugin").mkdir(parents=True)
    (folder / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": plugin}), encoding="utf-8"
    )
    (folder / "skills" / skill).mkdir(parents=True)
    (folder / "skills" / skill / "SKILL.md").write_text(
        f"---\nname: {skill}\ndescription: A skill. Use when needed.\n---\n",
        encoding="utf-8",
    )


def test_packaged_card_names_the_plugins_first_move(tmp_path: Path) -> None:
    banner = _packaged(tmp_path, "Have a filing? $cite-check on it.")
    payload = _run_packaged(banner, tmp_path / "missing")
    card = _card(payload)
    assert card[1].endswith("Have a filing? $cite-check on it.")
    assert card[2].endswith("Shelf: $lq-start   ·   2 skills installed")
    assert json.loads(payload)["systemMessage"] == (
        "CODEX for Legal · Have a filing? $cite-check on it. · $lq-start for the shelf"
    )


def test_first_move_naming_an_uninstalled_skill_is_not_shown(tmp_path: Path) -> None:
    banner = _packaged(tmp_path, "Have a markup? $read-redline on it.")
    card = _card(_run_packaged(banner, tmp_path / "missing"))
    assert "read-redline" not in "\n".join(card)
    assert "New here? $lq-start" in card[1]


def test_returning_user_keeps_the_status_over_the_first_move(tmp_path: Path) -> None:
    banner = _packaged(tmp_path, "Have a filing? $cite-check on it.")
    home = tmp_path / "lq"
    home.mkdir()
    (home / "profile.json").write_text("{}", encoding="utf-8")
    card = _card(_run_packaged(banner, home))
    assert card[1].endswith("0 moments kept")
    assert "cite-check" not in card[1]


def test_returning_user_sees_level_and_moments(tmp_path: Path) -> None:
    home = tmp_path / "lq"
    home.mkdir()
    (home / "profile.json").write_text(
        json.dumps({"fluency": {"level": "Early Builder"}}), encoding="utf-8"
    )
    events = [
        {"type": "lq_moment"},
        {"type": "lq_moment"},
        {"type": "debrief_run", "at": "2020-01-01T00:00:00+00:00"},
    ]
    (home / "journey.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )
    before = sorted(p.name for p in home.iterdir())
    payload = _run(home)
    card = _card(payload)
    assert "2 moments kept · last debrief" in card[1]
    assert "Early Builder" not in card[1]
    assert json.loads(payload)["systemMessage"] == (
        "CODEX for Legal · 2 moments kept · $lq-start for the shelf"
    )
    assert sorted(p.name for p in home.iterdir()) == before


def test_codex_setting_claude_plugin_root_changes_nothing(tmp_path: Path) -> None:
    """Codex exports CLAUDE_PLUGIN_ROOT for plugin hooks (live finding,
    2026-09-08, Codex 0.153): the card must still be the JSON form with $names."""
    payload = _run(tmp_path / "missing", claude=True)
    card = _card(payload)
    assert "New here? $lq-start" in card[1]
    assert "/lq-start" not in payload


def test_one_card_per_session(tmp_path: Path) -> None:
    """Every installed plugin runs this hook; the first prints, the rest stand down."""
    stdin = json.dumps({"session_id": "sess-1", "hook_event_name": "SessionStart"})
    first = _run(tmp_path / "missing", stdin=stdin, banner_dir=tmp_path / "t")
    second = _run(tmp_path / "missing", stdin=stdin, banner_dir=tmp_path / "t")
    other = _run(
        tmp_path / "missing",
        stdin=json.dumps({"session_id": "sess-2"}),
        banner_dir=tmp_path / "t",
    )
    assert "CODEX FOR LEGAL" in first
    assert second == ""
    assert "CODEX FOR LEGAL" in other


def test_siblings_installed_drop_the_first_move_and_count_the_union(
    tmp_path: Path,
) -> None:
    banner = _packaged(tmp_path, "Have a filing? $cite-check on it.")
    _sibling(tmp_path, "legalquants-transactional", "read-redline")
    payload = _run_packaged(banner, tmp_path / "missing")
    card = _card(payload)
    assert "New here? $lq-start" in card[1]
    assert "cite-check" not in card[1]
    assert card[2].endswith("Shelf: $lq-start   ·   3 skills installed")


def test_hooks_manifest_has_only_the_hooks_key() -> None:
    """Codex 0.142 rejects the whole file on any other top-level key."""
    manifest = json.loads(
        (ROOT / "packages/pluginctl/hooks/openai.json").read_text(encoding="utf-8")
    )
    assert set(manifest) == {"hooks"}
    assert [h["matcher"] for h in manifest["hooks"]["SessionStart"]] == [
        "startup|resume|clear|compact",
        "startup",
    ]
