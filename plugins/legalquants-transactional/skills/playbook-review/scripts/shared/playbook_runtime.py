"""Deterministic, provider-neutral helpers for the Playbook Engine.

The host model performs legal analysis. This module provides the mechanical
layer: source manifests, stable identifiers, lens compilation, markup
reconstruction, receipts, and local HTML rendering.
"""

from __future__ import annotations

import copy
import csv
import difflib
import hashlib
import html
import importlib
import io
import json
import os
import re
import tempfile
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from xml.etree import ElementTree

SUPPORTED_FORMATS = {
    ".docx": "docx",
    ".pdf": "pdf",
    ".md": "md",
    ".txt": "txt",
    ".xlsx": "xlsx",
    ".csv": "csv",
    ".tsv": "csv",
}
SPREADSHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
OFFICE_RELS_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PACKAGE_RELS_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
SOURCE_ROLES = {
    "approved-template",
    "negotiated-final",
    "km-guidance",
    "unannotated-precedent",
    "contract-under-review",
}
ACTIONABLE_WITH_DRAFTING = {
    "deviation",
    "missing-protection",
    "extra-obligation",
}
REVIEW_CLASSIFICATIONS = {
    "aligned-preferred",
    "aligned-fallback",
    "deviation",
    "missing-protection",
    "extra-obligation",
    "unclear",
    "not-applicable",
    "playbook-gap",
    "playbook-conflict",
}
CLASSIFICATION_LABELS: dict[str, str] = {
    "deviation": "Redline Required",
    "missing-protection": "Missing House Clause",
    "extra-obligation": "Onerous / Non-Standard",
    "aligned-fallback": "Acceptable Fallback",
    "aligned-preferred": "Standard / Aligned",
    "playbook-gap": "Uncovered Issue",
    "playbook-conflict": "Playbook Conflict",
    "unclear": "Ambiguous Drafting",
    "not-applicable": "Not Applicable",
}


CLASSIFICATION_TALLY_ORDER: tuple[str, ...] = (
    "deviation",
    "missing-protection",
    "extra-obligation",
    "playbook-gap",
    "playbook-conflict",
    "unclear",
    "aligned-fallback",
    "aligned-preferred",
    "not-applicable",
)
STRUCTURAL_WARNING_CATEGORIES = {
    "missing-document",
    "precedence-conflict",
    "governing-law-conflict",
    "irregular-drafting",
    "other",
}
STRUCTURAL_WARNING_LABELS: dict[str, str] = {
    "missing-document": "Missing Incorporated Document",
    "precedence-conflict": "Precedence Conflict",
    "governing-law-conflict": "Governing Law / Disputes Conflict",
    "irregular-drafting": "Irregular Drafting",
    "other": "Structural Warning",
}
EXPORT_AUDIENCES = {"internal", "external"}
DATE_STYLES = {"uk", "us", "iso"}
# Governing-law markers that select US date order. Matched on word boundaries so
# that "usa" never fires inside "Lusaka" and "york" never fires inside "Yorkshire".
US_GOVERNING_LAW_MARKERS: tuple[str, ...] = (
    "united states",
    "u.s.",
    "u.s.a.",
    "usa",
    "federal",
    "alabama",
    "alaska",
    "arizona",
    "arkansas",
    "california",
    "colorado",
    "connecticut",
    "delaware",
    "district of columbia",
    "florida",
    "georgia",
    "hawaii",
    "idaho",
    "illinois",
    "indiana",
    "iowa",
    "kansas",
    "kentucky",
    "louisiana",
    "maine",
    "maryland",
    "massachusetts",
    "michigan",
    "minnesota",
    "mississippi",
    "missouri",
    "montana",
    "nebraska",
    "nevada",
    "new hampshire",
    "new jersey",
    "new mexico",
    "new york",
    "north carolina",
    "north dakota",
    "ohio",
    "oklahoma",
    "oregon",
    "pennsylvania",
    "rhode island",
    "south carolina",
    "south dakota",
    "tennessee",
    "texas",
    "utah",
    "vermont",
    "virginia",
    "washington",
    "west virginia",
    "wisconsin",
    "wyoming",
)


def get_classification_label(classification: str) -> str:
    """Return a lawyer-friendly label for an internal review classification."""
    return CLASSIFICATION_LABELS.get(
        classification, classification.replace("-", " ").title()
    )


def parse_iso_timestamp(value: Any) -> datetime:
    """Parse an ISO 8601 timestamp (``Z`` suffix accepted) or raise ValueError."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty ISO 8601 string")
    clean = value.strip()
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    return datetime.fromisoformat(clean)


def detect_date_style(governing_law: str | None) -> str:
    """Return 'us' when the governing law names a US jurisdiction, else 'uk'."""
    law_lower = (governing_law or "").lower()
    if not law_lower:
        return "uk"
    for marker in US_GOVERNING_LAW_MARKERS:
        if re.search(rf"(?<![a-z]){re.escape(marker)}(?![a-z])", law_lower):
            return "us"
    return "uk"


def format_display_date(
    dt_str: str | None = None,
    style: str = "auto",
    governing_law: str | None = None,
) -> str:
    """Format an ISO timestamp or the current time as a formal, unambiguous date.

    Styles:
    - 'uk': '6 September 2026' (day-month-year, the international default)
    - 'us': 'September 6, 2026'
    - 'iso': '2026-09-06'
    - 'auto': 'us' when ``governing_law`` names a US jurisdiction, else 'uk'.

    An unparseable ``dt_str`` raises ValueError. A document date is a legal
    fact; silently substituting today's date would misdate the deliverable.
    """
    dt = parse_iso_timestamp(dt_str) if dt_str else datetime.now(UTC)

    target_style = (style or "auto").lower().strip()
    if target_style == "auto":
        target_style = detect_date_style(governing_law)
    if target_style not in DATE_STYLES:
        raise ValueError(f"Unknown date style: {style}")

    if target_style == "us":
        return f"{dt.strftime('%B')} {dt.day}, {dt.year}"
    if target_style == "iso":
        return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"
    return f"{dt.day} {dt.strftime('%B')} {dt.year}"


def format_british_date(dt_str: str | None = None) -> str:
    """Format an ISO timestamp or current time as a British date (backward-compatible alias)."""
    return format_display_date(dt_str, style="uk")


MATERIALITIES = {"high", "medium", "low", "none"}
MATERIALITY_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3}
DRAFTING_PROVENANCE = {
    "approved-playbook",
    "candidate-drafting",
    "mixed",
    "none",
}
LAWYER_REVIEW_STATES = {
    "pending",
    "accepted",
    "rejected",
    "revised",
    "not-required",
}
POSITION_FIELDS = {"summary", "preferred", "fallbacks", "redLine", "priority"}
WORD_TOKEN = re.compile(r"\s+|[^\s]+")
CLAUSE_PREFIX = re.compile(r"^((?:\d+\.)*\d+[A-Za-z]?|[A-Z])(?:[.)]|\s)")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DEFINITION_PREFIX = re.compile(
    r"^(?:[-*•+\s]*)"
    r"(?:(?:\d+(?:\.\d+)*|\([a-z0-9]+\))\s+)?"
    r"[\"“']?(?:\*{1,2}|_{1,2})?[\"“']?"
    r"(?P<term>[A-Z][A-Za-z0-9&/'. -]{0,80}?[A-Za-z0-9])"
    r"[\"”']?(?:\*{1,2}|_{1,2})?[\"”']?"
    r"\s*(?::\s*|\s*\|\s*|\s+)"
    r"(?:means|Means|shall\s+mean|has\s+the\s+meaning\s+(?:given|set\s+out))\b",
    re.IGNORECASE,
)
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WORD_XMLNS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
DEFAULT_REGISTRY_NAME = "playbook-registry.json"


class PlaybookError(ValueError):
    """Raised when an artifact would violate a Playbook Engine invariant."""


def utc_now() -> str:
    """Return a stable ISO 8601 UTC timestamp shape."""

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON deterministically for hashing and receipts."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def manifest_content_sha256(manifest: Mapping[str, Any]) -> str:
    return json_sha256(
        {
            "artifactType": manifest.get("artifactType"),
            "schemaVersion": manifest.get("schemaVersion"),
            "inputBoundary": manifest.get("inputBoundary"),
            "documents": manifest.get("documents"),
        }
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_id(prefix: str, *parts: object) -> str:
    material = "\x1f".join(str(part) for part in parts)
    suffix = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{suffix}"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PlaybookError(f"{path} must contain one JSON object")
    return value


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _normalise_text(text: str) -> str:
    return " ".join(text.split())


def _clause_ref(text: str) -> str | None:
    match = CLAUSE_PREFIX.match(text.strip())
    return match.group(1) if match else None


def _normalise_term(term: str) -> str:
    return " ".join(term.casefold().split())


def _elements_from_blocks(
    blocks: Iterable[tuple[str, str, int | None]],
    document_hash: str,
) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    for ordinal, (kind, raw_text, page_number) in enumerate(blocks, start=1):
        text = _normalise_text(raw_text)
        if not text:
            continue
        element_id = stable_id("el", document_hash, ordinal, kind, text)
        elements.append(
            {
                "elementId": element_id,
                "kind": kind,
                "ordinal": ordinal,
                "clauseRef": _clause_ref(text),
                "pageNumber": page_number,
                "sourceText": text,
                "textSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
    return elements


def _defined_terms_from_elements(
    elements: Sequence[Mapping[str, Any]], document_hash: str
) -> list[dict[str, Any]]:
    terms: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for element in elements:
        source_text = element.get("sourceText")
        if not isinstance(source_text, str):
            continue
        for line in source_text.splitlines():
            line_str = line.strip()
            match = DEFINITION_PREFIX.match(line_str)
            if not match:
                continue
            term = match.group("term").strip()
            normalized_term = _normalise_term(term)
            element_id = element.get("elementId")
            if not normalized_term or not isinstance(element_id, str):
                continue
            key = (normalized_term, element_id)
            if key in seen:
                continue
            seen.add(key)
            terms.append(
                {
                    "termId": stable_id(
                        "term", document_hash, normalized_term, element_id
                    ),
                    "term": term,
                    "normalizedTerm": normalized_term,
                    "definitionText": line_str
                    if len(source_text.splitlines()) > 1
                    else source_text,
                    "documentSha256": document_hash,
                    "elementId": element_id,
                    "clauseRef": element.get("clauseRef"),
                }
            )
    return terms


def _extract_text_file(
    path: Path, document_hash: str
) -> tuple[list[Any], list[Any], list[str]]:
    text = path.read_text(encoding="utf-8-sig")
    blocks: list[tuple[str, str, int | None]] = []
    bullet_re = re.compile(
        r"^\s*(?:[-*•+]|\([a-z0-9]+\)|\d+(?:\.\d+)*[.)])\s+", re.IGNORECASE
    )
    for chunk in re.split(r"\n\s*\n", text):
        stripped = chunk.strip()
        if not stripped:
            continue
        kind = (
            "heading"
            if path.suffix.lower() == ".md" and stripped.startswith("#")
            else "paragraph"
        )
        if kind == "heading":
            blocks.append(("heading", stripped.lstrip("# "), None))
            continue
        lines = stripped.splitlines()
        if len(lines) > 1 and sum(bool(bullet_re.match(item)) for item in lines) >= 2:
            current_item: list[str] = []
            for line in lines:
                if bullet_re.match(line):
                    if current_item:
                        blocks.append(("paragraph", " ".join(current_item), None))
                    current_item = [line.strip()]
                elif current_item:
                    current_item.append(line.strip())
                else:
                    current_item = [line.strip()]
            if current_item:
                blocks.append(("paragraph", " ".join(current_item), None))
        else:
            blocks.append((kind, stripped, None))
    return [], _elements_from_blocks(blocks, document_hash), []


def _extract_w_text(element: ElementTree.Element) -> str:
    """Extract text from a Word XML element, preserving line breaks and tabs."""
    parts: list[str] = []
    for node in element.iter():
        if node.tag == f"{WORD_NS}t":
            parts.append(node.text or "")
        elif node.tag in {f"{WORD_NS}br", f"{WORD_NS}cr"}:
            parts.append("\n")
        elif node.tag == f"{WORD_NS}tab":
            parts.append("\t")
    return "".join(parts)


def _extract_docx(
    path: Path, document_hash: str
) -> tuple[list[Any], list[Any], list[str]]:
    warnings: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
            if "word/footnotes.xml" in archive.namelist():
                try:
                    fn_root = ElementTree.fromstring(archive.read("word/footnotes.xml"))
                    for fn in fn_root.findall(f".//{WORD_NS}footnote"):
                        fn_id = fn.attrib.get(f"{WORD_NS}id")
                        if fn_id and fn_id not in {"-1", "0"}:
                            fn_text = _extract_w_text(fn).strip()
                            if fn_text:
                                warnings.append("document-contains-footnotes")
                                break
                except Exception:
                    pass
            if "word/comments.xml" in archive.namelist():
                try:
                    cm_root = ElementTree.fromstring(archive.read("word/comments.xml"))
                    for cm in cm_root.findall(f".//{WORD_NS}comment"):
                        cm_text = _extract_w_text(cm).strip()
                        if cm_text:
                            warnings.append("document-contains-comments")
                            break
                except Exception:
                    pass
    except (KeyError, zipfile.BadZipFile) as exc:
        raise PlaybookError(f"Unreadable DOCX {path.name}: {exc}") from exc

    root = ElementTree.fromstring(xml)
    if root.findall(f".//{WORD_NS}ins") or root.findall(f".//{WORD_NS}del"):
        warnings.append("unresolved-word-tracked-changes")

    blocks: list[tuple[str, str, int | None]] = []
    body = root.find(f".//{WORD_NS}body")
    if body is None:
        raise PlaybookError(f"Unreadable DOCX {path.name}: missing document body")
    for child in body:
        if child.tag == f"{WORD_NS}p":
            text = _extract_w_text(child)
            if text.strip():
                blocks.append(("paragraph", text, None))
        elif child.tag == f"{WORD_NS}tbl":
            for row in child.findall(f".//{WORD_NS}tr"):
                cells = row.findall(f"./{WORD_NS}tc")
                cell_paragraphs: list[str] = []
                for cell in cells:
                    paras = [
                        _extract_w_text(p).strip()
                        for p in cell.findall(f".//{WORD_NS}p")
                    ]
                    cell_text = (
                        "\n".join(p for p in paras if p)
                        or _extract_w_text(cell).strip()
                    )
                    if cell_text:
                        cell_paragraphs.append(cell_text)
                if cell_paragraphs:
                    blocks.append(("table-cell", " | ".join(cell_paragraphs), None))
    return [], _elements_from_blocks(blocks, document_hash), warnings


def _extract_pdf(
    path: Path, document_hash: str
) -> tuple[list[Any], list[Any], list[str]]:
    pages: list[dict[str, Any]] = []
    blocks: list[tuple[str, str, int | None]] = []
    warnings: list[str] = []

    extraction_error = False
    try:
        pdfplumber = importlib.import_module("pdfplumber")

        with pdfplumber.open(str(path)) as pdf:
            for page_index, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                stripped = text.strip()
                if stripped:
                    pages.append(
                        {
                            "pageNumber": page_index,
                            "readingMethod": "native-text",
                            "readability": "readable",
                            "textSha256": hashlib.sha256(
                                stripped.encode("utf-8")
                            ).hexdigest(),
                            "warning": None,
                        }
                    )
                    for chunk in re.split(r"\n\s*\n", text):
                        chunk_str = chunk.strip()
                        if chunk_str:
                            blocks.append(("paragraph", chunk_str, page_index))
                else:
                    pages.append(
                        {
                            "pageNumber": page_index,
                            "readingMethod": "pending-vision",
                            "readability": "unreadable",
                            "textSha256": hashlib.sha256(b"").hexdigest(),
                            "warning": "no-searchable-text-found",
                        }
                    )
    except Exception:
        extraction_error = True

    if not pages:
        try:
            pypdf = importlib.import_module("pypdf")

            reader = pypdf.PdfReader(str(path))
            for page_index, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                stripped = text.strip()
                if stripped:
                    pages.append(
                        {
                            "pageNumber": page_index,
                            "readingMethod": "native-text",
                            "readability": "readable",
                            "textSha256": hashlib.sha256(
                                stripped.encode("utf-8")
                            ).hexdigest(),
                            "warning": None,
                        }
                    )
                    for chunk in re.split(r"\n\s*\n", text):
                        chunk_str = chunk.strip()
                        if chunk_str:
                            blocks.append(("paragraph", chunk_str, page_index))
                else:
                    pages.append(
                        {
                            "pageNumber": page_index,
                            "readingMethod": "pending-vision",
                            "readability": "unreadable",
                            "textSha256": hashlib.sha256(b"").hexdigest(),
                            "warning": "no-searchable-text-found",
                        }
                    )
            extraction_error = False
        except Exception:
            extraction_error = True

    if extraction_error:
        warnings.append(
            "pdf-extraction-error; native text extraction failed, so coverage is "
            "partial and unread pages require host vision reading"
        )

    if blocks:
        if any(p["readingMethod"] == "pending-vision" for p in pages):
            warnings.append(
                "pdf-partial-native-text; image-only pages require host vision reading"
            )
        return pages, _elements_from_blocks(blocks, document_hash), warnings

    warnings.append(
        "pdf-host-reading-required; use native text where reliable and render "
        "every scanned or uncertain page"
    )
    return [], [], warnings


def _col_to_idx(col_str: str) -> int:
    idx = 0
    for char in col_str.upper():
        if "A" <= char <= "Z":
            idx = idx * 26 + (ord(char) - ord("A") + 1)
    return idx - 1


def _table_row_text(cells: Sequence[str]) -> str:
    """Join a table row exactly as the manifest extractors do.

    Non-empty cells joined with " | ". The importer uses the same rule so that
    every imported issue anchors to a real manifest element by exact text.
    """
    return " | ".join(cell for cell in cells if cell)


def _docx_cell_text(cell: ElementTree.Element) -> str:
    paras = [_extract_w_text(p).strip() for p in cell.findall(f".//{WORD_NS}p")]
    return "\n".join(p for p in paras if p) or _extract_w_text(cell).strip()


def _docx_table_rows(
    table: ElementTree.Element,
) -> tuple[list[list[str]], list[list[str]]]:
    """Return (filled_rows, raw_rows) for one Word table.

    ``filled_rows`` pad horizontally merged cells (``gridSpan``) and copy
    vertically merged cells (``vMerge``) down so every row has the same column
    positions as the header. ``raw_rows`` hold the text exactly as the manifest
    extractor reads it, which is what provenance is anchored to.
    """
    filled: list[list[str]] = []
    raw: list[list[str]] = []
    previous: list[str] = []
    for tr in table.findall(f"./{WORD_NS}tr"):
        row: list[str] = []
        raw_row: list[str] = []
        for tc in tr.findall(f"./{WORD_NS}tc"):
            cell_text = _docx_cell_text(tc)
            raw_row.append(cell_text)
            span = 1
            merged_from_above = False
            tc_pr = tc.find(f"./{WORD_NS}tcPr")
            if tc_pr is not None:
                grid_span = tc_pr.find(f"./{WORD_NS}gridSpan")
                if grid_span is not None:
                    try:
                        span = max(1, int(grid_span.attrib.get(f"{WORD_NS}val", "1")))
                    except ValueError:
                        span = 1
                v_merge = tc_pr.find(f"./{WORD_NS}vMerge")
                if (
                    v_merge is not None
                    and v_merge.attrib.get(f"{WORD_NS}val") != "restart"
                ):
                    merged_from_above = True
            if merged_from_above and not cell_text:
                column = len(row)
                cell_text = previous[column] if column < len(previous) else ""
            row.append(cell_text)
            row.extend([""] * (span - 1))
        if any(cell.strip() for cell in row):
            filled.append(row)
            raw.append(raw_row)
            previous = row
    return filled, raw


def _find_header_row(rows: Sequence[Sequence[str]], limit: int = 10) -> int:
    """Return the index of the first row that reads as a playbook header.

    Firm tables often open with a title or a legend, so the header is not
    always row one. A header is a row where at least two columns match known
    aliases and one of them is the topic or the preferred position.
    """
    for index, row in enumerate(rows[:limit]):
        matched = _match_column_headers(list(row))
        if len(matched) >= 2 and ("topic" in matched or "preferred" in matched):
            return index
    return 0


def _parse_docx_playbook_table(
    path: Path,
) -> tuple[list[list[str]], list[list[str]]]:
    """Return (filled_rows, raw_rows) for the table that looks like a playbook.

    When a document holds several tables, the one whose header row matches the
    most playbook column aliases wins; a legend or signature table never does.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise PlaybookError(f"Unreadable DOCX {path.name}: {exc}") from exc

    root = ElementTree.fromstring(xml)
    body = root.find(f".//{WORD_NS}body")
    tables = body.findall(f"./{WORD_NS}tbl") if body is not None else []
    if not tables:
        raise PlaybookError(f"No tables found in Word document: {path.name}")

    best: tuple[list[list[str]], list[list[str]]] | None = None
    best_score = -1
    for table in tables:
        filled, raw = _docx_table_rows(table)
        if not filled:
            continue
        header = filled[_find_header_row(filled)]
        score = len(_match_column_headers(header))
        if score > best_score:
            best = (filled, raw)
            best_score = score
    if best is None:
        raise PlaybookError(f"No populated table found in Word document: {path.name}")
    return best


