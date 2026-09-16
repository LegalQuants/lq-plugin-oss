"""Source census: walk a closing folder into source-manifest.json (PRD §4).

`build_manifest(root)` recursively inventories the supplied folder and returns
the manifest dict described by `../../references/source-manifest.schema.json`:
relative path, size, content hash (the stable document id), format, page
count where a PDF and `pdfinfo` are available, readability, text yield, and
two filename-derived hints. Identical files are grouped by hash in
`duplicate_groups`; nothing is deleted, renamed, moved or written (rule 6 of
`status-taxonomy.md`). The walk is deterministic: documents sorted by
`(id, path)`, no timestamps, no absolute paths, and the same folder contents
give the same `corpus_id`.

The reconciliation invariant carried over from `/diligence` holds here: the
number of files walked, the number of manifest rows, `counts.files` and the
sum of the readability counts must all agree, or `build_manifest` raises
`ValueError` and no manifest exists. The CLI turns that into exit 2.

Standard library only. Poppler's `pdfinfo`/`pdftotext` are probed at run time
and used when present; without them `pages` is null and a small content-stream
scan supplies the text yield. `extractor="stdlib"` forces that fallback so
evals can pin environment-independent output.

**Filename hints are not evidence.** `title_hint` and `version_hint` are
derived from the filename alone by `normalise_title`, the one normaliser the
families stage also applies to checklist titles and ledger agreement names.
They exist so families can group versions of one document; they never say
anything about whether a document is final, signed or executed (rule 1: "A
filename is not evidence"; PRD §4: "No item may be `ready` solely because its
filename says 'final', 'signed' or 'executed'"). Downstream code may cite them
only as `version` or `identity` observations with `source: filename`, never
as `execution` or `date`.

**Symlinks are never followed.** A file symlink whose target resolves inside
the root is inventoried like any other file (its bytes hash to the target's
id, so it lands in a duplicate group). A file symlink whose target resolves
outside the root, or is broken, is excluded from the manifest; so is every
directory symlink, whose contents are never walked through the link.

**Nothing is dropped silently.** Every entry the walk did not inventory —
a symlink resolving outside the root, a hidden entry (name starting with
"."), a directory that could not be read, a special file (socket, fifo,
device) — is listed in the manifest's `skipped[]` with its reason, so the
receipt can count it and the lawyer can see it.

**Readability is per document, not per path.** Every manifest row sharing an
id carries the same readability: the worst probe result across its paths
(corrupt > encrypted > suspect > scanned > native). A zero-byte file is
corrupt whatever its extension.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import zipfile
import zlib
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .models import READABILITY, SCHEMA_VERSION, corpus_id_for

EXTRACTORS = ("auto", "stdlib")
# Worst first: the readability a document id carries is the worst of its rows.
READABILITY_RANK = ("corrupt", "encrypted", "suspect", "scanned", "native")
SKIP_REASONS = (
    "symlink-outside-root",
    "hidden",
    "unreadable-directory",
    "special-file",
)

# A page "yields" if its extracted text contains any alphanumeric character;
# scanned pages extract as empty or whitespace-only.
ALNUM = re.compile(rb"[A-Za-z0-9]")
ALNUM_TEXT = re.compile(r"[A-Za-z0-9]")
TEXT_PROBE_BYTES = 65536

# Word edges that also treat "_" as a separator (`\b` does not).
_L = r"(?<![A-Za-z0-9])"
_R = r"(?![A-Za-z0-9])"
# A real file extension: short, alphanumeric, no spaces. Checklist titles and
# ledger agreement names pass through the same normaliser, so "Amendment No.
# 2" must not lose " 2" to os.path.splitext.
_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,5}$")
# Status words a filename may carry, bare or in brackets. Longer phrases
# first so "agreed form" is one word, not "agreed" + "form".
STATUS_WORDS = (
    "agreed form",
    "execution version",
    "execution copy",
    "executed",
    "execution",
    "exec",
    "conformed",
    "redline",
    "signed",
    "final",
    "draft",
    "clean",
    "scanned",
    "scan",
)
_STATUS_PATTERN = re.compile(
    _L
    + r"(?:"
    + "|".join(re.escape(w).replace(r"\ ", r"[ _.-]+") for w in STATUS_WORDS)
    + r")"
    + _R,
    re.IGNORECASE,
)
# Version markers, in the order they are removed. DMS-style ids first so the
# trailing "v9" of "12345678-v9" is not also matched as a bare "v9"; the
# trailing " - 2" last, after the other markers have been cut from the end.
_VERSION_NUMBER = r"\d+(?:\.\d+)*[a-z]?"
_MARKER_PATTERNS = (
    re.compile(_L + r"\d{6,}[-_ ]?v" + _VERSION_NUMBER + _R, re.IGNORECASE),
    re.compile(r"\(\d+\)"),
    re.compile(
        _L + r"(?:v|ver|version|rev|revision)[ _.-]?" + _VERSION_NUMBER + _R,
        re.IGNORECASE,
    ),
    re.compile(r"(?<=\S)[ _]+-[ _]+\d+\s*$"),
)
# Dates: 2026-09-06, 06.09.2026, 20260906, "6 September 2026", "Sept 6, 2026",
# "September 2026". A bare year is not a date and stays in the title.
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_DATE_PATTERNS = (
    re.compile(_L + r"(?:19|20)\d{2}[-_.\s/]\d{1,2}[-_.\s/]\d{1,2}" + _R),
    re.compile(_L + r"\d{1,2}[-_.\s/]\d{1,2}[-_.\s/](?:19|20)?\d{2}" + _R),
    re.compile(_L + r"(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])" + _R),
    re.compile(
        _L + r"(?:\d{1,2}(?:st|nd|rd|th)?[-_.\s]*)?" + _MONTH + r"\.?[-_.\s,]*"
        r"(?:\d{1,2}(?:st|nd|rd|th)?[-_.\s,]+)?(?:19|20)\d{2}" + _R,
        re.IGNORECASE,
    ),
)
_NON_ALNUM = re.compile(r"[\W_]+")


# ------------------------------------------------------------ filename hints


def normalise_title(filename: str) -> tuple[str, list[str], list[str]]:
    """Return `(title_hint, markers, status_words)` for one filename or title.

    The one normaliser: the families stage applies it to checklist titles and
    ledger agreement names as well, so both sides of a match are cut the same
    way. Steps, in order: strip a real extension; remove status tags such as
    "(Executed)" or "(Scan)" and the same words bare; remove version markers
    ("v3", "v2.1", "(2)", "12345678-v9", "version 3", a trailing " - 2");
    remove dates; turn non-alphanumerics into spaces, casefold and collapse.

    A grouping hint only — never evidence of status (rule 1). If stripping
    leaves nothing (a file called `final v2.pdf`), the normalised stem is
    returned instead so the hint is never empty.
    """

    stem = _EXTENSION.sub("", filename)
    status_words = [
        re.sub(r"[ _.-]+", " ", m.group(0).casefold())
        for m in _STATUS_PATTERN.finditer(stem)
    ]
    work = _STATUS_PATTERN.sub(" ", stem)
    markers: list[str] = []
    for pattern in _MARKER_PATTERNS:
        markers.extend(
            " ".join(m.group(0).casefold().split()) for m in pattern.finditer(work)
        )
        work = pattern.sub(" ", work)
    for pattern in _DATE_PATTERNS:
        work = pattern.sub(" ", work)
    title = _collapse(work) or _collapse(stem)
    return title, markers, status_words


def _collapse(value: str) -> str:
    return " ".join(_NON_ALNUM.sub(" ", value.casefold()).split())


# ------------------------------------------------------------------- hashing


def sha256_id(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()[:12]


# --------------------------------------------------------------- PDF probes

# Every probe returns (pages, readability, text_yield, note); readability is
# None from probe_pdf_info when the structure is sound and the caller must
# still measure text yield.
Probe = tuple[int | None, str | None, float, str | None]


def _has_encrypt_marker(path: str) -> bool:
    with open(path, "rb") as f:
        return b"/Encrypt" in f.read()


def probe_pdf_info(path: str) -> Probe:
    """Return pdfinfo's structural result without requiring pdftotext."""
    info = subprocess.run(
        ["pdfinfo", path], capture_output=True, text=True, errors="replace"
    )
    if info.returncode != 0:
        # pdfinfo refuses a user-password-protected file outright; the
        # /Encrypt marker separates "locked" from "broken".
        if _has_encrypt_marker(path):
            return None, "encrypted", 0.0, None
        return None, "corrupt", 0.0, "unparseable by pdfinfo"
    fields: dict[str, str] = {}
    for line in info.stdout.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fields[k.strip()] = v.strip()
    if fields.get("Encrypted", "").lower().startswith("yes"):
        pages = int(fields["Pages"]) if fields.get("Pages", "").isdigit() else None
        return pages, "encrypted", 0.0, None
    if not fields.get("Pages", "").isdigit():
        return None, "corrupt", 0.0, "no page count"
    pages = int(fields["Pages"])
    if pages == 0:
        return 0, "corrupt", 0.0, "zero pages"
    return pages, None, 0.0, None


