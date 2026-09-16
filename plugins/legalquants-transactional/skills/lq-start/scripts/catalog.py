#!/usr/bin/env python3
"""List the installed CODEX for Legal skills, read from their own files.

The router never keeps a list of skills. Each skill's ``SKILL.md`` front matter
(name, description) and, when present, its ``agents/openai.yaml`` label
(display name, short description, example prompt) are the only sources. Add a
skill folder and it appears; remove one and it disappears.

    python3 catalog.py                 # this plugin, markdown, one line per skill
    python3 catalog.py --all-plugins   # every sibling plugin too, deduplicated
    python3 catalog.py --format line --prefix '$'
    python3 catalog.py --format json
    python3 catalog.py --format names

``--all-plugins`` walks up from the skills folder to the plugin folder, then to
the folder that holds every installed plugin, and reads ``*/skills/*/SKILL.md``
there. Both marketplaces lay plugins out as siblings, so the same walk works on
each host. With no siblings it falls back to this plugin alone.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import TypedDict

SELF_NAME = "lq-start"


class Skill(TypedDict):
    name: str
    plugin: str
    plugin_name: str
    display_name: str
    summary: str
    description: str
    default_prompt: str


def _front_matter(text: str) -> dict[str, str]:
    match = re.match(r"---\n(.*?)\n---", text, re.S)
    if not match:
        return {}
    fields: dict[str, str] = {}
    key: str | None = None
    for line in match.group(1).splitlines():
        head = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if head and not line.startswith(" "):
            key = head.group(1)
            value = head.group(2).strip()
            fields[key] = "" if value in (">-", ">", "|", "|-") else value
        elif key is not None:
            fields[key] = (fields[key] + " " + line.strip()).strip()
    return fields


def _label(path: Path) -> dict[str, str]:
    """Read the flat ``key: "value"`` lines of a small hand-written YAML file."""
    if not path.is_file():
        return {}
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r'^\s+([a-z_]+):\s*"?(.*?)"?\s*$', line)
        if match:
            fields[match.group(1)] = match.group(2)
    return fields


def _first_sentence(text: str, *, max_words: int = 28) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    sentence = match.group(1) if match else text
    words = sentence.split()
    if len(words) > max_words:
        sentence = " ".join(words[:max_words]).rstrip(",;:") + "…"
    return sentence


def _title(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("-"))


def _skill_files(skills_root: Path) -> list[Path]:
    return [
        *skills_root.glob("*/SKILL.md"),
        *skills_root.glob("*/*/SKILL.md"),
    ]


PLUGIN_MANIFESTS = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json")


def _is_plugin_dir(folder: Path) -> bool:
    return any((folder / manifest).is_file() for manifest in PLUGIN_MANIFESTS)


def _manifest(folder: Path) -> dict:
    for manifest in PLUGIN_MANIFESTS:
        path = folder / manifest
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
            return data if isinstance(data, dict) else {}
    return {}


def plugin_id(folder: Path) -> str:
    """The plugin's id: its manifest name, else its folder name."""
    name = _manifest(folder).get("name")
    return name if isinstance(name, str) and name else folder.name


def plugin_display_name(folder: Path) -> str:
    interface = _manifest(folder).get("interface")
    if isinstance(interface, dict):
        name = interface.get("displayName")
        if isinstance(name, str) and name:
            return name
    return plugin_id(folder)


def _has_skills(folder: Path) -> bool:
    return (folder / "skills").is_dir() and bool(_skill_files(folder / "skills"))


def _newest(folders: list[Path]) -> Path:
    return max(folders, key=lambda f: f.stat().st_mtime)


def _plugins_under(level: Path) -> list[Path]:
    """Plugin folders one level down (``<plugins>/<id>``) or two levels down
    (``<cache>/<id>/<version>``, where Codex keeps installed plugins). For a
    versioned folder only the newest version counts."""
    found: list[Path] = []
    for child in sorted(level.iterdir()):
        if not child.is_dir():
            continue
        if _is_plugin_dir(child):
            if _has_skills(child):
                found.append(child)
            continue
        versions = [
            v
            for v in child.iterdir()
            if v.is_dir() and _is_plugin_dir(v) and _has_skills(v)
        ]
        if versions:
            found.append(_newest(versions))
    return found


def _codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _codex_disabled() -> set[str]:
    """``<id>@<marketplace>`` keys Codex's config marks ``enabled = false``.

    Codex keeps disabled plugins in its cache, so presence alone is not
    installation. Anything unreadable counts as enabled: the shelf must never
    lose a plugin because a config file could not be parsed."""
    config = _codex_home() / "config.toml"
    if not config.is_file():
        return set()
    try:
        text = config.read_text(encoding="utf-8")
    except OSError:
        return set()
    disabled: set[str] = set()
    section: str | None = None
    for line in text.splitlines():
        head = re.match(r'^\s*\[plugins\."([^"]+)"\]\s*$', line)
        if head:
            section = head.group(1)
            continue
        if line.startswith("["):
            section = None
            continue
        if section and re.match(r"^\s*enabled\s*=\s*false\s*$", line):
            disabled.add(section)
    return disabled


