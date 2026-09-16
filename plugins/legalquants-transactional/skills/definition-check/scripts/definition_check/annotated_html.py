"""Render an opt-in, full-document QA view with reviewed term annotations."""

from __future__ import annotations

import html
import json
import os
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Ledger, Location
from .projection import project_reviewed_inventory

_CATEGORY_LABELS = {
    "definition": "Confirmed definition",
    "usage": "Confirmed defined-term use",
    "mapped_variant": "Mapped variant",
    "inconsistent": "Inconsistent capitalization",
    "undefined": "Confirmed undefined term",
    "needs_review": "Needs review",
    "shadowed": "Shadowed overlapping match",
    "proper_name": "Proper name",
    "rejected": "Rejected lexical match",
    "unreviewed": "Unreviewed candidate",
}
_CATEGORY_PRIORITY = {
    "undefined": 0,
    "inconsistent": 1,
    "definition": 2,
    "needs_review": 3,
    "usage": 4,
    "mapped_variant": 5,
    "shadowed": 6,
    "proper_name": 7,
    "unreviewed": 8,
    "rejected": 9,
}


@dataclass(frozen=True)
class _Annotation:
    id: str
    category: str
    term: str
    location: Location
    decision: str
    definition_text: str | None = None
    rationale: str | None = None
    variant_id: str | None = None
    variant_type: str | None = None
    mapping_status: str | None = None


