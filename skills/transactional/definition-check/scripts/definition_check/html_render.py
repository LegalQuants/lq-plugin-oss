"""Self-contained, deterministic HTML glossary rendering for a ledger."""

from __future__ import annotations

import html
import json
import os
import tempfile
from pathlib import Path

from .extract import QUOTED_LABEL_EXCLUSIONS, QUOTED_LABEL_FORMATS
from .models import Ledger
from .projection import project_reviewed_inventory


def _json_int(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


_STYLE = """
:root { color-scheme: light; font: 16px system-ui, sans-serif; line-height: 1.45; }
body { margin: 0; color: #17202a; background: #f5f7fa; }
header, main { max-width: 1200px; margin: auto; padding: 1rem; }
header { background: #fff; border-bottom: 1px solid #d9e0e7; }
.controls { display: flex; flex-wrap: wrap; gap: .75rem; align-items: end; }
label { display: grid; gap: .25rem; font-weight: 650; }
input, select { min-height: 2.25rem; padding: .35rem .5rem; border: 1px solid #8b98a5; border-radius: .25rem; font: inherit; }
.layout { display: grid; grid-template-columns: minmax(17rem, 1fr) minmax(20rem, 2fr); gap: 1rem; }
section, article, details { background: #fff; border: 1px solid #d9e0e7; border-radius: .35rem; padding: 1rem; }
.term-list { display: grid; gap: .5rem; align-content: start; }
.term-button { display: block; width: 100%; text-align: left; padding: .7rem; border: 1px solid #c6d0da; border-radius: .25rem; background: #fff; cursor: pointer; font: inherit; }
.term-button:hover, .term-button:focus { border-color: #1769aa; outline: 3px solid #b9ddf7; }
.term-button[aria-selected="true"] { border-color: #1769aa; background: #eef7ff; }
.muted { color: #536271; }
dt { font-weight: 700; } dd { margin: 0 0 .75rem; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f5f7fa; padding: .75rem; border-radius: .25rem; }
.finding { border-left: .3rem solid #d97706; padding-left: .6rem; margin: .5rem 0; }
.candidate-note { background: #fff8e8; border: 1px solid #e6c979; border-radius: .3rem; padding: .75rem; margin: .75rem 0; }
.source-context { background: #f7f9fb; border: 1px solid #d9e0e7; border-radius: .3rem; margin: .65rem 0 0; padding: .7rem; }
.source-context p { margin: .35rem 0 0; white-space: pre-wrap; }
.context-meta { color: #536271; font-size: .875rem; }
mark { background: #ffe08a; color: inherit; padding: 0 .08rem; }
@media (max-width: 760px) { .layout { grid-template-columns: 1fr; } }
""".strip()

_SCRIPT = r"""
(function () {
  "use strict";
  const data = JSON.parse(document.getElementById("ledger-data").textContent);
  const list = document.getElementById("term-list");
  const detail = document.getElementById("term-detail");
  const search = document.getElementById("term-search");
  const status = document.getElementById("term-status");
  const byTerm = new Map();
  const findingContexts = new Map((data.finding_contexts || []).map(function (item) { return [item.finding_id, item.contexts]; }));
  const row = function (normalized, label) { if (!byTerm.has(normalized)) byTerm.set(normalized, { key: normalized, label: label || normalized, definition: null, variants: [], usages: [], findings: [], proposal: null, candidate: null, adjudication: null }); const item = byTerm.get(normalized); if (label && item.label === normalized) item.label = label; return item; };
  (data.definitions || []).forEach(function (item) { const r = row(item.normalized_term, item.term); r.definition = item; });
  (data.term_variants || []).forEach(function (item) { row(item.normalized_term, item.term).variants.push(item); });
  (data.usages || []).forEach(function (item) { row(item.normalized_term, item.term || item.observed_form).usages.push(item); });
  const findingViews = new Map((data.finding_term_views || []).map(function (item) { return [item.finding_id, item]; }));
  (data.findings || []).forEach(function (item) { if (item.normalized_term) { const view = findingViews.get(item.id); const r = row(item.normalized_term, view && view.term); r.findings.push(item); if (view) view.occurrences.forEach(function (usage) { if (!r.usages.some(function (old) { return old.location.block_id === usage.location.block_id && old.location.char_start === usage.location.char_start && old.location.char_end === usage.location.char_end; })) r.usages.push(usage); }); } });
  const latest = new Map();
  (data.candidate_proposals || []).forEach(function (item) { const key = item.candidate_id || item.normalized_term || item.term; const old = latest.get(key); if (!old || (item.revision || 0) > (old.revision || 0)) latest.set(key, item); });
  latest.forEach(function (item) { const r = row(item.normalized_term, item.term); r.proposal = item; });
  const adjudications = new Map((data.semantic_adjudications || []).map(function (item) { return [item.review_id, item]; }));
  (data.term_candidates || []).forEach(function (item) { const r = row(item.normalized_term, item.term); r.candidate = item; r.adjudication = adjudications.get(item.review_id) || null; });
  const semanticComplete = data.semantic_review && data.semantic_review.status === "complete";
  const occurrenceComplete = data.occurrence_review && data.occurrence_review.status === "complete";
  const occurrenceDecisions = new Map((data.occurrence_adjudications || []).map(function (item) { return [item.usage_id, item]; }));
  const occurrenceContexts = new Map((data.occurrence_contexts || []).map(function (item) { return [item.usage_id, item.context]; }));
  const projectedUsageIds = new Set(data.projected_usage_ids || []);
  const projectedFindings = new Map((data.projected_findings || []).map(function (item) { return [item.id, item]; }));
  const definitionContexts = new Map((data.definition_contexts || []).map(function (item) { return [item.definition_id, item.contexts]; }));
  const semanticEvidenceContexts = new Map((data.semantic_evidence_contexts || []).map(function (item) { return [item.review_id, item.contexts]; }));
  const locKey = function (loc) { return [loc.block_id, loc.char_start, loc.char_end].join(":"); };
  const decisionByLocation = new Map();
  (data.usages || []).forEach(function (usage) { const decision = occurrenceDecisions.get(usage.id); if (decision) decisionByLocation.set(locKey(usage.location), decision); });
  const activeUsages = function (item) { if (!occurrenceComplete) return item.usages; return item.usages.filter(function (usage) { return projectedUsageIds.has(usage.id); }); };
  const rejectedCollisions = function (item) { return item.usages.filter(function (usage) { const decision = occurrenceDecisions.get(usage.id); return decision && ["ordinary_language", "proper_name_component", "shadowed_by_overlapping_term"].includes(decision.decision); }); };
  const activeFindings = function (item) { if (!occurrenceComplete) return item.findings; return item.findings.map(function (finding) { return projectedFindings.get(finding.id); }).filter(Boolean); };
  status.options[0].textContent = semanticComplete ? "Confirmed defined" : "Unreviewed definition candidates";
  const terms = Array.from(byTerm.values()).filter(function (item) { return !(item.adjudication && item.adjudication.decision === "confirmed_alias"); }).sort(function (a, b) { return a.label.localeCompare(b.label); });
  const esc = function (value) { const node = document.createElement("span"); node.textContent = value == null ? "" : String(value); return node.innerHTML; };
  const location = function (item) { const loc = item.location || item; return esc((loc.part || "") + " / " + (loc.block_id || "") + " (" + (loc.char_start || 0) + "-" + (loc.char_end || 0) + ")"); };
  const sourceContext = function (context) {
    const text = context.text || ""; const start = context.match_start || 0; const end = context.match_end || start;
    const marked = esc(text.slice(0, start)) + "<mark>" + esc(text.slice(start, end)) + "</mark>" + esc(text.slice(end));
    const truncation = context.truncated ? " · bounded excerpt" : "";
    return "<div class=source-context><div class=context-meta>" + esc(context.label) + truncation + " · " + location(context.location) + "</div><p>" + marked + "</p></div>";
  };
  const findingCard = function (finding) {
    const evidenceLocations = new Set((finding.evidence || []).map(locKey));
    const contexts = (findingContexts.get(finding.id) || []).filter(function (context) { return evidenceLocations.has(locKey(context.location)); });
    return "<div class=finding><strong>" + esc(finding.rule_id) + "</strong> — " + esc(finding.message) + (contexts.length ? "<h4>Source paragraph" + (contexts.length === 1 ? "" : "s") + "</h4>" + contexts.map(sourceContext).join("") : "<p class=muted>No source paragraph available.</p>") + "</div>";
  };
  const statuses = function (item) {
    const reviewedFindings = activeFindings(item); const reviewedUsages = activeUsages(item);
    const rules = reviewedFindings.map(function (f) { return String(f.rule_id || "").toUpperCase(); }).join(" ");
    const states = reviewedFindings.map(function (f) { return String(f.review_state || "").toLowerCase(); });
    const proposalState = item.proposal && String(item.proposal.state || "").toLowerCase();
    const decision = item.adjudication && item.adjudication.decision;
    return { defined: semanticComplete ? decision === "confirmed_defined" : !!item.definition, undefined: semanticComplete ? decision === "confirmed_undefined" : !item.definition, rejected: ["rejected_not_a_term", "rejected_proper_name"].includes(decision), unreviewed: !decision, unused: !!item.definition && !reviewedUsages.some(function (usage) { return !usage.is_definition_occurrence; }), duplicated: /DUPLIC|DEF-003/.test(rules), inconsistent: /INCONSIST|DEF-004/.test(rules), unresolved: /UNRESOLVED|REFERENCE|DEF-006/.test(rules), needs_review: decision === "needs_review" || decision === "insufficient_evidence" || states.indexOf("needs_review") >= 0 || states.indexOf("insufficient_evidence") >= 0 || proposalState === "needs_context" || proposalState === "abstain" };
  };
  function renderDetail(item) {
    if (!item) { detail.innerHTML = "<p class=muted>Select a term.</p>"; return; }
    const d = item.definition; const p = item.proposal; const flags = statuses(item);
    const reviewedUsages = activeUsages(item); const external = reviewedUsages.filter(function (usage) { return !usage.is_definition_occurrence; }); const reviewedFindings = activeFindings(item); const collisions = rejectedCollisions(item);
    let out = "<h2 id=term-heading>" + esc(item.label) + "</h2>";
    const decisionLabel = item.adjudication ? item.adjudication.decision.replaceAll("_", " ") : (d ? "unreviewed definition candidate" : "unreviewed potential term");
    out += "<p class=muted>" + esc(decisionLabel) + "</p>";
    if (!semanticComplete) out += "<div class=candidate-note><strong>Pre-semantic result, not a conclusion.</strong> Every extracted term is queued for neutral semantic review; raw matches may include names, headings, signature metadata, and ordinary phrases.</div>";
    if (semanticComplete && !occurrenceComplete) out += "<div class=candidate-note><strong>Occurrence review not run.</strong> Case and number variants remain raw lexical matches and do not yet establish use of this defined term.</div>";
    if (item.adjudication) out += "<div class=candidate-note><strong>Semantic decision:</strong> " + esc(decisionLabel) + (item.adjudication.rationale_summary ? " — " + esc(item.adjudication.rationale_summary) : "") + "</div>";
    const structuralHints = item.candidate && (item.candidate.structural_hints || []);
    if (structuralHints.length) out += "<div class=candidate-note><strong>Structural hint:</strong> " + structuralHints.map(function (hint) { return esc(hint.replaceAll("_", " ")); }).join(", ") + ". Heuristic only; this candidate was not suppressed and semantic review decides its status.</div>";
    const semanticOnlyDefinition = semanticComplete && flags.defined && !d && !(p && p.definition_text);
    const definitionDisplay = d ? d.definition_text : (p && p.definition_text) || (semanticOnlyDefinition ? "Confirmed from cited source context; no structured definition text was extracted." : "No definition record");
    const semanticLocation = item.adjudication && item.adjudication.evidence && item.adjudication.evidence[0];
    out += "<dl><dt>" + (flags.rejected ? "Raw extracted definition" : "Definition") + "</dt><dd>" + esc(definitionDisplay) + "</dd>";
    out += "<dt>Aliases</dt><dd>" + esc(d ? (d.aliases || []).join(", ") || "None recorded" : "Not available") + "</dd>";
    out += "<dt>Mapped variants</dt><dd>" + (item.variants.length ? item.variants.map(function (variant) { return "<strong>" + esc(variant.observed_form) + "</strong> (" + esc(variant.variant_type.replaceAll("_", " ")) + ", " + esc(variant.mapping_status) + "; " + variant.mapped_usage_ids.length + " mapped, " + variant.rejected_usage_ids.length + " rejected, " + variant.unresolved_usage_ids.length + " unresolved)"; }).join("<br>") : "None recorded") + "</dd>";
    out += "<dt>Definition location</dt><dd>" + (d ? location(d) : semanticLocation ? location(semanticLocation) + " (semantic citation)" : "Not recorded") + "</dd>";
    out += "<dt>Indexed occurrences in document</dt><dd>" + reviewedUsages.length + "</dd>";
    out += "<dt>Uses outside definition</dt><dd>" + external.length + "</dd>";
    if (semanticOnlyDefinition) out += "<dt>Inventory note</dt><dd>Semantic review confirmed this label from source context, but the deterministic definition/usage index did not create a structured record for it. Occurrence counts may therefore be incomplete.</dd>";
    out += "<dt>Normalized matching key</dt><dd><code>" + esc(item.key) + "</code><br><span class=muted>Case-folded key used for matching; not the document spelling.</span></dd></dl>";
    if (reviewedFindings.length) { const findingTitle = flags.rejected ? "Raw deterministic observations (rejected)" : occurrenceComplete ? "Findings" : "Raw deterministic observations (occurrence review not run)"; out += "<h3>" + findingTitle + "</h3>" + reviewedFindings.map(findingCard).join(""); }
    if (collisions.length) { out += "<h3>Rejected lexical collisions</h3>" + collisions.map(function (usage) { const decision = occurrenceDecisions.get(usage.id); const context = occurrenceContexts.get(usage.id); return "<div class=source-context><strong>" + esc(usage.observed_form) + " — ordinary language</strong><p>" + esc(decision.rationale_summary) + "</p>" + (context ? sourceContext(context) : "") + "</div>"; }).join(""); }
    if (p) { out += "<h3>Candidate review</h3><p>" + esc(p.state) + (data.include_internal_traces && p.rationale_summary ? " — " + esc(p.rationale_summary) : "") + "</p>"; }
    out += "<details><summary>Reviewed document occurrences</summary>" + (reviewedUsages.map(function (usage) { return "<strong>" + esc(usage.observed_form || item.label) + "</strong> — " + location(usage); }).join("<br>") || "None recorded") + "</details>";
    const evidence = (data.evidence || []).filter(function (e) { return item.findings.some(function (f) { return (f.evidence || []).some(function (loc) { return loc.block_id === e.location.block_id && loc.char_start === e.location.char_start; }); }); });
    if (data.include_internal_traces && p) { (p.evidence_for || []).concat(p.evidence_against || []).forEach(function (id) { const found = (data.evidence || []).find(function (e) { return e.id === id; }); if (found && evidence.indexOf(found) < 0) evidence.push(found); }); }
    const citedContexts = []; const citedLocations = new Set();
    const addContexts = function (contexts) { (contexts || []).forEach(function (context) { const key = locKey(context.location); if (!citedLocations.has(key)) { citedLocations.add(key); citedContexts.push(context); } }); };
    if (d) addContexts(definitionContexts.get(d.id));
    if (item.adjudication) addContexts(semanticEvidenceContexts.get(item.adjudication.review_id));
    let evidenceHtml = "";
    if (citedContexts.length) { const evidenceHeading = item.adjudication ? "Definition and semantic-review evidence" : "Definition source"; evidenceHtml += "<p><strong>" + evidenceHeading + "</strong>" + (item.adjudication && item.adjudication.rationale_summary ? " — " + esc(item.adjudication.rationale_summary) : "") + "</p>" + citedContexts.map(sourceContext).join(""); }
    evidenceHtml += evidence.map(function (e) { return "<p><strong>" + esc(e.stance) + "</strong> — " + esc(e.method) + "<br>" + esc(e.excerpt) + "<br><span class=muted>" + location(e) + "</span></p>"; }).join("");
    out += "<details><summary>Evidence</summary>" + (evidenceHtml || "None recorded") + "</details>";
    const traceIds = p ? [p.id, p.candidate_id] : []; const traces = (data.review_traces || []).filter(function (t) { return traceIds.concat(d ? [d.id, d.normalized_term] : [item.key]).indexOf(t.subject_id) >= 0; });
    if (data.include_internal_traces && traces.length) { out += "<details><summary>Authorized trace summaries</summary>" + traces.map(function (t) { return "<p>" + esc(t.agent_role) + ": " + esc(t.rationale_summary) + "</p>"; }).join("") + "</details>"; }
    detail.innerHTML = out;
  }
  function render() {
    const query = search.value.toLocaleLowerCase(); const filter = status.value;
    const visible = terms.filter(function (item) { const d = item.definition; const text = (item.label + " " + (d && (d.aliases || []).join(" ") || "") + " " + item.variants.map(function (variant) { return variant.observed_form; }).join(" ")).toLocaleLowerCase(); const matches = !query || text.indexOf(query) >= 0; return matches && (filter === "all" || statuses(item)[filter]); });
    list.innerHTML = visible.map(function (item) { const label = item.adjudication ? item.adjudication.decision.replaceAll("_", " ") : (item.definition ? "Unreviewed extracted definition" : "Unreviewed potential term"); const reviewedUsages = activeUsages(item); const reviewedFindings = activeFindings(item); return "<button type=button class=term-button role=option aria-selected=false data-term-id=\"" + esc(item.key) + "\"><strong>" + esc(item.label) + "</strong><br><span class=muted>" + esc(label) + " · " + reviewedUsages.length + " indexed occurrence(s)" + (reviewedFindings.length ? " · " + reviewedFindings.length + " finding(s)" : "") + "</span></button>"; }).join("") || "<p class=muted>No matching terms.</p>";
    list.querySelectorAll(".term-button").forEach(function (button) { button.addEventListener("click", function () { list.querySelectorAll(".term-button").forEach(function (b) { b.setAttribute("aria-selected", "false"); }); button.setAttribute("aria-selected", "true"); renderDetail(terms.find(function (item) { return item.key === button.dataset.termId; })); }); });
    if (!visible.length) renderDetail(null);
  }
  search.addEventListener("input", render); status.addEventListener("change", render); render();
})();
""".strip()


def _payload(ledger: Ledger, include_internal_traces: bool) -> str:
    data = ledger.to_dict()
    projected_usages, projected_findings = project_reviewed_inventory(data)
    data["projected_usage_ids"] = [item["id"] for item in projected_usages]
    data["projected_findings"] = projected_findings
    blocks = {block.id: block for block in ledger.source.blocks}

    def source_context(location, label_prefix: str) -> dict[str, object] | None:
        block = blocks.get(location.block_id)
        if block is None:
            return None
        max_context = 4000
        if len(block.text) <= max_context:
            excerpt_start, excerpt_end = 0, len(block.text)
        else:
            half = max_context // 2
            excerpt_start = max(0, location.char_start - half)
            excerpt_end = min(len(block.text), excerpt_start + max_context)
            excerpt_start = max(0, excerpt_end - max_context)
        context_text = block.text[excerpt_start:excerpt_end]
        kind = "Table cell" if block.kind == "table_cell" else "Paragraph"
        return {
            "label": f"{label_prefix} · {kind} {block.order + 1}",
            "text": context_text,
            "match_start": max(0, location.char_start - excerpt_start),
            "match_end": min(len(context_text), location.char_end - excerpt_start),
            "truncated": excerpt_start > 0 or excerpt_end < len(block.text),
            "location": {
                "part": location.part,
                "block_id": location.block_id,
                "block_order": location.block_order,
                "char_start": location.char_start,
                "char_end": location.char_end,
            },
        }

    data["definition_contexts"] = []
    for definition in ledger.definitions:
        context = source_context(definition.location, "Definition source")
        if context is not None:
            data["definition_contexts"].append(
                {
                    "definition_id": definition.id,
                    "contexts": [context],
                }
            )
    data["semantic_evidence_contexts"] = []
    for adjudication in ledger.semantic_adjudications:
        contexts = [
            context
            for location in adjudication.evidence
            if (context := source_context(location, "Semantic review citation"))
            is not None
        ]
        if contexts:
            data["semantic_evidence_contexts"].append(
                {
                    "review_id": adjudication.review_id,
                    "contexts": contexts,
                }
            )
    data["finding_contexts"] = []
    for finding in ledger.findings:
        contexts = []
        seen_locations = set()
        for location in finding.evidence:
            location_key = (location.block_id, location.char_start, location.char_end)
            if location_key in seen_locations:
                continue
            seen_locations.add(location_key)
            block = blocks.get(location.block_id)
            if block is None:
                continue
            max_context = 4000
            if len(block.text) <= max_context:
                excerpt_start, excerpt_end = 0, len(block.text)
            else:
                half = max_context // 2
                excerpt_start = max(0, location.char_start - half)
                excerpt_end = min(len(block.text), excerpt_start + max_context)
                excerpt_start = max(0, excerpt_end - max_context)
            context_text = block.text[excerpt_start:excerpt_end]
            relative_start = max(0, location.char_start - excerpt_start)
            relative_end = min(len(context_text), location.char_end - excerpt_start)
            kind = "Table cell" if block.kind == "table_cell" else "Paragraph"
            contexts.append(
                {
                    "label": f"{kind} {block.order + 1}",
                    "text": context_text,
                    "match_start": relative_start,
                    "match_end": relative_end,
                    "truncated": excerpt_start > 0 or excerpt_end < len(block.text),
                    "location": {
                        "part": location.part,
                        "block_id": location.block_id,
                        "block_order": location.block_order,
                        "char_start": location.char_start,
                        "char_end": location.char_end,
                    },
                }
            )
        if contexts:
            data["finding_contexts"].append(
                {"finding_id": finding.id, "contexts": contexts}
            )
    data["occurrence_contexts"] = []
    for candidate in ledger.occurrence_candidates:
        block = blocks.get(candidate.location.block_id)
        if block is None:
            continue
        max_context = 4000
        if len(block.text) <= max_context:
            excerpt_start, excerpt_end = 0, len(block.text)
        else:
            half = max_context // 2
            excerpt_start = max(0, candidate.location.char_start - half)
            excerpt_end = min(len(block.text), excerpt_start + max_context)
            excerpt_start = max(0, excerpt_end - max_context)
        text = block.text[excerpt_start:excerpt_end]
        data["occurrence_contexts"].append(
            {
                "usage_id": candidate.usage_id,
                "context": {
                    "label": f"{'Table cell' if block.kind == 'table_cell' else 'Paragraph'} {block.order + 1}",
                    "text": text,
                    "match_start": candidate.location.char_start - excerpt_start,
                    "match_end": candidate.location.char_end - excerpt_start,
                    "truncated": excerpt_start > 0 or excerpt_end < len(block.text),
                    "location": {
                        "part": candidate.location.part,
                        "block_id": candidate.location.block_id,
                        "block_order": candidate.location.block_order,
                        "char_start": candidate.location.char_start,
                        "char_end": candidate.location.char_end,
                    },
                },
            }
        )
    data["finding_term_views"] = []
    for finding in ledger.findings:
        if finding.rule_id != "DEF-001" or not finding.normalized_term:
            continue
        occurrences = []
        for location in finding.evidence:
            block = blocks.get(location.block_id)
            if block is None:
                continue
            observed = block.text[location.char_start : location.char_end]
            occurrences.append(
                {
                    "term": observed,
                    "normalized_term": finding.normalized_term,
                    "observed_form": observed,
                    "location": {
                        "part": location.part,
                        "block_id": location.block_id,
                        "block_order": location.block_order,
                        "char_start": location.char_start,
                        "char_end": location.char_end,
                    },
                    "is_definition_occurrence": False,
                }
            )
        if occurrences:
            data["finding_term_views"].append(
                {
                    "finding_id": finding.id,
                    "term": occurrences[0]["observed_form"],
                    "occurrences": occurrences,
                }
            )
    data["include_internal_traces"] = bool(include_internal_traces)
    if not include_internal_traces:
        data["review_traces"] = []
        data["term_candidates"] = [
            {
                "review_id": item.get("review_id"),
                "term": item.get("term"),
                "normalized_term": item.get("normalized_term"),
                "structural_hints": item.get("structural_hints", []),
            }
            for item in data.get("term_candidates", [])
        ]
        latest: dict[str, dict[str, object]] = {}
        for proposal in data.get("candidate_proposals", []):
            candidate_id = str(
                proposal.get("candidate_id")
                or proposal.get("normalized_term")
                or proposal.get("term")
            )
            previous = latest.get(candidate_id)
            if previous is None or _json_int(proposal.get("revision")) > _json_int(
                previous.get("revision")
            ):
                latest[candidate_id] = proposal
        data["candidate_proposals"] = [
            {
                "term": proposal.get("term"),
                "normalized_term": proposal.get("normalized_term"),
                "state": proposal.get("state"),
                "location": proposal.get("location"),
                "definition_text": proposal.get("definition_text"),
            }
            for proposal in latest.values()
        ]
    # JSON is placed in a script element; escape characters that can terminate it.
    return (
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_html(ledger: Ledger, include_internal_traces: bool = False) -> str:
    data = ledger.to_dict()
    source_name = html.escape(str(data["source"].get("name") or "Untitled"), quote=True)
    payload = _payload(ledger, include_internal_traces)
    supported_quote_formats = ", ".join(
        f"<code>{html.escape(item)}</code>" for item in QUOTED_LABEL_FORMATS
    )
    excluded_quote_formats = ", ".join(
        f"<code>{html.escape(item)}</code>" for item in QUOTED_LABEL_EXCLUSIONS
    )
    candidate_coverage = (
        '<details class="candidate-coverage"><summary>How candidates are found</summary>'
        "<p><strong>Quoted-label recall:</strong> supported examples are "
        + supported_quote_formats
        + ". Parentheses and surrounding words do not affect a quoted match; "
        "each quoted label is queued separately.</p>"
        "<p><strong>Not captured by the quoted-label scanner:</strong> "
        + excluded_quote_formats
        + ". These forms may still be proposed by semantic discovery workers.</p>"
        "<p>A separate over-inclusive lexical scanner also queues multiword "
        "Title Case and ALL-CAPS phrases as potential undefined terms. Candidate "
        "status is not a conclusion; semantic review must confirm or reject it. "
        "Heading-like matches are retained and tagged as heuristic structural "
        "hints rather than suppressed.</p>"
        "</details>"
    )
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Definition glossary — "
        + source_name
        + "</title><style>"
        + _STYLE
        + "</style></head><body>"
        "<header><h1>Document terms</h1><p>"
        + source_name
        + '</p><p class="muted">Source spelling is preserved for display. Normalization is used only as an internal matching key.</p>'
        + '<p class="muted"><strong>Primary review artifact:</strong> this interactive HTML glossary. <code>definition-check.md</code> is the compact static fallback; <code>definition-check.json</code> is the machine-readable ledger.</p>'
        + candidate_coverage
        + '<div class="controls"><label for="term-search">Search terms<input id="term-search" type="search" placeholder="Search terms or aliases"></label>'
        '<label for="term-status">Status<select id="term-status"><option value="defined" selected>Reviewed / extracted definitions</option><option value="undefined">Confirmed / potential undefined</option><option value="rejected">Rejected noise</option><option value="unreviewed">Unreviewed</option><option value="all">All detected terms</option><option value="unused">Unused</option><option value="duplicated">Duplicated</option><option value="inconsistent">Inconsistent</option><option value="unresolved">Unresolved</option><option value="needs_review">Needs review</option></select></label></div></header>'
        '<main><p id="coverage"><strong>Run status:</strong> '
        + html.escape(str(data["run_status"]))
        + " · <strong>Capability:</strong> "
        + html.escape(str(data["capability_profile"]))
        + '</p><p class="muted" role="note"><strong>Parser scope:</strong> document-body and table-cell paragraphs are checked. Headers, footers, footnotes, endnotes, comments, embedded objects, macros, and tracked-change presentation are not checked. See document-specific coverage below.</p>'
        '<div class="layout"><section aria-labelledby="terms-heading"><h2 id="terms-heading">Terms in this document</h2><div id="term-list" class="term-list" role="listbox" aria-label="Detected document terms"></div></section>'
        '<article id="term-detail" aria-live="polite"><p class="muted">Select a term.</p></article></div>'
        "<section><h2>Coverage and limitations</h2><pre>"
        + html.escape(
            json.dumps(
                {
                    "coverage": data["source"].get("coverage", {}),
                    "limitations": data.get("limitations", []),
                    "methods_not_run": data.get("methods_not_run", []),
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
        )
        + "</pre></section></main>"
        '<script type="application/json" id="ledger-data">'
        + payload
        + "</script><script>"
        + _SCRIPT
        + "</script></body></html>\n"
    )


def write_html(
    ledger: Ledger, path: str | Path, include_internal_traces: bool = False
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(
                render_html(ledger, include_internal_traces=include_internal_traces)
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return destination
