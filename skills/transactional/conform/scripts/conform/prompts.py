"""Load versioned, packaged prompts for conform mapping workers."""

from __future__ import annotations

import hashlib
from functools import cache
from pathlib import Path

_PROMPT_ROOT = Path(__file__).resolve().parents[2] / "references" / "prompts"
_PROMPT_FILES = {
    "mapping": "mapping.md",
    "leakage-scan": "leakage-scan.md",
    "escalation": "escalation.md",
    "dispatch": "dispatch.md",
}
_PROMPT_VERSIONS = {
    "mapping": "mapping-v1",
    "leakage-scan": "leakage-scan-v1",
    "escalation": "escalation-v1",
    "dispatch": "dispatch-v1",
}
_MODE_PROMPTS = {
    "conform_selected_text": "mapping",
    "precedent_leakage_check": "leakage-scan",
}


class PromptRegistryError(ValueError):
    """Raised when a packaged prompt cannot be loaded safely."""


@cache
def _read_prompt(name: str) -> str:
    try:
        filename = _PROMPT_FILES[name]
    except KeyError as exc:
        raise PromptRegistryError(f"unknown conform prompt: {name}") from exc
    path = _PROMPT_ROOT / filename
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PromptRegistryError(f"unable to read packaged prompt: {path}") from exc
    if not text:
        raise PromptRegistryError(f"packaged prompt is empty: {path}")
    if "dev-tools" in text.casefold():
        raise PromptRegistryError(f"packaged prompt references dev-tools: {path}")
    return text


def prompt_for_mode(mode: str) -> str:
    """Return the canonical mapping-stage instruction text for a run mode."""

    try:
        name = _MODE_PROMPTS[mode]
    except KeyError as exc:
        raise PromptRegistryError(f"unsupported conform mode: {mode}") from exc
    return _read_prompt(name)


def prompt_inventory() -> dict[str, dict[str, str]]:
    """Return version and hash metadata for every model-facing prompt."""

    inventory = {}
    for name in _PROMPT_FILES:
        text = _read_prompt(name)
        inventory[name] = {
            "version": _PROMPT_VERSIONS[name],
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
    return inventory


def render_mapping_dispatch_prompt(
    *,
    packet_path: str | Path,
    response_path: str | Path,
    validation_command: str,
) -> str:
    """Render the standardized outer task given to a generic mapping worker."""

    template = _read_prompt("dispatch")
    rendered = template.format(
        stage="mapping",
        packet_path=Path(packet_path).resolve(),
        response_path=Path(response_path).resolve(),
        validation_command=validation_command,
    )
    if any(
        placeholder in rendered
        for placeholder in (
            "{stage}",
            "{packet_path}",
            "{response_path}",
            "{validation_command}",
        )
    ):
        raise PromptRegistryError("dispatch prompt contains unresolved placeholders")
    return rendered
