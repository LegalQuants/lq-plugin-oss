# ruff: noqa: E501 - synthetic OOXML is intentionally literal and inspectable
"""Degrading versus informational DOCX limitations, and story-scoped downgrades."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills/core/timenarratives/scripts"
sys.path[:0] = [str(SCRIPTS), str(ROOT / "packages/skill-tests/tests")]

docx_units = importlib.import_module("docx_units")
fixtures = importlib.import_module("test_timenarratives_docx_units")

W = fixtures.W
_docx = fixtures._docx
_document = fixtures._document
_relation = fixtures._relation


def test_custom_xml_effects_styles_and_people_parts_are_not_evidence() -> None:
    body = "<odd:p><odd:r><odd:t>Body text</odd:t></odd:r></odd:p>"
    parts: dict[str, str | bytes] = {
        "customXml/item1.xml": "<props><Order>1</Order></props>",
        "customXml/itemProps1.xml": "<ds:datastoreItem xmlns:ds='urn:x'/>",
        "word/stylesWithEffects.xml": "<styles/>",
        "word/people.xml": "<people/>",
        "word/commentsExtended.xml": "<commentsEx/>",
        "word/glossary/document.xml": _document(
            "<odd:p><odd:r><odd:t>Building block</odd:t></odd:r></odd:p>"
        ),
    }
    media = {
        "customXml/item1.xml": "application/xml",
        "customXml/itemProps1.xml": "application/vnd.openxmlformats-officedocument.customXmlProperties+xml",
        "word/stylesWithEffects.xml": "application/vnd.ms-word.stylesWithEffects+xml",
        "word/people.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.people+xml",
        "word/commentsExtended.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml",
        "word/glossary/document.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.glossary+xml",
    }
    result = docx_units.parse_docx(
        _docx(_document(body), parts=parts, content_types=media), "CTRL"
    )
    assert result["disposition"] == "ready"
    assert result["limitations"] == []
    assert result["notes"] == []
    assert result["affectedParts"] == []
    by_name = {part["locator"]: part for part in result["parts"]}
    for name in parts:
        assert by_name[f"docx:{name}"]["disposition"] == "excluded"
        assert by_name[f"docx:{name}"]["reason"] == "package_control_or_non_text"
    assert [u["canonicalText"] for u in result["units"]] == ["Body text"]


def test_embedded_image_is_a_note_not_a_downgrade() -> None:
    body = (
        "<odd:p><odd:r><odd:t>Reviewed the draft</odd:t></odd:r></odd:p>"
        '<odd:p><odd:r><odd:drawing><a:blip xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'r:embed="img1"/></odd:drawing></odd:r></odd:p>'
    )
    rels = _relation("img1", "image", "media/logo.png")
    result = docx_units.parse_docx(
        _docx(
            _document(body),
            parts={"word/media/logo.png": b"PNG"},
            relationships=rels,
        ),
        "IMG",
    )
    assert result["disposition"] == "ready"
    assert result["limitations"] == []
    assert result["notes"] == ["image_not_ocr"]
    assert result["affectedParts"] == []
    assert [u["eligibility"] for u in result["units"]] == ["eligible"]


def test_degrading_limitation_names_only_the_affected_story_part() -> None:
    body = (
        '<odd:p><odd:r><odd:t>Body text</odd:t><odd:footnoteReference odd:id="1"/></odd:r></odd:p>'
        '<odd:altChunk r:id="a1"/>'
    )
    footnotes = f'<n:footnotes xmlns:n="{W}"><n:footnote n:id="1"><n:p><n:r><n:t>Footnote text</n:t></n:r></n:p></n:footnote></n:footnotes>'
    rels = _relation("a1", "aFChunk", "chunk.html") + _relation(
        "fn", "footnotes", "footnotes.xml"
    )
    parts: dict[str, str | bytes] = {
        "word/chunk.html": "<p>hidden</p>",
        "word/footnotes.xml": footnotes,
    }
    media = {
        "word/chunk.html": "text/html",
        "word/footnotes.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
    }
    result = docx_units.parse_docx(
        _docx(_document(body), parts=parts, relationships=rels, content_types=media),
        "SCOPE",
    )
    assert result["disposition"] == "partial"
    assert result["affectedParts"] == ["word/document.xml"]
    assert "alt_chunk" in result["limitations"]
    by_part = {u["metadata"]["partName"]: u["canonicalText"] for u in result["units"]}
    assert by_part["word/footnotes.xml"] == "Footnote text"


def test_unknown_text_part_affects_every_story_part() -> None:
    body = '<odd:p><odd:r><odd:t>Body text</odd:t><odd:footnoteReference odd:id="1"/></odd:r></odd:p>'
    footnotes = f'<n:footnotes xmlns:n="{W}"><n:footnote n:id="1"><n:p><n:r><n:t>Footnote text</n:t></n:r></n:p></n:footnote></n:footnotes>'
    parts: dict[str, str | bytes] = {
        "word/footnotes.xml": footnotes,
        "word/unknownStory.xml": _document(
            "<odd:p><odd:r><odd:t>Hidden text</odd:t></odd:r></odd:p>"
        ),
    }
    media = {
        "word/footnotes.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
        "word/unknownStory.xml": "application/vnd.example.story+xml",
    }
    result = docx_units.parse_docx(
        _docx(
            _document(body),
            parts=parts,
            relationships=_relation("fn", "footnotes", "footnotes.xml"),
            content_types=media,
        ),
        "UNKNOWN",
    )
    assert result["disposition"] == "partial"
    assert result["limitations"] == ["unparsed_text_part"]
    assert result["affectedParts"] == ["word/document.xml", "word/footnotes.xml"]


def test_partial_never_leaves_every_unit_eligible(tmp_path) -> None:
    import importlib

    build_packet = importlib.import_module("build_packet")
    packet_tests = importlib.import_module("test_timenarratives_packet")
    body = "<odd:p><odd:r><odd:t>Body text</odd:t></odd:r></odd:p>"
    (tmp_path / "work.docx").write_bytes(
        _docx(
            _document(body),
            parts={
                "word/unknownStory.xml": _document(
                    "<odd:p><odd:r><odd:t>x</odd:t></odd:r></odd:p>"
                )
            },
            content_types={
                "word/unknownStory.xml": "application/vnd.example.story+xml"
            },
        )
    )
    result = build_packet.compile_packet(
        packet_tests.request([{"kind": "file", "path": "work.docx"}]), tmp_path
    )
    assert result["containers"][0]["disposition"] == "requiresConfirmation"
    assert [u["eligibility"] for u in result["units"]] == ["requires_confirmation"]


def test_orphan_chunk_relationship_still_affects_every_story_part() -> None:
    # Word left the aFChunk relationship and the chunk part behind, but the
    # <w:altChunk> element is gone from the body: no alt_chunk limitation fires,
    # so the unknown text part must fall back to the whole document.
    body = "<odd:p><odd:r><odd:t>Body text</odd:t></odd:r></odd:p>"
    result = docx_units.parse_docx(
        _docx(
            _document(body),
            parts={"word/chunk.html": "<p>orphaned imported text</p>"},
            relationships=_relation("a1", "aFChunk", "chunk.html"),
            content_types={"word/chunk.html": "text/html"},
        ),
        "ORPHAN",
    )
    assert result["disposition"] == "partial"
    assert result["limitations"] == ["unparsed_text_part"]
    assert result["affectedParts"] == ["word/document.xml"]


def test_missing_referenced_note_content_withholds_the_referencing_body() -> None:
    body = '<odd:p><odd:r><odd:t>Body text</odd:t><odd:footnoteReference odd:id="1"/></odd:r></odd:p>'
    footnotes = f'<n:footnotes xmlns:n="{W}"><n:footnote n:id="9"><n:p><n:r><n:t>Other note</n:t></n:r></n:p></n:footnote></n:footnotes>'
    result = docx_units.parse_docx(
        _docx(
            _document(body),
            parts={"word/footnotes.xml": footnotes},
            relationships=_relation("fn", "footnotes", "footnotes.xml"),
            content_types={
                "word/footnotes.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
            },
        ),
        "NOTE",
    )
    assert result["disposition"] == "partial"
    assert result["limitations"] == ["missing_referenced_story_content"]
    assert "word/document.xml" in result["affectedParts"]
