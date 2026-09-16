"""Safe, dependency-free intake for the readable portions of DOCX files."""

from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile, is_zipfile

from .models import Block, SourceDocument, stable_id


class IntakeError(ValueError):
    """Raised when a DOCX cannot be safely read as OOXML."""

    run_status = "not_run_unsupported_input"


class InputAccessError(IntakeError):
    """Raised when the requested source cannot be accessed."""

    def __init__(self, message: str, *, policy_restricted: bool = False) -> None:
        super().__init__(message)
        self.run_status = "not_run_policy_restricted" if policy_restricted else "failed"


_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _TAG(name: str) -> str:
    return f"{{{_WORD_NS}}}{name}"


_MAX_MEMBERS = 10_000
_MAX_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_BYTES = 256 * 1024 * 1024
_MAX_INPUT_BYTES = 300 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 1_000
_HASH_CHUNK_BYTES = 1024 * 1024


def _input_access_error(path: Path, exc: OSError) -> InputAccessError:
    return InputAccessError(
        f"unable to access DOCX file {path!s}",
        policy_restricted=isinstance(exc, PermissionError),
    )


def _hash_file(path: Path) -> str:
    digest = sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(_HASH_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError as exc:
        raise _input_access_error(path, exc) from exc
    return digest.hexdigest()


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _safe_members(archive: ZipFile) -> dict[str, object]:
    infos = archive.infolist()
    if len(infos) > _MAX_MEMBERS:
        raise IntakeError("DOCX archive has too many members")
    total = 0
    for info in infos:
        if info.flag_bits & 0x1:
            raise IntakeError("encrypted DOCX archives are not supported")
        if info.file_size > _MAX_MEMBER_BYTES:
            raise IntakeError("DOCX archive member is too large")
        total += info.file_size
        if total > _MAX_TOTAL_BYTES:
            raise IntakeError("DOCX archive is too large")
        if info.file_size and not info.compress_size:
            raise IntakeError("DOCX archive has an invalid compressed member")
        if (
            info.compress_size
            and info.file_size / info.compress_size > _MAX_COMPRESSION_RATIO
        ):
            raise IntakeError("DOCX archive compression ratio is unsafe")
    return {info.filename: info for info in infos}


def _read_xml(archive: ZipFile, name: str) -> ET.Element:
    try:
        raw = archive.read(name)
    except (BadZipFile, KeyError, OSError, RuntimeError) as exc:
        raise IntakeError(f"unable to read OOXML part {name!r}") from exc
    # ElementTree does not fetch external entities, and this check makes the
    # parser's no-DTD boundary explicit before handing it XML bytes.
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise IntakeError(f"OOXML part {name!r} contains a prohibited DTD/entity")
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise IntakeError(f"OOXML part {name!r} is malformed") from exc


def _paragraph_text(paragraph: ET.Element) -> str:
    pieces: list[str] = []
    for element in paragraph.iter():
        name = _local_name(element)
        if name == "t":
            pieces.append(element.text or "")
        elif name == "tab":
            pieces.append("\t")
        elif name in {"br", "cr"}:
            pieces.append("\n")
    return "".join(pieces)


def _content_children(
    container: ET.Element, tags: set[str], omitted: set[str]
) -> Iterable[ET.Element]:
    """Unwrap content controls, without treating other wrappers as clean text."""
    for child in container:
        if child.tag in tags:
            yield child
        elif child.tag == _TAG("sdt"):
            content = child.find(_TAG("sdtContent"))
            if content is None:
                omitted.add("content controls without sdtContent")
            else:
                yield from _content_children(content, tags, omitted)
        elif child.tag in {_TAG("ins"), _TAG("del"), _TAG("moveFrom"), _TAG("moveTo")}:
            # Coverage already records these revisions as excluded. Do not
            # accidentally accept them while walking a content control.
            continue
        elif any(
            element.tag
            in {
                _TAG("p"),
                _TAG("tbl"),
                _TAG("t"),
                _TAG("delText"),
                _TAG("altChunk"),
            }
            for element in child.iter()
        ):
            omitted.add(_local_name(child))


def _table_paragraphs(
    table: ET.Element, omitted: set[str]
) -> Iterable[tuple[int, int, ET.Element]]:
    for row_index, row in enumerate(_content_children(table, {_TAG("tr")}, omitted)):
        for cell_index, cell in enumerate(
            _content_children(row, {_TAG("tc")}, omitted)
        ):
            for child in _content_children(cell, {_TAG("p"), _TAG("tbl")}, omitted):
                if child.tag == _TAG("p"):
                    yield row_index, cell_index, child
                elif child.tag == _TAG("tbl"):
                    yield from _table_paragraphs(child, omitted)


def _coverage(
    members: dict[str, object], document: ET.Element
) -> tuple[dict[str, dict[str, bool]], list[str]]:
    names = set(members)
    structures = {
        "document_body": ("word/document.xml" in names, True),
        "tables": (bool(document.findall(f".//{_TAG('tbl')}")), True),
        "headers": (
            any(
                name.startswith("word/header") and name.endswith(".xml")
                for name in names
            ),
            False,
        ),
        "footers": (
            any(
                name.startswith("word/footer") and name.endswith(".xml")
                for name in names
            ),
            False,
        ),
        "footnotes": ("word/footnotes.xml" in names, False),
        "endnotes": ("word/endnotes.xml" in names, False),
        "comments": ("word/comments.xml" in names, False),
        "tracked_changes": (
            any(
                _local_name(item) in {"ins", "del", "moveFrom", "moveTo"}
                for item in document.iter()
            ),
            False,
        ),
        "macros": ("word/vbaProject.bin" in names, False),
        "embedded_objects": (
            any(
                name.startswith("word/embeddings/") or name.startswith("word/activeX/")
                for name in names
            ),
            False,
        ),
    }
    coverage = {
        key: {"present": present, "parsed": parsed and present}
        for key, (present, parsed) in structures.items()
    }
    warnings = [
        f"{key.replace('_', ' ')} are present but not parsed"
        for key, value in coverage.items()
        if value["present"] and not value["parsed"]
    ]
    return coverage, warnings


def extract_docx(path: str | Path) -> SourceDocument:
    """Extract body and table-cell paragraphs without executing archive content."""
    source_path = Path(path)
    try:
        input_size = source_path.stat().st_size
    except OSError as exc:
        raise _input_access_error(source_path, exc) from exc
    if input_size > _MAX_INPUT_BYTES:
        raise IntakeError("DOCX input file is too large")
    if not is_zipfile(source_path):
        raise IntakeError("input is not a ZIP-based DOCX file")

    digest = _hash_file(source_path)
    document_id = stable_id("src", digest)
    try:
        with ZipFile(source_path) as archive:
            members = _safe_members(archive)
            if "word/document.xml" not in members:
                raise IntakeError("DOCX archive is missing word/document.xml")
            document = _read_xml(archive, "word/document.xml")
    except PermissionError as exc:
        raise _input_access_error(source_path, exc) from exc
    except (BadZipFile, OSError, RuntimeError) as exc:
        raise IntakeError("DOCX archive is corrupt or unreadable") from exc

    body = document.find(_TAG("body"))
    if body is None:
        raise IntakeError("word/document.xml is missing w:body")
    coverage, warnings = _coverage(members, document)
    blocks: list[Block] = []
    paragraph_index = 0

    def add(
        paragraph: ET.Element,
        table_index: int | None = None,
        row_index: int | None = None,
        cell_index: int | None = None,
    ) -> None:
        nonlocal paragraph_index
        order = len(blocks)
        blocks.append(
            Block(
                id=stable_id("blk", document_id, "document", order, paragraph_index),
                part="document",
                kind="paragraph",
                order=order,
                text=_paragraph_text(paragraph),
                paragraph_index=paragraph_index,
                table_index=table_index,
                row_index=row_index,
                cell_index=cell_index,
            )
        )
        paragraph_index += 1

    table_index = 0
    omitted: set[str] = set()
    for child in _content_children(body, {_TAG("p"), _TAG("tbl")}, omitted):
        if child.tag == _TAG("p"):
            add(child)
        elif child.tag == _TAG("tbl"):
            for row_index, cell_index, paragraph in _table_paragraphs(child, omitted):
                add(paragraph, table_index, row_index, cell_index)
            table_index += 1
    if omitted:
        coverage["unsupported_body_content"] = {"present": True, "parsed": False}
        warnings.append(
            "document body content in unsupported structures is present but not parsed: "
            + ", ".join(sorted(omitted))
        )
    return SourceDocument(
        document_id=document_id,
        name=source_path.name,
        sha256=digest,
        blocks=blocks,
        coverage=coverage,
        warnings=warnings,
    )