def probe_pdf_poppler(path: str) -> Probe:
    """(pages, readability, yield, note) via pdfinfo + per-page pdftotext."""
    pages, readability, _yield, note = probe_pdf_info(path)
    if readability is not None or pages is None:
        return pages, readability or "corrupt", 0.0, note
    yielding = 0
    for p in range(1, pages + 1):
        r = subprocess.run(
            ["pdftotext", "-q", "-f", str(p), "-l", str(p), path, "-"],
            capture_output=True,
        )
        if r.returncode == 0 and ALNUM.search(r.stdout):
            yielding += 1
    y = yielding / pages
    return pages, ("native" if y >= 0.5 else "scanned"), y, None


def probe_pdf_hybrid(path: str) -> Probe:
    """pdfinfo for structure and pages; stdlib only for text yield.

    Modern PDFs may store page objects in compressed object streams that the
    deliberately small stdlib scanner cannot enumerate. A successful pdfinfo
    receipt therefore controls structural validity; stdlib failure merely
    marks the document scanned.
    """
    pages, readability, _yield, note = probe_pdf_info(path)
    if readability is not None:
        return pages, readability, 0.0, note
    _stdlib_pages, stdlib_readability, text_yield, _stdlib_note = probe_pdf_stdlib(path)
    if stdlib_readability == "native":
        return pages, "native", text_yield, None
    return pages, "scanned", 0.0, None


