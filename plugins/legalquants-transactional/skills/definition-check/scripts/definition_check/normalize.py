"""Deterministic normalization of defined terms into placeholder variables.

Reads one or more versioned definition-check ledgers (schema 0.14.0) together
with the DOCX each ledger was built from, and rewrites every accepted usage of
a defined term into a stable placeholder variable (e.g. ``«T001»``, or
``«A:T001»`` when several documents are normalized together). The result is a
single versioned ``definition-normalization-1.0.0`` artifact carrying:

- per-block ``normalized_text`` for every document,
- a lookup table mapping each variable back to its definition, and
- for multi-document runs, a deterministic cross-document report flagging
  same-name definitions and variant-form collisions for agentic review.

The module never decides semantic equivalence. Usages the ledger leaves
unresolved (unmapped variants, terms with duplicate definitions) are left
untouched and reported, never guessed. Every source span is re-validated
against the DOCX text; any drift between ledger and document fails closed.
"""

from __future__ import annotations

import json
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from .models import SCHEMA_VERSION as LEDGER_SCHEMA_VERSION
from .ooxml import IntakeError, extract_docx
from .term_identity import term_key

NORMALIZATION_SCHEMA_VERSION = "definition-normalization-1.0.0"
SUPPORTED_LEDGER_SCHEMA_VERSIONS = frozenset({LEDGER_SCHEMA_VERSION})

EXIT_UNSUPPORTED_LEDGER = 20
EXIT_SOURCE_MISMATCH = 21
EXIT_SPAN_INTEGRITY = 22
EXIT_INTAKE = 23


