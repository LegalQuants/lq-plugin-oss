#!/usr/bin/env python3
# ruff: noqa: E501 -- self-contained HTML, CSS, and JavaScript literals stay readable.
"""Render the Gate 3 factual issue/agreement crosswalk.

The renderer consumes only the frozen framework, checked findings ledger,
manifest, confirmed family map, and gap report. It refuses an incomplete
issue × substantive-unit matrix through reconcile_counts.py. The output is a
self-contained, deterministic HTML review surface plus a JSON receipt.

Usage:
    python3 render_crosswalk.py --framework framework.json \
        --findings findings.json --manifest manifest.json \
        --families families.confirmed.json --gaps gap-report.json \
        [--source-prefix ../room] --out crosswalk.html \
        --receipt crosswalk-receipt.json
"""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import posixpath
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_RECONCILE_SPEC = importlib.util.spec_from_file_location(
    "diligence_reconcile_counts", Path(__file__).with_name("reconcile_counts.py")
)
if _RECONCILE_SPEC is None or _RECONCILE_SPEC.loader is None:
    raise RuntimeError("cannot load sibling reconcile_counts.py")
reconcile_counts = importlib.util.module_from_spec(_RECONCILE_SPEC)
_RECONCILE_SPEC.loader.exec_module(reconcile_counts)

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

STATUS_LABELS = {
    "present": "Found",
    "absent": "Not found",
    "unresolved": "Needs a decision",
}
STATUS_CLASSES = {
    "present": "found",
    "absent": "not-found",
    "unresolved": "needs-review",
}
PRESCRIPTIVE_PHRASES = (
    "buyer should",
    "seller should",
    "we recommend",
    "we advise",
    "recommended action",
)


def read_json(path: Path, label: str, required: tuple[str, ...]) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label} at {path}: {exc}") from exc
    for key in required:
        if key not in data:
            raise ValueError(f"{label} missing key {key!r}")
    return data


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def pretty_filename(path: str) -> str:
    stem = posixpath.splitext(posixpath.basename(path))[0]
    words = stem.replace("-", " ").replace("_", " ").split()
    acronyms = {"msa", "psa", "ssa", "ela", "iaas", "dpa", "sow", "nda"}
    return " ".join(
        word.upper() if word.lower() in acronyms else word.capitalize()
        for word in words
    )


def source_href(prefix: str, path: str) -> str:
    return review_ui.source_href(prefix, path, link_without_prefix=True)


def document_anchor(document: dict) -> str:
    path_digest = hashlib.sha256(document.get("path", "").encode("utf-8")).hexdigest()[
        :8
    ]
    doc_id = str(document.get("id", "document")).removeprefix("sha256:")
    return f"review-document-{doc_id}-{path_digest}"


def render_review_document(document, source_prefix, validation, *, title=None):
    heading = title or pretty_filename(document.get("path", "")) or "Document"
    href = source_href(source_prefix, document.get("path", ""))
    component = review_copies.render_review_copy_component(
        validation,
        document.get("id", ""),
        path=document.get("path", ""),
        title=heading,
    )
    return (
        f'<article id="{esc(document_anchor(document))}" class="source-review-item" '
        'data-review-document="true" tabindex="-1">'
        f'{component}<p class="original-file"><a href="{esc(href)}" '
        'target="_blank" rel="noopener">Open original file ↗</a></p></article>'
    )


def status_counts(rows: list[dict]) -> Counter:
    return Counter(row.get("status") for row in rows)


def badge(status: str, count: int | None = None) -> str:
    suffix = f" {count}" if count is not None else ""
    return (
        f'<span class="pill {STATUS_CLASSES[status]}">'
        f"{esc(STATUS_LABELS[status])}{suffix}</span>"
    )


