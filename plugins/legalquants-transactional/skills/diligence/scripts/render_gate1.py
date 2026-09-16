#!/usr/bin/env python3
# ruff: noqa: E501 -- self-contained HTML, CSS, and JavaScript literals stay readable.
"""Render the fail-closed Diligence setup decision as self-contained HTML.

The lawyer-facing page uses plain-language stages. Internal Gate 1 identity,
framework versioning, source IDs, and reproducibility details remain available
inside collapsed technical receipts. The page records nothing; the
orchestrator records only an explicit lawyer reply.
"""

import argparse
import hashlib
import html
import importlib.util
import json
import posixpath
import sys
from pathlib import Path

_REVIEW_UI_SPEC = importlib.util.spec_from_file_location(
    "diligence_review_ui", Path(__file__).with_name("review_ui.py")
)
if _REVIEW_UI_SPEC is None or _REVIEW_UI_SPEC.loader is None:
    raise RuntimeError("cannot load sibling review_ui.py")
review_ui = importlib.util.module_from_spec(_REVIEW_UI_SPEC)
_REVIEW_UI_SPEC.loader.exec_module(review_ui)
BRAND_CSS = review_ui.BRAND_CSS
CONTRACT_ID = review_ui.CONTRACT_ID
THEME_JS = review_ui.THEME_JS
masthead = review_ui.masthead

_REVIEW_COPIES_SPEC = importlib.util.spec_from_file_location(
    "diligence_review_copies", Path(__file__).with_name("review_copies.py")
)
if _REVIEW_COPIES_SPEC is None or _REVIEW_COPIES_SPEC.loader is None:
    raise RuntimeError("cannot load sibling review_copies.py")
review_copies = importlib.util.module_from_spec(_REVIEW_COPIES_SPEC)
sys.modules[_REVIEW_COPIES_SPEC.name] = review_copies
_REVIEW_COPIES_SPEC.loader.exec_module(review_copies)

UNREADABLE = {"corrupt", "encrypted"}
GAP_LABELS = {
    "attachment-completeness-candidate": "Referenced attachment needs confirmation",
    "duplicate": "Duplicate file",
    "index-missing": "Expected file is missing",
    "referenced-absent": "Referenced material was not supplied",
    "unreadable": "File cannot be read",
}
NUMBER_WORDS = {
    0: "zero",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
}


