# ruff: noqa: E501 - synthetic OOXML is intentionally literal and inspectable
"""Semantic-unit contract for safe DOCX extraction."""

from __future__ import annotations

import importlib
import sys
import zipfile
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills/core/timenarratives/scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "packages/skill-tests/tests"))
docx_units = importlib.import_module("docx_units")
validate_packet_semantic_boundary = importlib.import_module(
    "structural_contracts"
).validate_packet_semantic_boundary

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_R = "http://schemas.openxmlformats.org/package/2006/relationships"
CORE = """<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dcterms="http://purl.org/dc/terms/"><dcterms:modified>2026-08-21T09:10:11Z</dcterms:modified></cp:coreProperties>"""


def _docx(
    document: str,
    *,
    parts: dict[str, str | bytes] | None = None,
    relationships: str = "",
    content_types: dict[str, str] | None = None,
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    overrides = {
        "word/document.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        "docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
        **(content_types or {}),
    }
    types = "".join(
        f'<Override PartName="/{name}" ContentType="{media}"/>'
        for name, media in overrides.items()
    )
    content = f"""<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="bin" ContentType="application/octet-stream"/><Default Extension="png" ContentType="image/png"/>{types}</Types>"""
    root_rels = f"""<Relationships xmlns="{PACKAGE_R}"><Relationship Id="rId1" Type="{R}/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="{PACKAGE_R}/metadata/core-properties" Target="docProps/core.xml"/></Relationships>"""
    doc_rels = f'<Relationships xmlns="{PACKAGE_R}">{relationships}</Relationships>'
    members: dict[str, str | bytes] = {
        "[Content_Types].xml": content,
        "_rels/.rels": root_rels,
        "docProps/core.xml": CORE,
        "word/document.xml": document,
    }
    if relationships:
        members["word/_rels/document.xml.rels"] = doc_rels
    members.update(parts or {})
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return output.getvalue()


def _document(body: str, prefix: str = "odd") -> str:
    return f'<{prefix}:document xmlns:{prefix}="{W}" xmlns:r="{R}"><{prefix}:body>{body}</{prefix}:body></{prefix}:document>'


def _relation(identifier: str, kind: str, target: str) -> str:
    return f'<Relationship Id="{identifier}" Type="{R}/{kind}" Target="{target}"/>'


def test_docx_unit_reader_is_available() -> None:
    assert (SCRIPTS / "docx_units.py").is_file()


def test_docx_unit_reader_exposes_public_parser() -> None:
    assert callable(getattr(docx_units, "parse_docx", None))


def test_parser_rejects_an_unsafe_container_identifier() -> None:
    with pytest.raises(ValueError, match="container_id"):
        docx_units.parse_docx(b"PK\x03\x04", "unsafe/id")


def test_extracts_arbitrary_prefix_tables_controls_fields_and_revisions() -> None:
    body = """
    <q:p><q:r><q:t>Alpha</q:t><q:tab/><q:t>Beta</q:t><q:br/><q:t>Gamma</q:t></q:r></q:p>
    <q:tbl><q:tr><q:tc><q:p><q:r><q:t>Cell</q:t></q:r></q:p></q:tc></q:tr></q:tbl>
    <q:p><q:pPr><q:pPrChange q:id="8" q:author="Prop"/></q:pPr>
      <q:ins q:id="1" q:author="Alice" q:date="2026-08-20T10:00:00Z"><q:r><q:t>Inserted</q:t></q:r></q:ins>
      <q:del q:id="2" q:author="Bob"><q:r><q:delText>Deleted</q:delText></q:r></q:del>
      <q:moveFrom q:id="3" q:author="Carol" q:date="2026-08-20T11:00:00Z"><q:r><q:t>From</q:t></q:r></q:moveFrom>
      <q:moveTo q:id="3" q:author="Carol" q:date="2026-08-20T11:00:00Z"><q:r><q:t>To</q:t></q:r></q:moveTo>
      <q:ins q:id="7" xmlns:e="urn:evil" e:author="Mallory"><q:r><q:t>No author</q:t></q:r></q:ins>
      <q:del q:id="7" q:author="Dave"><q:r><q:delText>Duplicate id</q:delText></q:r></q:del>
      <q:moveTo q:id="99"><q:r><q:t>Unpaired</q:t></q:r></q:moveTo>
    </q:p>
    <q:p><q:fldSimple q:instr=" DATE "><q:r><q:t>21 August</q:t></q:r></q:fldSimple></q:p>
    <q:p><q:r><q:fldChar q:fldCharType="begin"/><q:instrText> AUTHOR </q:instrText><q:fldChar q:fldCharType="separate"/><q:t>James</q:t><q:fldChar q:fldCharType="end"/></q:r></q:p>
    """
    result = docx_units.parse_docx(_docx(_document(body, "q")), "CASE")

    assert result["disposition"] == "ready"
    assert result["reason"] is None
    assert result["filterTimestamp"] == "2026-08-21T09:10:11Z"
    body_text = [
        unit["canonicalText"]
        for unit in result["units"]
        if unit["kind"] == "docx_accepted"
    ]
    assert body_text == [
        "Alpha\tBeta\nGamma",
        "Cell",
        "InsertedToNo authorUnpaired",
        "21 August",
        "James",
    ]
    revisions = [
        unit
        for unit in result["units"]
        if unit["metadata"].get("revisionKind") in {"ins", "del", "moveFrom", "moveTo"}
    ]
    assert [unit["canonicalText"] for unit in revisions] == [
        "Inserted",
        "Deleted",
        "From",
        "To",
        "No author",
        "Duplicate id",
        "Unpaired",
    ]
    duplicate_ids = [
        unit for unit in revisions if unit["metadata"]["revisionId"] == "7"
    ]
    assert len(duplicate_ids) == 2
    assert all(
        "actor_unestablished" in unit["metadata"]["attributionState"]
        for unit in revisions
    )
    missing = next(unit for unit in revisions if unit["canonicalText"] == "No author")
    assert missing["metadata"]["author"] is None
    assert missing["metadata"]["date"] is None
    assert (
        missing["metadata"]["attributionState"] == "author_missing_actor_unestablished"
    )
    malformed = next(unit for unit in revisions if unit["canonicalText"] == "Unpaired")
    assert malformed["metadata"]["attributionState"].endswith("_move_pair_malformed")
    assert any(
        unit["metadata"].get("revisionKind") == "pPrChange" for unit in result["units"]
    )
    field = next(
        unit
        for unit in result["units"]
        if unit["metadata"].get("fieldInstructions") == "DATE"
    )
    assert field["kind"] == "docx_annotation"
    assert field["eligibility"] == "ineligible"


def test_emits_container_scoped_hashed_located_units_and_reconciles_story_parts() -> (
    None
):
    main = _document(
        """<odd:p><odd:r><odd:t>Main</odd:t><odd:footnoteReference odd:id="1"/><odd:endnoteReference odd:id="2"/><odd:commentReference odd:id="5"/></odd:r></odd:p>
        <odd:sectPr><odd:headerReference odd:type="default" r:id="r1"/><odd:footerReference odd:type="default" r:id="r2"/></odd:sectPr>"""
    )
    story: dict[str, str | bytes] = {
        "word/header1.xml": f'<h:hdr xmlns:h="{W}"><h:p><h:r><h:t>Header</h:t></h:r></h:p></h:hdr>',
        "word/footer1.xml": f'<f:ftr xmlns:f="{W}"><f:p><f:r><f:t>Footer</f:t></f:r></f:p></f:ftr>',
        "word/footnotes.xml": f'<n:footnotes xmlns:n="{W}"><n:footnote n:id="-1" n:type="separator"><n:p><n:r><n:t>Separator must not evidence</n:t></n:r></n:p></n:footnote><n:footnote n:id="1"><n:p><n:r><n:t>Footnote</n:t></n:r></n:p></n:footnote></n:footnotes>',
        "word/endnotes.xml": f'<n:endnotes xmlns:n="{W}"><n:endnote n:id="2"><n:p><n:r><n:t>Endnote</n:t></n:r></n:p></n:endnote></n:endnotes>',
        "word/comments.xml": f'<c:comments xmlns:c="{W}"><c:comment c:id="5" c:author="Reviewer"><c:p><c:r><c:t>Comment</c:t></c:r></c:p></c:comment></c:comments>',
    }
    kinds = {
        "header1.xml": "header",
        "footer1.xml": "footer",
        "footnotes.xml": "footnotes",
        "endnotes.xml": "endnotes",
        "comments.xml": "comments",
    }
    rels = "".join(
        _relation(f"r{i}", kind, name)
        for i, (name, kind) in enumerate(kinds.items(), 1)
    )
    rels += _relation("r99", "header", "header1.xml")
    media = {
        f"word/{name}": f"application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml"
        for name, kind in kinds.items()
    }
    result = docx_units.parse_docx(
        _docx(main, parts=story, relationships=rels, content_types=media), "MATTER"
    )

    expected = {
        "word/document.xml": "Main",
        "word/header1.xml": "Header",
        "word/footer1.xml": "Footer",
        "word/footnotes.xml": "Footnote",
        "word/endnotes.xml": "Endnote",
    }
    accepted = {
        unit["metadata"]["partName"]: unit["canonicalText"]
        for unit in result["units"]
        if unit["kind"] == "docx_accepted"
    }
    assert accepted == expected
    comment = next(
        unit for unit in result["units"] if unit["kind"] == "docx_annotation"
    )
    assert comment["canonicalText"] == "Comment"
    assert [unit["unitId"] for unit in result["units"]] == [
        f"MATTER-U{i:04d}" for i in range(1, 7)
    ]
    for unit in result["units"]:
        assert (
            unit["canonicalUtf8Sha256"]
            == sha256(unit["canonicalText"].encode()).hexdigest()
        )
        assert unit["sourceClass"] == "documentary_supported"
        assert unit["locator"].startswith("docx:")
        assert unit["utf8End"] == len(unit["canonicalText"].encode())
        assert unit["containerId"] == "MATTER"
    parts = {part["locator"].removeprefix("docx:"): part for part in result["parts"]}
    with zipfile.ZipFile(
        BytesIO(_docx(main, parts=story, relationships=rels, content_types=media))
    ) as archive:
        assert set(parts) == set(archive.namelist())
    for name, part in parts.items():
        expected_ids = [
            unit["unitId"]
            for unit in result["units"]
            if unit["metadata"]["partName"] == name
        ]
        assert part["unitIds"] == expected_ids


def test_altchunk_ole_and_unknown_text_part_force_partial_read() -> None:
    body = '<odd:p><odd:r><odd:t>Safe text</odd:t></odd:r></odd:p><odd:altChunk r:id="a1"/><odd:p><odd:r><odd:object><odd:OLEObject r:id="o1"/></odd:object></odd:r></odd:p>'
    rels = _relation("a1", "aFChunk", "chunk.html") + _relation(
        "o1", "oleObject", "embeddings/object1.bin"
    )
    parts = {
        "word/chunk.html": "<p>Hidden imported text</p>",
        "word/embeddings/object1.bin": b"OLE",
        "word/unknownStory.xml": _document(
            "<odd:p><odd:r><odd:t>Unknown story</odd:t></odd:r></odd:p>"
        ),
    }
    media = {
        "word/chunk.html": "text/html",
        "word/unknownStory.xml": "application/vnd.example.story+xml",
    }
    result = docx_units.parse_docx(
        _docx(_document(body), parts=parts, relationships=rels, content_types=media),
        "C",
    )
    assert result["disposition"] == "partial"
    assert result["reason"] == "unparsed_text_bearing_content"
    assert set(result["limitations"]) >= {
        "alt_chunk",
        "embedded_ole",
        "unparsed_text_part",
    }
    assert [
        unit["canonicalText"]
        for unit in result["units"]
        if unit["kind"] == "docx_accepted"
    ] == ["Safe text"]


def test_whole_paragraph_delete_and_move_from_are_not_accepted_text() -> None:
    body = """<odd:p><odd:r><odd:t>Visible</odd:t></odd:r></odd:p>
    <odd:del odd:id="1" odd:author="A"><odd:p><odd:r><odd:delText>Deleted paragraph</odd:delText></odd:r></odd:p></odd:del>
    <odd:moveFrom odd:id="2"><odd:p><odd:r><odd:t>Moved-away paragraph</odd:t></odd:r></odd:p></odd:moveFrom>
    <odd:moveTo odd:id="2"><odd:p><odd:r><odd:t>Moved-here paragraph</odd:t></odd:r></odd:p></odd:moveTo>"""
    result = docx_units.parse_docx(_docx(_document(body)), "WHOLE")
    accepted = [
        unit["canonicalText"]
        for unit in result["units"]
        if unit["kind"] == "docx_accepted"
    ]
    assert accepted == ["Visible", "Moved-here paragraph"]


def test_image_only_and_invalid_packages_never_claim_a_full_read() -> None:
    image = _docx(
        _document("<odd:p><odd:r><odd:drawing/></odd:r></odd:p>"),
        parts={"word/media/image1.png": b"PNG"},
    )
    result = docx_units.parse_docx(image, "IMG")
    assert result["disposition"] == "unreadable"
    assert result["reason"] == "no_extractable_text"
    assert result["units"] == []
    assert result["limitations"] == []
    assert result["notes"] == ["image_not_ocr"]
    assert result["affectedParts"] == []
    assert all(
        part["disposition"] != "ready" or part["unitIds"] for part in result["parts"]
    )
    unsafe = _docx(
        _document("<odd:p><odd:r><odd:t>X</odd:t></odd:r></odd:p>"),
        parts={"../escape.bin": b"x"},
    )
    rejected = docx_units.parse_docx(unsafe, "BAD")
    assert rejected["disposition"] == "unreadable"
    assert rejected["reason"] == "unsafe_member_path"
    assert rejected["units"] == []
    assert all(part["disposition"] == "unreadable" for part in rejected["parts"])


def test_docx_units_survive_packet_compilation_and_strict_schema(
    tmp_path: Path,
) -> None:
    packet = importlib.import_module("build_packet")
    packet_tests = importlib.import_module("test_timenarratives_packet")
    (tmp_path / "work.docx").write_bytes(
        _docx(_document("<odd:p><odd:r><odd:t>Drafted advice</odd:t></odd:r></odd:p>"))
    )
    request = packet_tests.request([{"kind": "file", "path": "work.docx"}])

    result = packet.compile_packet(request, tmp_path)

    unit = result["units"][0]
    part = next(row for row in result["parts"] if row["unitIds"] == [unit["unitId"]])
    assert unit["kind"] == "docx_accepted"
    assert unit["originId"] == part["partId"]
    assert validate_packet_semantic_boundary(result) == []
    packet_tests._assert_schema_valid(
        tmp_path, "timenarratives-packet.schema.json", result
    )
