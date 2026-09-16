import copy
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills/transactional/closing-checklist/scripts"
FIXTURES = ROOT / "packages/skill-tests/tests/closing_checklist/fixtures"
sys.path.insert(0, str(SCRIPTS))

import checklist_docx as word  # noqa: E402
import closing_checklist as cc  # noqa: E402

HEADINGS = ["No.", "Item", "Responsibility", "Timing", "Status", "Internal notes"]
CELLS = [
    "1",
    "Deliver certificates (cl. 5)",
    "Seller's counsel",
    "At Completion",
    "Complete",
    "INTERNAL: negotiation fallback",
]


@pytest.fixture
def baseline(tmp_path):
    path = tmp_path / "latest.docx"
    path.write_bytes(
        word.archive(
            word.generic(
                "Project Lantern",
                HEADINGS,
                [
                    {"phase": "Closing", "cells": CELLS},
                    {
                        "phase": "Post-closing",
                        "cells": [
                            "2",
                            "Lawyer-added bank mandate",
                            "Buyer",
                            "To confirm",
                            "Pending",
                            "Keep me",
                        ],
                    },
                ],
            )
        )
    )
    return path


def proposal(**values):
    return {
        "id": "R1",
        "basis": "instruction",
        "reason": "Lawyer requested reference update",
        "evidence": [],
        "kind": "update",
        "table": 0,
        "row": 2,
        "before": CELLS,
        "values": {"1": "Deliver certificates (cl. 8)"},
        **values,
    }


def revision(baseline, operations=None):
    return cc.make_plan(
        {
            "mode": "revise",
            "baseline": str(baseline),
            "operations": operations or [proposal()],
        },
        cc.prepare([]),
    )


def approval(plan, ids=None):
    return {
        "plan_sha256": plan["plan_sha256"],
        "approved_ids": ids or ["R1"],
        "user_instruction": "Yes, apply the reference correction only.",
    }


def test_revision_preserves_manual_work_and_original(baseline, tmp_path):
    original = baseline.read_bytes()
    parts = word.package(baseline)
    parts["customXml/item1.xml"] = b"<internal>retained in INTERNAL copy</internal>"
    baseline.write_bytes(word.archive(parts))
    plan = revision(baseline)
    out = tmp_path / "revised.docx"
    out.write_bytes(cc.apply(plan, approval(plan)))
    before, after = word.inspect(baseline)[0], word.inspect(out)[0]
    assert after["rows"][2]["cells"][1] == "Deliver certificates (cl. 8)"
    assert after["rows"][2]["cells"][2:] == CELLS[2:]
    assert before["rows"][3:] == after["rows"][3:]
    assert before["rows"][1] == after["rows"][1]
    assert word.package(out)["customXml/item1.xml"] == parts["customXml/item1.xml"]
    assert baseline.read_bytes() == word.archive(parts)
    assert original != baseline.read_bytes()  # fixture alteration, not helper mutation


def test_unapproved_operation_is_not_applied(baseline, tmp_path):
    remove = proposal(
        id="R2",
        kind="remove",
        row=4,
        before=word.inspect(baseline)[0]["rows"][4]["cells"],
    )
    plan = revision(baseline, [proposal(), remove])
    out = tmp_path / "partial.docx"
    out.write_bytes(cc.apply(plan, approval(plan)))
    assert len(word.inspect(out)[0]["rows"]) == 5


@pytest.mark.parametrize("field", ["plan_sha256", "user_instruction", "approved_ids"])
def test_invalid_approval_blocks_output(baseline, field):
    plan = revision(baseline)
    consent = approval(plan)
    consent[field] = [] if field == "approved_ids" else ""
    with pytest.raises(ValueError):
        cc.apply(plan, consent)