CSS = (
    BRAND_CSS
    + r"""
:root {
  --bg: var(--lq-background);
  --surface: var(--lq-surface);
  --surface-soft: var(--lq-surface-muted);
  --text: var(--lq-foreground);
  --muted: var(--lq-muted-foreground);
  --line: var(--lq-border);
  --ink: var(--lq-primary);
  --action: var(--lq-primary);
  --action-text: var(--lq-primary-foreground);
  --warn: var(--lq-attention-surface);
  --warn-text: var(--lq-attention);
  --danger: var(--lq-destructive-surface);
  --danger-text: var(--lq-destructive);
}
* { box-sizing: border-box; }
html { background: var(--bg); }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 15px/1.5 var(--lq-font-sans);
}
a { color: var(--ink); text-underline-offset: 3px; }
a:hover { text-decoration-thickness: 2px; }
button, input { font: inherit; }
button:focus-visible, input:focus-visible, summary:focus-visible, a:focus-visible {
  outline: 2px solid var(--ink);
  outline-offset: 3px;
}
.skip { position: absolute; left: -9999px; top: 4px; background: var(--surface); color: var(--text); padding: 6px 10px; z-index: 20; }
.skip:focus { left: 4px; }
main { max-width: 900px; margin: 0 auto; padding: 34px 24px 48px; }
.eyebrow, .kicker { color: var(--ink); font-weight: 500; }
.eyebrow { margin: 0 0 8px; }
h1 { margin: 0; font-size: clamp(1.75rem, 4vw, 2.45rem); line-height: 1.2; }
.lede { max-width: 720px; margin: 12px 0 24px; color: var(--muted); }
.flow {
  display: grid;
  grid-template-columns: repeat(var(--stage-count), 1fr);
  gap: 1px;
  margin: 0 0 28px;
  background: var(--line);
  border: 1px solid var(--line);
}
.step { background: var(--surface); padding: 12px; color: var(--muted); }
.step[aria-current="step"] { color: var(--text); box-shadow: inset 0 3px 0 var(--action); }
.step strong { display: block; font-weight: 500; }
.alert {
  display: flex;
  gap: 10px;
  padding: 14px 16px;
  margin-bottom: 18px;
  background: var(--warn);
  color: var(--warn-text);
}
.alert.blocked { background: var(--danger); color: var(--danger-text); }
.section { margin-top: 14px; background: var(--surface); border: 1px solid var(--line); }
.section-head { padding: 18px 20px 8px; }
.kicker { margin: 0 0 4px; }
h2 { margin: 0; font-size: 1.18rem; }
h3 { margin: 0; font-size: 1rem; }
.help { margin: 6px 0 0; color: var(--muted); }
.section-body { padding: 10px 20px 20px; }
.match-rule, .boundary, .metric, .scope-note { padding: 13px 14px; background: var(--surface-soft); }
.match-rule { margin-bottom: 14px; }
.match-rule strong, .boundary strong, .scope-note strong { display: block; margin-bottom: 4px; }
.search-label { display: block; color: var(--muted); }
.search {
  display: block;
  width: 100%;
  min-height: 40px;
  margin-top: 5px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
}
.question-list { margin-top: 12px; }
.question-item { padding: 11px 0; border-bottom: 1px solid var(--line); }
.question-item:last-child { border-bottom: 0; }
.question-item strong { display: block; }
.question-item span { color: var(--muted); }
.metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.metric strong { display: block; font-size: 1.22rem; }
.metric span { color: var(--muted); }
details { padding: 12px 20px; border-top: 1px solid var(--line); }
summary { cursor: pointer; color: var(--ink); font-weight: 500; }
details p, details li { color: var(--muted); }
details ul { margin: 9px 0 0; padding-left: 21px; }
details li { margin: 8px 0; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 9px 14px 9px 0; text-align: left; vertical-align: top; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
.document-list, .scope-list { margin: 0; padding: 0; list-style: none; }
.document-list li, .scope-list li { padding: 9px 0; border-bottom: 1px solid var(--line); }
.document-list li:last-child, .scope-list li:last-child { border-bottom: 0; }
.document-list strong, .scope-list strong { display: block; }
.document-list span, .scope-list span { color: var(--muted); }
.source-review-item { margin: 14px 0; padding: 14px; border: 1px solid var(--line); background: var(--surface-soft); }
.source-review-item:target { outline: 3px solid var(--ink); outline-offset: 3px; }
.lq-review-copy h3 { margin-bottom: 6px; }
.lq-review-copy-receipt { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.lq-review-copy-frame, .lq-review-copy-pdf { display: block; width: 100%; min-height: 430px; border: 1px solid var(--line); background: var(--surface); }
.lq-review-copy-image { display: block; max-width: 100%; height: auto; margin: 8px auto; border: 1px solid var(--line); }
.lq-needs-rendering { padding: 12px 14px; background: var(--warn); color: var(--warn-text); border-left: 4px solid var(--warn-text); }
.original-file { margin: 9px 0 0; font-size: 13px; }
.group { padding: 10px 0; border-bottom: 1px solid var(--line); }
.group:last-child { border-bottom: 0; }
.edge { padding-left: 12px; border-left: 3px solid var(--ink); }
.edge.proposed { border-left-color: var(--warn-text); }
.edge blockquote { margin: 6px 0; color: var(--text); }
.scope-grid, .boundaries { display: grid; grid-template-columns: 1.1fr .9fr; gap: 18px; }
.approval { margin-top: 18px; padding: 20px; background: var(--surface); border: 2px solid var(--action); }
.boundaries { grid-template-columns: 1fr 1fr; margin: 14px 0; gap: 12px; }
.check { display: flex; gap: 10px; align-items: flex-start; }
.check input { margin-top: 5px; }
.check label { font-weight: 500; }
.actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 15px; }
button {
  appearance: none;
  padding: 10px 15px;
  border: 1px solid var(--line);
  background: var(--surface-soft);
  color: var(--text);
  cursor: pointer;
}
button.primary { background: var(--action); color: var(--action-text); border-color: var(--action); }
button:disabled { opacity: .45; cursor: not-allowed; }
.result { margin-top: 12px; color: var(--ink); font-weight: 500; }
.audit { max-width: 900px; margin: 18px auto 0; padding: 12px 0; border-top: 1px solid var(--line); }
.audit code { color: var(--text); overflow-wrap: anywhere; }
.small { color: var(--muted); font-size: 13px; }
@media (max-width: 680px) {
  main { padding: 24px 14px 36px; }
  .flow { grid-template-columns: 1fr 1fr; }
  .metrics { grid-template-columns: 1fr 1fr; }
  .scope-grid, .boundaries { grid-template-columns: 1fr; }
  .section-head, .section-body { padding-left: 15px; padding-right: 15px; }
}
@media (max-width: 380px) {
  .flow, .metrics { grid-template-columns: 1fr; }
  .actions button { width: 100%; }
}
"""
)


