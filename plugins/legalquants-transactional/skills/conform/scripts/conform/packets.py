"""Build, dispatch, and expand bounded mapping-stage packets.

This is a local, deliberately smaller equivalent of definition-check's
`review_packets.py`/`review.py` packet lifecycle
(`../../definition-check/scripts/definition_check/review_packets.py`), built
for exactly one stage (`mapping`) instead of four. It follows the same
prefill-and-validate discipline: `render_dispatch` derives one canonical
response path per packet and prefills it from the packet's exact
`response_template`; a worker edits that file in place; `validate_response`
is the packet-scoped validator a worker must run before reporting completion
and may use to correct one invalid response, but never more than once.

Skills are packaged independently into `dist/*`, so this module is vendored
rather than importing `definition_check.review_packets` across a skill
boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import MAPPING_TYPES, stable_id
from .prompts import prompt_for_mode

MAPPING_PACKET_SCHEMA_VERSION = "conform-mapping-packet-v1"
MAPPING_MANIFEST_SCHEMA_VERSION = "conform-mapping-manifest-v1"
MODES = frozenset({"conform_selected_text", "precedent_leakage_check"})
DEFAULT_TARGET_ITEMS_PER_PACKET = 6


class PacketError(ValueError):
    """Raised when a packet, manifest, or worker response cannot be trusted."""


def _normalize(text: str) -> str:
    return " ".join(text.split()).strip().casefold()


def _tokens(text: str) -> set[str]:
    return {token for token in _normalize(text).split(" ") if len(token) > 2}


def _term_and_aliases(definition: dict[str, Any]) -> list[str]:
    names = [definition.get("term", "")]
    names.extend(definition.get("aliases") or [])
    return [name for name in names if name]


def _contains_term(haystack: str, term: str) -> bool:
    """Whole-token substring check: term's normalized words all appear in order."""

    normalized_haystack = _normalize(haystack)
    normalized_term = _normalize(term)
    return bool(normalized_term) and normalized_term in normalized_haystack


def build_selected_text_queue(
    source_ledger: dict[str, Any], selected_text: str
) -> list[dict[str, Any]]:
    """Every source-document concept the selected text actually invokes.

    A definition is queued when its canonical term or any alias appears as a
    normalized substring of the selected text. This is a bounded, deterministic
    relevance pass, not a semantic judgment; the mapping worker still decides
    the actual mapping from full context.
    """

    queue: list[dict[str, Any]] = []
    for definition in source_ledger.get("definitions", []):
        names = _term_and_aliases(definition)
        if any(_contains_term(selected_text, name) for name in names):
            queue.append(definition)
    return queue


def build_leakage_queue(
    source_ledger: dict[str, Any], core_ledger: dict[str, Any]
) -> list[dict[str, Any]]:
    """Core-document definitions that lexically echo a source-document concept.

    Queues a core-document definition when its term or an alias shares a
    normalized token with a source-document definition's term or alias. The
    mapping worker (using `references/prompts/leakage-scan.md`) decides
    whether that overlap is genuine leakage, a coincidental false friend, or
    a fully independent core-document concept.
    """

    source_token_sets = [
        _tokens(" ".join(_term_and_aliases(definition)))
        for definition in source_ledger.get("definitions", [])
    ]
    queue: list[dict[str, Any]] = []
    for definition in core_ledger.get("definitions", []):
        core_tokens = _tokens(" ".join(_term_and_aliases(definition)))
        if not core_tokens:
            continue
        if any(core_tokens & source_tokens for source_tokens in source_token_sets):
            queue.append(definition)
    return queue