def _pdf_objects(data: bytes) -> dict[int, bytes]:
    return {
        int(m.group(1)): m.group(2)
        for m in re.finditer(rb"(?m)^(\d+)\s+\d+\s+obj\b(.*?)endobj", data, re.S)
    }


def _stream_bytes(body: bytes) -> bytes:
    m = re.search(rb"stream\r?\n(.*?)endstream", body, re.S)
    if not m:
        return b""
    raw = m.group(1)
    if b"/FlateDecode" in body:
        try:
            raw = zlib.decompress(raw.rstrip(b"\r\n"))
        except zlib.error:
            return b""
    return raw


def probe_pdf_stdlib(path: str) -> Probe:
    """Degraded probe when poppler is absent: raw/Flate content-stream scan.

    Pages stays null: pdfinfo is the page-count authority.
    """
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(b"%PDF-"):
        return None, "corrupt", 0.0, "not a PDF"
    if b"%%EOF" not in data[-1024:]:
        return None, "corrupt", 0.0, "truncated stream"
    if b"/Encrypt" in data:
        return None, "encrypted", 0.0, None
    objs = _pdf_objects(data)
    page_bodies = [b for b in objs.values() if re.search(rb"/Type\s*/Page[^s]", b)]
    if not page_bodies:
        return None, "corrupt", 0.0, "no page objects"
    yielding = 0
    for body in page_bodies:
        m = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", body)
        content = _stream_bytes(objs.get(int(m.group(1)), b"")) if m else b""
        shown = b""
        if b"Tj" in content or b"TJ" in content:
            shown = b"".join(re.findall(rb"\((?:[^()\\]|\\.)*\)", content))
        if ALNUM.search(shown):
            yielding += 1
    y = yielding / len(page_bodies)
    return None, ("native" if y >= 0.5 else "scanned"), y, None


