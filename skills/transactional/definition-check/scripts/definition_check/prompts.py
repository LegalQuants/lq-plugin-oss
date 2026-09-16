"""Load versioned, packaged prompts for definition-check review workers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cache
from pathlib import Path


class PromptRegistryError(ValueError):
    """Raised when a packaged prompt cannot be loaded safely."""


@dataclass(frozen=True)
class PromptSpec:
    stage: str
    version: str
    instruction: str
    sha256: str
    decision_codes: tuple[tuple[int, str], ...]
    review_reason_codes: tuple[tuple[int, str | None], ...]
    output_schema: tuple[str, ...]


_PROMPT_ROOT = Path(__file__).resolve().parents[2] / "references" / "prompts"
_PROMPT_FILES = {
    "discovery": "discovery.md",
    "semantic": "semantic.md",
    "occurrence": "occurrence.md",
    "reference": "reference.md",
    "dispatch": "dispatch.md",
}
_PROMPT_VERSIONS = {
    "discovery": "discovery-v2",
    "semantic": "semantic-v9",
    "occurrence": "occurrence-v7",
    "reference": "reference-v3",
    "dispatch": "dispatch-v3",
}
_DECISION_CODES = {
    "discovery": (),
    "semantic": (
        (1, "confirmed_defined"),
        (2, "confirmed_alias"),
        (3, "confirmed_undefined"),
        (4, "rejected_not_a_term"),
        (5, "needs_review"),
        (6, "insufficient_evidence"),
        (7, "confirmed_external_reference"),
        (8, "rejected_proper_name"),
    ),
    "occurrence": (
        (1, "defined_term_use"),
        (2, "ordinary_language"),
        (3, "inconsistent_capitalization"),
        (4, "needs_review"),
        (5, "insufficient_evidence"),
        (6, "shadowed_by_overlapping_term"),
        (7, "proper_name_component"),
    ),
    "reference": (
        (1, "resolved"),
        (2, "broken"),
        (3, "out_of_scope"),
        (4, "needs_review"),
        (5, "insufficient_evidence"),
    ),
    "dispatch": (),
}
_REVIEW_REASON_CODES = (
    (0, None),
    (1, "missing_external_evidence"),
    (2, "ambiguous_term_identity"),
    (3, "uncertain_occurrence_identity"),
    (4, "incomplete_source_context"),
    (5, "ambiguous_reference"),
)
_OUTPUT_SCHEMAS = {
    "discovery": ("fragment", "start", "end", "term", "note"),
    "semantic": (
        "item",
        "decision",
        "evidence_contexts",
        "definition_spans",
        "note",
        "canonical_item",
        "review_reason",
    ),
    "occurrence": ("item", "decision", "note", "review_reason"),
    "reference": (
        "item",
        "decision",
        "evidence_contexts",
        "note",
        "review_reason",
    ),
    "dispatch": (),
}


@cache
def _read_prompt(name: str) -> str:
    try:
        filename = _PROMPT_FILES[name]
    except KeyError as exc:
        raise PromptRegistryError(f"unknown definition-check prompt: {name}") from exc
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


@cache
def get_prompt(stage: str) -> PromptSpec:
    """Return one immutable stage prompt and its reproducibility metadata."""

    if stage == "dispatch":
        raise PromptRegistryError("dispatch is a template; use render_dispatch_prompt")
    instruction = _read_prompt(stage)
    return PromptSpec(
        stage=stage,
        version=_PROMPT_VERSIONS[stage],
        instruction=instruction,
        sha256=hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
        decision_codes=_DECISION_CODES[stage],
        review_reason_codes=_REVIEW_REASON_CODES,
        output_schema=_OUTPUT_SCHEMAS[stage],
    )


def prompt_inventory() -> dict[str, dict[str, str]]:
    """Return version and hash metadata for every model-facing prompt."""

    inventory = {}
    for stage in ("discovery", "semantic", "occurrence", "reference"):
        prompt = get_prompt(stage)
        inventory[stage] = {
            "version": prompt.version,
            "sha256": prompt.sha256,
        }
    dispatch = _read_prompt("dispatch")
    inventory["dispatch"] = {
        "version": _PROMPT_VERSIONS["dispatch"],
        "sha256": hashlib.sha256(dispatch.encode("utf-8")).hexdigest(),
    }
    return inventory


def render_dispatch_prompt(
    stage: str,
    packet_path: str | Path,
    response_path: str | Path,
    *,
    validation_command: str = "validate the response with the packaged runtime",
) -> str:
    """Render the standardized outer task given to a generic review worker."""

    if stage not in ("discovery", "semantic", "occurrence", "reference"):
        raise PromptRegistryError(f"unsupported dispatch stage: {stage}")
    template = _read_prompt("dispatch")
    rendered = template.format(
        stage=stage,
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