class NormalizationError(ValueError):
    """A fail-closed normalization stop, carrying its CLI exit code."""

    def __init__(self, message: str, *, exit_code: int = EXIT_INTAKE) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def load_ledger(path: Path) -> dict[str, Any]:
    """Read a ledger JSON file and fail closed on anything but a supported version."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise NormalizationError(f"unable to read ledger {path!s}") from exc
    except json.JSONDecodeError as exc:
        raise NormalizationError(f"ledger {path!s} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise NormalizationError(f"ledger {path!s} must be a JSON object")
    version = payload.get("schema_version")
    if version not in SUPPORTED_LEDGER_SCHEMA_VERSIONS:
        supported = ", ".join(sorted(SUPPORTED_LEDGER_SCHEMA_VERSIONS))
        raise NormalizationError(
            f"ledger {path!s} has unsupported schema_version {version!r}; "
            f"supported: {supported}",
            exit_code=EXIT_UNSUPPORTED_LEDGER,
        )
    for field in ("source", "definitions", "usages"):
        if field not in payload:
            raise NormalizationError(
                f"ledger {path!s} is missing required field {field!r}"
            )
    return payload


def _document_key(index: int) -> str:
    return chr(ord("A") + index) if index < 26 else f"DOC{index + 1}"


def _splice(text: str, spans: list[tuple[int, int, str]]) -> str:
    result = text
    for start, end, replacement in sorted(spans, reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


def _label_forms(definition: dict[str, Any]) -> list[str]:
    return [
        form
        for form in [definition.get("term"), *(definition.get("aliases") or [])]
        if form
    ]


def _span_matches_label(span_text: str, definition: dict[str, Any]) -> bool:
    forms = _label_forms(definition)
    if span_text in forms:
        return True
    folded = term_key(span_text)
    return any(folded == term_key(form) for form in forms)


def _word_bounded_occurrences(text: str, needle: str):
    start = 0
    while needle:
        index = text.find(needle, start)
        if index < 0:
            return
        end = index + len(needle)
        before = text[index - 1] if index > 0 else " "
        after = text[end] if end < len(text) else " "
        if not (before.isalnum() or before == "_") and not (
            after.isalnum() or after == "_"
        ):
            yield index, end
        start = index + 1


def _splice_declared_meaning(
    definition_text: str,
    label_index: list[tuple[str, str]],
    *,
    own_variable: str,
) -> tuple[str, list[str]]:
    """Splice variables into a declared (non-span) meaning, deterministically.

    Only exact, case-sensitive, word-bounded occurrences of other
    definitions' canonical labels are replaced; overlapping candidates lose
    to the longest match. No aliases, no case folding — anything softer is
    semantic judgment and stays with the agentic layer.
    """
    matches: list[tuple[int, int, str]] = []
    for label, variable in label_index:
        if variable == own_variable:
            continue
        for start, end in _word_bounded_occurrences(definition_text, label):
            matches.append((start, end, variable))
    matches.sort(key=lambda item: (-(item[1] - item[0]), item[0]))
    accepted: list[tuple[int, int, str]] = []
    for start, end, variable in matches:
        if any(
            start < other_end and other_start < end
            for other_start, other_end, _ in accepted
        ):
            continue
        accepted.append((start, end, variable))
    depends_on = sorted({variable for _, _, variable in accepted})
    return _splice(definition_text, accepted), depends_on


def _require_location(record: dict[str, Any], *, owner: str) -> dict[str, Any]:
    location = record.get("location")
    if not isinstance(location, dict):
        raise NormalizationError(
            f"{owner} {record.get('id')!r} carries no location",
            exit_code=EXIT_SPAN_INTEGRITY,
        )
    return location


def _block_for(blocks: dict[str, Any], location: dict[str, Any], *, owner: str) -> Any:
    block = blocks.get(location.get("block_id"))
    if block is None:
        raise NormalizationError(
            f"{owner} references a block absent from the DOCX: {location.get('block_id')!r}",
            exit_code=EXIT_SPAN_INTEGRITY,
        )
    return block


def normalize_document(
    docx_path: Path,
    ledger: dict[str, Any],
    *,
    document_key: str,
    prefix_variables: bool,
) -> dict[str, Any]:
    """Normalize one document against its ledger into the artifact's document entry."""
    try:
        document = extract_docx(docx_path)
    except IntakeError as exc:
        raise NormalizationError(f"unable to intake {docx_path!s}: {exc}") from exc
    source_meta = ledger["source"]
    if (
        source_meta.get("sha256") != document.sha256
        or source_meta.get("document_id") != document.document_id
    ):
        raise NormalizationError(
            f"ledger source binding does not match {docx_path!s}; "
            "the ledger was built from a different document",
            exit_code=EXIT_SOURCE_MISMATCH,
        )
    blocks = {block.id: block for block in document.blocks}

    definitions = ledger["definitions"]
    usages = ledger["usages"]
    variants = {item["id"]: item for item in ledger.get("term_variants") or []}

    ordered = sorted(
        definitions,
        key=lambda item: (
            _require_location(item, owner="definition")["block_order"],
            item["location"]["char_start"],
            item["id"],
        ),
    )
    width = max(3, len(str(len(ordered))))
    variable_by_definition: dict[str, str] = {}
    for index, definition in enumerate(ordered, start=1):
        token = f"T{index:0{width}d}"
        if prefix_variables:
            variable = f"«{document_key}:{token}»"
        else:
            variable = f"«{token}»"
        variable_by_definition[definition["id"]] = variable

    definitions_by_term: dict[str, list[str]] = {}
    for definition in ordered:
        definitions_by_term.setdefault(definition["normalized_term"], []).append(
            definition["id"]
        )

    spans_by_block: dict[str, list[tuple[int, int, str]]] = {}
    replaced_usage_ids: dict[str, list[str]] = {
        definition["id"]: [] for definition in ordered
    }
    skipped_usages: list[dict[str, Any]] = []
    for usage in usages:
        usage_id = usage.get("id")
        candidates = definitions_by_term.get(usage.get("normalized_term"))
        if not candidates:
            raise NormalizationError(
                f"usage {usage_id!r} has no matching definition in the ledger",
                exit_code=EXIT_SPAN_INTEGRITY,
            )
        location = _require_location(usage, owner="usage")
        variant_id = usage.get("variant_id")
        if variant_id is not None:
            variant = variants.get(variant_id)
            if variant is None:
                raise NormalizationError(
                    f"usage {usage_id!r} references unknown variant {variant_id!r}",
                    exit_code=EXIT_SPAN_INTEGRITY,
                )
            if usage_id not in (variant.get("mapped_usage_ids") or []):
                skipped_usages.append(
                    {
                        "usage_id": usage_id,
                        "term": usage.get("term"),
                        "observed_form": usage.get("observed_form"),
                        "location": dict(location),
                        "reason": f"variant_{variant.get('mapping_status', 'unknown')}",
                    }
                )
                continue
        if len(candidates) > 1:
            skipped_usages.append(
                {
                    "usage_id": usage_id,
                    "term": usage.get("term"),
                    "observed_form": usage.get("observed_form"),
                    "location": dict(location),
                    "reason": "multiple_definitions",
                }
            )
            continue
        definition_id = candidates[0]
        block = _block_for(blocks, location, owner=f"usage {usage_id!r}")
        start = location["char_start"]
        end = location["char_end"]
        if block.text[start:end] != usage.get("observed_form"):
            raise NormalizationError(
                f"usage {usage_id!r} span does not match the DOCX text; "
                "the ledger and document have drifted",
                exit_code=EXIT_SPAN_INTEGRITY,
            )
        spans_by_block.setdefault(block.id, []).append(
            (start, end, variable_by_definition[definition_id])
        )
        replaced_usage_ids[definition_id].append(usage_id)

    for block_id, spans in spans_by_block.items():
        spans.sort()
        for (_, end, _), (next_start, _, _) in zip(spans, spans[1:], strict=False):
            if next_start < end:
                raise NormalizationError(
                    f"overlapping usage spans in block {block_id!r}",
                    exit_code=EXIT_SPAN_INTEGRITY,
                )

    label_index = [
        (definition["term"], variable_by_definition[definition["id"]])
        for definition in ordered
        if definition.get("term")
    ]

    variable_entries: list[dict[str, Any]] = []
    for definition in ordered:
        location = _require_location(definition, owner="definition")
        block = _block_for(blocks, location, owner=f"definition {definition['id']!r}")
        start = location["char_start"]
        end = location["char_end"]
        span_text = block.text[start:end]
        own_variable = variable_by_definition[definition["id"]]
        if span_text == definition.get("definition_text"):
            meaning_source = "span_verified"
            inner = [
                (span_start - start, span_end - start, variable)
                for span_start, span_end, variable in spans_by_block.get(block.id, [])
                if start <= span_start and span_end <= end
            ]
            normalized_definition_text = _splice(span_text, inner)
            depends_on = sorted({variable for _, _, variable in inner} - {own_variable})
        elif _span_matches_label(span_text, definition):
            # The ledger records the label's location; the meaning is declared
            # text reconstructed elsewhere (e.g. spanning earlier paragraphs).
            # Carry the declared meaning with verbatim, word-bounded variable
            # splices only — never a run-killer, never silently span-derived.
            meaning_source = "declared"
            normalized_definition_text, depends_on = _splice_declared_meaning(
                definition.get("definition_text") or "",
                label_index,
                own_variable=own_variable,
            )
        else:
            raise NormalizationError(
                f"definition {definition['id']!r} span matches neither the "
                "definition text nor the term label; the ledger and document "
                "have drifted",
                exit_code=EXIT_SPAN_INTEGRITY,
            )
        variable_entries.append(
            {
                "variable": own_variable,
                "term": definition["term"],
                "normalized_term": definition["normalized_term"],
                "definition_id": definition["id"],
                "document_key": document_key,
                "definition_text": definition["definition_text"],
                "normalized_definition_text": normalized_definition_text,
                "meaning_source": meaning_source,
                "depends_on": depends_on,
                "pattern": definition.get("pattern"),
                "scope": definition.get("scope"),
                "reference_target": definition.get("reference_target"),
                "aliases": list(definition.get("aliases") or []),
                "location": dict(location),
                "replaced_usage_ids": replaced_usage_ids[definition["id"]],
            }
        )

    block_entries = []
    for block in document.blocks:
        normalized_text = _splice(
            block.text,
            [
                (start, end, variable)
                for start, end, variable in spans_by_block.get(block.id, [])
            ],
        )
        block_entries.append(
            {
                "block_id": block.id,
                "part": block.part,
                "block_order": block.order,
                "text": block.text,
                "normalized_text": normalized_text,
            }
        )

    return {
        "document_key": document_key,
        "document_id": document.document_id,
        "name": document.name,
        "sha256": document.sha256,
        "variables": variable_entries,
        "blocks": block_entries,
        "skipped_usages": skipped_usages,
    }