# ------------------------------------------------------- Office text probes


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _zip_xml(archive: zipfile.ZipFile, member: str) -> ElementTree.Element:
    """Parse one Office XML part. Entity declarations are refused: Office
    never writes them, and the stdlib parser is the only one available."""
    try:
        data = archive.read(member)
        if b"<!ENTITY" in data or b"<!DOCTYPE" in data:
            raise OSError(f"{member} declares XML entities")
        return ElementTree.fromstring(data)
    except (
        KeyError,
        ElementTree.ParseError,
        zipfile.BadZipFile,
        NotImplementedError,
        OSError,
        zlib.error,
    ) as error:
        raise OSError(f"cannot parse {member}: {error}") from error


def docx_text(path: str) -> str:
    """Visible body text of a DOCX, enough to say whether it carries text."""
    try:
        with zipfile.ZipFile(path) as archive:
            root = _zip_xml(archive, "word/document.xml")
    except (zipfile.BadZipFile, OSError) as error:
        raise OSError(f"cannot parse DOCX: {error}") from error
    parts: list[str] = []
    for node in root.iter():
        name = _local_name(node.tag)
        if name == "t" and node.text:
            parts.append(node.text)
        elif name in {"tab", "br", "cr", "p"}:
            parts.append(" ")
    return " ".join("".join(parts).split())


def xlsx_text(path: str) -> str:
    """Shared strings, inline strings and cell values of every worksheet."""
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.namelist()
            if "xl/workbook.xml" not in members:
                raise OSError("no xl/workbook.xml")
            parts: list[str] = []
            if "xl/sharedStrings.xml" in members:
                strings = _zip_xml(archive, "xl/sharedStrings.xml")
                parts.extend(
                    node.text
                    for node in strings.iter()
                    if _local_name(node.tag) == "t" and node.text
                )
            for member in sorted(members):
                if not (
                    member.startswith("xl/worksheets/") and member.endswith(".xml")
                ):
                    continue
                sheet = _zip_xml(archive, member)
                parts.extend(
                    node.text
                    for node in sheet.iter()
                    if _local_name(node.tag) in {"v", "t"} and node.text
                )
    except (zipfile.BadZipFile, OSError) as error:
        raise OSError(f"cannot parse XLSX: {error}") from error
    return " ".join(" ".join(parts).split())


# --------------------------------------------------------- non-PDF probing


def structural_truncation_reason(head: str, tail: str | None = None) -> str | None:
    """Return a strong markup-truncation receipt, else None.

    Missing closing wrappers and EOF inside a tag are objective completeness
    failures; ordinary unmarked plain text is not guessed incomplete. Large
    files are checked with separate head and tail samples so a close marker
    beyond the first probe window is not mistaken for a missing marker.
    """
    tail = head if tail is None else tail
    for tag in ("document", "html", "body"):
        if re.search(rf"<{tag}\b", head, re.I) and not (
            re.search(rf"</{tag}\s*>", head, re.I)
            or re.search(rf"</{tag}\s*>", tail, re.I)
        ):
            return f"missing </{tag.upper()}> close marker"
    if re.search(r"<[^>]*\Z", tail.rstrip(), re.S):
        return "EOF inside markup tag"
    return None