def esc(value):
    return html.escape(str(value), quote=True)


def word(number):
    return NUMBER_WORDS.get(number, str(number))


def load(path, kind, required_keys):
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        sys.exit(f"render_gate1: cannot read {kind} at {path}: {error}")
    if not isinstance(value, dict):
        sys.exit(f"render_gate1: {kind} must be an object")
    for key in required_keys:
        if key not in value:
            sys.exit(f"render_gate1: {kind} missing key '{key}'")
    return value


def apply_metadata(manifest, metadata_dir):
    documents = {row["id"]: dict(row) for row in manifest.get("documents", [])}
    expected = {
        doc_id
        for doc_id, row in documents.items()
        if row.get("review_role", "substantive") != "runner-control"
    }
    if not metadata_dir.is_dir():
        sys.exit(f"render_gate1: metadata directory is missing: {metadata_dir}")
    seen = set()
    for path in sorted(metadata_dir.glob("*.json")):
        metadata = load(path, "metadata", ["id", "status"])
        doc_id = metadata["id"]
        if not isinstance(doc_id, str) or not doc_id:
            sys.exit(f"render_gate1: metadata at {path} has an invalid id")
        if doc_id in seen:
            sys.exit(f"render_gate1: duplicate metadata id {doc_id!r}")
        if doc_id not in expected:
            sys.exit(f"render_gate1: metadata references unknown unit {doc_id!r}")
        seen.add(doc_id)
        if metadata["status"] != "complete":
            continue
        for key in ("dated", "title"):
            value = metadata.get(key)
            if value is not None and not isinstance(value, str):
                sys.exit(
                    f"render_gate1: metadata {doc_id!r} field {key!r} "
                    "must be a string or null"
                )
            if value:
                documents[doc_id][key] = value
    if seen != expected:
        missing = ", ".join(sorted(expected - seen))
        sys.exit(
            f"render_gate1: metadata does not cover substantive unit(s): {missing}"
        )
    enriched = dict(manifest)
    enriched["documents"] = [documents[row["id"]] for row in manifest["documents"]]
    return enriched


def source_href(prefix, path):
    try:
        return review_ui.source_href(prefix, path, link_without_prefix=False)
    except ValueError as error:
        sys.exit(f"render_gate1: {error}")


def doc_label(document):
    return document.get("title") or posixpath.basename(
        document.get("path", document.get("id", "document"))
    )


def document_anchor(document):
    path_digest = hashlib.sha256(document.get("path", "").encode("utf-8")).hexdigest()[
        :8
    ]
    doc_id = str(document.get("id", "document")).removeprefix("sha256:")
    return f"review-document-{doc_id}-{path_digest}"


def review_copy_blockers(validation):
    if validation.sidecar is None:
        return []
    return [
        row
        for row in validation.sidecar.get("documents", [])
        if row.get("status") != "ready"
    ]


def render_review_document(document, prefix, validation):
    label = doc_label(document)
    href = source_href(prefix, document.get("path", ""))
    original = (
        f'<a href="{esc(href)}" target="_blank" rel="noopener">Open original file ↗</a>'
        if href
        else "Original-file link not supplied"
    )
    component = review_copies.render_review_copy_component(
        validation,
        document.get("id", ""),
        path=document.get("path", ""),
        title=label,
    )
    return (
        f'<article id="{esc(document_anchor(document))}" class="source-review-item" '
        'data-review-document="true" tabindex="-1">'
        f'{component}<p class="original-file">{original}</p></article>'
    )


