"""The front door's map names every shipping skill, and nothing that does not ship."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SKILLS = ROOT / "skills"
MAP = SKILLS / "core" / "lq-start" / "references" / "map.md"
SKILL_MD = SKILLS / "core" / "lq-start" / "SKILL.md"

ENTRY = re.compile(
    r"→\s*`\$([a-z0-9-]+)`\s*\((core|transactional|litigation|companion)\)"
)
ANY_NAME = re.compile(r"`\$([a-z0-9-]+)`")


def _shipping() -> dict[str, str]:
    """skill name -> group folder, from the canonical tree."""
    return {
        path.parent.name: path.parent.parent.name
        for path in SKILLS.glob("*/*/SKILL.md")
    }


def test_every_shipping_skill_has_an_entry_with_the_right_group() -> None:
    text = MAP.read_text(encoding="utf-8")
    entries = dict(ENTRY.findall(text))
    expected = {
        name: group for name, group in _shipping().items() if name != "lq-start"
    }
    missing = set(expected) - set(entries)
    assert not missing, f"map.md has no entry for {sorted(missing)}"
    for name, group in expected.items():
        assert entries[name] == group, (
            f"{name} is tagged {entries[name]}, ships in {group}"
        )


def test_every_skill_has_exactly_one_entry() -> None:
    """Two entries for one skill say two different things about it."""
    names = [name for name, _ in ENTRY.findall(MAP.read_text(encoding="utf-8"))]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    assert not duplicated, f"map.md has more than one entry for {duplicated}"


def test_map_header_names_the_plugins_from_the_release_manifest() -> None:
    """The router names the plugin a missing skill lives in from the map's
    header, so the ids there must be the ids that ship."""
    manifest = (ROOT / "plugin.release.yaml").read_text(encoding="utf-8")
    ids = re.findall(r"^\s+- id:\s*(\S+)", manifest, re.M)
    assert ids, "plugin.release.yaml lists no plugins"
    header = MAP.read_text(encoding="utf-8").split("## ", 1)[0]
    for plugin_id in ids:
        assert f"`{plugin_id}`" in header, f"map.md header does not name {plugin_id}"
    for group in ("core", "litigation", "transactional", "companion"):
        assert f"`{group}`" in header


def test_map_names_nothing_that_does_not_ship() -> None:
    text = MAP.read_text(encoding="utf-8")
    named = set(ANY_NAME.findall(text))
    unknown = named - set(_shipping())
    assert not unknown, f"map.md names skills that do not ship: {sorted(unknown)}"
    assert "lq-start" not in named, "the map does not name the front door itself"


def test_front_door_is_typed_not_triggered() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "disable-model-invocation: true" in text.split("---")[1]
    yaml = (SKILLS / "core" / "lq-start" / "agents" / "openai.yaml").read_text(
        encoding="utf-8"
    )
    assert "allow_implicit_invocation: false" in yaml


def test_front_door_shows_the_shelf_next_door() -> None:
    """Installed from the catalog; the rest from the map, named but never
    offered."""
    text = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    assert "Installed names only from the catalog output" in text
    assert "not-installed names only from the map, never offered as a pick" in text
    assert "In other LegalQuants plugins" in text
    assert "When everything in the map is installed, the block is not shown" in text
    yaml = (SKILLS / "core" / "lq-start" / "agents" / "openai.yaml").read_text(
        encoding="utf-8"
    )
    assert "Same door in every LegalQuants plugin; pick any" in yaml


def test_front_door_never_touches_the_profile() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "profile_store" not in text
    assert "debrief_scan" not in text


def test_front_door_diagnoses_a_short_catalog() -> None:
    """The door still points at reinstalling a plugin when the shelf is broken,
    but never by comparing counts: the catalog omits /lq-start itself, so a
    count check would warn every time."""
    text = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    assert "omits `/lq-start` itself by design" in text
    assert "Do not compare counts" in text
    assert "reinstalling that plugin" in text
