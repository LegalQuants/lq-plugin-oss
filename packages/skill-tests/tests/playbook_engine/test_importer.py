"""Tests for importing an existing firm playbook table.

The importer must never fabricate what the table does not say: rows are
candidates until the lawyer approves them, cells are summaries not approved
wording, priority only comes from a priority column, and every row anchors
to a real manifest element.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
BUILDER = ROOT / "skills/transactional/playbook-builder"
sys.path.insert(0, str(BUILDER / "scripts"))

from shared.playbook_runtime import (  # noqa: E402
    UNSTATED_FALLBACK_CONDITION,
    PlaybookError,
    _find_header_row,
    _match_column_headers,
    _parse_csv_table_rows,
    _parse_docx_playbook_table,
    _parse_docx_table_rows,
    _parse_xlsx_table_rows,
    import_playbook_table,
    validate_playbook,
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

Cell = str | dict[str, Any]


def _run_cli(*arguments: object) -> subprocess.CompletedProcess[str]:
    script = BUILDER / "scripts/playbook_builder.py"
    return subprocess.run(
        [sys.executable, str(script), *(str(arg) for arg in arguments)],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )


def _docx_cell(cell: Cell) -> str:
    if isinstance(cell, str):
        spec: dict[str, Any] = {"text": cell}
    else:
        spec = cell
    props = ""
    if spec.get("span", 1) > 1 or "vmerge" in spec:
        parts = []
        if spec.get("span", 1) > 1:
            parts.append(f'<w:gridSpan w:val="{spec["span"]}"/>')
        if "vmerge" in spec:
            parts.append(
                '<w:vMerge w:val="restart"/>'
                if spec["vmerge"] == "restart"
                else "<w:vMerge/>"
            )
        props = f"<w:tcPr>{''.join(parts)}</w:tcPr>"
    paragraphs = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{line}</w:t></w:r></w:p>'
        for line in str(spec.get("text", "")).split("\n")
    )
    return f"<w:tc>{props}{paragraphs}</w:tc>"


def _docx_table(rows: list[list[Cell]]) -> str:
    return (
        "<w:tbl>"
        + "".join(f"<w:tr>{''.join(_docx_cell(c) for c in row)}</w:tr>" for row in rows)
        + "</w:tbl>"
    )


def _create_docx(path: Path, *tables: list[list[Cell]], preamble: str = "") -> None:
    body = "".join(_docx_table(t) for t in tables)
    if preamble:
        body = f"<w:p><w:r><w:t>{preamble}</w:t></w:r></w:p>" + body
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{P_NS}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        zf.writestr("word/document.xml", doc_xml)


def _create_xlsx(
    path: Path,
    rows: list[list[str]],
    sheet_part: str = "xl/worksheets/sheet1.xml",
    decoy_part: str | None = None,
    shared: bool = False,
) -> None:
    strings: list[str] = []

    def cell_xml(ref: str, text: str) -> str:
        if shared:
            if text not in strings:
                strings.append(text)
            return f'<c r="{ref}" t="s"><v>{strings.index(text)}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'

    sheet_rows = []
    for r_idx, row in enumerate(rows, start=1):
        cells = [
            cell_xml(f"{chr(ord('A') + c_idx)}{r_idx}", text)
            for c_idx, text in enumerate(row)
            if text  # empty cells are omitted, as Excel does
        ]
        sheet_rows.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    sheet_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{S_NS}">'
        f"<sheetData>{''.join(sheet_rows)}</sheetData></worksheet>"
    )
    target = sheet_part.removeprefix("xl/")
    workbook_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{S_NS}" xmlns:r="{R_NS}">'
        '<sheets><sheet name="Playbook" sheetId="1" r:id="rId7"/></sheets></workbook>'
    )
    workbook_rels = (
        f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{P_NS}">'
        f'<Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="{target}"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{P_NS}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr(sheet_part, sheet_xml)
        if decoy_part:
            zf.writestr(
                decoy_part,
                f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{S_NS}">'
                '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Decoy</t></is></c></row></sheetData></worksheet>',
            )
        if shared:
            sst = "".join(f"<si><t>{s}</t></si>" for s in strings)
            zf.writestr(
                "xl/sharedStrings.xml",
                f'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="{S_NS}">{sst}</sst>',
            )


def _write_csv(path: Path, rows: list[list[str]], encoding: str = "utf-8") -> Path:
    with open(path, "w", newline="", encoding=encoding) as handle:
        csv.writer(handle).writerows(rows)
    return path


HEADER = ["Clause", "House Standard", "Concession", "Walk Away", "Risk", "Guidance"]
LIABILITY = [
    "Limitation of Liability",
    "Aggregate liability capped at 100% of annual fees.",
    "Capped at 150% of annual fees.",
    "Unlimited liability.",
    "High",
    "Escalate to the CFO above 150%.",
]
GOVERNING_LAW = [
    "Governing Law",
    "Laws of England and Wales.",
    "Scotland or Northern Ireland.",
    "Any non-UK jurisdiction.",
    "",
    "",
]


def _import(path: Path, tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "title": "Enterprise SaaS Playbook",
        "playbook_id": "enterprise-saas",
        "perspective": "supplier",
        "family": "SaaS",
        "out_dir": tmp_path / "pkg",
    }
    kwargs.update(overrides)
    return import_playbook_table(path, **kwargs)


# --- Parsers -----------------------------------------------------------------


def test_csv_parser_keeps_quoted_line_breaks_and_windows_encoding(
    tmp_path: Path,
) -> None:
    rows = [["Clause", "Position"], ["Payment", "30 days.\nInterest at 4% over base."]]
    parsed = _parse_csv_table_rows(_write_csv(tmp_path / "a.csv", rows))
    assert parsed[1][1] == "30 days.\nInterest at 4% over base."

    windows = _write_csv(
        tmp_path / "b.csv",
        [["Clause", "Position"], ["Cap", "£500,000 cap"]],
        encoding="cp1252",
    )
    assert _parse_csv_table_rows(windows)[1][1] == "£500,000 cap"

    bom = _write_csv(
        tmp_path / "c.csv", [["Clause", "Position"], ["X", "Y"]], encoding="utf-8-sig"
    )
    assert _parse_csv_table_rows(bom)[0] == ["Clause", "Position"]


def test_xlsx_parser_resolves_first_sheet_through_workbook(tmp_path: Path) -> None:
    path = tmp_path / "book.xlsx"
    _create_xlsx(
        path,
        [
            ["Topic", "Standard Position", "Walk Away"],
            ["Warranty", "90 days", "30 days"],
        ],
        sheet_part="xl/worksheets/playbook.xml",
        decoy_part="xl/worksheets/sheet1.xml",
    )
    parsed = _parse_xlsx_table_rows(path)
    assert parsed[0] == ["Topic", "Standard Position", "Walk Away"]
    assert parsed[1] == ["Warranty", "90 days", "30 days"]


def test_xlsx_parser_places_cells_by_reference_and_reads_shared_strings(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sparse.xlsx"
    _create_xlsx(
        path,
        [["Topic", "Standard", "", "Red Line"], ["Term", "", "", "No evergreen"]],
        shared=True,
    )
    parsed = _parse_xlsx_table_rows(path)
    assert parsed[0] == ["Topic", "Standard", "", "Red Line"]
    assert parsed[1] == ["Term", "", "", "No evergreen"]


def test_docx_parser_handles_merged_cells_and_picks_the_playbook_table(
    tmp_path: Path,
) -> None:
    legend: list[list[Cell]] = [["Key", "Meaning"], ["H", "High"]]
    playbook: list[list[Cell]] = [
        ["Clause", "House Standard", "Fallback", "Red Line"],
        [
            {"text": "Liability", "vmerge": "restart"},
            "100% fees",
            "150% fees",
            "Unlimited",
        ],
        [{"text": "", "vmerge": "continue"}, "Exclude indirect loss", "", "None"],
        [{"text": "Data protection", "span": 2}, "UK GDPR clause", "Controller only"],
    ]
    path = tmp_path / "firm.docx"
    _create_docx(path, legend, playbook, preamble="Negotiation playbook v3")

    filled, raw = _parse_docx_playbook_table(path)
    assert filled[0] == ["Clause", "House Standard", "Fallback", "Red Line"]
    assert filled[2][0] == "Liability"  # copied down from the merged cell
    assert raw[2][0] == ""  # but provenance keeps the manifest's view
    assert filled[3] == ["Data protection", "", "UK GDPR clause", "Controller only"]
    assert _parse_docx_table_rows(path)[0][0] == "Clause"


# --- Header matching ---------------------------------------------------------


def test_match_column_headers_prefers_exact_matches() -> None:
    mapping = _match_column_headers(
        [
            "Provision",
            "Fallback 2",
            "Fallback 1",
            "Preferred Wording",
            "Position",
            "Hard Stop",
            "Materiality",
            "Comments",
            "When",
        ]
    )
    assert mapping["topic"] == 0
    assert mapping["fallback_2"] == 1
    assert mapping["fallback_1"] == 2
    assert mapping["wording"] == 3
    assert mapping["preferred"] == 4
    assert mapping["redline"] == 5
    assert mapping["priority"] == 6
    assert mapping["guidance"] == 7
    assert mapping["condition"] == 8


def test_find_header_row_skips_title_rows() -> None:
    rows = [
        ["Firm Playbook v3", "", ""],
        ["Last reviewed March 2026", "", ""],
        ["Clause", "House Standard", "Fallback"],
        ["Liability", "100%", "150%"],
    ]
    assert _find_header_row(rows) == 2
    assert _find_header_row([["a", "b"], ["c", "d"]]) == 0


# --- Import semantics --------------------------------------------------------


def test_import_defaults_to_candidate_rows_in_a_draft_playbook(tmp_path: Path) -> None:
    path = _write_csv(tmp_path / "playbook.csv", [HEADER, LIABILITY, GOVERNING_LAW])
    result = _import(path, tmp_path)
    assert result["status"] == "candidate"
    assert result["sealed"] is False
    assert result["issuesCount"] == 2
    assert result["columnMap"] == {
        "topic": "Clause",
        "preferred": "House Standard",
        "fallback_1": "Concession",
        "redline": "Walk Away",
        "priority": "Risk",
        "guidance": "Guidance",
    }
    playbook = json.loads((tmp_path / "pkg/playbook.json").read_text(encoding="utf-8"))
    assert playbook["status"] == "draft"
    assert playbook["governingLaw"] is None
    assert "dateStyle" not in playbook
    liability = playbook["issues"][0]
    assert liability["issueId"] == "limitation-of-liability"
    assert liability["status"] == "candidate"
    assert liability["basePosition"]["preferred"]["approvalStatus"] == "candidate"
    assert liability["basePosition"]["preferred"]["text"] is None
    assert liability["basePosition"]["preferred"]["summary"] == LIABILITY[1]
    assert "Guidance: Escalate to the CFO" in liability["basePosition"]["summary"]
    assert liability["basePosition"]["priority"] == "high"
    fallback = liability["basePosition"]["fallbacks"][0]
    assert fallback["condition"] == UNSTATED_FALLBACK_CONDITION
    assert fallback["wording"]["text"] is None
    assert fallback["wording"]["approvalStatus"] == "candidate"
    # No priority column value, red line present: still medium, never inferred.
    assert playbook["issues"][1]["basePosition"]["priority"] == "medium"
    assert (
        playbook["issues"][1]["basePosition"]["redLine"] == "Any non-UK jurisdiction."
    )

    receipt = json.loads(
        (tmp_path / "pkg/import-receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["status"] == "candidate"
    assert receipt["approvalNote"] is None
    assert receipt["headerRow"] == 1
    assert not (tmp_path / "pkg/build-receipt.json").exists()

    manifest = json.loads(
        (tmp_path / "pkg/source-manifest.json").read_text(encoding="utf-8")
    )
    assert validate_playbook(playbook, source_manifest=manifest) == []


def test_import_anchors_every_row_to_its_manifest_element(tmp_path: Path) -> None:
    path = _write_csv(tmp_path / "playbook.csv", [HEADER, LIABILITY, GOVERNING_LAW])
    result = _import(path, tmp_path)
    manifest = result["manifest"]
    elements = {e["elementId"]: e for e in manifest["documents"][0]["elements"]}
    for issue in result["playbook"]["issues"]:
        provenance = issue["provenance"][0]
        assert (
            provenance["exactText"] == elements[provenance["elementId"]]["sourceText"]
        )
        assert issue["topic"] in provenance["exactText"]
    ids = [i["provenance"][0]["elementId"] for i in result["playbook"]["issues"]]
    assert len(set(ids)) == len(ids)


def test_import_uses_wording_and_condition_columns_when_present(tmp_path: Path) -> None:
    rows = [
        ["Clause", "Position", "Approved Wording", "Fallback", "Condition", "Priority"],
        [
            "Audit",
            "Annual audit on notice",
            "The Customer may audit the Supplier once per year on 30 days' notice.",
            "1. Twice per year\n2) Quarterly for regulated customers",
            "Regulated customer",
            "low",
        ],
    ]
    result = _import(_write_csv(tmp_path / "w.csv", rows), tmp_path)
    issue = result["playbook"]["issues"][0]
    assert issue["basePosition"]["preferred"]["text"] == rows[1][2]
    assert issue["basePosition"]["priority"] == "low"
    fallbacks = issue["basePosition"]["fallbacks"]
    assert [f["wording"]["summary"] for f in fallbacks] == [
        "Twice per year",
        "Quarterly for regulated customers",
    ]
    assert [f["rank"] for f in fallbacks] == [1, 2]
    assert all(f["condition"] == "Regulated customer" for f in fallbacks)


def test_import_with_approval_note_approves_and_seals(tmp_path: Path) -> None:
    path = _write_csv(tmp_path / "playbook.csv", [HEADER, LIABILITY, GOVERNING_LAW])
    registry = tmp_path / "playbook-registry.json"
    result = _import(
        path,
        tmp_path,
        approve_note="Lawyer's message: 'this table is our approved policy, load it'",
        seal=True,
        registry_path=registry,
        governing_law="England and Wales",
    )
    assert result["status"] == "approved"
    assert result["sealed"] is True
    playbook = json.loads((tmp_path / "pkg/playbook.json").read_text(encoding="utf-8"))
    assert playbook["status"] == "approved"
    assert playbook["dateStyle"] == "uk"
    assert all(i["status"] == "approved" for i in playbook["issues"])
    manifest = json.loads(
        (tmp_path / "pkg/source-manifest.json").read_text(encoding="utf-8")
    )
    assert (
        validate_playbook(playbook, require_approved=True, source_manifest=manifest)
        == []
    )
    assert (tmp_path / "pkg/build-receipt.json").is_file()
    assert (tmp_path / "pkg/playbook.md").is_file()
    receipt = json.loads(
        (tmp_path / "pkg/import-receipt.json").read_text(encoding="utf-8")
    )
    assert "approved policy" in receipt["approvalNote"]
    registered = json.loads(registry.read_text(encoding="utf-8"))
    assert "enterprise-saas" in [p["playbookId"] for p in registered["playbooks"]]


def test_import_refuses_to_seal_candidates(tmp_path: Path) -> None:
    path = _write_csv(tmp_path / "playbook.csv", [HEADER, LIABILITY])
    with pytest.raises(PlaybookError, match="approve_note"):
        _import(path, tmp_path, seal=True)
    assert not (tmp_path / "pkg").exists()


def test_import_finds_header_below_title_rows_in_excel(tmp_path: Path) -> None:
    path = tmp_path / "titled.xlsx"
    _create_xlsx(
        path,
        [
            ["Commercial Playbook", "", "", ""],
            ["Version 3, March 2026", "", "", ""],
            ["Clause Name", "House Position", "Concession", "Hard Stop"],
            ["Term", "1 year auto-renew", "1 year fixed", "Multi-year without break"],
        ],
    )
    result = _import(path, tmp_path)
    assert result["issuesCount"] == 1
    receipt = json.loads(
        (tmp_path / "pkg/import-receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["headerRow"] == 3
    assert result["playbook"]["issues"][0]["issueId"] == "term"


def test_import_word_table_with_merged_cells_and_legend(tmp_path: Path) -> None:
    legend: list[list[Cell]] = [["Key", "Meaning"], ["H", "High"]]
    playbook: list[list[Cell]] = [
        ["Clause", "House Standard", "Fallback", "Red Line"],
        [
            {"text": "Liability", "vmerge": "restart"},
            "100% fees",
            "150% fees",
            "Unlimited",
        ],
        [{"text": "", "vmerge": "continue"}, "Exclude indirect loss", "", "None"],
    ]
    path = tmp_path / "firm.docx"
    _create_docx(path, legend, playbook)
    result = _import(path, tmp_path)
    issues = result["playbook"]["issues"]
    assert [i["issueId"] for i in issues] == ["liability", "liability-2"]
    assert issues[1]["topic"] == "Liability"
    # The merged row's provenance is the row as the manifest saw it.
    assert issues[1]["provenance"][0]["exactText"] == "Exclude indirect loss | None"
    manifest = result["manifest"]
    assert validate_playbook(result["playbook"], source_manifest=manifest) == []


def test_import_skips_incomplete_rows_and_reports_them(tmp_path: Path) -> None:
    rows = [
        HEADER,
        LIABILITY,
        ["Notes only", "", "", "", "", "see above"],
        GOVERNING_LAW,
    ]
    result = _import(_write_csv(tmp_path / "gaps.csv", rows), tmp_path)
    assert result["issuesCount"] == 2
    assert result["rowsSkipped"] == [3]


def test_import_rejects_unrecognised_headers_and_empty_tables(tmp_path: Path) -> None:
    with pytest.raises(PlaybookError, match="Could not identify"):
        _import(_write_csv(tmp_path / "odd.csv", [["A", "B"], ["x", "y"]]), tmp_path)
    with pytest.raises(PlaybookError, match="header row and at least one data row"):
        _import(_write_csv(tmp_path / "empty.csv", [["Clause", "Standard"]]), tmp_path)
    txt = tmp_path / "unsupported.txt"
    txt.write_text("Not a table", encoding="utf-8")
    with pytest.raises(PlaybookError, match="Unsupported table format"):
        _import(txt, tmp_path)
    with pytest.raises(FileNotFoundError):
        _import(tmp_path / "missing.docx", tmp_path)


def test_import_cli_requires_family_and_gates_sealing(tmp_path: Path) -> None:
    path = _write_csv(tmp_path / "cli.csv", [HEADER, LIABILITY])
    base = [
        "import-playbook",
        path,
        "--title",
        "Warranty Playbook",
        "--playbook-id",
        "warranty-pb",
        "--perspective",
        "supplier",
        "--out-dir",
        tmp_path / "pkg",
    ]

    missing_family = _run_cli(*base)
    assert missing_family.returncode == 2
    assert "--family" in missing_family.stderr

    candidate = _run_cli(*base, "--family", "MSA")
    assert candidate.returncode == 0, candidate.stderr
    data = json.loads(candidate.stdout)
    assert data["status"] == "candidate"
    assert data["columnMap"]["topic"] == "Clause"

    seal_without_approval = _run_cli(*base, "--family", "MSA", "--seal")
    assert seal_without_approval.returncode != 0
    assert (
        "approve"
        in (seal_without_approval.stderr + seal_without_approval.stdout).lower()
    )

    sealed = _run_cli(
        *base,
        "--family",
        "MSA",
        "--approve-all",
        "Lawyer's message: 'approved, load it'",
        "--seal",
        "--registry",
        tmp_path / "playbook-registry.json",
    )
    assert sealed.returncode == 0, sealed.stderr
    assert json.loads(sealed.stdout)["status"] == "approved"
    assert (tmp_path / "pkg/build-receipt.json").is_file()