def build_model(manifest, families, framework, findings, gaps, reconciliation):
    documents = {row["id"]: row for row in manifest["documents"]}
    family_by_unit = {
        row.get("family_id", ""): row for row in families.get("families", [])
    }
    issues = []
    issue_by_id = {}
    for lens_order, lens in enumerate(framework["lenses"]):
        for issue_order, item in enumerate(lens.get("items", [])):
            issue = {
                "issue_id": item["issue_id"],
                "question": item["question"],
                "lens_id": lens["lens_id"],
                "lens_name": lens.get("name", lens["lens_id"]),
                "lens_order": lens_order,
                "issue_order": issue_order,
            }
            issues.append(issue)
            issue_by_id[issue["issue_id"]] = issue

    reviewable = reconciliation["reviewable_units"]
    units: list[dict[str, Any]] = []
    unit_by_id = {}
    for unit_id in reviewable:
        family = family_by_unit.get(unit_id)
        if family:
            members = sorted(
                family.get("members", []),
                key=lambda row: (row.get("order", 0), row.get("id", "")),
            )
        else:
            members = [{"id": unit_id, "role": "standalone", "order": 0}]
        member_rows = []
        for member in members:
            document = documents.get(member.get("id", ""))
            if not document or document.get("review_role") == "runner-control":
                continue
            member_rows.append(
                {
                    "id": member["id"],
                    "path": document["path"],
                    "role": member.get("role", "member"),
                }
            )
        base = documents.get(unit_id) or documents[member_rows[0]["id"]]
        unit = {
            "unit_id": unit_id,
            "name": pretty_filename(base["path"]),
            "path": base["path"],
            "members": member_rows,
            "parked": unit_id in reconciliation["parked_units"],
        }
        units.append(unit)
        unit_by_id[unit_id] = unit
    units.sort(key=lambda row: (row["name"].lower(), row["unit_id"]))

    rows = []
    by_issue = defaultdict(list)
    by_unit = defaultdict(list)
    for raw in findings.get("findings", []):
        row = dict(raw)
        row["document"] = documents[row["doc_id"]]
        row["unit"] = unit_by_id[row["unit_id"]]
        row["issue"] = issue_by_id[row["issue_id"]]
        rows.append(row)
        by_issue[row["issue_id"]].append(row)
        by_unit[row["unit_id"]].append(row)
    for issue_id in by_issue:
        by_issue[issue_id].sort(key=lambda row: row["unit"]["name"].lower())
    issue_order = {row["issue_id"]: index for index, row in enumerate(issues)}
    for unit_id in by_unit:
        by_unit[unit_id].sort(key=lambda row: issue_order[row["issue_id"]])
    return {
        "documents": documents,
        "issues": issues,
        "units": units,
        "rows": rows,
        "by_issue": by_issue,
        "by_unit": by_unit,
        "gaps": gaps.get("entries", []),
    }


def receipt_text(row: dict) -> str:
    quote_receipt = row.get("quote_verification") or {}
    checker_receipt = row.get("verification") or {}
    quote_checker = quote_receipt.get("checker") or "deterministic text match"
    finding_checker = checker_receipt.get("checker") or "independent checker"
    return f"Quote verified · {quote_checker}; finding checked · {finding_checker}"


def finding_search_text(row: dict) -> str:
    document = row["document"]
    unit = row["unit"]
    title = unit["name"]
    if row["doc_id"] != row["unit_id"]:
        title += f" · evidence in {pretty_filename(document['path'])}"
    return " ".join(
        str(value or "")
        for value in (
            row["issue"]["question"],
            title,
            document["path"],
            row.get("section"),
            row.get("characterization"),
            row.get("quote"),
        )
    ).lower()


def finding_card(row: dict, compact: bool = False) -> str:
    status = row["status"]
    document = row["document"]
    unit = row["unit"]
    title = unit["name"]
    if row["doc_id"] != row["unit_id"]:
        title += f" · evidence in {pretty_filename(document['path'])}"
    search = finding_search_text(row)
    out = [
        f'<article class="finding-card {STATUS_CLASSES[status]}" '
        f'data-status="{esc(status)}" data-search="{esc(search)}">',
        '<div class="finding-head">',
        f'<div><div class="finding-title">{esc(title)}</div>'
        f'<div class="fileline">{esc(document["path"])}</div></div>',
        badge(status),
        "</div>",
    ]
    if row.get("characterization"):
        out.append(f'<p class="characterization">{esc(row["characterization"])}</p>')
    if status == "present" and not compact:
        out.append(f"<blockquote>{esc(row['quote'])}</blockquote>")
        out.append(
            f'<p class="cite">{esc(row.get("section"))} · {esc(document["path"])}</p>'
        )
        out.append('<div class="receipt-line">')
        out.append(f'<span class="verification">✓ {esc(receipt_text(row))}</span>')
        if row.get("current_position"):
            out.append('<span class="current">Current governing position</span>')
        out.append("</div>")
    elif status == "unresolved":
        out.append(
            '<p class="scope-note">No affirmative contract conclusion is presented '
            "for this result.</p>"
        )
    out.append(
        f'<p class="source-access"><a href="#{esc(document_anchor(document))}" '
        'data-review-jump="true">Review document on this page ↓</a></p>'
    )
    out.append("</article>")
    return "\n".join(out)