def test_stale_baseline_and_tampered_plan_block(baseline):
    plan = revision(baseline)
    tampered = copy.deepcopy(plan)
    tampered["spec"]["operations"][0]["values"]["4"] = "Waived"
    with pytest.raises(ValueError, match="Approval"):
        cc.apply(tampered, approval(plan))
    baseline.write_bytes(cc.apply(plan, approval(plan)))
    with pytest.raises(ValueError, match="changed"):
        cc.apply(plan, approval(plan))


def test_reapplication_to_original_does_not_duplicate(baseline, tmp_path):
    op = proposal(
        kind="add_after",
        row=1,
        before=["Closing"],
        prototype_row=2,
        values=["1a", "Side letter", "Seller", "At Completion", "Not confirmed", ""],
    )
    plan = revision(baseline, [op])
    for i in range(2):
        out = tmp_path / f"run-{i}.docx"
        out.write_bytes(cc.apply(plan, approval(plan)))
        texts = [r["cells"] for r in word.inspect(out)[0]["rows"]]
        assert sum("Side letter" in cells for cells in texts) == 1


def test_exact_source_quote_and_stale_source(tmp_path):
    source = tmp_path / "anchor.md"
    source.write_text("Seller shall deliver share certificates.\n", encoding="utf-8")
    bundle = cc.prepare([source])
    item = {
        "id": "C1",
        "basis": "document",
        "reason": "Express delivery",
        "evidence": [
            {"source_id": "S1", "unit_id": "L1", "quote": "share certificates"}
        ],
        "phase": "Closing",
        "cells": CELLS,
    }
    spec = {"mode": "create", "title": "Example", "headings": HEADINGS, "items": [item]}
    plan = cc.make_plan(spec, bundle)
    assert cc.apply(plan, approval(plan, ["C1"]))[:2] == b"PK"
    item["evidence"][0]["quote"] = "regulatory clearance"
    with pytest.raises(ValueError, match="quote"):
        cc.make_plan(spec, bundle)
    source.write_text("Changed source", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        cc.apply(plan, approval(plan, ["C1"]))


def create_plan(tmp_path, numbers):
    source = tmp_path / "anchor.md"
    source.write_text("Seller shall deliver share certificates.\n", encoding="utf-8")
    items = [
        {
            "id": f"C{n}",
            "basis": "document",
            "reason": "Express delivery",
            "evidence": [
                {"source_id": "S1", "unit_id": "L1", "quote": "share certificates"}
            ],
            "phase": "Closing",
            "cells": [n, f"Deliver item {n}", "Seller", "At Completion", "Pending", ""],
        }
        for n in numbers
    ]
    return cc.make_plan(
        {"mode": "create", "title": "Example", "headings": HEADINGS, "items": items},
        cc.prepare([source]),
    )


def test_partial_approval_resequences_the_number_column(tmp_path):
    plan = create_plan(tmp_path, ["1", "2", "3"])
    out = tmp_path / "partial.docx"
    out.write_bytes(cc.apply(plan, approval(plan, ["C1", "C3"])))
    rows = word.inspect(out)[0]["rows"]
    assert [row["cells"][:2] for row in rows[2:]] == [
        ["1", "Deliver item 1"],
        ["2", "Deliver item 3"],
    ]


def test_manual_numbering_scheme_is_left_alone(tmp_path):
    plan = create_plan(tmp_path, ["1", "1a", "2"])
    out = tmp_path / "manual.docx"
    out.write_bytes(cc.apply(plan, approval(plan, ["C1", "C1a"])))
    rows = word.inspect(out)[0]["rows"]
    assert [row["cells"][0] for row in rows[2:]] == ["1", "1a"]


def test_content_types_is_the_first_package_member(baseline, tmp_path):
    out = tmp_path / "revised.docx"
    plan = revision(baseline)
    out.write_bytes(cc.apply(plan, approval(plan)))
    for path in (baseline, out):
        with ZipFile(path) as archive:
            assert archive.namelist()[0] == "[Content_Types].xml", path


def test_house_template_preserves_style(baseline, tmp_path):
    parts = word.package(baseline)
    root = word.xml(parts["word/document.xml"])
    for font in root.iter(word.tag("rFonts")):
        font.set(word.tag("ascii"), "Arial")
    grid = root.find(".//w:gridCol", word.NS)
    grid.set(word.tag("w"), "700")
    parts["word/document.xml"] = word.serialize(root)
    result = word.from_template(
        parts,
        {"table": 0, "item_row": 2, "phase_row": 1, "body_start": 1},
        [{"phase": "Signing and closing", "cells": CELLS}],
    )
    out = tmp_path / "house.docx"
    out.write_bytes(word.archive(result))
    changed = word.xml(result["word/document.xml"])
    assert all(
        f.get(word.tag("ascii")) == "Arial" for f in changed.iter(word.tag("rFonts"))
    )
    assert changed.find(".//w:gridCol", word.NS).get(word.tag("w")) == "700"
    assert word.inspect(out)[0]["rows"][1]["spans"] == [6]


@pytest.mark.parametrize("feature", ["vMerge", "ins", "sdt"])
def test_unsupported_content_is_not_flattened(baseline, feature):
    parts = word.package(baseline)
    root = word.xml(parts["word/document.xml"])
    cell = word.cells(word.rows(word.tables(root)[0])[2])[1]
    target = cell.find("w:tcPr", word.NS) if feature == "vMerge" else cell
    word.element(target, feature)
    parts["word/document.xml"] = word.serialize(root)
    with pytest.raises(ValueError):
        word.patch(parts, [proposal()])


def test_generic_external_removes_notes_and_preserves_original(baseline, tmp_path):
    original = baseline.read_bytes()
    out = tmp_path / "external.docx"
    out.write_bytes(cc.external_copy(baseline, 0, 5))
    assert baseline.read_bytes() == original
    assert word.inspect(out)[0]["grid_columns"] == 5
    assert word.inspect(out)[0]["rows"][1]["spans"] == [5]
    saved = b"".join(word.package(out).values())
    assert b"negotiation fallback" not in saved
    assert b"Keep me" not in saved
    assert b"Deliver certificates" in saved


@pytest.mark.parametrize(
    "name", ["word/comments.xml", "customXml/item1.xml", "docProps/core.xml"]
)
def test_external_refuses_recoverable_notes(baseline, name):
    parts = word.package(baseline)
    parts[name] = b"<secret>CONFIDENTIAL</secret>"
    baseline.write_bytes(word.archive(parts))
    with pytest.raises(ValueError, match="sanitisation"):
        cc.external_copy(baseline, 0, 5)


def test_new_output_never_overwrites_input(baseline):
    original = baseline.read_bytes()
    with pytest.raises(FileExistsError):
        cc.write_new(baseline, b"replacement")
    assert baseline.read_bytes() == original


def test_multiline_cell_roundtrip(baseline, tmp_path):
    out = tmp_path / "multiline.docx"
    out.write_bytes(
        word.archive(
            word.patch(
                word.package(baseline),
                [proposal(values={"1": "Deliver certificates\nClause 8"})],
            )
        )
    )
    assert (
        word.inspect(out)[0]["rows"][2]["cells"][1] == "Deliver certificates\nClause 8"
    )


def test_cli_prepare_fixture_and_unknown_type(tmp_path):
    out = tmp_path / "sources.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "closing_checklist.py"),
            "prepare",
            str(FIXTURES / "anchor-v1.md"),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert len(json.loads(out.read_text())["sources"][0]["units"]) == 9
    with pytest.raises(ValueError, match="TXT/MD/DOCX"):
        cc.extract(tmp_path / "unreadable.pdf")


# --- Issue #180 layout: legend, source column, footer, notes, sub-headings ---

DEFAULT = [
    "No.",
    "Source reference",
    "Item",
    "Responsibility",
    "Timing",
    "Status",
    "Notes",
]
FRONT = {
    "scope": [
        "Source: Project Lantern SPA, Draft 3 dated 1 June 2026",
        "Perspective: Buyer",
    ],
    "parties": [
        {
            "label": "Seller",
            "name": "Lantern Holdings Limited",
            "role": "Seller",
            "group": "Principals",
        },
        {
            "label": "Buyer",
            "name": "Beacon Bidco Limited",
            "role": "Buyer",
            "group": "Principals",
        },
        {
            "label": "[Counsel A]",
            "name": "Not identified in the source",
            "role": "Seller's counsel",
            "group": "Advisers and service providers",
        },
    ],
    "status_key": [
        {"label": "Not confirmed", "meaning": "Status unknown from the sources"},
        {"label": "Complete", "meaning": "Confirmed complete by the lawyer"},
    ],
    "footer": "Prepared based on draft Share Purchase Agreement (Draft 3) "
    "dated 1 June 2026",
}


def default_records():
    return [
        {
            "phase": "Closing",
            "group": "Seller deliverables",
            "cells": [
                "1",
                "SPA cl. 5.1(a)",
                "Deliver share certificates",
                "Seller",
                "At Completion",
                "Not confirmed",
                "Query: originals or certified copies?",
            ],
        },
        {
            "phase": "Closing",
            "group": "Seller deliverables",
            "cells": [
                "2",
                "SPA cl. 5.1(b)",
                "Deliver stock transfer forms",
                "Seller",
                "At Completion",
                "Not confirmed",
                "",
            ],
        },
        {
            "phase": "Closing",
            "group": "Buyer deliverables",
            "cells": [
                "3",
                "SPA cl. 5.2",
                "Pay the Purchase Price",
                "Buyer",
                "At Completion",
                "Not confirmed",
                "INTERNAL: funds-flow not yet agreed",
            ],
        },
        {
            "phase": "Post-closing",
            "cells": [
                "4",
                "SPA cl. 6.1",
                "Deliver statutory books",
                "Seller",
                "No later than three Business Days after Completion",
                "Not confirmed",
                "",
            ],
        },
    ]


def default_create(tmp_path, front=FRONT, headings=DEFAULT, records=None):
    source = tmp_path / "anchor.md"
    source.write_text("Seller shall deliver share certificates.\n", encoding="utf-8")
    items = [
        {
            "id": f"C{i}",
            "basis": "document",
            "reason": "Express obligation",
            "evidence": [
                {"source_id": "S1", "unit_id": "L1", "quote": "share certificates"}
            ],
            **record,
        }
        for i, record in enumerate(records or default_records(), 1)
    ]
    spec = {
        "mode": "create",
        "title": "Project Lantern — Closing Checklist",
        "headings": headings,
        "items": items,
        **front,
    }
    plan = cc.make_plan(spec, cc.prepare([source]))
    out = tmp_path / "default.docx"
    out.write_bytes(cc.apply(plan, approval(plan, [i["id"] for i in items])))
    return out


def body_sequence(path):
    root = word.xml(word.package(path)["word/document.xml"])
    body = root.find("w:body", word.NS)
    return [
        word.text(node) if node.tag == word.tag("p") else node.tag.split("}")[1]
        for node in body
    ]


def test_default_layout_places_legend_and_key_before_checklist(tmp_path):
    out = default_create(tmp_path)
    sequence = body_sequence(out)
    assert sequence[:3] == ["Project Lantern — Closing Checklist", *FRONT["scope"]]
    assert sequence[3:] == [
        "Parties",
        "tbl",
        "Status key",
        "tbl",
        "Checklist",
        "tbl",
        "sectPr",
    ]
    legend, key, checklist = word.inspect(out)
    assert legend["rows"][0]["cells"] == ["Short label", "Full name", "Role"]
    assert legend["rows"][1]["cells"] == ["Principals"] and legend["rows"][1][
        "spans"
    ] == [3]
    assert legend["rows"][4]["cells"] == ["Advisers and service providers"]
    assert key["rows"][1]["cells"] == [
        "Not confirmed",
        "Status unknown from the sources",
    ]
    assert checklist["grid_columns"] == 7
    assert checklist["rows"][0]["cells"] == DEFAULT


def test_default_layout_groups_rows_under_phase_and_sub_headings(tmp_path):
    out = default_create(tmp_path)
    rows = word.inspect(out)[2]["rows"]
    merged = [(r["cells"][0], r["spans"]) for r in rows if len(r["cells"]) == 1]
    assert merged == [
        ("Closing", [7]),
        ("Seller deliverables", [7]),
        ("Buyer deliverables", [7]),
        ("Post-closing", [7]),
    ]
    assert [r["cells"][2] for r in rows if len(r["cells"]) == 7][1:] == [
        "Deliver share certificates",
        "Deliver stock transfer forms",
        "Pay the Purchase Price",
        "Deliver statutory books",
    ]


def test_footer_repeats_source_basis_and_page_numbers(tmp_path):
    out = default_create(tmp_path)
    parts = word.package(out)
    footer = word.xml(parts["word/footer1.xml"])
    assert word.text(footer) == f"{FRONT['footer']}\tPage 1 of 1"
    instrs = [
        f.get(word.tag("instr")).strip() for f in footer.iter(word.tag("fldSimple"))
    ]
    assert instrs == ["PAGE", "NUMPAGES"]
    document = word.xml(parts["word/document.xml"])
    ref = document.find(".//w:sectPr/w:footerReference", word.NS)
    assert ref is not None and ref.get(word.tag("type")) == "default"
    assert document.find(".//w:sectPr/w:titlePg", word.NS) is None  # first page too
    assert b"/word/footer1.xml" in parts["[Content_Types].xml"]
    assert b"footer1.xml" in parts["word/_rels/document.xml.rels"]


def test_missing_draft_date_keeps_visible_placeholder(tmp_path):
    front = {
        **FRONT,
        "footer": "Prepared based on draft Share Purchase Agreement [date]",
    }
    out = default_create(tmp_path, front)
    assert "[date]" in word.text(word.xml(word.package(out)["word/footer1.xml"]))


def test_column_widths_follow_heading_meaning():
    widths = word.widths_for(DEFAULT)
    assert abs(sum(widths) - word.TABLE_WIDTH) < len(DEFAULT)
    by_name = dict(zip(DEFAULT, widths, strict=True))
    assert by_name["Item"] == max(widths)
    assert by_name["No."] == min(widths)
    assert by_name["Source reference"] < by_name["Notes"]
    legacy = dict(zip(HEADINGS, word.widths_for(HEADINGS), strict=True))
    assert legacy["Item"] == max(legacy.values())


@pytest.mark.parametrize("count", [4, 9])
def test_generic_rejects_unsupported_column_counts(count):
    headings = [f"Column {i}" for i in range(count)]
    with pytest.raises(ValueError, match="five to eight"):
        word.generic("Title", headings, [])


@pytest.mark.parametrize(
    "front",
    [
        {"parties": [{"label": "Seller", "role": "Seller"}]},
        {"parties": []},
        {"status_key": [{"label": "Complete"}]},
        {"scope": "not a list"},
        {"footer": ["not", "a", "string"]},
    ],
)
def test_front_matter_is_validated_at_plan_time(tmp_path, front):
    with pytest.raises(ValueError):
        default_create(tmp_path, {**FRONT, **front})


def test_external_copy_keeps_legend_and_footer_and_removes_notes(tmp_path):
    internal = default_create(tmp_path)
    original = internal.read_bytes()
    out = tmp_path / "external.docx"
    out.write_bytes(cc.external_copy(internal, None, 6))
    assert internal.read_bytes() == original
    legend, key, checklist = word.inspect(out)
    assert checklist["grid_columns"] == 6
    assert checklist["rows"][0]["cells"] == DEFAULT[:6]
    assert [r["spans"] for r in checklist["rows"] if len(r["cells"]) == 1] == [[6]] * 4
    assert legend["rows"][2]["cells"] == [
        "Seller",
        "Lantern Holdings Limited",
        "Seller",
    ]
    parts = word.package(out)
    saved = b"".join(parts.values())
    assert b"funds-flow not yet agreed" not in saved
    assert b"originals or certified copies" not in saved
    assert b"Deliver share certificates" in saved
    assert str(FRONT["footer"]).encode() in parts["word/footer1.xml"]
    assert set(parts) == set(word.GENERIC_PARTS)
    assert body_sequence(out) == body_sequence(internal)


def test_external_refuses_a_column_that_is_not_notes(tmp_path):
    internal = default_create(tmp_path)
    with pytest.raises(ValueError, match="does not look like notes"):
        cc.external_copy(internal, None, 2)
    with pytest.raises(ValueError, match="outside"):
        cc.external_copy(internal, None, 7)


def test_external_refuses_notes_text_repeated_in_public_cells(tmp_path):
    records = default_records()
    records[0]["cells"][2] = (
        "Deliver share certificates. Query: originals or certified copies?"
    )
    internal = default_create(tmp_path, records=records)
    with pytest.raises(ValueError, match="appears elsewhere"):
        cc.external_copy(internal, None, 6)


def test_page_number_fields_are_editable_but_other_fields_are_not(tmp_path):
    internal = default_create(tmp_path)
    parts = word.package(internal)
    before = word.inspect(internal)[2]["rows"][3]["cells"]
    op = proposal(
        table=2,
        row=3,
        before=before,
        values={"2": "Deliver original share certificates"},
    )
    revised = word.patch(parts, [op])
    assert revised["word/footer1.xml"] == parts["word/footer1.xml"]
    root = word.xml(parts["word/document.xml"])
    field = word.element(root.find(".//w:tc/w:p", word.NS), "fldSimple", instr=" DATE ")
    with pytest.raises(ValueError, match="page numbers"):
        word.editable(root, parts)
    field.set(word.tag("instr"), " PAGE \\* MERGEFORMAT ")
    word.editable(root, parts)
    word.element(root.find(".//w:tc/w:p/w:r", word.NS), "fldChar", fldCharType="begin")
    with pytest.raises(ValueError, match="host editor"):
        word.editable(root, parts)


def test_parse_generic_roundtrips_front_matter_and_records(tmp_path):
    internal = default_create(tmp_path)
    title, front, headings, records, index = word.parse_generic(word.package(internal))
    assert (title, headings, index) == (
        "Project Lantern — Closing Checklist",
        DEFAULT,
        2,
    )
    assert front["scope"] == FRONT["scope"]
    assert front["parties"] == FRONT["parties"]
    assert front["status_key"] == FRONT["status_key"]
    assert front["footer"] == FRONT["footer"]
    assert records == default_records()


def test_legacy_six_column_layout_still_supported(tmp_path):
    out = default_create(tmp_path, {}, HEADINGS, [{"phase": "Closing", "cells": CELLS}])
    checklist = word.inspect(out)[0]
    assert checklist["grid_columns"] == 6
    assert body_sequence(out) == [
        "Project Lantern — Closing Checklist",
        "Checklist",
        "tbl",
        "sectPr",
    ]
    external = tmp_path / "legacy-external.docx"
    external.write_bytes(cc.external_copy(out, 0, 5))
    assert word.inspect(external)[0]["grid_columns"] == 5


def test_cli_external_defaults_to_last_table(tmp_path):
    internal = default_create(tmp_path)
    out = tmp_path / "cli-external.docx"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "closing_checklist.py"),
            "external",
            str(internal),
            "--notes-column",
            "6",
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert word.inspect(out)[2]["grid_columns"] == 6