def build_cross_document_report(
    documents: list[dict[str, Any]], ledgers: list[dict[str, Any]]
) -> dict[str, Any]:
    """Deterministic cross-document flags; equivalence decisions stay agentic."""
    by_normalized_term: dict[str, list[dict[str, Any]]] = {}
    form_map: dict[str, set[tuple[str, str]]] = {}
    for document, ledger in zip(documents, ledgers, strict=True):
        key = document["document_key"]
        unique_terms = {
            entry["normalized_term"]
            for entry in document["variables"]
            if sum(
                1
                for other in document["variables"]
                if other["normalized_term"] == entry["normalized_term"]
            )
            == 1
        }
        for entry in document["variables"]:
            by_normalized_term.setdefault(entry["normalized_term"], []).append(
                {
                    "document_key": key,
                    "variable": entry["variable"],
                    "definition_id": entry["definition_id"],
                    "term": entry["term"],
                }
            )
            forms = {term_key(entry["term"]), term_key(entry["normalized_term"])}
            forms.update(term_key(alias) for alias in entry["aliases"])
            for form in forms:
                form_map.setdefault(form, set()).add((key, entry["normalized_term"]))
        for variant in ledger.get("term_variants") or []:
            normalized_term = variant.get("normalized_term")
            observed_form = variant.get("observed_form")
            if not normalized_term or not observed_form:
                continue
            if normalized_term not in unique_terms:
                continue
            form_map.setdefault(term_key(observed_form), set()).add(
                (key, normalized_term)
            )

    same_name_definitions = [
        {"normalized_term": term, "definitions": occurrences}
        for term, occurrences in sorted(by_normalized_term.items())
        if len({item["document_key"] for item in occurrences}) > 1
    ]
    variant_collisions = [
        {
            "form": form,
            "mappings": [
                {"document_key": key, "normalized_term": term}
                for key, term in sorted(mappings)
            ],
        }
        for form, mappings in sorted(form_map.items())
        if len({term for _, term in mappings}) > 1
        and len({key for key, _ in mappings}) > 1
    ]
    return {
        "same_name_definitions": same_name_definitions,
        "cross_doc_variant_collisions": variant_collisions,
    }


def normalize_pairs(pairs: list[tuple[Path, Path]]) -> dict[str, Any]:
    """Normalize one or more (docx, ledger) pairs into a single artifact."""
    multi = len(pairs) > 1
    documents: list[dict[str, Any]] = []
    ledgers: list[dict[str, Any]] = []
    for index, (docx_path, ledger_path) in enumerate(pairs):
        ledger = load_ledger(ledger_path)
        documents.append(
            normalize_document(
                docx_path,
                ledger,
                document_key=_document_key(index),
                prefix_variables=multi,
            )
        )
        ledgers.append(ledger)
    artifact: dict[str, Any] = {
        "normalization_schema_version": NORMALIZATION_SCHEMA_VERSION,
        "ledger_schema_version": LEDGER_SCHEMA_VERSION,
        "generated_by": "normalize_terms.py",
        "generated_at": datetime.now(UTC).isoformat(),
        "documents": documents,
    }
    if multi:
        artifact["cross_document"] = build_cross_document_report(documents, ledgers)
    return artifact