def render_issue_group(issue, rows):
    counts = status_counts(rows)
    search = " ".join(
        [issue["question"], issue["lens_name"]]
        + [finding_search_text(row) for row in rows]
    ).lower()
    out = [
        f'<details class="crosswalk-group" data-search="{esc(search)}">',
        "<summary>",
        '<div class="summary-main">',
        f'<span class="eyebrow">{esc(issue["lens_name"])}</span>',
        f'<span class="group-title">{esc(issue["question"])}</span>',
        "</div>",
        '<div class="pills">',
        badge("present", counts["present"]),
        badge("unresolved", counts["unresolved"]),
        badge("absent", counts["absent"]),
        "</div></summary>",
        '<div class="group-body">',
    ]
    for label, status in (("Found", "present"), ("Needs a decision", "unresolved")):
        selected = [row for row in rows if row["status"] == status]
        if selected:
            out.append(f"<h4>{label} · {len(selected)}</h4>")
            out.extend(finding_card(row) for row in selected)
    absent = [row for row in rows if row["status"] == "absent"]
    if absent:
        out.append(
            f'<details class="negative-drawer"><summary>Also checked: {len(absent)} '
            "agreement unit(s) with nothing found</summary>"
        )
        out.append(
            '<p class="scope-note">“Not found” is limited to the supplied visible '
            "text in these reviewed agreement units.</p>"
        )
        out.extend(finding_card(row, compact=True) for row in absent)
        out.append("</details>")
    out.append("</div></details>")
    return "\n".join(out)


def member_links(unit):
    links = []
    for member in unit["members"]:
        links.append(
            f'<a href="#{esc(document_anchor(member))}" data-review-jump="true">'
            f'Review {esc(member["path"])}</a> <span class="role">{esc(member["role"])}</span>'
        )
    return "<br>".join(links)


def render_unit_group(unit, rows, source_prefix, validation):
    counts = status_counts(rows)
    search = " ".join(
        [unit["name"]]
        + [member["path"] for member in unit["members"]]
        + [finding_search_text(row) for row in rows]
    ).lower()
    out = [
        f'<details class="crosswalk-group" data-search="{esc(search)}">',
        "<summary>",
        '<div class="summary-main"><span class="eyebrow">Agreement unit</span>',
        f'<span class="group-title">{esc(unit["name"])}</span>',
        f'<span class="memberline">{len(unit["members"])} source file(s)</span></div>',
        '<div class="pills">',
    ]
    if unit["parked"]:
        out.append('<span class="pill needs-review">Parked</span>')
    else:
        out.extend(
            [
                badge("present", counts["present"]),
                badge("unresolved", counts["unresolved"]),
                badge("absent", counts["absent"]),
            ]
        )
    out.extend(
        [
            "</div></summary>",
            '<div class="group-body">',
            f'<div class="member-box"><b>Unit documents</b><br>{member_links(unit)}</div>',
        ]
    )
    for member in unit["members"]:
        out.append(
            render_review_document(
                member,
                source_prefix,
                validation,
                title=pretty_filename(member["path"]),
            )
        )
    if unit["parked"]:
        out.append(
            '<p class="scope-note">This unit was parked and no substantive result is '
            "presented for any issue.</p>"
        )
    else:
        for label, status in (("Found", "present"), ("Needs a decision", "unresolved")):
            selected = [row for row in rows if row["status"] == status]
            if selected:
                out.append(f"<h4>{label} · {len(selected)}</h4>")
                for row in selected:
                    out.append(
                        f'<div class="issue-context">{esc(row["issue"]["question"])}</div>'
                    )
                    out.append(finding_card(row))
        absent = [row for row in rows if row["status"] == "absent"]
        if absent:
            out.append(
                f'<details class="negative-drawer"><summary>Also checked: {len(absent)} '
                "issue(s) with nothing found</summary>"
            )
            out.append(
                '<p class="scope-note">These negatives are limited to this unit’s '
                "supplied visible text.</p>"
            )
            for row in absent:
                out.append(
                    f'<div class="issue-context">{esc(row["issue"]["question"])}</div>'
                )
                out.append(finding_card(row, compact=True))
            out.append("</details>")
    out.append("</div></details>")
    return "\n".join(out)