def probe_other(path: str) -> Probe:
    """Non-PDF: decodable text is native; opaque binary maps to scanned.

    The schema has no fifth class; scanned means "needs stronger extraction".
    Legacy encodings (latin-1) are text too: on a UTF-8 failure, decode latin-1
    and require a high printable ratio, since latin-1 never fails and would
    otherwise call any binary native.
    """
    suffix = path.casefold()
    if suffix.endswith((".docx", ".xlsx")):
        extractor = docx_text if suffix.endswith(".docx") else xlsx_text
        try:
            text = extractor(path)
        except OSError as error:
            return None, "corrupt", 0.0, str(error)
        if ALNUM_TEXT.search(text):
            return None, "native", 1.0, None
        return None, "scanned", 0.0, None
    try:
        with open(path, "rb") as f:
            head_bytes = f.read(TEXT_PROBE_BYTES)
            size = os.fstat(f.fileno()).st_size
            if size > TEXT_PROBE_BYTES:
                f.seek(max(0, size - TEXT_PROBE_BYTES))
                tail_bytes = f.read(TEXT_PROBE_BYTES)
            else:
                tail_bytes = head_bytes
    except OSError:
        return None, "scanned", 0.0, None
    try:
        text = head_bytes.decode("utf-8")
        tail = tail_bytes.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        text = head_bytes.decode("latin-1")
        tail = tail_bytes.decode("latin-1")
        printable = sum(1 for c in text if c.isprintable() or c in "\r\n\t")
        if text and printable / len(text) < 0.9:
            return None, "scanned", 0.0, None
    reason = structural_truncation_reason(text, tail)
    if reason:
        return None, "suspect", 1.0, reason
    if ALNUM_TEXT.search(text):
        return None, "native", 1.0, None
    return None, "scanned", 0.0, None


# ------------------------------------------------------------------- walking