def _is_enabled(plugin_dir: Path, disabled: set[str]) -> bool:
    """A Codex-cached plugin is installed only when its config entry is not
    ``enabled = false``.

    The cache path is ``<codex>/plugins/cache/<marketplace>/<id>/<version>``."""
    if not disabled:
        return True
    cache = _codex_home() / "plugins" / "cache"
    try:
        marketplace, folder_id, _version = (
            plugin_dir.resolve().relative_to(cache.resolve()).parts[:3]
        )
    except ValueError:
        return True
    for key in (f"{plugin_id(plugin_dir)}@{marketplace}", f"{folder_id}@{marketplace}"):
        if key in disabled:
            return False
    return True


def sibling_plugin_roots(skills_root: Path) -> list[Path]:
    """Every ``skills`` folder of every plugin installed beside this one.

    The walk is: skills folder → plugin folder → up to three ancestors, reading
    the plugins found one level down (``<plugins>/<id>/skills``, the shape a
    marketplace checkout has) or two levels down (``<cache>/<id>/<version>/skills``,
    the shape Codex installs into). The first ancestor that holds this plugin
    and at least one other wins. A folder counts as a plugin only when it
    carries a plugin manifest, and a Codex-cached plugin only when its config
    entry is enabled. In the authoring repository the skills folder sits under
    the repo root, which has no plugin manifest, so the walk stops and only
    ``skills_root`` is read.
    """
    skills_root = skills_root.resolve()
    plugin_dir = skills_root.parent
    if not _is_plugin_dir(plugin_dir):
        return [skills_root]
    disabled = _codex_disabled()
    level = plugin_dir
    for _ in range(3):
        level = level.parent
        if level == level.parent:
            break
        plugins = [p for p in _plugins_under(level) if _is_enabled(p, disabled)]
        roots = sorted(p / "skills" for p in plugins)
        if skills_root in roots and len(roots) > 1:
            return roots
    return [skills_root]


def load_skills(
    skills_root: Path, *, include_self: bool = False, all_plugins: bool = False
) -> list[Skill]:
    skills: list[Skill] = []
    roots = sibling_plugin_roots(skills_root) if all_plugins else [skills_root]
    skill_files: list[tuple[Path, str, str]] = []
    for root in roots:
        # Installed: <plugins>/<plugin>/skills/<name>. Authoring: skills/<group>/<name>.
        if _is_plugin_dir(root.parent):
            plugin = plugin_id(root.parent)
            plugin_name = plugin_display_name(root.parent)
            skill_files.extend(
                (path, plugin, plugin_name) for path in _skill_files(root)
            )
        else:
            skill_files.extend(
                (path, path.parent.parent.name, path.parent.parent.name)
                for path in _skill_files(root)
            )
    seen: set[str] = set()
    for skill_md, plugin, plugin_name in sorted(set(skill_files)):
        folder = skill_md.parent
        fm = _front_matter(skill_md.read_text(encoding="utf-8"))
        name = fm.get("name") or folder.name
        if name == SELF_NAME and not include_self:
            continue
        if name in seen:
            continue
        seen.add(name)
        label = _label(folder / "agents" / "openai.yaml")
        description = fm.get("description", "")
        summary = label.get("short_description") or _first_sentence(description)
        skills.append(
            {
                "name": name,
                "plugin": plugin,
                "plugin_name": plugin_name,
                "display_name": label.get("display_name") or _title(name),
                "summary": summary.rstrip("."),
                "description": description,
                "default_prompt": label.get("default_prompt", ""),
            }
        )
    return skills


def render_md(skills: list[Skill], *, prefix: str = "/") -> str:
    lines: list[str] = []
    for skill in skills:
        summary = skill["summary"]
        stop = "" if summary.endswith("…") else "."
        line = f"- **{prefix}{skill['name']}** — {summary}{stop}"
        if skill["default_prompt"]:
            line += f' _Try: "{skill["default_prompt"]}"_'
        lines.append(line)
    return "\n".join(lines)


def render_line(skills: list[Skill], *, prefix: str = "/") -> str:
    return " · ".join(f"{prefix}{skill['name']}" for skill in skills)


def render_names(skills: list[Skill]) -> str:
    return "\n".join(skill["name"] for skill in skills)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="catalog.py", description=__doc__)
    parser.add_argument(
        "--format", choices=("md", "line", "json", "names"), default="md"
    )
    parser.add_argument("--include-self", action="store_true")
    parser.add_argument(
        "--all-plugins",
        action="store_true",
        help="also read every plugin installed beside this one",
    )
    parser.add_argument(
        "--prefix",
        default="/",
        help="how the host invokes a skill: '/' (default) or '$'",
    )
    parser.add_argument(
        "--skills-root",
        type=Path,
        default=next(
            parent
            for parent in Path(__file__).resolve().parents
            if parent.name == "skills"
        ),
        help="canonical skills root or packaged skills folder (default: this plugin's)",
    )
    args = parser.parse_args(argv[1:])
    skills = load_skills(
        args.skills_root,
        include_self=args.include_self,
        all_plugins=args.all_plugins,
    )
    if args.format == "json":
        print(json.dumps(skills, indent=1, ensure_ascii=False))
    elif args.format == "line":
        print(render_line(skills, prefix=args.prefix))
    elif args.format == "names":
        print(render_names(skills))
    else:
        print(render_md(skills, prefix=args.prefix))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