CSS = (
    BRAND_CSS
    + r"""
:root{--desk:var(--lq-background);--paper:var(--lq-surface);--ink:var(--lq-foreground);
--muted:var(--lq-muted-foreground);--line:var(--lq-border);--blue:var(--lq-primary);
--blue-soft:var(--lq-accent);--green:var(--lq-success);--green-bg:var(--lq-success-surface);
--amber:var(--lq-attention);--amber-bg:var(--lq-attention-surface);--gray:var(--lq-surface-muted);
--focus:var(--lq-ring);--serif:var(--lq-font-serif);--sans:var(--lq-font-sans);--mono:var(--lq-font-mono)}
*{box-sizing:border-box}[hidden]{display:none!important}html{scroll-behavior:smooth}
body{margin:0;background:var(--desk);color:var(--ink);font:15px/1.5 var(--sans)}a{color:var(--blue);text-underline-offset:3px}
.skip{position:absolute;left:-9999px;top:4px;background:var(--paper);padding:6px 10px;z-index:20}.skip:focus{left:4px}
header,main,footer{max-width:1080px;margin:0 auto;padding-left:20px;padding-right:20px}header{padding-top:20px}
.machine-note{display:inline-block;background:var(--blue-soft);color:var(--blue);border:1px solid var(--blue);border-radius:3px;padding:3px 8px;font-size:12px;font-weight:500}
h1{font:500 28px/1.2 var(--serif);margin:7px 0 2px}.sub,.scope-note{color:var(--muted);font-size:13px}.sub{margin:0 0 12px}
.boundary{background:var(--paper);border:1px solid var(--line);border-left:4px solid var(--blue);padding:11px 14px;margin:12px 0}
.statline{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin:14px 0}.stat{background:var(--paper);border:1px solid var(--line);padding:9px 11px}.stat strong{display:block;font:500 22px var(--serif)}.stat span{font-size:12px;color:var(--muted)}
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.toolbar input{flex:1;min-width:240px}.toolbar input,.clear{background:var(--paper);color:var(--ink);border:1px solid var(--line);border-radius:4px;padding:8px 10px;font:14px var(--sans)}.clear{cursor:pointer}.filter-count{font-size:12px;color:var(--muted);margin-left:auto}
.tabs{display:flex;border-bottom:2px solid var(--ink);margin:10px 0 14px;overflow-x:auto}.tab{border:0;border-bottom:3px solid transparent;background:none;color:var(--muted);padding:8px 16px;font:500 16px var(--serif);cursor:pointer;white-space:nowrap;margin-bottom:-2px}.tab[aria-selected=true]{color:var(--ink);border-bottom-color:var(--blue)}
h2{font:500 22px var(--serif);margin:20px 0 2px}h3{font:500 18px var(--serif)}h4{font:500 15px var(--serif);margin:17px 0 8px}.lens-heading{font:500 12px var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:22px 0 8px}
.crosswalk-group{background:var(--paper);border:1px solid var(--line);border-radius:2px;margin:0 0 8px}.crosswalk-group>summary{display:flex;gap:16px;align-items:center;justify-content:space-between;cursor:pointer;padding:11px 13px}.summary-main{display:flex;flex-direction:column;min-width:0}.eyebrow{font:11px var(--mono);color:var(--muted);text-transform:uppercase;letter-spacing:.09em}.group-title{font:500 16px/1.3 var(--serif)}.memberline{font-size:12px;color:var(--muted)}
.pills,.receipt-line{display:flex;gap:5px;flex-wrap:wrap;align-items:center}.pill{border-radius:12px;padding:2px 8px;font-size:12px;white-space:nowrap}.pill.found{background:var(--green-bg);color:var(--green)}.pill.needs-review{background:var(--amber-bg);color:var(--amber)}.pill.not-found{background:var(--gray);color:var(--muted)}
.group-body{border-top:1px solid var(--line);padding:12px 14px 15px}.finding-card{border:1px solid var(--line);border-left:4px solid var(--line);padding:10px 12px;margin:8px 0;background:var(--paper)}.finding-card.found{border-left-color:var(--green)}.finding-card.needs-review{border-left-color:var(--amber)}.finding-head{display:flex;gap:12px;justify-content:space-between;align-items:flex-start}.finding-title{font-weight:500}.fileline,.cite,.receipt-line,.role{font:11.5px var(--mono);color:var(--muted)}.characterization{margin:6px 0}
blockquote{font:15.5px/1.5 var(--serif);margin:9px 0;padding:8px 12px;background:var(--gray);border-left:3px solid var(--blue)}.verification{color:var(--green)}.current{background:var(--blue-soft);color:var(--blue);border-radius:9px;padding:1px 7px}.source-access{margin:7px 0 0;font-size:13px}.negative-drawer{margin:13px 0 0;border-top:1px dashed var(--line);padding-top:8px}.negative-drawer>summary{cursor:pointer;font-weight:500}.issue-context{font:500 14px var(--serif);margin:12px 0 2px}.member-box,.plain-card{background:var(--gray);padding:10px 12px;margin:3px 0 12px}.plain-card{background:var(--paper);border:1px solid var(--line)}.role{margin-left:5px}
.review-copy-alert{background:var(--amber-bg);color:var(--amber);border:1px solid var(--amber);padding:12px 14px;margin:12px 0}.source-review-item{margin:14px 0;padding:14px;border:1px solid var(--line);background:var(--gray)}.source-review-item:target{outline:3px solid var(--focus);outline-offset:3px}.lq-review-copy h3{margin-bottom:6px}.lq-review-copy-receipt{font:11.5px/1.5 var(--mono);color:var(--muted);overflow-wrap:anywhere}.lq-review-copy-frame,.lq-review-copy-pdf{display:block;width:100%;min-height:430px;border:1px solid var(--line);background:var(--paper)}.lq-review-copy-image{display:block;max-width:100%;height:auto;margin:8px auto;border:1px solid var(--line)}.lq-needs-rendering{padding:12px 14px;background:var(--amber-bg);color:var(--amber);border-left:4px solid var(--amber)}.original-file{margin:9px 0 0;font-size:13px}
table{width:100%;border-collapse:collapse;background:var(--paper)}th,td{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:8px 10px}th{font:500 13px var(--serif)}.scroll{overflow-x:auto}.gap{border-left:4px solid var(--amber);padding:10px 12px;margin:8px 0;background:var(--paper);border-top:1px solid var(--line);border-right:1px solid var(--line);border-bottom:1px solid var(--line)}.gap p{margin:4px 0}.technical{font:12px/1.5 var(--mono);overflow-wrap:anywhere}.audit details{background:var(--paper);border:1px solid var(--line);padding:9px 12px;margin:8px 0}.audit summary{cursor:pointer;font-weight:500}.refusal{background:var(--amber-bg);color:var(--amber);border:1px solid var(--amber);padding:12px 14px;margin:12px 0}
footer{padding-top:12px;padding-bottom:40px;color:var(--muted);font-size:13px}button:focus-visible,input:focus-visible,summary:focus-visible,a:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
@media(max-width:760px){header,main,footer{padding-left:12px;padding-right:12px}.statline{grid-template-columns:repeat(2,minmax(0,1fr))}.crosswalk-group>summary,.finding-head{align-items:flex-start;flex-direction:column}.pills{justify-content:flex-start}.tabs{padding-bottom:1px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
"""
)

