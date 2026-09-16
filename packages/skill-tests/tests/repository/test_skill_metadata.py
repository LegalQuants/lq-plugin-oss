"""Skill front matter routes; an OpenAI label, when present, is complete.

The front matter of ``SKILL.md`` is what every host uses to route to a skill.
``agents/openai.yaml`` is optional UI metadata for the OpenAI plugin picker;
a half-written one is worse than none, so when a skill ships one it must
carry every field and the LegalQuants accent colour.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SKILLS = ROOT / "skills"
BRAND_CHARCOAL = "#2d2d2d"


def _skill_dirs() -> list[Path]:
    return sorted(skill_md.parent for skill_md in SKILLS.glob("*/*/SKILL.md"))


def _front_matter(skill_md: Path) -> dict[str, str]:
    text = skill_md.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---", text, re.S)
    assert match, f"{skill_md} has no front matter"
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


def _yaml_scalars(path: Path) -> dict[str, str]:
    """Read the flat ``key: "value"`` lines of a small hand-written YAML file."""
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s+([a-z_]+):\s*\"?(.*?)\"?\s*$", line)
        if match:
            fields[match.group(1)] = match.group(2)
    return fields


def test_every_skill_front_matter_names_itself() -> None:
    for skill in _skill_dirs():
        fields = _front_matter(skill / "SKILL.md")
        assert fields.get("name") == skill.name, skill
        words = fields.get("description", "").split()
        assert len(words) >= 15, f"{skill.name}: description too short to route on"


def test_openai_label_is_complete_when_present() -> None:
    for skill in _skill_dirs():
        label = skill / "agents" / "openai.yaml"
        if not label.is_file():
            continue
        fields = _yaml_scalars(label)
        assert fields.get("display_name"), f"{skill.name}: display_name"
        assert len(fields.get("short_description", "").split()) >= 3, (
            f"{skill.name}: short_description"
        )
        assert fields.get("default_prompt"), f"{skill.name}: default_prompt"
        assert fields.get("brand_color", "").lower() == BRAND_CHARCOAL, (
            f"{skill.name}: brand_color must be LegalQuants charcoal"
        )
