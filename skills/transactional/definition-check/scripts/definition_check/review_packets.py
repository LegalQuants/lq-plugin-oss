"""Build bounded worker-visible review packets and private supervisor manifests."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .extract import normalize_term
from .models import CandidateProposal, Location, stable_id
from .occurrence_review import OccurrenceSubmission
from .prompts import get_prompt
from .reference_review import MAX_REFERENCE_EVIDENCE, ReferenceSubmission
from .semantic_review import AdjudicationSubmission
from .term_identity import TERM_NORMALIZATION_VERSION, term_key

PACKET_SCHEMA_VERSION = "review-packet-v3"
MANIFEST_SCHEMA_VERSION = "review-packet-manifest-v2"
DEFAULT_TARGET_CHARACTERS = 12_000
DEFAULT_HARD_MAX_CHARACTERS = 20_000

_PACKET_COMMON_FIELDS = {
    "schema_version",
    "normalization_version",
    "stage",
    "packet",
    "instruction",
    "prompt_version",
    "prompt_sha256",
    "row_fields",
    "response_schema",
    "response_template",
}
_PACKET_STAGE_FIELDS = {
    "discovery": {"outline", "fragments"},
    "semantic": {
        "item_constraints",
        "decision_codes",
        "review_reason_codes",
        "term_index",
        "context_pool",
        "items",
    },
    "occurrence": {
        "decision_codes",
        "review_reason_codes",
        "context_pool",
        "groups",
    },
    "reference": {
        "item_constraints",
        "decision_codes",
        "review_reason_codes",
        "context_pool",
        "items",
    },
}


class ReviewPacketError(ValueError):
    """Raised when packet data cannot be built or trusted."""

    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        packet: int | None = None,
        item: int | str | None = None,
        field: str | None = None,
        code: str = "invalid_review_response",
        correction: str | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.packet = packet
        self.item = item
        self.field = field
        self.code = code
        self.correction = correction or message

    def with_context(
        self,
        *,
        stage: str | None = None,
        packet: int | None = None,
        item: int | str | None = None,
        field: str | None = None,
    ) -> ReviewPacketError:
        return ReviewPacketError(
            str(self),
            stage=stage if stage is not None else self.stage,
            packet=packet if packet is not None else self.packet,
            item=item if item is not None else self.item,
            field=field if field is not None else self.field,
            code=self.code,
            correction=self.correction,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "packet": self.packet,
            "item": self.item,
            "field": self.field,
            "error_code": self.code,
            "message": str(self),
            "permitted_correction": self.correction,
        }


def validate_review_packet(packet: object) -> dict[str, Any]:
    """Validate the versioned model-input transport before dispatch."""

    if not isinstance(packet, dict):
        raise ReviewPacketError("review packet root must be an object")
    stage = packet.get("stage")
    if stage not in _PACKET_STAGE_FIELDS:
        raise ReviewPacketError("review packet stage is unsupported")
    expected_fields = _PACKET_COMMON_FIELDS | _PACKET_STAGE_FIELDS[stage]
    if set(packet) != expected_fields:
        raise ReviewPacketError("review packet fields do not match its stage schema")
    if packet.get("schema_version") != PACKET_SCHEMA_VERSION:
        raise ReviewPacketError("review packet schema_version is unsupported")
    if packet.get("normalization_version") != TERM_NORMALIZATION_VERSION:
        raise ReviewPacketError("review packet normalization_version is unsupported")
    packet_number = packet.get("packet")
    if (
        isinstance(packet_number, bool)
        or not isinstance(packet_number, int)
        or packet_number < 1
    ):
        raise ReviewPacketError("review packet ordinal must be positive")
    for field in ("instruction", "prompt_version"):
        if not isinstance(packet.get(field), str) or not packet[field].strip():
            raise ReviewPacketError(f"review packet {field} must be non-empty")
    prompt_hash = packet.get("prompt_sha256")
    if not isinstance(prompt_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", prompt_hash
    ):
        raise ReviewPacketError("review packet prompt_sha256 is invalid")
    row_fields = packet.get("row_fields")
    if (
        not isinstance(row_fields, list)
        or not row_fields
        or any(not isinstance(item, str) or not item for item in row_fields)
        or len(row_fields) != len(set(row_fields))
    ):
        raise ReviewPacketError("review packet row_fields are invalid")
    schema = packet.get("response_schema")
    template = packet.get("response_template")
    if not isinstance(schema, dict) or not isinstance(template, dict):
        raise ReviewPacketError("review packet response contract is missing")
    if set(template) != {"packet", "rows"} or template.get("packet") != packet_number:
        raise ReviewPacketError("review packet response_template is invalid")
    if not isinstance(template.get("rows"), list):
        raise ReviewPacketError("review packet response_template rows must be an array")
    properties = schema.get("properties")
    if (
        schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema"
        or schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or schema.get("required") != ["packet", "rows"]
        or not isinstance(properties, dict)
        or not isinstance(properties.get("packet"), dict)
        or properties["packet"].get("const") != packet_number
        or "rows" not in properties
    ):
        raise ReviewPacketError("review packet response_schema is invalid")
    return packet


@dataclass(frozen=True)
class PacketBuild:
    stage: str
    packets: tuple[dict[str, Any], ...]
    manifest: dict[str, Any]


def _compact_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _review_content_size(packet: dict[str, Any]) -> int:
    """Measure review content without structured-response transport metadata."""

    transport_fields = {
        "response_schema",
        "response_template",
        "item_constraints",
    }
    return len(
        _compact_json(
            {key: value for key, value in packet.items() if key not in transport_fields}
        )
    )


def _hash(value: object) -> str:
    return hashlib.sha256(_compact_json(value).encode("utf-8")).hexdigest()


def _queue_hash(value: object) -> str:
    return _hash(
        {
            "normalization_version": TERM_NORMALIZATION_VERSION,
            "queue": value,
        }
    )


_ASCII_PUNCTUATION = {
    "\u00a0": " ",
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\ufffd": "?",
}


def _worker_text(value: object) -> str:
    """Return a length-preserving ASCII projection for stable model offsets."""

    projected = []
    for character in str(value):
        if ord(character) < 128:
            projected.append(character)
            continue
        if character in _ASCII_PUNCTUATION:
            projected.append(_ASCII_PUNCTUATION[character])
            continue
        decomposed = unicodedata.normalize("NFKD", character)
        ascii_value = decomposed.encode("ascii", "ignore").decode("ascii")
        projected.append(ascii_value[0] if ascii_value else "?")
    result = "".join(projected)
    if len(result) != len(str(value)) or not result.isascii():
        raise ReviewPacketError(
            "worker text projection must be ASCII and length preserving"
        )
    return result


def _validate_limits(target_characters: int, hard_max_characters: int) -> None:
    if target_characters < 1:
        raise ValueError("target_characters must be positive")
    if hard_max_characters < target_characters:
        raise ValueError("hard_max_characters must be at least target_characters")


def _partition(
    records: list[dict[str, Any]],
    render: Callable[[int, list[dict[str, Any]]], dict[str, Any]],
    *,
    target_characters: int,
    hard_max_characters: int,
) -> list[tuple[dict[str, Any], bool]]:
    """Partition source-order records without splitting one indivisible record."""

    _validate_limits(target_characters, hard_max_characters)
    packets: list[tuple[dict[str, Any], bool]] = []
    current: list[dict[str, Any]] = []
    for record in records:
        packet_ordinal = len(packets) + 1
        proposed = render(packet_ordinal, [*current, record])
        proposed_size = _review_content_size(proposed)
        if current and proposed_size > target_characters:
            rendered = render(packet_ordinal, current)
            packets.append(
                (rendered, len(_compact_json(rendered)) > hard_max_characters)
            )
            current = [record]
            continue
        current.append(record)
    if current:
        packet_ordinal = len(packets) + 1
        rendered = render(packet_ordinal, current)
        packets.append((rendered, len(_compact_json(rendered)) > hard_max_characters))
    return packets


def _closed_array_schema(prefix_items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "array",
        "prefixItems": prefix_items,
        "items": False,
        "minItems": len(prefix_items),
        "maxItems": len(prefix_items),
    }


def _response_contract(
    packet_ordinal: int,
    row_schema: dict[str, Any],
    row_templates: list[list[Any]],
    *,
    variable_rows: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    rows_schema: dict[str, Any] = {"type": "array", "items": row_schema}
    if not variable_rows:
        rows_schema.update(
            {
                "minItems": len(row_templates),
                "maxItems": len(row_templates),
            }
        )
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["packet", "rows"],
        "properties": {
            "packet": {"const": packet_ordinal},
            "rows": rows_schema,
        },
    }
    return schema, {"packet": packet_ordinal, "rows": row_templates}


def _semantic_response_contract(
    packet_ordinal: int,
    items: list[dict[str, Any]],
    decision_codes: tuple[tuple[int, str], ...],
    term_index: tuple[tuple[int, str], ...],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    decision_ordinals = [code for code, _ in decision_codes]
    review_reason_ordinals = [
        code for code, _ in get_prompt("semantic").review_reason_codes
    ]
    canonical_ordinals = [ordinal for ordinal, _ in term_index]
    item_ordinals = [int(item["ordinal"]) for item in items]
    context_ordinals = sorted(
        {int(context[0]) for item in items for context in item["contexts"]}
    )
    definition_span = _closed_array_schema(
        [
            {"type": "integer", "enum": context_ordinals},
            {"type": "integer", "minimum": 0},
            {"type": "integer", "minimum": 1},
        ]
    )
    row_schema = _closed_array_schema(
        [
            {"type": "integer", "enum": item_ordinals},
            {"type": "integer", "enum": decision_ordinals},
            {
                "type": "array",
                "items": {"type": "integer", "enum": context_ordinals},
                "uniqueItems": True,
            },
            {
                "oneOf": [
                    {"type": "null"},
                    {"type": "array", "items": definition_span, "minItems": 1},
                ]
            },
            {"type": "string"},
            {
                "oneOf": [
                    {"type": "null"},
                    {"type": "integer", "enum": canonical_ordinals},
                ]
            },
            {"type": "integer", "enum": review_reason_ordinals},
        ]
    )
    templates = [[ordinal, None, [], None, "", None, 0] for ordinal in item_ordinals]
    constraints = [
        {
            "item": int(item["ordinal"]),
            "evidence_contexts": [int(context[0]) for context in item["contexts"]],
        }
        for item in items
    ]
    schema, template = _response_contract(packet_ordinal, row_schema, templates)
    return schema, template, constraints


def _semantic_packet(
    packet_ordinal: int, records: list[dict[str, Any]]
) -> dict[str, Any]:
    prompt = get_prompt("semantic")
    context_pool: list[dict[str, Any]] = []
    context_keys: dict[str, str] = {}
    items: list[dict[str, Any]] = []
    for record in records:
        item_contexts = []
        for local_ordinal, context in enumerate(record["contexts"], start=1):
            text = context["worker_text"]
            source_structure = context.get("source_structure")
            context_identity = _compact_json([text, source_structure])
            source_key = context_keys.get(context_identity)
            if source_key is None:
                source_key = f"c{len(context_pool) + 1}"
                context_keys[context_identity] = source_key
                pool_entry = {"key": source_key, "text": text}
                if source_structure is not None:
                    pool_entry["source_structure"] = source_structure
                context_pool.append(pool_entry)
            item_contexts.append(
                [
                    local_ordinal,
                    source_key,
                    int(context["match_start"]),
                    int(context["match_end"]),
                ]
            )
        items.append(
            {
                "ordinal": record["ordinal"],
                "term": record["worker_term"],
                "contexts": item_contexts,
            }
        )
    term_index = _semantic_term_index(records)
    response_schema, response_template, item_constraints = _semantic_response_contract(
        packet_ordinal,
        items,
        prompt.decision_codes,
        term_index,
    )
    return {
        "schema_version": PACKET_SCHEMA_VERSION,
        "normalization_version": TERM_NORMALIZATION_VERSION,
        "stage": "semantic",
        "packet": packet_ordinal,
        "instruction": prompt.instruction,
        "prompt_version": prompt.version,
        "prompt_sha256": prompt.sha256,
        "row_fields": list(prompt.output_schema),
        "response_schema": response_schema,
        "response_template": response_template,
        "item_constraints": item_constraints,
        "decision_codes": [list(item) for item in prompt.decision_codes],
        "review_reason_codes": [list(item) for item in prompt.review_reason_codes],
        "term_index": [list(item) for item in term_index],
        "context_pool": context_pool,
        "items": items,
    }


def _semantic_term_index(
    records: list[dict[str, Any]],
) -> tuple[tuple[int, str], ...]:
    """Expose only canonical ordinals that the packet can reasonably reference.

    Every packet item is always indexed. An external candidate is indexed only
    when its exact label appears in one of the packet's supplied contexts. This
    keeps alias targets addressable without repeating the complete run-wide term
    list in every shard. The match is deliberately neutral: it supplies a numeric
    reference and does not decide whether either label is a term or an alias.
    """

    visible_ordinals = {int(record["ordinal"]) for record in records}
    for record in records:
        visible_ordinals.update(record["visible_term_ordinals"])
    return tuple(
        (int(ordinal), term)
        for ordinal, term in records[0]["worker_term_index"]
        if int(ordinal) in visible_ordinals
    )


def _semantic_visibility_by_context(
    records: list[dict[str, Any]],
    term_index: tuple[tuple[int, str], ...],
) -> dict[str, frozenset[int]]:
    """Index visible labels once per distinct source context.

    Packet partitioning renders each growing shard repeatedly to measure its
    serialized size. Scanning the complete term index during every tentative
    render makes that loop superlinear in both queue size and context length.
    Context visibility is independent of packet membership, so compute it once
    and let each render take the union for its records.
    """

    context_texts = {
        str(context["text"]) for record in records for context in record["contexts"]
    }
    patterns = tuple(
        (
            int(ordinal),
            re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", flags=re.IGNORECASE),
        )
        for ordinal, term in term_index
        if term
    )
    return {
        text: frozenset(
            ordinal for ordinal, pattern in patterns if pattern.search(text)
        )
        for text in context_texts
    }


def build_semantic_packets(
    envelopes: Iterable[dict[str, Any]],
    *,
    source_sha256: str | None,
    target_characters: int = DEFAULT_TARGET_CHARACTERS,
    hard_max_characters: int = DEFAULT_HARD_MAX_CHARACTERS,
) -> PacketBuild:
    """Create sanitized semantic packets plus a private ID/location manifest."""

    envelope_list = list(envelopes)
    records: list[dict[str, Any]] = []
    for ordinal, envelope in enumerate(envelope_list, start=1):
        envelope_contexts = envelope.get("contexts")
        if not isinstance(envelope_contexts, list) or not envelope_contexts:
            raise ReviewPacketError(
                "semantic envelope contexts must be a non-empty array"
            )
        contexts = [
            {**context, "worker_text": _worker_text(context["text"])}
            for context in envelope_contexts
        ]
        term = str(envelope["term"])
        records.append(
            {
                "ordinal": ordinal,
                "review_id": str(envelope["review_id"]),
                "term": term,
                "worker_term": _worker_text(term),
                "contexts": contexts,
            }
        )
    term_index = tuple((record["ordinal"], record["term"]) for record in records)
    worker_term_index = tuple(
        (record["ordinal"], record["worker_term"]) for record in records
    )
    visibility_by_context = _semantic_visibility_by_context(records, term_index)
    for record in records:
        record["term_index"] = term_index
        record["worker_term_index"] = worker_term_index
        record["visible_term_ordinals"] = frozenset(
            ordinal
            for context in record["contexts"]
            for ordinal in visibility_by_context[str(context["text"])]
        )
    records_for_sharding = sorted(
        records,
        key=lambda record: (
            int(record["contexts"][0]["location"]["block_order"]),
            int(record["contexts"][0]["match_start"]),
            int(record["ordinal"]),
        ),
    )
    rendered = _partition(
        records_for_sharding,
        _semantic_packet,
        target_characters=target_characters,
        hard_max_characters=hard_max_characters,
    )
    packet_by_item = {
        item["ordinal"]: packet["packet"]
        for packet, _ in rendered
        for item in packet["items"]
    }
    manifest_items = []
    for record in records:
        manifest_items.append(
            {
                "ordinal": record["ordinal"],
                "packet": packet_by_item[record["ordinal"]],
                "review_id": record["review_id"],
                "term": record["term"],
                "contexts": [
                    {
                        "ordinal": local_ordinal,
                        "location": dict(context["location"]),
                        "match_start": int(context["match_start"]),
                        "match_end": int(context["match_end"]),
                        "text": str(context["text"]),
                    }
                    for local_ordinal, context in enumerate(record["contexts"], start=1)
                ],
            }
        )
    packets = tuple(packet for packet, _ in rendered)
    prompt = get_prompt("semantic")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "normalization_version": TERM_NORMALIZATION_VERSION,
        "stage": "semantic",
        "prompt_version": prompt.version,
        "prompt_sha256": prompt.sha256,
        "source_sha256": source_sha256,
        "queue_sha256": _queue_hash(
            [[record["ordinal"], record["review_id"]] for record in records]
        ),
        "target_characters": target_characters,
        "hard_max_characters": hard_max_characters,
        "packets": [
            {
                "packet": packet["packet"],
                "item_ordinals": [item["ordinal"] for item in packet["items"]],
                "characters": len(_compact_json(packet)),
                "oversized_indivisible_item": oversized,
            }
            for packet, oversized in rendered
        ],
        "items": manifest_items,
    }
    return PacketBuild("semantic", packets, manifest)


def _reference_packet(
    packet_ordinal: int, records: list[dict[str, Any]]
) -> dict[str, Any]:
    prompt = get_prompt("reference")
    context_pool: list[dict[str, Any]] = []
    context_ordinals: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for record in records:
        contexts: list[list[int]] = []
        for context in record["contexts"]:
            text = _worker_text(context["text"])
            context_ordinal = context_ordinals.get(text)
            if context_ordinal is None:
                context_ordinal = len(context_pool) + 1
                context_ordinals[text] = context_ordinal
                context_pool.append({"ordinal": context_ordinal, "text": text})
            contexts.append(
                [
                    context_ordinal,
                    int(context["match_start"]),
                    int(context["match_end"]),
                ]
            )
        items.append(
            {
                "ordinal": record["ordinal"],
                "target": _worker_text(record["reference_target"]),
                "contexts": contexts,
            }
        )
    decision_ordinals = [code for code, _ in prompt.decision_codes]
    review_reason_ordinals = [code for code, _ in prompt.review_reason_codes]
    item_ordinals = [int(item["ordinal"]) for item in items]
    all_contexts = sorted(
        {int(context[0]) for item in items for context in item["contexts"]}
    )
    row_schema = _closed_array_schema(
        [
            {"type": "integer", "enum": item_ordinals},
            {"type": "integer", "enum": decision_ordinals},
            {
                "type": "array",
                "items": {"type": "integer", "enum": all_contexts},
                "uniqueItems": True,
                "maxItems": MAX_REFERENCE_EVIDENCE,
            },
            {"type": "string"},
            {"type": "integer", "enum": review_reason_ordinals},
        ]
    )
    templates = [[ordinal, None, [], "", 0] for ordinal in item_ordinals]
    response_schema, response_template = _response_contract(
        packet_ordinal, row_schema, templates
    )
    return {
        "schema_version": PACKET_SCHEMA_VERSION,
        "normalization_version": TERM_NORMALIZATION_VERSION,
        "stage": "reference",
        "packet": packet_ordinal,
        "instruction": prompt.instruction,
        "prompt_version": prompt.version,
        "prompt_sha256": prompt.sha256,
        "row_fields": list(prompt.output_schema),
        "response_schema": response_schema,
        "response_template": response_template,
        "item_constraints": [
            {
                "item": int(item["ordinal"]),
                "evidence_contexts": [int(context[0]) for context in item["contexts"]],
            }
            for item in items
        ],
        "decision_codes": [list(item) for item in prompt.decision_codes],
        "review_reason_codes": [list(item) for item in prompt.review_reason_codes],
        "context_pool": context_pool,
        "items": items,
    }


def build_reference_packets(
    envelopes: Iterable[dict[str, Any]],
    *,
    source_sha256: str | None,
    target_characters: int = DEFAULT_TARGET_CHARACTERS,
    hard_max_characters: int = DEFAULT_HARD_MAX_CHARACTERS,
) -> PacketBuild:
    """Create sanitized reference packets and a private ID/source manifest."""

    envelope_list = list(envelopes)
    records = []
    for ordinal, envelope in enumerate(envelope_list, start=1):
        contexts = envelope.get("contexts")
        if not isinstance(contexts, list) or not contexts:
            raise ReviewPacketError(
                "reference envelope contexts must be a non-empty array"
            )
        records.append(
            {
                "ordinal": ordinal,
                "review_id": str(envelope["review_id"]),
                "definition_id": str(envelope.get("definition_id", "")),
                "reference_target": str(envelope["reference_target"]),
                "contexts": contexts,
            }
        )

    def contexts_for(record: dict[str, Any]) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], record["contexts"])

    def source_order(record: dict[str, Any]) -> tuple[int, int, int]:
        first_context = contexts_for(record)[0]
        location = cast(dict[str, Any], first_context["location"])
        return (
            int(location["block_order"]),
            int(first_context["match_start"]),
            int(record["ordinal"]),
        )

    records.sort(key=source_order)
    rendered = _partition(
        records,
        _reference_packet,
        target_characters=target_characters,
        hard_max_characters=hard_max_characters,
    )
    packet_by_item = {
        item["ordinal"]: packet["packet"]
        for packet, _ in rendered
        for item in packet["items"]
    }
    context_ordinals_by_item = {
        item["ordinal"]: [context[0] for context in item["contexts"]]
        for packet, _ in rendered
        for item in packet["items"]
    }
    prompt = get_prompt("reference")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "normalization_version": TERM_NORMALIZATION_VERSION,
        "stage": "reference",
        "prompt_version": prompt.version,
        "prompt_sha256": prompt.sha256,
        "source_sha256": source_sha256,
        "queue_sha256": _queue_hash(
            [
                [record["ordinal"], record["review_id"], record["definition_id"]]
                for record in sorted(records, key=lambda item: item["ordinal"])
            ]
        ),
        "target_characters": target_characters,
        "hard_max_characters": hard_max_characters,
        "packets": [
            {
                "packet": packet["packet"],
                "item_ordinals": [item["ordinal"] for item in packet["items"]],
                "characters": len(_compact_json(packet)),
                "oversized_indivisible_item": oversized,
            }
            for packet, oversized in rendered
        ],
        "items": [
            {
                "ordinal": record["ordinal"],
                "packet": packet_by_item[record["ordinal"]],
                "review_id": record["review_id"],
                "definition_id": record["definition_id"],
                "reference_target": record["reference_target"],
                "contexts": [
                    {
                        "ordinal": context_ordinals_by_item[record["ordinal"]][
                            index - 1
                        ],
                        "location": dict(context["location"]),
                        "match_start": int(context["match_start"]),
                        "match_end": int(context["match_end"]),
                        "text": str(context["text"]),
                    }
                    for index, context in enumerate(contexts_for(record), start=1)
                ],
            }
            for record in sorted(records, key=lambda item: item["ordinal"])
        ],
    }
    return PacketBuild("reference", tuple(packet for packet, _ in rendered), manifest)


def build_discovery_packets(
    seeds: Iterable[dict[str, Any]],
    *,
    source_sha256: str | None,
) -> PacketBuild:
    """Sanitize already-bounded discovery seeds into one worker packet per seed."""

    prompt = get_prompt("discovery")
    packets = []
    manifest_packets = []
    for packet_ordinal, seed in enumerate(seeds, start=1):
        fragments = list(seed.get("fragments") or [])
        fragment_ordinals = list(range(1, len(fragments) + 1))
        response_schema, response_template = _response_contract(
            packet_ordinal,
            _closed_array_schema(
                [
                    {"type": "integer", "enum": fragment_ordinals},
                    {"type": "integer", "minimum": 0},
                    {"type": "integer", "minimum": 1},
                    {"type": "string", "minLength": 1},
                    {"type": "string"},
                ]
            ),
            [],
            variable_rows=True,
        )
        packet = {
            "schema_version": PACKET_SCHEMA_VERSION,
            "normalization_version": TERM_NORMALIZATION_VERSION,
            "stage": "discovery",
            "packet": packet_ordinal,
            "instruction": prompt.instruction,
            "prompt_version": prompt.version,
            "prompt_sha256": prompt.sha256,
            "row_fields": list(prompt.output_schema),
            "response_schema": response_schema,
            "response_template": response_template,
            "outline": [
                _worker_text(item.get("text", "")) for item in seed.get("outline") or []
            ],
            "fragments": [
                [ordinal, _worker_text(fragment["text"])]
                for ordinal, fragment in enumerate(fragments, start=1)
            ],
        }
        packets.append(packet)
        manifest_packets.append(
            {
                "packet": packet_ordinal,
                "seed_id": str(seed.get("id", "")),
                "characters": len(_compact_json(packet)),
                "fragments": [
                    {
                        "ordinal": ordinal,
                        "location": dict(fragment["location"]),
                        "text": str(fragment["text"]),
                    }
                    for ordinal, fragment in enumerate(fragments, start=1)
                ],
            }
        )
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "normalization_version": TERM_NORMALIZATION_VERSION,
        "stage": "discovery",
        "prompt_version": prompt.version,
        "prompt_sha256": prompt.sha256,
        "source_sha256": source_sha256,
        "queue_sha256": _queue_hash(
            [[item["packet"], item["seed_id"]] for item in manifest_packets]
        ),
        "packets": manifest_packets,
    }
    return PacketBuild("discovery", tuple(packets), manifest)


def _occurrence_packet(
    packet_ordinal: int, groups: list[dict[str, Any]]
) -> dict[str, Any]:
    prompt = get_prompt("occurrence")
    context_pool: list[dict[str, Any]] = []
    context_ordinals: dict[str, int] = {}
    visible_groups: list[dict[str, Any]] = []
    for group in groups:
        visible_items: list[list[Any]] = []
        for item in group["items"]:
            context = item["context"]
            text = _worker_text(context["text"])
            pool_ordinal = context_ordinals.get(text)
            if pool_ordinal is None:
                pool_ordinal = len(context_pool) + 1
                context_ordinals[text] = pool_ordinal
                context_pool.append({"ordinal": pool_ordinal, "text": text})
            visible_items.append(
                [
                    item["ordinal"],
                    _worker_text(item["observed_form"]),
                    pool_ordinal,
                    int(context["match_start"]),
                    int(context["match_end"]),
                    [
                        [
                            _worker_text(match["term"]),
                            int(match["match_start"]),
                            int(match["match_end"]),
                        ]
                        for match in (item.get("collision") or {}).get("matches", [])
                    ],
                ]
            )
        visible_groups.append(
            {
                "term": _worker_text(group["term"]),
                "term_status": group["term_status"],
                "definition": (
                    _worker_text(group["definition"])
                    if group["definition"] is not None
                    else None
                ),
                "aliases": [_worker_text(alias) for alias in group["aliases"]],
                "items": visible_items,
            }
        )
    decision_ordinals = [code for code, _ in prompt.decision_codes]
    review_reason_ordinals = [code for code, _ in prompt.review_reason_codes]
    item_ordinals = [
        int(item[0]) for group in visible_groups for item in group["items"]
    ]
    row_schema = _closed_array_schema(
        [
            {"type": "integer", "enum": item_ordinals},
            {"type": "integer", "enum": decision_ordinals},
            {"type": "string"},
            {"type": "integer", "enum": review_reason_ordinals},
        ]
    )
    response_schema, response_template = _response_contract(
        packet_ordinal,
        row_schema,
        [[ordinal, None, "", 0] for ordinal in item_ordinals],
    )
    return {
        "schema_version": PACKET_SCHEMA_VERSION,
        "normalization_version": TERM_NORMALIZATION_VERSION,
        "stage": "occurrence",
        "packet": packet_ordinal,
        "instruction": prompt.instruction,
        "prompt_version": prompt.version,
        "prompt_sha256": prompt.sha256,
        "row_fields": list(prompt.output_schema),
        "response_schema": response_schema,
        "response_template": response_template,
        "decision_codes": [list(item) for item in prompt.decision_codes],
        "review_reason_codes": [list(item) for item in prompt.review_reason_codes],
        "context_pool": context_pool,
        "groups": visible_groups,
    }


def _split_occurrence_group(
    group: dict[str, Any],
    *,
    target_characters: int,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for item in group["items"]:
        proposed = {**group, "items": [*current, item]}
        size = _review_content_size(_occurrence_packet(1, [proposed]))
        if current and size > target_characters:
            chunks.append({**group, "items": current})
            current = [item]
        else:
            current.append(item)
    if current:
        chunks.append({**group, "items": current})
    return chunks


def build_occurrence_packets(
    envelopes: Iterable[dict[str, Any]],
    *,
    source_sha256: str | None,
    target_characters: int = DEFAULT_TARGET_CHARACTERS,
    hard_max_characters: int = DEFAULT_HARD_MAX_CHARACTERS,
    group_by_context: bool = False,
) -> PacketBuild:
    """Group occurrences by canonical term and shard complete worker packets."""

    _validate_limits(target_characters, hard_max_characters)
    envelope_list = list(envelopes)
    grouped: dict[str, dict[str, Any]] = {}
    group_order: list[str] = []
    records: list[dict[str, Any]] = []
    for ordinal, envelope in enumerate(envelope_list, start=1):
        context = envelope.get("context")
        if not isinstance(context, dict):
            raise ReviewPacketError("occurrence envelope context must be an object")
        term = str(envelope["term"])
        definition = envelope.get("definition_text")
        term_status = str(envelope.get("term_status", "defined"))
        if term_status not in {"defined", "undefined"}:
            raise ReviewPacketError("occurrence term_status is unsupported")
        aliases = envelope.get("aliases") or []
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) for alias in aliases
        ):
            raise ReviewPacketError("occurrence envelope aliases must be strings")
        if term not in grouped:
            grouped[term] = {
                "term": term,
                "term_status": term_status,
                "definition": str(definition) if definition is not None else None,
                "aliases": tuple(dict.fromkeys(aliases)),
                "items": [],
            }
            group_order.append(term)
        group = grouped[term]
        if (
            group["definition"] != (str(definition) if definition is not None else None)
            or group["aliases"] != tuple(dict.fromkeys(aliases))
            or group["term_status"] != term_status
        ):
            raise ReviewPacketError(
                f"occurrence envelopes disagree about canonical term {term!r}"
            )
        record = {
            "ordinal": ordinal,
            "review_id": str(envelope["review_id"]),
            "usage_id": str(envelope.get("usage_id", "")),
            "term": term,
            "term_status": term_status,
            "observed_form": str(envelope["observed_form"]),
            "context": context,
            "collision_id": (
                str(envelope["collision_id"])
                if envelope.get("collision_id") is not None
                else None
            ),
            "collision": envelope.get("collision"),
        }
        records.append(record)
        group["items"].append(record)

    chunks = [
        chunk
        for term in group_order
        for chunk in _split_occurrence_group(
            grouped[term], target_characters=target_characters
        )
    ]
    if group_by_context:
        # Keep every occurrence and its canonical definition. Adjacent groups
        # share paragraph text through the existing packet context pool.
        chunks = []
        by_context: dict[str, dict[str, dict[str, Any]]] = {}
        for record in records:
            context_key = _compact_json(
                [
                    record["context"]["location"].get("block_id"),
                    record["context"]["text"],
                ]
            )
            terms = by_context.setdefault(context_key, {})
            term = record["term"]
            if term not in terms:
                terms[term] = {**grouped[term], "items": []}
            terms[term]["items"].append(record)
        for terms in by_context.values():
            for group in terms.values():
                chunks.extend(
                    _split_occurrence_group(group, target_characters=target_characters)
                )
    rendered = _partition(
        chunks,
        _occurrence_packet,
        target_characters=target_characters,
        hard_max_characters=hard_max_characters,
    )
    packet_by_item = {
        item[0]: packet["packet"]
        for packet, _ in rendered
        for group in packet["groups"]
        for item in group["items"]
    }
    prompt = get_prompt("occurrence")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "normalization_version": TERM_NORMALIZATION_VERSION,
        "stage": "occurrence",
        "group_by_context": group_by_context,
        "prompt_version": prompt.version,
        "prompt_sha256": prompt.sha256,
        "source_sha256": source_sha256,
        "queue_sha256": _queue_hash(
            [
                [record["ordinal"], record["review_id"], record["usage_id"]]
                for record in records
            ]
        ),
        "target_characters": target_characters,
        "hard_max_characters": hard_max_characters,
        "packets": [
            {
                "packet": packet["packet"],
                "item_ordinals": [
                    item[0] for group in packet["groups"] for item in group["items"]
                ],
                "characters": len(_compact_json(packet)),
                "oversized_indivisible_item": oversized,
            }
            for packet, oversized in rendered
        ],
        "items": [
            {
                "ordinal": record["ordinal"],
                "packet": packet_by_item[record["ordinal"]],
                "review_id": record["review_id"],
                "usage_id": record["usage_id"],
                "term": record["term"],
                "term_status": record["term_status"],
                "observed_form": record["observed_form"],
                "collision_id": record["collision_id"],
                "location": dict(record["context"]["location"]),
            }
            for record in records
        ],
    }
    return PacketBuild("occurrence", tuple(packet for packet, _ in rendered), manifest)


def _atomic_json(path: Path, value: object, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite review packet artifact: {path}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            if compact:
                handle.write(_compact_json(value))
            else:
                json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def write_packet_builds(work_dir: str | Path, builds: Iterable[PacketBuild]) -> Path:
    """Write packets and private manifests into one run workspace."""

    root = Path(work_dir)
    packet_root = root / "packets"
    private_root = root / "private"
    packet_root.mkdir(parents=True, exist_ok=True)
    private_root.mkdir(parents=True, exist_ok=True)
    for build in builds:
        stage_dir = packet_root / build.stage
        manifest_path = private_root / f"{build.stage}-manifest.json"
        response_dir = root / "responses" / build.stage
        if manifest_path.exists():
            try:
                existing_manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise ReviewPacketError(
                    f"unable to trust existing packet manifest: {manifest_path}"
                ) from exc
            unchanged = all(
                existing_manifest.get(field) == build.manifest.get(field)
                for field in (
                    "schema_version",
                    "stage",
                    "source_sha256",
                    "queue_sha256",
                    "prompt_version",
                    "prompt_sha256",
                    "normalization_version",
                    "target_characters",
                    "hard_max_characters",
                    "group_by_context",
                )
            )
            if unchanged:
                expected_files = {
                    f"packet-{int(packet['packet']):03d}.json": packet
                    for packet in build.packets
                }
                actual_files = {path.name for path in stage_dir.glob("packet-*.json")}
                if actual_files != set(expected_files):
                    raise ReviewPacketError(
                        f"existing packet files do not match manifest: {stage_dir}"
                    )
                for name, expected_packet in expected_files.items():
                    try:
                        existing_packet = json.loads(
                            (stage_dir / name).read_text(encoding="utf-8")
                        )
                    except (OSError, json.JSONDecodeError) as exc:
                        raise ReviewPacketError(
                            f"unable to trust existing review packet: {stage_dir / name}"
                        ) from exc
                    if existing_packet != expected_packet:
                        raise ReviewPacketError(
                            f"existing review packet content does not match: {stage_dir / name}"
                        )
                continue
            if stage_dir.exists():
                shutil.rmtree(stage_dir)
            manifest_path.unlink()
            if response_dir.exists():
                shutil.rmtree(response_dir)
        elif stage_dir.exists() and any(stage_dir.iterdir()):
            raise ReviewPacketError(
                f"packet directory has no trusted manifest: {stage_dir}"
            )
        stage_dir.mkdir(parents=True, exist_ok=True)
        response_dir.mkdir(parents=True, exist_ok=True)
        for packet in build.packets:
            validate_review_packet(packet)
            _atomic_json(
                stage_dir / f"packet-{int(packet['packet']):03d}.json",
                packet,
                compact=True,
            )
        _atomic_json(manifest_path, build.manifest)
    return root


def _int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReviewPacketError(f"{field} must be an integer")
    return value


def _load_manifest_items(
    manifest: dict[str, Any], stage: str
) -> tuple[dict[int, dict[str, Any]], dict[int, set[int]]]:
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ReviewPacketError("unsupported review packet manifest version")
    if manifest.get("normalization_version") != TERM_NORMALIZATION_VERSION:
        raise ReviewPacketError("unsupported review packet normalization version")
    if manifest.get("stage") != stage:
        raise ReviewPacketError(f"expected a {stage} review packet manifest")
    prompt = get_prompt(stage)
    if (
        manifest.get("prompt_version") != prompt.version
        or manifest.get("prompt_sha256") != prompt.sha256
    ):
        raise ReviewPacketError("review packet manifest prompt provenance is invalid")
    raw_items = manifest.get("items")
    raw_packets = manifest.get("packets")
    if not isinstance(raw_items, list) or not isinstance(raw_packets, list):
        raise ReviewPacketError("review packet manifest is missing item coverage")
    items: dict[int, dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            raise ReviewPacketError("manifest items must be objects")
        ordinal = _int(item.get("ordinal"), "manifest item ordinal")
        if ordinal < 1 or ordinal in items:
            raise ReviewPacketError(
                "manifest item ordinals must be unique and positive"
            )
        items[ordinal] = item
    if sorted(items) != list(range(1, len(items) + 1)):
        raise ReviewPacketError("manifest item ordinals must be contiguous from 1")

    packet_items: dict[int, set[int]] = {}
    covered: set[int] = set()
    for packet in raw_packets:
        if not isinstance(packet, dict):
            raise ReviewPacketError("manifest packets must be objects")
        packet_ordinal = _int(packet.get("packet"), "manifest packet ordinal")
        ordinals = packet.get("item_ordinals")
        if (
            packet_ordinal < 1
            or packet_ordinal in packet_items
            or not isinstance(ordinals, list)
        ):
            raise ReviewPacketError("manifest packet coverage is invalid")
        packet_set = {_int(value, "manifest covered item") for value in ordinals}
        if len(packet_set) != len(ordinals) or not packet_set.issubset(items):
            raise ReviewPacketError("manifest packet item coverage is invalid")
        if covered.intersection(packet_set):
            raise ReviewPacketError("manifest assigns an item to multiple packets")
        packet_items[packet_ordinal] = packet_set
        covered.update(packet_set)
    if covered != set(items):
        raise ReviewPacketError("manifest packet coverage is incomplete")

    if stage == "semantic":
        hash_input = [[ordinal, items[ordinal].get("review_id")] for ordinal in items]
    elif stage == "reference":
        hash_input = [
            [
                ordinal,
                items[ordinal].get("review_id"),
                items[ordinal].get("definition_id"),
            ]
            for ordinal in items
        ]
    else:
        hash_input = [
            [
                ordinal,
                items[ordinal].get("review_id"),
                items[ordinal].get("usage_id"),
            ]
            for ordinal in items
        ]
    if manifest.get("queue_sha256") != _queue_hash(hash_input):
        raise ReviewPacketError("review packet manifest queue hash is invalid")
    return items, packet_items


def _response_rows(
    responses: Mapping[int, object],
    packet_items: dict[int, set[int]],
    *,
    manifest: dict[str, Any],
    stage: str,
) -> dict[int, list[list[Any]]]:
    if set(responses) != set(packet_items):
        raise ReviewPacketError(
            "compact response packet coverage is incomplete or mismatched"
        )
    parsed: dict[int, list[list[Any]]] = {}
    for packet_ordinal, payload in responses.items():
        canonical = (
            payload
            if isinstance(payload, dict)
            else {"packet": packet_ordinal, "rows": payload}
        )
        validate_packet_response(
            manifest,
            canonical,
            stage=stage,
            packet_ordinal=packet_ordinal,
        )
        rows: object
        if isinstance(payload, dict):
            declared = _int(payload.get("packet"), "response packet ordinal")
            if declared != packet_ordinal:
                raise ReviewPacketError(
                    "response packet ordinal does not match its file"
                )
            rows = payload.get("rows")
        else:
            rows = payload
        if not isinstance(rows, list) or any(not isinstance(row, list) for row in rows):
            raise ReviewPacketError("compact response rows must be an array of arrays")
        parsed[packet_ordinal] = rows
    return parsed


def _note(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewPacketError("compact reviewer note must be a non-empty string")
    if len(value) > 2000:
        raise ReviewPacketError(
            "compact reviewer note exceeds ledger compatibility limit"
        )
    return value.strip()


def _review_reason(stage: str, decision: str, value: object) -> str | None:
    code = _int(value, f"{stage} review reason code")
    reasons = dict(get_prompt(stage).review_reason_codes)
    if code not in reasons:
        raise ReviewPacketError(f"{stage} response contains an unknown review reason")
    reason = reasons[code]
    unresolved = decision in {"needs_review", "insufficient_evidence"}
    if unresolved and reason is None:
        raise ReviewPacketError(f"{stage} unresolved response requires a review reason")
    if not unresolved and reason is not None:
        raise ReviewPacketError(
            f"{stage} resolved response must use the none review reason"
        )
    return reason


def _load_discovery_manifest(
    manifest: dict[str, Any], *, expected_source_sha256: str | None = None
) -> dict[int, dict[int, dict[str, Any]]]:
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ReviewPacketError("unsupported review packet manifest version")
    if manifest.get("normalization_version") != TERM_NORMALIZATION_VERSION:
        raise ReviewPacketError("unsupported review packet normalization version")
    if manifest.get("stage") != "discovery":
        raise ReviewPacketError("expected a discovery review packet manifest")
    prompt = get_prompt("discovery")
    if (
        manifest.get("prompt_version") != prompt.version
        or manifest.get("prompt_sha256") != prompt.sha256
    ):
        raise ReviewPacketError("review packet manifest prompt provenance is invalid")
    if (
        expected_source_sha256 is not None
        and manifest.get("source_sha256") != expected_source_sha256
    ):
        raise ReviewPacketError("review packet manifest source hash does not match")
    raw_packets = manifest.get("packets")
    if not isinstance(raw_packets, list):
        raise ReviewPacketError("discovery manifest packets must be an array")
    packets: dict[int, dict[int, dict[str, Any]]] = {}
    queue_input = []
    for raw_packet in raw_packets:
        if not isinstance(raw_packet, dict):
            raise ReviewPacketError("discovery manifest packet must be an object")
        packet = _int(raw_packet.get("packet"), "discovery manifest packet")
        if packet < 1 or packet in packets:
            raise ReviewPacketError("discovery manifest packet ordinals are invalid")
        seed_id = raw_packet.get("seed_id")
        if not isinstance(seed_id, str):
            raise ReviewPacketError("discovery manifest seed ID must be a string")
        raw_fragments = raw_packet.get("fragments")
        if not isinstance(raw_fragments, list):
            raise ReviewPacketError("discovery manifest fragments must be an array")
        fragments: dict[int, dict[str, Any]] = {}
        for raw_fragment in raw_fragments:
            if not isinstance(raw_fragment, dict):
                raise ReviewPacketError("discovery manifest fragment must be an object")
            ordinal = _int(
                raw_fragment.get("ordinal"), "discovery manifest fragment ordinal"
            )
            text = raw_fragment.get("text")
            location = raw_fragment.get("location")
            if (
                ordinal < 1
                or ordinal in fragments
                or not isinstance(text, str)
                or not isinstance(location, dict)
            ):
                raise ReviewPacketError("discovery manifest fragment is invalid")
            fragments[ordinal] = raw_fragment
        if sorted(fragments) != list(range(1, len(fragments) + 1)):
            raise ReviewPacketError(
                "discovery manifest fragment ordinals must be contiguous from 1"
            )
        packets[packet] = fragments
        queue_input.append([packet, seed_id])
    if sorted(packets) != list(range(1, len(packets) + 1)):
        raise ReviewPacketError(
            "discovery manifest packet ordinals must be contiguous from 1"
        )
    if manifest.get("queue_sha256") != _queue_hash(queue_input):
        raise ReviewPacketError("discovery manifest queue hash is invalid")
    return packets


def _declared_rows(
    payload: object, packet_ordinal: int, *, strict_object: bool = False
) -> list[list[Any]]:
    rows: object
    if isinstance(payload, dict):
        if strict_object and set(payload) != {"packet", "rows"}:
            raise ReviewPacketError(
                "response object must contain exactly packet and rows"
            )
        declared = _int(payload.get("packet"), "response packet ordinal")
        if declared != packet_ordinal:
            raise ReviewPacketError("response packet ordinal does not match its file")
        rows = payload.get("rows")
    else:
        if strict_object:
            raise ReviewPacketError("response must be the packet JSON object")
        rows = payload
    if not isinstance(rows, list) or any(not isinstance(row, list) for row in rows):
        raise ReviewPacketError("compact response rows must be an array of arrays")
    return rows


def _validate_discovery_packet_rows(
    fragments: dict[int, dict[str, Any]], rows: list[list[Any]]
) -> list[tuple[str, Location, str]]:
    proposals = []
    for row in rows:
        if len(row) != 5:
            raise ReviewPacketError("discovery response rows must contain five fields")
        fragment_ordinal = _int(row[0], "discovery fragment ordinal")
        start = _int(row[1], "discovery start offset")
        end = _int(row[2], "discovery end offset")
        returned_term = row[3]
        note = _note(row[4])
        fragment = fragments.get(fragment_ordinal)
        if fragment is None:
            raise ReviewPacketError("discovery response cites an unknown fragment")
        original = fragment["text"]
        visible = _worker_text(original)
        if start < 0 or end <= start or end > len(visible):
            raise ReviewPacketError("discovery response span is out of bounds")
        if not isinstance(returned_term, str) or returned_term != visible[start:end]:
            raise ReviewPacketError(
                "discovery response term does not match its exact source span"
            )
        source_term = original[start:end]
        if not source_term.strip():
            raise ReviewPacketError("discovery response term must not be blank")
        try:
            base = Location(**fragment["location"])
        except (TypeError, ValueError) as exc:
            raise ReviewPacketError("discovery manifest location is invalid") from exc
        proposals.append(
            (
                source_term,
                Location(
                    part=base.part,
                    block_id=base.block_id,
                    block_order=base.block_order,
                    char_start=base.char_start + start,
                    char_end=base.char_start + end,
                ),
                note,
            )
        )
    return proposals


def expand_discovery_responses(
    manifest: dict[str, Any],
    responses: Mapping[int, object],
    *,
    agent_role: str = "discovery_reviewer",
    model_id: str | None = None,
    prompt_version: str | None = None,
    expected_source_sha256: str | None = None,
) -> tuple[CandidateProposal, ...]:
    """Expand and exact-deduplicate discovery rows into candidate proposals."""

    if not agent_role.strip():
        raise ReviewPacketError("agent_role must be non-empty supervisor metadata")
    packets = _load_discovery_manifest(
        manifest, expected_source_sha256=expected_source_sha256
    )
    if set(responses) != set(packets):
        raise ReviewPacketError(
            "compact response packet coverage is incomplete or mismatched"
        )
    source_sha256 = str(manifest.get("source_sha256") or "unknown-source")
    unique: dict[tuple[object, ...], CandidateProposal] = {}
    for packet_ordinal in sorted(packets):
        validate_packet_response(
            manifest,
            responses[packet_ordinal]
            if isinstance(responses[packet_ordinal], dict)
            else {"packet": packet_ordinal, "rows": responses[packet_ordinal]},
            stage="discovery",
            packet_ordinal=packet_ordinal,
        )
        rows = _declared_rows(responses[packet_ordinal], packet_ordinal)
        for term, location, note in _validate_discovery_packet_rows(
            packets[packet_ordinal], rows
        ):
            key = (
                term,
                location.part,
                location.block_id,
                location.char_start,
                location.char_end,
            )
            if key in unique:
                continue
            normalized = normalize_term(term)
            candidate_id = stable_id(
                "candidate",
                source_sha256,
                normalized,
                location.block_id,
                location.char_start,
                location.char_end,
            )
            unique[key] = CandidateProposal(
                id=stable_id("proposal", candidate_id, 1),
                candidate_id=candidate_id,
                term=term,
                normalized_term=normalized,
                location=location,
                state="candidate",
                agent_role=agent_role,
                revision=1,
                rationale_summary=note,
                model_id=model_id,
                prompt_version=prompt_version or str(manifest.get("prompt_version")),
            )
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (
                item.location.block_order,
                item.location.char_start,
                item.location.char_end,
                item.term,
            ),
        )
    )


def validate_packet_response(
    manifest: dict[str, Any],
    response: object,
    *,
    stage: str,
    packet_ordinal: int,
) -> int:
    """Validate one worker response before its stage-wide expansion."""

    if packet_ordinal < 1:
        raise ReviewPacketError("packet ordinal must be positive")
    rows = _declared_rows(response, packet_ordinal, strict_object=True)
    if stage == "discovery":
        packets = _load_discovery_manifest(manifest)
        if packet_ordinal not in packets:
            raise ReviewPacketError("response packet is not present in the manifest")
        _validate_discovery_packet_rows(packets[packet_ordinal], rows)
        return len(rows)

    items, packet_items = _load_manifest_items(manifest, stage)
    expected = packet_items.get(packet_ordinal)
    if expected is None:
        raise ReviewPacketError("response packet is not present in the manifest")
    raw_packet = next(
        (
            packet
            for packet in manifest["packets"]
            if isinstance(packet, dict) and packet.get("packet") == packet_ordinal
        ),
        None,
    )
    expected_order = [] if raw_packet is None else raw_packet.get("item_ordinals")
    if not isinstance(expected_order, list):
        raise ReviewPacketError(f"{stage} packet item order is invalid")
    seen: set[int] = set()
    decision_codes = dict(get_prompt(stage).decision_codes)
    for row in rows:
        expected_fields = {"semantic": 7, "occurrence": 4, "reference": 5}[stage]
        if len(row) != expected_fields:
            raise ReviewPacketError(
                f"{stage} response rows must contain {expected_fields} fields"
            )
        ordinal = _int(row[0], f"{stage} item ordinal")
        decision = _int(row[1], f"{stage} decision code")
        if ordinal not in expected:
            raise ReviewPacketError(f"{stage} response item is in the wrong packet")
        if ordinal in seen:
            raise ReviewPacketError(f"{stage} response contains a duplicate item")
        if decision not in decision_codes:
            raise ReviewPacketError(
                f"{stage} response contains an unknown decision code"
            )
        seen.add(ordinal)
        item = items[ordinal]
        if stage == "occurrence":
            decision_name = decision_codes[decision]
            if item.get("term_status", "defined") == "undefined" and decision_name in {
                "defined_term_use",
                "inconsistent_capitalization",
            }:
                raise ReviewPacketError(
                    "occurrence decision conflicts with undefined term status",
                    stage=stage,
                    packet=packet_ordinal,
                    item=ordinal,
                    field="decision",
                    code="occurrence_status_conflict",
                )
            _note(row[2])
            _review_reason(stage, decision_name, row[3])
            continue
        evidence = row[2]
        if (
            not isinstance(evidence, list)
            or any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in evidence
            )
            or len(evidence) != len(set(evidence))
            or (stage == "reference" and len(evidence) > MAX_REFERENCE_EVIDENCE)
        ):
            raise ReviewPacketError(
                f"{stage} evidence contexts must be a bounded unique integer array"
            )
        contexts = item.get("contexts")
        if not isinstance(contexts, list):
            raise ReviewPacketError(f"{stage} manifest item has no contexts")
        context_ordinals = {
            _int(context.get("ordinal"), f"{stage} context ordinal")
            for context in contexts
            if isinstance(context, dict)
        }
        if any(value not in context_ordinals for value in evidence):
            raise ReviewPacketError(f"{stage} response cites an unknown context")
        if (
            stage == "semantic"
            and decision_codes[decision] == "confirmed_external_reference"
            and not evidence
        ):
            raise ReviewPacketError(
                "external-reference semantic response requires source evidence",
                stage=stage,
                packet=packet_ordinal,
                item=ordinal,
                field="evidence_contexts",
                code="missing_source_evidence",
            )
        if stage == "reference":
            if not evidence:
                raise ReviewPacketError(
                    "reference response requires source evidence",
                    stage=stage,
                    packet=packet_ordinal,
                    item=ordinal,
                    field="evidence_contexts",
                    code="missing_source_evidence",
                    correction="Cite at least one item-local context ID.",
                )
            _note(row[3])
            _review_reason(stage, decision_codes[decision], row[4])
            continue
        spans = row[3]
        if decision_codes[decision] == "confirmed_defined":
            if not isinstance(spans, list) or not spans:
                raise ReviewPacketError(
                    "defined semantic response requires definition spans"
                )
            if len(spans) == 3 and all(not isinstance(value, list) for value in spans):
                spans = [spans]
            seen_spans: set[tuple[int, int, int]] = set()
            for span in spans:
                if not isinstance(span, list) or len(span) != 3:
                    raise ReviewPacketError(
                        "semantic definition spans must contain three-integer arrays"
                    )
                context_ordinal, start, end = (
                    _int(span[0], "semantic definition context"),
                    _int(span[1], "semantic definition start"),
                    _int(span[2], "semantic definition end"),
                )
                context = next(
                    (
                        value
                        for value in contexts
                        if isinstance(value, dict)
                        and value.get("ordinal") == context_ordinal
                    ),
                    None,
                )
                if not isinstance(context, dict):
                    raise ReviewPacketError(
                        "semantic definition span cites invalid context coordinates"
                    )
                text = context.get("text")
                if (
                    not isinstance(text, str)
                    or start < 0
                    or end <= start
                    or end > len(text)
                ):
                    raise ReviewPacketError(
                        "semantic definition span cites invalid context coordinates"
                    )
                match_start = context.get("match_start")
                match_end = context.get("match_end")
                if (
                    isinstance(match_start, bool)
                    or not isinstance(match_start, int)
                    or isinstance(match_end, bool)
                    or not isinstance(match_end, int)
                    or match_start < 0
                    or match_end <= match_start
                    or match_end > len(text)
                    or term_key(text[match_start:match_end])
                    != term_key(str(item.get("term", "")))
                ):
                    raise ReviewPacketError(
                        "defined semantic response has no matching label beside its definition",
                        stage=stage,
                        packet=packet_ordinal,
                        item=ordinal,
                        field="definitions",
                        code="definition_label_mismatch",
                        correction=(
                            "Cite a definition context whose matched label identifies this "
                            "exact item, or classify the cognate as an alias or non-definition."
                        ),
                    )
                if (
                    start > 0 and text[start - 1].isalnum() and text[start].isalnum()
                ) or (
                    end < len(text) and text[end - 1].isalnum() and text[end].isalnum()
                ):
                    raise ReviewPacketError(
                        f"semantic item {ordinal} definition span splits a word boundary"
                    )
                span_key = (context_ordinal, start, end)
                if span_key in seen_spans or any(
                    context_ordinal == seen_context
                    and start < seen_end
                    and seen_start < end
                    for seen_context, seen_start, seen_end in seen_spans
                ):
                    raise ReviewPacketError(
                        "semantic definition spans must be unique and non-overlapping"
                    )
                seen_spans.add(span_key)
        elif spans is not None:
            raise ReviewPacketError(
                "non-defined semantic response must use null definition spans"
            )
        _note(row[4])
        canonical = row[5]
        if decision_codes[decision] == "confirmed_alias":
            canonical_ordinal = _int(canonical, "semantic canonical item ordinal")
            if canonical_ordinal == ordinal or canonical_ordinal not in items:
                raise ReviewPacketError(
                    "alias response requires another valid canonical item"
                )
            if not evidence:
                raise ReviewPacketError(
                    "alias response requires shared source evidence"
                )
            alias_key = term_key(str(item.get("term", "")))
            canonical_key = term_key(str(items[canonical_ordinal].get("term", "")))
            if not any(
                alias_key in term_key(str(context.get("text", "")))
                and canonical_key in term_key(str(context.get("text", "")))
                for context in contexts
                if isinstance(context, dict) and context.get("ordinal") in evidence
            ):
                raise ReviewPacketError(
                    "alias response lacks shared source evidence for both labels"
                )
        elif canonical is not None:
            raise ReviewPacketError(
                "non-alias semantic response must use null canonical item"
            )
        _review_reason(stage, decision_codes[decision], row[6])
    if seen != expected:
        raise ReviewPacketError(f"{stage} compact response item coverage is incomplete")
    if stage == "semantic":
        decisions = {row[0]: decision_codes[row[1]] for row in rows}
        for row in rows:
            if (
                decisions[row[0]] == "confirmed_alias"
                and row[5] in decisions
                and decisions[row[5]] != "confirmed_defined"
            ):
                raise ReviewPacketError(
                    f"semantic item {row[0]} alias canonical item {row[5]} "
                    "must be confirmed as a definition; reassess the source "
                    "for a direct parenthetical short-form definition"
                )
    return len(rows)


def expand_semantic_responses(
    manifest: dict[str, Any],
    responses: Mapping[int, object],
    *,
    agent_role: str = "semantic_reviewer",
    model_id: str | None = None,
    prompt_version: str | None = None,
    expected_source_sha256: str | None = None,
) -> tuple[AdjudicationSubmission, ...]:
    """Expand strict seven-field semantic rows into the bundle contract."""

    if (
        expected_source_sha256 is not None
        and manifest.get("source_sha256") != expected_source_sha256
    ):
        raise ReviewPacketError("review packet manifest source hash does not match")
    if not agent_role.strip():
        raise ReviewPacketError("agent_role must be non-empty supervisor metadata")
    items, packet_items = _load_manifest_items(manifest, "semantic")
    packet_rows = _response_rows(
        responses, packet_items, manifest=manifest, stage="semantic"
    )
    decision_by_code = dict(get_prompt("semantic").decision_codes)
    seen: set[int] = set()
    parsed: list[
        tuple[
            int,
            int,
            list[int],
            list[list[int]] | None,
            bool,
            str,
            int | None,
            str | None,
        ]
    ] = []
    for packet_ordinal in sorted(packet_rows):
        for row in packet_rows[packet_ordinal]:
            if len(row) != 7:
                raise ReviewPacketError(
                    "semantic response rows must contain seven fields"
                )
            ordinal = _int(row[0], "semantic item ordinal")
            decision_code = _int(row[1], "semantic decision code")
            evidence = row[2]
            definition_spans = row[3]
            legacy_single_span = (
                isinstance(definition_spans, list)
                and len(definition_spans) == 3
                and all(not isinstance(value, list) for value in definition_spans)
            )
            note = _note(row[4])
            canonical = row[5]
            if ordinal not in packet_items[packet_ordinal]:
                raise ReviewPacketError("semantic response item is in the wrong packet")
            if ordinal in seen:
                raise ReviewPacketError("semantic response contains a duplicate item")
            if decision_code not in decision_by_code:
                raise ReviewPacketError(
                    "semantic response contains an unknown decision code"
                )
            review_reason = _review_reason(
                "semantic", decision_by_code[decision_code], row[6]
            )
            if not isinstance(evidence, list):
                raise ReviewPacketError("semantic evidence contexts must be an array")
            evidence_ordinals = [
                _int(value, "semantic evidence context") for value in evidence
            ]
            if len(evidence_ordinals) != len(set(evidence_ordinals)):
                raise ReviewPacketError("semantic evidence contexts must be unique")
            if definition_spans is not None:
                if (
                    isinstance(definition_spans, list)
                    and len(definition_spans) == 3
                    and all(not isinstance(value, list) for value in definition_spans)
                ):
                    definition_spans = [definition_spans]
                elif not isinstance(definition_spans, list):
                    raise ReviewPacketError(
                        "semantic definition spans must be an array"
                    )
                normalized_spans = []
                for definition_span in definition_spans:
                    if (
                        not isinstance(definition_span, list)
                        or len(definition_span) != 3
                    ):
                        raise ReviewPacketError(
                            "semantic definition spans must contain three-integer arrays"
                        )
                    normalized_spans.append(
                        [
                            _int(value, "semantic definition span")
                            for value in definition_span
                        ]
                    )
                definition_spans = normalized_spans
            canonical_ordinal = (
                None
                if canonical is None
                else _int(canonical, "semantic canonical item ordinal")
            )
            seen.add(ordinal)
            parsed.append(
                (
                    ordinal,
                    decision_code,
                    evidence_ordinals,
                    definition_spans,
                    legacy_single_span,
                    note,
                    canonical_ordinal,
                    review_reason,
                )
            )
    if seen != set(items):
        raise ReviewPacketError("semantic compact response item coverage is incomplete")

    decision_by_ordinal = {
        ordinal: decision_by_code[decision_code]
        for ordinal, decision_code, *_ in parsed
    }
    result = []
    for (
        ordinal,
        decision_code,
        evidence_ordinals,
        spans,
        legacy_single_span,
        note,
        canonical,
        review_reason,
    ) in parsed:
        item = items[ordinal]
        contexts = item.get("contexts")
        if not isinstance(contexts, list) or not contexts:
            raise ReviewPacketError("semantic manifest item has no contexts")
        context_by_ordinal = {
            _int(context.get("ordinal"), "manifest context ordinal"): context
            for context in contexts
            if isinstance(context, dict)
        }
        if set(context_by_ordinal) != set(range(1, len(contexts) + 1)):
            raise ReviewPacketError("semantic manifest context ordinals are invalid")
        if any(value not in context_by_ordinal for value in evidence_ordinals):
            raise ReviewPacketError("semantic response cites an unknown context")
        decision = decision_by_code[decision_code]
        definition_spans = ()
        if decision == "confirmed_defined":
            if spans is None or not spans:
                raise ReviewPacketError(
                    "defined semantic response requires definition spans"
                )
            seen_spans = set()
            for context_ordinal, start, end in spans:
                context = context_by_ordinal.get(context_ordinal)
                if context is None:
                    raise ReviewPacketError(
                        "semantic definition span cites an unknown context"
                    )
                text = context.get("text")
                if (
                    not isinstance(text, str)
                    or start < 0
                    or end <= start
                    or end > len(text)
                ):
                    raise ReviewPacketError("semantic definition span is out of bounds")
                span_key = (context_ordinal, start, end)
                if span_key in seen_spans or any(
                    context_ordinal == seen_context
                    and start < seen_end
                    and seen_start < end
                    for seen_context, seen_start, seen_end in seen_spans
                ):
                    raise ReviewPacketError(
                        "semantic definition spans must be unique and non-overlapping"
                    )
                seen_spans.add(span_key)
            definition_spans = tuple(
                (context_ordinal - 1, start, end)
                for context_ordinal, start, end in spans
            )
        elif spans is not None:
            raise ReviewPacketError(
                "non-defined semantic response must use null definition spans"
            )

        canonical_term = None
        if decision == "confirmed_alias":
            if canonical is None or canonical not in items or canonical == ordinal:
                raise ReviewPacketError(
                    "alias response requires another valid canonical item"
                )
            if decision_by_ordinal.get(canonical) != "confirmed_defined":
                raise ReviewPacketError(
                    "alias response canonical item must be confirmed as a definition",
                    stage="semantic",
                    item=ordinal,
                    field="canonical_item",
                    code="cross_packet_alias_conflict",
                    correction=(
                        "Reassess this alias and its canonical target; the target must "
                        "be a confirmed definition."
                    ),
                )
            canonical_term = str(items[canonical]["term"])
        elif canonical is not None:
            raise ReviewPacketError(
                "non-alias semantic response must use null canonical item"
            )
        result.append(
            AdjudicationSubmission(
                review_id=str(item["review_id"]),
                decision=decision,
                evidence_indexes=tuple(value - 1 for value in evidence_ordinals),
                rationale_summary=note,
                reason_codes=(),
                confidence=None,
                agent_role=agent_role,
                canonical_term=canonical_term,
                model_id=model_id,
                prompt_version=prompt_version,
                definition_spans=definition_spans,
                definition_text=(
                    context_by_ordinal[spans[0][0]]["text"][spans[0][1] : spans[0][2]]
                    if legacy_single_span and spans
                    else None
                ),
                definition_context_index=(
                    spans[0][0] - 1 if legacy_single_span and spans else None
                ),
                definition_start=(
                    spans[0][1] if legacy_single_span and spans else None
                ),
                definition_end=(spans[0][2] if legacy_single_span and spans else None),
                review_reason=review_reason,
            )
        )
    return tuple(sorted(result, key=lambda item: item.review_id))


def expand_occurrence_responses(
    manifest: dict[str, Any],
    responses: dict[int, object],
    *,
    agent_role: str = "occurrence_reviewer",
    model_id: str | None = None,
    prompt_version: str | None = None,
    expected_source_sha256: str | None = None,
) -> tuple[OccurrenceSubmission, ...]:
    """Expand strict four-field occurrence rows into the bundle contract."""

    if (
        expected_source_sha256 is not None
        and manifest.get("source_sha256") != expected_source_sha256
    ):
        raise ReviewPacketError("review packet manifest source hash does not match")
    if not agent_role.strip():
        raise ReviewPacketError("agent_role must be non-empty supervisor metadata")
    items, packet_items = _load_manifest_items(manifest, "occurrence")
    packet_rows = _response_rows(
        responses, packet_items, manifest=manifest, stage="occurrence"
    )
    decision_by_code = dict(get_prompt("occurrence").decision_codes)
    seen: set[int] = set()
    result = []
    for packet_ordinal in sorted(packet_rows):
        for row in packet_rows[packet_ordinal]:
            if len(row) != 4:
                raise ReviewPacketError(
                    "occurrence response rows must contain four fields"
                )
            ordinal = _int(row[0], "occurrence item ordinal")
            decision_code = _int(row[1], "occurrence decision code")
            note = _note(row[2])
            if ordinal not in packet_items[packet_ordinal]:
                raise ReviewPacketError(
                    "occurrence response item is in the wrong packet"
                )
            if ordinal in seen:
                raise ReviewPacketError("occurrence response contains a duplicate item")
            if decision_code not in decision_by_code:
                raise ReviewPacketError(
                    "occurrence response contains an unknown decision code"
                )
            review_reason = _review_reason(
                "occurrence", decision_by_code[decision_code], row[3]
            )
            seen.add(ordinal)
            item = items[ordinal]
            result.append(
                OccurrenceSubmission(
                    review_id=str(item["review_id"]),
                    decision=decision_by_code[decision_code],
                    rationale_summary=note,
                    reason_codes=(),
                    confidence=None,
                    agent_role=agent_role,
                    model_id=model_id,
                    prompt_version=prompt_version,
                    review_reason=review_reason,
                )
            )
    if seen != set(items):
        raise ReviewPacketError(
            "occurrence compact response item coverage is incomplete"
        )
    return tuple(sorted(result, key=lambda item: item.review_id))


def expand_reference_responses(
    manifest: dict[str, Any],
    responses: Mapping[int, object],
    *,
    agent_role: str = "reference_reviewer",
    model_id: str | None = None,
    prompt_version: str | None = None,
    expected_source_sha256: str | None = None,
) -> tuple[ReferenceSubmission, ...]:
    """Expand strict five-field reference rows into scoped submissions."""

    if (
        expected_source_sha256 is not None
        and manifest.get("source_sha256") != expected_source_sha256
    ):
        raise ReviewPacketError("review packet manifest source hash does not match")
    if not agent_role.strip():
        raise ReviewPacketError("agent_role must be non-empty supervisor metadata")
    items, packet_items = _load_manifest_items(manifest, "reference")
    packet_rows = _response_rows(
        responses, packet_items, manifest=manifest, stage="reference"
    )
    decision_by_code = dict(get_prompt("reference").decision_codes)
    seen: set[int] = set()
    result = []
    for packet_ordinal in sorted(packet_rows):
        for row in packet_rows[packet_ordinal]:
            if len(row) != 5:
                raise ReviewPacketError(
                    "reference response rows must contain five fields"
                )
            ordinal = _int(row[0], "reference item ordinal")
            decision_code = _int(row[1], "reference decision code")
            evidence = row[2]
            note = _note(row[3])
            if ordinal not in packet_items[packet_ordinal]:
                raise ReviewPacketError(
                    "reference response item is in the wrong packet"
                )
            if ordinal in seen:
                raise ReviewPacketError("reference response contains a duplicate item")
            if decision_code not in decision_by_code:
                raise ReviewPacketError(
                    "reference response contains an unknown decision code"
                )
            if (
                not isinstance(evidence, list)
                or any(
                    isinstance(index, bool) or not isinstance(index, int)
                    for index in evidence
                )
                or len(evidence) != len(set(evidence))
                or len(evidence) > MAX_REFERENCE_EVIDENCE
            ):
                raise ReviewPacketError(
                    "reference evidence_contexts must be a bounded unique integer array"
                )
            seen.add(ordinal)
            item = items[ordinal]
            manifest_contexts = item.get("contexts")
            if not isinstance(manifest_contexts, list) or not manifest_contexts:
                raise ReviewPacketError("reference manifest item has no contexts")
            evidence_by_ordinal = {
                _int(context.get("ordinal"), "reference context ordinal"): index
                for index, context in enumerate(manifest_contexts)
                if isinstance(context, dict)
            }
            if any(index not in evidence_by_ordinal for index in evidence):
                raise ReviewPacketError(
                    "reference response cites an unknown context ordinal"
                )
            review_reason = _review_reason(
                "reference", decision_by_code[decision_code], row[4]
            )
            result.append(
                ReferenceSubmission(
                    review_id=str(item["review_id"]),
                    decision=decision_by_code[decision_code],
                    evidence_indexes=tuple(
                        evidence_by_ordinal[index] for index in evidence
                    ),
                    rationale_summary=note,
                    agent_role=agent_role,
                    model_id=model_id,
                    prompt_version=prompt_version,
                    review_reason=review_reason,
                )
            )
    if seen != set(items):
        raise ReviewPacketError(
            "reference compact response item coverage is incomplete"
        )
    return tuple(sorted(result, key=lambda item: item.review_id))
