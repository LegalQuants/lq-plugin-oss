"""Wave 2: the build plan (Gate 2), the versioned package, and the change report.

Everything here follows `references/assembly-rules.md`. Only the standard
library is loaded when this module loads; pypdf is brought in lazily for the
combined PDF, while `soffice` and Poppler are probed with `shutil.which`, and
each absence degrades exactly as the capability ladder says — never silently.

    plan(index, selection_plan, manifest, overview, *, include_qualified=False,
         volume_pages=None, prior_folder=None, package_parent) -> dict
    build(plan, *, root, audit_dir, package_parent, as_of)
        -> (receipt, conversion_log, change_report_md | None)
    change_report(prior_dir, new_dir) -> str

Sources are read and copied; the only writes land in the new package folder,
staged as `<folder>.partial` and renamed once complete. The closing folder is
hashed before and after; a difference raises `SourceMutated` and the package
is not kept.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import html
import importlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .models import (
    ITEM_STATUSES,
    RECEIPT_STATUSES,
    SCHEMA_VERSION,
    SELECTABLE_STATUSES,
    Receipt,
)

PACKAGE_RE = re.compile(r"^closing-bible-v(\d{3,})$")
STAGING_SUFFIX = ".partial"
QUALIFIED_STATUSES = frozenset({"unsigned", "undated", "incomplete"})
NEVER_INCLUDED = frozenset(
    {"not-required", "missing", "unreadable", "version-conflict"}
)
WORD_EXTENSIONS = frozenset({"docx", "doc", "rtf", "odt"})
MIN_VOLUME_PAGES = 50
# Audit outputs the package carries forward, byte for byte.
CARRIED = (
    "source-manifest.json",
    "families.json",
    "selection-plan.json",
    "execution-overview.json",
    "exceptions.md",
)
PLAN_KEYS = {
    "schema_version",
    "corpus_id",
    "index_sha256",
    "approved",
    "include_qualified",
    "package",
    "entries",
    "excluded",
    "volume_pages",
}
ENTRY_KEYS = {
    "order",
    "item_id",
    "title",
    "status",
    "qualification",
    "source_id",
    "source_path",
    "output_name",
    "conversion",
    "execution_pages",
}
INDEX_PDF = "closing-bible-index.pdf"
COMBINED_PDF = "closing-bible.pdf"

# Front-matter typesetting: Helvetica 9pt, one text column.
LINES_PER_PAGE = 58
LINE_CHARS = 105


class SourceMutated(RuntimeError):
    """The closing folder changed during the run (rule 6). The package is dropped."""


# ------------------------------------------------------------------ helpers


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _require(cond: bool, reason: str) -> None:
    if not cond:
        raise ValueError(reason)


def index_sha256(index: dict[str, Any]) -> str:
    """The hash `build` checks: sha256 of the index in the form the script
    writes it (sorted keys, two-space indent, trailing newline), so the bytes
    reconcile writes are the bytes hashed and an edited index is caught."""

    return hashlib.sha256(_dump(index).encode("utf-8")).hexdigest()


def document_id(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def hash_tree(root: Path) -> dict[str, tuple[str, int, int]]:
    """Relative path → (sha256, size, mtime_ns) for every file under root."""

    out: dict[str, tuple[str, int, int]] = {}
    for path in sorted(p for p in Path(root).rglob("*") if p.is_file()):
        stat = path.stat()
        out[path.relative_to(root).as_posix()] = (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            stat.st_size,
            stat.st_mtime_ns,
        )
    return out


def next_version(package_parent: Path) -> int:
    """One more than the highest `closing-bible-vNNN` sibling; 1 when none."""

    highest = 0
    if package_parent.is_dir():
        for entry in package_parent.iterdir():
            match = PACKAGE_RE.match(entry.name)
            if match and entry.is_dir():
                highest = max(highest, int(match.group(1)))
    return highest + 1


def package_folder(version: int) -> str:
    return f"closing-bible-v{version:03d}"


def safe_title(title: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:120] or "Untitled"


def find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
        Path("/opt/homebrew/bin/soffice"),
        Path("/usr/bin/soffice"),
        Path("/usr/lib/libreoffice/program/soffice"),
    ):
        if candidate.exists():
            return str(candidate)
    return None


def _import_pypdf() -> Any | None:
    try:
        return importlib.import_module("pypdf")
    except ImportError:
        return None


def _stdlib_page_count(path: Path) -> int | None:
    """The page tree's own `/Count`, the largest `/Type /Pages` node wins."""

    try:
        data = path.read_bytes()
    except OSError:
        return None
    counts = [
        int(m.group(1))
        for m in re.finditer(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", data, re.S)
    ]
    counts += [
        int(m.group(1))
        for m in re.finditer(rb"/Count\s+(\d+)[^>]*?/Type\s*/Pages\b", data, re.S)
    ]
    return max(counts) if counts else None


def pdf_page_count(path: Path) -> int | None:
    """pdfinfo when present; else the page tree (stdlib). None when unknown."""

    if shutil.which("pdfinfo"):
        try:
            proc = subprocess.run(
                ["pdfinfo", str(path)],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            proc = None
        if proc is not None and proc.returncode == 0:
            match = re.search(r"^Pages:\s+(\d+)\s*$", proc.stdout, re.M)
            if match:
                return int(match.group(1))
    return _stdlib_page_count(path)


# --------------------------------------------------------------------- plan


def _objects(value: Any, where: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(i, dict) for i in value):
        raise ValueError(f"{where} must be a list of objects")
    return list(value)


def _items(index: dict[str, Any]) -> list[dict[str, Any]]:
    items = _objects(index.get("items"), "closing-index.json: items")
    return sorted(items, key=lambda i: (int(i.get("order", 0)), str(i.get("item_id"))))


def _overview_docs(overview: dict[str, Any]) -> dict[str, dict[str, Any]]:
    docs = _objects(overview.get("documents"), "execution-overview.json: documents")
    return {d["item_id"]: d for d in docs if isinstance(d.get("item_id"), str)}


def _manifest_docs(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """First row per id in the manifest's (id, path) order: the canonical path."""

    docs = _objects(manifest.get("documents"), "source-manifest.json: documents")
    by_id: dict[str, dict[str, Any]] = {}
    for doc in sorted(docs, key=lambda d: (str(d.get("id")), str(d.get("path")))):
        by_id.setdefault(doc["id"], doc)
    return by_id


def _prior_name(prior_folder: str | Path | None, package_parent: Path) -> str | None:
    if prior_folder is None:
        return None
    prior = Path(prior_folder)
    if prior.parent != Path(".") and prior.parent != Path(""):
        _require(
            prior.resolve().parent == package_parent.resolve(),
            f"prior package {prior_folder} is not a sibling under {package_parent}",
        )
    name = prior.name
    _require(
        bool(PACKAGE_RE.match(name)),
        f"prior package name is not closing-bible-vNNN: {name}",
    )
    _require(
        (package_parent / name / "closing-index.json").is_file(),
        f"prior package {name} has no closing-index.json under {package_parent}",
    )
    return name


def _exclusion(item: dict[str, Any], include_qualified: bool) -> dict[str, Any] | None:
    """The Gate 2 exclusion row for an index item, or None when it enters."""

    status = item.get("status")
    if status in NEVER_INCLUDED or (
        status in QUALIFIED_STATUSES and not include_qualified
    ):
        return {
            "item_id": item.get("item_id"),
            "title": item.get("title"),
            "status": status,
            "reason": "qualified-not-included"
            if status in QUALIFIED_STATUSES
            else status,
        }
    return None


def check_exclusions(plan_doc: dict[str, Any], index: dict[str, Any]) -> None:
    """Gate 2 shows every item that will not enter the bible. The lawyer may
    exclude more at the gate; the plan may never show fewer than the index
    implies, or describe one with the wrong reason."""

    required = {}
    for item in _items(index):
        row = _exclusion(item, plan_doc["include_qualified"])
        if row is not None:
            required[row["item_id"]] = row
    listed = {x.get("item_id"): x for x in plan_doc["excluded"] if isinstance(x, dict)}
    absent = [item_id for item_id in required if item_id not in listed]
    _require(
        not absent,
        "refused: build-plan.json's exclusion list omits "
        + ", ".join(f"{i} ({required[i]['status']})" for i in absent)
        + "; Gate 2 must show every item that will not enter the bible — re-run plan",
    )
    for item_id, row in required.items():
        shown = listed[item_id]
        _require(
            shown.get("status") == row["status"]
            and shown.get("reason") == row["reason"],
            f"refused: build-plan.json describes {item_id} as "
            f"{shown.get('status')!r}/{shown.get('reason')!r}; the approved index says "
            f"{row['status']!r}/{row['reason']!r} — re-run plan",
        )


def plan(
    index: dict[str, Any],
    selection_plan: dict[str, Any],
    manifest: dict[str, Any],
    overview: dict[str, Any],
    *,
    include_qualified: bool = False,
    volume_pages: int | None = None,
    prior_folder: str | Path | None = None,
    package_parent: Path,
) -> dict[str, Any]:
    """build-plan.json from an APPROVED index (assembly-rules.md, Gate 2)."""

    package_parent = Path(package_parent)
    _require(
        index.get("approved") is True,
        "refused: closing-index.json is not approved; nothing is planned from an "
        "index the lawyer has not confirmed at Gate 1",
    )
    corpus_id = index.get("corpus_id")
    _require(
        isinstance(corpus_id, str) and bool(corpus_id),
        "closing-index.json: corpus_id missing",
    )
    _require(
        manifest.get("corpus_id") == corpus_id,
        f"refused: the index is for corpus {corpus_id!r} but the manifest is "
        f"{manifest.get('corpus_id')!r}: a different folder",
    )
    _require(
        selection_plan.get("corpus_id") == corpus_id,
        "refused: selection-plan.json is for another corpus",
    )
    _require(
        overview.get("corpus_id") == corpus_id,
        "refused: execution-overview.json is for another corpus",
    )
    if volume_pages is not None:
        _require(
            isinstance(volume_pages, int)
            and not isinstance(volume_pages, bool)
            and volume_pages >= MIN_VOLUME_PAGES,
            f"volume_pages must be an integer of {MIN_VOLUME_PAGES} or more",
        )
    prior = _prior_name(prior_folder, package_parent)
    version = next_version(package_parent)
    if prior is not None:
        prior_version = int(prior.rsplit("v", 1)[1])
        _require(
            prior_version < version,
            f"prior package {prior} is not below the next version {version}",
        )

    docs = _manifest_docs(manifest)
    overview_docs = _overview_docs(overview)
    plan_families = _objects(
        selection_plan.get("families"), "selection-plan.json: families"
    )
    selected_by_item = {
        f.get("item_id"): f.get("selected_id")
        for f in plan_families
        if isinstance(f.get("item_id"), str)
    }
    soffice = find_soffice()

    entries: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _items(index):
        item_id = item.get("item_id")
        status = item.get("status")
        title = item.get("title")
        if not isinstance(item_id, str) or item_id in seen:
            raise ValueError(f"closing-index.json: bad or repeated item_id {item_id!r}")
        seen.add(item_id)
        _require(
            status in ITEM_STATUSES,
            f"{item_id}: '{status}' is not an index item status",
        )
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"{item_id}: title missing")
        row = _exclusion(item, include_qualified)
        if row is not None:
            excluded.append(row)
            continue
        _require(
            status in SELECTABLE_STATUSES, f"{item_id}: cannot plan status {status}"
        )
        source_id = item.get("selected_id")
        if not isinstance(source_id, str):
            raise ValueError(f"{item_id}: {status} has no selected_id")
        if item_id in selected_by_item:
            _require(
                selected_by_item[item_id] == source_id,
                f"{item_id}: selection-plan.json selects {selected_by_item[item_id]!r} but the "
                f"index says {source_id!r}; re-run reconcile",
            )
        doc = docs.get(source_id)
        if doc is None:
            raise ValueError(
                f"{item_id}: selected source {source_id} is not in the manifest"
            )
        ext = str(doc.get("ext") or "").lower()
        order = int(item.get("order", 0))
        _require(order >= 1, f"{item_id}: order must be 1 or more")
        if ext == "pdf":
            conversion = "none"
        elif ext in WORD_EXTENSIONS and soffice:
            conversion = "docx-to-pdf"
        else:
            conversion = "unrenderable"
        pages: list[int] = []
        for ref in overview_docs.get(item_id, {}).get("signature_pages", []) or []:
            if (
                isinstance(ref, dict)
                and ref.get("document_id") == source_id
                and isinstance(ref.get("page"), int)
                and ref["page"] >= 1
            ):
                pages.append(ref["page"])
        qualification = item.get("qualification") or ""
        entries.append(
            {
                "order": order,
                "item_id": item_id,
                "title": title,
                "status": status,
                "qualification": qualification,
                "source_id": source_id,
                "source_path": doc["path"],
                "output_name": f"{order:03d} - {safe_title(title)}"
                + (f".{ext}" if ext else ""),
                "conversion": conversion,
                "execution_pages": sorted(set(pages)),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_id": corpus_id,
        "index_sha256": index_sha256(index),
        "approved": False,
        "include_qualified": bool(include_qualified),
        "package": {
            "version": version,
            "folder": package_folder(version),
            "prior_folder": prior,
        },
        "entries": entries,
        "excluded": excluded,
        "volume_pages": volume_pages,
    }


# ------------------------------------------------------ front-matter pages


def _pdf_escape(text: str) -> bytes:
    raw = text.encode("latin-1", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def text_pdf(pages: list[list[str]]) -> bytes:
    """A minimal PDF, one text column per page in Helvetica. The only pages
    this skill authors (assembly-rules.md rule 2)."""

    _require(bool(pages), "a PDF needs at least one page")
    objects: dict[int, bytes] = {}
    first_page = 4
    kids = []
    for i, lines in enumerate(pages):
        page_num = first_page + 2 * i
        content_num = page_num + 1
        kids.append(f"{page_num} 0 R")
        objects[page_num] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_num} 0 R >>"
        ).encode("ascii")
        ops = [b"BT", b"/F1 9 Tf", b"50 760 Td", b"12 TL"]
        for line in lines:
            ops.append(b"(" + _pdf_escape(line[:LINE_CHARS]) + b") Tj T*")
        ops.append(b"ET")
        stream = b"\n".join(ops) + b"\n"
        objects[content_num] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = (
        f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>"
    ).encode("ascii")
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode("ascii") + objects[num] + b"\nendobj\n"
    size = max(objects) + 1
    xref_at = len(out)
    out += f"xref\n0 {size}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for num in range(1, size):
        out += f"{offsets[num]:010d} 00000 n \n".encode("ascii")
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\n".encode("ascii")
    out += f"startxref\n{xref_at}\n%%EOF\n".encode("ascii")
    return bytes(out)


def _wrap(line: str) -> list[str]:
    """Wrap at LINE_CHARS with a hanging indent; nothing is truncated."""

    indent = " " * (len(line) - len(line.lstrip(" ")) + 6)
    words = line.split(" ")
    out: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) > LINE_CHARS and current:
            out.append(current)
            current = indent + word
        else:
            current = candidate
    out.append(current)
    return out


def _paginate(lines: list[str]) -> list[list[str]]:
    wrapped = [w for line in lines for w in _wrap(line)]
    pages = [
        wrapped[i : i + LINES_PER_PAGE] for i in range(0, len(wrapped), LINES_PER_PAGE)
    ]
    return pages or [[""]]


def _index_lines(
    index: dict[str, Any],
    placements: dict[str, dict[str, Any]],
    folder: str,
    as_of: str,
) -> list[str]:
    lines = [
        f"CLOSING INDEX - {index.get('matter') or 'closing set'}",
        f"{folder} · as of {as_of} · execution status is apparent status on inspected evidence, never a certification",
        "",
    ]
    for item in _items(index):
        placed = placements.get(item["item_id"])
        where = "not in the combined PDF"
        if placed is not None:
            where = f"p. {placed['start_page']}"
            if placed.get("volume"):
                where = f"vol. {placed['volume']:02d}, " + where
        parties = ", ".join(item.get("parties") or []) or "-"
        lines.append(
            f"{int(item.get('order', 0)):03d}  {item['title']}  [{item['status']}]  {where}"
        )
        lines.append(
            f"      parties: {parties} · date: {item.get('document_date') or '-'} · execution: "
            f"{item.get('execution', {}).get('apparent_status', '-')} · source: {item.get('selected_id') or '-'}"
        )
        if item.get("qualification"):
            lines.append(f"      qualified: {item['qualification']}")
    return lines


def _overview_lines(overview: dict[str, Any]) -> list[str]:
    lines = [
        "EXECUTION OVERVIEW",
        "apparent status per document; a sigpack ledger, where cited, is the source for block-level status",
        "",
    ]
    sig = overview.get("sigpack") or {}
    lines.append(
        f"sigpack ledger supplied: {sig.get('ledger_supplied')} · current: {sig.get('ledger_current')} · closing date per ledger: {sig.get('closing_date') or '-'}"
    )
    lines.append("")
    for doc in overview.get("documents") or []:
        lines.append(
            f"{doc.get('item_id')}  {doc.get('title')}  expected: {doc.get('execution_expected')} · "
            f"{doc.get('apparent_status')} ({doc.get('evidence_source')}) · date: {doc.get('document_date') or '-'}"
            + (" · dating unresolved" if doc.get("dating_unresolved") else "")
        )
        if doc.get("qualification"):
            lines.append(f"      qualified: {doc['qualification']}")
        for block in doc.get("blocks") or []:
            lines.append(
                f"      block {block.get('party')}: {block.get('status')} ({block.get('ledger_page_id') or 'no page id'})"
            )
        pages = ", ".join(
            str(p.get("page"))
            for p in doc.get("signature_pages") or []
            if p.get("page")
        )
        if pages:
            lines.append(f"      signature pages: {pages}")
        for exc in doc.get("exceptions") or []:
            lines.append(f"      exception: {exc}")
    return lines


def _master_index_lines(
    index: dict[str, Any], placements: dict[str, dict[str, Any]], folder: str
) -> list[str]:
    lines = [
        f"CLOSING BIBLE - MASTER INDEX ({folder})",
        "every item, its volume and its starting page",
        "",
    ]
    for item in _items(index):
        placed = placements.get(item["item_id"])
        where = (
            f"volume {placed['volume']:02d}, p. {placed['start_page']}"
            if placed
            else f"not in the volumes ({item['status']})"
        )
        lines.append(f"{int(item.get('order', 0)):03d}  {item['title']}  {where}")
    return lines


# --------------------------------------------------------------------- HTML


def _h(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _html_page(title: str, body: str) -> str:
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{_h(title)}</title>\n"
        "<style>body{font-family:Helvetica,Arial,sans-serif;font-size:13px;margin:2em}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #999;padding:4px 6px;"
        "text-align:left;vertical-align:top}th{background:#eee}</style>\n</head>\n<body>\n"
        f"{body}\n</body>\n</html>\n"
    )


def index_html(
    index: dict[str, Any],
    placements: dict[str, dict[str, Any]],
    docs: dict[str, dict[str, Any]],
    folder: str,
    as_of: str,
) -> str:
    rows = []
    for item in _items(index):
        placed = placements.get(item["item_id"])
        start = "-"
        if placed is not None:
            start = str(placed["start_page"])
            if placed.get("volume"):
                start = f"vol. {placed['volume']:02d}, p. {placed['start_page']}"
        source = "-"
        if item.get("selected_id"):
            doc = docs.get(item["selected_id"], {})
            source = (
                f"{_h(doc.get('path', '?'))}<br><code>{_h(item['selected_id'])}</code>"
            )
        execution = _h(item.get("execution", {}).get("apparent_status", "-"))
        if item.get("qualification"):
            execution += f"<br><em>{_h(item['qualification'])}</em>"
        rows.append(
            "<tr>"
            f"<td>{int(item.get('order', 0)):03d}</td>"
            f"<td>{_h(item['title'])}<br><small>{_h(item['item_id'])}</small></td>"
            f"<td>{_h(', '.join(item.get('parties') or []) or '-')}</td>"
            f"<td>{_h(item.get('document_date') or '-')}</td>"
            f"<td>{_h(item['status'])}<br>{execution}</td>"
            f"<td>{source}</td>"
            f"<td>{_h(start)}</td>"
            "</tr>"
        )
    body = (
        f"<h1>Closing index — {_h(index.get('matter') or 'closing set')}</h1>\n"
        f"<p>{_h(folder)} · as of {_h(as_of)} · execution status is the apparent status on inspected "
        "evidence; nothing here certifies execution, authority or delivery.</p>\n"
        "<table>\n<tr><th>No.</th><th>Title</th><th>Parties</th><th>Document date</th>"
        "<th>Execution status</th><th>Source</th><th>Starting page</th></tr>\n"
        + "\n".join(rows)
        + "\n</table>"
    )
    return _html_page(f"Closing index — {index.get('matter') or 'closing set'}", body)


def overview_html(overview: dict[str, Any], folder: str) -> str:
    sig = overview.get("sigpack") or {}
    rows = []
    for doc in overview.get("documents") or []:
        blocks = (
            "<br>".join(
                f"{_h(b.get('party'))}: {_h(b.get('status'))} ({_h(b.get('ledger_page_id') or 'no page id')})"
                for b in doc.get("blocks") or []
            )
            or "-"
        )
        pages = (
            ", ".join(
                str(p.get("page"))
                for p in doc.get("signature_pages") or []
                if p.get("page")
            )
            or "-"
        )
        exceptions = "<br>".join(_h(e) for e in doc.get("exceptions") or []) or "-"
        date = _h(doc.get("document_date") or "-")
        if doc.get("dating_unresolved"):
            date += "<br><em>dating unresolved</em>"
        rows.append(
            "<tr>"
            f"<td>{_h(doc.get('item_id'))}</td><td>{_h(doc.get('title'))}</td>"
            f"<td>{'yes' if doc.get('execution_expected') else 'no'}</td>"
            f"<td>{_h(doc.get('evidence_source'))}</td>"
            f"<td>{_h(doc.get('apparent_status'))}"
            + (
                f"<br><em>{_h(doc['qualification'])}</em>"
                if doc.get("qualification")
                else ""
            )
            + f"</td><td>{blocks}</td><td>{date}</td><td>{pages}</td><td>{exceptions}</td></tr>"
        )
    body = (
        "<h1>Execution overview</h1>\n"
        f"<p>{_h(folder)} · sigpack ledger supplied: {_h(sig.get('ledger_supplied'))} · current: "
        f"{_h(sig.get('ledger_current'))} · closing date per ledger: {_h(sig.get('closing_date') or '-')}. "
        "Apparent status on inspected evidence only; nothing here certifies execution, authority or delivery.</p>\n"
        "<table>\n<tr><th>Item</th><th>Title</th><th>Execution expected</th><th>Evidence</th>"
        "<th>Apparent status</th><th>Blocks</th><th>Document date</th><th>Signature pages</th>"
        "<th>Exceptions</th></tr>\n" + "\n".join(rows) + "\n</table>"
    )
    return _html_page("Execution overview", body)


# --------------------------------------------------------------- conversion


def docx_paragraphs(path: Path) -> int | None:
    """Paragraphs carrying text in word/document.xml; None when not a docx."""

    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    return sum(1 for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S) if "<w:t" in p)