def build_context_pool(
    source_ledger: dict[str, Any],
    core_ledger: dict[str, Any],
    *,
    limit_per_role: int = 25,
) -> list[dict[str, Any]]:
    """A bounded, numbered pool of candidate definitions from both ledgers.

    Workers cite context_pool ordinals in their evidence; they never receive
    the raw ledgers. The pool is capped so a large document pair still
    produces a bounded packet.
    """

    pool: list[dict[str, Any]] = []
    ordinal = 0
    for role, ledger in (("source", source_ledger), ("core", core_ledger)):
        for definition in ledger.get("definitions", [])[:limit_per_role]:
            pool.append(
                {
                    "ordinal": ordinal,
                    "document_role": role,
                    "term": definition.get("term", ""),
                    "text": definition.get("definition_text", ""),
                    "location": definition.get("location", {}),
                }
            )
            ordinal += 1
    return pool


def _chunk(
    items: list[dict[str, Any]], target_items_per_packet: int
) -> list[list[dict[str, Any]]]:
    if target_items_per_packet < 1:
        raise PacketError("target_items_per_packet must be at least 1")
    if not items:
        return []
    return [
        items[index : index + target_items_per_packet]
        for index in range(0, len(items), target_items_per_packet)
    ]


def build_mapping_packets(
    source_ledger: dict[str, Any],
    core_ledger: dict[str, Any],
    *,
    mode: str,
    selected_text: str | None = None,
    target_items_per_packet: int = DEFAULT_TARGET_ITEMS_PER_PACKET,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build the frozen mapping queue, its packets, and the private manifest."""

    if mode not in MODES:
        raise PacketError(f"unsupported mode: {mode}")
    if mode == "conform_selected_text":
        if not selected_text or not selected_text.strip():
            raise PacketError(
                "conform_selected_text mode requires non-empty selected_text"
            )
        queue_definitions = build_selected_text_queue(source_ledger, selected_text)
        queue_role = "source"
    else:
        queue_definitions = build_leakage_queue(source_ledger, core_ledger)
        queue_role = "core"

    context_pool = build_context_pool(source_ledger, core_ledger)

    items: list[dict[str, Any]] = []
    manifest_items: dict[str, Any] = {}
    for ordinal, definition in enumerate(queue_definitions, start=1):
        review_id = stable_id(
            "conform-mapping-item",
            mode,
            queue_role,
            definition.get("id", definition.get("term", "")),
        )
        items.append(
            {
                "item": ordinal,
                "term": definition.get("term", ""),
                "context": definition.get("definition_text", ""),
                "role": queue_role,
            }
        )
        manifest_items[str(ordinal)] = {
            "review_id": review_id,
            "term": definition.get("term", ""),
            "definition_id": definition.get("id"),
            "location": definition.get("location", {}),
            "document_role": queue_role,
        }

    instruction = prompt_for_mode(mode)
    packets: list[dict[str, Any]] = []
    manifest_packets: list[dict[str, Any]] = []
    for packet_number, chunk in enumerate(
        _chunk(items, target_items_per_packet), start=1
    ):
        response_template = {
            "packet": packet_number,
            "rows": [[item["item"], None, [], ""] for item in chunk],
        }
        packets.append(
            {
                "schema_version": MAPPING_PACKET_SCHEMA_VERSION,
                "stage": "mapping",
                "mode": mode,
                "packet": packet_number,
                "instruction": instruction,
                "decision_codes": sorted(MAPPING_TYPES),
                "items": chunk,
                "context_pool": context_pool,
                "response_template": response_template,
            }
        )
        manifest_packets.append({"packet": packet_number, "item_count": len(chunk)})

    manifest = {
        "schema_version": MAPPING_MANIFEST_SCHEMA_VERSION,
        "stage": "mapping",
        "mode": mode,
        "packets": manifest_packets,
        "items": manifest_items,
        "context_pool": {str(entry["ordinal"]): entry for entry in context_pool},
    }
    return packets, manifest


def canonical_response_path(work_dir: Path, packet_number: int) -> Path:
    return work_dir / "responses" / "mapping" / f"packet-{packet_number:03d}.json"


def prefill_response(work_dir: Path, packet: dict[str, Any]) -> Path:
    """Write the canonical, prefilled response file for one packet.

    Refuses to overwrite an existing response, matching definition-check's
    render-dispatch discipline: a worker edits the prefilled file in place
    rather than reconstructing its shape.
    """

    packet_number = packet.get("packet")
    if not isinstance(packet_number, int) or packet_number < 1:
        raise PacketError("packet is missing a valid packet number")
    path = canonical_response_path(work_dir, packet_number)
    if path.exists():
        raise PacketError(f"refusing to overwrite existing response: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(packet["response_template"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def validate_response(
    packet: dict[str, Any], manifest: dict[str, Any], response: dict[str, Any]
) -> None:
    """Fail-closed validation of one worker response against its packet and manifest.

    Raises PacketError with a specific, exact message on the first problem
    found. A worker may correct its response once and must stop and report
    this exact error verbatim after a second failure.
    """

    if response.get("packet") != packet.get("packet"):
        raise PacketError("response packet number does not match the dispatched packet")
    rows = response.get("rows")
    expected_items = packet.get("items", [])
    if not isinstance(rows, list) or len(rows) != len(expected_items):
        raise PacketError(
            f"response must contain exactly {len(expected_items)} rows, one per packet item"
        )
    expected_ordinals = [item["item"] for item in expected_items]
    context_pool_size = len(packet.get("context_pool", []))
    seen_ordinals = []
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != 4
            or not isinstance(row[0], int)
            or isinstance(row[0], bool)
        ):
            raise PacketError(
                "each response row must be [item, decision, evidence, note]"
            )
        item_ordinal, decision, evidence, note = row
        seen_ordinals.append(item_ordinal)
        if decision is None or decision not in MAPPING_TYPES:
            raise PacketError(
                f"row for item {item_ordinal} has an invalid decision: {decision!r}"
            )
        if not isinstance(evidence, list):
            raise PacketError(f"row for item {item_ordinal} evidence must be an array")
        for entry in evidence:
            if (
                not isinstance(entry, list)
                or len(entry) != 3
                or entry[0] not in ("source", "core")
                or not isinstance(entry[1], int)
                or isinstance(entry[1], bool)
                or not (0 <= entry[1] < context_pool_size)
                or entry[2] not in ("supports", "contradicts", "context")
            ):
                raise PacketError(
                    f"row for item {item_ordinal} cites an invalid evidence entry: {entry!r}"
                )
        if not isinstance(note, str):
            raise PacketError(f"row for item {item_ordinal} note must be a string")
    if seen_ordinals != expected_ordinals:
        raise PacketError(
            "response rows must preserve the packet's item order and ordinals"
        )


def expand_responses(
    manifest: dict[str, Any],
    packets_by_number: dict[int, dict[str, Any]],
    responses_by_number: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Reconcile validated responses into a bundle keyed by the manifest's review IDs.

    Raises PacketError if any manifest packet lacks a corresponding response.
    """

    manifest_packet_numbers = sorted(
        entry["packet"] for entry in manifest.get("packets", [])
    )
    missing = [
        number
        for number in manifest_packet_numbers
        if number not in responses_by_number
    ]
    if missing:
        raise PacketError(f"missing responses for packets: {missing}")

    decisions: list[dict[str, Any]] = []
    for packet_number in manifest_packet_numbers:
        packet = packets_by_number[packet_number]
        response = responses_by_number[packet_number]
        validate_response(packet, manifest, response)
        for item_ordinal, decision, evidence, note in response["rows"]:
            item_manifest = manifest["items"][str(item_ordinal)]
            decisions.append(
                {
                    "review_id": item_manifest["review_id"],
                    "term": item_manifest["term"],
                    "document_role": item_manifest["document_role"],
                    "location": item_manifest["location"],
                    "decision": decision,
                    "evidence": [
                        {
                            "document_role": entry[0],
                            "context_pool_ordinal": entry[1],
                            "stance": entry[2],
                        }
                        for entry in evidence
                    ],
                    "reviewer_note": note,
                }
            )
    return {
        "schema_version": "conform-mapping-bundle-v1",
        "mode": manifest.get("mode"),
        "decisions": decisions,
    }