JS = (
    r"""
"use strict";
const tabs=[...document.querySelectorAll('.tab')],panels=[...document.querySelectorAll('[role=tabpanel]')];
const search=document.getElementById('search'),count=document.getElementById('filter-count');
function selectTab(name){tabs.forEach(tab=>{const on=tab.dataset.tab===name;tab.setAttribute('aria-selected',String(on));tab.tabIndex=on?0:-1});panels.forEach(panel=>panel.hidden=panel.dataset.panel!==name);search.disabled=!['issues','agreements'].includes(name);applySearch()}
function applySearch(){const panel=panels.find(row=>!row.hidden),q=search.value.trim().toLowerCase();if(!panel)return;const groups=[...panel.querySelectorAll('.crosswalk-group')];let shown=0;groups.forEach(group=>{const on=!q||group.dataset.search.includes(q);group.hidden=!on;if(on){shown+=1;if(q)group.open=true}});count.textContent=groups.length?`${shown} of ${groups.length} groups shown`:''}
tabs.forEach(tab=>tab.addEventListener('click',()=>selectTab(tab.dataset.tab)));document.querySelector('.tabs').addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight'].includes(event.key))return;const current=tabs.findIndex(tab=>tab.getAttribute('aria-selected')==='true'),next=(current+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].focus();selectTab(tabs[next].dataset.tab);event.preventDefault()});
search.addEventListener('input',applySearch);document.getElementById('clear-search').addEventListener('click',()=>{search.value='';applySearch();search.focus()});document.addEventListener('keydown',event=>{if(event.key==='/'&&document.activeElement!==search&&!search.disabled){event.preventDefault();search.focus()}});selectTab('issues');
document.addEventListener('click',event=>{const link=event.target.closest('[data-review-jump=true]');if(!link)return;const target=document.querySelector(link.getAttribute('href'));if(!target)return;selectTab(target.closest('#panel-scope')?'scope':'agreements');const group=target.closest('details.crosswalk-group');if(group){group.hidden=false;group.open=true}setTimeout(()=>target.focus(),0)});
"""
    + THEME_JS
)