def _visible_pgm(path: Path) -> bool:
    data = path.read_bytes()
    # P5 header: magic, width, height, maxval, then one byte per pixel.
    tokens: list[bytes] = []
    pos = 0
    while len(tokens) < 4 and pos < len(data):
        while pos < len(data) and data[pos : pos + 1].isspace():
            pos += 1
        start = pos
        while pos < len(data) and not data[pos : pos + 1].isspace():
            pos += 1
        tokens.append(data[start:pos])
    raster = data[pos + 1 :]
    return bool(raster) and min(raster) < 240


def render_check(pdf: Path, pages: int | None) -> tuple[bool, int | None, str]:
    """Poppler renders every page; count those with visible content."""

    if not shutil.which("pdftoppm"):
        return False, None, "Poppler not present; render check skipped"
    if not pages:
        return False, None, "page count unknown; render check skipped"
    with tempfile.TemporaryDirectory(prefix="closing-bible-render-") as tmp:
        prefix = Path(tmp) / "page"
        try:
            proc = subprocess.run(
                ["pdftoppm", "-gray", "-r", "20", str(pdf), str(prefix)],
                capture_output=True,
                text=True,
                timeout=300,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return False, None, f"pdftoppm failed: {error}"
        if proc.returncode != 0:
            return False, None, f"pdftoppm exited {proc.returncode}"
        rendered = sorted(Path(tmp).glob("page-*.pgm"))
        if len(rendered) != pages:
            return False, None, f"rendered {len(rendered)} of {pages} pages"
        visible = sum(1 for p in rendered if _visible_pgm(p))
    return True, visible, f"{visible} of {pages} rendered pages carry visible content"


def convert_word(source: Path, soffice: str, workdir: Path) -> Path | None:
    """Word → PDF with a per-run profile (the sigpack convert recipe). The
    source is a copy already outside the closing folder, so LibreOffice's lock
    files never land beside client material."""

    profile = workdir / "lo_profile"
    profile.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = str(profile)
    env["XDG_CONFIG_HOME"] = str(profile / "xdg_config")
    env["XDG_CACHE_HOME"] = str(profile / "xdg_cache")
    Path(env["XDG_CONFIG_HOME"]).mkdir(parents=True, exist_ok=True)
    Path(env["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)
    outdir = workdir / "pdf"
    outdir.mkdir(exist_ok=True)
    try:
        subprocess.run(
            [
                soffice,
                f"-env:UserInstallation={profile.resolve().as_uri()}",
                "--invisible",
                "--headless",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(outdir),
                str(source),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    target = outdir / (source.stem + ".pdf")
    if target.is_file() and target.stat().st_size > 0:
        return target
    return None


# -------------------------------------------------------------------- build


def _load(path: Path, what: str) -> dict[str, Any]:
    _require(path.is_file(), f"refused: {what} not found at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"{what} could not be read as JSON ({path}): {error}"
        ) from error
    _require(isinstance(data, dict), f"{what} must be a JSON object")
    return data


def check_plan(plan_doc: dict[str, Any]) -> None:
    _require(isinstance(plan_doc, dict), "build-plan.json must be a JSON object")
    _require(
        set(plan_doc) == PLAN_KEYS,
        f"build-plan.json must carry exactly {sorted(PLAN_KEYS)}",
    )
    _require(
        plan_doc["schema_version"] == SCHEMA_VERSION,
        "build-plan.json: unsupported schema_version",
    )
    package = plan_doc["package"]
    _require(
        isinstance(package, dict)
        and set(package) == {"version", "folder", "prior_folder"},
        "build-plan.json: package must carry version, folder, prior_folder",
    )
    _require(
        isinstance(package["version"], int) and package["version"] >= 1,
        "build-plan.json: package.version must be 1 or more",
    )
    _require(
        package["folder"] == package_folder(package["version"]),
        f"build-plan.json: package.folder must be {package_folder(package['version'])}",
    )
    _require(
        isinstance(plan_doc["entries"], list), "build-plan.json: entries must be a list"
    )
    _require(
        isinstance(plan_doc["excluded"], list),
        "build-plan.json: excluded must be a list",
    )
    seen: set[str] = set()
    for entry in plan_doc["entries"]:
        _require(
            isinstance(entry, dict) and set(entry) == ENTRY_KEYS,
            f"build-plan.json: entry must carry exactly {sorted(ENTRY_KEYS)}",
        )
        _require(
            entry["status"] in SELECTABLE_STATUSES,
            f"{entry['item_id']}: status {entry['status']} cannot enter the bible",
        )
        _require(
            entry["conversion"] in ("none", "docx-to-pdf", "unrenderable"),
            f"{entry['item_id']}: bad conversion",
        )
        _require(
            isinstance(entry["order"], int) and entry["order"] >= 1,
            f"{entry['item_id']}: order must be 1 or more",
        )
        _require(
            entry["item_id"] not in seen,
            f"{entry['item_id']}: listed twice in the plan",
        )
        seen.add(entry["item_id"])
        _require(
            entry["status"] == "ready" or plan_doc["include_qualified"] is True,
            f"{entry['item_id']}: {entry['status']} is on the plan but include_qualified is false",
        )
    vp = plan_doc["volume_pages"]
    _require(
        vp is None
        or (
            isinstance(vp, int) and not isinstance(vp, bool) and vp >= MIN_VOLUME_PAGES
        ),
        f"build-plan.json: volume_pages must be null or {MIN_VOLUME_PAGES} or more",
    )


def _nothing_to_build(
    plan_doc: dict[str, Any], index: dict[str, Any], overview: dict[str, Any]
) -> str:
    items = {i["item_id"]: i for i in _items(index)}
    lines = ["refused: nothing enters the bible — the plan has no entries."]
    for x in plan_doc["excluded"]:
        q = (items.get(x["item_id"]) or {}).get("qualification") or ""
        lines.append(
            f"  {x['item_id']} {x['title']}: {x['status']} ({x['reason']})"
            + (f" — {q}" if q else "")
        )
    held = any(
        "held, not placed" in exc
        for doc in _overview_docs(overview).values()
        for exc in doc.get("exceptions") or []
    )
    if held:
        lines.append(
            "The sigpack ledger holds returned signature pages that have not been placed into an "
            "executed compilation. Inserting them is $sigpack work (compile), not this skill's; "
            "run it, then audit the folder again."
        )
    lines.append(
        "A visibly qualified bible from items that are not ready needs the lawyer's express "
        "instruction: re-run plan with --include-qualified."
    )
    return "\n".join(lines)


def build(
    plan_doc: dict[str, Any],
    *,
    root: Path,
    audit_dir: Path,
    package_parent: Path,
    as_of: str,
) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    """Assemble the package the approved plan describes. Returns
    (receipt, conversion_log, change_report_md); the report only for update."""

    root = Path(root)
    audit_dir = Path(audit_dir)
    package_parent = Path(package_parent)
    check_plan(plan_doc)
    _require(root.is_dir(), f"refused: closing folder is not a folder: {root}")
    try:
        _dt.date.fromisoformat(as_of)
    except ValueError as error:
        raise ValueError(
            f"as_of {as_of!r} is not a real date; give it as YYYY-MM-DD"
        ) from error
    _require(
        plan_doc["approved"] is True,
        "refused: build-plan.json is not approved; nothing is assembled before the lawyer approves the plan at Gate 2",
    )

    index = _load(audit_dir / "closing-index.json", "closing-index.json")
    _require(
        index.get("approved") is True, "refused: closing-index.json is not approved"
    )
    _require(
        index_sha256(index) == plan_doc["index_sha256"],
        "refused: closing-index.json has changed since the plan was made; re-run plan and approve it again",
    )
    check_exclusions(plan_doc, index)
    manifest = _load(audit_dir / "source-manifest.json", "source-manifest.json")
    _require(
        plan_doc["corpus_id"] == manifest.get("corpus_id") == index.get("corpus_id"),
        f"refused: the plan is for corpus {plan_doc['corpus_id']!r}; the manifest is "
        f"{manifest.get('corpus_id')!r} and the index {index.get('corpus_id')!r}",
    )
    overview = _load(audit_dir / "execution-overview.json", "execution-overview.json")
    audit_receipt = _load(audit_dir / "closing-receipt.json", "closing-receipt.json")
    for name in CARRIED:
        _require(
            (audit_dir / name).is_file(), f"refused: {name} not found in {audit_dir}"
        )

    version = plan_doc["package"]["version"]
    folder = plan_doc["package"]["folder"]
    package = package_parent / folder
    _require(
        not package.exists(),
        f"refused: {package} already exists; a package is never modified after it is written",
    )
    _require(
        not package.resolve().is_relative_to(root.resolve()),
        f"refused: {package} resolves inside the closing folder {root}; the package goes beside it, never into it",
    )
    _require(
        next_version(package_parent) == version,
        f"refused: the next package under {package_parent} would be version {next_version(package_parent)}, "
        f"but the plan says {version}; re-run plan against this package parent",
    )
    prior_name = plan_doc["package"]["prior_folder"]
    prior_dir: Path | None = None
    if prior_name is not None:
        prior_dir = package_parent / prior_name
        _require(
            (prior_dir / "closing-index.json").is_file(),
            f"refused: prior package {prior_name} not found under {package_parent}",
        )
        prior_index = _load(
            prior_dir / "closing-index.json", f"{prior_name}/closing-index.json"
        )
        # An update continues one closing: numbers are never reused for a
        # different document (assembly-rules.md, "Never renumber items"). Two
        # packages that give one number two titles are two different closings,
        # and a change report over them would read "replaced" across deals that
        # have nothing to do with each other.
        prior_titles = {
            i.get("item_id"): i.get("title")
            for i in _items(prior_index)
            if isinstance(i.get("item_id"), str)
        }
        clashes = [
            f"{i['item_id']} is {prior_titles[i['item_id']]!r} in {prior_name} "
            f"and {i.get('title')!r} here"
            for i in _items(index)
            if i.get("item_id") in prior_titles
            and prior_titles[i["item_id"]] != i.get("title")
        ]
        _require(
            not clashes,
            f"refused: {prior_name} is not a prior version of this closing — "
            + "; ".join(clashes)
            + ". An update continues one closing folder; a change report across two "
            "different closings would be a fiction. If a title was corrected at "
            "Gate 1, start a new bible rather than an update.",
        )
    if not plan_doc["entries"]:
        raise ValueError(_nothing_to_build(plan_doc, index, overview))

    before = hash_tree(root)
    staging = package_parent / (folder + STAGING_SUFFIX)
    _require(
        not staging.exists(),
        f"refused: {staging} is already there; this skill never deletes a folder it "
        "did not write. If it is a crashed run of this skill, remove it yourself and "
        "run build again",
    )
    staging.mkdir(parents=True)
    try:
        receipt, log, report = _assemble(
            plan_doc,
            root=root,
            audit_dir=audit_dir,
            staging=staging,
            index=index,
            manifest=manifest,
            overview=overview,
            audit_receipt=audit_receipt,
            prior_dir=prior_dir,
            as_of=as_of,
        )
        if hash_tree(root) != before:
            raise SourceMutated(
                "the closing folder changed during the run (rule 6); the package was not kept"
            )
        os.replace(staging, package)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return receipt, log, report


def _assemble(
    plan_doc: dict[str, Any],
    *,
    root: Path,
    audit_dir: Path,
    staging: Path,
    index: dict[str, Any],
    manifest: dict[str, Any],
    overview: dict[str, Any],
    audit_receipt: dict[str, Any],
    prior_dir: Path | None,
    as_of: str,
) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    folder = plan_doc["package"]["folder"]
    docs = _manifest_docs(manifest)
    items = {i["item_id"]: i for i in _items(index)}
    entries = sorted(plan_doc["entries"], key=lambda e: (e["order"], e["item_id"]))
    soffice = find_soffice()
    pypdf = _import_pypdf()
    indexed = staging / "indexed-set"
    indexed.mkdir()

    conversions: list[dict[str, Any]] = []
    unverified = 0
    # Per entry: the PDF that may enter the combined file, and its page count.
    prepared: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="closing-bible-convert-") as tmp:
        work = Path(tmp)
        for n, entry in enumerate(entries):
            item = items.get(entry["item_id"])
            if item is None:
                raise ValueError(f"{entry['item_id']}: not in closing-index.json")
            _require(
                item["status"] == entry["status"]
                and item.get("selected_id") == entry["source_id"],
                f"{entry['item_id']}: the plan and the index disagree on status or source; re-run plan",
            )
            source = root / entry["source_path"]
            _require(
                source.is_file(),
                f"{entry['item_id']}: source {entry['source_path']} is not in the closing folder",
            )
            _require(
                document_id(source) == entry["source_id"],
                f"{entry['item_id']}: {entry['source_path']} no longer hashes to {entry['source_id']}; the folder changed since the audit",
            )
            native = indexed / entry["output_name"]
            _require(
                not native.exists(),
                f"{entry['item_id']}: output name {entry['output_name']} is taken",
            )
            shutil.copyfile(source, native)
            pdf: Path | None = None
            pages: int | None = None
            note = ""
            if entry["conversion"] == "none":
                pdf = native
                pages = pdf_page_count(native)
                if pages is None:
                    note = "page count unknown"
            elif entry["conversion"] == "docx-to-pdf":
                rendered_name = Path(entry["output_name"]).stem + ".pdf"
                record: dict[str, Any] = {
                    "item_id": entry["item_id"],
                    "source_id": entry["source_id"],
                    "source_path": entry["source_path"],
                    "tool": "soffice" if soffice else None,
                    "output": None,
                    "pages_before": docs.get(entry["source_id"], {}).get("pages"),
                    "pages_after": None,
                    "verified": False,
                    "note": "",
                }
                paragraphs = docx_paragraphs(native)
                rendered = None
                if soffice:
                    scratch = work / f"{n:03d}"
                    scratch.mkdir()
                    copy = scratch / source.name
                    shutil.copyfile(native, copy)
                    rendered = convert_word(copy, soffice, scratch)
                if rendered is None:
                    record["note"] = (
                        "conversion produced no PDF"
                        if soffice
                        else "soffice not present"
                    )
                else:
                    record["pages_after"] = pdf_page_count(rendered)
                    ok, visible, check = render_check(rendered, record["pages_after"])
                    floor = 1 if paragraphs else 0
                    verified = ok and visible is not None and visible >= floor
                    record["verified"] = verified
                    record["note"] = (
                        f"{check}; native document has "
                        f"{paragraphs if paragraphs is not None else 'an unknown number of'} paragraphs with text"
                    )
                    if verified:
                        target = indexed / rendered_name
                        shutil.copyfile(rendered, target)
                        record["output"] = f"indexed-set/{rendered_name}"
                        pdf = target
                        pages = record["pages_after"]
                if not record["verified"]:
                    unverified += 1
                    note = f"conversion unverified: {record['note']}; native retained, not in the combined PDF"
                conversions.append(record)
            else:
                unverified += 1
                note = "unrenderable here: no conversion tool for this format; native retained, not in the combined PDF"
                conversions.append(
                    {
                        "item_id": entry["item_id"],
                        "source_id": entry["source_id"],
                        "source_path": entry["source_path"],
                        "tool": None,
                        "output": None,
                        "pages_before": docs.get(entry["source_id"], {}).get("pages"),
                        "pages_after": None,
                        "verified": False,
                        "note": note,
                    }
                )
            prepared.append(
                {
                    "entry": entry,
                    "native": native,
                    "pdf": pdf,
                    "pages": pages,
                    "note": note,
                }
            )

    placements: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    combined: str | None = None
    volumes: list[str] = []
    if pypdf is None:
        for p in prepared:
            entry = p["entry"]
            included = pdf_page_count(p["pdf"]) if p["pdf"] is not None else None
            rows.append(
                {
                    "item_id": entry["item_id"],
                    "status": entry["status"],
                    "output": f"indexed-set/{entry['output_name']}"
                    + (
                        f" ({p['note']})"
                        if p["note"]
                        else " (combined PDF not built here: pypdf absent)"
                    ),
                    "pages_expected": p["pages"],
                    "pages_included": included,
                    "reconciled": p["pages"] == included,
                }
            )
    else:
        combined, volumes = _write_pdfs(
            pypdf,
            prepared,
            plan_doc,
            index,
            overview,
            staging,
            placements,
            rows,
            folder,
            as_of,
        )

    # The index the package carries: the approved one, start pages filled.
    packaged_index = json.loads(_dump(index))
    for item in packaged_index["items"]:
        placed = placements.get(item["item_id"])
        item["start_page"] = placed["start_page"] if placed else None
    (staging / "closing-index.json").write_text(_dump(packaged_index), encoding="utf-8")
    (staging / "closing-index.html").write_text(
        index_html(packaged_index, placements, docs, folder, as_of), encoding="utf-8"
    )
    (staging / "execution-overview.html").write_text(
        overview_html(overview, folder), encoding="utf-8"
    )
    for name in CARRIED:
        shutil.copyfile(audit_dir / name, staging / name)
    (staging / "build-plan.json").write_text(_dump(plan_doc), encoding="utf-8")
    log = {
        "schema_version": SCHEMA_VERSION,
        "corpus_id": plan_doc["corpus_id"],
        "package": folder,
        "tools": {
            "soffice": soffice is not None,
            "pdfinfo": shutil.which("pdfinfo") is not None,
            "pdftoppm": shutil.which("pdftoppm") is not None,
            "pypdf": pypdf is not None,
        },
        "conversions": conversions,
    }
    (staging / "conversion-log.json").write_text(_dump(log), encoding="utf-8")

    by_status = {s: 0 for s in RECEIPT_STATUSES}
    for item in items.values():
        _require(
            item["status"] in by_status, f"{item['item_id']}: status {item['status']!r}"
        )
        by_status[item["status"]] += 1
    unexpected = index.get("unexpected_families")
    for key in ("sources", "inspection", "sigpack"):
        _require(
            isinstance(audit_receipt.get(key), dict),
            f"closing-receipt.json in the audit folder lacks {key}",
        )
    receipt = Receipt(
        corpus_id=plan_doc["corpus_id"],
        mode="update" if prior_dir is not None else "build",
        index_approved=True,
        expected_items=len(items),
        by_status=by_status,
        unexpected_families=len(unexpected) if isinstance(unexpected, list) else 0,
        sources=dict(audit_receipt["sources"]),
        inspection=dict(audit_receipt["inspection"]),
        sigpack=dict(audit_receipt["sigpack"]),
        as_of=as_of,
        included_outputs=tuple(rows),
        package={
            "version": plan_doc["package"]["version"],
            "folder": folder,
            "prior_folder": plan_doc["package"]["prior_folder"],
            "combined_pdf": combined,
            "volumes": volumes,
            "conversions_unverified": unverified,
        },
    ).to_dict()
    (staging / "closing-receipt.json").write_text(_dump(receipt), encoding="utf-8")

    report: str | None = None
    if prior_dir is not None:
        report = change_report(prior_dir, staging)
        (staging / "change-report.md").write_text(report, encoding="utf-8")
    return receipt, log, report


def _write_pdfs(
    pypdf: Any,
    prepared: list[dict[str, Any]],
    plan_doc: dict[str, Any],
    index: dict[str, Any],
    overview: dict[str, Any],
    staging: Path,
    placements: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
    folder: str,
    as_of: str,
) -> tuple[str | None, list[str]]:
    """The combined PDF, or numbered volumes plus the master index. Front
    matter first; source pages appended as page objects, never re-rendered."""

    cap = plan_doc["volume_pages"]
    readers: dict[str, Any] = {}
    counts: dict[str, int] = {}
    for p in prepared:
        if p["pdf"] is None:
            continue
        try:
            reader = pypdf.PdfReader(str(p["pdf"]))
            if reader.is_encrypted:
                raise ValueError("encrypted")
            counts[p["entry"]["item_id"]] = len(reader.pages)
        except Exception as error:  # pypdf raises its own hierarchy
            raise ValueError(
                f"{p['entry']['item_id']}: {p['entry']['output_name']} could not be opened for the combined PDF ({error})"
            ) from error
        readers[p["entry"]["item_id"]] = reader

    # The index pages carry the start pages, and the start pages depend on how
    # many index pages there are: lay out with placeholders, then repeat with
    # the real numbers until the page count stops moving.
    overview_pages = _paginate(_overview_lines(overview))
    single = cap is None
    index_pages = _paginate(_index_lines(index, {}, folder, as_of))
    groups: list[list[dict[str, Any]]] = []
    for _ in range(5):
        front = len(index_pages) + len(overview_pages)
        # Volume assignment: never split a document; front matter opens volume 1.
        groups = [[]]
        used = front
        for p in prepared:
            if p["pdf"] is None:
                continue
            n = counts[p["entry"]["item_id"]]
            if cap is not None and groups[-1] and used + n > cap:
                groups.append([])
                used = 0
            groups[-1].append(p)
            used += n
        placements.clear()
        page_cursor = front + 1
        for v, group in enumerate(groups, 1):
            if v > 1:
                page_cursor = 1
            for p in group:
                iid = p["entry"]["item_id"]
                placements[iid] = {
                    "volume": None if single else v,
                    "start_page": page_cursor,
                    "pages": counts[iid],
                }
                page_cursor += counts[iid]
        relaid = _paginate(_index_lines(index, placements, folder, as_of))
        settled = len(relaid) == len(index_pages)
        index_pages = relaid
        if settled:
            break
    else:
        raise ValueError("front matter layout did not settle")
    index_page_count = len(index_pages)
    front = index_page_count + len(overview_pages)
    front_reader = pypdf.PdfReader(io.BytesIO(text_pdf(index_pages + overview_pages)))

    names: list[str] = []
    for v, group in enumerate(groups, 1):
        writer = pypdf.PdfWriter()
        name = COMBINED_PDF if single else f"closing-bible-volume-{v:02d}.pdf"
        if v == 1:
            for page in front_reader.pages:
                writer.add_page(page)
            writer.add_outline_item("Closing index", 0)
            writer.add_outline_item("Execution overview", index_page_count)
        for p in group:
            entry = p["entry"]
            iid = entry["item_id"]
            start = placements[iid]["start_page"]
            reader = readers[iid]
            for page in reader.pages:
                writer.add_page(page)
            parent = writer.add_outline_item(
                f"{entry['order']:03d} - {entry['title']}", start - 1
            )
            for ep in entry["execution_pages"]:
                if 1 <= ep <= counts[iid]:
                    writer.add_outline_item(
                        "Execution", start - 1 + ep - 1, parent=parent
                    )
        with open(staging / name, "wb") as fh:
            writer.write(fh)
        names.append(name)
        written = len(pypdf.PdfReader(str(staging / name)).pages)
        expected_total = (front if v == 1 else 0) + sum(
            counts[p["entry"]["item_id"]] for p in group
        )
        _require(
            written == expected_total,
            f"{name}: wrote {written} pages, expected {expected_total}",
        )

    for p in prepared:
        entry = p["entry"]
        iid = entry["item_id"]
        placed = placements.get(iid)
        if placed is None:
            rows.append(
                {
                    "item_id": iid,
                    "status": entry["status"],
                    "output": f"indexed-set/{entry['output_name']} ({p['note']})",
                    "pages_expected": None,
                    "pages_included": None,
                    "reconciled": True,
                }
            )
            continue
        where = (
            COMBINED_PDF
            if single
            else f"closing-bible-volume-{placed['volume']:02d}.pdf"
        )
        end = placed["start_page"] + placed["pages"] - 1
        rows.append(
            {
                "item_id": iid,
                "status": entry["status"],
                "output": f"indexed-set/{entry['output_name']}; {where} pp. {placed['start_page']}-{end}",
                "pages_expected": p["pages"],
                "pages_included": placed["pages"],
                "reconciled": p["pages"] == placed["pages"],
            }
        )

    if single:
        return COMBINED_PDF, []
    master = text_pdf(_paginate(_master_index_lines(index, placements, folder)))
    (staging / INDEX_PDF).write_bytes(master)
    return None, names


# ------------------------------------------------------------ change report


def _package_name(package_dir: Path) -> str:
    receipt_path = package_dir / "closing-receipt.json"
    if receipt_path.is_file():
        try:
            package = (
                json.loads(receipt_path.read_text(encoding="utf-8")).get("package")
                or {}
            )
            if isinstance(package.get("folder"), str):
                return package["folder"]
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    return package_dir.name


def _source_paths(package_dir: Path) -> dict[str, str]:
    try:
        manifest = _load(package_dir / "source-manifest.json", "source-manifest.json")
        return {i: d["path"] for i, d in _manifest_docs(manifest).items()}
    except ValueError:
        return {}


def change_report(prior_dir: Path, new_dir: Path) -> str:
    """assembly-rules.md 'Update': Added / Replaced / Removed / Status changed /
    Unchanged, from the two packages' closing-index.json and selection-plan.json."""

    prior_dir = Path(prior_dir)
    new_dir = Path(new_dir)
    prior_index = _load(prior_dir / "closing-index.json", "prior closing-index.json")
    new_index = _load(new_dir / "closing-index.json", "new closing-index.json")
    _require(
        prior_index.get("corpus_id") is not None
        and new_index.get("corpus_id") is not None,
        "change report: both indexes must carry a corpus_id",
    )
    prior_plan = _load(prior_dir / "selection-plan.json", "prior selection-plan.json")
    new_plan = _load(new_dir / "selection-plan.json", "new selection-plan.json")
    prior_sel = {
        f.get("item_id"): f.get("selected_id")
        for f in prior_plan.get("families") or []
        if isinstance(f, dict)
    }
    new_sel = {
        f.get("item_id"): f.get("selected_id")
        for f in new_plan.get("families") or []
        if isinstance(f, dict)
    }
    prior_paths = _source_paths(prior_dir)
    new_paths = _source_paths(new_dir)
    prior_items = {i["item_id"]: i for i in _items(prior_index)}
    new_items = {i["item_id"]: i for i in _items(new_index)}

    def source(item: dict[str, Any], sel: dict[str, Any], paths: dict[str, str]) -> str:
        sid = item.get("selected_id") or sel.get(item["item_id"])
        if not sid:
            return "no source"
        return f"{paths.get(sid, '?')} ({sid})"

    added: list[str] = []
    replaced: list[str] = []
    removed: list[str] = []
    changed: list[str] = []
    unchanged = 0
    for iid, item in new_items.items():
        label = f"{iid} {item['title']}"
        old = prior_items.get(iid)
        if old is None:
            added.append(
                f"- {label}: {source(item, new_sel, new_paths)}; {item['status']}"
            )
            continue
        old_sid = old.get("selected_id") or prior_sel.get(iid)
        new_sid = item.get("selected_id") or new_sel.get(iid)
        moved = False
        if old_sid and new_sid and old_sid != new_sid:
            replaced.append(
                f"- {label}: {prior_paths.get(old_sid, '?')} ({old_sid}) → {new_paths.get(new_sid, '?')} ({new_sid})"
            )
            moved = True
        elif not old_sid and new_sid:
            added.append(
                f"- {label}: {source(item, new_sel, new_paths)}; {old['status']} → {item['status']} (source now present)"
            )
            moved = True
        if item["status"] == "not-required" and old["status"] != "not-required":
            removed.append(
                f"- {label}: {old['status']} → not-required; {item.get('qualification') or 'marked not-required at Gate 1'}"
            )
            moved = True
        elif old["status"] != item["status"]:
            why = item.get("qualification") or (
                "now ready" if item["status"] == "ready" else ""
            )
            changed.append(
                f"- {label}: {old['status']} → {item['status']}"
                + (f"; {why}" if why else "")
            )
            moved = True
        if not moved:
            unchanged += 1
    for iid, old in prior_items.items():
        if iid not in new_items:
            removed.append(f"- {iid} {old['title']}: no longer in the index")

    def section(title: str, lines: list[str]) -> str:
        return f"## {title}\n\n" + ("\n".join(lines) if lines else "none") + "\n"

    prior_name = _package_name(prior_dir)
    short_prior = prior_name.replace("closing-bible-", "")
    return "\n".join(
        [
            f"# Change report — {_package_name(new_dir)} against {short_prior}",
            "",
            section("Added", added),
            section("Replaced", replaced),
            section("Removed", removed),
            section("Status changed", changed),
            f"## Unchanged\n\n{unchanged} item(s)\n",
        ]
    )