def _parse_docx_table_rows(path: Path) -> list[list[str]]:
    return _parse_docx_playbook_table(path)[0]


def _xlsx_first_sheet_part(archive: zipfile.ZipFile) -> str:
    """Resolve the first worksheet through workbook.xml and its relationships.

    ``sheet1.xml`` is only the first tab by convention; a workbook whose tabs
    were reordered or deleted can have its first tab in any part.
    """
    names = archive.namelist()
    try:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        first_sheet = workbook.find(f".//{SPREADSHEET_NS}sheets/{SPREADSHEET_NS}sheet")
        rel_id = (
            first_sheet.attrib.get(f"{OFFICE_RELS_NS}id")
            if first_sheet is not None
            else None
        )
        if rel_id:
            for rel in rels.findall(f"./{PACKAGE_RELS_NS}Relationship"):
                if rel.attrib.get("Id") == rel_id:
                    target = rel.attrib.get("Target", "")
                    part = target.lstrip("/")
                    if not part.startswith("xl/"):
                        part = f"xl/{part}"
                    if part in names:
                        return part
    except (KeyError, ElementTree.ParseError):
        pass
    if "xl/worksheets/sheet1.xml" in names:
        return "xl/worksheets/sheet1.xml"
    sheets = sorted(
        n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
    )
    if not sheets:
        raise PlaybookError("No worksheet found in workbook")
    return sheets[0]