def factual_errors(findings):
    errors = []
    for row in findings.get("findings", []):
        characterization = str(row.get("characterization") or "").lower()
        for phrase in PRESCRIPTIVE_PHRASES:
            if phrase in characterization:
                errors.append(
                    f"{row.get('finding_id', '<no id>')}: characterization contains prescriptive phrase {phrase!r}"
                )
    return errors


def source_path_errors(manifest, source_prefix):
    errors = []
    try:
        review_ui.safe_source_prefix(source_prefix)
    except ValueError as error:
        errors.append(str(error))
    for document in manifest.get("documents", []):
        try:
            review_ui.safe_source_path(document.get("path"))
        except ValueError:
            errors.append(
                f"manifest document {document.get('id', '<no id>')} has an unsafe source path"
            )
    return errors


def render_html(
    manifest,
    framework,
    findings,
    model,
    reconciliation,
    inputs,
    source_prefix,
    review_validation,
):
    counts = status_counts(model["rows"])
    controls = [
        row
        for row in manifest["documents"]
        if row.get("review_role", "substantive") == "runner-control"
    ]
    substantive = [row for row in manifest["documents"] if row not in controls]
    reviewed_units = [row for row in model["units"] if not row["parked"]]
    render_blockers = [
        row
        for row in review_validation.sidecar.get("documents", [])
        if row.get("status") != "ready"
    ]
    review_alert = ""
    if render_blockers:
        label = (
            "One file needs rendering"
            if len(render_blockers) == 1
            else f"{len(render_blockers)} files need rendering"
        )
        review_alert = (
            f'<div class="review-copy-alert" role="alert"><b>{esc(label)}.</b> '
            "The affected results are not ready for reliance until a verified "
            "in-page copy is available.</div>"
        )
    parts = [
        "<!doctype html>",
        f'<html lang="en" data-lq-review-ui="{CONTRACT_ID}"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>Diligence factual crosswalk</title>",
        f"<style>{CSS}</style></head><body>",
        '<a class="skip" href="#panel-issues">Skip to crosswalk</a>',
        masthead("Final factual review"),
        "<header>",
        '<span class="machine-note">Factual results · verify before relying</span>',
        f"<h1>{esc(manifest.get('root_label', 'Data room'))}</h1>",
        f'<p class="sub">{len(manifest["documents"])} files accounted for · '
        f"{len(reviewed_units)} agreement units reviewed · {len(model['issues'])} approved issues</p>",
        '<div class="boundary"><b>What this page does.</b> It maps the approved issue list to the supplied agreement units and shows checked evidence. It does not rank risk, recommend a transaction response, or decide legal effect.</div>',
        '<div class="statline">',
        f'<div class="stat"><strong>{len(manifest["documents"])}</strong><span>files in corpus</span></div>',
        f'<div class="stat"><strong>{len(reviewed_units)}</strong><span>agreement units reviewed</span></div>',
        f'<div class="stat"><strong>{counts["present"]}</strong><span>matches found</span></div>',
        f'<div class="stat"><strong>{counts["unresolved"]}</strong><span>results needing a decision</span></div>',
        f'<div class="stat"><strong>{counts["absent"]}</strong><span>nothing found in reviewed text</span></div>',
        "</div>",
        review_alert,
        '<div class="toolbar"><input id="search" type="search" aria-label="Search issues, agreements, and evidence" placeholder="Search issues, agreements, or quoted text… ( / )"><button class="clear" id="clear-search" type="button">Clear</button><span class="filter-count" id="filter-count" aria-live="polite"></span></div>',
        '<div class="tabs" role="tablist" aria-label="Crosswalk orientation">',
        '<button class="tab" type="button" role="tab" data-tab="issues" aria-selected="true" aria-controls="panel-issues">Issues</button>',
        '<button class="tab" type="button" role="tab" data-tab="agreements" aria-selected="false" aria-controls="panel-agreements" tabindex="-1">Agreements</button>',
        '<button class="tab" type="button" role="tab" data-tab="scope" aria-selected="false" aria-controls="panel-scope" tabindex="-1">Scope &amp; gaps</button>',
        '<button class="tab" type="button" role="tab" data-tab="audit" aria-selected="false" aria-controls="panel-audit" tabindex="-1">Audit</button>',
        "</div></header><main>",
        '<section id="panel-issues" role="tabpanel" data-panel="issues">',
        '<h2>Issues</h2><p class="scope-note">Open an issue to see where language was found, results needing a decision, and reviewed units where nothing was found.</p>',
    ]
    last_lens = None
    for issue in model["issues"]:
        if issue["lens_id"] != last_lens:
            parts.append(f'<div class="lens-heading">{esc(issue["lens_name"])}</div>')
            last_lens = issue["lens_id"]
        parts.append(render_issue_group(issue, model["by_issue"][issue["issue_id"]]))
    parts.append("</section>")
    parts.append(
        '<section id="panel-agreements" role="tabpanel" data-panel="agreements" hidden>'
    )
    parts.append(
        '<h2>Agreements</h2><p class="scope-note">Open an agreement unit to see every approved issue tested against it.</p>'
    )
    for unit in model["units"]:
        parts.append(
            render_unit_group(
                unit,
                model["by_unit"][unit["unit_id"]],
                source_prefix,
                review_validation,
            )
        )
    parts.append("</section>")

    parts.append('<section id="panel-scope" role="tabpanel" data-panel="scope" hidden>')
    parts.append("<h2>Scope and gaps</h2>")
    parts.append(
        f'<div class="plain-card"><b>Corpus accounting.</b> {len(controls)} runner-control input(s) '
        f"governed the scope or issue framework but were not substantive sample units. "
        f"{len(substantive)} substantive source file(s) formed {len(model['units'])} agreement unit(s); "
        f"{reconciliation['totals']['parked']} unit(s) were parked.</div>"
    )
    parts.append(
        '<div class="scroll"><table><thead><tr><th>File</th><th>Run role</th><th>Readability</th></tr></thead><tbody>'
    )
    for document in manifest["documents"]:
        role = (
            "Runner-control input"
            if document in controls
            else "Substantive agreement material"
        )
        parts.append(
            f'<tr><td><a href="#{esc(document_anchor(document))}" data-review-jump="true">'
            f"Review {esc(document['path'])}</a></td><td>{role}</td>"
            f"<td>{esc(document.get('readability'))}</td></tr>"
        )
    parts.append("</tbody></table></div>")
    if controls:
        parts.append("<h3>Review instructions and control inputs</h3>")
        for document in sorted(controls, key=lambda row: (row["path"], row["id"])):
            parts.append(
                render_review_document(
                    document,
                    source_prefix,
                    review_validation,
                    title=pretty_filename(document["path"]),
                )
            )
    parts.append(
        f"<h3>Missing, unreadable, or duplicate materials · {len(model['gaps'])}</h3>"
    )
    for gap in model["gaps"]:
        parts.append(
            f'<article class="gap"><b>{esc(str(gap.get("type", "gap")).replace("-", " ").title())}</b>'
            f'<p>{esc(gap.get("detail"))}</p><p class="cite">Evidence: {esc(gap.get("evidence"))}</p></article>'
        )
    if not model["gaps"]:
        parts.append('<p class="scope-note">No gap entries were recorded.</p>')
    parts.append(
        '<div class="plain-card"><b>Meaning of “Not found.”</b> The approved issue test found no responsive language in the supplied visible text for that reviewed agreement unit. It does not establish portfolio-wide absence and does not cover missing agreements or materials.</div>'
    )
    parts.append("</section>")

    parts.append(
        '<section id="panel-audit" role="tabpanel" data-panel="audit" class="audit" hidden>'
    )
    parts.append(
        '<h2>Audit</h2><p class="scope-note">Technical provenance remains available without dominating the legal review.</p>'
    )
    parts.append(
        f'<div class="plain-card technical">Framework version: {esc(framework.get("framework_version"))}<br>'
        f"Review plan: {esc(findings.get('review_plan_id') or 'not recorded')}<br>"
        f"Result equation: {counts['present']} found + {counts['absent']} not found + "
        f"{counts['unresolved']} needs a decision = {len(model['rows'])} results<br>"
        f"Expected matrix: {len(model['issues'])} issues × {len(reviewed_units)} reviewed agreement units "
        f"= {len(model['issues']) * len(reviewed_units)} results<br>"
        f"Review-copy receipt: {esc(review_validation.sidecar.get('digest'))}<br>"
        f"Review-copy status: {esc(review_validation.sidecar.get('status'))}</div>"
    )
    parts.append('<details><summary>Input hashes</summary><div class="technical">')
    for record in inputs:
        parts.append(f"{esc(record['label'])} · SHA-256 {esc(record['sha256'])}<br>")
    parts.append("</div></details>")
    parts.append(
        "<details><summary>Assurance boundary</summary><p>The matrix is complete for the approved framework and reviewable substantive units. Present results carry separate quote and checker receipts. Missing, unreadable, runner-control, parked, and needs-a-decision lanes remain visible. The page itself performs no new substantive review.</p></details>"
    )
    parts.append(
        "<details><summary>Fields intentionally not used</summary><p>Materiality bands and ranking fields, if present in the source ledger, do not affect grouping, visibility, checker selection, or ordering on this factual surface.</p></details>"
    )
    parts.append("</section></main>")
    parts.append(
        "<footer>This is a factual review surface. Analysis, prioritization, or transaction advice requires a separate instruction.</footer>"
    )
    parts.append(f"<script>{JS}</script></body></html>")
    return "\n".join(parts) + "\n"


