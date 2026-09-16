#!/usr/bin/env python3
"""Build and verify deterministic, hash-bound offline review copies.

The sidecar binds every manifest row to the complete source hash and to each
byte of every derivative.  It contains no timestamps or absolute paths.  The
same module also renders conservative HTML components from a successfully
revalidated sidecar; it never mutates findings or evidence receipts.

Usage:
    python3 review_copies.py build --manifest manifest.json \
        --source-root room --sidecar review-copies.json \
        --bundle-root review-copies --mode auto
    python3 review_copies.py verify --manifest manifest.json \
        --source-root room --sidecar review-copies.json
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import zipfile
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

SCHEMA_VERSION = "lq-review-copies-v1"
RENDERER_VERSION = "2"
TEXT_EXTENSIONS = {
    "csv",
    "htm",
    "html",
    "json",
    "log",
    "md",
    "text",
    "txt",
    "xml",
}
IMAGE_MEDIA_TYPES = {
    "bmp": "image/bmp",
    "gif": "image/gif",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
OFFICE_EXTENSIONS = {"docx", "pptx", "xlsx"}
MAX_ZIP_MEMBERS = 20_000
MAX_ZIP_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
DOC_ID_RE = re.compile(r"^sha256:[0-9a-f]{12}$")


class ReviewCopyError(ValueError):
    """A fail-closed path, schema, or containment error."""


@dataclass(frozen=True)
class ValidationResult:
    """Result of a full sidecar, source, and derivative revalidation."""

    integrity_ok: bool
    ready: bool
    errors: tuple[str, ...]
    sidecar: dict[str, Any] | None
    sidecar_path: Path


@dataclass(frozen=True)
class BuildResult:
    """Result returned after the sidecar has been written and revalidated."""

    sidecar: dict[str, Any]
    validation: ValidationResult


def canonical_json_bytes(value: Any) -> bytes:
    """Return the canonical bytes used by all digests in this contract."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _bytes_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReviewCopyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle, object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewCopyError(f"could not read JSON {path.name}: {exc}") from exc


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _relative_parts(value: str, label: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value:
        raise ReviewCopyError(f"{label} must be a non-empty relative path")
    if "\\" in value:
        raise ReviewCopyError(f"{label} must use forward slashes")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ReviewCopyError(f"{label} escapes its allowed root: {value}")
    return path.parts


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _contained_source(root: Path, relative: str) -> Path:
    parts = _relative_parts(relative, "manifest document path")
    lexical = root.joinpath(*parts)
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise ReviewCopyError(f"source is missing or unreadable: {relative}") from exc
    if not _is_relative_to(resolved, root):
        raise ReviewCopyError(f"source symlink escapes the source root: {relative}")
    if not resolved.is_file():
        raise ReviewCopyError(f"source is not a regular file: {relative}")
    return resolved


def _assert_no_output_symlink(base: Path, parts: tuple[str, ...]) -> None:
    current = base
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ReviewCopyError(
                f"bundle path contains a symlink and is refused: {current.name}"
            )


def _bundle_directory(sidecar_path: Path, bundle_root: str, *, create: bool) -> Path:
    parts = _relative_parts(bundle_root, "bundle_root")
    sidecar_parent = sidecar_path.parent.resolve()
    _assert_no_output_symlink(sidecar_parent, parts)
    bundle = sidecar_parent.joinpath(*parts)
    if create:
        bundle.mkdir(parents=True, exist_ok=True)
    try:
        resolved = bundle.resolve(strict=True)
    except OSError as exc:
        raise ReviewCopyError("review-copy bundle is missing") from exc
    if not _is_relative_to(resolved, sidecar_parent):
        raise ReviewCopyError("bundle_root escapes the sidecar directory")
    if not resolved.is_dir():
        raise ReviewCopyError("bundle_root is not a directory")
    return resolved


def _renderer(name: str, version: str = RENDERER_VERSION) -> dict[str, str]:
    return {"name": name, "version": version}


def _safe_extension(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "", value.casefold())
    return cleaned[:12] or "bin"


def _write_derivative(
    bundle: Path,
    data: bytes,
    *,
    extension: str,
    media_type: str,
    role: str,
    renderer: dict[str, str],
    page: int | None = None,
) -> dict[str, Any]:
    digest = hashlib.sha256(data).hexdigest()
    extension = _safe_extension(extension)
    relative = f"objects/{digest[:2]}/{digest}.{extension}"
    parts = _relative_parts(relative, "derivative path")
    _assert_no_output_symlink(bundle, parts)
    target = bundle.joinpath(*parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ReviewCopyError("refusing to replace a symlinked derivative")
    if target.exists() and target.read_bytes() != data:
        raise ReviewCopyError("content-addressed derivative contains different bytes")
    target.write_bytes(data)
    derivative: dict[str, Any] = {
        "bytes": len(data),
        "media_type": media_type,
        "path": relative,
        "renderer": renderer,
        "role": role,
        "sha256": "sha256:" + digest,
    }
    if page is not None:
        derivative["page"] = page
    return derivative


def _decode_text(data: bytes) -> str:
    encodings = ["utf-8-sig"]
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.append("utf-16")
    encodings.append("latin-1")
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ReviewCopyError("text could not be decoded")


def _replace_surrogates(value: str) -> str:
    """Return UTF-8-safe text while preserving every valid Unicode scalar."""

    return "".join(
        "\ufffd" if 0xD800 <= ord(character) <= 0xDFFF else character
        for character in value
    )


def _text_review_html(title: str, text: str, *, label: str = "Full text") -> bytes:
    safe_title = html.escape(_replace_surrogates(title), quote=True)
    safe_label = html.escape(_replace_surrogates(label), quote=True)
    safe_text = html.escape(_replace_surrogates(text), quote=False)
    document = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{safe_title}</title><style>"
        ":root{color-scheme:light dark}body{margin:0;padding:1rem;"
        "font:400 15px/1.55 system-ui,-apple-system,sans-serif;"
        "background:Canvas;color:CanvasText}h1{font-size:1rem;font-weight:500;"
        "margin:0 0 .75rem}pre{font:400 13px/1.55 ui-monospace,monospace;"
        "white-space:pre-wrap;overflow-wrap:anywhere;margin:0}"
        "</style></head><body>"
        f"<h1>{safe_label}: {safe_title}</h1><pre>{safe_text}</pre>"
        "</body></html>"
    )
    return document.encode("utf-8")


def _image_media_type(ext: str, data: bytes) -> str | None:
    ext = ext.casefold()
    valid = False
    if ext == "png":
        valid = data.startswith(b"\x89PNG\r\n\x1a\n")
    elif ext in {"jpg", "jpeg"}:
        valid = data.startswith(b"\xff\xd8\xff")
    elif ext == "gif":
        valid = data.startswith((b"GIF87a", b"GIF89a"))
    elif ext == "webp":
        valid = len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    elif ext == "bmp":
        valid = data.startswith(b"BM")
    return IMAGE_MEDIA_TYPES.get(ext) if valid else None


def _zip_parts(data: bytes) -> tuple[zipfile.ZipFile, list[zipfile.ZipInfo]]:
    stream = io.BytesIO(data)
    try:
        archive = zipfile.ZipFile(stream)
        infos = archive.infolist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReviewCopyError("Office file is not a readable OOXML package") from exc
    if len(infos) > MAX_ZIP_MEMBERS:
        archive.close()
        raise ReviewCopyError("Office package has too many members")
    if sum(info.file_size for info in infos) > MAX_ZIP_UNCOMPRESSED_BYTES:
        archive.close()
        raise ReviewCopyError("Office package is too large to expand safely")
    for info in infos:
        if info.is_dir():
            name = info.filename.rstrip("/")
            if name:
                _relative_parts(name, "Office package member")
            continue
        try:
            _relative_parts(info.filename, "Office package member")
        except ReviewCopyError:
            archive.close()
            raise
    return archive, infos


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _numeric_suffix(value: str, pattern: str) -> int:
    match = re.search(pattern, value)
    if match is None:
        raise ReviewCopyError(f"expected numbered path, got {value!r}")
    return int(match.group(1))


def _xml_visible_text(data: bytes) -> str:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise ReviewCopyError("Office XML could not be parsed") from exc
    pieces: list[str] = []

    def walk(element: ElementTree.Element) -> None:
        name = _local_name(element.tag)
        if name in {"del", "delText", "instrText"}:
            return
        if name == "t" and element.text:
            pieces.append(element.text)
            return
        if name == "tab":
            pieces.append("\t")
            return
        if name in {"br", "cr"}:
            pieces.append("\n")
            return
        for child in element:
            walk(child)
        if name in {"p", "tr"}:
            pieces.append("\n")
        elif name == "tc":
            pieces.append("\t")

    walk(root)
    return "".join(pieces).strip()


def _docx_text(data: bytes) -> str:
    archive, infos = _zip_parts(data)
    try:
        names = {info.filename for info in infos}
        selected = ["word/document.xml"]
        selected.extend(
            sorted(
                name
                for name in names
                if re.fullmatch(
                    r"word/(header\d+|footer\d+|footnotes|endnotes|comments)\.xml",
                    name,
                )
            )
        )
        if "word/document.xml" not in names:
            raise ReviewCopyError("DOCX has no word/document.xml")
        sections = []
        for name in selected:
            text = _xml_visible_text(archive.read(name))
            if text:
                sections.append(f"[{PurePosixPath(name).name}]\n{text}")
        return "\n\n".join(sections)
    finally:
        archive.close()


def _xlsx_text(data: bytes) -> str:
    archive, infos = _zip_parts(data)
    try:
        names = {info.filename for info in infos}
        worksheets = sorted(
            (
                name
                for name in names
                if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
            ),
            key=lambda name: _numeric_suffix(name, r"(\d+)\.xml$"),
        )
        if not worksheets:
            raise ReviewCopyError("XLSX has no worksheets")
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            try:
                root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            except ElementTree.ParseError as exc:
                raise ReviewCopyError(
                    "XLSX shared strings could not be parsed"
                ) from exc
            for item in root.iter():
                if _local_name(item.tag) == "si":
                    shared.append(
                        "".join(
                            node.text or ""
                            for node in item.iter()
                            if _local_name(node.tag) == "t"
                        )
                    )
        sections: list[str] = []
        for number, name in enumerate(worksheets, start=1):
            try:
                root = ElementTree.fromstring(archive.read(name))
            except ElementTree.ParseError as exc:
                raise ReviewCopyError(
                    f"XLSX worksheet {number} could not be parsed"
                ) from exc
            lines = [f"[Worksheet {number}: {PurePosixPath(name).name}]"]
            for row in root.iter():
                if _local_name(row.tag) != "row":
                    continue
                cells: list[str] = []
                for cell in row:
                    if _local_name(cell.tag) != "c":
                        continue
                    reference = cell.attrib.get("r", "cell")
                    cell_type = cell.attrib.get("t")
                    formula = next(
                        (
                            node.text or ""
                            for node in cell
                            if _local_name(node.tag) == "f"
                        ),
                        "",
                    )
                    value = next(
                        (
                            node.text or ""
                            for node in cell
                            if _local_name(node.tag) == "v"
                        ),
                        "",
                    )
                    if cell_type == "s" and value.isdigit():
                        index = int(value)
                        value = (
                            shared[index]
                            if index < len(shared)
                            else "[bad string index]"
                        )
                    elif cell_type == "inlineStr":
                        value = "".join(
                            node.text or ""
                            for node in cell.iter()
                            if _local_name(node.tag) == "t"
                        )
                    shown = f"={formula} -> {value}" if formula else value
                    cells.append(f"{reference}: {shown}")
                if cells:
                    lines.append("\t".join(cells))
            sections.append("\n".join(lines))
        return "\n\n".join(sections)
    finally:
        archive.close()


def _pptx_text(data: bytes) -> str:
    archive, infos = _zip_parts(data)
    try:
        names = {info.filename for info in infos}
        slides = sorted(
            (name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
            key=lambda name: _numeric_suffix(name, r"(\d+)\.xml$"),
        )
        if not slides:
            raise ReviewCopyError("PPTX has no slides")
        sections = []
        for number, name in enumerate(slides, start=1):
            text = _xml_visible_text(archive.read(name))
            sections.append(f"[Slide {number}]\n{text}")
        return "\n\n".join(sections)
    finally:
        archive.close()


def _tool_version(tool: str) -> str:
    try:
        result = subprocess.run(
            [tool, "-v"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    combined = (result.stderr or result.stdout).strip().splitlines()
    if not combined:
        return "unknown"
    match = re.search(r"\d+(?:\.\d+)+", combined[0])
    return match.group(0) if match else "unknown"


def _poppler_pages(
    pdf_data: bytes,
    bundle: Path,
    *,
    role: str,
    renderer_override: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    tool = shutil.which("pdftoppm")
    if not tool:
        return []
    with tempfile.TemporaryDirectory(prefix="lq-review-pdf-") as temp_name:
        temp = Path(temp_name)
        source = temp / "source.pdf"
        prefix = temp / "page"
        source.write_bytes(pdf_data)
        try:
            result = subprocess.run(
                [tool, "-png", "-r", "144", str(source), str(prefix)],
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if result.returncode != 0:
            return []
        pages = sorted(
            temp.glob("page-*.png"),
            key=lambda path: _numeric_suffix(path.name, r"-(\d+)\.png$"),
        )
        renderer = renderer_override or _renderer(
            "poppler-pdftoppm", _tool_version(tool)
        )
        return [
            _write_derivative(
                bundle,
                page_path.read_bytes(),
                extension="png",
                media_type="image/png",
                role=role,
                renderer=renderer,
                page=page_number,
            )
            for page_number, page_path in enumerate(pages, start=1)
        ]


def _office_pdf_derivatives(
    source_data: bytes, ext: str, bundle: Path
) -> list[dict[str, Any]]:
    tool = shutil.which("libreoffice") or shutil.which("soffice")
    poppler = shutil.which("pdftoppm")
    if not tool or not poppler:
        return []
    with tempfile.TemporaryDirectory(prefix="lq-review-office-") as temp_name:
        temp = Path(temp_name)
        source = temp / f"source.{ext}"
        output = temp / "out"
        profile = temp / "profile"
        output.mkdir()
        profile.mkdir()
        source.write_bytes(source_data)
        try:
            result = subprocess.run(
                [
                    tool,
                    f"-env:UserInstallation={profile.as_uri()}",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(output),
                    str(source),
                ],
                capture_output=True,
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        pdfs = sorted(output.glob("*.pdf"))
        if result.returncode != 0 or len(pdfs) != 1:
            return []
        pdf_data = pdfs[0].read_bytes()
        if not pdf_data.startswith(b"%PDF-"):
            return []
        # LibreOffice injects volatile PDF metadata (including CreationDate), so
        # the temporary PDF is never persisted or receipted. Poppler raster
        # pages are the deterministic review derivatives.
        renderer = _renderer(
            "libreoffice+poppler-pdftoppm",
            f"{_tool_version(tool)}+{_tool_version(poppler)}",
        )
        return _poppler_pages(
            pdf_data,
            bundle,
            role="converted-page",
            renderer_override=renderer,
        )


def _render_payload(
    data: bytes,
    ext: str,
    title: str,
    bundle: Path,
    *,
    mode: str,
) -> tuple[str, str, str | None, list[dict[str, Any]]]:
    ext = ext.casefold()
    derivatives: list[dict[str, Any]] = []
    if ext in TEXT_EXTENSIONS:
        try:
            text = _decode_text(data)
        except ReviewCopyError as exc:
            return "text", "needs-rendering", str(exc), []
        review = _text_review_html(title, text)
        derivatives.append(
            _write_derivative(
                bundle,
                review,
                extension="html",
                media_type="text/html",
                role="full-text",
                renderer=_renderer("lq-escaped-text"),
            )
        )
        return "text", "ready", None, derivatives

    if ext == "eml":
        raise ReviewCopyError("EML payloads must use the message renderer")

    if ext in IMAGE_MEDIA_TYPES:
        media_type = _image_media_type(ext, data)
        if not media_type:
            return (
                "image",
                "needs-rendering",
                "Image signature does not match its extension.",
                [],
            )
        derivatives.append(
            _write_derivative(
                bundle,
                data,
                extension=ext,
                media_type=media_type,
                role="image",
                renderer=_renderer("browser-native-image"),
            )
        )
        return "image", "ready", None, derivatives

    if ext == "pdf":
        if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-4096:]:
            return (
                "pdf",
                "needs-rendering",
                "PDF signature or end marker is invalid.",
                [],
            )
        derivatives.append(
            _write_derivative(
                bundle,
                data,
                extension="pdf",
                media_type="application/pdf",
                role="browser-pdf",
                renderer=_renderer("browser-native-pdf"),
            )
        )
        if mode == "auto":
            derivatives.extend(_poppler_pages(data, bundle, role="pdf-page"))
        return "pdf", "ready", None, derivatives

    if ext in OFFICE_EXTENSIONS:
        try:
            if ext == "docx":
                text = _docx_text(data)
            elif ext == "xlsx":
                text = _xlsx_text(data)
            else:
                text = _pptx_text(data)
        except ReviewCopyError as exc:
            return ext, "needs-rendering", str(exc), []
        review = _text_review_html(title, text, label="Safe visible-text review copy")
        derivatives.append(
            _write_derivative(
                bundle,
                review,
                extension="html",
                media_type="text/html",
                role="visible-text",
                renderer=_renderer(f"lq-{ext}-visible-text"),
            )
        )
        if mode == "auto":
            derivatives.extend(_office_pdf_derivatives(data, ext, bundle))
        return ext, "ready", None, derivatives

    return (
        "unsupported",
        "needs-rendering",
        "No safe offline review-copy renderer is available for "
        f".{ext or 'unknown'} files.",
        [],
    )


def _safe_attachment_filename(message_part: Any, number: int) -> str:
    filename = message_part.get_filename()
    if filename:
        return PurePosixPath(str(filename).replace("\\", "/")).name
    guessed = mimetypes.guess_extension(message_part.get_content_type()) or ".bin"
    return f"attachment-{number}{guessed}"


def _eml_document(
    data: bytes,
    title: str,
    bundle: Path,
    *,
    mode: str,
) -> tuple[str, str | None, list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        message = BytesParser(policy=policy.default).parsebytes(data)
    except Exception as exc:  # email defects vary by Python minor version
        return (
            "needs-rendering",
            f"EML could not be parsed: {type(exc).__name__}.",
            [],
            [],
        )

    header_lines = [f"{name}: {value}" for name, value in message.raw_items()]
    body_sections: list[str] = []
    attachments: list[dict[str, Any]] = []
    parts = list(message.walk()) if message.is_multipart() else [message]
    attachment_number = 0
    for part in parts:
        if part.is_multipart():
            continue
        disposition = part.get_content_disposition()
        filename = part.get_filename()
        if disposition == "attachment" or filename:
            attachment_number += 1
            raw_payload = part.get_payload(decode=True)
            payload = raw_payload if isinstance(raw_payload, bytes) else b""
            safe_name = _safe_attachment_filename(part, attachment_number)
            ext = PurePosixPath(safe_name).suffix.lstrip(".").casefold()
            try:
                kind, status, reason, derivatives = _render_payload(
                    payload, ext, safe_name, bundle, mode=mode
                )
            except ReviewCopyError as exc:
                kind, status, reason, derivatives = (
                    "unsupported",
                    "needs-rendering",
                    str(exc),
                    [],
                )
            source_digest = _bytes_digest(payload)
            attachments.append(
                {
                    "attachment_id": source_digest,
                    "bytes": len(payload),
                    "derivatives": derivatives,
                    "filename": safe_name,
                    "kind": kind,
                    "reason": reason,
                    "source_sha256": source_digest,
                    "status": status,
                }
            )
            continue
        content_type = part.get_content_type()
        if content_type.startswith("text/"):
            raw_payload = part.get_payload(decode=True)
            payload = (
                raw_payload
                if isinstance(raw_payload, bytes)
                else str(part.get_payload()).encode("utf-8", errors="replace")
            )
            charset = part.get_content_charset() or "utf-8"
            try:
                body = payload.decode(charset)
            except (LookupError, UnicodeDecodeError):
                body = _decode_text(payload)
            body_sections.append(f"[{content_type}]\n{body}")

    inventory = [
        f"- {item['filename']} ({item['bytes']} bytes; {item['source_sha256']})"
        for item in attachments
    ]
    text = "\n".join(header_lines)
    text += "\n\n" + ("\n\n".join(body_sections) or "[No safe text body found]")
    if inventory:
        text += "\n\n[Attachments]\n" + "\n".join(inventory)
    derivative = _write_derivative(
        bundle,
        _text_review_html(title, text, label="Safe email review copy"),
        extension="html",
        media_type="text/html",
        role="email",
        renderer=_renderer("lq-safe-eml"),
    )
    failed = [item for item in attachments if item["status"] != "ready"]
    if failed:
        names = ", ".join(item["filename"] for item in failed)
        return (
            "needs-rendering",
            f"Email attachment needs rendering: {names}.",
            [derivative],
            attachments,
        )
    return "ready", None, [derivative], attachments


def _manifest_documents(manifest: Any) -> list[dict[str, Any]]:
    if not isinstance(manifest, dict) or not isinstance(
        manifest.get("documents"), list
    ):
        raise ReviewCopyError("manifest must contain a documents array")
    documents = manifest["documents"]
    for index, row in enumerate(documents):
        if not isinstance(row, dict):
            raise ReviewCopyError(f"manifest documents[{index}] must be an object")
        for field in ("id", "path", "bytes"):
            if field not in row:
                raise ReviewCopyError(f"manifest documents[{index}] lacks {field}")
        if not DOC_ID_RE.fullmatch(str(row["id"])):
            raise ReviewCopyError(
                f"manifest documents[{index}].id is not a stable doc ID"
            )
        if (
            not isinstance(row["bytes"], int)
            or isinstance(row["bytes"], bool)
            or row["bytes"] < 0
        ):
            raise ReviewCopyError(f"manifest documents[{index}].bytes is invalid")
        _relative_parts(row["path"], f"manifest documents[{index}].path")
    return documents


def build_review_copies(
    manifest_path: str | os.PathLike[str],
    source_root: str | os.PathLike[str],
    sidecar_path: str | os.PathLike[str],
    *,
    bundle_root: str = "review-copies",
    mode: str = "auto",
) -> BuildResult:
    """Build a sidecar and bundle, then revalidate both from disk.

    ``bundle_root`` is a durable relative reference resolved beneath the
    sidecar's directory.  ``mode='text'`` disables optional external
    converters; ``mode='auto'`` adds Poppler/LibreOffice derivatives when the
    corresponding executable is already available.
    """

    if mode not in {"auto", "text"}:
        raise ReviewCopyError("mode must be auto or text")
    manifest_path = Path(manifest_path).resolve(strict=True)
    source_root_path = Path(source_root).resolve(strict=True)
    if not source_root_path.is_dir():
        raise ReviewCopyError("source_root is not a directory")
    sidecar_path = Path(sidecar_path).absolute()
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = _load_json(manifest_path)
    rows = _manifest_documents(manifest)
    bundle = _bundle_directory(sidecar_path, bundle_root, create=True)

    documents: list[dict[str, Any]] = []
    for row in rows:
        relative = row["path"]
        source = _contained_source(source_root_path, relative)
        data = source.read_bytes()
        source_digest = _bytes_digest(data)
        ext = str(
            row.get("ext") or PurePosixPath(relative).suffix.lstrip(".")
        ).casefold()
        reason: str | None = None
        derivatives: list[dict[str, Any]] = []
        attachments: list[dict[str, Any]] = []
        kind = ext or "unknown"

        if len(data) != row["bytes"]:
            status = "needs-rendering"
            reason = "Source size no longer matches the manifest; rebuild the manifest."
        elif row["id"] != "sha256:" + source_digest.removeprefix("sha256:")[:12]:
            status = "needs-rendering"
            reason = "Source hash no longer matches the manifest; rebuild the manifest."
        elif row.get("ext") is not None and row["ext"].casefold() != ext:
            status = "needs-rendering"
            reason = "Manifest extension does not match the source path."
        elif ext == "eml":
            kind = "email"
            status, reason, derivatives, attachments = _eml_document(
                data, PurePosixPath(relative).name, bundle, mode=mode
            )
        else:
            try:
                kind, status, reason, derivatives = _render_payload(
                    data, ext, PurePosixPath(relative).name, bundle, mode=mode
                )
            except ReviewCopyError as exc:
                status = "needs-rendering"
                reason = str(exc)

        documents.append(
            {
                "attachments": attachments,
                "bytes": len(data),
                "derivatives": derivatives,
                "doc_id": row["id"],
                "kind": kind,
                "path": relative,
                "reason": reason,
                "source_sha256": source_digest,
                "status": status,
            }
        )

    documents.sort(key=lambda item: (item["doc_id"], item["path"]))
    body: dict[str, Any] = {
        "bundle_root": bundle_root,
        "documents": documents,
        "manifest_digest": canonical_digest(manifest),
        "schema_version": SCHEMA_VERSION,
        "status": (
            "ready"
            if all(document["status"] == "ready" for document in documents)
            else "needs-rendering"
        ),
    }
    sidecar = {**body, "digest": canonical_digest(body)}
    _write_json(sidecar_path, sidecar)
    validation = revalidate_review_copies(sidecar_path, manifest_path, source_root_path)
    return BuildResult(sidecar=sidecar, validation=validation)


def _exact_keys(
    value: Any,
    required: set[str],
    optional: set[str],
    where: str,
    errors: list[str],
) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{where} must be an object")
        return False
    keys = set(value)
    missing = sorted(required - keys)
    extra = sorted(keys - required - optional)
    if missing:
        errors.append(f"{where} lacks keys: {', '.join(missing)}")
    if extra:
        errors.append(f"{where} has unexpected keys: {', '.join(extra)}")
    return not missing and not extra


def _validate_derivative_shape(value: Any, where: str, errors: list[str]) -> bool:
    if not _exact_keys(
        value,
        {"bytes", "media_type", "path", "renderer", "role", "sha256"},
        {"page"},
        where,
        errors,
    ):
        return False
    okay = True
    if (
        not isinstance(value["bytes"], int)
        or isinstance(value["bytes"], bool)
        or value["bytes"] < 0
    ):
        errors.append(f"{where}.bytes is invalid")
        okay = False
    if not isinstance(value["media_type"], str) or not value["media_type"]:
        errors.append(f"{where}.media_type is invalid")
        okay = False
    try:
        _relative_parts(value["path"], f"{where}.path")
    except ReviewCopyError as exc:
        errors.append(str(exc))
        okay = False
    if not isinstance(value["role"], str) or not value["role"]:
        errors.append(f"{where}.role is invalid")
        okay = False
    if not isinstance(value["sha256"], str) or not SHA256_RE.fullmatch(value["sha256"]):
        errors.append(f"{where}.sha256 is invalid")
        okay = False
    elif isinstance(value["path"], str):
        digest = value["sha256"].removeprefix("sha256:")
        path = PurePosixPath(value["path"])
        if (
            len(path.parts) != 3
            or path.parts[0] != "objects"
            or path.parts[1] != digest[:2]
            or path.stem != digest
            or not re.fullmatch(r"[a-z0-9]{1,12}", path.suffix.lstrip("."))
        ):
            errors.append(f"{where}.path is not content-addressed by its sha256")
            okay = False
    if "page" in value and (
        not isinstance(value["page"], int)
        or isinstance(value["page"], bool)
        or value["page"] < 1
    ):
        errors.append(f"{where}.page is invalid")
        okay = False
    if not _exact_keys(
        value["renderer"], {"name", "version"}, set(), f"{where}.renderer", errors
    ):
        okay = False
    elif not all(
        isinstance(value["renderer"][key], str) and value["renderer"][key]
        for key in ("name", "version")
    ):
        errors.append(f"{where}.renderer values must be non-empty strings")
        okay = False
    return okay


def _validate_item_shape(
    value: Any, where: str, errors: list[str], *, attachment: bool
) -> bool:
    identity = {"attachment_id", "filename"} if attachment else {"doc_id", "path"}
    required = identity | {
        "bytes",
        "derivatives",
        "kind",
        "reason",
        "source_sha256",
        "status",
    }
    if not attachment:
        required.add("attachments")
    if not _exact_keys(value, required, set(), where, errors):
        return False
    okay = True
    id_field = "attachment_id" if attachment else "doc_id"
    id_pattern = SHA256_RE if attachment else DOC_ID_RE
    if not isinstance(value[id_field], str) or not id_pattern.fullmatch(
        value[id_field]
    ):
        errors.append(f"{where}.{id_field} is invalid")
        okay = False
    if attachment:
        if (
            not isinstance(value["filename"], str)
            or not value["filename"]
            or value["filename"] in {".", ".."}
            or "/" in value["filename"]
            or "\\" in value["filename"]
        ):
            errors.append(f"{where}.filename is invalid")
            okay = False
    else:
        try:
            _relative_parts(value["path"], f"{where}.path")
        except ReviewCopyError as exc:
            errors.append(str(exc))
            okay = False
    if (
        not isinstance(value["bytes"], int)
        or isinstance(value["bytes"], bool)
        or value["bytes"] < 0
    ):
        errors.append(f"{where}.bytes is invalid")
        okay = False
    if not isinstance(value["kind"], str) or not value["kind"]:
        errors.append(f"{where}.kind is invalid")
        okay = False
    if value["status"] not in {"ready", "needs-rendering"}:
        errors.append(f"{where}.status is invalid")
        okay = False
    if value["status"] == "ready" and value["reason"] is not None:
        errors.append(f"{where}.reason must be null when ready")
        okay = False
    if value["status"] == "needs-rendering" and (
        not isinstance(value["reason"], str) or not value["reason"]
    ):
        errors.append(f"{where}.reason must explain the rendering blocker")
        okay = False
    if not isinstance(value["source_sha256"], str) or not SHA256_RE.fullmatch(
        value["source_sha256"]
    ):
        errors.append(f"{where}.source_sha256 is invalid")
        okay = False
    elif attachment and value["attachment_id"] != value["source_sha256"]:
        errors.append(f"{where}.attachment_id must equal its full source hash")
        okay = False
    elif not attachment:
        expected_doc_id = "sha256:" + value["source_sha256"][7:19]
        if value["doc_id"] != expected_doc_id:
            errors.append(f"{where}.doc_id does not match its full source hash")
            okay = False
    if not isinstance(value["derivatives"], list):
        errors.append(f"{where}.derivatives must be an array")
        okay = False
    else:
        if value["status"] == "ready" and not value["derivatives"]:
            errors.append(f"{where} is ready but has no review derivative")
            okay = False
        seen_derivatives: set[tuple[str, str, int | None]] = set()
        pages_by_role: dict[str, list[int]] = {}
        for index, derivative in enumerate(value["derivatives"]):
            if not _validate_derivative_shape(
                derivative, f"{where}.derivatives[{index}]", errors
            ):
                okay = False
                continue
            identity = (
                derivative["path"],
                derivative["role"],
                derivative.get("page"),
            )
            if identity in seen_derivatives:
                errors.append(f"{where}.derivatives contains a duplicate receipt")
                okay = False
            seen_derivatives.add(identity)
            if "page" in derivative:
                pages_by_role.setdefault(derivative["role"], []).append(
                    derivative["page"]
                )
        for role, pages in pages_by_role.items():
            if pages != list(range(1, len(pages) + 1)):
                errors.append(f"{where} page order is not contiguous for role {role}")
                okay = False
    return okay


def _validate_sidecar_shape(sidecar: Any, errors: list[str]) -> bool:
    if not _exact_keys(
        sidecar,
        {
            "bundle_root",
            "digest",
            "documents",
            "manifest_digest",
            "schema_version",
            "status",
        },
        set(),
        "sidecar",
        errors,
    ):
        return False
    okay = True
    if sidecar["schema_version"] != SCHEMA_VERSION:
        errors.append("sidecar.schema_version is unsupported")
        okay = False
    if sidecar["status"] not in {"ready", "needs-rendering"}:
        errors.append("sidecar.status is invalid")
        okay = False
    for field in ("digest", "manifest_digest"):
        if not isinstance(sidecar[field], str) or not SHA256_RE.fullmatch(
            sidecar[field]
        ):
            errors.append(f"sidecar.{field} is invalid")
            okay = False
    try:
        _relative_parts(sidecar["bundle_root"], "sidecar.bundle_root")
    except ReviewCopyError as exc:
        errors.append(str(exc))
        okay = False
    if not isinstance(sidecar["documents"], list):
        errors.append("sidecar.documents must be an array")
        return False
    for index, document in enumerate(sidecar["documents"]):
        where = f"sidecar.documents[{index}]"
        if not _validate_item_shape(document, where, errors, attachment=False):
            okay = False
            continue
        if not isinstance(document.get("attachments"), list):
            errors.append(f"{where}.attachments must be an array")
            okay = False
            continue
        for attachment_index, attachment in enumerate(document["attachments"]):
            if not _validate_item_shape(
                attachment,
                f"{where}.attachments[{attachment_index}]",
                errors,
                attachment=True,
            ):
                okay = False
        if document.get("status") == "ready" and any(
            isinstance(attachment, dict) and attachment.get("status") != "ready"
            for attachment in document["attachments"]
        ):
            errors.append(f"{where} is ready while an attachment needs rendering")
            okay = False
    if isinstance(sidecar.get("documents"), list):
        order = [
            (document.get("doc_id", ""), document.get("path", ""))
            for document in sidecar["documents"]
            if isinstance(document, dict)
        ]
        if order != sorted(order):
            errors.append("sidecar.documents are not in canonical doc_id/path order")
            okay = False
    if isinstance(sidecar.get("documents"), list):
        computed_status = (
            "ready"
            if all(
                isinstance(document, dict) and document.get("status") == "ready"
                for document in sidecar["documents"]
            )
            else "needs-rendering"
        )
        if sidecar.get("status") != computed_status:
            errors.append("sidecar.status does not match document statuses")
            okay = False
    return okay


def _iter_derivatives(document: dict[str, Any]):
    yield from document["derivatives"]
    for attachment in document["attachments"]:
        yield from attachment["derivatives"]


def _bundle_files(bundle: Path, errors: list[str]) -> set[str]:
    files: set[str] = set()
    for directory, dirnames, filenames in os.walk(bundle, followlinks=False):
        directory_path = Path(directory)
        safe_dirs = []
        for dirname in sorted(dirnames):
            child = directory_path / dirname
            if child.is_symlink():
                relative = child.relative_to(bundle).as_posix()
                errors.append(f"bundle contains a symlinked directory: {relative}")
            else:
                safe_dirs.append(dirname)
        dirnames[:] = safe_dirs
        for filename in sorted(filenames):
            child = directory_path / filename
            relative = child.relative_to(bundle).as_posix()
            if child.is_symlink():
                errors.append(f"bundle contains a symlinked file: {relative}")
            elif child.is_file():
                files.add(relative)
            else:
                errors.append(f"bundle contains a non-regular entry: {relative}")
    return files


def revalidate_review_copies(
    sidecar_path: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str],
    source_root: str | os.PathLike[str],
) -> ValidationResult:
    """Revalidate schema, exact coverage, sources, derivatives, and bundle set."""

    sidecar_path = Path(sidecar_path).absolute()
    errors: list[str] = []
    try:
        sidecar = _load_json(sidecar_path)
        manifest = _load_json(Path(manifest_path).resolve(strict=True))
        rows = _manifest_documents(manifest)
        source_root_path = Path(source_root).resolve(strict=True)
    except (OSError, ReviewCopyError) as exc:
        return ValidationResult(False, False, (str(exc),), None, sidecar_path)

    if not _validate_sidecar_shape(sidecar, errors):
        return ValidationResult(
            False, False, tuple(sorted(set(errors))), sidecar, sidecar_path
        )

    body = {key: value for key, value in sidecar.items() if key != "digest"}
    if sidecar["digest"] != canonical_digest(body):
        errors.append("sidecar self-digest mismatch")
    if sidecar["manifest_digest"] != canonical_digest(manifest):
        errors.append("manifest canonical digest mismatch")

    expected_coverage = sorted((row["id"], row["path"], row["bytes"]) for row in rows)
    actual_coverage = sorted(
        (document["doc_id"], document["path"], document["bytes"])
        for document in sidecar["documents"]
    )
    if actual_coverage != expected_coverage:
        errors.append("sidecar does not exactly cover the manifest rows")

    try:
        bundle = _bundle_directory(sidecar_path, sidecar["bundle_root"], create=False)
    except ReviewCopyError as exc:
        errors.append(str(exc))
        return ValidationResult(
            False, False, tuple(sorted(set(errors))), sidecar, sidecar_path
        )

    expected_files: set[str] = set()
    for document in sidecar["documents"]:
        try:
            source = _contained_source(source_root_path, document["path"])
        except ReviewCopyError as exc:
            errors.append(str(exc))
            continue
        actual_size = source.stat().st_size
        actual_digest = _file_digest(source)
        if actual_size != document["bytes"]:
            errors.append(f"source byte count drift: {document['path']}")
        if actual_digest != document["source_sha256"]:
            errors.append(f"source hash drift: {document['path']}")
        expected_id = "sha256:" + actual_digest.removeprefix("sha256:")[:12]
        if document["doc_id"] != expected_id:
            errors.append(f"source doc_id drift: {document['path']}")

        for derivative in _iter_derivatives(document):
            relative = derivative["path"]
            expected_files.add(relative)
            try:
                parts = _relative_parts(relative, "derivative path")
                _assert_no_output_symlink(bundle, parts)
            except ReviewCopyError as exc:
                errors.append(str(exc))
                continue
            target = bundle.joinpath(*parts)
            if not target.exists():
                errors.append(f"derivative is missing: {relative}")
                continue
            if target.is_symlink() or not target.is_file():
                errors.append(f"derivative is not a regular file: {relative}")
                continue
            if target.stat().st_size != derivative["bytes"]:
                errors.append(f"derivative byte count mismatch: {relative}")
            if _file_digest(target) != derivative["sha256"]:
                errors.append(f"derivative hash mismatch: {relative}")

    actual_files = _bundle_files(bundle, errors)
    for missing in sorted(expected_files - actual_files):
        message = f"derivative is missing: {missing}"
        if message not in errors:
            errors.append(message)
    for extra in sorted(actual_files - expected_files):
        errors.append(f"extra file in review-copy bundle: {extra}")

    integrity_ok = not errors
    ready = integrity_ok and sidecar["status"] == "ready"
    return ValidationResult(
        integrity_ok,
        ready,
        tuple(sorted(set(errors))),
        sidecar,
        sidecar_path,
    )


def _component_alert(message: str) -> str:
    return (
        '<div class="lq-review-copy lq-needs-rendering" role="alert">'
        "<strong>Needs rendering</strong> " + html.escape(message) + "</div>"
    )


def _derivative_html(derivative: dict[str, Any], bundle_root: str, title: str) -> str:
    relative = f"{bundle_root}/{derivative['path']}"
    href = html.escape(urllib.parse.quote(relative, safe="/"), quote=True)
    title_attr = html.escape(title, quote=True)
    media_type = derivative["media_type"]
    if media_type == "text/html":
        return (
            f'<iframe class="lq-review-copy-frame" src="{href}" title="{title_attr}" '
            'sandbox="" loading="lazy" referrerpolicy="no-referrer"></iframe>'
        )
    if media_type.startswith("image/"):
        return (
            f'<img class="lq-review-copy-image" src="{href}" alt="{title_attr}" '
            'loading="lazy" referrerpolicy="no-referrer">'
        )
    if media_type == "application/pdf":
        return (
            f'<object class="lq-review-copy-pdf" data="{href}" '
            f'type="application/pdf" aria-label="{title_attr}">'
            f'<a href="{href}">Open verified PDF review copy</a></object>'
        )
    return f'<a href="{href}">Open verified review copy</a>'


def render_review_copy_component(
    validation: ValidationResult,
    doc_id: str,
    *,
    path: str | None = None,
    title: str | None = None,
) -> str:
    """Render a safe component only after full bundle revalidation.

    A path is required when duplicate manifest rows share a content-derived
    doc_id.  References are relative to the sidecar directory and point only
    to bytes included in the successful validation.
    """

    if not validation.integrity_ok or validation.sidecar is None:
        detail = "; ".join(validation.errors[:3]) or "Review-copy receipt is invalid."
        return _component_alert(detail)
    matches = [
        document
        for document in validation.sidecar["documents"]
        if document["doc_id"] == doc_id and (path is None or document["path"] == path)
    ]
    if len(matches) != 1:
        return _component_alert(
            "The document is absent from the verified receipt or its duplicate "
            "path is ambiguous."
        )
    document = matches[0]
    if document["status"] != "ready":
        return _component_alert(document["reason"])
    heading = title or PurePosixPath(document["path"]).name
    safe_heading = html.escape(heading)
    safe_hash = html.escape(document["source_sha256"])
    content = [
        '<section class="lq-review-copy" data-review-copy-status="verified">',
        f"<h3>{safe_heading}</h3>",
        '<p class="lq-review-copy-receipt">Verified source '
        f"<code>{safe_hash}</code></p>",
    ]
    for derivative in document["derivatives"]:
        content.append(
            _derivative_html(derivative, validation.sidecar["bundle_root"], heading)
        )
    for attachment in document["attachments"]:
        attachment_name = html.escape(attachment["filename"])
        content.append(f"<details><summary>Attachment: {attachment_name}</summary>")
        if attachment["status"] != "ready":
            content.append(_component_alert(attachment["reason"]))
        else:
            for derivative in attachment["derivatives"]:
                content.append(
                    _derivative_html(
                        derivative,
                        validation.sidecar["bundle_root"],
                        f"Attachment {attachment['filename']}",
                    )
                )
        content.append("</details>")
    content.append("</section>")
    return "".join(content)


def _build_command(args: argparse.Namespace) -> int:
    try:
        result = build_review_copies(
            args.manifest,
            args.source_root,
            args.sidecar,
            bundle_root=args.bundle_root,
            mode=args.mode,
        )
    except (OSError, ReviewCopyError) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2
    ready = sum(
        document["status"] == "ready" for document in result.sidecar["documents"]
    )
    total = len(result.sidecar["documents"])
    print(f"Wrote {args.sidecar}: {ready}/{total} documents review-ready")
    if not result.validation.integrity_ok:
        for error in result.validation.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0 if result.validation.ready else 1


def _verify_command(args: argparse.Namespace) -> int:
    result = revalidate_review_copies(args.sidecar, args.manifest, args.source_root)
    if result.integrity_ok:
        print("Review-copy sidecar and bundle integrity verified.")
        return 0 if result.ready else 1
    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify deterministic, hash-bound review copies."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    verify = subparsers.add_parser("verify")
    for command in (build, verify):
        command.add_argument("--manifest", required=True)
        command.add_argument("--source-root", required=True)
        command.add_argument("--sidecar", required=True)
    build.add_argument("--bundle-root", default="review-copies")
    build.add_argument("--mode", choices=["auto", "text"], default="auto")
    build.set_defaults(function=_build_command)
    verify.set_defaults(function=_verify_command)
    args = parser.parse_args()
    return args.function(args)


if __name__ == "__main__":
    raise SystemExit(main())