def validate_review_copy_inputs(sidecar, manifest, document_root, output):
    if sidecar.parent.resolve() != output.parent.resolve():
        sys.exit(
            "render_gate1: review-copies sidecar and HTML output must share a directory"
        )
    validation = review_copies.revalidate_review_copies(
        sidecar, manifest, document_root
    )
    if not validation.integrity_ok:
        detail = "; ".join(validation.errors)
        sys.exit(f"render_gate1: review-copy validation failed: {detail}")
    return validation


def unit_members(families):
    members = {}
    for family in families.get("families", []):
        family_id = family.get("family_id")
        family_members = [row.get("id") for row in family.get("members", [])]
        if not isinstance(family_id, str) or not family_id:
            sys.exit("render_gate1: family has an invalid family_id")
        if any(not isinstance(value, str) or not value for value in family_members):
            sys.exit(f"render_gate1: family {family_id!r} has an invalid member ID")
        members[family_id] = sorted(set(family_members))
    for orphan in families.get("orphans", []):
        if not isinstance(orphan, str) or not orphan:
            sys.exit("render_gate1: families contain an invalid orphan ID")
        if orphan in members:
            sys.exit(f"render_gate1: review unit {orphan!r} is duplicated")
        members[orphan] = [orphan]
    return members


def validate_scope(sample, available_units, documents):
    rows = sample.get("proposed_units")
    if not isinstance(rows, list) or not rows:
        sys.exit("render_gate1: sample has no proposed_units")
    selected = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            sys.exit(f"render_gate1: sample row {index} is not an object")
        doc_id = row.get("doc_id")
        if not isinstance(doc_id, str) or not doc_id:
            sys.exit(f"render_gate1: sample row {index} has no doc_id")
        selected.append(doc_id)
    if len(selected) != len(set(selected)):
        sys.exit("render_gate1: sample contains duplicate unit IDs")
    unknown = sorted(set(selected) - set(available_units))
    if unknown:
        sys.exit(
            "render_gate1: sample references unknown unit(s): " + ", ".join(unknown)
        )
    if sample.get("sample_size") != len(selected):
        sys.exit("render_gate1: sample_size does not match proposed_units")
    all_scope = set(selected) == set(available_units)
    if len(available_units) <= 5 and not all_scope:
        sys.exit(
            "render_gate1: a room with five or fewer units must show complete review scope"
        )
    for doc_id in selected:
        if doc_id not in documents:
            sys.exit(f"render_gate1: selected unit {doc_id!r} has no manifest document")
    return selected, all_scope


def render_question_list(items):
    out = ['<div id="question-list" class="question-list">']
    for index, item in enumerate(items, 1):
        search = " ".join(
            str(item.get(key, "")) for key in ("lens", "question", "hit_rule")
        ).lower()
        out.append(
            f'<article class="question-item" data-search="{esc(search)}">'
            f"<strong>{index}. {esc(item.get('question', ''))}</strong>"
            f"<span>{esc(item.get('lens', ''))}</span></article>"
        )
    out.append("</div>")
    return "\n".join(out)


def render_rule_table(items):
    out = [
        '<div class="table-wrap"><table><thead><tr>',
        "<th>Review question</th><th>What counts</th><th>When no conclusion is presented</th>",
        "</tr></thead><tbody>",
    ]
    for item in items:
        unresolved = item.get("unresolved_when") or (
            "The supplied text does not support a conclusion."
        )
        out.append(
            f"<tr><td>{esc(item.get('question', ''))}</td>"
            f"<td>{esc(item.get('hit_rule', ''))}</td>"
            f"<td>{esc(unresolved)}</td></tr>"
        )
    out.append("</tbody></table></div>")
    return "\n".join(out)


def render_documents(documents, prefix, validation):
    out = ['<ul class="document-list">']
    for document in sorted(
        documents, key=lambda row: (row.get("dated") or "", doc_label(row))
    ):
        label = esc(doc_label(document))
        dated = document.get("dated") or "Date not stated in inventory"
        out.append(
            f"<li><strong>{label}</strong>"
            f"<span>{esc(dated)} · {esc(document.get('path', ''))}</span>"
            f"{render_review_document(document, prefix, validation)}</li>"
        )
    out.append("</ul>")
    return "\n".join(out)


