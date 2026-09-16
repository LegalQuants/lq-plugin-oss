"""Optional host-adapter stage runner; no model SDK or inferred decisions.

The adapter owns dispatch and must return only when a response is available.
Events measure host boundaries, never provider inference or billing.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .prompts import get_prompt
from .review_packets import ReviewPacketError, _worker_text, validate_packet_response

WORKER_RESPONSE_VERSION = "worker-response-v3"
DEFAULT_STAGE_CONCURRENCY = 4


def default_stage_concurrency(stage: str) -> int:
    if stage not in {"discovery", "semantic", "reference", "occurrence"}:
        raise ValueError(f"unsupported review stage: {stage}")
    return DEFAULT_STAGE_CONCURRENCY


def collected_packet_numbers(directory: Path) -> set[int]:
    completed: set[int] = set()
    for path in directory.glob("packet-*.json"):
        match = re.fullmatch(r"packet-(\d+)", path.stem)
        if match:
            completed.add(int(match.group(1)))
    return completed


def compact_stage_checkpoint(
    manifest: dict,
    *,
    completed_packets: set[int] | list[int] | tuple[int, ...] = (),
    failed_packets: set[int] | list[int] | tuple[int, ...] = (),
    attempts: dict[int, int] | None = None,
    status: str = "running",
) -> dict[str, Any]:
    packet_numbers = sorted(
        packet["packet"]
        for packet in manifest.get("packets", [])
        if isinstance(packet, dict)
    )
    completed = sorted(set(completed_packets))
    return {
        "schema": "definition-check-stage-checkpoint-v2",
        "stage": manifest.get("stage"),
        "source_sha256": manifest.get("source_sha256"),
        "prompt_sha256": manifest.get("prompt_sha256"),
        "queue_sha256": manifest.get("queue_sha256"),
        "normalization_version": manifest.get("normalization_version"),
        "packet_count": len(packet_numbers),
        "packet_numbers": packet_numbers,
        "completed_packets": completed,
        "completed_count": len(completed),
        "failed_packets": sorted(set(failed_packets)),
        "attempts": {
            str(packet): count for packet, count in sorted((attempts or {}).items())
        },
        "status": status,
    }


def summarize_worker_attempts(directory: Path) -> dict[str, Any]:
    receipts: list[dict[str, Any]] = []
    for path in sorted((directory / "workers").glob("*/*/metadata.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            receipts.append(value)
    starts: list[int] = []
    endpoints: list[tuple[int, int]] = []
    attempts_by_packet: dict[int, int] = {}
    usage_totals = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
        "model_calls": 0,
    }
    usage_attempts = 0
    for receipt in receipts:
        packet = receipt.get("packet")
        attempt = receipt.get("attempt")
        if type(packet) is int and type(attempt) is int:
            attempts_by_packet[packet] = max(attempts_by_packet.get(packet, 0), attempt)
        start = receipt.get("process_started_monotonic_ns")
        end = receipt.get("process_completed_monotonic_ns")
        if type(start) is int and type(end) is int and end >= start:
            starts.append(start)
            endpoints.extend(((start, 1), (end, -1)))
        usage = receipt.get("usage")
        if not isinstance(usage, dict):
            continue
        values: dict[str, int] = {}
        for key in usage_totals:
            count = usage.get(key, 0)
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                break
            values[key] = count
        else:
            usage_attempts += 1
            for key, count in values.items():
                usage_totals[key] += count
    active = peak = 0
    for _, delta in sorted(endpoints, key=lambda item: (item[0], item[1])):
        active += delta
        peak = max(peak, active)
    return {
        "attempt_count": len(receipts),
        "retry_count": sum(max(value - 1, 0) for value in attempts_by_packet.values()),
        "maximum_observed_process_concurrency": peak,
        "process_start_spread_seconds": (
            (max(starts) - min(starts)) / 1_000_000_000 if len(starts) > 1 else 0.0
        )
        if starts
        else None,
        "provider_usage_attempts": usage_attempts,
        "missing_provider_usage_attempts": len(receipts) - usage_attempts,
        "provider_usage": usage_totals if usage_attempts else None,
    }


def _named_id(value: object, prefix: str, field: str) -> int:
    if not isinstance(value, str):
        raise ReviewPacketError(
            f"{field} must use the {prefix}-<number> namespace",
            field=field,
            code="wrong_context_namespace"
            if prefix != "item"
            else "wrong_item_namespace",
            correction=f"Use a string such as {prefix}-1 from this item.",
        )
    match = re.fullmatch(rf"{re.escape(prefix)}-([1-9][0-9]*)", value)
    if match is None:
        raise ReviewPacketError(
            f"{field} must use the {prefix}-<number> namespace",
            field=field,
            code="wrong_context_namespace"
            if prefix != "item"
            else "wrong_item_namespace",
            correction=f"Use a string such as {prefix}-1 from this item.",
        )
    return int(match.group(1))


def _packet_order(manifest: dict, packet: int) -> list[int]:
    for entry in manifest.get("packets", []):
        if isinstance(entry, dict) and entry.get("packet") == packet:
            values = entry.get("item_ordinals")
            if isinstance(values, list):
                return list(values)
    raise ReviewPacketError(
        "response packet is not present in the manifest",
        packet=packet,
        code="unknown_packet",
    )


def _decision_code(stage: str, value: object) -> int:
    codes = {name: code for code, name in get_prompt(stage).decision_codes}
    if not isinstance(value, str) or value not in codes:
        raise ReviewPacketError(
            f"unknown {stage} decision name",
            field="decision",
            code="unknown_decision",
            correction="Use one decision name listed in decision_codes.",
        )
    return codes[value]


def _reason_code(stage: str, value: object) -> int:
    reasons = {name: code for code, name in get_prompt(stage).review_reason_codes}
    if (
        not isinstance(value, bool)
        and isinstance(value, int)
        and value in reasons.values()
    ):
        return value
    if value is not None and not isinstance(value, str):
        raise ReviewPacketError(
            f"unknown {stage} review reason name",
            field="review_reason",
            code="unknown_review_reason",
            correction="Use a listed review_reason name, or null for a resolved decision.",
        )
    if value not in reasons:
        raise ReviewPacketError(
            f"unknown {stage} review reason name",
            field="review_reason",
            code="unknown_review_reason",
            correction="Use a listed review_reason name, or null for a resolved decision.",
        )
    return reasons[value]


def _exact_occurrence_span(text: str, quote: str, occurrence: int) -> tuple[int, int]:
    visible = _worker_text(text)
    if not isinstance(quote, str) or not quote:
        raise ReviewPacketError("support quote must be non-empty", field="quote")
    if (
        isinstance(occurrence, bool)
        or not isinstance(occurrence, int)
        or occurrence < 1
    ):
        raise ReviewPacketError(
            "support occurrence must be a positive integer", field="occurrence"
        )
    starts = [match.start() for match in re.finditer(re.escape(quote), visible)]
    if occurrence > len(starts):
        raise ReviewPacketError(
            "support quote occurrence is absent from the selected context",
            field="quote",
            code="quote_not_found",
            correction="Copy an exact quotation and select its 1-based occurrence.",
        )
    start = starts[occurrence - 1]
    return start, start + len(quote)


def exact_span(text: str, quote: str, *, after: int | None = None) -> tuple[int, int]:
    """Resolve a unique quote in the same sanitized text seen by the worker."""
    text = _worker_text(text)
    if not isinstance(quote, str) or not quote:
        raise ReviewPacketError("definition quote must be non-empty")
    starts = [match.start() for match in re.finditer(re.escape(quote), text)]
    if len(starts) > 1 and after is not None:
        starts = [start for start in starts if start >= after][:1]
    if len(starts) != 1:
        raise ReviewPacketError("definition quote must match exactly once in context")
    start = starts[0]
    end = start + len(quote)
    if (start and text[start - 1].isalnum() and text[start].isalnum()) or (
        end < len(text) and text[end - 1].isalnum() and text[end].isalnum()
    ):
        raise ReviewPacketError("definition quote splits a word")
    return start, end


def _normalize_legacy_response(manifest: dict, packet: int, response: object) -> object:
    """Convert named semantic decisions to the existing canonical contract.

    Numeric responses remain supported. Nothing fills in a missing decision,
    evidence, or explanatory note. Only transport defaults are host supplied.
    """
    if isinstance(response, dict) and "proposals" in response:
        if manifest["stage"] != "discovery" or set(response) != {"proposals"}:
            raise ReviewPacketError("grouped proposals require discovery only")
        proposals = response["proposals"]
        if not isinstance(proposals, list):
            raise ReviewPacketError("proposals must be an array")
        rows = []
        seen = set()
        for index, proposal in enumerate(proposals):
            if not isinstance(proposal, dict) or set(proposal) != {
                "term",
                "note",
                "supports",
            }:
                raise ReviewPacketError(
                    f"proposals[{index}]: requires term, note, supports"
                )
            term = proposal["term"]
            if not isinstance(term, str) or not term or term in seen:
                raise ReviewPacketError(
                    f"proposals[{index}]: term must be unique and non-empty"
                )
            seen.add(term)
            supports = proposal["supports"]
            if not isinstance(supports, list) or not supports:
                raise ReviewPacketError(
                    f"proposals[{index}]: supports must be non-empty"
                )
            for support in supports:
                if not isinstance(support, list) or len(support) != 3:
                    raise ReviewPacketError(
                        f"proposals[{index}]: support requires fragment, start, end"
                    )
                rows.append([*support, term, proposal["note"]])
        return {"packet": packet, "rows": rows}
    if not isinstance(response, dict) or "decisions" not in response:
        return response
    if manifest["stage"] != "semantic" or set(response) != {"decisions"}:
        raise ReviewPacketError("named responses require semantic decisions only")
    entries = response["decisions"]
    if not isinstance(entries, list):
        raise ReviewPacketError("decisions must be an array")
    codes = {name: code for code, name in get_prompt("semantic").decision_codes}
    reasons = {name: code for code, name in get_prompt("semantic").review_reason_codes}
    items = {item["ordinal"]: item for item in manifest["items"]}
    rows = []
    allowed = {
        "item",
        "decision",
        "evidence_contexts",
        "definitions",
        "note",
        "canonical_item",
        "review_reason",
    }
    for index, entry in enumerate(entries):
        try:
            if not isinstance(entry, dict) or set(entry) - allowed:
                raise ReviewPacketError("unexpected decision fields")
            ordinal = entry["item"]
            if isinstance(ordinal, bool) or not isinstance(ordinal, int):
                raise ReviewPacketError("item must be an integer")
            decision = codes[entry["decision"]]
            spans = None
            definitions = entry.get("definitions")
            if definitions is not None:
                if not isinstance(definitions, list) or not definitions:
                    raise ReviewPacketError("definitions must be a non-empty array")
                spans = []
                contexts = {
                    context["ordinal"]: context
                    for context in items[ordinal]["contexts"]
                }
                for definition in definitions:
                    if not isinstance(definition, dict) or set(definition) != {
                        "context",
                        "quote",
                    }:
                        raise ReviewPacketError("definition requires context and quote")
                    context = definition["context"]
                    if isinstance(context, bool) or not isinstance(context, int):
                        raise ReviewPacketError("context must be an integer")
                    start, end = exact_span(
                        contexts[context]["text"], definition["quote"]
                    )
                    spans.append([context, start, end])
            rows.append(
                [
                    ordinal,
                    decision,
                    entry["evidence_contexts"],
                    spans,
                    entry["note"],
                    entry.get("canonical_item"),
                    reasons[entry.get("review_reason")],
                ]
            )
        except (KeyError, TypeError, ReviewPacketError) as exc:
            raise ReviewPacketError(f"decisions[{index}]: {exc}") from exc
    return {"packet": packet, "rows": rows}


def _normalize_v3_discovery(manifest: dict, packet: int, entries: object) -> dict:
    if not isinstance(entries, list):
        raise ReviewPacketError("items must be an array", field="items")
    raw_packet = next(
        (
            value
            for value in manifest.get("packets", [])
            if isinstance(value, dict) and value.get("packet") == packet
        ),
        None,
    )
    if raw_packet is None:
        raise ReviewPacketError("unknown discovery packet", code="unknown_packet")
    fragments = {
        int(fragment["ordinal"]): fragment
        for fragment in raw_packet.get("fragments", [])
        if isinstance(fragment, dict) and isinstance(fragment.get("ordinal"), int)
    }
    rows: list[list[Any]] = []
    seen_items: set[str] = set()
    for index, entry in enumerate(entries):
        item_name: str | None = None
        try:
            if not isinstance(entry, dict) or set(entry) != {
                "item",
                "term",
                "note",
                "supports",
            }:
                raise ReviewPacketError(
                    "discovery item requires item, term, note, and supports",
                    code="unexpected_fields",
                )
            item_name = entry["item"]
            if not isinstance(item_name, str) or not item_name:
                raise ReviewPacketError("discovery item ID must be non-empty")
            if item_name in seen_items:
                raise ReviewPacketError(
                    "discovery response contains a duplicate item",
                    code="duplicate_item",
                )
            seen_items.add(item_name)
            term = entry["term"]
            if not isinstance(term, str) or not term:
                raise ReviewPacketError("term must be non-empty", field="term")
            supports = entry["supports"]
            if not isinstance(supports, list) or not supports:
                raise ReviewPacketError(
                    "supports must be a non-empty array", field="supports"
                )
            item_rows: list[list[Any]] = []
            for support in supports:
                if (
                    not isinstance(support, dict)
                    or set(support)
                    - {
                        "context",
                        "quote",
                        "occurrence",
                    }
                    or not {"context", "quote"} <= set(support)
                ):
                    raise ReviewPacketError(
                        "support requires context and quote",
                        field="supports",
                        code="unexpected_fields",
                    )
                context = _named_id(support["context"], "fragment", "context")
                fragment = fragments.get(context)
                if fragment is None:
                    raise ReviewPacketError(
                        "support cites a context outside this packet",
                        field="context",
                        code="unknown_context",
                    )
                quote = support["quote"]
                if quote != term:
                    continue
                try:
                    start, end = _exact_occurrence_span(
                        fragment["text"], quote, support.get("occurrence", 1)
                    )
                except ReviewPacketError as exc:
                    if exc.code != "quote_not_found":
                        raise
                    continue
                item_rows.append([context, start, end, term, entry["note"]])
            if not item_rows:
                for context, fragment in fragments.items():
                    visible = _worker_text(fragment["text"])
                    item_rows.extend(
                        [context, match.start(), match.end(), term, entry["note"]]
                        for match in re.finditer(re.escape(term), visible)
                    )
            # Discovery is recall-only. A proposal with no exact source support is
            # a hallucinated candidate, not a reason to regenerate the packet.
            if not item_rows:
                continue
            rows.extend(item_rows)
        except (KeyError, TypeError, ReviewPacketError) as exc:
            error = (
                exc
                if isinstance(exc, ReviewPacketError)
                else ReviewPacketError(str(exc))
            )
            raise error.with_context(
                stage="discovery", packet=packet, item=item_name or index + 1
            ) from exc
    return {"packet": packet, "rows": rows}


def _normalize_v3_review(
    manifest: dict, packet: int, stage: str, entries: object
) -> dict:
    if not isinstance(entries, list):
        raise ReviewPacketError("items must be an array", field="items")
    order = _packet_order(manifest, packet)
    manifest_items = {
        int(item["ordinal"]): item
        for item in manifest.get("items", [])
        if isinstance(item, dict) and isinstance(item.get("ordinal"), int)
    }
    compiled: dict[int, list[Any]] = {}
    for index, entry in enumerate(entries):
        ordinal: int | None = None
        try:
            if not isinstance(entry, dict):
                raise ReviewPacketError("review item must be an object")
            ordinal = _named_id(entry.get("item"), "item", "item")
            if ordinal not in order:
                raise ReviewPacketError(
                    "response item is not in this packet",
                    field="item",
                    code="unknown_item",
                )
            if ordinal in compiled:
                raise ReviewPacketError(
                    "response contains a duplicate item",
                    field="item",
                    code="duplicate_item",
                )
            allowed = {
                "semantic": {
                    "item",
                    "decision",
                    "evidence_contexts",
                    "definitions",
                    "note",
                    "canonical_item",
                    "review_reason",
                },
                "occurrence": {"item", "decision", "note", "review_reason"},
                "reference": {
                    "item",
                    "decision",
                    "evidence_contexts",
                    "note",
                    "review_reason",
                },
            }[stage]
            required = {
                "semantic": {"item", "decision", "evidence_contexts", "note"},
                "occurrence": {"item", "decision", "note"},
                "reference": {"item", "decision", "evidence_contexts", "note"},
            }[stage]
            if set(entry) - allowed or not required <= set(entry):
                raise ReviewPacketError(
                    "review item fields do not match the worker-response-v3 contract",
                    code="unexpected_fields",
                )
            decision = _decision_code(stage, entry["decision"])
            reason = _reason_code(stage, entry.get("review_reason"))
            unresolved = {
                "semantic": {5, 6},
                "occurrence": {4, 5},
                "reference": {4, 5},
            }[stage]
            if decision not in unresolved:
                reason = 0
            if stage == "occurrence":
                compiled[ordinal] = [ordinal, decision, entry["note"], reason]
                continue
            contexts = manifest_items[ordinal].get("contexts")
            if not isinstance(contexts, list):
                raise ReviewPacketError("manifest item has no contexts")
            evidence = entry["evidence_contexts"]
            if not isinstance(evidence, list):
                raise ReviewPacketError(
                    "evidence_contexts must be an array", field="evidence_contexts"
                )
            evidence_ordinals: list[int] = []
            for context_name in evidence:
                local = _named_id(context_name, "context", "evidence_contexts")
                if local > len(contexts):
                    raise ReviewPacketError(
                        "evidence cites a context outside this item",
                        field="evidence_contexts",
                        code="unknown_context",
                    )
                canonical_context = (
                    int(contexts[local - 1]["ordinal"])
                    if stage == "reference"
                    else local
                )
                evidence_ordinals.append(canonical_context)
            if len(evidence_ordinals) != len(set(evidence_ordinals)):
                raise ReviewPacketError(
                    "evidence contexts must be unique",
                    field="evidence_contexts",
                    code="duplicate_context",
                )
            if stage == "reference":
                compiled[ordinal] = [
                    ordinal,
                    decision,
                    evidence_ordinals,
                    entry["note"],
                    reason,
                ]
                continue
            spans = None
            definitions = entry.get("definitions")
            if definitions is not None:
                if not isinstance(definitions, list) or not definitions:
                    raise ReviewPacketError(
                        "definitions must be a non-empty array or null",
                        field="definitions",
                    )
                spans = []
                for definition in definitions:
                    if not isinstance(definition, dict) or set(definition) != {
                        "context",
                        "quote",
                    }:
                        raise ReviewPacketError(
                            "definition requires context and quote",
                            field="definitions",
                        )
                    local = _named_id(
                        definition["context"], "context", "definitions.context"
                    )
                    if local > len(contexts):
                        raise ReviewPacketError(
                            "definition cites a context outside this item",
                            field="definitions.context",
                            code="unknown_context",
                        )
                    context = contexts[local - 1]
                    start, end = exact_span(
                        context["text"],
                        definition["quote"],
                        after=context.get("match_end"),
                    )
                    spans.append([local, start, end])
            canonical = entry.get("canonical_item")
            canonical_ordinal = (
                None
                if canonical is None
                else _named_id(canonical, "item", "canonical_item")
            )
            compiled[ordinal] = [
                ordinal,
                decision,
                evidence_ordinals,
                spans,
                entry["note"],
                canonical_ordinal,
                reason,
            ]
        except (KeyError, TypeError, ReviewPacketError) as exc:
            error = (
                exc
                if isinstance(exc, ReviewPacketError)
                else ReviewPacketError(str(exc))
            )
            raise error.with_context(
                stage=stage, packet=packet, item=ordinal or index + 1
            ) from exc
    missing = [ordinal for ordinal in order if ordinal not in compiled]
    if missing:
        raise ReviewPacketError(
            f"{stage} response is missing items {missing}",
            stage=stage,
            packet=packet,
            field="items",
            code="missing_items",
            correction="Return each missing item once; preserve accepted items unchanged.",
        )
    return {"packet": packet, "rows": [compiled[ordinal] for ordinal in order]}


def normalize_response(manifest: dict, packet: int, response: object) -> object:
    """Compile a worker response into the unchanged canonical numeric arrays."""

    if (
        not isinstance(response, dict)
        or response.get("schema_version") != WORKER_RESPONSE_VERSION
    ):
        return _normalize_legacy_response(manifest, packet, response)
    if set(response) != {"schema_version", "stage", "packet", "items"}:
        raise ReviewPacketError(
            "worker response fields do not match worker-response-v3",
            stage=manifest.get("stage"),
            packet=packet,
            code="unexpected_fields",
        )
    stage = manifest.get("stage")
    if response.get("stage") != stage or response.get("packet") != packet:
        raise ReviewPacketError(
            "worker response identity does not match the scheduled packet",
            stage=stage,
            packet=packet,
            code="identity_mismatch",
            correction="Keep schema_version, stage, and packet exactly as supplied.",
        )
    if stage == "discovery":
        return _normalize_v3_discovery(manifest, packet, response["items"])
    if stage not in {"semantic", "occurrence", "reference"}:
        raise ReviewPacketError("unsupported worker response stage")
    return _normalize_v3_review(manifest, packet, stage, response["items"])


def valid_response_items(
    manifest: dict, packet: int, response: object
) -> dict[int | str, list]:
    """Identify independently valid rows to protect them during a correction."""
    if not isinstance(response, dict):
        return {}
    if manifest["stage"] == "discovery":
        discovery_valid: dict[int | str, list] = {}
        if response.get("schema_version") == WORKER_RESPONSE_VERSION:
            entries = response.get("items")
            for entry in entries if isinstance(entries, list) else []:
                try:
                    canonical = normalize_response(
                        manifest,
                        packet,
                        {**response, "items": [entry]},
                    )
                    if not isinstance(canonical, dict):
                        continue
                    validate_packet_response(
                        manifest,
                        canonical,
                        stage="discovery",
                        packet_ordinal=packet,
                    )
                    discovery_valid[str(entry["item"])] = canonical["rows"]
                except (KeyError, TypeError, ReviewPacketError):
                    continue
            return discovery_valid
        entries = response.get("rows", [])
        if "proposals" in response:
            entries = []
            proposals = response["proposals"]
            for proposal in proposals if isinstance(proposals, list) else []:
                if not isinstance(proposal, dict) or set(proposal) != {
                    "term",
                    "note",
                    "supports",
                }:
                    continue
                supports = proposal["supports"]
                for support in supports if isinstance(supports, list) else []:
                    if isinstance(support, list) and len(support) == 3:
                        entries.append([*support, proposal["term"], proposal["note"]])
        for row in entries if isinstance(entries, list) else []:
            try:
                validate_packet_response(
                    manifest,
                    {"packet": packet, "rows": [row]},
                    stage="discovery",
                    packet_ordinal=packet,
                )
                discovery_valid[json.dumps(row[:4], ensure_ascii=False)] = row
            except (ReviewPacketError, TypeError, IndexError):
                continue
        return discovery_valid
    v3 = response.get("schema_version") == WORKER_RESPONSE_VERSION
    named = "decisions" in response
    entries = response.get("items" if v3 else "decisions" if named else "rows")
    if not isinstance(entries, list):
        return {}
    expected = next(
        p["item_ordinals"] for p in manifest["packets"] if p["packet"] == packet
    )
    valid: dict[int | str, list] = {}
    seen = set()
    for entry in entries:
        try:
            ordinal = (
                _named_id(entry["item"], "item", "item")
                if v3
                else entry["item"]
                if named
                else entry[0]
            )
            if (
                isinstance(ordinal, bool)
                or not isinstance(ordinal, int)
                or ordinal not in expected
            ):
                continue
            if ordinal in seen:
                valid.pop(ordinal, None)
                continue
            seen.add(ordinal)
            # Preserve the complete ID universe and queue hash. Only validation
            # packet membership changes for this independent row check.
            isolated = {
                **manifest,
                "packets": [
                    {"packet": packet, "item_ordinals": [ordinal]},
                    {
                        "packet": max(p["packet"] for p in manifest["packets"]) + 1,
                        "item_ordinals": [
                            item["ordinal"]
                            for item in manifest["items"]
                            if item["ordinal"] != ordinal
                        ],
                    },
                ],
            }
            single = (
                {**response, "items": [entry]}
                if v3
                else {"decisions": [entry]}
                if named
                else {"packet": packet, "rows": [entry]}
            )
            canonical = normalize_response(isolated, packet, single)
            validate_packet_response(
                isolated, canonical, stage=manifest["stage"], packet_ordinal=packet
            )
            if isinstance(canonical, dict):
                valid[ordinal] = canonical["rows"][0]
        except (KeyError, IndexError, TypeError, ReviewPacketError):
            continue
    return valid


async def run_stage(
    manifest: dict,
    dispatch: Callable[[int, int, dict | None], Awaitable[object]],
    collect: Callable[[int, dict], None],
    event: Callable[[dict], None],
    *,
    concurrency: int = 4,
    max_attempts: int = 2,
    validation_manifest: dict | None = None,
    initial_corrections: dict[int, dict[str, Any]] | None = None,
) -> dict[int, dict[str, Any]]:
    """Dispatch with bounded concurrency, validate and collect without a barrier.

    A retry receives the previous response and precise validation error. The
    adapter may ask for a targeted correction; accepted packets are never rerun.
    Failed packets prevent stage success. Stage-wide semantic/alias validation
    and subsequent stage gates remain the caller's responsibility.
    """
    if concurrency < 1 or max_attempts < 1:
        raise ValueError("concurrency and max_attempts must be positive")
    numbers = [entry["packet"] for entry in manifest["packets"]]
    if len(numbers) != len(set(numbers)):
        raise ReviewPacketError("duplicate manifest packets")
    validation_manifest = validation_manifest or manifest
    validation_numbers = {
        entry["packet"] for entry in validation_manifest.get("packets", [])
    }
    if not set(numbers) <= validation_numbers:
        raise ReviewPacketError("scheduled packet is absent from validation manifest")
    semaphore = asyncio.Semaphore(concurrency)
    started = time.perf_counter()

    def emit(kind: str, packet: int, attempt: int, **details: Any) -> None:
        event(
            {
                "event": kind,
                "packet": packet,
                "attempt": attempt,
                "elapsed_seconds": time.perf_counter() - started,
                "timestamp": datetime.now(UTC).isoformat(),
                **details,
            }
        )

    async def worker(packet: int) -> tuple[int, dict]:
        correction = copy.deepcopy((initial_corrections or {}).get(packet))
        locked: dict[int | str, list] = (
            valid_response_items(
                validation_manifest, packet, correction.get("response")
            )
            if correction
            else {}
        )
        for replaceable in (correction or {}).get("replace_item_ordinals", []):
            locked.pop(replaceable, None)
        ready_at = time.perf_counter()
        emit("packet_ready", packet, 0)
        async with semaphore:
            launch_delay = time.perf_counter() - ready_at
            for attempt in range(1, max_attempts + 1):
                dispatch_started = time.perf_counter()
                emit(
                    "dispatch_started",
                    packet,
                    attempt,
                    launch_delay_seconds=launch_delay if attempt == 1 else 0.0,
                )
                try:
                    response = await dispatch(
                        packet, attempt, copy.deepcopy(correction)
                    )
                except Exception as exc:
                    emit("dispatch_failed", packet, attempt, error=str(exc))
                    correction = {
                        "response": None,
                        "error": str(exc),
                        "preserve_item_ordinals": sorted(locked, key=str)
                        if validation_manifest["stage"] != "discovery"
                        else [],
                        "preserve_discovery_rows": list(locked.values())
                        if validation_manifest["stage"] == "discovery"
                        else [],
                    }
                    if attempt == max_attempts:
                        raise
                    continue
                emit(
                    "response_received",
                    packet,
                    attempt,
                    worker_duration_seconds=time.perf_counter() - dispatch_started,
                )
                try:
                    valid = valid_response_items(validation_manifest, packet, response)
                    changed_locked = [
                        ordinal
                        for ordinal, row in locked.items()
                        if valid.get(ordinal) != row
                    ]
                    if changed_locked and validation_manifest["stage"] == "discovery":
                        raise ReviewPacketError(
                            "correction changed a previously valid item; substantive disagreement requires separate review"
                        )
                    if changed_locked:
                        emit(
                            "locked_items_restored",
                            packet,
                            attempt,
                            item_ordinals=sorted(changed_locked, key=str),
                        )
                    for ordinal, row in valid.items():
                        locked.setdefault(ordinal, row)
                    canonical = normalize_response(
                        validation_manifest, packet, response
                    )
                    count = validate_packet_response(
                        validation_manifest,
                        canonical,
                        stage=validation_manifest["stage"],
                        packet_ordinal=packet,
                    )
                    if not isinstance(canonical, dict):
                        raise ReviewPacketError("response must be an object")
                    if validation_manifest["stage"] != "discovery" and locked:
                        current = {row[0]: row for row in canonical["rows"]}
                        current.update(locked)
                        canonical["rows"] = [
                            current[ordinal]
                            for ordinal in _packet_order(validation_manifest, packet)
                        ]
                        count = validate_packet_response(
                            validation_manifest,
                            canonical,
                            stage=validation_manifest["stage"],
                            packet_ordinal=packet,
                        )
                except ReviewPacketError as exc:
                    emit(
                        "validation_failed",
                        packet,
                        attempt,
                        error=str(exc),
                        validation_error=exc.to_dict(),
                    )
                    correction = {
                        "response": response,
                        "error": str(exc),
                        "validation_error": exc.to_dict(),
                        "preserve_item_ordinals": sorted(locked, key=str)
                        if validation_manifest["stage"] != "discovery"
                        else [],
                        "preserve_discovery_rows": list(locked.values())
                        if validation_manifest["stage"] == "discovery"
                        else [],
                    }
                    if attempt == max_attempts:
                        raise
                else:
                    emit("validation_completed", packet, attempt, rows=count)
                    collect(packet, canonical)
                    emit("collection_completed", packet, attempt)
                    return packet, canonical
        raise AssertionError("unreachable")

    # Await all tasks even on failure: no orphan workers or premature stage gate.
    results = await asyncio.gather(
        *(worker(number) for number in numbers), return_exceptions=True
    )
    errors = [result for result in results if isinstance(result, BaseException)]
    if errors:
        raise ReviewPacketError(
            f"stage failed: {len(errors)} packet(s); first error: {errors[0]}"
        )
    return dict(result for result in results if isinstance(result, tuple))


def adapter_packet(packet: dict) -> dict:
    """Return the packet view authored against worker-response-v3."""
    payload = copy.deepcopy(packet)
    for key in ("response_schema", "response_template", "row_fields"):
        payload.pop(key, None)
    stage = packet["stage"]
    if "decision_codes" in payload:
        payload["decision_names"] = [name for _, name in payload.pop("decision_codes")]
    if "review_reason_codes" in payload:
        payload["review_reason_names"] = [
            name for _, name in payload.pop("review_reason_codes")
        ]
    if stage == "discovery":
        payload["fragments"] = [
            {"id": f"fragment-{ordinal}", "text": text}
            for ordinal, text in payload["fragments"]
        ]
    elif stage == "semantic":
        payload["term_index"] = [
            {"id": f"item-{ordinal}", "term": term}
            for ordinal, term in payload["term_index"]
        ]
        payload["items"] = [
            {
                "id": f"item-{item['ordinal']}",
                "term": item["term"],
                "contexts": [
                    {
                        "id": f"context-{context[0]}",
                        "source": context[1],
                        "match_start": context[2],
                        "match_end": context[3],
                    }
                    for context in item["contexts"]
                ],
            }
            for item in payload["items"]
        ]
    elif stage == "reference":
        payload["items"] = [
            {
                "id": f"item-{item['ordinal']}",
                "target": item["target"],
                "contexts": [
                    {
                        "id": f"context-{local}",
                        "source": context[0],
                        "match_start": context[1],
                        "match_end": context[2],
                    }
                    for local, context in enumerate(item["contexts"], start=1)
                ],
            }
            for item in payload["items"]
        ]
    elif stage == "occurrence":
        payload["groups"] = [
            {
                **{key: value for key, value in group.items() if key != "items"},
                "items": [
                    {
                        "id": f"item-{item[0]}",
                        "observed_form": item[1],
                        "context": {
                            "id": "context-1",
                            "source": item[2],
                            "match_start": item[3],
                            "match_end": item[4],
                        },
                        "collision_matches": item[5],
                    }
                    for item in group["items"]
                ],
            }
            for group in payload["groups"]
        ]
    else:
        raise ReviewPacketError(f"unsupported worker stage: {stage}")
    if stage == "semantic":
        contract = (
            'Each item uses {"item":"item-1","decision":"confirmed_defined",'
            '"evidence_contexts":["context-1"],"definitions":'
            '[{"context":"context-1","quote":"exact source quotation"}],'
            '"note":"short explanation","canonical_item":null,"review_reason":null}. '
            "Use decision_names. definitions is null except for confirmed_defined. "
            "Quotes must match exactly once in the selected item-local context and must not split words. "
            "For aliases include canonical_item. For unresolved decisions include review_reason by name "
            "from review_reason_names. Other canonical_item and review_reason fields may be omitted. "
            "Do not infer missing evidence or use default decisions."
        )
    elif stage == "discovery":
        contract = (
            'Each item uses {"item":"proposal-1","term":"exact label",'
            '"note":"short explanation","supports":[{"context":"fragment-1",'
            '"quote":"exact label","occurrence":1}]}. '
            "List each exact spelling once per packet, with all supporting locations. "
            "Scan every fragment; grouping must not remove labels or support locations."
        )
    elif stage == "occurrence":
        contract = (
            'Each item uses {"item":"item-1","decision":"defined_term_use",'
            '"note":"short explanation","review_reason":null}. Use decision_names. '
            "For unresolved decisions include a review_reason from review_reason_names."
        )
    else:
        contract = (
            'Each item uses {"item":"item-1","decision":"resolved",'
            '"evidence_contexts":["context-1"],"note":"short explanation",'
            '"review_reason":null}. Use decision_names and cite at least one item-local context. '
            "For unresolved decisions include a review_reason from review_reason_names."
        )
    payload["instruction"] += (
        "\nTransport contract: Return exactly one JSON object with "
        f'{{"schema_version":"{WORKER_RESPONSE_VERSION}","stage":"{stage}",'
        f'"packet":{packet["packet"]},"items":[...]}}. '
        "Return every scheduled item exactly once. Item order is irrelevant. "
        + contract
    )
    payload["canonical_prompt_sha256"] = packet["prompt_sha256"]
    payload["response_transport_version"] = WORKER_RESPONSE_VERSION
    payload["worker_response_contract"] = {
        "schema_version": WORKER_RESPONSE_VERSION,
        "stage": stage,
        "packet": packet["packet"],
        "items": "stage-specific named objects",
    }
    payload["prompt_sha256"] = hashlib.sha256(
        payload["instruction"].encode("utf-8")
    ).hexdigest()
    return payload