def _parse_xlsx_table_rows(path: Path) -> list[list[str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                sst_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                for si in sst_root.findall(f".//{SPREADSHEET_NS}si"):
                    # Rich-text cells split their text across <r><t> runs.
                    text_parts = [
                        t.text or "" for t in si.iter() if t.tag == f"{SPREADSHEET_NS}t"
                    ]
                    shared_strings.append("".join(text_parts))

            sheet_root = ElementTree.fromstring(
                archive.read(_xlsx_first_sheet_part(archive))
            )
            sheet_data = sheet_root.find(f".//{SPREADSHEET_NS}sheetData")
            if sheet_data is None:
                return []

            rows: list[list[str]] = []
            for row_elem in sheet_data.findall(f"./{SPREADSHEET_NS}row"):
                cell_map: dict[int, str] = {}
                max_col = -1
                for c in row_elem.findall(f"./{SPREADSHEET_NS}c"):
                    # Empty cells are omitted from the XML, so place each cell
                    # by its reference rather than by position.
                    ref = c.attrib.get("r", "")
                    col_match = re.match(r"^([A-Za-z]+)", ref)
                    col_idx = (
                        _col_to_idx(col_match.group(1)) if col_match else len(cell_map)
                    )
                    t_attr = c.attrib.get("t", "")
                    v_elem = c.find(f"./{SPREADSHEET_NS}v")
                    val = (
                        v_elem.text
                        if v_elem is not None and v_elem.text is not None
                        else ""
                    )
                    if t_attr == "s":
                        try:
                            s_idx = int(val)
                            cell_text = (
                                shared_strings[s_idx]
                                if s_idx < len(shared_strings)
                                else ""
                            )
                        except ValueError:
                            cell_text = val
                    elif t_attr == "inlineStr":
                        is_elem = c.find(f".//{SPREADSHEET_NS}is")
                        cell_text = (
                            "".join(
                                t.text or ""
                                for t in is_elem.iter()
                                if t.tag == f"{SPREADSHEET_NS}t"
                            )
                            if is_elem is not None
                            else ""
                        )
                    else:
                        cell_text = val

                    cell_map[col_idx] = cell_text.strip()
                    max_col = max(max_col, col_idx)

                if max_col >= 0:
                    row = [cell_map.get(i, "") for i in range(max_col + 1)]
                    if any(cell for cell in row):
                        rows.append(row)
            return rows
    except (KeyError, zipfile.BadZipFile) as exc:
        raise PlaybookError(f"Unreadable XLSX {path.name}: {exc}") from exc


def _parse_csv_table_rows(path: Path) -> list[list[str]]:
    content: str | None = None
    # Excel writes UTF-8 with a BOM or the Windows code page; try both before
    # giving up rather than decoding a pound sign into mojibake.
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            content = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    if content is None:
        raise PlaybookError(f"Cannot decode CSV file: {path.name}")

    first_line = content.split("\n", 1)[0] if content else ""
    delimiter = "\t" if path.suffix.lower() == ".tsv" or "\t" in first_line else ","
    # newline="" keeps quoted cells that contain line breaks intact.
    reader = csv.reader(io.StringIO(content, newline=""), delimiter=delimiter)
    rows: list[list[str]] = []
    for raw_row in reader:
        row = [cell.strip() for cell in raw_row]
        if any(row):
            rows.append(row)
    return rows


def _extract_xlsx(
    path: Path, document_hash: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    rows = _parse_xlsx_table_rows(path)
    blocks: list[tuple[str, str, int | None]] = []
    for row in rows:
        text = _table_row_text(row)
        if text.strip():
            blocks.append(("table-cell", text, None))
    return [], _elements_from_blocks(blocks, document_hash), []


def _extract_csv(
    path: Path, document_hash: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    rows = _parse_csv_table_rows(path)
    blocks: list[tuple[str, str, int | None]] = []
    for row in rows:
        text = _table_row_text(row)
        if text.strip():
            blocks.append(("table-cell", text, None))
    return [], _elements_from_blocks(blocks, document_hash), []


def inventory_document(
    path: Path,
    ordinal: int,
    source_role: str,
) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    suffix = resolved.suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        raise PlaybookError(f"Unsupported source format: {resolved.name}")
    if source_role not in SOURCE_ROLES:
        raise PlaybookError(f"Unsupported source role: {source_role}")

    document_hash = file_sha256(resolved)
    document_format = SUPPORTED_FORMATS[suffix]
    if document_format in {"md", "txt"}:
        pages, elements, warnings = _extract_text_file(resolved, document_hash)
    elif document_format == "docx":
        pages, elements, warnings = _extract_docx(resolved, document_hash)
    elif document_format == "xlsx":
        pages, elements, warnings = _extract_xlsx(resolved, document_hash)
    elif document_format == "csv":
        pages, elements, warnings = _extract_csv(resolved, document_hash)
    else:
        pages, elements, warnings = _extract_pdf(resolved, document_hash)
    defined_terms = _defined_terms_from_elements(elements, document_hash)

    if document_format == "pdf" and not pages and not elements:
        readability = "pending-host-read"
    elif pages and all(page["readability"] == "unreadable" for page in pages):
        readability = "unreadable"
    elif pages and any(page["readingMethod"] == "pending-vision" for page in pages):
        readability = "partial"
    elif any(warning.startswith("pdf-extraction-error") for warning in warnings):
        readability = "partial"
    elif "unresolved-word-tracked-changes" in warnings:
        readability = "partial"
    elif not elements:
        readability = "unreadable"
    else:
        readability = "readable"

    return {
        "documentId": stable_id("doc", document_hash),
        "fileName": resolved.name,
        "format": document_format,
        "sha256": document_hash,
        "sizeBytes": resolved.stat().st_size,
        "ordinal": ordinal,
        "sourceRole": source_role,
        "readability": readability,
        "pages": pages,
        "elements": elements,
        "definedTerms": defined_terms,
        "warnings": sorted(set(warnings)),
    }


def build_source_manifest(
    paths: Sequence[Path],
    input_boundary: Path,
    source_roles: Mapping[str, str] | None = None,
    max_sources: int | None = 5,
) -> dict[str, Any]:
    if not paths:
        raise PlaybookError("At least one source file is required")
    if max_sources is not None and len(paths) > max_sources:
        raise PlaybookError(
            f"At most {max_sources} source files are allowed per run; got {len(paths)}"
        )
    boundary = input_boundary.resolve(strict=True)
    roles = source_roles or {}
    documents: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for ordinal, path in enumerate(paths, start=1):
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(boundary):
            raise PlaybookError(
                f"Source is outside the declared input boundary: {path}"
            )
        if resolved in seen:
            raise PlaybookError(f"Duplicate source path: {path}")
        seen.add(resolved)
        role = roles.get(str(path), roles.get(path.name))
        if role is None:
            raise PlaybookError(
                f"Source role is required for {path.name}; pass --role "
                f"{path.name}=ROLE with one of: {', '.join(sorted(SOURCE_ROLES))}"
            )
        documents.append(inventory_document(resolved, ordinal, role))

    payload: dict[str, Any] = {
        "artifactType": "source-manifest",
        "schemaVersion": "1.0",
        "manifestId": stable_id(
            "manifest", *(document["sha256"] for document in documents)
        ),
        "createdAt": utc_now(),
        "inputBoundary": str(boundary),
        "documents": documents,
    }
    payload["manifestSha256"] = manifest_content_sha256(payload)
    return payload


def validate_playbook(
    playbook: Mapping[str, Any],
    require_approved: bool = False,
    source_manifest: Mapping[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    if playbook.get("artifactType") != "contract-playbook":
        errors.append("artifactType must be contract-playbook")
    if playbook.get("schemaVersion") != "1.0":
        errors.append("schemaVersion must be 1.0")

    status = playbook.get("status")
    if status == "approved":
        require_approved = True
    elif require_approved:
        errors.append("playbook must be approved before review")

    for field in ("playbookId", "version", "perspective", "agreementFamily"):
        val = playbook.get(field)
        if not isinstance(val, str) or not val.strip():
            errors.append(f"{field} is required")

    # Build manifest element lookup if manifest supplied
    manifest_doc_shas: set[str] = set()
    manifest_element_index: dict[tuple[str, str], str] = {}
    if source_manifest and isinstance(source_manifest.get("documents"), list):
        for doc in source_manifest["documents"]:
            if not isinstance(doc, Mapping):
                continue
            sha = str(doc.get("sha256") or doc.get("documentSha256") or "")
            if sha:
                manifest_doc_shas.add(sha)
                for elem in doc.get("elements", []):
                    if isinstance(elem, Mapping):
                        elem_id = str(elem.get("elementId") or "")
                        if elem_id:
                            manifest_element_index[(sha, elem_id)] = str(
                                elem.get("sourceText") or ""
                            )

    issues = playbook.get("issues")
    if not isinstance(issues, list) or not issues:
        return [*errors, "issues must be a non-empty list"]
    issue_ids: set[str] = set()
    for index, issue in enumerate(issues):
        if not isinstance(issue, dict):
            errors.append(f"issues[{index}] must be an object")
            continue
        issue_id = issue.get("issueId")
        if not isinstance(issue_id, str) or not issue_id:
            errors.append(f"issues[{index}].issueId is required")
            continue
        if issue_id in issue_ids:
            errors.append(f"duplicate issueId: {issue_id}")
        issue_ids.add(issue_id)
        if issue.get("status") not in {"approved", "candidate", "conflicted"}:
            errors.append(f"{issue_id}: invalid status")
        position = issue.get("basePosition")
        if not isinstance(position, dict):
            errors.append(f"{issue_id}: basePosition is required")
        provenance = issue.get("provenance")
        if not isinstance(provenance, list) or not provenance:
            errors.append(f"{issue_id}: provenance must contain at least one source")
        elif source_manifest:
            for prov in provenance:
                if not isinstance(prov, Mapping):
                    continue
                doc_sha = str(prov.get("documentSha256") or prov.get("sha256") or "")
                elem_id = str(prov.get("elementId") or "")
                if not doc_sha or doc_sha not in manifest_doc_shas:
                    errors.append(
                        f"{issue_id}: provenance document {doc_sha} not found in source manifest"
                    )
                    continue
                if not elem_id or (doc_sha, elem_id) not in manifest_element_index:
                    errors.append(
                        f"{issue_id}: provenance element {elem_id} not found in source manifest"
                    )
                    continue
                exact_text = prov.get("exactText")
                if isinstance(exact_text, str) and exact_text.strip():
                    src_text = manifest_element_index[(doc_sha, elem_id)]
                    if _normalise_text(exact_text) not in _normalise_text(src_text):
                        errors.append(
                            f"{issue_id}: provenance quotation does not match source element {elem_id}"
                        )

        fallbacks = position.get("fallbacks", []) if isinstance(position, dict) else []
        ranks = [
            fallback.get("rank") for fallback in fallbacks if isinstance(fallback, dict)
        ]
        if ranks != list(range(1, len(ranks) + 1)):
            errors.append(f"{issue_id}: fallback ranks must be consecutive from 1")
        if (
            require_approved
            and issue.get("status") == "approved"
            and isinstance(position, dict)
        ):
            preferred = position.get("preferred")
            if (
                not isinstance(preferred, dict)
                or preferred.get("approvalStatus") != "approved"
            ):
                errors.append(
                    f"{issue_id}: operative preferred wording is not approved"
                )
            for fallback in fallbacks:
                wording = (
                    fallback.get("wording") if isinstance(fallback, dict) else None
                )
                if (
                    not isinstance(wording, dict)
                    or wording.get("approvalStatus") != "approved"
                ):
                    errors.append(
                        f"{issue_id}: operative fallback wording is not approved"
                    )

    for issue in issues:
        if not isinstance(issue, dict):
            continue
        for dependency in issue.get("dependencies", []):
            if dependency not in issue_ids:
                errors.append(
                    f"{issue.get('issueId')}: unknown dependency {dependency}"
                )

    lens_ids: set[str] = set()
    lenses = playbook.get("matterLenses", [])
    if not isinstance(lenses, list):
        errors.append("matterLenses must be a list")
        return errors
    for index, lens in enumerate(lenses):
        if not isinstance(lens, dict):
            errors.append(f"matterLenses[{index}] must be an object")
            continue
        lens_id = lens.get("lensId")
        if not isinstance(lens_id, str) or not lens_id:
            errors.append(f"matterLenses[{index}].lensId is required")
            continue
        if lens_id in lens_ids:
            errors.append(f"duplicate lensId: {lens_id}")
        lens_ids.add(lens_id)
        for adjustment in lens.get("adjustments", []):
            if not isinstance(adjustment, dict):
                errors.append(f"{lens_id}: adjustment must be an object")
                continue
            if adjustment.get("issueId") not in issue_ids:
                errors.append(
                    f"{lens_id}: unknown adjusted issue {adjustment.get('issueId')}"
                )
            changes = adjustment.get("changes")
            if not isinstance(changes, dict) or not changes:
                errors.append(f"{lens_id}: adjustment changes must not be empty")
            if lens.get("status") == "approved" and isinstance(changes, dict):
                candidate_fields = [
                    field
                    for field, value in changes.items()
                    if field.endswith("approvalStatus") and value != "approved"
                ]
                if candidate_fields:
                    errors.append(
                        f"{lens_id}: approved lens introduces candidate wording"
                    )
    return errors


def _set_position_path(position: dict[str, Any], field: str, value: Any) -> None:
    parts = field.split(".")
    if not parts or parts[0] not in POSITION_FIELDS:
        raise PlaybookError(f"Unsupported position field: {field}")
    target: dict[str, Any] = position
    for part in parts[:-1]:
        current = target.get(part)
        if not isinstance(current, dict):
            raise PlaybookError(f"Position field is not an object: {field}")
        target = current
    target[parts[-1]] = copy.deepcopy(value)


def compile_effective_stance(
    playbook: Mapping[str, Any],
    activation: Mapping[str, Any],
) -> dict[str, Any]:
    errors = validate_playbook(playbook, require_approved=True)
    if errors:
        raise PlaybookError("; ".join(errors))
    if activation.get("artifactType") != "matter-lens-activation":
        raise PlaybookError("activation artifactType must be matter-lens-activation")
    if activation.get("schemaVersion") != "1.0":
        raise PlaybookError("activation schemaVersion must be 1.0")
    if activation.get("confirmedByLawyer") is not True:
        raise PlaybookError(
            "Gate 1 confirmation is required, including when Standard "
            "Baseline alone applies"
        )

    issues_by_id = {
        issue["issueId"]: issue
        for issue in playbook["issues"]
        if issue["status"] == "approved"
    }
    lenses_by_id = {lens["lensId"]: lens for lens in playbook.get("matterLenses", [])}
    activated = activation.get("activatedLenses", [])
    suggested = activation.get("suggestedLenses", [])
    if not isinstance(activated, list) or not isinstance(suggested, list):
        raise PlaybookError("activatedLenses and suggestedLenses must be lists")
    if any(not isinstance(lens_id, str) for lens_id in [*activated, *suggested]):
        raise PlaybookError("activatedLenses and suggestedLenses must contain strings")
    if len(activated) != len(set(activated)):
        raise PlaybookError("activatedLenses must not contain duplicates")
    if len(suggested) != len(set(suggested)):
        raise PlaybookError("suggestedLenses must not contain duplicates")
    for lens_id in [*activated, *suggested]:
        if lens_id not in lenses_by_id:
            raise PlaybookError(f"Unknown Matter Lens: {lens_id}")
        if lenses_by_id[lens_id].get("status") != "approved":
            raise PlaybookError(f"Candidate Matter Lens is non-operative: {lens_id}")
    for lens_id in activated:
        if lens_id in suggested:
            suggested = [candidate for candidate in suggested if candidate != lens_id]

    effective: dict[str, dict[str, Any]] = {
        issue_id: {
            "issueId": issue_id,
            "topic": issue["topic"],
            "position": copy.deepcopy(issue["basePosition"]),
            "trace": ["Standard Baseline"],
        }
        for issue_id, issue in issues_by_id.items()
    }
    assignments: dict[tuple[str, str], tuple[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for lens_id in activated:
        lens = lenses_by_id[lens_id]
        for adjustment in lens.get("adjustments", []):
            issue_id = adjustment["issueId"]
            if issue_id not in effective:
                raise PlaybookError(
                    f"Lens {lens_id} targets a non-operative issue: {issue_id}"
                )
            for field, value in adjustment["changes"].items():
                key = (issue_id, field)
                previous = assignments.get(key)
                if previous and canonical_json_bytes(
                    previous[1]
                ) != canonical_json_bytes(value):
                    conflicts.append(
                        {
                            "issueId": issue_id,
                            "field": field,
                            "sources": [previous[0], lens_id],
                            "values": [previous[1], value],
                        }
                    )
                    continue
                assignments[key] = (lens_id, value)
                _set_position_path(effective[issue_id]["position"], field, value)
            effective[issue_id]["trace"].append(
                f"Matter Lens {lens_id}: {adjustment['reason']}"
            )

    instruction_assignments: dict[tuple[str, str], tuple[str, Any]] = {}
    instruction_ids: list[str] = []
    seen_instruction_ids: set[str] = set()
    instructions = activation.get("matterInstructions", [])
    if not isinstance(instructions, list):
        raise PlaybookError("matterInstructions must be a list")
    for instruction in instructions:
        if not isinstance(instruction, dict):
            raise PlaybookError("Each matter instruction must be an object")
        instruction_id = instruction.get("instructionId")
        issue_id = instruction.get("issueId")
        if not isinstance(instruction_id, str) or not instruction_id:
            raise PlaybookError("Each matter instruction needs an instructionId")
        if instruction_id in seen_instruction_ids:
            raise PlaybookError(f"Duplicate matter instruction: {instruction_id}")
        seen_instruction_ids.add(instruction_id)
        if not isinstance(issue_id, str) or issue_id not in effective:
            raise PlaybookError(f"Matter instruction targets unknown issue: {issue_id}")
        instruction_ids.append(instruction_id)
        changes = instruction.get("changes")
        if not isinstance(changes, dict) or not changes:
            raise PlaybookError(
                f"Matter instruction {instruction_id} needs non-empty changes"
            )
        for field, value in changes.items():
            key = (issue_id, field)
            previous = instruction_assignments.get(key)
            if previous and canonical_json_bytes(previous[1]) != canonical_json_bytes(
                value
            ):
                conflicts.append(
                    {
                        "issueId": issue_id,
                        "field": field,
                        "sources": [previous[0], instruction_id],
                        "values": [previous[1], value],
                    }
                )
                continue
            instruction_assignments[key] = (instruction_id, value)
            _set_position_path(effective[issue_id]["position"], field, value)
        effective[issue_id]["trace"].append(
            f"Matter instruction {instruction_id}: {instruction.get('reason', '')}"
        )

    payload: dict[str, Any] = {
        "artifactType": "effective-stance",
        "schemaVersion": "1.0",
        "playbookId": playbook["playbookId"],
        "playbookVersion": playbook["version"],
        "status": "blocked" if conflicts else "ready",
        "baseline": "standard-baseline",
        "activatedLenses": list(activated),
        "suggestedLenses": list(suggested),
        "matterInstructions": instruction_ids,
        "issues": list(effective.values()),
        "conflicts": conflicts,
    }
    payload["stanceSha256"] = json_sha256(payload)
    return payload


def build_markup_segments(original: str, proposed: str) -> list[dict[str, str]]:
    original_tokens = WORD_TOKEN.findall(original)
    proposed_tokens = WORD_TOKEN.findall(proposed)
    matcher = difflib.SequenceMatcher(
        a=original_tokens, b=proposed_tokens, autojunk=False
    )
    segments: list[dict[str, str]] = []

    def append(op: str, text: str) -> None:
        if not text:
            return
        if segments and segments[-1]["op"] == op:
            segments[-1]["text"] += text
        else:
            segments.append({"op": op, "text": text})

    for opcode, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        left = "".join(original_tokens[left_start:left_end])
        right = "".join(proposed_tokens[right_start:right_end])
        if opcode == "equal":
            append("equal", left)
        elif opcode == "delete":
            append("delete", left)
        elif opcode == "insert":
            append("insert", right)
        else:
            append("delete", left)
            append("insert", right)
    return segments


def reconstruct_markup(segments: Sequence[Mapping[str, str]]) -> tuple[str, str]:
    original: list[str] = []
    proposed: list[str] = []
    for segment in segments:
        if not isinstance(segment, Mapping):
            raise PlaybookError("Every markup segment must be an object")
        operation = segment.get("op")
        text = segment.get("text")
        if operation not in {"equal", "delete", "insert"}:
            raise PlaybookError(f"Unknown markup operation: {operation}")
        if not isinstance(text, str) or not text:
            raise PlaybookError("Every markup segment must contain non-empty text")
        if operation in {"equal", "delete"}:
            original.append(text)
        if operation in {"equal", "insert"}:
            proposed.append(text)
    return "".join(original), "".join(proposed)


def source_text_index(manifest: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    index: dict[tuple[str, str], str] = {}
    for document in manifest.get("documents", []):
        document_hash = document.get("sha256")
        for element in document.get("elements", []):
            index[(document_hash, element.get("elementId"))] = element.get(
                "sourceText", ""
            )
    return index


def _manifest_defined_terms(
    manifest: Mapping[str, Any], role_filter: set[str] | None = None
) -> list[dict[str, Any]]:
    terms: list[dict[str, Any]] = []
    for document in manifest.get("documents", []):
        if not isinstance(document, Mapping):
            continue
        if role_filter and document.get("sourceRole") not in role_filter:
            continue
        for term in document.get("definedTerms", []):
            if isinstance(term, dict):
                terms.append(copy.deepcopy(term))
    return terms


def build_term_map_skeleton(
    playbook_manifest: Mapping[str, Any],
    contract_manifest: Mapping[str, Any],
    playbook: Mapping[str, Any],
    run_id: str,
) -> dict[str, Any]:
    if not run_id:
        raise PlaybookError("run_id is required")
    playbook_errors = validate_playbook(playbook, require_approved=True)
    if playbook_errors:
        raise PlaybookError("; ".join(playbook_errors))
    playbook_manifest_hash = playbook_manifest.get("manifestSha256")
    contract_manifest_hash = contract_manifest.get("manifestSha256")
    if playbook.get("sourceManifestSha256") != playbook_manifest_hash:
        raise PlaybookError("playbook is bound to a different source manifest")
    if not isinstance(contract_manifest_hash, str):
        raise PlaybookError("contract manifest needs manifestSha256")
    if playbook_manifest_hash != manifest_content_sha256(playbook_manifest):
        raise PlaybookError("playbook manifest hash does not match its contents")
    if contract_manifest_hash != manifest_content_sha256(contract_manifest):
        raise PlaybookError("contract manifest hash does not match its contents")

    house_groups: dict[str, list[dict[str, Any]]] = {}
    contract_groups: dict[str, list[dict[str, Any]]] = {}
    house_docs = playbook_manifest.get("documents", [])
    has_template = any(
        isinstance(d, Mapping) and d.get("sourceRole") == "approved-template"
        for d in house_docs
    )
    house_terms = _manifest_defined_terms(
        playbook_manifest,
        role_filter={"approved-template"} if has_template else None,
    )
    for term in house_terms:
        house_groups.setdefault(term["normalizedTerm"], []).append(term)
    for term in _manifest_defined_terms(contract_manifest):
        contract_groups.setdefault(term["normalizedTerm"], []).append(term)

    entries: list[dict[str, Any]] = []
    for normalized_term in sorted(house_groups):
        house_candidates = house_groups[normalized_term]
        house_definition = house_candidates[0]
        house_texts = {
            _normalise_text(candidate["definitionText"]).casefold()
            for candidate in house_candidates
        }
        contract_candidates = contract_groups.get(normalized_term, [])
        contract_definition = contract_candidates[0] if contract_candidates else None
        contract_texts = {
            _normalise_text(candidate["definitionText"]).casefold()
            for candidate in contract_candidates
        }

        if len(house_texts) > 1:
            relation = "unresolved"
            basis = "not-assessed"
            action = "hard-stop"
            review = "pending"
            rationale = "House sources contain multiple definitions for this term."
        elif not contract_candidates:
            relation = "unresolved"
            basis = "not-assessed"
            action = "hard-stop"
            review = "pending"
            rationale = "No same-name counterparty definition was found."
        elif len(contract_texts) > 1 or house_texts != contract_texts:
            relation = "unresolved"
            basis = "not-assessed"
            action = "hard-stop"
            review = "pending"
            rationale = (
                "The same term label has different definition text; compare scope."
            )
        else:
            relation = "exact"
            basis = "deterministic-exact"
            action = "use-contract-term"
            review = "not-required"
            rationale = "The term label and normalized definition text match."

        entries.append(
            {
                "entryId": stable_id(
                    "term-map", playbook["playbookId"], normalized_term
                ),
                "houseDefinition": house_definition,
                "contractDefinition": contract_definition,
                "relation": relation,
                "decisionBasis": basis,
                "draftingAction": action,
                "rationale": rationale,
                "lawyerReview": review,
            }
        )

    return {
        "artifactType": "term-map",
        "schemaVersion": "1.0",
        "runId": run_id,
        "playbookId": playbook.get("playbookId", ""),
        "playbookVersion": playbook.get("version", ""),
        "playbookSourceManifestSha256": playbook_manifest_hash,
        "contractSourceManifestSha256": contract_manifest_hash,
        "entries": entries,
    }


def validate_term_map(term_map: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if term_map.get("artifactType") != "term-map":
        errors.append("artifactType must be term-map")
    if term_map.get("schemaVersion") != "1.0":
        errors.append("schemaVersion must be 1.0")
    for field in (
        "runId",
        "playbookId",
        "playbookVersion",
        "playbookSourceManifestSha256",
        "contractSourceManifestSha256",
    ):
        if not isinstance(term_map.get(field), str) or not term_map[field]:
            errors.append(f"{field} must be a non-empty string")
    for field in (
        "playbookSourceManifestSha256",
        "contractSourceManifestSha256",
    ):
        value = term_map.get(field)
        if isinstance(value, str) and value and SHA256.fullmatch(value) is None:
            errors.append(f"{field} must be a lowercase SHA-256 hash")
    entries = term_map.get("entries")
    if not isinstance(entries, list):
        return [*errors, "entries must be a list"]

    seen_terms: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            errors.append(f"entries[{index}] must be an object")
            continue
        label = str(entry.get("entryId") or f"entries[{index}]")
        if not isinstance(entry.get("entryId"), str) or not entry["entryId"]:
            errors.append(f"{label}: entryId must be a non-empty string")
        house = entry.get("houseDefinition")
        contract = entry.get("contractDefinition")
        if not isinstance(house, Mapping):
            errors.append(f"{label}: houseDefinition must be an object")
            continue
        normalized_term = house.get("normalizedTerm")
        if not isinstance(normalized_term, str) or not normalized_term:
            errors.append(f"{label}: house normalizedTerm is required")
        elif normalized_term in seen_terms:
            errors.append(f"duplicate house term: {normalized_term}")
        else:
            seen_terms.add(normalized_term)
        for field in ("term", "definitionText", "documentSha256", "elementId"):
            if not isinstance(house.get(field), str) or not house[field]:
                errors.append(f"{label}: house {field} is required")
        house_hash = house.get("documentSha256")
        if (
            isinstance(house_hash, str)
            and house_hash
            and SHA256.fullmatch(house_hash) is None
        ):
            errors.append(f"{label}: house documentSha256 is invalid")
        if isinstance(house.get("term"), str) and normalized_term != _normalise_term(
            house["term"]
        ):
            errors.append(f"{label}: house normalizedTerm does not match term")
        if contract is not None and not isinstance(contract, Mapping):
            errors.append(f"{label}: contractDefinition must be an object or null")
            continue
        if isinstance(contract, Mapping):
            for field in (
                "term",
                "normalizedTerm",
                "definitionText",
                "documentSha256",
                "elementId",
            ):
                if not isinstance(contract.get(field), str) or not contract[field]:
                    errors.append(f"{label}: contract {field} is required")
            contract_hash = contract.get("documentSha256")
            if (
                isinstance(contract_hash, str)
                and contract_hash
                and SHA256.fullmatch(contract_hash) is None
            ):
                errors.append(f"{label}: contract documentSha256 is invalid")
            contract_term = contract.get("term")
            contract_normalized = contract.get("normalizedTerm")
            if isinstance(
                contract_term, str
            ) and contract_normalized != _normalise_term(contract_term):
                errors.append(f"{label}: contract normalizedTerm does not match term")

        relation = entry.get("relation")
        basis = entry.get("decisionBasis")
        action = entry.get("draftingAction")
        review = entry.get("lawyerReview")
        if relation == "exact":
            if not isinstance(contract, Mapping):
                errors.append(f"{label}: exact mapping needs a contract definition")
            else:
                same_term = normalized_term == contract.get("normalizedTerm")
                same_definition = (
                    _normalise_text(str(house.get("definitionText", ""))).casefold()
                    == _normalise_text(
                        str(contract.get("definitionText", ""))
                    ).casefold()
                )
                if not same_term or not same_definition:
                    errors.append(f"{label}: exact mapping is not textually exact")
            if basis != "deterministic-exact" or action != "use-contract-term":
                errors.append(f"{label}: exact mapping has invalid controls")
        elif relation == "equivalent":
            if not isinstance(contract, Mapping):
                errors.append(f"{label}: equivalent mapping needs both definitions")
            if basis not in {"model-cited", "lawyer-confirmed"}:
                errors.append(f"{label}: equivalent mapping needs cited judgment")
            if action != "use-contract-term":
                errors.append(f"{label}: equivalent mapping must use contract term")
        elif relation == "undefined":
            if contract is not None:
                errors.append(
                    f"{label}: undefined mapping cannot cite a contract definition"
                )
            if action != "insert-definition":
                errors.append(f"{label}: undefined mapping must insert a definition")
            if basis not in {"model-cited", "lawyer-confirmed"}:
                errors.append(f"{label}: undefined mapping needs cited judgment")
        elif relation == "defined-differently":
            if not isinstance(contract, Mapping):
                errors.append(f"{label}: scope difference needs both definitions")
            if basis not in {"model-cited", "lawyer-confirmed"}:
                errors.append(f"{label}: scope difference needs cited judgment")
            if action != "hard-stop":
                errors.append(f"{label}: scope difference must hard-stop drafting")
        elif relation == "unresolved":
            if basis != "not-assessed" or action != "hard-stop":
                errors.append(f"{label}: unresolved mapping must remain a hard stop")
        else:
            errors.append(f"{label}: invalid relation")
        if not isinstance(entry.get("rationale"), str) or not entry["rationale"]:
            errors.append(f"{label}: rationale is required")
        if review not in {"pending", "confirmed", "not-required"}:
            errors.append(f"{label}: invalid lawyerReview")
    return errors


def adapt_drafting_to_term_map(
    proposed_text: str, term_map: Mapping[str, Any]
) -> dict[str, Any]:
    errors = validate_term_map(term_map)
    if errors:
        raise PlaybookError("; ".join(errors))
    adapted = proposed_text
    substitutions: list[dict[str, str]] = []
    insertions: list[dict[str, Any]] = []
    hard_stops: list[dict[str, str]] = []
    entries = sorted(
        term_map["entries"],
        key=lambda entry: len(entry["houseDefinition"]["term"]),
        reverse=True,
    )
    for entry in entries:
        house = entry["houseDefinition"]
        house_term = house["term"]
        pattern = re.compile(rf"(?<!\w){re.escape(house_term)}(?!\w)")
        if not pattern.search(adapted):
            continue
        relation = entry["relation"]
        if relation in {"exact", "equivalent"}:
            contract_term = entry["contractDefinition"]["term"]
            updated = pattern.sub(contract_term, adapted)
            if updated != adapted:
                substitutions.append(
                    {"houseTerm": house_term, "contractTerm": contract_term}
                )
                adapted = updated
        elif relation == "undefined":
            insertions.append(
                {
                    "houseTerm": house_term,
                    "suggestedDefinition": house["definitionText"],
                    "documentSha256": house["documentSha256"],
                    "elementId": house["elementId"],
                }
            )
        else:
            hard_stops.append(
                {
                    "houseTerm": house_term,
                    "relation": relation,
                    "reason": entry["rationale"],
                }
            )
    return {
        "artifactType": "term-adapted-drafting",
        "schemaVersion": "1.0",
        "status": "blocked" if hard_stops else "ready",
        "originalProposedText": proposed_text,
        "adaptedProposedText": proposed_text if hard_stops else adapted,
        "substitutions": [] if hard_stops else substitutions,
        "definitionInsertions": insertions,
        "hardStops": hard_stops,
    }


def validate_structural_warnings(warnings: Any) -> list[str]:
    """Validate the optional ``structuralWarnings`` block of an issues list."""
    if warnings is None:
        return []
    if not isinstance(warnings, list):
        return ["structuralWarnings must be a list"]
    errors: list[str] = []
    for index, warning in enumerate(warnings):
        label = f"structuralWarnings[{index}]"
        if not isinstance(warning, dict):
            errors.append(f"{label} must be an object")
            continue
        if warning.get("category") not in STRUCTURAL_WARNING_CATEGORIES:
            errors.append(f"{label}: invalid category")
        summary = warning.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            errors.append(f"{label}: summary must be a non-empty string")
        if "detail" in warning and not isinstance(warning.get("detail"), str):
            errors.append(f"{label}: detail must be a string")
        if not isinstance(warning.get("clauseRef"), (str, type(None))):
            errors.append(f"{label}: clauseRef must be a string or null")
        related = warning.get("relatedIssueIds", [])
        if not isinstance(related, list) or any(
            not isinstance(item, str) or not item for item in related
        ):
            errors.append(f"{label}: relatedIssueIds must be a list of issue IDs")
    return errors


def validate_issues_list(
    issues_list: Mapping[str, Any],
    source_index: Mapping[tuple[str, str], str] | None = None,
    source_manifest_sha256: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if issues_list.get("artifactType") != "issues-list":
        errors.append("artifactType must be issues-list")
    if issues_list.get("schemaVersion") != "1.0":
        errors.append("schemaVersion must be 1.0")
    for field in (
        "runId",
        "sourceManifestSha256",
        "playbookId",
        "playbookVersion",
        "effectiveStanceSha256",
    ):
        if not isinstance(issues_list.get(field), str) or not issues_list[field]:
            errors.append(f"{field} must be a non-empty string")
    for field in ("sourceManifestSha256", "effectiveStanceSha256"):
        value = issues_list.get(field)
        if isinstance(value, str) and value and SHA256.fullmatch(value) is None:
            errors.append(f"{field} must be a lowercase SHA-256 hash")
    if (
        source_manifest_sha256 is not None
        and issues_list.get("sourceManifestSha256") != source_manifest_sha256
    ):
        errors.append("issues list is bound to a different source manifest")
    if "contractName" in issues_list and not isinstance(
        issues_list.get("contractName"), str
    ):
        errors.append("contractName must be a string")
    if "generatedAt" in issues_list:
        try:
            parse_iso_timestamp(issues_list.get("generatedAt"))
        except ValueError:
            errors.append("generatedAt must be an ISO 8601 timestamp")
    errors.extend(validate_structural_warnings(issues_list.get("structuralWarnings")))
    known_element_ids = (
        {element_id for _, element_id in source_index} if source_index else None
    )
    errors.extend(
        validate_element_sweep(issues_list.get("elementSweep"), known_element_ids)
    )
    seen: set[str] = set()
    issues = issues_list.get("issues")
    if not isinstance(issues, list):
        return [*errors, "issues must be a list"]
    for index, issue in enumerate(issues):
        if not isinstance(issue, dict):
            errors.append(f"issues[{index}] must be an object")
            continue
        issue_id = issue.get("issueId")
        label = str(issue_id or f"issues[{index}]")
        if not isinstance(issue_id, str) or not issue_id:
            errors.append(f"{label}: issueId must be a non-empty string")
        if isinstance(issue_id, str):
            if issue_id in seen:
                errors.append(f"duplicate issueId: {issue_id}")
            seen.add(issue_id)
        for field in ("documentSha256", "elementId", "rationale"):
            if not isinstance(issue.get(field), str) or not issue[field]:
                errors.append(f"{label}: {field} must be a non-empty string")
        document_hash = issue.get("documentSha256")
        if (
            isinstance(document_hash, str)
            and document_hash
            and SHA256.fullmatch(document_hash) is None
        ):
            errors.append(f"{label}: documentSha256 must be a lowercase SHA-256 hash")
        if not isinstance(issue.get("playbookIssueId"), (str, type(None))):
            errors.append(f"{label}: playbookIssueId must be a string or null")
        if not isinstance(issue.get("clauseRef"), (str, type(None))):
            errors.append(f"{label}: clauseRef must be a string or null")
        for field in ("originalText", "proposedText"):
            if not isinstance(issue.get(field), str):
                errors.append(f"{label}: {field} must be a string")
        if issue.get("classification") not in REVIEW_CLASSIFICATIONS:
            errors.append(f"{label}: invalid classification")
        if issue.get("materiality") not in MATERIALITIES:
            errors.append(f"{label}: invalid materiality")
        if issue.get("draftingProvenance") not in DRAFTING_PROVENANCE:
            errors.append(f"{label}: invalid draftingProvenance")
        if issue.get("lawyerReview") not in LAWYER_REVIEW_STATES:
            errors.append(f"{label}: invalid lawyerReview")
        if "externalComment" in issue and not isinstance(
            issue.get("externalComment"), str
        ):
            errors.append(f"{label}: externalComment must be a string")
        segments = issue.get("markupSegments")
        if not isinstance(segments, list):
            errors.append(f"{label}: markupSegments must be a list")
            continue
        try:
            reconstructed_original, reconstructed_proposed = reconstruct_markup(
                segments
            )
        except PlaybookError as exc:
            errors.append(f"{label}: {exc}")
            continue
        if reconstructed_original != issue.get("originalText"):
            errors.append(f"{label}: markup does not reconstruct exact originalText")
        if reconstructed_proposed != issue.get("proposedText"):
            errors.append(f"{label}: markup does not reconstruct exact proposedText")
        classification = issue.get("classification")
        if (
            classification in ACTIONABLE_WITH_DRAFTING
            and issue.get("proposedText") is None
        ):
            errors.append(f"{label}: actionable issue needs proposedText")
        if classification in ACTIONABLE_WITH_DRAFTING and not segments:
            errors.append(f"{label}: actionable issue needs visible markup")
        if source_index is not None:
            document_hash = issue.get("documentSha256")
            element_id = issue.get("elementId")
            if not isinstance(document_hash, str) or not isinstance(element_id, str):
                continue
            key = (document_hash, element_id)
            source_text = source_index.get(key)
            if source_text is None:
                errors.append(f"{label}: source anchor does not exist in manifest")
            elif issue.get("originalText") and _normalise_text(
                issue["originalText"]
            ) not in _normalise_text(source_text):
                errors.append(
                    f"{label}: originalText is not present at the source anchor"
                )
    return errors


def build_coverage_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    documents = copy.deepcopy(payload.get("documents", {}))
    elements = copy.deepcopy(payload.get("elements", {}))
    rules = copy.deepcopy(payload.get("rules", {}))

    def check_counts(
        label: str, counts: Mapping[str, Any], fields: Sequence[str]
    ) -> None:
        values = [counts.get(field) for field in fields]
        expected = counts.get("expected")
        if type(expected) is not int or any(type(value) is not int for value in values):
            errors.append(f"{label}: counts must be integers")
            return
        expected_count = cast(int, expected)
        accounted_counts = [cast(int, value) for value in values]
        if any(value < 0 for value in [expected_count, *accounted_counts]):
            errors.append(f"{label}: counts cannot be negative")
        accounted = sum(accounted_counts)
        if expected_count != accounted:
            errors.append(
                f"{label}: expected {expected_count} does not equal "
                f"accounted {accounted}"
            )

    for label, counts, fields in (
        ("documents", documents, ("completed", "parked", "unreadable")),
        ("elements", elements, ("completed", "parked", "unreadable")),
        ("rules", rules, ("evaluated", "notApplicable", "blocked")),
    ):
        if not isinstance(counts, Mapping):
            errors.append(f"{label}: counts must be an object")
        elif not counts:
            errors.append(f"{label}: counts mapping cannot be empty")
        else:
            check_counts(label, counts, fields)

    has_evidence = bool(
        isinstance(documents, Mapping)
        and documents
        and isinstance(elements, Mapping)
        and elements
        and isinstance(rules, Mapping)
        and rules
    )
    return {
        "artifactType": "coverage-receipt",
        "schemaVersion": "1.0",
        "runId": payload.get("runId", "unknown-run"),
        "documents": documents,
        "elements": elements,
        "rules": rules,
        "reconciled": not errors and has_evidence,
        "errors": errors,
    }


def build_receipt(
    playbook: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    errors = validate_playbook(playbook, source_manifest=manifest)
    if manifest.get("artifactType") != "source-manifest":
        errors.append("manifest artifactType must be source-manifest")
    if manifest.get("schemaVersion") != "1.0":
        errors.append("manifest schemaVersion must be 1.0")
    stored_manifest_hash = manifest.get("manifestSha256")
    calculated_manifest_hash = manifest_content_sha256(manifest)
    if stored_manifest_hash != calculated_manifest_hash:
        errors.append("manifestSha256 does not match the manifest contents")
    if playbook.get("sourceManifestSha256") != stored_manifest_hash:
        errors.append("playbook is bound to a different source manifest")
    raw_issues = playbook.get("issues", [])
    issues = raw_issues if isinstance(raw_issues, list) else []
    approved = sum(
        1
        for issue in issues
        if isinstance(issue, Mapping) and issue.get("status") == "approved"
    )
    candidate = sum(
        1
        for issue in issues
        if isinstance(issue, Mapping) and issue.get("status") == "candidate"
    )
    return {
        "artifactType": "build-receipt",
        "schemaVersion": "1.0",
        "playbookId": playbook.get("playbookId", ""),
        "playbookVersion": playbook.get("version", ""),
        "sourceManifestSha256": manifest.get("manifestSha256", ""),
        "playbookSha256": json_sha256(playbook),
        "approvedIssueCount": approved,
        "candidateIssueCount": candidate,
        "validationErrors": errors,
    }


def _issues_by_severity(
    issues: Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Order issues by materiality: high, medium, low, none (schema order)."""

    return sorted(
        issues,
        key=lambda issue: MATERIALITY_ORDER.get(
            str(issue.get("materiality") or "none").lower(),
            len(MATERIALITY_ORDER),
        ),
    )


def _structural_warning_lines(warnings: Any) -> list[tuple[str, str]]:
    """Return (label, text) pairs for each valid structural warning."""
    lines: list[tuple[str, str]] = []
    if not isinstance(warnings, list):
        return lines
    for warning in warnings:
        if not isinstance(warning, Mapping):
            continue
        category = str(warning.get("category") or "other")
        label = STRUCTURAL_WARNING_LABELS.get(category, "Structural Warning")
        text = str(warning.get("summary") or "").strip()
        clause_ref = warning.get("clauseRef")
        if clause_ref:
            text = f"{text} (clause {clause_ref})"
        detail = str(warning.get("detail") or "").strip()
        if detail:
            text = f"{text} {detail}"
        lines.append((label, text))
    return lines


def _render_structural_warnings_html(warnings: Any) -> str:
    lines = _structural_warning_lines(warnings)
    if not lines:
        return ""
    items = "".join(
        f"<li><strong>{html.escape(label)}:</strong> {html.escape(text)}</li>"
        for label, text in lines
    )
    return f'<section class="warnings"><h2>Structural Warnings</h2><ul>{items}</ul></section>'


def render_issues_html(issues_list: Mapping[str, Any]) -> str:
    errors = validate_issues_list(issues_list)
    if errors:
        raise PlaybookError("; ".join(errors))

    cards: list[str] = []
    for issue in _issues_by_severity(issues_list.get("issues", [])):
        rendered_segments: list[str] = []
        for segment in issue["markupSegments"]:
            text = html.escape(segment["text"])
            if segment["op"] == "delete":
                rendered_segments.append(f"<del>{text}</del>")
            elif segment["op"] == "insert":
                rendered_segments.append(f"<ins>{text}</ins>")
            else:
                rendered_segments.append(f"<span>{text}</span>")
        clause = html.escape(issue.get("clauseRef") or "Unnumbered provision")
        class_label = get_classification_label(str(issue.get("classification", "")))
        ext_comment = str(issue.get("externalComment") or "").strip()
        mat_label = str(issue.get("materiality", "")).upper()
        prov_label = str(issue.get("draftingProvenance", "")).replace("-", " ").title()
        comment_html = (
            f'<p class="comment"><strong>Negotiation Comment:</strong> <em>"{html.escape(ext_comment)}"</em></p>'
            if ext_comment
            else ""
        )
        cards.append(
            "".join(
                [
                    '<article class="issue">',
                    f"<h2>{html.escape(issue['issueId'])}: {clause}</h2>",
                    '<div class="badges">',
                    f"<span>{html.escape(class_label)}</span>",
                    f"<span>{html.escape(mat_label)}</span>",
                    f"<span>{html.escape(prov_label)}</span>",
                    "</div>",
                    f"<p><strong>Internal Risk / Guidance:</strong> {html.escape(issue['rationale'])}</p>",
                    comment_html,
                    '<h3>Suggested markup</h3><div class="markup">',
                    "".join(rendered_segments),
                    "</div>",
                    "<details><summary>Exact source text</summary>",
                    f"<pre>{html.escape(issue['originalText'])}</pre></details>",
                    "<details><summary>Clean proposed text</summary>",
                    f"<pre>{html.escape(issue['proposedText'])}</pre></details>",
                    "</article>",
                ]
            )
        )

    return "".join(
        [
            '<!doctype html><html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            "<title>Playbook Review Issues</title><style>",
            "body{font-family:system-ui,sans-serif;margin:0;background:#f5f5f3;color:#252525}",
            "main{max-width:980px;margin:auto;padding:32px 20px}"
            ".issue{background:white;",
            "border:1px solid #ddd;border-radius:10px;padding:22px;margin:18px 0}",
            ".badges{display:flex;gap:8px;flex-wrap:wrap}.badges span{background:#eee;",
            "padding:3px 8px;border-radius:99px;font-size:12px}"
            ".markup{white-space:pre-wrap;",
            "line-height:1.7;padding:14px;background:#fafafa;border-radius:6px}",
            "del{background:#fee2e2;color:#8b1a1a}ins{background:#dcfce7;color:#166534;",
            "text-decoration:none;border-bottom:2px solid #166534}"
            "pre{white-space:pre-wrap}",
            ".warnings{background:#fff7ed;border:1px solid #fdba74;border-radius:10px;",
            "padding:16px 22px;margin:18px 0}.warnings h2{margin:0 0 8px;font-size:16px}",
            "</style></head><body><main><h1>Playbook Review Issues</h1>",
            f"<p>Run {html.escape(str(issues_list.get('runId', '')))} · ",
            f"{len(issues_list.get('issues', []))} issues</p>",
            _render_structural_warnings_html(issues_list.get("structuralWarnings")),
            *cards,
            "</main></body></html>",
        ]
    )


def render_playbook_markdown(
    playbook: Mapping[str, Any],
    source_manifest: Mapping[str, Any] | None = None,
) -> str:
    """Render an approved or candidate playbook to clean Markdown.

    Presents issues, preferred positions, approved fallbacks, red lines,
    matter lenses, and formats sources as an indented bulleted list.
    """
    errors = validate_playbook(playbook)
    if errors:
        raise PlaybookError("; ".join(errors))

    doc_map: dict[str, str] = {}
    if source_manifest and isinstance(source_manifest.get("documents"), list):
        for doc in source_manifest["documents"]:
            sha = doc.get("sha256") or doc.get("documentSha256")
            name = doc.get("fileName") or doc.get("originalPath")
            if sha and name:
                doc_map[str(sha)] = Path(str(name)).name

    lines: list[str] = []
    title = str(
        playbook.get("title") or playbook.get("playbookName") or "Contract Playbook"
    )
    version = str(playbook.get("version", "1.0.0"))
    status = str(playbook.get("status", "draft"))
    perspective = str(playbook.get("perspective", "unspecified"))
    gov_law = str(playbook.get("governingLaw") or "unspecified")
    agreement_family = str(playbook.get("agreementFamily") or "unspecified")
    manifest_sha = str(playbook.get("sourceManifestSha256") or "")

    lines.append(f"# {title}")
    lines.append("")
    if status == "approved":
        lines.append(
            f"> **Operative Playbook (v{version}):** Approved for use with `/playbook-review`."
        )
    else:
        lines.append(
            f"> **Candidate Playbook (v{version}):** Pending lawyer approval. Candidate entries remain non-operative."
        )
    lines.append("")
    lines.append(f"- **Playbook ID:** `{playbook.get('playbookId', '')}`")
    lines.append(f"- **Version:** `{version}`")
    lines.append(f"- **Status:** `{status}`")
    lines.append(f"- **Perspective:** {perspective}")
    lines.append(f"- **Agreement Family:** {agreement_family}")
    lines.append(f"- **Governing Law:** {gov_law}")
    if manifest_sha:
        lines.append(f"- **Source Manifest SHA-256:** `{manifest_sha}`")
    lines.append("")

    matter_lenses = playbook.get("matterLenses", [])
    if matter_lenses and isinstance(matter_lenses, list):
        lines.append("## Matter Lenses")
        lines.append("")
        for lens in matter_lenses:
            if not isinstance(lens, dict):
                continue
            lens_id = str(lens.get("lensId", ""))
            label = str(lens.get("label") or lens.get("name") or lens_id)
            desc = str(lens.get("description", ""))
            trigger = str(lens.get("triggerConditions") or lens.get("trigger") or "")
            lines.append(f"### Lens: {label} (`{lens_id}`)")
            lines.append("")
            if desc:
                lines.append(f"- **Description:** {desc}")
            if trigger:
                lines.append(f"- **Trigger Conditions:** {trigger}")
            adjustments = lens.get("adjustments", [])
            if isinstance(adjustments, list) and adjustments:
                lines.append(
                    f"- **Adjustments:** {len(adjustments)} issue modification(s)"
                )
            lines.append("")

    lines.append("## Issues and Positions")
    lines.append("")

    for issue in playbook.get("issues", []):
        if not isinstance(issue, dict):
            continue
        issue_id = str(issue.get("issueId", ""))
        topic = str(issue.get("topic", ""))
        issue_status = str(issue.get("status", "candidate"))
        base = issue.get("basePosition", {})
        if not isinstance(base, dict):
            base = {}
        priority = str(base.get("priority", "medium"))
        summary = str(base.get("summary", ""))

        header_text = f"{topic} (`{issue_id}`)" if topic else f"`{issue_id}`"
        lines.append(f"### {header_text}")
        lines.append("")
        lines.append(f"- **Status:** `{issue_status}`")
        lines.append(f"- **Priority:** `{priority}`")
        if summary:
            lines.append(f"- **Summary:** {summary}")
        lines.append("")

        pref = base.get("preferred", {})
        if isinstance(pref, dict):
            pref_summary = str(pref.get("summary", ""))
            pref_text = pref.get("text")
            lines.append("#### Preferred Position")
            lines.append("")
            if pref_text:
                if pref_summary:
                    lines.append(f"**Position:** {pref_summary}")
                    lines.append("")
                lines.append(f"> {str(pref_text).strip()}")
                lines.append("")
            elif pref_summary:
                lines.append(f"**Policy Guidance:** {pref_summary}")
                lines.append("")

        fallbacks = base.get("fallbacks", [])
        if isinstance(fallbacks, list) and fallbacks:
            fb_header = (
                "Approved Fallbacks"
                if issue_status == "approved"
                else "Candidate Fallbacks"
            )
            lines.append(f"#### {fb_header}")
            lines.append("")
            for fb in fallbacks:
                if not isinstance(fb, dict):
                    continue
                rank = fb.get("rank", 1)
                cond = str(fb.get("condition", ""))
                wording = fb.get("wording", {})
                fb_summary = ""
                fb_text = None
                if isinstance(wording, dict):
                    fb_summary = str(wording.get("summary") or "")
                    fb_text = wording.get("text")
                else:
                    fb_summary = str(fb.get("summary", ""))

                rank_header = (
                    f"**Fallback {rank}**"
                    + (f" (Condition: {cond})" if cond else "")
                    + ":"
                )
                lines.append(rank_header)
                if fb_summary and fb_summary != fb_text:
                    lines.append(fb_summary)
                if fb_text:
                    lines.append("")
                    lines.append(f"> {str(fb_text).strip()}")
                lines.append("")

        red_line = base.get("redLine")
        if red_line:
            lines.append("#### Red Line")
            lines.append("")
            lines.append(f"{red_line}")
            lines.append("")

        adjustments = issue.get("lensAdjustments")
        if isinstance(adjustments, dict) and adjustments:
            lines.append("#### Matter Lens Adjustments")
            lines.append("")
            for lens_key, adj in adjustments.items():
                lines.append(f"- **`{lens_key}`:** {adj}")
            lines.append("")

        provenance = issue.get("provenance", [])
        if isinstance(provenance, list) and provenance:
            lines.append("#### Sources")
            lines.append("")
            for prov in provenance:
                if not isinstance(prov, dict):
                    continue
                doc_sha = str(prov.get("documentSha256") or prov.get("sha256") or "")
                file_name = doc_map.get(doc_sha) or str(prov.get("fileName") or "")
                if not file_name:
                    file_name = (doc_sha[:12] + "...") if doc_sha else "unknown-source"
                element_id = str(prov.get("elementId", ""))
                source_role = str(prov.get("sourceRole", ""))
                clause_ref = prov.get("clauseRef") or prov.get("clause")

                parts: list[str] = []
                if clause_ref:
                    parts.append(f"cl. {clause_ref}")
                if element_id:
                    parts.append(f"`{element_id}`")
                if source_role:
                    parts.append(f"role: {source_role}")

                details = f" ({', '.join(parts)})" if parts else ""
                lines.append(f"- `{file_name}`{details}")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_playbook_html(playbook: Mapping[str, Any]) -> str:
    errors = validate_playbook(playbook)
    if errors:
        raise PlaybookError("; ".join(errors))

    cards: list[str] = []
    for issue in playbook.get("issues", []):
        base = issue.get("basePosition", {})
        preferred = base.get("preferred", {})
        pref_text = html.escape(
            preferred.get("text", preferred.get("summary", "None"))
            if isinstance(preferred, dict)
            else "None"
        )
        fallbacks = base.get("fallbacks", [])
        fb_items = []
        for fb in fallbacks:
            fb_wording = fb.get("wording", {})
            fb_text = html.escape(
                fb_wording.get("text", fb.get("summary", "None"))
                if isinstance(fb_wording, dict)
                else str(fb.get("summary", "None"))
            )
            fb_items.append(
                f"<li><strong>Rank {fb.get('rank', 1)}:</strong> {fb_text}</li>"
            )
        fb_html = f"<ul>{''.join(fb_items)}</ul>" if fb_items else "<p>None</p>"
        red_line = html.escape(str(base.get("redLine") or "None"))
        priority = html.escape(str(base.get("priority") or "medium"))
        rationale = html.escape(str(base.get("summary") or issue.get("topic") or ""))

        topic_str = str(issue.get("topic") or "")
        issue_id_str = str(issue.get("issueId") or "")
        title_text = (
            f"{html.escape(topic_str)} ({html.escape(issue_id_str)})"
            if topic_str
            else html.escape(issue_id_str)
        )
        cards.append(
            "".join(
                [
                    '<article class="issue">',
                    f"<h2>{title_text}</h2>",
                    '<div class="badges">',
                    f"<span>Status: {html.escape(issue.get('status', ''))}</span>",
                    f"<span>Priority: {priority}</span>",
                    "</div>",
                    f"<p><strong>Summary:</strong> {rationale}</p>",
                    f"<div class='section'><h3>Preferred Position</h3><p>{pref_text}</p></div>",
                    f"<div class='section'><h3>Approved Fallbacks</h3>{fb_html}</div>",
                    f"<div class='section'><h3>Red Line</h3><p>{red_line}</p></div>",
                    "</article>",
                ]
            )
        )

    lenses_html = []
    for lens in playbook.get("matterLenses", []):
        adj_count = len(lens.get("adjustments", []))
        lenses_html.append(
            f"<li><strong>{html.escape(lens.get('label', lens.get('lensId', '')))}</strong>: "
            f"{html.escape(lens.get('description', ''))} ({adj_count} adjustment{'s' if adj_count != 1 else ''})</li>"
        )
    lenses_section = (
        f"<section class='lenses'><h2>Matter Lenses</h2><ul>{''.join(lenses_html)}</ul></section>"
        if lenses_html
        else ""
    )

    return "".join(
        [
            '<!doctype html><html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            f"<title>{html.escape(playbook.get('title', 'Contract Playbook'))}</title><style>",
            "body{font-family:system-ui,sans-serif;margin:0;background:#f5f5f3;color:#252525}",
            "main{max-width:980px;margin:auto;padding:32px 20px}",
            ".issue{background:white;border:1px solid #ddd;border-radius:10px;padding:22px;margin:18px 0}",
            ".badges{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.badges span{background:#eee;",
            "padding:3px 8px;border-radius:99px;font-size:12px}",
            ".section{margin:12px 0}.section h3{margin:6px 0;font-size:14px;color:#555}",
            ".lenses{background:white;border:1px solid #ddd;border-radius:10px;padding:22px;margin:18px 0}",
            "</style></head><body><main>",
            f"<h1>{html.escape(playbook.get('title', 'Contract Playbook'))}</h1>",
            f"<p>Playbook ID: {html.escape(playbook.get('playbookId', ''))} · Version: {html.escape(playbook.get('version', ''))} · ",
            f"Perspective: {html.escape(playbook.get('perspective', ''))} · ",
            f"{len(playbook.get('issues', []))} issues</p>",
            lenses_section,
            *cards,
            "</main></body></html>",
        ]
    )


def build_review_receipt(
    issues_list: Mapping[str, Any],
    coverage_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    raw_issues = issues_list.get("issues", [])
    issues = raw_issues if isinstance(raw_issues, list) else []
    counts: dict[str, int] = {}
    for issue in issues:
        if isinstance(issue, Mapping):
            c = str(issue.get("classification", "unknown"))
            counts[c] = counts.get(c, 0) + 1
    reconciled = (
        bool(coverage_receipt.get("reconciled", False))
        if (coverage_receipt and isinstance(coverage_receipt, Mapping))
        else False
    )
    return {
        "artifactType": "review-receipt",
        "schemaVersion": "1.0",
        "runId": issues_list.get("runId", ""),
        "playbookId": issues_list.get("playbookId", ""),
        "playbookVersion": issues_list.get("playbookVersion", ""),
        "sourceManifestSha256": issues_list.get("sourceManifestSha256", ""),
        "effectiveStanceSha256": issues_list.get("effectiveStanceSha256", ""),
        "issuesCount": len(issues),
        "classificationCounts": counts,
        "reconciled": reconciled,
    }


def seal_playbook(
    playbook: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    version: str | None = None,
    package_path: Path | str | None = None,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    """Seal an approved playbook package, creating an immutable verified version.

    Validates all evidential anchors against the manifest, checks cross-issue
    dependencies, sets status to approved, builds the receipt, renders markdown,
    and registers the playbook.
    """
    sealed = copy.deepcopy(dict(playbook))
    if version:
        sealed["version"] = version
    sealed["status"] = "approved"

    for issue in sealed.get("issues", []):
        if not isinstance(issue, dict):
            continue
        if issue.get("status") == "approved":
            base = issue.get("basePosition")
            if isinstance(base, dict):
                pref = base.get("preferred")
                if isinstance(pref, dict) and pref.get("approvalStatus") != "approved":
                    pref["approvalStatus"] = "approved"
                for fb in base.get("fallbacks", []):
                    if isinstance(fb, dict):
                        wording = fb.get("wording")
                        if (
                            isinstance(wording, dict)
                            and wording.get("approvalStatus") != "approved"
                        ):
                            wording["approvalStatus"] = "approved"

    errors = validate_playbook(
        sealed, require_approved=True, source_manifest=source_manifest
    )
    if errors:
        raise PlaybookError(
            f"Cannot seal playbook due to validation errors: {'; '.join(errors)}"
        )

    receipt = build_receipt(sealed, source_manifest)
    if receipt.get("validationErrors"):
        raise PlaybookError(
            f"Cannot seal playbook due to build receipt errors: {'; '.join(receipt['validationErrors'])}"
        )

    markdown = render_playbook_markdown(sealed, source_manifest)

    registry_entry = None
    if package_path:
        registry_entry = register_playbook(sealed, package_path, registry_path)

    return {
        "playbook": sealed,
        "receipt": receipt,
        "markdown": markdown,
        "registryEntry": registry_entry,
    }


def populate_issues_markup(issues_list: dict[str, Any]) -> dict[str, Any]:
    if not issues_list.get("generatedAt"):
        issues_list["generatedAt"] = utc_now()
    for issue in issues_list.get("issues", []):
        if isinstance(issue, dict):
            orig = issue.get("originalText", "")
            prop = issue.get("proposedText")
            if prop is not None and not issue.get("markupSegments"):
                issue["markupSegments"] = build_markup_segments(orig, prop)
    return issues_list


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def validate_playbook_registry(registry: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if registry.get("artifactType") != "playbook-registry":
        errors.append("artifactType must be playbook-registry")
    if registry.get("schemaVersion") != "1.0":
        errors.append("schemaVersion must be 1.0")
    playbooks = registry.get("playbooks")
    if not isinstance(playbooks, list):
        return [*errors, "playbooks must be a list"]
    for index, entry in enumerate(playbooks):
        if not isinstance(entry, dict):
            errors.append(f"playbooks[{index}] must be an object")
            continue
        for field in (
            "playbookId",
            "playbookName",
            "version",
            "sealedAt",
            "packagePath",
        ):
            val = entry.get(field)
            if not isinstance(val, str) or not val.strip():
                errors.append(f"playbooks[{index}]: {field} must be a non-empty string")
        issue_count = entry.get("issueCount")
        if issue_count is not None and (
            not isinstance(issue_count, int)
            or isinstance(issue_count, bool)
            or issue_count < 0
        ):
            errors.append(
                f"playbooks[{index}]: issueCount must be a non-negative integer"
            )
    return errors


def _version_key(version: object) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(version)))


def register_playbook(
    playbook: Mapping[str, Any],
    package_path: Path | str,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    playbook_id = playbook.get("playbookId")
    if not isinstance(playbook_id, str) or not playbook_id:
        raise PlaybookError("Playbook missing valid playbookId")
    if playbook.get("status") != "approved":
        raise PlaybookError(
            "Only approved playbooks may be registered; "
            f"status is {playbook.get('status')!r}"
        )

    resolved_pkg = Path(package_path).resolve()
    if registry_path:
        target_registry = registry_path.resolve()
    elif (resolved_pkg.parent / DEFAULT_REGISTRY_NAME).is_file():
        target_registry = resolved_pkg.parent / DEFAULT_REGISTRY_NAME
    elif (resolved_pkg / DEFAULT_REGISTRY_NAME).is_file():
        target_registry = resolved_pkg / DEFAULT_REGISTRY_NAME
    elif Path(DEFAULT_REGISTRY_NAME).is_file():
        target_registry = Path(DEFAULT_REGISTRY_NAME).resolve()
    else:
        target_registry = resolved_pkg.parent / DEFAULT_REGISTRY_NAME

    registry: dict[str, Any]
    if target_registry.is_file():
        try:
            registry = load_json(target_registry)
            if registry.get("artifactType") != "playbook-registry":
                raise PlaybookError(
                    f"Target registry at {target_registry} has invalid artifactType: {registry.get('artifactType')!r}"
                )
        except Exception as exc:
            backup_name = f"{target_registry.stem}.corrupt-{int(datetime.now(UTC).timestamp())}{target_registry.suffix}"
            backup_path = target_registry.parent / backup_name
            try:
                backup_path.write_bytes(target_registry.read_bytes())
            except Exception:
                pass
            raise PlaybookError(
                f"Existing registry at {target_registry} is malformed ({exc}); "
                f"preserved corrupted file as {backup_name} and refused to overwrite."
            ) from exc
    else:
        registry = {
            "artifactType": "playbook-registry",
            "schemaVersion": "1.0",
            "playbooks": [],
        }

    raw_playbooks = registry.get("playbooks")
    playbook_entries: list[dict[str, Any]] = (
        raw_playbooks if isinstance(raw_playbooks, list) else []
    )
    registry["playbooks"] = playbook_entries

    entry: dict[str, Any] = {
        "playbookId": playbook_id,
        "playbookName": str(
            playbook.get("title") or playbook.get("playbookName") or playbook_id
        ),
        "version": str(playbook.get("version", "1.0.0")),
        "status": "approved",
        "agreementFamily": str(playbook.get("agreementFamily", "")),
        "perspective": str(playbook.get("perspective", "")),
        "issueCount": len(playbook.get("issues", [])),
        "sealedAt": utc_now(),
        "packagePath": str(package_path),
    }

    existing_index = next(
        (
            i
            for i, item in enumerate(playbook_entries)
            if isinstance(item, dict) and item.get("playbookId") == playbook_id
        ),
        None,
    )
    if existing_index is not None:
        existing_version = playbook_entries[existing_index].get("version")
        if _version_key(entry["version"]) < _version_key(existing_version):
            raise PlaybookError(
                f"Registry already has {playbook_id} v{existing_version}; "
                f"refusing to register older v{entry['version']}"
            )
        playbook_entries[existing_index] = entry
    else:
        playbook_entries.append(entry)

    write_json_atomic(target_registry, registry)
    return registry


def find_playbook_registry(search_dir: Path | None = None) -> Path | None:
    current = (search_dir or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / DEFAULT_REGISTRY_NAME
        if candidate.is_file():
            return candidate
    return None


def list_registered_playbooks(
    registry_path: Path | None = None,
    search_dir: Path | None = None,
) -> list[dict[str, Any]]:
    target = registry_path or find_playbook_registry(search_dir)
    if not target or not target.is_file():
        return []
    try:
        registry = load_json(target)
        playbooks = registry.get("playbooks")
        if isinstance(playbooks, list):
            return [
                p
                for p in playbooks
                if isinstance(p, dict) and p.get("status") == "approved"
            ]
    except Exception:
        pass
    return []


# Aliases are agreement titles, not clause headings. A bare "confidentiality",
# "licence" or "data protection" appears as a heading in most agreements and
# would misidentify the family; only phrases that name a document type belong here.
CONTRACT_FAMILY_ALIASES: dict[str, dict[str, Any]] = {
    "msa": {
        "family": "MSA",
        "aliases": {
            "msa",
            "master services agreement",
            "master service agreement",
            "master services",
            "master agreement",
            "framework agreement",
            "services agreement",
        },
    },
    "nda": {
        "family": "NDA",
        "aliases": {
            "nda",
            "non disclosure",
            "non-disclosure",
            "confidentiality agreement",
            "confidentiality undertaking",
            "confidential disclosure",
            "cda",
            "secrecy agreement",
        },
    },
    "saas": {
        "family": "SaaS Agreement",
        "aliases": {
            "saas",
            "software as a service",
            "cloud services",
            "subscription agreement",
            "cloud agreement",
            "hosted services",
        },
    },
    "dpa": {
        "family": "DPA",
        "aliases": {
            "dpa",
            "data processing agreement",
            "data processing addendum",
            "data protection agreement",
            "data protection addendum",
            "data transfer agreement",
            "gdpr agreement",
            "privacy addendum",
        },
    },
    "sow": {
        "family": "Statement of Work (SOW)",
        "aliases": {
            "sow",
            "statement of work",
            "order form",
            "work order",
            "schedule of work",
        },
    },
    "lease": {
        "family": "Commercial Lease",
        "aliases": {
            "lease",
            "tenancy agreement",
            "commercial lease",
            "office lease",
            "property lease",
        },
    },
    "licence": {
        "family": "Software Licence",
        "aliases": {
            "licence agreement",
            "license agreement",
            "software licence",
            "software license",
            "eula",
            "end user licence",
            "end user license",
        },
    },
    "supply": {
        "family": "Supply Agreement",
        "aliases": {
            "supply agreement",
            "supply of goods",
            "procurement agreement",
            "supplier agreement",
            "distribution agreement",
        },
    },
    "employment": {
        "family": "Employment Agreement",
        "aliases": {
            "employment agreement",
            "employment contract",
            "consultancy agreement",
            "contractor agreement",
        },
    },
}


# Only the opening of a contract (title, parties, recitals) is trusted for
# family detection. Body clauses share vocabulary across every agreement type.
TITLE_REGION_CHARS = 400


def extract_sample_text_from_file(path: Path) -> str:
    """Extract opening text or headings from a contract file for shallow inspection."""
    if not path.is_file():
        return ""
    suffix = path.suffix.lower()
    try:
        if suffix in {".txt", ".md"}:
            return path.read_text(encoding="utf-8", errors="ignore")[:3000]
        if suffix == ".docx":
            with zipfile.ZipFile(path) as zf:
                if "word/document.xml" in zf.namelist():
                    xml_bytes = zf.read("word/document.xml")[:60000]
                    texts = re.findall(
                        r"<w:t[^>]*>([^<]+)</w:t>",
                        xml_bytes.decode("utf-8", errors="ignore"),
                    )
                    return " ".join(texts[:60])
        if suffix == ".pdf":
            # pdfplumber is an optional host extra, never a shipped dependency.
            # It is loaded by name so the standard-library-only rule for bundled
            # scripts holds: when it is absent the first-guess check simply
            # returns no sample text and the picker is shown instead.
            try:
                pdfplumber = importlib.import_module("pdfplumber")
                with pdfplumber.open(path) as pdf:
                    if pdf.pages:
                        return pdf.pages[0].extract_text() or ""
            except Exception:
                pass
    except Exception:
        pass
    return ""


def match_playbook_candidate(
    playbooks: Sequence[Mapping[str, Any]],
    source_names: Sequence[str | Path] | None = None,
    sample_text: str | None = None,
) -> dict[str, Any] | None:
    """Deterministically match contract sources against registered playbooks.

    The contract's family is read only from its file names and the title region
    of its text (the first ``TITLE_REGION_CHARS`` characters). Body text is not
    consulted for family detection: almost every agreement has a confidentiality
    clause, a licence grant, and a data protection clause, so body aliases would
    make an MSA look like an NDA whenever the library holds only an NDA
    playbook. A playbook is a candidate only when its own family matches one of
    the contract's detected families.

    Returns the top candidate when exactly one playbook leads, or None when
    nothing matches or the leaders tie (so the caller falls back to the picker).
    """
    if not playbooks:
        return None

    name_clues: list[str] = []
    if source_names:
        for name in source_names:
            p = Path(name)
            name_clues.append(re.sub(r"[_.\-]+", " ", p.stem).lower())

    clean_sample = ""
    if sample_text:
        clean_sample = re.sub(r"\s+", " ", sample_text).strip().lower()
    title_region = clean_sample[:TITLE_REGION_CHARS]

    family_blob = " ".join([*name_clues, title_region]).strip()
    if not family_blob:
        return None
    perspective_blob = " ".join([*name_clues, clean_sample[:3000]])

    # Detect which contract families the file names or title region establish.
    matched_families: dict[str, str] = {}
    for key, info in CONTRACT_FAMILY_ALIASES.items():
        family_name = info["family"]
        for alias in info["aliases"]:
            if re.search(rf"\b{re.escape(alias)}\b", family_blob):
                matched_families[key] = family_name
                break
    if not matched_families:
        return None

    # Score each playbook whose own family is one of the detected families.
    scored: list[tuple[int, Mapping[str, Any], str]] = []
    for pb in playbooks:
        pb_id = str(pb.get("playbookId") or "").lower()
        pb_name = str(pb.get("playbookName") or pb.get("title") or "").lower()
        pb_family = str(pb.get("agreementFamily") or "").lower()
        pb_persp = str(pb.get("perspective") or "").lower()
        pb_text = f"{pb_id} {pb_name} {pb_family}"

        score = 0
        assigned_family = ""
        for fam_key, fam_label in matched_families.items():
            aliases = CONTRACT_FAMILY_ALIASES[fam_key]["aliases"]
            if any(re.search(rf"\b{re.escape(a)}\b", pb_text) for a in aliases):
                score += 100
                assigned_family = fam_label
        if score == 0:
            continue

        # Perspective bonus (e.g. supplier vs customer) may use the wider text.
        if pb_persp and re.search(rf"\b{re.escape(pb_persp)}\b", perspective_blob):
            score += 30

        # Small bonus for playbook-name words appearing in the names or title.
        for word in re.findall(r"[a-z0-9]+", pb_name):
            if len(word) > 3 and re.search(rf"\b{re.escape(word)}\b", family_blob):
                score += 5

        scored.append((score, pb, assigned_family))

    if not scored:
        return None

    scored.sort(key=lambda item: item[0], reverse=True)
    top_score, top_pb, top_family = scored[0]

    # Check for tie with runner up
    if len(scored) > 1:
        second_score = scored[1][0]
        if top_score == second_score:
            # Ambiguous match between multiple playbooks
            return None

    return {
        "playbook": top_pb,
        "detectedFamily": top_family,
        "score": top_score,
    }


def format_playbook_suggestion(match_result: Mapping[str, Any]) -> str:
    """Format a conversational first-guess recommendation for a matched playbook."""
    pb = match_result["playbook"]
    family = match_result.get("detectedFamily", "agreement")
    name = str(
        pb.get("playbookName") or pb.get("title") or pb.get("playbookId") or "Unknown"
    )
    ver = str(pb.get("version") or "1.0.0")
    count = pb.get("issueCount", 0)
    persp = str(pb.get("perspective") or "").capitalize()
    persp_str = f" [{persp}]" if persp else ""
    pid = str(pb.get("playbookId") or "")

    article = (
        "an"
        if re.match(r"^(?:[AEIOUaeiou]|MSA|NDA|DPA|SOW|EULA)\b", str(family))
        else "a"
    )
    return (
        f"This looks like {article} {family}. You have an approved playbook in your library:\n"
        f"- **{name}** (v{ver}) - {count} issues{persp_str} (`{pid}`)\n\n"
        "Would you like to use this playbook, or select another from your library?"
    )


def format_playbook_picker(playbooks: Sequence[Mapping[str, Any]]) -> str:
    if not playbooks:
        return "No approved playbooks found in registry."
    lines = ["Available Approved Playbooks:"]
    for idx, pb in enumerate(playbooks, start=1):
        name = str(
            pb.get("playbookName")
            or pb.get("title")
            or pb.get("playbookId")
            or "unknown"
        )
        pid = str(pb.get("playbookId") or "unknown")
        ver = str(pb.get("version") or "1.0.0")
        count = pb.get("issueCount", 0)
        persp = str(pb.get("perspective") or "").capitalize()
        persp_str = f" [{persp}]" if persp else ""
        id_str = f" (`{pid}`)"
        lines.append(f"{idx}. **{name}** (v{ver}) - {count} issues{persp_str}{id_str}")
    lines.append("\nReply with the number to apply, or provide a custom folder path.")
    return "\n".join(lines)


INTERNAL_MARKING = (
    "INTERNAL - PRIVILEGED AND CONFIDENTIAL. Prepared for the represented party "
    "and its advisers. Contains internal risk assessment and negotiation "
    "guidance. Do not circulate to the counterparty; use the external cut."
)
EXTERNAL_MARKING = (
    "Prepared for circulation to the counterparty. Internal risk assessment, "
    "playbook references and risk ratings are omitted from this cut."
)


def summarise_issue_counts(issues: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Count issues by materiality and by every classification.

    Every classification is counted, so an executive tally can never total
    fewer issues than the matrix beneath it.
    """
    by_materiality = {key: 0 for key in MATERIALITY_ORDER}
    by_classification = {key: 0 for key in CLASSIFICATION_TALLY_ORDER}
    total = 0
    for issue in issues:
        total += 1
        materiality = str(issue.get("materiality") or "none").lower()
        by_materiality[materiality] = by_materiality.get(materiality, 0) + 1
        classification = str(issue.get("classification") or "")
        by_classification[classification] = by_classification.get(classification, 0) + 1
    return {
        "total": total,
        "byMateriality": by_materiality,
        "byClassification": by_classification,
    }


def format_issue_tally(tally: Mapping[str, Any], warning_count: int = 0) -> str:
    """Render the executive tally line used at the top of the issues matrix."""
    materiality = tally["byMateriality"]
    classification = tally["byClassification"]
    risk_parts = [
        f"{materiality.get('high', 0)} High Risk",
        f"{materiality.get('medium', 0)} Medium Risk",
        f"{materiality.get('low', 0)} Low Risk",
    ]
    if materiality.get("none", 0):
        risk_parts.append(f"{materiality['none']} Not Rated")
    action_parts: list[str] = []
    for key in CLASSIFICATION_TALLY_ORDER:
        count = classification.get(key, 0)
        # Redlines are always shown, even at zero, because that is the first
        # number a reader looks for. Other categories appear when present.
        if count or key == "deviation":
            action_parts.append(f"{count} {_plural_label(key, count)}")
    parts = [
        f"Executive Summary: {tally['total']} Total Issues",
        "  •  ".join(risk_parts),
        "  •  ".join(action_parts),
    ]
    if warning_count:
        parts.append(f"{warning_count} Structural Warnings")
    return "  |  ".join(parts)


_TALLY_PLURALS: dict[str, tuple[str, str]] = {
    "deviation": ("Redline Required", "Redlines Required"),
    "missing-protection": ("Missing House Clause", "Missing House Clauses"),
    "extra-obligation": ("Onerous / Non-Standard", "Onerous / Non-Standard"),
    "playbook-gap": ("Uncovered Issue", "Uncovered Issues"),
    "playbook-conflict": ("Playbook Conflict", "Playbook Conflicts"),
    "unclear": ("Ambiguous Drafting", "Ambiguous Drafting"),
    "aligned-fallback": ("Acceptable Fallback", "Acceptable Fallbacks"),
    "aligned-preferred": ("Standard", "Standard"),
    "not-applicable": ("Not Applicable", "Not Applicable"),
}


def _plural_label(classification: str, count: int) -> str:
    singular, plural = _TALLY_PLURALS.get(
        classification,
        (
            get_classification_label(classification),
            get_classification_label(classification),
        ),
    )
    return singular if count == 1 else plural


def render_issues_docx(
    issues: Mapping[str, Any],
    out_path: Path,
    playbook: Mapping[str, Any] | None = None,
    contract_name: str | None = None,
    audience: str = "internal",
) -> None:
    """Write the issues matrix as a landscape Word document.

    ``audience`` selects the cut:

    - ``internal``: the full matrix for the represented party and its advisers,
      marked privileged, with the internal risk guidance, playbook reference,
      classification labels and executive tally.
    - ``external``: a counterparty-safe cut that omits the internal guidance,
      playbook and rule identifiers, risk ratings and tally, and keeps only the
      clause, the source wording, the proposed markup and the negotiation
      comment.
    """
    if audience not in EXPORT_AUDIENCES:
        raise PlaybookError(
            f"Unknown export audience: {audience!r} (expected internal or external)"
        )
    external = audience == "external"

    errors = validate_issues_list(issues)
    if errors:
        raise PlaybookError(
            f"Cannot export invalid issues list to DOCX: {'; '.join(errors)}"
        )

    run_id = str(issues.get("runId", "review-run"))
    playbook_id = str(issues.get("playbookId", "playbook"))
    playbook_version = str(issues.get("playbookVersion", "1.0.0"))
    pb_display_name = None
    if playbook:
        pb_display_name = playbook.get("title") or playbook.get("playbookName")
    if external:
        title = "Contract Review: Proposed Amendments and Comments"
    elif pb_display_name:
        title = f"Contract Review: Issues Matrix - {pb_display_name}"
    else:
        title = "Contract Review: Issues Matrix"

    raw_issues = issues.get("issues", [])
    issues_list = [i for i in raw_issues if isinstance(i, Mapping)]
    tally = summarise_issue_counts(issues_list)
    warning_lines = _structural_warning_lines(issues.get("structuralWarnings"))

    def _clean_text(val: Any) -> str:
        s = str(val or "")
        cleaned = "".join(ch for ch in s if ch in "\t\n\r" or ord(ch) >= 32)
        return html.escape(cleaned, quote=True)

    def _p(runs_xml: str, ppr_xml: str = "") -> str:
        return f"<w:p>{ppr_xml}{runs_xml}</w:p>"

    def _run(text: str, rpr_xml: str = "") -> str:
        """Emit one run. Newlines become <w:br/> and tabs <w:tab/>.

        Word ignores literal newline characters inside <w:t>, so a
        multi-paragraph clause redraft would otherwise collapse into one line.
        """
        if not text:
            return ""
        pieces: list[str] = []
        for line_index, line in enumerate(str(text).replace("\r\n", "\n").split("\n")):
            if line_index:
                pieces.append("<w:br/>")
            for tab_index, chunk in enumerate(line.split("\t")):
                if tab_index:
                    pieces.append("<w:tab/>")
                if chunk:
                    pieces.append(
                        f'<w:t xml:space="preserve">{_clean_text(chunk)}</w:t>'
                    )
        return f"<w:r>{rpr_xml}{''.join(pieces)}</w:r>"

    body_elements: list[str] = []

    # Title paragraph
    title_p = _p(
        _run(
            title,
            '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:b/><w:sz w:val="36"/><w:color w:val="1B365D"/></w:rPr>',
        ),
        '<w:pPr><w:spacing w:after="80"/><w:jc w:val="left"/></w:pPr>',
    )
    body_elements.append(title_p)

    # Audience marking. The internal cut carries candid leverage guidance, so it
    # is marked privileged; the external cut says what has been left out.
    marking_text = EXTERNAL_MARKING if external else INTERNAL_MARKING
    body_elements.append(
        _p(
            _run(
                marking_text,
                '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:b/><w:sz w:val="18"/><w:color w:val="900C3F"/></w:rPr>',
            ),
            '<w:pPr><w:spacing w:after="80"/><w:jc w:val="left"/></w:pPr>',
        )
    )

    # Subtitle / Metadata paragraph
    meta_parts: list[str] = []
    if not external:
        if pb_display_name:
            meta_parts.append(f"Playbook: {pb_display_name} (v{playbook_version})")
        else:
            meta_parts.append(f"Playbook: {playbook_id} (v{playbook_version})")

    doc_ref = contract_name or issues.get("contractName")
    if doc_ref:
        meta_parts.append(f"Document: {doc_ref}")

    governing_law = playbook.get("governingLaw") if playbook else None
    date_style = str((playbook.get("dateStyle") if playbook else None) or "auto")
    formatted_date = format_display_date(
        issues.get("generatedAt"), style=date_style, governing_law=governing_law
    )
    meta_parts.append(f"Date: {formatted_date}")
    if governing_law:
        meta_parts.append(f"Governing Law: {governing_law}")
    if not external:
        meta_parts.append(f"Run ID: {run_id}")

    meta_str = "  |  ".join(meta_parts)
    meta_p = _p(
        _run(
            meta_str,
            '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="19"/><w:color w:val="475569"/></w:rPr>',
        ),
        '<w:pPr><w:spacing w:after="80"/><w:jc w:val="left"/></w:pPr>',
    )
    body_elements.append(meta_p)

    if not external:
        tally_p = _p(
            _run(
                format_issue_tally(tally, len(warning_lines)),
                '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:b/><w:sz w:val="19"/><w:color w:val="1B365D"/></w:rPr>',
            ),
            '<w:pPr><w:spacing w:after="120"/><w:jc w:val="left"/></w:pPr>',
        )
        body_elements.append(tally_p)

    # Structural warnings sit above the table in both cuts: a missing schedule
    # or a precedence clash matters to whoever is reading the matrix.
    if warning_lines:
        body_elements.append(
            _p(
                _run(
                    "Structural Warnings",
                    '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:b/><w:sz w:val="22"/><w:color w:val="9A3412"/></w:rPr>',
                ),
                '<w:pPr><w:spacing w:before="60" w:after="40"/></w:pPr>',
            )
        )
        for label, text in warning_lines:
            body_elements.append(
                _p(
                    _run(
                        f"{label}: ",
                        '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:b/><w:sz w:val="19"/><w:color w:val="9A3412"/></w:rPr>',
                    )
                    + _run(
                        text,
                        '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="19"/><w:color w:val="1E293B"/></w:rPr>',
                    ),
                    '<w:pPr><w:spacing w:after="40"/><w:ind w:left="284"/></w:pPr>',
                )
            )
    body_elements.append(_p("", '<w:pPr><w:spacing w:after="120"/></w:pPr>'))

    # Column widths: Col 1 (1.6 in = 2304 dxa), Col 2 (1.4 in = 2016 dxa), Col 3 (3.5 in = 5040 dxa), Col 4 (3.8 in = 5472 dxa)
    col_widths = [2304, 2016, 5040, 5472]

    tbl_pr = (
        "<w:tblPr>"
        '<w:tblW w:w="5000" w:type="pct"/>'
        "<w:tblCellMar>"
        '<w:top w:w="140" w:type="dxa"/><w:bottom w:w="140" w:type="dxa"/>'
        '<w:left w:w="160" w:type="dxa"/><w:right w:w="160" w:type="dxa"/>'
        "</w:tblCellMar>"
        "<w:tblBorders>"
        '<w:top w:val="single" w:sz="6" w:space="0" w:color="CBD5E1"/>'
        '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="CBD5E1"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
        '<w:left w:val="none"/>'
        '<w:right w:val="none"/>'
        "</w:tblBorders>"
        "</w:tblPr>"
    )

    grid_cols = "".join(f'<w:gridCol w:w="{w}"/>' for w in col_widths)
    tbl_grid = f"<w:tblGrid>{grid_cols}</w:tblGrid>"

    # Header Row
    header_titles = (
        [
            "Clause Ref",
            "Proposed Change",
            "Contract Wording (As Drafted)",
            "Proposed Markup & Comment",
        ]
        if external
        else [
            "Clause Ref / ID",
            "Risk / Status",
            "Contract Wording (As Drafted)",
            "Proposed Markup & Guidance",
        ]
    )
    header_cells: list[str] = []
    for title_text, width in zip(header_titles, col_widths, strict=False):
        tc_pr = (
            f"<w:tcPr>"
            f'<w:tcW w:w="{width}" w:type="dxa"/>'
            '<w:shd w:val="clear" w:color="auto" w:fill="1B365D"/>'
            '<w:vAlign w:val="center"/>'
            "</w:tcPr>"
        )
        cell_p = _p(
            _run(
                title_text,
                '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:b/><w:sz w:val="20"/><w:color w:val="FFFFFF"/></w:rPr>',
            ),
            '<w:pPr><w:spacing w:before="60" w:after="60"/></w:pPr>',
        )
        header_cells.append(f"<w:tc>{tc_pr}{cell_p}</w:tc>")

    header_row = (
        "<w:tr>"
        "<w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>"
        + "".join(header_cells)
        + "</w:tr>"
    )

    rows: list[str] = [header_row]

    for item in _issues_by_severity(issues_list):
        clause_ref = str(item.get("clauseRef") or "N/A")
        issue_id = str(item.get("issueId") or "")
        playbook_issue_id = str(item.get("playbookIssueId") or "")
        materiality = str(item.get("materiality") or "none").lower()
        classification = str(item.get("classification") or "")
        drafting_provenance = str(item.get("draftingProvenance") or "")
        original_text = str(item.get("originalText") or "")
        proposed_text = str(item.get("proposedText") or "")
        rationale = str(item.get("rationale") or "")
        markup_segments = item.get("markupSegments")

        # Color fill based on risk / materiality (neutral in the external cut,
        # which does not disclose the house risk rating)
        if external:
            risk_fill = "F1F5F9"
            risk_text_color = "475569"
        elif materiality == "high":
            risk_fill = "FADBD8"  # pastel red
            risk_text_color = "900C3F"
        elif materiality == "medium":
            risk_fill = "FDEBD0"  # pastel amber
            risk_text_color = "B9770E"
        elif materiality == "low":
            risk_fill = "D5F5E3"  # pastel green
            risk_text_color = "1E8449"
        else:
            risk_fill = "F1F5F9"  # neutral grey
            risk_text_color = "475569"

        # Col 1: Clause Ref & IDs
        col1_p1 = _p(
            _run(
                f"Clause {clause_ref}",
                '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:b/><w:sz w:val="20"/><w:color w:val="1E293B"/></w:rPr>',
            ),
            '<w:pPr><w:spacing w:after="40"/></w:pPr>',
        )
        col1_p2 = _p(
            _run(
                issue_id,
                '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="16"/><w:color w:val="64748B"/></w:rPr>',
            ),
            '<w:pPr><w:spacing w:after="20"/></w:pPr>',
        )
        # The rule reference is only meaningful when the issue maps to a
        # playbook rule; playbook-gap issues have none, so no dangling label.
        col1_p3 = (
            _p(
                _run(
                    f"Rule: {playbook_issue_id}",
                    '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="17"/><w:color w:val="475569"/></w:rPr>',
                ),
                '<w:pPr><w:spacing w:after="40"/></w:pPr>',
            )
            if playbook_issue_id
            else ""
        )
        tc1_content = col1_p1 if external else f"{col1_p1}{col1_p2}{col1_p3}"
        tc1 = (
            f"<w:tc>"
            f'<w:tcPr><w:tcW w:w="{col_widths[0]}" w:type="dxa"/><w:vAlign w:val="top"/></w:tcPr>'
            f"{tc1_content}"
            f"</w:tc>"
        )

        # Col 2: Risk / Status (internal) or Proposed Change (external)
        if external:
            change_label = (
                "Amendment proposed"
                if proposed_text != original_text
                else "Comment only"
            )
            tc2_content = _p(
                _run(
                    change_label,
                    f'<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:b/><w:sz w:val="18"/><w:color w:val="{risk_text_color}"/></w:rPr>',
                ),
                '<w:pPr><w:spacing w:after="40"/></w:pPr>',
            )
        else:
            col2_p1 = _p(
                _run(
                    materiality.upper(),
                    f'<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:b/><w:sz w:val="20"/><w:color w:val="{risk_text_color}"/></w:rPr>',
                ),
                '<w:pPr><w:spacing w:after="40"/></w:pPr>',
            )
            col2_p2 = _p(
                _run(
                    get_classification_label(classification),
                    '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:b/><w:sz w:val="18"/><w:color w:val="1E293B"/></w:rPr>',
                ),
                '<w:pPr><w:spacing w:after="40"/></w:pPr>',
            )
            prov_label = (
                drafting_provenance.replace("-", " ").title()
                if drafting_provenance
                else ""
            )
            col2_p3 = _p(
                _run(
                    prov_label,
                    '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="16"/><w:color w:val="64748B"/></w:rPr>',
                ),
                '<w:pPr><w:spacing w:after="40"/></w:pPr>',
            )
            tc2_content = f"{col2_p1}{col2_p2}{col2_p3}"
        tc2 = (
            f"<w:tc>"
            f"<w:tcPr>"
            f'<w:tcW w:w="{col_widths[1]}" w:type="dxa"/>'
            f'<w:shd w:val="clear" w:color="auto" w:fill="{risk_fill}"/>'
            f'<w:vAlign w:val="top"/>'
            f"</w:tcPr>"
            f"{tc2_content}"
            f"</w:tc>"
        )

        # Col 3: Inbound Wording
        col3_paragraphs: list[str] = []
        for line in (original_text or "(None)").splitlines():
            if line.strip():
                col3_paragraphs.append(
                    _p(
                        _run(
                            line.strip(),
                            '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="19"/><w:color w:val="334155"/></w:rPr>',
                        ),
                        '<w:pPr><w:spacing w:after="60"/></w:pPr>',
                    )
                )
        if not col3_paragraphs:
            col3_paragraphs.append(
                _p(
                    _run(
                        "(None)",
                        '<w:rPr><w:sz w:val="19"/><w:color w:val="94A3B8"/></w:rPr>',
                    )
                )
            )
        tc3 = (
            f"<w:tc>"
            f'<w:tcPr><w:tcW w:w="{col_widths[2]}" w:type="dxa"/><w:vAlign w:val="top"/></w:tcPr>'
            + "".join(col3_paragraphs)
            + "</w:tc>"
        )

        # Col 4: Proposed Supplier Markup + Commercial Guidance
        if not markup_segments and proposed_text:
            markup_segments = build_markup_segments(original_text, proposed_text)

        markup_runs: list[str] = []
        if isinstance(markup_segments, list) and markup_segments:
            for seg in markup_segments:
                if isinstance(seg, Mapping):
                    stype = seg.get("op") or seg.get("kind")
                    stext = str(seg.get("text", ""))
                    if stype == "delete":
                        markup_runs.append(
                            _run(
                                stext,
                                '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:strike/><w:color w:val="B91C1C"/><w:sz w:val="19"/></w:rPr>',
                            )
                        )
                    elif stype == "insert":
                        markup_runs.append(
                            _run(
                                stext,
                                '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:u w:val="single"/><w:color w:val="15803D"/><w:b/><w:sz w:val="19"/></w:rPr>',
                            )
                        )
                    else:
                        markup_runs.append(
                            _run(
                                stext,
                                '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:color w:val="1E293B"/><w:sz w:val="19"/></w:rPr>',
                            )
                        )
        elif proposed_text:
            markup_runs.append(
                _run(
                    proposed_text,
                    '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:color w:val="1E293B"/><w:sz w:val="19"/></w:rPr>',
                )
            )
        else:
            markup_runs.append(
                _run(
                    "(No drafting change recommended)",
                    '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="18"/><w:color w:val="64748B"/><w:i/></w:rPr>',
                )
            )

        col4_p1 = _p("".join(markup_runs), '<w:pPr><w:spacing w:after="80"/></w:pPr>')

        guidance_runs = [
            _run(
                "Internal Risk / Guidance: ",
                '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:b/><w:sz w:val="18"/><w:color w:val="1B365D"/></w:rPr>',
            ),
            _run(
                rationale or "(No specific guidance provided)",
                '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="18"/><w:color w:val="475569"/></w:rPr>',
            ),
        ]
        col4_p2 = _p("".join(guidance_runs), '<w:pPr><w:spacing w:after="60"/></w:pPr>')

        external_comment = str(item.get("externalComment") or "").strip()
        col4_p3 = ""
        if external_comment:
            ext_runs = [
                _run(
                    "Comment: "
                    if external
                    else "Negotiation Comment (for Word / Counterparty): ",
                    '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:b/><w:sz w:val="18"/><w:color w:val="0D5C75"/></w:rPr>',
                ),
                _run(
                    f'"{external_comment}"',
                    '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:i/><w:sz w:val="18"/><w:color w:val="334155"/></w:rPr>',
                ),
            ]
            col4_p3 = _p("".join(ext_runs), '<w:pPr><w:spacing w:after="60"/></w:pPr>')
        # The external cut never carries the internal guidance paragraph.
        tc4_content = (
            f"{col4_p1}{col4_p3}" if external else f"{col4_p1}{col4_p2}{col4_p3}"
        )

        tc4 = (
            f"<w:tc>"
            f'<w:tcPr><w:tcW w:w="{col_widths[3]}" w:type="dxa"/><w:vAlign w:val="top"/></w:tcPr>'
            f"{tc4_content}"
            f"</w:tc>"
        )

        row_xml = f"<w:tr><w:trPr><w:cantSplit/></w:trPr>{tc1}{tc2}{tc3}{tc4}</w:tr>"
        rows.append(row_xml)

    tbl_xml = f"<w:tbl>{tbl_pr}{tbl_grid}{''.join(rows)}</w:tbl>"
    body_elements.append(tbl_xml)

    sect_pr = (
        "<w:sectPr>"
        '<w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/>'
        '<w:pgMar w:top="1008" w:right="1008" w:bottom="1008" w:left="1008" w:header="720" w:footer="720" w:gutter="0"/>'
        "</w:sectPr>"
    )

    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f"<w:document {WORD_XMLNS}>\n"
        f"<w:body>\n" + "\n".join(body_elements) + f"\n{sect_pr}\n"
        "</w:body>\n"
        "</w:document>"
    )

    types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="xml" ContentType="application/xml"/>\n'
        '  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>\n'
        '  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>\n'
        "</Types>"
    )

    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>\n'
        "</Relationships>"
    )

    doc_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>\n'
        "</Relationships>"
    )

    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f"<w:styles {WORD_XMLNS}>\n"
        "  <w:docDefaults>\n"
        "    <w:rPrDefault>\n"
        "      <w:rPr>\n"
        '        <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>\n'
        '        <w:sz w:val="20"/>\n'
        '        <w:color w:val="1E293B"/>\n'
        "      </w:rPr>\n"
        "    </w:rPrDefault>\n"
        "  </w:docDefaults>\n"
        "</w:styles>"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{out_path.name}.",
        suffix=".tmp",
        dir=out_path.parent,
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", types_xml)
            zf.writestr("_rels/.rels", rels_xml)
            zf.writestr("word/_rels/document.xml.rels", doc_rels_xml)
            zf.writestr("word/styles.xml", styles_xml)
            zf.writestr("word/document.xml", doc_xml)
        temporary.replace(out_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


PLAYBOOK_COLUMN_ALIASES: dict[str, Sequence[str]] = {
    "topic": (
        "topic",
        "issue",
        "issue name",
        "clause",
        "clause name",
        "clause topic",
        "provision",
        "subject",
        "name",
        "title",
        "item",
        "area",
        "matter",
    ),
    "preferred": (
        "preferred",
        "standard",
        "house standard",
        "starting position",
        "position",
        "house position",
        "approved position",
        "preferred position",
        "standard position",
        "opening position",
        "baseline",
    ),
    "wording": (
        "wording",
        "approved wording",
        "preferred wording",
        "clause wording",
        "house wording",
        "standard wording",
        "model wording",
        "model clause",
        "house clause",
        "clause text",
        "approved text",
        "drafting",
        "precedent wording",
    ),
    "fallback_1": (
        "fallback",
        "fallbacks",
        "acceptable position",
        "acceptable fallback",
        "concession",
        "fallback 1",
        "first fallback",
        "rank 1",
        "fallback position",
    ),
    "fallback_2": (
        "fallback 2",
        "second fallback",
        "secondary fallback",
        "rank 2",
    ),
    "condition": (
        "condition",
        "fallback condition",
        "when",
        "trigger",
        "when to concede",
        "circumstances",
    ),
    "redline": (
        "red line",
        "redline",
        "red-line",
        "walk away",
        "walkaway",
        "walk-away",
        "hard stop",
        "non-negotiable",
        "minimum position",
        "unacceptable",
        "deal breaker",
    ),
    "priority": (
        "priority",
        "materiality",
        "risk",
        "importance",
        "severity",
        "significance",
    ),
    "guidance": (
        "guidance",
        "notes",
        "km notes",
        "practice notes",
        "comments",
        "instructions",
        "escalation",
        "approval",
        "rationale",
    ),
}
_PRIORITY_WORDS: dict[str, str] = {
    "high": "high",
    "h": "high",
    "critical": "high",
    "must": "high",
    "1": "high",
    "medium": "medium",
    "med": "medium",
    "m": "medium",
    "moderate": "medium",
    "2": "medium",
    "low": "low",
    "l": "low",
    "minor": "low",
    "3": "low",
}
UNSTATED_FALLBACK_CONDITION = "Not stated in the source table; confirm with the lawyer"


def _clean_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", header.strip().lower()).strip()


def _match_column_headers(headers: Sequence[str]) -> dict[str, int]:
    """Map playbook fields to column indexes by header alias.

    Exact alias matches are claimed first across every field, then prefix and
    suffix matches, so "Fallback 2" is never swallowed by the fallback_1 group
    because it starts with "fallback".
    """
    cleaned = [_clean_header(h) for h in headers]
    col_map: dict[str, int] = {}
    matched: set[int] = set()
    for field, aliases in PLAYBOOK_COLUMN_ALIASES.items():
        for idx, header in enumerate(cleaned):
            if idx in matched or not header:
                continue
            if header in aliases:
                col_map[field] = idx
                matched.add(idx)
                break
    for field, aliases in PLAYBOOK_COLUMN_ALIASES.items():
        if field in col_map:
            continue
        for idx, header in enumerate(cleaned):
            if idx in matched or not header:
                continue
            if any(
                header.startswith(f"{alias} ") or header.endswith(f" {alias}")
                for alias in aliases
            ):
                col_map[field] = idx
                matched.add(idx)
                break
    return col_map


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned or "issue"


def _split_listed_positions(cell: str) -> list[str]:
    """Split a cell holding several positions (one per line, or numbered)."""
    positions: list[str] = []
    for line in cell.split("\n"):
        clean_line = re.sub(r"^(\d+[.)]|-|\*|•)\s*", "", line).strip()
        if clean_line:
            positions.append(clean_line)
    return positions


def import_playbook_table(
    source_path: Path | str,
    title: str,
    playbook_id: str,
    perspective: str,
    family: str,
    governing_law: str | None = None,
    version: str = "1.0.0",
    out_dir: Path | str | None = None,
    approve_note: str | None = None,
    seal: bool = False,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    """Import an existing firm playbook table into a playbook package.

    Every row becomes an issue anchored to the manifest element for that row.
    Table cells are treated as position summaries, never as approved clause
    wording, unless the table has an explicit wording column. Issues land as
    ``candidate`` in a ``draft`` playbook unless ``approve_note`` records the
    lawyer's confirmation that the table is approved policy, in which case the
    playbook can also be sealed.
    """
    resolved_source = Path(source_path).resolve(strict=True)
    suffix = resolved_source.suffix.lower()
    if seal and not approve_note:
        raise PlaybookError(
            "A playbook can only be sealed once the lawyer has approved it; pass "
            "approve_note (--approve-all) with the lawyer's confirmation"
        )

    if suffix == ".docx":
        rows, raw_rows = _parse_docx_playbook_table(resolved_source)
    elif suffix in {".xlsx", ".xlsm"}:
        rows = _parse_xlsx_table_rows(resolved_source)
        raw_rows = rows
    elif suffix in {".csv", ".tsv"}:
        rows = _parse_csv_table_rows(resolved_source)
        raw_rows = rows
    else:
        raise PlaybookError(
            f"Unsupported table format for import: {suffix}. Expected .docx, .xlsx, or .csv"
        )

    header_index = _find_header_row(rows)
    if len(rows) < header_index + 2:
        raise PlaybookError(
            "Source table must contain a header row and at least one data row"
        )
    headers = [h.strip() for h in rows[header_index]]
    col_map = _match_column_headers(headers)
    if "topic" not in col_map or "preferred" not in col_map:
        raise PlaybookError(
            "Could not identify the topic and preferred-position columns from the "
            f"header row {headers!r}; rename the headers (e.g. Clause, House "
            "Standard, Fallback, Red Line, Priority, Guidance) and retry"
        )

    manifest = build_source_manifest(
        [resolved_source],
        resolved_source.parent,
        {resolved_source.name: "km-guidance"},
    )
    doc_entry = manifest["documents"][0]
    doc_sha = doc_entry["sha256"]
    elements_by_text: dict[str, list[Mapping[str, Any]]] = {}
    for element in doc_entry.get("elements", []):
        if isinstance(element, Mapping):
            key = _normalise_text(str(element.get("sourceText") or ""))
            elements_by_text.setdefault(key, []).append(element)

    def _cell(row_data: Sequence[str], field: str) -> str:
        index = col_map.get(field)
        if index is not None and 0 <= index < len(row_data):
            return row_data[index].strip()
        return ""

    approval = "approved" if approve_note else "candidate"
    issues: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    skipped_rows: list[int] = []

    for offset, row in enumerate(rows[header_index + 1 :], start=header_index + 1):
        row_number = offset + 1
        topic_text = _cell(row, "topic")
        pref_text = _cell(row, "preferred")
        if not topic_text or not pref_text:
            skipped_rows.append(row_number)
            continue

        raw_row = raw_rows[offset] if offset < len(raw_rows) else row
        anchor_key = _normalise_text(_table_row_text(raw_row))
        candidates = elements_by_text.get(anchor_key) or []
        if not candidates:
            raise PlaybookError(
                f"Row {row_number} ({topic_text}) could not be anchored to a source "
                "manifest element; the table text and the manifest disagree"
            )
        element = candidates.pop(0)

        base_id = _slugify(topic_text)
        issue_id = base_id
        suffix_index = 2
        while issue_id in seen_ids:
            issue_id = f"{base_id}-{suffix_index}"
            suffix_index += 1
        seen_ids.add(issue_id)

        wording_text = _cell(row, "wording") or None
        guidance_text = _cell(row, "guidance")
        condition_text = _cell(row, "condition") or UNSTATED_FALLBACK_CONDITION
        redline_text = _cell(row, "redline") or None
        # Priority comes only from a priority column. A red line being present
        # says nothing about how important the issue is, and the builder must
        # not infer policy the source does not state.
        priority = _PRIORITY_WORDS.get(_cell(row, "priority").lower(), "medium")

        fallbacks: list[dict[str, Any]] = []
        for fallback_cell in (_cell(row, "fallback_1"), _cell(row, "fallback_2")):
            for position in _split_listed_positions(fallback_cell):
                fallbacks.append(
                    {
                        "rank": len(fallbacks) + 1,
                        "condition": condition_text,
                        "wording": {
                            "summary": position,
                            "text": None,
                            "approvalStatus": approval,
                        },
                    }
                )

        summary = (
            pref_text if not guidance_text else f"{pref_text} Guidance: {guidance_text}"
        )
        issues.append(
            {
                "issueId": issue_id,
                "topic": topic_text,
                "status": approval,
                "basePosition": {
                    "summary": summary,
                    "preferred": {
                        "summary": pref_text,
                        "text": wording_text,
                        "approvalStatus": approval,
                    },
                    "fallbacks": fallbacks,
                    "redLine": redline_text,
                    "priority": priority,
                },
                "provenance": [
                    {
                        "documentSha256": doc_sha,
                        "elementId": str(element.get("elementId")),
                        "exactText": str(element.get("sourceText")),
                        "sourceRole": "km-guidance",
                    }
                ],
                "dependencies": [],
            }
        )

    if not issues:
        raise PlaybookError("No rows with both a topic and a preferred position found")

    playbook_payload: dict[str, Any] = {
        "artifactType": "contract-playbook",
        "schemaVersion": "1.0",
        "playbookId": playbook_id,
        "version": version,
        "title": title,
        "status": "approved" if approve_note else "draft",
        "perspective": perspective,
        "agreementFamily": family,
        "governingLaw": governing_law,
        "sourceManifestSha256": manifest["manifestSha256"],
        "issues": issues,
        "matterLenses": [],
    }
    if governing_law:
        playbook_payload["dateStyle"] = detect_date_style(governing_law)

    errors = validate_playbook(
        playbook_payload,
        require_approved=bool(approve_note),
        source_manifest=manifest,
    )
    if errors:
        raise PlaybookError(f"Imported playbook validation failed: {'; '.join(errors)}")

    target_dir = (
        Path(out_dir).resolve() if out_dir else resolved_source.parent / playbook_id
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(target_dir / "source-manifest.json", manifest)
    write_json_atomic(target_dir / "playbook.json", playbook_payload)
    import_receipt = {
        "artifactType": "import-receipt",
        "schemaVersion": "1.0",
        "importedAt": utc_now(),
        "sourceFile": resolved_source.name,
        "sourceSha256": doc_sha,
        "headerRow": header_index + 1,
        "columnMap": {field: headers[index] for field, index in col_map.items()},
        "rowsImported": len(issues),
        "rowsSkipped": skipped_rows,
        "status": approval,
        "approvalNote": approve_note,
    }
    write_json_atomic(target_dir / "import-receipt.json", import_receipt)

    receipt = None
    markdown = None
    if seal:
        sealed_result = seal_playbook(
            playbook_payload,
            manifest,
            version=version,
            package_path=target_dir,
            registry_path=registry_path,
        )
        write_json_atomic(target_dir / "playbook.json", sealed_result["playbook"])
        write_json_atomic(target_dir / "build-receipt.json", sealed_result["receipt"])
        write_text_atomic(target_dir / "playbook.md", sealed_result["markdown"])
        playbook_payload = sealed_result["playbook"]
        receipt = sealed_result["receipt"]
        markdown = sealed_result["markdown"]

    return {
        "status": approval,
        "playbookId": playbook_id,
        "version": version,
        "issuesCount": len(issues),
        "rowsSkipped": skipped_rows,
        "columnMap": import_receipt["columnMap"],
        "packageDir": str(target_dir),
        "sealed": seal,
        "playbook": playbook_payload,
        "manifest": manifest,
        "receipt": receipt,
        "markdown": markdown,
    }


# --- Review orchestration ----------------------------------------------------


def validate_element_sweep(sweep: Any, known_ids: set[str] | None = None) -> list[str]:
    """Validate the optional ``elementSweep`` block of an issues list."""
    if sweep is None:
        return []
    if not isinstance(sweep, Mapping):
        return ["elementSweep must be an object"]
    errors: list[str] = []
    seen: dict[str, str] = {}
    for field in ("completed", "parked", "unreadable"):
        value = sweep.get(field)
        if value is None:
            continue
        if field == "completed" and value == "all-remaining":
            continue
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item for item in value
        ):
            errors.append(f"elementSweep.{field} must be a list of element IDs")
            continue
        for element_id in value:
            if element_id in seen and seen[element_id] != field:
                errors.append(
                    f"elementSweep: {element_id} is listed as both {seen[element_id]} and {field}"
                )
            seen[element_id] = field
            if known_ids is not None and element_id not in known_ids:
                errors.append(f"elementSweep: unknown element {element_id}")
    return errors


def _coverage_analysis(
    manifest: Mapping[str, Any],
    effective_stance: Mapping[str, Any],
    issues_list: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive coverage counts from the artefacts and name every gap.

    The receipt is only honest if nothing is counted as covered by default. A
    rule is evaluated only when the issues list records a status for it; an
    element is completed only when an issue anchors to it or the model's
    ``elementSweep`` records it. Whatever is left is a gap, and the receipt
    does not reconcile.
    """
    raw_docs = manifest.get("documents", [])
    docs = (
        [d for d in raw_docs if isinstance(d, Mapping)]
        if isinstance(raw_docs, list)
        else []
    )
    raw_issues = issues_list.get("issues", [])
    issues = (
        [i for i in raw_issues if isinstance(i, Mapping)]
        if isinstance(raw_issues, list)
        else []
    )

    sweep = issues_list.get("elementSweep")
    sweep = sweep if isinstance(sweep, Mapping) else {}
    completed_value = sweep.get("completed")
    all_remaining = completed_value == "all-remaining"
    swept_completed = (
        set(completed_value) if isinstance(completed_value, list) else set()
    )
    swept_parked = set(sweep.get("parked") or [])
    swept_unreadable = set(sweep.get("unreadable") or [])
    anchored = {str(i.get("elementId") or "") for i in issues}

    element_status: dict[str, str] = {}
    doc_status: dict[str, str] = {}
    for doc in docs:
        doc_id = str(doc.get("documentId") or doc.get("sha256") or "")
        readability = str(doc.get("readability") or "readable")
        elements = doc.get("elements", [])
        element_ids = [
            str(e.get("elementId") or "")
            for e in (elements if isinstance(elements, list) else [])
            if isinstance(e, Mapping) and e.get("elementId")
        ]
        for element_id in element_ids:
            if readability == "unreadable" or element_id in swept_unreadable:
                element_status[element_id] = "unreadable"
            elif element_id in swept_parked:
                element_status[element_id] = "parked"
            elif (
                element_id in anchored or element_id in swept_completed or all_remaining
            ):
                element_status[element_id] = "completed"
            else:
                element_status[element_id] = "unswept"
        statuses = {element_status[e] for e in element_ids}
        if readability == "unreadable":
            doc_status[doc_id] = "unreadable"
        elif (
            readability in {"partial", "pending-host-read"}
            or "unswept" in statuses
            or "parked" in statuses
        ):
            doc_status[doc_id] = "parked"
        else:
            doc_status[doc_id] = "completed"

    stance_issues = effective_stance.get("issues", [])
    stance_ids = [
        str(s.get("issueId") or "")
        for s in (stance_issues if isinstance(stance_issues, list) else [])
        if isinstance(s, Mapping) and s.get("issueId")
    ]
    evaluated: set[str] = set()
    blocked: set[str] = set()
    not_applicable: set[str] = set()
    outside_stance: list[str] = []
    for issue in issues:
        rule_id = issue.get("playbookIssueId")
        if not isinstance(rule_id, str) or not rule_id:
            continue
        if rule_id not in stance_ids:
            outside_stance.append(rule_id)
            continue
        classification = issue.get("classification")
        if classification == "not-applicable":
            not_applicable.add(rule_id)
        elif classification == "playbook-conflict":
            blocked.add(rule_id)
        else:
            evaluated.add(rule_id)
    # One rule, one status: an evaluated rule outranks a blocked one, which
    # outranks a not-applicable marker left alongside a real finding.
    blocked -= evaluated
    not_applicable -= evaluated | blocked
    missing_rules = [
        r for r in stance_ids if r not in evaluated | blocked | not_applicable
    ]
    unswept = [e for e, status in element_status.items() if status == "unswept"]

    counts = {
        "runId": str(issues_list.get("runId") or "review-run"),
        "documents": {
            "expected": len(docs),
            "completed": sum(1 for s in doc_status.values() if s == "completed"),
            "parked": sum(1 for s in doc_status.values() if s == "parked"),
            "unreadable": sum(1 for s in doc_status.values() if s == "unreadable"),
        },
        "elements": {
            "expected": len(element_status),
            "completed": sum(1 for s in element_status.values() if s == "completed"),
            "parked": sum(1 for s in element_status.values() if s == "parked"),
            "unreadable": sum(1 for s in element_status.values() if s == "unreadable"),
        },
        "rules": {
            "expected": len(stance_ids),
            "evaluated": len(evaluated),
            "notApplicable": len(not_applicable),
            "blocked": len(blocked),
        },
    }
    return {
        "counts": counts,
        "gaps": {
            "missingRules": missing_rules,
            "unsweptElements": unswept,
            "issuesOutsideStance": sorted(set(outside_stance)),
        },
    }


def reconcile_coverage_from_artifacts(
    manifest: Mapping[str, Any],
    effective_stance: Mapping[str, Any],
    issues_list: Mapping[str, Any],
    coverage_counts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the coverage receipt from the run artefacts.

    Explicit ``coverage_counts`` (the manual path) take precedence when given.
    """
    if coverage_counts and isinstance(coverage_counts, Mapping):
        return build_coverage_receipt(coverage_counts)
    return build_coverage_receipt(
        _coverage_analysis(manifest, effective_stance, issues_list)["counts"]
    )


def describe_coverage_gaps(
    manifest: Mapping[str, Any],
    effective_stance: Mapping[str, Any],
    issues_list: Mapping[str, Any],
) -> dict[str, Any]:
    """Name the rules and elements that stop a coverage receipt reconciling."""
    return _coverage_analysis(manifest, effective_stance, issues_list)["gaps"]


def _term_map_blockers(
    term_map: Mapping[str, Any], issues: Sequence[Mapping[str, Any]]
) -> list[str]:
    """Return house terms used in proposed drafting that are not yet mapped.

    A term whose mapping is still ``unresolved`` or whose scope differs blocks
    any proposed text that uses it, unless the lawyer has accepted the entry.
    """
    blockers: list[str] = []
    entries = term_map.get("entries", [])
    if not isinstance(entries, list):
        return blockers
    changed = [
        str(i.get("proposedText") or "")
        for i in issues
        if i.get("proposedText") and i.get("proposedText") != i.get("originalText")
    ]
    if not changed:
        return blockers
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("relation") not in {"unresolved", "scope-differs"}:
            continue
        if entry.get("lawyerReview") in {"accepted", "revised"}:
            continue
        house = entry.get("houseDefinition")
        term = str(house.get("term") or "") if isinstance(house, Mapping) else ""
        if not term:
            continue
        pattern = rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])"
        if any(re.search(pattern, text) for text in changed):
            blockers.append(f"{term} ({entry.get('relation')})")
    return blockers


def _approved_lens_summaries(playbook: Mapping[str, Any]) -> list[dict[str, str]]:
    lenses = playbook.get("matterLenses", [])
    summaries: list[dict[str, str]] = []
    for lens in lenses if isinstance(lenses, list) else []:
        if isinstance(lens, Mapping) and lens.get("status") == "approved":
            summaries.append(
                {
                    "lensId": str(lens.get("lensId") or ""),
                    "label": str(lens.get("label") or ""),
                    "description": str(lens.get("description") or ""),
                }
            )
    return summaries


def setup_review_pipeline(
    sources: Sequence[Path | str],
    boundary: Path | str,
    playbook_path: Path | str,
    playbook_manifest_path: Path | str | None = None,
    activation_path: Path | str | None = None,
    confirmation: str | None = None,
    selected_lenses: Sequence[str] | None = None,
    run_id: str = "review-run",
    out_dir: Path | str | None = None,
    contract_name: str | None = None,
) -> dict[str, Any]:
    """Freeze the package, settle Gate 1, compile the stance and build the term map.

    Gate 1 is settled only by an activation file or by ``confirmation``, the
    lawyer's own words. With neither, the manifest is written and the result
    reports ``awaiting-gate-1`` with the approved lenses so the lawyer can be
    asked. The pipeline never writes ``confirmedByLawyer: true`` on its own.
    """
    sources_paths = [Path(s).resolve(strict=True) for s in sources]
    boundary_path = Path(boundary).resolve(strict=True)
    playbook_file = Path(playbook_path).resolve(strict=True)
    out_path = (
        Path(out_dir).resolve() if out_dir else sources_paths[0].parent / "review-run"
    )
    out_path.mkdir(parents=True, exist_ok=True)

    playbook = load_json(playbook_file)
    playbook_errors = validate_playbook(playbook, require_approved=True)
    if playbook_errors:
        raise PlaybookError(
            "The playbook is not usable for an operative review: "
            + "; ".join(playbook_errors)
        )

    roles = {s.name: "contract-under-review" for s in sources_paths}
    manifest = build_source_manifest(sources_paths, boundary_path, roles)
    write_json_atomic(out_path / "source-manifest.json", manifest)

    intake_warnings: list[str] = []
    documents = manifest.get("documents", [])
    for doc in documents if isinstance(documents, list) else []:
        if isinstance(doc, Mapping):
            for warning in doc.get("warnings", []):
                intake_warnings.append(f"{doc.get('fileName')}: {warning}")
    elements_count = sum(
        len(d.get("elements", []))
        for d in (documents if isinstance(documents, list) else [])
        if isinstance(d, Mapping) and isinstance(d.get("elements"), list)
    )
    result: dict[str, Any] = {
        "runId": run_id,
        "contractName": contract_name or sources_paths[0].stem,
        "outDir": str(out_path),
        "manifestPath": str(out_path / "source-manifest.json"),
        "stancePath": None,
        "termMapPath": None,
        "documentsCount": len(documents) if isinstance(documents, list) else 0,
        "elementsCount": elements_count,
        "operativeRulesCount": 0,
        "intakeWarnings": intake_warnings,
        "gate1": {
            "defaultStance": "standard-baseline",
            "approvedLenses": _approved_lens_summaries(playbook),
        },
    }

    lenses = [str(lens) for lens in (selected_lenses or []) if str(lens).strip()]
    if activation_path:
        activation = load_json(Path(activation_path).resolve(strict=True))
        if activation.get("confirmedByLawyer") is not True:
            raise PlaybookError(
                "The supplied activation is not confirmed by the lawyer; Gate 1 "
                "must be settled before the stance is compiled"
            )
        if lenses and set(lenses) != set(activation.get("activatedLenses", [])):
            raise PlaybookError(
                "--lens conflicts with the activatedLenses in the supplied activation"
            )
    elif confirmation and confirmation.strip():
        activation = {
            "artifactType": "matter-lens-activation",
            "schemaVersion": "1.0",
            "activatedLenses": lenses,
            "suggestedLenses": [],
            "matterInstructions": [],
            "confirmedByLawyer": True,
            "confirmationNote": f"Lawyer's message: {confirmation.strip()!r}",
        }
    else:
        if lenses:
            raise PlaybookError(
                "A Matter Lens can only be activated with the lawyer's confirmation; "
                "pass --confirm with their words or --activation with a confirmed file"
            )
        result["status"] = "awaiting-gate-1"
        return result

    write_json_atomic(out_path / "matter-lens-activation.json", activation)
    stance = compile_effective_stance(playbook, activation)
    write_json_atomic(out_path / "effective-stance.json", stance)
    result["stancePath"] = str(out_path / "effective-stance.json")
    result["operativeRulesCount"] = len(stance.get("issues", []))
    result["activatedLenses"] = list(stance.get("activatedLenses", []))
    if stance.get("status") == "blocked":
        result["status"] = "blocked"
        result["conflicts"] = stance.get("conflicts", [])
        return result

    pb_manifest_file = (
        Path(playbook_manifest_path).resolve(strict=True)
        if playbook_manifest_path
        else playbook_file.parent / "source-manifest.json"
    )
    if pb_manifest_file.exists():
        pb_manifest = load_json(pb_manifest_file)
        term_map = build_term_map_skeleton(pb_manifest, manifest, playbook, run_id)
        term_map_errors = validate_term_map(term_map)
        if term_map_errors:
            raise PlaybookError("Term map is invalid: " + "; ".join(term_map_errors))
        write_json_atomic(out_path / "term-map.json", term_map)
        result["termMapPath"] = str(out_path / "term-map.json")
        result["unresolvedTerms"] = [
            str(entry.get("houseDefinition", {}).get("term") or "")
            for entry in term_map.get("entries", [])
            if isinstance(entry, Mapping) and entry.get("relation") == "unresolved"
        ]

    result["status"] = "ready"
    return result


def run_review_pipeline(
    issues_path: Path | str,
    manifest_path: Path | str | None = None,
    stance_path: Path | str | None = None,
    playbook_path: Path | str | None = None,
    term_map_path: Path | str | None = None,
    out_dir: Path | str | None = None,
    contract_name: str | None = None,
) -> dict[str, Any]:
    """Verify the issues list, reconcile coverage, sign receipts and export.

    Fails before writing anything when the stance is blocked, the issues list
    is bound to a different stance, playbook or manifest, a house term used in
    proposed drafting is still unmapped, or the issues fail validation. A
    coverage gap does not stop the exports, but the receipt records that the
    run did not reconcile and the gaps are returned by name.
    """
    issues_file = Path(issues_path).resolve(strict=True)
    parent_dir = issues_file.parent

    def _locate(explicit: Path | str | None, default_name: str, flag: str) -> Path:
        candidate = (
            Path(explicit).resolve(strict=True)
            if explicit
            else parent_dir / default_name
        )
        if not candidate.exists():
            raise PlaybookError(
                f"Missing {default_name} at {candidate}. Provide {flag} or run "
                "setup-review first."
            )
        return candidate

    manifest_file = _locate(manifest_path, "source-manifest.json", "--manifest")
    stance_file = _locate(stance_path, "effective-stance.json", "--stance")
    playbook_file = Path(playbook_path).resolve(strict=True) if playbook_path else None
    if playbook_file is None and (parent_dir / "playbook.json").exists():
        playbook_file = parent_dir / "playbook.json"
    term_map_file = (
        Path(term_map_path).resolve(strict=True)
        if term_map_path
        else parent_dir / "term-map.json"
    )

    issues = load_json(issues_file)
    manifest = load_json(manifest_file)
    stance = load_json(stance_file)
    playbook = load_json(playbook_file) if playbook_file else None

    if stance.get("status") == "blocked":
        raise PlaybookError(
            "The effective stance is blocked by conflicting lens changes; resolve "
            "the conflicts with the lawyer before reviewing"
        )
    binding_errors: list[str] = []
    if issues.get("effectiveStanceSha256") != stance.get("stanceSha256"):
        binding_errors.append("issues list is bound to a different effective stance")
    if issues.get("playbookId") != stance.get("playbookId"):
        binding_errors.append("issues list names a different playbook")
    if issues.get("playbookVersion") != stance.get("playbookVersion"):
        binding_errors.append("issues list names a different playbook version")
    if binding_errors:
        raise PlaybookError("; ".join(binding_errors))

    issues = populate_issues_markup(issues)
    if contract_name and not issues.get("contractName"):
        issues["contractName"] = contract_name

    index = source_text_index(manifest)
    validation_errors = validate_issues_list(
        issues, index, manifest.get("manifestSha256")
    )
    if validation_errors:
        error_lines = "\n".join(f"  - {err}" for err in validation_errors)
        raise PlaybookError(
            f"Issues list validation failed with {len(validation_errors)} error(s):\n{error_lines}"
        )

    raw_issue_rows = issues.get("issues", [])
    issue_rows = [i for i in raw_issue_rows if isinstance(i, Mapping)]
    if term_map_file.exists():
        blockers = _term_map_blockers(load_json(term_map_file), issue_rows)
        if blockers:
            raise PlaybookError(
                "Proposed drafting uses house defined terms that are not yet mapped "
                "into the contract: " + ", ".join(blockers)
            )

    dest_dir = Path(out_dir).resolve() if out_dir else parent_dir
    dest_dir.mkdir(parents=True, exist_ok=True)

    analysis = _coverage_analysis(manifest, stance, issues)
    coverage = build_coverage_receipt(analysis["counts"])
    write_json_atomic(dest_dir / "coverage-receipt.json", coverage)
    receipt = build_review_receipt(issues, coverage)
    write_json_atomic(dest_dir / "review-receipt.json", receipt)
    write_json_atomic(dest_dir / "issues-list.json", issues)

    effective_name = contract_name or issues.get("contractName")
    internal_docx = dest_dir / "issues-matrix.docx"
    external_docx = dest_dir / "issues-matrix-external.docx"
    html_path = dest_dir / "issues-list.html"
    render_issues_docx(
        issues, internal_docx, playbook=playbook, contract_name=effective_name
    )
    render_issues_docx(
        issues,
        external_docx,
        playbook=playbook,
        contract_name=effective_name,
        audience="external",
    )
    write_text_atomic(html_path, render_issues_html(issues))

    return {
        "status": "reconciled" if coverage.get("reconciled") else "unreconciled",
        "reconciled": bool(coverage.get("reconciled", False)),
        "issuesCount": len(issue_rows),
        "classificationCounts": receipt.get("classificationCounts", {}),
        "coverageGaps": analysis["gaps"],
        "artifacts": {
            "issuesList": str(dest_dir / "issues-list.json"),
            "coverageReceipt": str(dest_dir / "coverage-receipt.json"),
            "reviewReceipt": str(dest_dir / "review-receipt.json"),
            "docxInternal": str(internal_docx),
            "docxExternal": str(external_docx),
            "html": str(html_path),
        },
    }
