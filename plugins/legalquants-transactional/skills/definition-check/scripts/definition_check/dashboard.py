"""Render the completed Definition Check as a lawyer-facing dashboard."""

from __future__ import annotations

import html
import json
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .dashboard_theme import DASHBOARD_STYLE
from .models import Ledger
from .projection import project_reviewed_inventory

_COMPLETED_RUNS = {"completed", "completed_reduced_assurance"}
_RULES = {
    "DEF-001": (
        "undefined",
        "Used but not defined",
        "This term is used as a defined concept, but this document does not define it.",
    ),
    "DEF-002": (
        "unused",
        "Unused definition",
        "This definition appears in the agreement, but no operative use was found outside the definition.",
    ),
    "DEF-003": (
        "duplicate",
        "Duplicate or conflicting definition",
        "This defined label appears in more than one definition and the source language should be compared.",
    ),
    "DEF-004": (
        "inconsistent",
        "Inconsistent term",
        "This defined concept appears in a form or capitalization that is inconsistent with its definition.",
    ),
    "DEF-005": (
        "used-before",
        "Used before definition",
        "This term appears in operative text before its definition.",
    ),
    "DEF-006": (
        "broken-reference",
        "Broken definition reference",
        "This definition points to language that the completed check could not resolve within the supplied review scope.",
    ),
    "DEF-007": (
        "external-reference",
        "Referenced document not checked",
        "This document specifically refers to outside material that was not supplied for this check.",
    ),
}

_REVIEW_REASON_COPY = {
    "missing_external_evidence": (
        "Missing external evidence",
        "Supply the identified outside document and review it separately.",
    ),
    "ambiguous_term_identity": (
        "Ambiguous term identity",
        "Confirm whether the exact label is intended to carry a defined legal meaning.",
    ),
    "uncertain_occurrence_identity": (
        "Uncertain occurrence identity",
        "Compare this occurrence with the definition and its surrounding operative sentence.",
    ),
    "incomplete_source_context": (
        "Incomplete source context",
        "Provide the omitted surrounding or companion source context.",
    ),
    "ambiguous_reference": (
        "Ambiguous reference",
        "Confirm the intended target from the drafting source or identified companion document.",
    ),
}


