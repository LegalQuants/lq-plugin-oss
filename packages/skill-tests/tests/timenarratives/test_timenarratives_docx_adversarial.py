# ruff: noqa: E501 - synthetic OOXML is intentionally literal and inspectable
"""Adversarial regressions for DOCX completeness and reference closure."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills/core/timenarratives/scripts"
sys.path[:0] = [str(SCRIPTS), str(ROOT / "packages/skill-tests/tests")]

docx_units = importlib.import_module("docx_units")
fixtures = importlib.import_module("test_timenarratives_docx_units")

W = fixtures.W
R = fixtures.R
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_docx = fixtures._docx
_document = fixtures._document
_relation = fixtures._relation


def _texts(result: dict) -> list[str]:
    return [unit["canonicalText"] for unit in result["units"]]


def _parts(result: dict) -> dict[str, dict]:
    return {part["locator"].removeprefix("docx:"): part for part in result["parts"]}


def test_unreferenced_header_and_footer_relationships_never_emit_text() -> None:
    body = """<w:p><w:r><w:t>Main</w:t></w:r></w:p>
    <w:sectPr><w:headerReference w:type="default" r:id="h1"/></w:sectPr>"""
    parts: dict[str, str | bytes] = {
        "word/header1.xml": f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:t>Active header</w:t></w:r></w:p></w:hdr>',
        "word/header2.xml": f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:t>Orphan header</w:t></w:r></w:p></w:hdr>',
        "word/footer1.xml": f'<w:ftr xmlns:w="{W}"><w:p><w:r><w:t>Orphan footer</w:t></w:r></w:p></w:ftr>',
    }
    relationships = "".join(
        [
            _relation("h1", "header", "header1.xml"),
            _relation("h2", "header", "header2.xml"),
            _relation("f1", "footer", "footer1.xml"),
        ]
    )
    media = {
        name: "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"
        for name in ("word/header1.xml", "word/header2.xml")
    }
    media["word/footer1.xml"] = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"
    )

    result = docx_units.parse_docx(
        _docx(
            _document(body, "w"),
            parts=parts,
            relationships=relationships,
            content_types=media,
        ),
        "REFS",
    )

    assert result["disposition"] == "ready"
    assert _texts(result) == ["Main", "Active header"]
    package_parts = _parts(result)
    for name in ("word/header2.xml", "word/footer1.xml"):
        assert package_parts[name]["disposition"] == "excluded"
        assert package_parts[name]["reason"] == "unreferenced_story_part"
        assert package_parts[name]["unitIds"] == []


def test_ambiguous_header_relationship_never_promotes_either_target() -> None:
    body = """<w:p><w:r><w:t>Main</w:t></w:r></w:p>
    <w:sectPr><w:headerReference w:type="default" r:id="same"/></w:sectPr>"""
    parts: dict[str, str | bytes] = {
        "word/header1.xml": f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:t>First</w:t></w:r></w:p></w:hdr>',
        "word/header2.xml": f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:t>Second</w:t></w:r></w:p></w:hdr>',
    }
    relationships = _relation("same", "header", "header1.xml") + _relation(
        "same", "header", "header2.xml"
    )
    media = {
        name: "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"
        for name in parts
    }

    result = docx_units.parse_docx(
        _docx(
            _document(body, "w"),
            parts=parts,
            relationships=relationships,
            content_types=media,
        ),
        "AMBIG",
    )

    assert result["disposition"] == "partial"
    assert result["affectedParts"] == ["word/document.xml"]
    assert result["limitations"] == ["ambiguous_relationship_reference"]
    assert _texts(result) == ["Main"]
    assert all(
        _parts(result)[name]["reason"] == "unreferenced_story_part" for name in parts
    )


def test_header_reference_with_wrong_relationship_kind_is_partial() -> None:
    body = """<w:p><w:r><w:t>Main</w:t></w:r></w:p>
    <w:sectPr><w:headerReference w:type="default" r:id="wrong"/></w:sectPr>"""
    footer = f'<w:ftr xmlns:w="{W}"><w:p><w:r><w:t>Footer</w:t></w:r></w:p></w:ftr>'

    result = docx_units.parse_docx(
        _docx(
            _document(body, "w"),
            parts={"word/footer1.xml": footer},
            relationships=_relation("wrong", "footer", "footer1.xml"),
            content_types={
                "word/footer1.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"
            },
        ),
        "KIND",
    )

    assert result["disposition"] == "partial"
    assert result["affectedParts"] == ["word/document.xml"]
    assert result["limitations"] == ["invalid_referenced_story_relationship"]
    assert _texts(result) == ["Main"]


def test_multiple_referenced_headers_follow_document_reference_order() -> None:
    identifiers = ["zeta", "alpha", "mu", "beta"]
    references = "".join(
        f'<w:headerReference w:type="default" r:id="{identifier}"/>'
        for identifier in identifiers
    )
    body = f"<w:p><w:r><w:t>Main</w:t></w:r></w:p><w:sectPr>{references}</w:sectPr>"
    parts: dict[str, str | bytes] = {
        f"word/header{index}.xml": f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:t>{identifier}</w:t></w:r></w:p></w:hdr>'
        for index, identifier in enumerate(identifiers, 1)
    }
    relationships = "".join(
        _relation(identifier, "header", f"header{index}.xml")
        for index, identifier in reversed(list(enumerate(identifiers, 1)))
    )
    media = {
        name: "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"
        for name in parts
    }

    result = docx_units.parse_docx(
        _docx(
            _document(body, "w"),
            parts=parts,
            relationships=relationships,
            content_types=media,
        ),
        "ORDER",
    )

    assert _texts(result) == ["Main", *identifiers]


def test_only_referenced_note_and_comment_ids_emit_units() -> None:
    body = """<w:p><w:r><w:t>Main</w:t><w:footnoteReference w:id="1"/>
    <w:commentReference w:id="5"/></w:r></w:p>"""
    parts: dict[str, str | bytes] = {
        "word/footnotes.xml": f'<w:footnotes xmlns:w="{W}"><w:footnote w:id="1"><w:p><w:r><w:t>Used note</w:t></w:r></w:p></w:footnote><w:footnote w:id="2"><w:p><w:r><w:t>Orphan note</w:t></w:r></w:p></w:footnote></w:footnotes>',
        "word/comments.xml": f'<w:comments xmlns:w="{W}"><w:comment w:id="5"><w:p><w:r><w:t>Used comment</w:t></w:r></w:p></w:comment><w:comment w:id="6"><w:p><w:r><w:t>Orphan comment</w:t></w:r></w:p></w:comment></w:comments>',
    }
    relationships = _relation("n1", "footnotes", "footnotes.xml") + _relation(
        "c1", "comments", "comments.xml"
    )
    media = {
        "word/footnotes.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
        "word/comments.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml",
    }

    result = docx_units.parse_docx(
        _docx(
            _document(body, "w"),
            parts=parts,
            relationships=relationships,
            content_types=media,
        ),
        "IDS",
    )

    assert result["disposition"] == "ready"
    assert _texts(result) == ["Main", "Used note", "Used comment"]
    assert "Orphan note" not in _texts(result)
    assert "Orphan comment" not in _texts(result)


def test_office_math_text_is_extracted_in_visible_document_order() -> None:
    body = f"""<w:p xmlns:m="{M}"><w:r><w:t>Before </w:t></w:r>
    <m:oMath><m:r><m:t>x</m:t></m:r><m:r><m:t> + 1</m:t></m:r></m:oMath>
    <w:r><w:t> after</w:t></w:r></w:p>"""

    result = docx_units.parse_docx(_docx(_document(body, "w")), "MATH")

    assert result["disposition"] == "ready"
    assert _texts(result) == ["Before x + 1 after"]


def test_unmapped_word_symbol_preserves_text_but_forces_partial_story() -> None:
    body = """<w:p><w:r><w:t>Before</w:t>
    <w:sym w:font="Wingdings" w:char="F0A7"/><w:t>After</w:t></w:r></w:p>"""

    result = docx_units.parse_docx(_docx(_document(body, "w")), "SYMBOL")

    assert result["disposition"] == "partial"
    assert result["affectedParts"] == ["word/document.xml"]
    assert result["reason"] == "unparsed_text_bearing_content"
    assert result["limitations"] == ["font_symbol_unresolved"]
    assert _texts(result) == ["BeforeAfter"]
    main_part = _parts(result)["word/document.xml"]
    assert main_part["disposition"] == "unreadable"
    assert main_part["reason"] == "font_symbol_unresolved"


def test_non_rfc3339_core_time_is_null_and_noted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_core = fixtures.CORE.replace(
        "2026-08-21T09:10:11Z", "2026-08-21T09:10:11+0000"
    )
    monkeypatch.setattr(fixtures, "CORE", invalid_core)
    body = "<w:p><w:r><w:t>Timestamped text</w:t></w:r></w:p>"

    result = docx_units.parse_docx(_docx(_document(body, "w")), "TIME")

    assert result["disposition"] == "ready"
    assert result["filterTimestamp"] is None
    assert result["sourceTime"] is None
    assert result["sourceTimeKind"] is None
    assert result["limitations"] == []
    assert result["notes"] == ["invalid_core_timestamp"]
    assert result["affectedParts"] == []
    core_part = _parts(result)["docProps/core.xml"]
    assert core_part["disposition"] == "excluded"
    assert core_part["reason"] == "invalid_core_timestamp"


@pytest.mark.parametrize(
    ("attribute", "relationships", "expected_limitation"),
    [
        ("embed", "", "missing_relationship_reference"),
        (
            "embed",
            _relation("image1", "image", "media/missing.png"),
            "missing_internal_relationship_target",
        ),
        (
            "link",
            f'<Relationship Id="image1" Type="{R}/image" Target="https://example.invalid/image.png" TargetMode="External"/>',
            "external_relationship_not_retrieved",
        ),
        (
            "link",
            f'<Relationship Id="image1" Type="{R}/image" Target="" TargetMode="External"/>',
            "missing_external_relationship_target",
        ),
    ],
)
def test_active_drawing_relationships_are_closed_or_explicitly_partial(
    attribute: str, relationships: str, expected_limitation: str
) -> None:
    drawing = f"""<w:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
    <w:r><w:t>Visible text</w:t><w:drawing><a:blip r:{attribute}="image1"/></w:drawing></w:r></w:p>"""

    result = docx_units.parse_docx(
        _docx(_document(drawing, "w"), relationships=relationships), "DRAW"
    )

    assert result["disposition"] == "partial"
    assert result["affectedParts"] == ["word/document.xml"]
    assert result["limitations"] == [expected_limitation]
    assert _texts(result) == ["Visible text"]
    main_part = _parts(result)["word/document.xml"]
    assert main_part["disposition"] == "unreadable"
    assert main_part["reason"] == expected_limitation


def test_referenced_note_without_story_relationship_is_explicitly_partial() -> None:
    body = '<w:p><w:r><w:t>Main</w:t><w:footnoteReference w:id="1"/></w:r></w:p>'
    note = f'<w:footnotes xmlns:w="{W}"><w:footnote w:id="1"><w:p><w:r><w:t>Unclosed note</w:t></w:r></w:p></w:footnote></w:footnotes>'

    result = docx_units.parse_docx(
        _docx(
            _document(body, "w"),
            parts={"word/footnotes.xml": note},
            content_types={
                "word/footnotes.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
            },
        ),
        "NOTE",
    )

    assert result["disposition"] == "partial"
    assert result["affectedParts"] == ["word/document.xml"]
    assert result["limitations"] == ["missing_referenced_story_relationship"]
    assert _texts(result) == ["Main"]
    note_part = _parts(result)["word/footnotes.xml"]
    assert note_part["disposition"] == "excluded"
    assert note_part["reason"] == "unreferenced_story_part"


def test_partial_docx_state_survives_packet_and_strict_schema(tmp_path: Path) -> None:
    packet = importlib.import_module("build_packet")
    packet_tests = importlib.import_module("test_timenarratives_packet")
    body = (
        "<w:p><w:r><w:t>Schema-safe partial text</w:t></w:r></w:p>"
        '<w:altChunk r:id="a1"/>'
    )
    (tmp_path / "work.docx").write_bytes(
        _docx(
            _document(body, "w"),
            parts={"word/chunk.html": "<p>imported</p>"},
            relationships=_relation("a1", "aFChunk", "chunk.html"),
            content_types={"word/chunk.html": "text/html"},
        )
    )

    result = packet.compile_packet(
        packet_tests.request([{"kind": "file", "path": "work.docx"}]), tmp_path
    )

    assert result["roots"][0]["disposition"] == "requiresConfirmation"
    assert result["containers"][0]["disposition"] == "requiresConfirmation"
    assert result["units"][0]["eligibility"] == "requires_confirmation"
    assert result["units"][0]["sourceTime"] == "2026-08-21T09:10:11Z"
    assert "docx_partial" in result["errors"]
    packet_tests._assert_schema_valid(
        tmp_path, "timenarratives-packet.schema.json", result
    )