def _json_for_script(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _location_from_dict(value: dict[str, Any]) -> Location:
    return Location(
        str(value["part"]),
        str(value["block_id"]),
        int(value["block_order"]),
        int(value["char_start"]),
        int(value["char_end"]),
    )


def _annotations(ledger: Ledger) -> list[_Annotation]:
    data = ledger.to_dict()
    semantic_by_review = {
        item["review_id"]: item for item in data.get("semantic_adjudications", [])
    }
    candidate_by_review = {
        item["review_id"]: item for item in data.get("term_candidates", [])
    }
    semantic_by_normalized: dict[str, dict[str, Any]] = {}
    for review_id, candidate in candidate_by_review.items():
        decision = semantic_by_review.get(review_id)
        if decision is not None:
            semantic_by_normalized[str(candidate["normalized_term"])] = decision

    occurrence_by_usage = {
        item["usage_id"]: item for item in data.get("occurrence_adjudications", [])
    }
    variants_by_id = {item["id"]: item for item in data.get("term_variants", [])}
    definitions_by_normalized = {
        item["normalized_term"]: item for item in data.get("definitions", [])
    }
    semantic_complete = (data.get("semantic_review") or {}).get("status") == "complete"
    occurrence_complete = (data.get("occurrence_review") or {}).get(
        "status"
    ) == "complete"
    annotations: list[_Annotation] = []
    seen: set[tuple[str, str, int, int, str]] = set()

    def add(
        category: str,
        term: str,
        location: Location,
        decision: str,
        *,
        definition_text: str | None = None,
        rationale: str | None = None,
        variant_id: str | None = None,
        variant_type: str | None = None,
        mapping_status: str | None = None,
    ) -> None:
        if location.char_end <= location.char_start:
            return
        key = (
            category,
            location.block_id,
            location.char_start,
            location.char_end,
            term,
        )
        if key in seen:
            return
        seen.add(key)
        annotations.append(
            _Annotation(
                id=f"ann-{len(annotations) + 1}",
                category=category,
                term=term,
                location=location,
                decision=decision,
                definition_text=definition_text,
                rationale=rationale,
                variant_id=variant_id,
                variant_type=variant_type,
                mapping_status=mapping_status,
            )
        )

    for definition in data.get("definitions", []):
        decision = semantic_by_normalized.get(definition["normalized_term"])
        disposition = decision and decision.get("decision")
        if disposition == "confirmed_defined":
            category = "definition"
        elif disposition == "rejected_proper_name":
            category = "proper_name"
        elif disposition == "rejected_not_a_term":
            category = "rejected"
        elif disposition in {"needs_review", "insufficient_evidence"}:
            category = "needs_review"
        else:
            category = "unreviewed"
        add(
            category,
            str(definition["term"]),
            _location_from_dict(definition["location"]),
            str(disposition or "raw extracted definition"),
            definition_text=str(definition.get("definition_text") or ""),
            rationale=str(decision.get("rationale_summary") or "")
            if decision
            else None,
        )

    projected_usages, _ = project_reviewed_inventory(data)
    mapped_variant_spans: set[tuple[str, int, int]] = set()
    for usage in projected_usages:
        if usage.get("is_definition_occurrence"):
            continue
        semantic = semantic_by_normalized.get(str(usage["normalized_term"]))
        semantic_decision = semantic and semantic.get("decision")
        occurrence = occurrence_by_usage.get(usage["id"])
        occurrence_decision = occurrence and occurrence.get("decision")
        if occurrence_decision == "inconsistent_capitalization":
            category = "inconsistent"
        elif semantic_decision == "confirmed_defined" and (
            not occurrence_complete or occurrence_decision in {None, "defined_term_use"}
        ):
            category = "mapped_variant" if usage.get("variant_id") else "usage"
        else:
            continue
        definition = definitions_by_normalized.get(usage["normalized_term"])
        variant = variants_by_id.get(str(usage.get("variant_id") or ""))
        if usage.get("variant_id") and category in {"mapped_variant", "inconsistent"}:
            mapped_variant_spans.add(
                (
                    str(usage["location"]["block_id"]),
                    int(usage["location"]["char_start"]),
                    int(usage["location"]["char_end"]),
                )
            )
        add(
            category,
            str(usage.get("observed_form") or usage["term"]),
            _location_from_dict(usage["location"]),
            str(occurrence_decision or semantic_decision or "lexical usage"),
            definition_text=str(definition.get("definition_text") or "")
            if definition
            else None,
            rationale=str(occurrence.get("rationale_summary") or "")
            if occurrence
            else None,
            variant_id=str(usage.get("variant_id"))
            if usage.get("variant_id")
            else None,
            variant_type=str(variant.get("variant_type")) if variant else None,
            mapping_status=str(variant.get("mapping_status")) if variant else None,
        )

    for review_id, candidate in candidate_by_review.items():
        decision = semantic_by_review.get(review_id)
        disposition = decision and decision.get("decision")
        if disposition == "confirmed_undefined":
            category = "undefined"
        elif disposition == "rejected_proper_name":
            category = "proper_name"
        elif disposition == "rejected_not_a_term":
            category = "rejected"
        elif disposition in {"needs_review", "insufficient_evidence"}:
            category = "needs_review"
        elif not semantic_complete and not candidate.get("definition_ids"):
            category = "unreviewed"
        else:
            continue
        for raw_location in candidate.get("locations", []):
            candidate_span = (
                str(raw_location["block_id"]),
                int(raw_location["char_start"]),
                int(raw_location["char_end"]),
            )
            if category == "rejected" and candidate_span in mapped_variant_spans:
                continue
            add(
                category,
                str(candidate["term"]),
                _location_from_dict(raw_location),
                str(disposition or "unreviewed candidate"),
                rationale=str(decision.get("rationale_summary") or "")
                if decision
                else None,
            )

    if occurrence_complete:
        usage_by_id = {item["id"]: item for item in data.get("usages", [])}
        for usage_id, decision in occurrence_by_usage.items():
            disposition = decision.get("decision")
            if disposition not in {
                "ordinary_language",
                "proper_name_component",
                "shadowed_by_overlapping_term",
            }:
                continue
            usage = usage_by_id.get(usage_id)
            if usage is None:
                continue
            definition = definitions_by_normalized.get(usage["normalized_term"])
            add(
                (
                    "shadowed"
                    if disposition == "shadowed_by_overlapping_term"
                    else "proper_name"
                    if disposition == "proper_name_component"
                    else "rejected"
                ),
                str(usage.get("observed_form") or usage["term"]),
                _location_from_dict(usage["location"]),
                str(disposition),
                definition_text=str(definition.get("definition_text") or "")
                if definition
                else None,
                rationale=str(decision.get("rationale_summary") or ""),
            )

    return annotations


def _render_block(text: str, annotations: list[_Annotation]) -> str:
    valid = [
        item
        for item in annotations
        if 0 <= item.location.char_start < item.location.char_end <= len(text)
    ]
    if not valid:
        return html.escape(text)
    boundaries = {0, len(text)}
    for item in valid:
        boundaries.update((item.location.char_start, item.location.char_end))
    ordered = sorted(boundaries)
    pieces: list[str] = []
    for start, end in zip(ordered, ordered[1:], strict=False):
        fragment = html.escape(text[start:end])
        active = [
            item
            for item in valid
            if item.location.char_start <= start and end <= item.location.char_end
        ]
        if not active:
            pieces.append(fragment)
            continue
        active.sort(key=lambda item: (_CATEGORY_PRIORITY[item.category], item.id))
        categories = " ".join(dict.fromkeys(item.category for item in active))
        identifiers = ",".join(item.id for item in active)
        label = "; ".join(
            f"{_CATEGORY_LABELS[item.category]}: {item.term}" for item in active
        )
        pieces.append(
            f'<mark class="annotation {categories}" tabindex="0" '
            f'data-annotation-ids="{html.escape(identifiers, quote=True)}" '
            f'aria-label="{html.escape(label, quote=True)}">{fragment}</mark>'
        )
    return "".join(pieces)


def render_annotated_html(ledger: Ledger) -> str:
    annotations = _annotations(ledger)
    by_block: dict[str, list[_Annotation]] = defaultdict(list)
    for item in annotations:
        by_block[item.location.block_id].append(item)
    counts = Counter(item.category for item in annotations)
    details = {
        item.id: {
            "category": item.category,
            "category_label": _CATEGORY_LABELS[item.category],
            "term": item.term,
            "decision": item.decision,
            "definition_text": item.definition_text,
            "rationale": item.rationale,
            "variant_id": item.variant_id,
            "variant_type": item.variant_type,
            "mapping_status": item.mapping_status,
            "location": {
                "part": item.location.part,
                "block_id": item.location.block_id,
                "block_order": item.location.block_order,
                "char_start": item.location.char_start,
                "char_end": item.location.char_end,
            },
        }
        for item in annotations
    }
    controls = "".join(
        '<label class="filter"><input type="checkbox"'
        + (
            ""
            if category in {"rejected", "proper_name", "shadowed", "unreviewed"}
            else " checked"
        )
        + f' data-category="{category}"><span class="swatch {category}"></span>'
        + f"{html.escape(label)} <strong>{counts.get(category, 0)}</strong></label>"
        for category, label in _CATEGORY_LABELS.items()
    )
    blocks = []
    for block in sorted(ledger.source.blocks, key=lambda item: (item.order, item.id)):
        location = f"Paragraph {block.order + 1}"
        if block.table_index is not None:
            location += (
                f" · Table {block.table_index + 1}, row {(block.row_index or 0) + 1}, "
                f"cell {(block.cell_index or 0) + 1}"
            )
        content = _render_block(block.text, by_block.get(block.id, []))
        empty = " empty" if not block.text else ""
        blocks.append(
            f'<section class="document-block{empty}" id="block-{html.escape(block.id, quote=True)}">'
            f'<div class="block-meta">{html.escape(location)} · {html.escape(block.id)}</div>'
            f"<p>{content}</p></section>"
        )
    source_name = html.escape(ledger.source.name or "Untitled", quote=True)
    coverage = html.escape(
        json.dumps(
            {
                "coverage": ledger.source.coverage,
                "warnings": ledger.source.warnings,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    style = """
:root { color-scheme: light; font: 15px system-ui, sans-serif; line-height: 1.5; }
* { box-sizing: border-box; }
body { margin: 0; color: #17202a; background: #eef2f6; }
header { position: sticky; top: 0; z-index: 3; padding: .8rem 1rem; background: #fff; border-bottom: 1px solid #cbd5df; }
header h1 { margin: 0; font-size: 1.25rem; }
header p { margin: .2rem 0; }
.filters { display: flex; flex-wrap: wrap; gap: .45rem 1rem; margin-top: .6rem; }
.filter { display: inline-flex; gap: .35rem; align-items: center; font-size: .88rem; }
.swatch { width: .8rem; height: .8rem; border-radius: .15rem; }
.layout { display: grid; grid-template-columns: minmax(0, 1fr) 22rem; gap: 1rem; max-width: 1500px; margin: auto; padding: 1rem; }
.document, aside { background: #fff; border: 1px solid #cbd5df; border-radius: .4rem; }
.document { padding: 1.2rem 1.5rem; }
.document-block { margin: 0 0 .9rem; scroll-margin-top: 10rem; }
.document-block p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.document-block.empty p { min-height: .55rem; }
.block-meta { color: #718096; font-size: .72rem; opacity: 0; transition: opacity .15s; }
.document-block:hover .block-meta { opacity: 1; }
aside { position: sticky; top: 10rem; align-self: start; max-height: calc(100vh - 11rem); overflow: auto; padding: 1rem; }
aside h2 { margin-top: 0; }
aside dl { margin-bottom: 0; }
aside dt { font-weight: 700; margin-top: .7rem; }
aside dd { margin: .1rem 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.annotation { border-radius: .15rem; color: inherit; cursor: pointer; padding: 0 .04rem; }
.annotation:focus, .annotation.selected { outline: 2px solid #111827; outline-offset: 1px; }
.annotation.definition, .swatch.definition { background: #b7ebc6; }
.annotation.usage, .swatch.usage { background: #bee3f8; }
.annotation.mapped_variant, .swatch.mapped_variant { background: #c4f1e1; border-bottom: 2px dotted #237a57; }
.annotation.inconsistent, .swatch.inconsistent { background: #fbd38d; }
.annotation.undefined, .swatch.undefined { background: #feb2b2; }
.annotation.needs_review, .swatch.needs_review { background: #d6bcfa; }
.annotation.rejected, .swatch.rejected { background: #e2e8f0; text-decoration: line-through; }
.annotation.proper_name, .swatch.proper_name { background: #e0f2fe; border-bottom: 2px dotted #0369a1; }
.annotation.shadowed, .swatch.shadowed { background: #e9d8fd; border-bottom: 2px dashed #6b46c1; }
.annotation.unreviewed, .swatch.unreviewed { background: #faf089; }
.annotation.annotation-hidden { background: transparent; outline: 0; text-decoration: none; cursor: text; }
.muted { color: #58677a; }
details { margin-top: 1rem; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: .75rem; }
@media (max-width: 900px) { .layout { grid-template-columns: 1fr; } aside { position: static; max-height: none; } header { position: static; } }
""".strip()
    script = r"""
(function () {
  "use strict";
  const details = JSON.parse(document.getElementById("annotation-data").textContent);
  const panel = document.getElementById("annotation-detail");
  const esc = function (value) { const node = document.createElement("span"); node.textContent = value == null ? "" : String(value); return node.innerHTML; };
  function show(mark) {
    document.querySelectorAll("mark.selected").forEach(function (item) { item.classList.remove("selected"); });
    mark.classList.add("selected");
    const items = String(mark.dataset.annotationIds || "").split(",").map(function (id) { return details[id]; }).filter(Boolean);
    panel.innerHTML = items.map(function (item) {
      const loc = item.location;
      return "<section><h3>" + esc(item.term) + "</h3><dl><dt>Annotation</dt><dd>" + esc(item.category_label) + "</dd><dt>Decision</dt><dd>" + esc(item.decision) + "</dd>" + (item.variant_type ? "<dt>Variant type</dt><dd>" + esc(item.variant_type) + "</dd>" : "") + (item.mapping_status ? "<dt>Mapping status</dt><dd>" + esc(item.mapping_status) + "</dd>" : "") + (item.definition_text ? "<dt>Definition</dt><dd>" + esc(item.definition_text) + "</dd>" : "") + (item.rationale ? "<dt>Review rationale</dt><dd>" + esc(item.rationale) + "</dd>" : "") + "<dt>Location</dt><dd>" + esc(loc.block_id + " (" + loc.char_start + "-" + loc.char_end + ")") + "</dd></dl></section>";
    }).join("") || "<p class=muted>No annotation details.</p>";
  }
  document.querySelectorAll("mark.annotation").forEach(function (mark) {
    mark.addEventListener("click", function () { if (!mark.classList.contains("annotation-hidden")) show(mark); });
    mark.addEventListener("keydown", function (event) { if ((event.key === "Enter" || event.key === " ") && !mark.classList.contains("annotation-hidden")) { event.preventDefault(); show(mark); } });
  });
  function applyFilters() {
    const enabled = new Set(Array.from(document.querySelectorAll("[data-category]")).filter(function (input) { return input.checked; }).map(function (input) { return input.dataset.category; }));
    document.querySelectorAll("mark.annotation").forEach(function (mark) {
      const visible = Array.from(mark.classList).some(function (name) { return enabled.has(name); });
      mark.classList.toggle("annotation-hidden", !visible);
      mark.tabIndex = visible ? 0 : -1;
    });
  }
  document.querySelectorAll("[data-category]").forEach(function (input) { input.addEventListener("change", applyFilters); });
  applyFilters();
})();
""".strip()
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Annotated definition QA — {source_name}</title><style>{style}</style></head><body>"
        f"<header><h1>Annotated definition QA</h1><p>{source_name}</p>"
        '<p class="muted">Full extracted document text in source order. This is a QA view, not a Word-format reproduction. '
        '<a href="definition-check.html">Open term glossary</a>.</p>'
        f'<div class="filters">{controls}</div></header>'
        '<main class="layout"><article class="document" aria-label="Annotated extracted document">'
        + "".join(blocks)
        + '</article><aside><h2>Annotation detail</h2><div id="annotation-detail" class="muted">Select a highlighted term.</div>'
        f"<details><summary>Extraction coverage</summary><pre>{coverage}</pre></details></aside></main>"
        '<script type="application/json" id="annotation-data">'
        + _json_for_script(details)
        + f"</script><script>{script}</script></body></html>\n"
    )


def write_annotated_html(ledger: Ledger, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(render_annotated_html(ledger))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