def render_gaps(entries):
    if not entries:
        return '<p class="small">No collection gaps were identified from the supplied files.</p>'
    out = ["<ul>"]
    for entry in entries:
        label = GAP_LABELS.get(entry.get("type"), "Collection question")
        out.append(
            f"<li><strong>{esc(label)}:</strong> {esc(entry.get('detail', ''))}"
            f'<div class="small">Basis: {esc(entry.get("evidence", ""))}</div></li>'
        )
    out.append("</ul>")
    return "\n".join(out)


def render_groups(families, documents):
    family_rows = sorted(
        families.get("families", []), key=lambda row: row.get("family_id", "")
    )
    if not family_rows:
        return (
            "<p>Each supplied agreement will be reviewed separately. The available "
            "metadata did not establish an amendment, schedule, statement of work, "
            "or other supplied file that should be read together with another agreement.</p>"
        )
    out = []
    for family in family_rows:
        base = documents.get(
            family.get("family_id"), {"id": family.get("family_id", "")}
        )
        out.append(f'<div class="group"><h3>{esc(doc_label(base))}</h3><ul>')
        members = sorted(
            family.get("members", []),
            key=lambda row: (row.get("order", 0), row.get("id", "")),
        )
        for member in members:
            document = documents.get(member.get("id"), {"id": member.get("id", "")})
            out.append(
                f"<li>{esc(doc_label(document))} · "
                f"{esc(member.get('role', 'related document'))}</li>"
            )
        out.append("</ul>")
        edges = sorted(
            family.get("edges", []),
            key=lambda row: (row.get("src", ""), row.get("dst", "")),
        )
        for edge in edges:
            proposed = edge.get("provenance") == "model"
            css_class = "edge proposed" if proposed else "edge"
            status = (
                "Needs your confirmation"
                if proposed
                else "Matched from the supplied reference text"
            )
            out.append(
                f'<div class="{css_class}"><strong>{esc(status)}:</strong> '
                f"{esc(edge.get('relation', 'related'))}"
            )
            if edge.get("quote"):
                out.append(f"<blockquote>“{esc(edge.get('quote'))}”</blockquote>")
            out.append("</div>")
        out.append("</div>")
    return "\n".join(out)


def render_scope_rows(sample):
    out = ['<ul class="scope-list">']
    for row in sample.get("proposed_units", []):
        out.append(
            f"<li><strong>{esc(row.get('label') or row.get('doc_id', ''))}</strong>"
            f"<span>{esc(row.get('reason', 'Included in the proposed review scope.'))}</span></li>"
        )
    out.append("</ul>")
    return "\n".join(out)


