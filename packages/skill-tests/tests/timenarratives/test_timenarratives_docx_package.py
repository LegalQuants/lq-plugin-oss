# ruff: noqa: E501 - synthetic OOXML is intentionally literal and inspectable
"""Safety contract for the stdlib-only DOCX package reader."""

from __future__ import annotations

import importlib
import struct
import sys
import warnings
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills/core/timenarratives/scripts"
sys.path.insert(0, str(SCRIPTS))
docx_package = importlib.import_module("docx_package")

CONTENT_TYPES = """<?xml version="1.0"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="xml" ContentType="application/xml"/>
 <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
 <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""
ROOT_RELS = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
 <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""
DOCUMENT = """<x:document xmlns:x="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><x:body><x:p><x:r><x:t>Hello</x:t></x:r></x:p></x:body></x:document>"""
CORE = """<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dcterms="http://purl.org/dc/terms/"><dcterms:modified>2026-08-21T09:10:11Z</dcterms:modified></cp:coreProperties>"""


def _archive(
    *,
    document: str | None = DOCUMENT,
    content_types: str | None = CONTENT_TYPES,
    root_rels: str | None = ROOT_RELS,
    extra: dict[str, str | bytes] | None = None,
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    members: dict[str, str | bytes] = {"docProps/core.xml": CORE}
    if content_types is not None:
        members["[Content_Types].xml"] = content_types
    if root_rels is not None:
        members["_rels/.rels"] = root_rels
    if document is not None:
        members["word/document.xml"] = document
    members.update(extra or {})
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return output.getvalue()


def _archive_entries(entries: list[tuple[str, str | bytes]]) -> bytes:
    output = BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(output, "w") as archive:
            for name, payload in entries:
                archive.writestr(name, payload)
    return output.getvalue()


def _encrypted_flag(data: bytes) -> bytes:
    output = bytearray(data)
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        start = 0
        while (start := output.find(signature, start)) >= 0:
            flags = struct.unpack_from("<H", output, start + flag_offset)[0]
            struct.pack_into("<H", output, start + flag_offset, flags | 1)
            start += 4
    return bytes(output)


def _error_code(data: bytes) -> str:
    with pytest.raises(Exception) as caught:  # noqa: B017 - asserting stable code below
        docx_package.load_docx_package(data)
    return str(getattr(caught.value, "code", caught.value))


def test_docx_package_reader_is_available() -> None:
    assert (SCRIPTS / "docx_package.py").is_file()


def test_docx_package_exposes_a_loader() -> None:
    assert callable(getattr(docx_package, "load_docx_package", None))


def test_loads_main_document_timestamp_and_external_relationship_inventory() -> None:
    rels = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.invalid/private" TargetMode="External"/>
    </Relationships>"""
    package = docx_package.load_docx_package(
        _archive(extra={"word/_rels/document.xml.rels": rels})
    )
    assert package.main_document == "word/document.xml"
    assert package.filter_timestamp == "2026-08-21T09:10:11Z"
    assert sorted(package.members) == [
        "[Content_Types].xml",
        "_rels/.rels",
        "docProps/core.xml",
        "word/_rels/document.xml.rels",
        "word/document.xml",
    ]
    assert package.external_relationships == (
        {
            "id": "rId9",
            "source": "word/document.xml",
            "target": "https://example.invalid/private",
            "type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        },
    )


def test_invalid_core_timestamp_is_null_not_a_filter_fact() -> None:
    package = docx_package.load_docx_package(
        _archive(
            extra={
                "docProps/core.xml": CORE.replace("2026-08-21T09:10:11Z", "not-a-time")
            }
        )
    )
    assert package.filter_timestamp is None


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-21T09:10:11+0000",
        "2026-08-21 09:10:11Z",
        "2026-08-21T09:10Z",
        "2026-08-21T09:10:11Z ",
        "2026-08-21t09:10:11Z",
        "2026-08-21T09:10:11z",
    ],
)
def test_non_rfc3339_core_timestamps_are_never_preserved(value: str) -> None:
    package = docx_package.load_docx_package(
        _archive(
            extra={"docProps/core.xml": CORE.replace("2026-08-21T09:10:11Z", value)}
        )
    )

    assert package.filter_timestamp is None
    foreign = CORE.replace("http://purl.org/dc/terms/", "urn:not-dcterms")
    package = docx_package.load_docx_package(
        _archive(extra={"docProps/core.xml": foreign})
    )
    assert package.filter_timestamp is None


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"not a zip", "invalid_zip_magic"),
        (_archive(content_types=None), "missing_content_types"),
        (_archive(root_rels=None), "missing_root_relationships"),
        (
            _archive(
                root_rels='<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
            ),
            "missing_main_document_relationship",
        ),
        (_archive(document=None), "missing_main_document"),
        (_archive(document="<broken"), "malformed_xml"),
        (
            _archive(
                document='<x:notDocument xmlns:x="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'
            ),
            "invalid_main_document_root",
        ),
        (
            _archive(
                document='<!DOCTYPE x [<!ENTITY e "boom">]><x:document xmlns:x="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><x:body><x:p><x:r><x:t>&e;</x:t></x:r></x:p></x:body></x:document>'
            ),
            "forbidden_xml_declaration",
        ),
    ],
)
def test_rejects_invalid_package_roots(data: bytes, expected: str) -> None:
    assert _error_code(data) == expected


@pytest.mark.parametrize(
    "unsafe_name",
    ["../escape.xml", "/absolute.xml", "C:/drive.xml"],
)
def test_rejects_unsafe_member_paths(unsafe_name: str) -> None:
    assert _error_code(_archive(extra={unsafe_name: "x"})) == "unsafe_member_path"


def test_rejects_a_raw_backslash_member_path() -> None:
    data = _archive(extra={"word/evil.xml": "x"}).replace(
        b"word/evil.xml", b"word\\evil.xml"
    )
    assert _error_code(data) == "unsafe_member_path"


def test_rejects_duplicate_and_casefold_colliding_members() -> None:
    base = [
        ("[Content_Types].xml", CONTENT_TYPES),
        ("_rels/.rels", ROOT_RELS),
        ("word/document.xml", DOCUMENT),
    ]
    assert (
        _error_code(_archive_entries([*base, ("word/a.xml", "x"), ("word/a.xml", "y")]))
        == "duplicate_member"
    )
    assert (
        _error_code(_archive_entries([*base, ("word/A.xml", "x"), ("word/a.xml", "y")]))
        == "member_case_collision"
    )


def test_rejects_encryption_macro_and_relationship_escape() -> None:
    assert _error_code(_encrypted_flag(_archive())) == "encrypted_package"
    macro_types = CONTENT_TYPES.replace(
        "document.wordprocessingml.document.main+xml",
        "document.macroEnabled.main+xml",
    )
    assert _error_code(_archive(content_types=macro_types)) == "macro_enabled_package"
    escaping = ROOT_RELS.replace("word/document.xml", "../../../escape.xml")
    assert _error_code(_archive(root_rels=escaping)) == "unsafe_relationship_target"


def test_rejects_wrong_control_namespaces_main_type_and_rels_part_name() -> None:
    wrong_types = CONTENT_TYPES.replace(
        "http://schemas.openxmlformats.org/package/2006/content-types",
        "urn:not-content-types",
    )
    assert _error_code(_archive(content_types=wrong_types)) == "invalid_content_types"
    wrong_rels = ROOT_RELS.replace(
        "http://schemas.openxmlformats.org/package/2006/relationships",
        "urn:not-relationships",
    )
    assert _error_code(_archive(root_rels=wrong_rels)) == "invalid_root_relationships"
    wrong_main = CONTENT_TYPES.replace(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        "application/xml",
    )
    assert (
        _error_code(_archive(content_types=wrong_main))
        == "invalid_main_document_content_type"
    )
    assert (
        _error_code(_archive(extra={"loose.rels": "<Relationships/>"}))
        == "invalid_relationship_part"
    )


def test_enforces_member_count_size_ratio_depth_and_xml_element_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docx_package, "MAX_MEMBERS", 4)
    assert _error_code(_archive(extra={"extra.bin": b"x"})) == "member_count_limit"
    monkeypatch.setattr(docx_package, "MAX_MEMBERS", 512)
    monkeypatch.setattr(docx_package, "MAX_MEMBER_BYTES", 20)
    assert _error_code(_archive()) == "member_size_limit"
    monkeypatch.setattr(docx_package, "MAX_MEMBER_BYTES", 32 * 1024 * 1024)
    monkeypatch.setattr(docx_package, "MAX_COMPRESSION_RATIO", 10.0)
    assert (
        _error_code(_archive(extra={"bomb.bin": b"0" * 100_000}))
        == "compression_ratio_limit"
    )
    monkeypatch.setattr(docx_package, "MAX_COMPRESSION_RATIO", 500.0)
    monkeypatch.setattr(docx_package, "MAX_PATH_DEPTH", 4)
    assert _error_code(_archive(extra={"a/b/c/d/e.bin": b"x"})) == "member_depth_limit"
    monkeypatch.setattr(docx_package, "MAX_PATH_DEPTH", 16)
    monkeypatch.setattr(docx_package, "MAX_XML_ELEMENTS", 3)
    assert _error_code(_archive(compression=zipfile.ZIP_STORED)) == "xml_element_limit"
    monkeypatch.setattr(docx_package, "MAX_XML_ELEMENTS", 250_000)
    monkeypatch.setattr(docx_package, "MAX_XML_DEPTH", 3)
    assert _error_code(_archive(compression=zipfile.ZIP_STORED)) == "xml_depth_limit"


def test_directory_entries_are_ignored_not_rejected() -> None:
    data = _archive_entries(
        [
            ("word/", b""),
            ("docProps/", b""),
            ("[Content_Types].xml", CONTENT_TYPES),
            ("_rels/.rels", ROOT_RELS),
            ("word/document.xml", DOCUMENT),
            ("docProps/core.xml", CORE),
        ]
    )
    package = docx_package.load_docx_package(data)
    assert "word/" not in package.members
    assert "docProps/" not in package.members
    assert package.main_document == "word/document.xml"


def test_directory_entry_with_payload_is_still_rejected() -> None:
    data = _archive_entries(
        [
            ("word/", b"not-empty"),
            ("[Content_Types].xml", CONTENT_TYPES),
            ("_rels/.rels", ROOT_RELS),
            ("word/document.xml", DOCUMENT),
            ("docProps/core.xml", CORE),
        ]
    )
    assert _error_code(data) == "unsafe_member_path"