def refusal_html(label: str, errors: list[str]) -> str:
    items = "".join(f"<li>{esc(error)}</li>" for error in errors)
    return (
        f'<!doctype html><html lang="en" data-lq-review-ui="{CONTRACT_ID}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style>'
        f"<title>Diligence crosswalk refused</title></head><body>{masthead('Review paused')}"
        f"<main><header><h1>{esc(label)}</h1>"
        '<div class="refusal" role="alert"><b>Crosswalk not issued.</b> The factual coverage or assurance '
        f"checks failed:<ul>{items}</ul></div></header></main><script>{THEME_JS}</script></body></html>\n"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Render the factual diligence crosswalk."
    )
    parser.add_argument("--framework", required=True, type=Path)
    parser.add_argument("--findings", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--families", required=True, type=Path)
    parser.add_argument("--gaps", required=True, type=Path)
    parser.add_argument("--source-prefix", default="")
    parser.add_argument("--review-copies", required=True, type=Path)
    parser.add_argument("--document-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    paths = (
        ("Manifest", args.manifest, ("documents", "counts")),
        ("Confirmed family map", args.families, ("families",)),
        ("Approved framework", args.framework, ("framework_version", "lenses")),
        ("Checked findings ledger", args.findings, ("findings",)),
        ("Gap report", args.gaps, ("entries",)),
    )
    try:
        loaded = [read_json(path, label, required) for label, path, required in paths]
    except ValueError as exc:
        print(f"render_crosswalk: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    manifest, families, framework, findings, gaps = loaded
    inputs = [{"label": label, "sha256": sha256(path)} for label, path, _ in paths]
    if args.review_copies.is_file():
        inputs.append(
            {"label": "Review-copy sidecar", "sha256": sha256(args.review_copies)}
        )
    reconciliation = reconcile_counts.reconcile(manifest, findings, framework, families)
    errors = (
        list(reconciliation["errors"])
        + factual_errors(findings)
        + source_path_errors(manifest, args.source_prefix)
    )
    review_validation = review_copies.revalidate_review_copies(
        args.review_copies, args.manifest, args.document_root
    )
    if args.review_copies.parent.resolve() != args.out.parent.resolve():
        errors.append("review-copies sidecar and HTML output must share a directory")
    if not review_validation.integrity_ok:
        errors.extend(
            f"review-copy validation failed: {error}"
            for error in review_validation.errors
        )
    if not reconciliation["ok"]:
        errors.extend(reconciliation["lines"])
    errors = sorted(set(errors))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    if errors:
        output = refusal_html(manifest.get("root_label", "Data room"), errors)
    else:
        model = build_model(
            manifest, families, framework, findings, gaps, reconciliation
        )
        output = render_html(
            manifest,
            framework,
            findings,
            model,
            reconciliation,
            inputs,
            args.source_prefix,
            review_validation,
        )
    with args.out.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(output)
    counts = Counter(row.get("status") for row in findings.get("findings", []))
    receipt = {
        "artifact": "diligence-factual-crosswalk-receipt",
        "version": 1,
        "status": "fail" if errors or not review_validation.ready else "pass",
        "errors": errors,
        "inputs": inputs,
        "output": {"bytes": args.out.stat().st_size, "sha256": sha256(args.out)},
        "counts": {
            **reconciliation["totals"],
            "found": counts["present"],
            "not_found": counts["absent"],
            "needs_review": counts["unresolved"],
        },
        "checks": {
            "complete_issue_unit_cross_product": reconciliation["ok"],
            "runner_control_excluded_from_substantive_units": not any(
                "runner-control" in error for error in reconciliation["errors"]
            ),
            "present_results_have_quote_locator_and_two_receipts": not any(
                "receipt" in error or "empty quote" in error or "empty section" in error
                for error in reconciliation["errors"]
            ),
            "factual_characterizations": not factual_errors(findings),
            "review_copy_integrity": review_validation.integrity_ok,
            "review_copies_ready": review_validation.ready,
        },
    }
    with args.receipt.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {"status": receipt["status"], "counts": receipt["counts"]},
            indent=2,
            sort_keys=True,
        )
    )
    raise SystemExit(1 if errors or not review_validation.ready else 0)


if __name__ == "__main__":
    main()