def build_html(
    manifest, families, gaps, readback, sample, source_prefix, review_validation
):
    documents = {row["id"]: row for row in manifest.get("documents", [])}
    if len(documents) != len(manifest.get("documents", [])):
        sys.exit("render_gate1: manifest contains duplicate document IDs")
    for document in documents.values():
        source_href(source_prefix, document.get("path", ""))
    substantive = [
        row
        for row in documents.values()
        if row.get("review_role", "substantive") != "runner-control"
    ]
    control = [
        row for row in documents.values() if row.get("review_role") == "runner-control"
    ]
    members_by_unit = unit_members(families)
    accounted_ids = {
        doc_id for member_ids in members_by_unit.values() for doc_id in member_ids
    }
    substantive_ids = {row["id"] for row in substantive}
    if accounted_ids != substantive_ids:
        missing = sorted(substantive_ids - accounted_ids)
        extra = sorted(accounted_ids - substantive_ids)
        sys.exit(
            f"render_gate1: family/unit census drift; missing={missing}, extra={extra}"
        )
    available_units = sorted(members_by_unit)
    selected, all_scope = validate_scope(sample, available_units, documents)
    selected_unreadable = []
    for unit_id in selected:
        if any(
            documents[doc_id].get("readability") in UNREADABLE
            for doc_id in members_by_unit[unit_id]
        ):
            selected_unreadable.append(unit_id)
    render_blockers = review_copy_blockers(review_validation)
    blocked = bool(selected_unreadable or render_blockers)
    items = readback.get("items", [])
    if not items:
        sys.exit("render_gate1: readback contains no review questions")
    entries = gaps.get("entries", [])

    dates = sorted(row.get("dated") for row in substantive if row.get("dated"))
    date_span = "Not supplied"
    if dates:
        first, last = dates[0][:4], dates[-1][:4]
        date_span = first if first == last else f"{first}–{last}"
    duplicates = sum(1 for entry in entries if entry.get("type") == "duplicate")
    unreadable_total = sum(
        1 for row in substantive if row.get("readability") in UNREADABLE
    )
    open_count = len(entries)
    selected_count = len(selected)
    issue_count = len(items)
    scope_word = word(selected_count)

    if all_scope:
        stages = [
            ("1 · Set up", "Confirm the rules", True),
            ("2 · Review all agreements", f"Review all {selected_count}", False),
            ("3 · Final decisions", "Lawyer review", False),
        ]
        scope_heading = f"Should we review all {scope_word} agreements?"
        scope_help = "This small collection can be reviewed in full without a separate test subset."
        approval_heading = f"Ready to review all {scope_word} agreements?"
        authorizes = (
            f"Starts factual review of all {selected_count} listed agreements against "
            f"all {issue_count} listed questions. The checked results return for lawyer "
            "review before any final use."
        )
    else:
        stages = [
            ("1 · Set up", "Confirm the rules", True),
            ("2 · Test sample", f"Review {selected_count} agreements", False),
            ("3 · Full review", "Only after approval", False),
            ("4 · Final decisions", "Lawyer review", False),
        ]
        scope_heading = f"Is this a useful {scope_word}-agreement test?"
        scope_help = (
            "This subset is intended to calibrate the questions before broader review."
        )
        approval_heading = "Ready to run the test?"
        authorizes = (
            f"Starts factual review of only the {selected_count} listed agreements "
            f"against all {issue_count} questions. The checked results return before "
            "broader review."
        )

    stage_parts = []
    for title, detail, current in stages:
        current_attr = ' aria-current="step"' if current else ""
        stage_parts.append(
            f'<div class="step"{current_attr}><strong>{esc(title)}</strong>'
            f"{esc(detail)}</div>"
        )
    stage_html = "".join(stage_parts)

    if render_blockers:
        count_phrase = (
            "one file" if len(render_blockers) == 1 else f"{len(render_blockers)} files"
        )
        alert = (
            f'<div class="alert blocked" role="alert"><div><strong>Review paused: '
            f"{count_phrase} need rendering.</strong> A verified in-page review copy is "
            "required before approval. The affected file remains visible below and will "
            "not be treated as reviewed or as having no responsive terms.</div></div>"
        )
    elif selected_unreadable:
        count_phrase = (
            "one selected agreement"
            if len(selected_unreadable) == 1
            else f"{len(selected_unreadable)} selected agreements"
        )
        alert = (
            f'<div class="alert blocked" role="alert"><div><strong>Review paused: '
            f"{count_phrase} cannot be read.</strong> It will not be treated as having "
            "no responsive terms. Replace it or expressly remove it from scope before "
            "review can begin.</div></div>"
        )
    elif open_count:
        alert = (
            f'<div class="alert" role="alert"><div><strong>'
            f"{word(open_count).capitalize()} collection questions remain open.</strong> "
            "They will stay in Needs attention and will not be treated as negative "
            "findings. Review the collection details below before approving.</div></div>"
        )
    else:
        alert = ""

    approval_statement = (
        f"I approve the Diligence review setup shown on this page: {len(substantive)} "
        f"substantive agreements, {len(control)} instruction input, {issue_count} factual "
        f"review questions and their match definitions, {open_count} open collection "
        f"questions, and review of {selected_count} agreements. This authorizes factual "
        "review of the listed agreements only and requires the checked results to return "
        "for my review. It does not authorize risk or materiality rankings, legal "
        "conclusions, recommendations, sending, producing, publishing, or final "
        "transaction decisions."
    )
    blocked_attr = ' data-blocked="true"' if blocked else ""
    check_disabled = " disabled" if blocked else ""

    parts = [
        "<!doctype html>",
        f'<html lang="en" data-lq-review-ui="{CONTRACT_ID}"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Confirm the Diligence review setup</title>",
        f"<style>{CSS}</style></head><body>",
        '<a class="skip" href="#review-setup">Skip to review setup</a>',
        masthead(esc(f"{manifest.get('root_label', 'Agreement collection')} · Setup")),
        '<main id="review-setup">',
        '<p class="eyebrow">Set up the review</p>',
        "<h1>Confirm what we should look for</h1>",
        f'<p class="lede">Before any agreement review begins, check the {issue_count} '
        f"questions, the {len(substantive)} agreements received, and the proposed review "
        "scope. You can change any of them now.</p>",
        f'<nav class="flow" aria-label="Review progress" style="--stage-count:{len(stages)}">{stage_html}</nav>',
        alert,
        '<section class="section" aria-labelledby="questions-title">',
        '<div class="section-head"><p class="kicker">Decision 1 of 3</p>',
        '<h2 id="questions-title">Are these the right review questions?</h2>',
        f'<p class="help">Each selected agreement will be checked against every one of '
        f"the {issue_count} questions below.</p></div>",
        '<div class="section-body">',
        '<div class="match-rule"><strong>What counts as a match</strong>Agreement language that directly addresses the approved question. Every match must include a verbatim quote and section reference. Missing schedules or outside facts become “Needs a decision”—never “Not found.” No risk, severity, materiality, or recommendation ranking will be applied.</div>',
        '<label class="search-label" for="question-search">Search the review questions<input id="question-search" class="search" type="search" placeholder="Search questions or topics"></label>',
        render_question_list(items),
        "</div>",
        "<details><summary>See the exact match definitions and evidence rules</summary>",
        "<p>“Not found” means only that the supplied agreement text did not contain language meeting the definition. It does not cover missing schedules, amendments, side letters, or outside facts.</p>",
        render_rule_table(items),
        "</details></section>",
        '<section class="section" aria-labelledby="collection-title">',
        '<div class="section-head"><p class="kicker">Decision 2 of 3</p>',
        '<h2 id="collection-title">Does this look like the collection you expected?</h2>',
        '<p class="help">You are confirming what is available for review—not certifying that the data room or transaction record is legally complete.</p></div>',
        '<div class="section-body"><div class="metrics">',
        f'<div class="metric"><strong>{len(substantive)}</strong><span>agreements to review</span></div>',
        f'<div class="metric"><strong>{len(control)}</strong><span>instruction input</span></div>',
        f'<div class="metric"><strong>{esc(date_span)}</strong><span>stated agreement dates</span></div>',
        f'<div class="metric"><strong>{duplicates + unreadable_total}</strong><span>duplicate or unreadable files</span></div>',
        "</div></div>",
        "<details><summary>Review the supplied agreements and dates</summary>",
        '<p class="small">Review copies are hash-bound to the manifest and rechecked before this page is issued.</p>',
        render_documents(substantive, source_prefix, review_validation),
        "</details>",
        "<details><summary>Review instructions and collection limits</summary>",
        render_documents(control, source_prefix, review_validation),
        render_gaps(entries),
        "<p>This is a contract collection, so custodian statistics are not applicable. The practical question is whether these are the agreements and referenced materials you expected us to have.</p>",
        "</details>",
        "<details><summary>How the agreements will be reviewed together</summary>",
        "<p>Does this grouping match how you understand the agreements and their related documents?</p>",
        render_groups(families, documents),
        "</details></section>",
        '<section class="section" aria-labelledby="scope-title">',
        '<div class="section-head"><p class="kicker">Decision 3 of 3</p>',
        f'<h2 id="scope-title">{esc(scope_heading)}</h2>',
        f'<p class="help">{esc(scope_help)}</p></div>',
        '<div class="section-body scope-grid">',
        render_scope_rows(sample),
        '<div class="scope-note"><strong>Why this scope</strong>',
        f"{esc(sample.get('selection_basis', 'The selected agreements cover the proposed review scope.'))}</div>",
        "</div></section>",
        f'<section class="approval" aria-labelledby="approval-title"><h2 id="approval-title">{esc(approval_heading)}</h2>',
        '<p class="help">Approval is narrow. The review stops again before any final use of the results.</p>',
        '<div class="boundaries">',
        f'<div class="boundary"><strong>What approving this does</strong>{esc(authorizes)}</div>',
        '<div class="boundary"><strong>What it does not do</strong>It does not authorize risk or materiality rankings, legal conclusions, recommendations, privilege rulings, sending, producing, publishing, or final transaction decisions.</div>',
        "</div>",
        f'<div class="check"><input id="approval-check" type="checkbox"{check_disabled}>',
        f'<label for="approval-check">I confirm the {issue_count} review questions, the supplied collection and open gaps, and the listed review scope are appropriate.</label></div>',
        '<div class="actions">',
        f'<button class="primary" id="prepare-approval" type="button" disabled{blocked_attr}>Prepare approval statement</button>',
        '<span class="small">Nothing on this page records approval or starts review.</span></div>',
        '<div id="approval-result" class="result" aria-live="polite"></div>',
        "</section>",
        '<details id="audit-details" class="audit"><summary>Technical receipts and reproducibility details</summary>',
        "<p><strong>Practical consequence:</strong> source identity and the review instructions remain bound. If a supplied file, agreement grouping, review question, or scope changes, this approval becomes stale and must be renewed.</p>",
        f"<p>Internal control: Gate 1 · framework version <code>{esc(readback.get('framework_version', 'not recorded'))}</code> · framework status <code>{'approved' if readback.get('approved') else 'not approved'}</code> · deterministic local rendering · no findings exist.</p>",
        f"<p>Review-copy receipt: <code>{esc(review_validation.sidecar.get('digest'))}</code> · status <code>{esc(review_validation.sidecar.get('status'))}</code>.</p>",
        "<ul>",
    ]
    for document in sorted(documents.values(), key=lambda row: row["id"]):
        parts.append(
            f"<li><code>{esc(document['id'])}</code> · "
            f"{esc(document.get('path', ''))}</li>"
        )
    parts.extend(
        [
            "</ul></details>",
            "</main>",
            "<script>",
            "(() => {",
            "  const search = document.getElementById('question-search');",
            "  const questions = [...document.querySelectorAll('.question-item')];",
            "  const check = document.getElementById('approval-check');",
            "  const prepare = document.getElementById('prepare-approval');",
            "  const result = document.getElementById('approval-result');",
            f"  const blocked = {str(blocked).lower()};",
            f"  const statement = {json.dumps(approval_statement)};",
            "  search.addEventListener('input', () => {",
            "    const term = search.value.trim().toLowerCase();",
            "    questions.forEach((row) => {",
            "      row.hidden = Boolean(term) && !row.dataset.search.includes(term);",
            "    });",
            "  });",
            "  check.addEventListener('change', () => {",
            "    prepare.disabled = blocked || !check.checked;",
            "    result.textContent = '';",
            "  });",
            "  prepare.addEventListener('click', () => {",
            "    result.textContent = statement + ' Send this exact statement in the conversation to record approval.';",
            "  });",
            "})();",
            "</script>",
            f"<script>{THEME_JS}</script></body></html>",
        ]
    )
    return "\n".join(parts) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Render the Diligence setup surface.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--families", required=True)
    parser.add_argument("--gaps", required=True)
    parser.add_argument("--readback", required=True)
    parser.add_argument("--sample", required=True)
    parser.add_argument("--source-prefix", default=None)
    parser.add_argument("--review-copies", required=True, type=Path)
    parser.add_argument("--document-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    manifest = load(args.manifest, "manifest", ["documents", "counts"])
    families = load(args.families, "families", ["families", "orphans"])
    gaps = load(args.gaps, "gap report", ["entries"])
    readback = load(args.readback, "readback", ["items"])
    sample = load(args.sample, "sample", ["proposed_units", "sample_size"])
    for document in manifest.get("documents", []):
        source_href(args.source_prefix, document.get("path", ""))
    review_validation = validate_review_copy_inputs(
        args.review_copies, args.manifest, args.document_root, args.out
    )
    manifest = apply_metadata(manifest, args.metadata)
    rendered = build_html(
        manifest,
        families,
        gaps,
        readback,
        sample,
        args.source_prefix,
        review_validation,
    )
    try:
        with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
    except OSError as error:
        sys.exit(f"render_gate1: cannot write {args.out}: {error}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