def _json_for_script(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _is_review_complete(summary: object) -> bool:
    return isinstance(summary, dict) and summary.get("status") == "complete"


def dashboard_eligible(ledger: Ledger) -> bool:
    """Return whether a complete lawyer dashboard can be rendered truthfully."""

    data = ledger.to_dict()
    reference_candidates = data.get("reference_candidates") or []
    has_reference_finding = any(
        item.get("rule_id") == "DEF-006" for item in data.get("findings") or []
    )
    reference_complete = _is_review_complete(data.get("reference_review"))
    if (reference_candidates or has_reference_finding) and not reference_complete:
        return False
    if reference_complete and data.get("reference_review", {}).get(
        "queue_count"
    ) != len(reference_candidates):
        return False
    return bool(
        data.get("run_status") in _COMPLETED_RUNS
        and _is_review_complete(data.get("semantic_review"))
        and _is_review_complete(data.get("occurrence_review"))
        and ledger.source.blocks
    )


def _location_key(location: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        int(location.get("block_order") or 0),
        int(location.get("char_start") or 0),
        int(location.get("char_end") or 0),
        str(location.get("block_id") or ""),
    )


def _location_span_key(location: dict[str, Any]) -> tuple[str, int, int]:
    return (
        str(location.get("block_id") or ""),
        int(location.get("char_start") or 0),
        int(location.get("char_end") or 0),
    )


def _first_rationale(
    locations: list[dict[str, Any]],
    rationale_by_location: dict[tuple[str, int, int], str],
) -> str:
    for location in locations:
        rationale = rationale_by_location.get(_location_span_key(location), "").strip()
        if rationale:
            return rationale
    return ""


def _source_text(blocks: dict[str, Any], location: dict[str, Any]) -> str:
    block = blocks.get(str(location.get("block_id") or ""))
    if block is None:
        return ""
    start = int(location.get("char_start") or 0)
    end = int(location.get("char_end") or 0)
    if not 0 <= start <= end <= len(block.text):
        return ""
    return block.text[start:end]


def _excerpt(
    blocks: dict[str, Any], location: dict[str, Any], radius: int = 150
) -> str:
    block = blocks.get(str(location.get("block_id") or ""))
    if block is None:
        return ""
    start = int(location.get("char_start") or 0)
    end = int(location.get("char_end") or 0)
    if not 0 <= start <= end <= len(block.text):
        return ""
    left = max(0, start - radius)
    right = min(len(block.text), end + radius)
    prefix = "…" if left else ""
    suffix = "…" if right < len(block.text) else ""
    return prefix + block.text[left:right] + suffix


def _friendly_term(
    normalized: str | None,
    locations: list[dict[str, Any]],
    blocks: dict[str, Any],
    terms_by_normalized: dict[str, str],
) -> str:
    if normalized and normalized in terms_by_normalized:
        return terms_by_normalized[normalized]
    for location in locations:
        source = _source_text(blocks, location).strip()
        if source:
            return source
    return normalized or "Document language"


def _evidence_items(
    rule_id: str,
    locations: list[dict[str, Any]],
    blocks: dict[str, Any],
) -> list[dict[str, Any]]:
    items = []
    for index, location in enumerate(locations):
        if rule_id == "DEF-005":
            label = "Definition" if index == len(locations) - 1 else "Earlier use"
        elif rule_id == "DEF-003":
            label = f"Definition {index + 1}"
        else:
            label = "Source language" if index == 0 else "Related language"
        items.append(
            {
                "label": label,
                "excerpt": _excerpt(blocks, location),
                "location": dict(location),
            }
        )
    return items


def _action_locations(
    rule_id: str, locations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if rule_id == "DEF-004" and len(locations) > 1:
        return locations[1:]
    if rule_id == "DEF-005" and len(locations) > 1:
        return locations[:-1]
    if rule_id == "DEF-006" and len(locations) > 1:
        return locations[1:2]
    return locations


def _review_term_stem(value: str) -> str:
    normalized = value.casefold().strip()
    return normalized[:-1] if normalized.endswith("s") else normalized


def _group_related_review_results(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group only source-provable review relationships without merging meanings."""

    grouped: list[dict[str, Any]] = []
    for result in results:
        if result["category"] != "needs-review":
            grouped.append(result)
            continue
        block_scope = {
            (item["block_id"], item["block_order"]) for item in result["locations"]
        }
        match = next(
            (
                item
                for item in grouped
                if item["category"] == "needs-review"
                and _review_term_stem(item["term"]) == _review_term_stem(result["term"])
                and {(loc["block_id"], loc["block_order"]) for loc in item["locations"]}
                == block_scope
            ),
            None,
        )
        if match is None:
            result["related_labels"] = [result["term"]]
            grouped.append(result)
            continue
        match["related_labels"].append(result["term"])
        for location, evidence in zip(
            result["locations"], result["evidence"], strict=False
        ):
            if _location_span_key(location) not in {
                _location_span_key(item) for item in match["locations"]
            }:
                match["locations"].append(location)
                match["evidence"].append(evidence)
        match["term"] = " / ".join(match["related_labels"])
    return grouped


def build_dashboard_view(ledger: Ledger) -> dict[str, Any]:
    """Project a completed ledger into an allowlisted lawyer-facing view model."""

    if not dashboard_eligible(ledger):
        raise ValueError(
            "a lawyer dashboard requires a completed review and source text"
        )

    data = ledger.to_dict()
    blocks = {block.id: block for block in ledger.source.blocks}
    definitions = list(data.get("definitions") or [])
    usage_by_id = {item["id"]: item for item in data.get("usages") or []}
    candidate_by_review = {
        item["review_id"]: item for item in data.get("term_candidates") or []
    }
    semantic_rationale_by_location: dict[tuple[str, int, int], str] = {}
    semantic_rationale_by_term: dict[str, str] = {}
    for decision in data.get("semantic_adjudications") or []:
        rationale = str(decision.get("rationale_summary") or "").strip()
        if not rationale:
            continue
        candidate = candidate_by_review.get(decision.get("review_id"))
        if candidate is not None and decision.get("decision") == "confirmed_defined":
            semantic_rationale_by_term.setdefault(
                str(candidate.get("normalized_term") or ""), rationale
            )
        semantic_locations = [dict(item) for item in decision.get("evidence") or []]
        semantic_locations.extend(
            dict(item["location"])
            for item in decision.get("definition_spans") or []
            if item.get("location")
        )
        for location in semantic_locations:
            semantic_rationale_by_location.setdefault(
                _location_span_key(location), rationale
            )
    occurrence_rationale_by_usage: dict[str, str] = {}
    occurrence_rationale_by_location: dict[tuple[str, int, int], str] = {}
    for decision in data.get("occurrence_adjudications") or []:
        rationale = str(decision.get("rationale_summary") or "").strip()
        usage_id = str(decision.get("usage_id") or "")
        usage = usage_by_id.get(usage_id)
        if not rationale or usage is None:
            continue
        occurrence_rationale_by_usage[usage_id] = rationale
        occurrence_rationale_by_location[_location_span_key(usage["location"])] = (
            rationale
        )
    reference_rationale_by_location: dict[tuple[str, int, int], str] = {}
    for decision in data.get("reference_adjudications") or []:
        rationale = str(decision.get("rationale_summary") or "").strip()
        if not rationale:
            continue
        for location in decision.get("evidence") or []:
            reference_rationale_by_location.setdefault(
                _location_span_key(location), rationale
            )
    terms_by_normalized = {
        str(item.get("normalized_term") or ""): str(item.get("term") or "")
        for item in definitions
    }
    for candidate in data.get("term_candidates") or []:
        normalized = str(candidate.get("normalized_term") or "")
        terms_by_normalized.setdefault(normalized, str(candidate.get("term") or ""))

    reviewed_usages, reviewed_findings = project_reviewed_inventory(data)
    results: list[dict[str, Any]] = []
    for finding in reviewed_findings:
        mapping = _RULES.get(str(finding.get("rule_id") or ""))
        if mapping is None:
            continue
        locations = [dict(item) for item in finding.get("evidence") or []]
        if not locations:
            continue
        category, label, explanation = mapping
        rule_id = str(finding.get("rule_id") or "")
        if rule_id == "DEF-003":
            definition_texts = {
                str(item.get("definition_text") or "").strip()
                for item in definitions
                if item.get("normalized_term") == finding.get("normalized_term")
            }
            if len(definition_texts) == 1:
                label = "Repeated definition"
                explanation = (
                    "This label is defined more than once using identical meaning text."
                )
        action_locations = _action_locations(rule_id, locations)
        if rule_id == "DEF-001":
            rationale = _first_rationale(
                action_locations, semantic_rationale_by_location
            )
        elif rule_id in {"DEF-004", "DEF-005"}:
            rationale = _first_rationale(
                action_locations, occurrence_rationale_by_location
            )
        elif rule_id == "DEF-006":
            rationale = _first_rationale(
                action_locations, reference_rationale_by_location
            )
        else:
            rationale = ""
        result_id = f"result-{len(results) + 1}"
        normalized = finding.get("normalized_term")
        results.append(
            {
                "id": result_id,
                "category": category,
                "label": label,
                "term": _friendly_term(
                    normalized, locations, blocks, terms_by_normalized
                ),
                "explanation": explanation,
                "rationale": rationale,
                "scope_qualification": finding.get("scope_qualification", "none"),
                "scope_target": finding.get("scope_target"),
                "evidence": _evidence_items(rule_id, locations, blocks),
                "location": min(action_locations, key=_location_key),
                "locations": locations,
            }
        )

    for decision in data.get("semantic_adjudications") or []:
        if decision.get("decision") not in {"needs_review", "insufficient_evidence"}:
            continue
        candidate = candidate_by_review.get(decision.get("review_id"))
        if candidate is None:
            continue
        locations = [
            dict(item)
            for item in decision.get("evidence") or candidate.get("locations") or []
        ]
        if not locations:
            continue
        results.append(
            {
                "id": f"result-{len(results) + 1}",
                "category": "needs-review",
                "label": "Needs review",
                "term": str(candidate.get("term") or "Document language"),
                "explanation": "The completed check could not determine conclusively whether this language creates or uses a defined term.",
                "rationale": str(decision.get("rationale_summary") or "").strip(),
                "review_reason": decision.get("review_reason"),
                "evidence": _evidence_items("", locations, blocks),
                "location": min(locations, key=_location_key),
                "locations": locations,
            }
        )

    for decision in data.get("occurrence_adjudications") or []:
        if decision.get("decision") not in {"needs_review", "insufficient_evidence"}:
            continue
        usage = usage_by_id.get(decision.get("usage_id"))
        if usage is None:
            continue
        location = dict(usage["location"])
        results.append(
            {
                "id": f"result-{len(results) + 1}",
                "category": "needs-review",
                "label": "Needs review",
                "term": str(
                    usage.get("observed_form")
                    or usage.get("term")
                    or "Document language"
                ),
                "explanation": "The completed check could not determine conclusively whether this occurrence uses the defined concept.",
                "rationale": str(decision.get("rationale_summary") or "").strip(),
                "review_reason": decision.get("review_reason"),
                "evidence": _evidence_items("", [location], blocks),
                "location": location,
                "locations": [location],
            }
        )

    reference_by_review = {
        item["review_id"]: item for item in data.get("reference_candidates") or []
    }
    for decision in data.get("reference_adjudications") or []:
        if decision.get("decision") not in {"needs_review", "insufficient_evidence"}:
            continue
        candidate = reference_by_review.get(decision.get("review_id"))
        if candidate is None:
            continue
        supporting_locations = [
            dict(item)
            for item in decision.get("evidence") or [candidate["reference_location"]]
        ]
        reference_location = dict(candidate["reference_location"])
        evidence_locations = [reference_location]
        evidence_locations.extend(
            location
            for location in supporting_locations
            if _location_span_key(location) != _location_span_key(reference_location)
        )
        results.append(
            {
                "id": f"result-{len(results) + 1}",
                "category": "needs-review",
                "label": "Needs review",
                "term": str(candidate.get("term") or "Document language"),
                "explanation": "The completed check could not determine conclusively whether the referenced definition target is resolved within the supplied scope.",
                "rationale": str(decision.get("rationale_summary") or "").strip(),
                "review_reason": decision.get("review_reason"),
                "evidence": _evidence_items("", evidence_locations, blocks),
                "location": reference_location,
                "locations": [reference_location],
            }
        )

    results = _group_related_review_results(results)
    results.sort(
        key=lambda item: (*_location_key(item["location"]), item["label"], item["term"])
    )
    for index, item in enumerate(results, start=1):
        item["id"] = f"result-{index}"

    occurrence_by_usage = {
        item["usage_id"]: item["decision"]
        for item in data.get("occurrence_adjudications") or []
    }
    mapped_variants_by_term: dict[str, list[str]] = defaultdict(list)
    for variant in data.get("term_variants") or []:
        normalized = str(variant.get("normalized_term") or "")
        observed = str(variant.get("observed_form") or "")
        if (
            variant.get("mapping_status") == "mapped"
            and variant.get("variant_type") != "alias"
            and variant.get("mapped_usage_ids")
            and observed
            and observed not in mapped_variants_by_term[normalized]
        ):
            mapped_variants_by_term[normalized].append(observed)
    terms: list[dict[str, Any]] = []
    for definition in definitions:
        normalized = str(definition.get("normalized_term") or "")
        term_usages = [
            item
            for item in reviewed_usages
            if str(item.get("normalized_term") or "") == normalized
            and not item.get("is_definition_occurrence")
            and occurrence_by_usage.get(item.get("id"), "defined_term_use")
            == "defined_term_use"
        ]
        term_usages.sort(key=lambda item: _location_key(item["location"]))
        terms.append(
            {
                "id": f"term-{len(terms) + 1}",
                "term": str(definition.get("term") or ""),
                "normalized": normalized,
                "definition": str(definition.get("definition_text") or ""),
                "rationale": semantic_rationale_by_term.get(normalized, ""),
                "aliases": [str(item) for item in definition.get("aliases") or []],
                "variants": sorted(
                    mapped_variants_by_term.get(normalized, []),
                    key=lambda item: (item.casefold(), item),
                ),
                "location": dict(definition["location"]),
                "uses": [
                    {
                        **dict(item["location"]),
                        "rationale": occurrence_rationale_by_usage.get(item["id"], ""),
                    }
                    for item in term_usages
                ],
                "first_order": _location_key(definition["location"]),
            }
        )

    source_order_terms = [
        item["id"] for item in sorted(terms, key=lambda item: item["first_order"])
    ]
    terms.sort(key=lambda item: (item["term"].casefold(), item["term"]))
    category_counts = Counter(item["category"] for item in results)
    return {
        "document": {"name": ledger.source.name or "Untitled agreement"},
        "results": results,
        "result_count": len(results),
        "category_counts": dict(category_counts),
        "terms": terms,
        "source_order_terms": source_order_terms,
        "blocks": [
            {"id": block.id, "order": block.order, "text": block.text}
            for block in sorted(
                ledger.source.blocks, key=lambda item: (item.order, item.id)
            )
        ],
    }


def _render_result_cards(results: list[dict[str, Any]]) -> str:
    if not results:
        return (
            '<div class="empty-state"><h3>No definition issues found</h3>'
            "<p>The completed Definition Check found no items requiring attention. "
            "This is not legal clearance.</p></div>"
        )
    cards = []
    for result in results:
        occurrence_count = len(result["locations"])
        navigator = ""
        if occurrence_count > 1:
            term = html.escape(result["term"], quote=True)
            navigator = (
                '<div class="occurrence-navigator" '
                f'data-occurrence-navigator data-result="{result["id"]}" '
                f'data-occurrence-count="{occurrence_count}" '
                f'role="group" aria-label="Occurrences of {term}">'
                '<output class="occurrence-status" data-occurrence-status '
                f'aria-live="polite" aria-label="Occurrence 1 of {occurrence_count}">1 of {occurrence_count}</output>'
                '<span class="occurrence-controls">'
                '<button type="button" data-occurrence-prev disabled '
                f'aria-label="Previous occurrence of {term}">'
                '<span aria-hidden="true">&#x2039;</span></button>'
                '<button type="button" data-occurrence-next '
                f'aria-label="Next occurrence of {term}">'
                '<span aria-hidden="true">&#x203A;</span></button>'
                "</span></div>"
            )
        evidence = "".join(
            f'<button type="button" class="evidence" data-evidence-link data-result="{result["id"]}" data-evidence-index="{index}"><span>'
            + html.escape(item["label"])
            + "</span><blockquote>"
            + html.escape(item["excerpt"])
            + "</blockquote></button>"
            for index, item in enumerate(result["evidence"])
        )
        reason = result.get("review_reason")
        reason_copy = _REVIEW_REASON_COPY.get(str(reason))
        review_detail = ""
        if reason_copy:
            review_detail = (
                f'<p class="review-reason"><strong>{html.escape(reason_copy[0])}.</strong> '
                f"{html.escape(result.get('rationale') or 'No additional rationale was retained.')}</p>"
                f'<p class="next-check"><strong>Next check:</strong> {html.escape(reason_copy[1])}</p>'
            )
        related_detail = ""
        if len(result.get("related_labels", [])) > 1:
            related_detail = (
                '<p class="related-labels"><strong>Related labels:</strong> '
                + html.escape(", ".join(result["related_labels"]))
                + ". Each label and location remains a separate review question.</p>"
            )
        scope_detail = ""
        if result.get("scope_qualification") == "possible_inherited_definition":
            scope_detail = f'<p class="scope-note"><strong>Possible inherited definition:</strong> {html.escape(str(result.get("scope_target") or "outside document"))} was not checked.</p>'
        cards.append(
            f'<article class="result-card category-{result["category"]}" tabindex="0" '
            f'id="card-{result["id"]}" data-result="{result["id"]}" '
            f'data-category="{result["category"]}"><div class="result-card-meta"><span class="category-label">{html.escape(result["label"])}</span>{navigator}</div>'
            f"<h4>{html.escape(result['term'])}</h4>"
            f"<p>{html.escape(result['explanation'])}</p>{scope_detail}{review_detail}{related_detail}{evidence}</article>"
        )
    return "".join(cards)


def _ordered_issue_categories() -> list[tuple[str, str]]:
    return [
        *((key, label) for key, label, _ in _RULES.values()),
        ("needs-review", "Needs review"),
    ]


def _render_result_groups(view: dict[str, Any]) -> str:
    if not view["results"]:
        return _render_result_cards([])

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in view["results"]:
        grouped[result["category"]].append(result)

    sections = []
    for category, label in _ordered_issue_categories():
        results = grouped.get(category, [])
        if not results:
            continue
        count = len(results)
        count_label = f"{count} issue" if count == 1 else f"{count} issues"
        sections.append(
            f'<details class="result-group category-{category}" data-result-group="{category}">'
            '<summary class="result-group-heading">'
            f'<span class="result-group-title">{html.escape(label)}</span>'
            f'<span class="result-group-count">{count_label}</span></summary>'
            f'<div class="result-group-cards">{_render_result_cards(results)}</div>'
            "</details>"
        )
    return "".join(sections)


def _category_filter_controls(view: dict[str, Any], *, include_all: bool = True) -> str:
    controls = []
    if include_all:
        controls.append(
            f'<button type="button" class="filter-option active" data-filter="all" data-filter-label="All issues · {view["result_count"]}">'
            f"<span>All issues</span><strong>{view['result_count']}</strong></button>"
        )
    for key, label in _ordered_issue_categories():
        count = int(view["category_counts"].get(key, 0))
        controls.append(
            f'<button type="button" class="filter-option category-{key}" data-filter="{key}" '
            f'data-filter-label="{html.escape(label, quote=True)} · {count}">'
            f"<span>{html.escape(label)}</span><strong>{count}</strong></button>"
        )
    return "".join(controls)


def _render_document_category_key(view: dict[str, Any]) -> str:
    controls = _category_filter_controls(view, include_all=False)
    return (
        '<nav class="category-key document-category-key" aria-label="Document marks and checked issue categories">'
        "<p>Document marks and checked categories</p>"
        '<div class="toolbar-legend-items">'
        '<span class="mark-key definition-key">Definition</span>'
        '<span class="mark-key use-key">Defined-term use</span>'
        f'<div class="filter-options" role="group" aria-label="Issue category">{controls}</div>'
        "</div></nav>"
    )


def _render_filters(view: dict[str, Any]) -> str:
    controls = _category_filter_controls(view)
    return (
        '<details class="filter-menu"><summary><span>Filter issues</span>'
        f'<small class="current-filter">All issues · {view["result_count"]}</small></summary>'
        f'<div class="filter-options" role="group" aria-label="Issue category">{controls}</div></details>'
    )


def _document_annotations(view: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    annotations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for term in view["terms"]:
        location = term["location"]
        annotations[location["block_id"]].append(
            {
                "start": location["char_start"],
                "end": location["char_end"],
                "kind": "definition",
                "target": term["id"],
                "type": "Definition",
                "rationale": term.get("rationale", ""),
                "label": f"Definition: {term['term']}",
            }
        )
        for use_location in term["uses"]:
            annotations[use_location["block_id"]].append(
                {
                    "start": use_location["char_start"],
                    "end": use_location["char_end"],
                    "kind": "use",
                    "target": term["id"],
                    "type": "Defined-term use",
                    "rationale": use_location.get("rationale", ""),
                    "label": f"Defined-term use: {term['term']}",
                }
            )
    for result in view["results"]:
        kind = "needs-review" if result["category"] == "needs-review" else "issue"
        for occurrence_index, issue_location in enumerate(result["locations"]):
            annotations[issue_location["block_id"]].append(
                {
                    "start": issue_location["char_start"],
                    "end": issue_location["char_end"],
                    "kind": kind,
                    "target": result["id"],
                    "occurrence": f"{result['id']}:{occurrence_index}",
                    "type": result["label"],
                    "category": result["category"],
                    "rationale": result.get("rationale", ""),
                    "label": f"{result['label']}: {result['term']}",
                }
            )
    return annotations


def _render_block(text: str, annotations: list[dict[str, Any]]) -> str:
    valid = [
        item for item in annotations if 0 <= item["start"] < item["end"] <= len(text)
    ]
    if not valid:
        return html.escape(text)
    boundaries = {0, len(text)}
    for item in valid:
        boundaries.update((item["start"], item["end"]))
    ordered = sorted(boundaries)
    pieces = []
    priority = {"issue": 0, "needs-review": 1, "definition": 2, "use": 3}
    for start, end in zip(ordered, ordered[1:], strict=False):
        fragment = html.escape(text[start:end])
        active = [
            item for item in valid if item["start"] <= start and end <= item["end"]
        ]
        if not active:
            pieces.append(fragment)
            continue
        active.sort(key=lambda item: (priority[item["kind"]], item["target"]))
        selected = active[0]
        targets = " ".join(dict.fromkeys(item["target"] for item in active))
        occurrences = " ".join(
            dict.fromkeys(
                item["occurrence"] for item in active if item.get("occurrence")
            )
        )
        occurrence_attribute = (
            f'data-result-occurrences="{html.escape(occurrences, quote=True)}" '
            if occurrences
            else ""
        )
        rationale = str(selected.get("rationale") or "").strip()
        rationale_attribute = (
            f'data-annotation-rationale="{html.escape(rationale, quote=True)}" '
            if rationale
            else ""
        )
        pieces.append(
            f'<mark class="annotation {selected["kind"]} category-{selected.get("category", selected["kind"])}" role="button" tabindex="0" '
            f'data-targets="{html.escape(targets, quote=True)}" '
            f"{occurrence_attribute}"
            f'data-annotation-type="{html.escape(selected["type"], quote=True)}" '
            f"{rationale_attribute}"
            'aria-describedby="annotation-card" '
            f'aria-label="{html.escape(selected["label"], quote=True)}">{fragment}</mark>'
        )
    return "".join(pieces)


def _render_document(view: dict[str, Any]) -> str:
    annotations = _document_annotations(view)
    return "".join(
        f'<section class="document-block" id="block-{html.escape(block["id"], quote=True)}">'
        f"<p>{_render_block(block['text'], annotations.get(block['id'], []))}</p></section>"
        for block in view["blocks"]
    )


def _usage_blocks(
    term: dict[str, Any], blocks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Project only source blocks containing uses, in document order."""

    counts = Counter(location["block_id"] for location in term["uses"])
    return [
        {"id": block["id"], "order": block["order"], "count": counts[block["id"]]}
        for block in blocks
        if counts[block["id"]]
    ]


def _term_detail_data(
    term: dict[str, Any], blocks: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return the compact allowlisted data needed to render one term on demand."""

    return {
        "id": term["id"],
        "term": term["term"],
        "definition": term["definition"],
        "aliases": term["aliases"],
        "variants": term["variants"],
        "definitionBlockId": term["location"]["block_id"],
        "usageCount": len(term["uses"]),
        "usageBlocks": _usage_blocks(term, blocks),
    }


def _render_panel_terms(view: dict[str, Any]) -> str:
    buttons = "".join(
        f'<button type="button" class="term-row" data-term="{term["id"]}" '
        f'data-name="{html.escape(term["term"].casefold(), quote=True)}">'
        f"<span>{html.escape(term['term'])}</span><small>{len(term['uses'])} use{'s' if len(term['uses']) != 1 else ''}</small></button>"
        for term in view["terms"]
    )
    return (
        '<div class="term-browse" data-term-browse>'
        '<div class="terms-toolbar"><label for="term-search">Find a term</label>'
        '<input id="term-search" type="search" autocomplete="off" placeholder="Search defined terms">'
        '<div class="segmented" aria-label="Term order"><button type="button" class="active" data-term-order="alpha">A–Z</button>'
        '<button type="button" data-term-order="source">Document</button></div></div>'
        '<p class="agent-note">Your authorized agent can use a structured version of these Terms to answer document questions.</p>'
        f'<nav class="term-list" aria-label="Defined terms">{buttons}</nav></div>'
        '<div class="term-detail-panel" data-term-detail-panel aria-live="polite"></div>'
    )


_SCRIPT = r"""
(function () {
  "use strict";
  const model = JSON.parse(document.getElementById("dashboard-data").textContent);
  const termsById = new Map(model.terms.map(function (term) { return [term.id, term]; }));
  const annotationCard = document.getElementById("annotation-card");
  const annotationCardLabel = annotationCard ? annotationCard.querySelector("[data-annotation-card-label]") : null;
  const annotationCardRationale = annotationCard ? annotationCard.querySelector("[data-annotation-card-rationale]") : null;
  let activeAnnotation = null;
  function positionAnnotationCard(mark) {
    if (!annotationCard || annotationCard.hidden || !mark) return;
    const edge = 8;
    const gap = 10;
    const anchor = mark.getBoundingClientRect();
    const card = annotationCard.getBoundingClientRect();
    let left = anchor.left + (anchor.width / 2) - (card.width / 2);
    left = Math.max(edge, Math.min(left, window.innerWidth - card.width - edge));
    let top = anchor.top - card.height - gap;
    let placement = "above";
    if (top < edge) {
      top = anchor.bottom + gap;
      placement = "below";
    }
    top = Math.max(edge, Math.min(top, window.innerHeight - card.height - edge));
    annotationCard.style.left = Math.round(left) + "px";
    annotationCard.style.top = Math.round(top) + "px";
    annotationCard.dataset.placement = placement;
  }
  function showAnnotationCard(mark) {
    if (!annotationCard || !mark) return;
    const annotationType = mark.dataset.annotationType;
    if (!annotationType) return;
    const rationale = String(mark.dataset.annotationRationale || "").trim();
    activeAnnotation = mark;
    if (annotationCardLabel) annotationCardLabel.textContent = annotationType;
    if (annotationCardRationale) {
      annotationCardRationale.textContent = rationale;
      annotationCardRationale.hidden = !rationale;
    }
    annotationCard.classList.toggle("has-rationale", Boolean(rationale));
    annotationCard.hidden = false;
    positionAnnotationCard(mark);
  }
  function hideAnnotationCard(mark) {
    if (!annotationCard || activeAnnotation !== mark) return;
    annotationCard.hidden = true;
    activeAnnotation = null;
  }
  const panelTabs = Array.from(document.querySelectorAll(".panel-tab"));
  const panelViews = Array.from(document.querySelectorAll(".panel-view"));
  function showPanel(name) {
    panelTabs.forEach(function (tab) { const active = tab.dataset.panel === name; tab.setAttribute("aria-selected", String(active)); tab.tabIndex = active ? 0 : -1; });
    panelViews.forEach(function (view) { view.hidden = view.dataset.panel !== name; });
  }
  panelTabs.forEach(function (tab, index) {
    tab.addEventListener("click", function () { showPanel(tab.dataset.panel); });
    tab.addEventListener("keydown", function (event) {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault(); const step = event.key === "ArrowRight" ? 1 : -1;
      const next = panelTabs[(index + step + panelTabs.length) % panelTabs.length]; next.focus(); showPanel(next.dataset.panel);
    });
  });
  function applyIssueFilter(button) {
    const filter = button.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach(function (item) { item.classList.toggle("active", item === button); });
    document.querySelectorAll("[data-result-group]").forEach(function (group) { const matches = filter === "all" || group.dataset.resultGroup === filter; group.hidden = !matches; if (filter !== "all" && matches) group.open = true; });
    document.querySelectorAll(".result-card").forEach(function (card) { card.hidden = filter !== "all" && card.dataset.category !== filter; });
    const label = document.querySelector(".current-filter"); if (label) label.textContent = button.dataset.filterLabel;
    const announcement = document.getElementById("current-category-announcement"); if (announcement) announcement.textContent = "Current category: " + button.dataset.filterLabel;
    const menu = button.closest("details"); if (menu) menu.open = false;
  }
  function clearSelections() { document.querySelectorAll(".selected").forEach(function (item) { item.classList.remove("selected"); }); }
  const occurrenceIndexByResult = new Map();
  function occurrenceMarks(id, index) {
    const token = id + ":" + String(index);
    return Array.from(document.querySelectorAll('.annotation[data-result-occurrences~="' + token + '"]'));
  }
  function updateOccurrenceNavigator(card, index) {
    const navigator = card ? card.querySelector("[data-occurrence-navigator]") : null;
    if (!navigator) return;
    const count = Number(navigator.dataset.occurrenceCount || 0);
    const safeIndex = Math.max(0, Math.min(index, count - 1));
    const status = navigator.querySelector("[data-occurrence-status]");
    const previous = navigator.querySelector("[data-occurrence-prev]");
    const next = navigator.querySelector("[data-occurrence-next]");
    if (status) { status.textContent = String(safeIndex + 1) + " of " + String(count); status.setAttribute("aria-label", "Occurrence " + String(safeIndex + 1) + " of " + String(count)); }
    if (previous) previous.disabled = safeIndex === 0;
    if (next) next.disabled = safeIndex === count - 1;
  }
  function appendTextElement(parent, tag, text, className) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = text;
    parent.appendChild(element);
    return element;
  }
  function appendTermMetadata(article, label, values) {
    if (!values.length) return;
    const paragraph = document.createElement("p");
    appendTextElement(paragraph, "strong", label + ": ");
    paragraph.appendChild(document.createTextNode(values.join(", ")));
    article.appendChild(paragraph);
  }
  function usageLevel(count) {
    if (count === 1) return 1;
    if (count === 2) return 2;
    if (count <= 4) return 3;
    return 4;
  }
  function renderUsageMap(article, term) {
    if (!term.usageCount) {
      appendTextElement(article, "p", "No operative uses were found.");
      return;
    }
    const section = document.createElement("section");
    section.className = "usage-map";
    section.setAttribute("aria-label", "Term uses by document paragraph");
    const heading = document.createElement("div");
    heading.className = "usage-map-heading";
    appendTextElement(heading, "h3", "Uses in this agreement");
    section.appendChild(heading);
    appendTextElement(
      section,
      "p",
      "Each square represents a paragraph. Select a blue square to jump to its source.",
    );
    const grid = document.createElement("div");
    grid.className = "usage-grid";
    const usageByBlock = new Map(
      term.usageBlocks.map(function (block) { return [block.id, block]; }),
    );
    model.documentBlocks.forEach(function (blockId) {
      const block = usageByBlock.get(blockId);
      if (!block) {
        const empty = document.createElement("i");
        empty.className = "usage-cell level-0";
        empty.setAttribute("aria-hidden", "true");
        grid.appendChild(empty);
        return;
      }
      const count = Number(block.count);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "usage-cell level-" + String(usageLevel(count));
      button.dataset.gotoBlock = block.id;
      button.setAttribute("aria-label", "View paragraph with use in document");
      button.title = "View paragraph with use in document";
      grid.appendChild(button);
    });
    section.appendChild(grid);
    const legend = document.createElement("div");
    legend.className = "usage-legend";
    appendTextElement(legend, "span", "Fewer");
    [1, 2, 3, 4].forEach(function (level) {
      const marker = document.createElement("i");
      marker.className = "usage-cell level-" + String(level);
      legend.appendChild(marker);
    });
    appendTextElement(legend, "span", "More");
    section.appendChild(legend);
    article.appendChild(section);
  }
  function renderTermDetail(id) {
    const panel = document.querySelector("[data-term-detail-panel]");
    const term = termsById.get(id);
    if (!panel || !term) return;
    panel.replaceChildren();
    const article = document.createElement("article");
    article.className = "term-detail";
    article.id = "detail-" + term.id;
    article.dataset.termDetail = term.id;
    const back = appendTextElement(article, "button", "← All terms", "back-to-terms");
    back.type = "button";
    back.dataset.backToTerms = "";
    appendTextElement(article, "p", "Definition", "eyebrow");
    appendTextElement(article, "h2", term.term);
    appendTextElement(article, "blockquote", term.definition);
    appendTermMetadata(article, "Also used as", term.aliases);
    appendTermMetadata(article, "Mapped variants", term.variants);
    const definitionLinkRow = document.createElement("p");
    const definitionLink = appendTextElement(definitionLinkRow, "button", "View definition in document", "text-link");
    definitionLink.type = "button";
    definitionLink.dataset.gotoBlock = term.definitionBlockId;
    article.appendChild(definitionLinkRow);
    renderUsageMap(article, term);
    panel.appendChild(article);
  }
  function showTermBrowse() {
    const panel = document.querySelector("[data-term-detail-panel]");
    if (panel) panel.replaceChildren();
    const browse = document.querySelector("[data-term-browse]");
    if (browse) browse.hidden = false;
    const search = document.getElementById("term-search");
    if (search) search.focus();
  }
  function selectResult(id, scrollDocument, occurrenceIndex) {
    showPanel("issues");
    clearSelections();
    const card = document.getElementById("card-" + id);
    const group = card ? card.closest("[data-result-group]") : null;
    if (group && group.hidden) { const allIssues = document.querySelector('[data-filter="all"]'); if (allIssues) applyIssueFilter(allIssues); }
    if (group) group.open = true;
    document.querySelectorAll('[data-result="' + id + '"]').forEach(function (item) { item.classList.add("selected"); });
    const navigator = card ? card.querySelector("[data-occurrence-navigator]") : null;
    const count = navigator ? Number(navigator.dataset.occurrenceCount || 0) : 1;
    const requestedIndex = Number.isInteger(occurrenceIndex) ? occurrenceIndex : 0;
    const safeIndex = Math.max(0, Math.min(requestedIndex, count - 1));
    occurrenceIndexByResult.set(id, safeIndex);
    let marks = occurrenceMarks(id, safeIndex);
    if (!marks.length) marks = Array.from(document.querySelectorAll('.annotation[data-targets~="' + id + '"]'));
    marks.forEach(function (item) { item.classList.add("selected"); });
    updateOccurrenceNavigator(card, safeIndex);
    if (card) card.scrollIntoView({block:"start"});
    if (scrollDocument && marks.length) marks[0].scrollIntoView({block:"center"});
  }
  document.querySelectorAll(".result-card").forEach(function (card) {
    function activate(event) { if (event && event.target.closest("button")) return; selectResult(card.dataset.result, false, 0); }
    card.addEventListener("click", activate); card.addEventListener("keydown", function (event) { if (event.target !== card) return; if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(event); } });
  });
  document.querySelectorAll("[data-evidence-link]").forEach(function (button) {
    button.addEventListener("click", function (event) { event.preventDefault(); event.stopPropagation(); selectResult(button.dataset.result, true, Number(button.dataset.evidenceIndex)); });
  });
  document.querySelectorAll("[data-occurrence-navigator]").forEach(function (navigator) {
    const id = navigator.dataset.result;
    const previous = navigator.querySelector("[data-occurrence-prev]");
    const next = navigator.querySelector("[data-occurrence-next]");
    function move(step, event) {
      event.preventDefault();
      event.stopPropagation();
      const current = occurrenceIndexByResult.has(id) ? occurrenceIndexByResult.get(id) : 0;
      selectResult(id, true, current + step);
    }
    if (previous) previous.addEventListener("click", function (event) { move(-1, event); });
    if (next) next.addEventListener("click", function (event) { move(1, event); });
  });
  function selectTerm(id, selectedMark) {
    showPanel("terms");
    clearSelections();
    document.querySelectorAll(".term-row").forEach(function (item) { item.classList.toggle("selected", item.dataset.term === id); });
    if (selectedMark) selectedMark.classList.add("selected");
    renderTermDetail(id);
    const browse = document.querySelector("[data-term-browse]"); if (browse) browse.hidden = true;
  }
  document.querySelectorAll(".term-row").forEach(function (row) { row.addEventListener("click", function () { selectTerm(row.dataset.term); }); });
  document.querySelectorAll("mark.annotation").forEach(function (mark) {
    function activate() { const ids = String(mark.dataset.targets || "").split(" "); const result = ids.find(function (id) { return id.indexOf("result-") === 0; }); if (result) { const token = String(mark.dataset.resultOccurrences || "").split(" ").find(function (item) { return item.indexOf(result + ":") === 0; }); const index = token ? Number(token.slice(token.lastIndexOf(":") + 1)) : 0; selectResult(result, false, index); return; } const term = ids.find(function (id) { return id.indexOf("term-") === 0; }); if (term) selectTerm(term, mark); }
    mark.addEventListener("click", activate); mark.addEventListener("keydown", function (event) { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(); } });
    mark.addEventListener("mouseenter", function () { showAnnotationCard(mark); });
    mark.addEventListener("mouseleave", function () { if (document.activeElement !== mark) hideAnnotationCard(mark); });
    mark.addEventListener("focus", function () { showAnnotationCard(mark); });
    mark.addEventListener("blur", function () { hideAnnotationCard(mark); });
    mark.addEventListener("keydown", function (event) { if (event.key === "Escape") hideAnnotationCard(mark); });
  });
  window.addEventListener("resize", function () { if (activeAnnotation) positionAnnotationCard(activeAnnotation); });
  window.addEventListener("scroll", function () { if (activeAnnotation) positionAnnotationCard(activeAnnotation); }, true);
  document.querySelectorAll("[data-filter]").forEach(function (button) {
    button.addEventListener("click", function () { applyIssueFilter(button); });
  });
  document.addEventListener("click", function (event) {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const back = target.closest("[data-back-to-terms]");
    if (back) { showTermBrowse(); return; }
    const button = target.closest("[data-goto-block]");
    if (!button) return;
    const block = document.getElementById("block-" + button.dataset.gotoBlock);
    if (block) block.scrollIntoView({block:"center"});
  });
  const search = document.getElementById("term-search");
  if (search) search.addEventListener("input", function () { const query = search.value.trim().toLocaleLowerCase(); document.querySelectorAll(".term-row").forEach(function (row) { row.hidden = query && row.dataset.name.indexOf(query) === -1; }); });
  function orderTerms(order) { const list = document.querySelector(".term-list"); if (!list) return; const ids = order === "source" ? model.sourceOrderTerms : model.alphaTerms; ids.forEach(function (id) { const row = list.querySelector('[data-term="' + id + '"]'); if (row) list.appendChild(row); }); document.querySelectorAll("[data-term-order]").forEach(function (button) { button.classList.toggle("active", button.dataset.termOrder === order); }); }
  document.querySelectorAll("[data-term-order]").forEach(function (button) { button.addEventListener("click", function () { orderTerms(button.dataset.termOrder); }); });

  const searchInput = document.getElementById("document-search");
  const searchPrev = document.querySelector("[data-search-prev]");
  const searchNext = document.querySelector("[data-search-next]");
  const searchStatus = document.querySelector("[data-search-status]");
  const paragraphEntries = Array.from(document.querySelectorAll(".document-block p")).map(function (paragraph) {
    const segments = [];
    let text = "";
    const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const value = node.nodeValue || "";
      if (!value) continue;
      segments.push({ node: node, start: text.length, end: text.length + value.length });
      text += value;
    }
    return {
      paragraph: paragraph,
      block: paragraph.closest(".document-block"),
      segments: segments,
      text: text,
      lower: text.toLocaleLowerCase(),
    };
  });
  const searchSupportsHighlights = Boolean(window.CSS && CSS.highlights && window.Highlight);
  const searchState = {
    query: "",
    matches: [],
    currentIndex: -1,
  };
  function clearSearchMarks() {
    paragraphEntries.forEach(function (entry) {
      entry.paragraph.classList.remove("search-hit", "search-current");
    });
    if (searchSupportsHighlights) {
      CSS.highlights.delete("definition-check-search");
      CSS.highlights.delete("definition-check-search-current");
    }
  }
  function setSearchStatus(text) {
    if (searchStatus) searchStatus.textContent = text;
  }
  function buildRange(entry, start, end) {
    let startSegment = null;
    let endSegment = null;
    for (let index = 0; index < entry.segments.length; index += 1) {
      const segment = entry.segments[index];
      if (!startSegment && segment.start <= start && start < segment.end) {
        startSegment = segment;
      }
      if (segment.start < end && end <= segment.end) {
        endSegment = segment;
        break;
      }
    }
    if (!startSegment || !endSegment) return null;
    const range = document.createRange();
    range.setStart(startSegment.node, start - startSegment.start);
    range.setEnd(endSegment.node, end - endSegment.start);
    return range;
  }
  function renderSearchHighlights() {
    clearSearchMarks();
    if (!searchState.query || !searchState.matches.length) {
      return;
    }
    if (searchSupportsHighlights) {
      const all = new Highlight();
      const current = new Highlight();
      searchState.matches.forEach(function (match, index) {
        all.add(match.range);
        if (index === searchState.currentIndex) current.add(match.range);
      });
      CSS.highlights.set("definition-check-search", all);
      CSS.highlights.set("definition-check-search-current", current);
      return;
    }
    searchState.matches.forEach(function (match, index) {
      match.entry.paragraph.classList.add("search-hit");
      if (index === searchState.currentIndex) match.entry.paragraph.classList.add("search-current");
    });
  }
  function updateSearchStatus() {
    if (!searchState.query || !searchState.matches.length) {
      setSearchStatus("0/0");
      return;
    }
    setSearchStatus(String(searchState.currentIndex + 1) + "/" + searchState.matches.length);
  }
  function jumpToSearchMatch(index) {
    if (!searchState.matches.length) return;
    const length = searchState.matches.length;
    searchState.currentIndex = ((index % length) + length) % length;
    renderSearchHighlights();
    updateSearchStatus();
    const match = searchState.matches[searchState.currentIndex];
    if (match && match.entry.block) {
      match.entry.block.scrollIntoView({ block: "center" });
    }
  }
  function runSearch(query) {
    const normalized = query.trim().toLocaleLowerCase();
    searchState.query = normalized;
    searchState.matches = [];
    searchState.currentIndex = -1;
    if (searchPrev) searchPrev.disabled = true;
    if (searchNext) searchNext.disabled = true;
    clearSearchMarks();
    if (!normalized) {
      updateSearchStatus();
      return;
    }
    paragraphEntries.forEach(function (entry) {
      let offset = 0;
      while (offset <= entry.lower.length) {
        const found = entry.lower.indexOf(normalized, offset);
        if (found === -1) break;
        const range = buildRange(entry, found, found + normalized.length);
        if (range) {
          searchState.matches.push({ entry: entry, range: range });
        }
        offset = found + Math.max(1, normalized.length);
      }
    });
    if (searchState.matches.length) {
      searchState.currentIndex = 0;
      renderSearchHighlights();
      const match = searchState.matches[0];
      if (match && match.entry.block) {
        match.entry.block.scrollIntoView({ block: "center" });
      }
    }
    if (searchPrev) searchPrev.disabled = !searchState.matches.length;
    if (searchNext) searchNext.disabled = !searchState.matches.length;
    updateSearchStatus();
  }
  if (searchInput) {
    searchInput.addEventListener("input", function () {
      runSearch(searchInput.value);
    });
    searchInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        jumpToSearchMatch(event.shiftKey ? searchState.currentIndex - 1 : searchState.currentIndex + 1);
      } else if (event.key === "Escape") {
        event.preventDefault();
        searchInput.value = "";
        runSearch("");
      }
    });
  }
  if (searchPrev) {
    searchPrev.addEventListener("click", function () {
      jumpToSearchMatch(searchState.currentIndex - 1);
    });
  }
  if (searchNext) {
    searchNext.addEventListener("click", function () {
      jumpToSearchMatch(searchState.currentIndex + 1);
    });
  }
  runSearch("");
})();
""".strip()


def render_dashboard(ledger: Ledger) -> str:
    view = build_dashboard_view(ledger)
    source_name = html.escape(view["document"]["name"])
    data = {
        "alphaTerms": [item["id"] for item in view["terms"]],
        "documentBlocks": [block["id"] for block in view["blocks"]],
        "sourceOrderTerms": view["source_order_terms"],
        "terms": [_term_detail_data(item, view["blocks"]) for item in view["terms"]],
    }
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Definition Check — {source_name}</title><style>{DASHBOARD_STYLE}</style></head><body>"
        '<a class="skip-link" href="#results-panel">Skip to issues</a>'
        f'<header class="app-header"><div class="identity"><h1>{source_name}</h1>'
        '<div class="document-search" role="search" aria-label="Search agreement text">'
        '<label class="sr-only" for="document-search">Search agreement text</label>'
        '<input id="document-search" type="search" autocomplete="off" placeholder="Search agreement text">'
        '<div class="search-navigation" aria-label="Search result navigation">'
        '<button type="button" data-search-prev disabled aria-label="Previous search match"><span aria-hidden="true">&#x2039;</span></button>'
        '<output class="search-status" data-search-status aria-live="polite">0/0</output>'
        '<button type="button" data-search-next disabled aria-label="Next search match"><span aria-hidden="true">&#x203A;</span></button>'
        "</div></div></div></header>"
        '<main id="main-content"><section class="view" id="view-document"><div class="document-layout">'
        '<div class="document-shell"><div class="document-toolbar">'
        f"{_render_document_category_key(view)}</div>"
        f'<article class="document" aria-label="Extracted agreement text">{_render_document(view)}</article></div>'
        f'<aside class="results-panel" id="results-panel" aria-label="Issues and terms" tabindex="-1">'
        '<div class="panel-tabs" role="tablist" aria-label="Document information">'
        f'<button class="panel-tab" id="panel-tab-issues" role="tab" aria-controls="panel-issues" aria-selected="true" data-panel="issues">Issues <span>{view["result_count"]}</span></button>'
        f'<button class="panel-tab" id="panel-tab-terms" role="tab" aria-controls="panel-terms" aria-selected="false" tabindex="-1" data-panel="terms">Terms <span>{len(view["terms"])}</span></button></div>'
        f'<section class="panel-view" id="panel-issues" role="tabpanel" aria-labelledby="panel-tab-issues" data-panel="issues"><div class="panel-meta"><div class="panel-heading"><h2>Issues</h2><p>{view["result_count"]} grouped by type</p></div>{_render_filters(view)}</div><output class="sr-only" id="current-category-announcement" aria-live="polite">Current category: All issues</output><div class="result-list">{_render_result_groups(view)}</div></section>'
        f'<section class="panel-view" id="panel-terms" role="tabpanel" aria-labelledby="panel-tab-terms" data-panel="terms" hidden>{_render_panel_terms(view)}</section></aside></div></section></main>'
        '<aside class="annotation-card" id="annotation-card" role="tooltip" hidden>'
        '<p class="annotation-card-label" data-annotation-card-label></p>'
        '<p class="annotation-card-rationale" data-annotation-card-rationale hidden></p></aside>'
        '<script type="application/json" id="dashboard-data">'
        + _json_for_script(data)
        + f"</script><script>{_SCRIPT}</script></body></html>\n"
    )


def write_dashboard(ledger: Ledger, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(render_dashboard(ledger))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
