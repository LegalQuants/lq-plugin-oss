"""Deterministic renderers for definition-check ledgers."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .annotated_html import write_annotated_html
from .dashboard import dashboard_eligible, write_dashboard
from .models import Ledger
from .projection import project_reviewed_inventory


def render_json(ledger: Ledger, indent: int = 2) -> str:
    return (
        json.dumps(ledger.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)
        + "\n"
    )


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "<br>")
        .replace("\n", "<br>")
    )


def _location(location: dict[str, Any]) -> str:
    return f"{location.get('part', '')} / {location.get('block_id', '')} ({location.get('char_start', '')}-{location.get('char_end', '')})"


def render_markdown(ledger: Ledger) -> str:
    data = ledger.to_dict()
    source = data["source"]
    coverage = source.get("coverage") or {}
    lines = [
        "# Definition check",
        "",
        "**Developer artifact:** This Markdown report is a compact diagnostic fallback. A completed review produces the lawyer-facing `definition-check.html`; `definition-check.json` remains the machine-readable record used by authorized tools and agents.",
        "",
        "**Parser scope:** document-body and table-cell paragraphs are checked. Headers, footers, footnotes, endnotes, comments, embedded objects, macros, and tracked-change presentation are not checked by the packaged parser.",
        "",
        f"- **Status:** {_cell(data['run_status'])}",
        f"- **Capability:** {_cell(data['capability_profile'])}",
        f"- **Source:** {_cell(source.get('name'))}",
        f"- **Coverage:** {_cell(json.dumps(coverage, ensure_ascii=False, sort_keys=True))}",
        "",
        "## Limitations and methods not run",
        "",
    ]
    limitations = data.get("limitations") or []
    lines.extend(f"- {_cell(item)}" for item in limitations)
    if not limitations:
        lines.append("- None recorded.")
    skipped = data.get("methods_not_run") or []
    if skipped:
        lines.extend(
            ["", "### Methods not run", "", "| Method | Reason |", "| --- | --- |"]
        )
        lines.extend(
            f"| {_cell(item.get('method', ''))} | {_cell(item.get('reason', ''))} |"
            for item in skipped
        )
    lines.extend(["", "## Findings", ""])
    usages, findings = project_reviewed_inventory(data)
    if findings:
        lines.extend(
            [
                "| Rule | Severity | Term | Message | Evidence |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for finding in findings:
            evidence = (
                "; ".join(_location(item) for item in finding.get("evidence", []))
                or "Not recorded"
            )
            lines.append(
                f"| {_cell(finding.get('rule_id', ''))} | {_cell(finding.get('severity', ''))} | {_cell(finding.get('normalized_term', ''))} | {_cell(finding.get('message', ''))} | {_cell(evidence)} |"
            )
    else:
        lines.append("No findings recorded.")
    lines.extend(
        [
            "",
            "## Inventories",
            "",
            f"- **Definitions:** {len(data.get('definitions', []))}",
            f"- **Term variants:** {len(data.get('term_variants', []))}",
            f"- **Reviewed usages:** {len(usages)}",
        ]
    )
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def write_outputs(
    ledger: Ledger,
    output_dir: str | Path,
    *,
    include_internal_traces: bool = False,
    include_qa_annotated_document: bool = False,
) -> tuple[Path, ...]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "definition-check.json"
    markdown_path = directory / "definition-check.md"
    html_path = directory / "definition-check.html"
    annotated_document_path = directory / "annotated-document.html"
    existing = [
        path.name
        for path in (
            json_path,
            markdown_path,
            html_path,
            *([annotated_document_path] if include_qa_annotated_document else []),
        )
        if path.exists()
    ]
    if existing:
        raise FileExistsError(
            f"refusing to overwrite existing definition-check artifacts: {existing}"
        )
    _atomic_write(json_path, render_json(ledger))
    _atomic_write(markdown_path, render_markdown(ledger))
    dashboard_written = dashboard_eligible(ledger)
    if dashboard_written:
        write_dashboard(ledger, html_path)
    if include_qa_annotated_document:
        write_annotated_html(ledger, annotated_document_path)
    paths = [json_path, markdown_path]
    if dashboard_written:
        paths.append(html_path)
    if include_qa_annotated_document:
        paths.append(annotated_document_path)
    return tuple(paths)


def write_review_artifacts(
    work_dir: str | Path,
    *,
    review_envelopes: list[dict[str, Any]] | None = None,
    occurrence_review_envelopes: list[dict[str, Any]] | None = None,
    reference_review_envelopes: list[dict[str, Any]] | None = None,
) -> tuple[Path, Path, Path]:
    """Write internal review envelopes into the run workspace."""

    directory = Path(work_dir)
    directory.mkdir(parents=True, exist_ok=True)
    review_path = directory / "semantic-review-envelopes.json"
    occurrence_review_path = directory / "occurrence-review-envelopes.json"
    reference_review_path = directory / "reference-review-envelopes.json"
    _atomic_write(
        review_path,
        json.dumps(
            {"envelopes": review_envelopes or []},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    _atomic_write(
        occurrence_review_path,
        json.dumps(
            {"envelopes": occurrence_review_envelopes or []},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    _atomic_write(
        reference_review_path,
        json.dumps(
            {"envelopes": reference_review_envelopes or []},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return review_path, occurrence_review_path, reference_review_path