def _walk(root: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Return `(file paths, skipped entries)`, both sorted.

    Directory symlinks are never descended (os.walk does not follow them) and
    are reported. File symlinks are kept only when their target resolves to a
    regular file inside the resolved root. Every entry not inventoried is
    returned as `{"path", "reason"}` (source-manifest.schema.json `skipped[]`).
    """
    root_str = os.fspath(root)
    real_root = os.path.realpath(root_str)
    found: list[str] = []
    skipped: list[dict[str, str]] = []

    def skip(full: str, reason: str) -> None:
        assert reason in SKIP_REASONS
        skipped.append({"path": _rel(full, root_str), "reason": reason})

    def unreadable(error: OSError) -> None:
        full = error.filename if isinstance(error.filename, str) else root_str
        skip(full, "unreadable-directory")

    for dirpath, dirnames, filenames in os.walk(
        root_str, followlinks=False, onerror=unreadable
    ):
        kept: list[str] = []
        for d in sorted(dirnames):
            full = os.path.join(dirpath, d)
            if d.startswith("."):
                skip(full, "hidden")
            elif os.path.islink(full):
                skip(full, "symlink-outside-root")
            else:
                kept.append(d)
        dirnames[:] = kept
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            if name.startswith("."):
                skip(full, "hidden")
                continue
            if os.path.islink(full):
                target = os.path.realpath(full)
                inside = target == real_root or target.startswith(real_root + os.sep)
                if not (inside and os.path.isfile(target)):
                    skip(full, "symlink-outside-root")
                    continue
            elif not os.path.isfile(full):
                skip(full, "special-file")
                continue
            found.append(full)
    return sorted(found), sorted(skipped, key=lambda s: (s["path"], s["reason"]))


def _rel(path: str, root: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def skipped_entries(root: Path) -> list[dict[str, str]]:
    """The `skipped[]` entries `build_manifest` would write for `root`."""
    _require_dir(root)
    return _walk(root)[1]


def _require_dir(root: Path) -> None:
    if not os.path.isdir(root):
        raise NotADirectoryError(f"census root is not a directory: {root.name or root}")


# ------------------------------------------------------------------ manifest


def build_manifest(root: Path, *, extractor: str = "auto") -> dict[str, Any]:
    """Walk `root` and return the source manifest as a dict.

    `extractor` is `"auto"` (use Poppler when installed) or `"stdlib"` (force
    the fallback PDF probe; `pages` is null). Raises `ValueError` when the
    walk and the rows do not reconcile — zero unreconciled items is an
    invariant and no manifest is returned in that case.
    """
    if extractor not in EXTRACTORS:
        raise ValueError(f"extractor must be one of {EXTRACTORS}, got {extractor!r}")
    _require_dir(root)
    root_str = os.fspath(root)
    have_pdfinfo = shutil.which("pdfinfo") is not None
    have_pdftotext = shutil.which("pdftotext") is not None
    if extractor == "stdlib" or not have_pdfinfo:
        pdf_probe = probe_pdf_stdlib
    elif have_pdftotext:
        pdf_probe = probe_pdf_poppler
    else:
        pdf_probe = probe_pdf_hybrid

    files, skipped = _walk(root)
    documents: list[dict[str, Any]] = []
    counts: dict[str, int] = {
        "corrupt": 0,
        "distinct": 0,
        "encrypted": 0,
        "files": 0,
        "native": 0,
        "scanned": 0,
        "suspect": 0,
    }
    for path in files:
        rel = _rel(path, root_str)
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lstrip(".").lower()
        size = os.path.getsize(path)
        if size == 0:
            # Nothing to read, whatever the extension says it is.
            pages, readability, y = None, "corrupt", 0.0
        elif ext == "pdf":
            pages, readability, y, _note = pdf_probe(path)
        else:
            pages, readability, y, _note = probe_other(path)
        if readability not in READABILITY:
            raise ValueError(f"{rel}: probe returned readability {readability!r}")
        title_hint, markers, status_words = normalise_title(name)
        version_hint = {"markers": markers, "status_words": status_words}
        documents.append(
            {
                "bytes": size,
                "ext": ext,
                "id": sha256_id(path),
                "pages": pages,
                "path": rel,
                "readability": readability,
                "text_yield": round(y, 2),
                "title_hint": title_hint,
                "version_hint": version_hint,
            }
        )
        counts["files"] += 1

    # Readability is a property of the bytes, not the path: every row sharing
    # an id carries the worst result any of its paths produced.
    worst_by_id: dict[str, str] = {}
    for d in documents:
        current = worst_by_id.get(d["id"])
        if current is None or READABILITY_RANK.index(
            d["readability"]
        ) < READABILITY_RANK.index(current):
            worst_by_id[d["id"]] = d["readability"]
    for d in documents:
        d["readability"] = worst_by_id[d["id"]]
        counts[d["readability"]] += 1

    documents.sort(key=lambda d: (d["id"], d["path"]))
    ids = {d["id"] for d in documents}
    counts["distinct"] = len(ids)
    readability_total = sum(counts[key] for key in sorted(READABILITY))
    paths = [d["path"] for d in documents]
    if (
        counts["files"] != len(documents)
        or counts["files"] != len(files)
        or counts["files"] != readability_total
        or len(paths) != len(set(paths))
    ):
        raise ValueError(
            f"manifest does not reconcile with walk: walked {len(files)} files, "
            f"{len(documents)} manifest rows ({len(set(paths))} distinct paths), "
            f"counts.files={counts['files']}, readability total "
            f"{readability_total}. Zero unreconciled items is "
            "an invariant; refusing to write."
        )

    # A byte-duplicate file yields two rows sharing one id. The first row in
    # (id, path) order is the canonical path; the rest are grouped, never
    # removed (rule 6).
    paths_by_id: dict[str, list[str]] = {}
    for d in documents:
        paths_by_id.setdefault(d["id"], []).append(d["path"])
    duplicate_groups = [
        {"canonical_path": dpaths[0], "duplicate_paths": dpaths[1:], "id": did}
        for did, dpaths in sorted(paths_by_id.items())
        if len(dpaths) > 1
    ]

    return {
        "corpus_id": corpus_id_for(ids),
        "counts": counts,
        "documents": documents,
        "duplicate_groups": duplicate_groups,
        "root_label": os.path.basename(os.path.realpath(root_str)),
        "schema_version": SCHEMA_VERSION,
        "skipped": skipped,
    }
