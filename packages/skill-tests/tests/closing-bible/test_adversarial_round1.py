"""Adversarial closing regressions:
one test per confirmed defect, numbered as the log numbers them, then the
contract settlements the same round produced (checklist hash, approved-index
corpus, `status` recomputation, the empty expected set, `--as-of`, and the
uninspected unexpected family). Each pins the behaviour the contract now
requires; none may be weakened."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from cb_support import (
    AS_OF,
    BUYER,
    CLOSING_DATE_TEXT,
    SELLER,
    Audit,
    Folder,
    checklist,
    cover,
    evidence,
    ledger,
    ledger_block,
    ledger_page,
    load,
    rec_not_expected,
    rec_signed,
    rec_unsigned,
    record,
    run_cli,
    signed_page,
    write_cli_inputs,
)
from closing_bible import models

SPA = "Share Purchase Agreement"
EXECUTION_REL = "execution/(Final) Share Purchase Agreement.pdf"
EXECUTED_NAME = "(Executed) Share Purchase Agreement.pdf"
EXECUTED_REL = f"executed/{EXECUTED_NAME}"
BLANK_BLOCK = (
    f"SIGNED by ______________\nfor and on behalf of {SELLER}\nDated: ______________"
)


def _both(date: str | None) -> str:
    return (
        signed_page(party=SELLER, date=date)
        + "\n"
        + signed_page(party=BUYER, date=date)
    )


def _section(exceptions: str, title: str) -> str:
    return exceptions.split(f"## {title}\n", 1)[1].split("\n## ", 1)[0]


def _spa_ledger(
    blocks: list[dict[str, Any]], *, page: str = "SPA-p3", page_no: int = 3
) -> dict[str, Any]:
    return ledger(
        [
            ledger_page(
                page, "(Final) Share Purchase Agreement.pdf", page_no, SPA, blocks
            )
        ]
    )


# --------------------------------------------------------------- defect 1


def test_01_visual_blank_on_the_pick_beats_a_ledger_placed_by_name(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """[1] Ledger placed_in is resolved by basename alone, so a blank draft
    named "(Executed) SPA.pdf" is READY on ledger evidence — even when visual
    inspection recorded the block as blank. Now: the honest visual record
    governs the item (unsigned, visual-inspection), the ledger's blocks stay
    verbatim in the overview, and the disagreement is written under Ledger
    notes with the contract's line."""

    folder.pdf(EXECUTION_REL, [cover(SPA), "terms", BLANK_BLOCK])
    draft = folder.pdf(EXECUTED_NAME, [cover(SPA), "terms", BLANK_BLOCK + "\nDRAFT"])
    led = _spa_ledger(
        [
            ledger_block(
                1,
                SELLER.upper(),
                "signed",
                dated=CLOSING_DATE_TEXT,
                placed_in=f"{EXECUTED_NAME}#3",
            )
        ]
    )
    run = audit(checklist=checklist([("1.1", SPA, True)]), sigpack=led)
    fam = run.family_of(draft)
    result = run.reconcile([rec_unsigned(fam, draft, page=3)])  # no ledger citation
    assert result.receipt["sigpack"]["ledger_current"] is True
    assert result.receipt["inspection"]["rejected"] == 0
    item = result.item(SPA)
    assert item["status"] == "unsigned"
    assert item["selected_id"] == draft
    assert item["execution"] == {
        "evidence_source": "visual-inspection",
        "apparent_status": "appears-unsigned",
        "dated": "undated",
        "ledger_page_ids": [],
    }
    assert item["document_date"] is None
    assert "appears unsigned on visual inspection" in item["qualification"]
    doc_view = result.overview_doc(item["item_id"])
    assert [b["status"] for b in doc_view["blocks"]] == ["signed"]  # never softened
    line = (
        "inspection saw a blank block on the selected file; the ledger's signed "
        "finding could not be tied to these bytes"
    )
    assert line in doc_view["exceptions"]
    assert f"- CB-001 {SPA}: {line}" in _section(result.exceptions, "Ledger notes")
    assert result.receipt["by_status"]["ready"] == 0
    assert result.receipt["outcome"] == "qualified"
    assert result.receipt["sigpack"]["documents_cited"] == 0


# --------------------------------------------------------------- defect 2


def test_02_execution_evidence_and_signature_pages_must_name_the_pick(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """[2] Execution/date evidence and signature_pages may point at a different
    document than the pick (even one outside the family), so an unsigned file
    named FINAL EXECUTED is READY on another file's signature page. Now the
    record is rejected with the reason, and the item is unsigned."""

    blank = folder.pdf("SPA FINAL EXECUTED.pdf", [cover(SPA), "terms", BLANK_BLOCK])
    signed = folder.pdf("return_0001.pdf", [signed_page(date=CLOSING_DATE_TEXT)])
    run = audit(checklist=checklist([("1.1", "SPA", True)]))
    fam = run.family_of(blank)
    assert fam["member_ids"] == [blank]
    lying = record(
        fam,
        pick=blank,
        status="ready",
        execution_expected=True,
        apparent="appears-signed",
        dated="dated",
        document_date=CLOSING_DATE_TEXT,
        signature_pages=[{"document_id": signed, "page": 1}],
        evidence=[
            evidence(
                "execution", "visual-inspection", "page 1", "block signed", signed
            ),
            evidence("date", "visual-inspection", "page 1", "dated", signed),
        ],
        validate=False,
    )
    with pytest.raises(ValueError, match="findings are about the pick"):
        models.FamilyInspection.from_dict(lying)
    result = run.reconcile([lying])
    assert result.receipt["inspection"] == {
        "families": 2,
        "inspected": 0,
        "rejected": 1,
    }
    assert "cites a document that is not the pick" in result.exceptions
    item = result.item("SPA")
    assert item["status"] == "unsigned"
    assert item["execution"]["apparent_status"] == "not-inspected"
    assert result.overview_doc(item["item_id"])["signature_pages"] == []
    assert result.receipt["by_status"]["ready"] == 0


# --------------------------------------------------------------- defect 3


def test_03_dated_needs_a_date_seen_and_document_date_must_read_as_a_date(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """[3] dated: dated needs no date evidence and document_date is unvalidated
    free text — a filename date or an mtime string becomes the document date
    of a READY item. Now: a record carrying dated with a filename date and no
    date evidence is rejected, and a placeholder or dotted line is not a date."""

    rel = "SPA - signed 2026-09-01.pdf"
    doc = folder.pdf(
        rel, [cover(SPA), "terms", signed_page(date=None)], mtime="2020-09-13T09:00:00"
    )
    run = audit(checklist=checklist([("1.1", "SPA", True)]))
    fam = run.family_of(doc)
    filename_dated = record(
        fam,
        pick=doc,
        status="ready",
        execution_expected=True,
        apparent="appears-signed",
        dated="dated",
        document_date="2026-09-01",
        signature_pages=[{"document_id": doc, "page": 3}],
        evidence=[
            evidence("version", "filename", rel, "filename dated 2026-09-01", doc),
            evidence(
                "execution",
                "visual-inspection",
                "page 3",
                "block signed; date line is dotted and empty",
                doc,
            ),
        ],
        validate=False,
    )
    with pytest.raises(ValueError, match="dated without a date evidence record"):
        models.FamilyInspection.from_dict(filename_dated)
    result = run.reconcile([filename_dated])
    assert result.receipt["inspection"]["rejected"] == 1
    item = result.item("SPA")
    assert item["status"] == "unsigned" and item["document_date"] is None
    everything = json.dumps([result.index, result.overview]).replace(rel, "")
    assert "2026-09-01" not in everything and "2020-09-13" not in everything
    # document_date must read as a date: a placeholder or a blank line is not one.
    for not_a_date in ("[DATE]", "...........", "Date: ______"):
        with pytest.raises(ValueError, match="does not read as a date"):
            models.ExecutionFinding("appears-signed", "dated", not_a_date)
    # And the index never carries a date without a dated finding behind it.
    with pytest.raises(ValueError, match="rule 3"):
        models.IndexItem(
            item_id="CB-001",
            order=1,
            title=SPA,
            checklist_ref=None,
            execution_expected=True,
            status="unsigned",
            family_id=fam["family_id"],
            selected_id=doc,
            execution=models.ExecutionRecord("none", "not-inspected", "unclear"),
            document_date="1 March 2026",
            qualification="not inspected",
        )


# --------------------------------------------------------------- defect 4


@pytest.mark.parametrize("cite", ["other_member", "encrypted_file", "null_and_phantom"])
def test_04_blank_execution_version_never_ready_on_another_files_pages(
    folder: Folder, audit: Callable[..., Audit], cite: str
) -> None:
    """[4] ready is written for the BLANK execution version when every
    execution/date observation and signature-page location cites a different
    file (another member, a census-encrypted file, or nothing at all). Every
    variant is now rejected: findings are about the pick."""

    blank = folder.pdf(
        "SPA/Share Purchase Agreement (Execution Version).pdf",
        [cover(SPA), "terms", BLANK_BLOCK],
    )
    if cite == "other_member":
        other = folder.pdf(
            "SPA/Share Purchase Agreement (Executed).pdf",
            [cover(SPA), "terms", _both(CLOSING_DATE_TEXT)],
        )
        cited: str | None = other
    elif cite == "encrypted_file":
        cited = folder.pdf(
            "SPA/Share Purchase Agreement (Signed).pdf",
            [cover(SPA), "terms", _both(CLOSING_DATE_TEXT)],
            encrypt=True,
        )
    else:
        cited = None
    run = audit(checklist=checklist([("1.1", SPA, True)]))
    fam = run.family_of(blank)
    page_doc = cited or "sha256:" + "0" * 12
    lying = record(
        fam,
        pick=blank,
        status="ready",
        execution_expected=True,
        apparent="appears-signed",
        dated="dated",
        document_date=CLOSING_DATE_TEXT,
        signature_pages=[{"document_id": page_doc, "page": 3}],
        evidence=[
            evidence("execution", "visual-inspection", "page 3", "both signed", cited),
            evidence("date", "visual-inspection", "page 3", "dated", page_doc),
        ],
        validate=False,
    )
    with pytest.raises(ValueError, match="findings are about the pick"):
        models.FamilyInspection.from_dict(lying)
    result = run.reconcile([lying])
    assert result.receipt["inspection"]["rejected"] == 1
    item = result.item(SPA)
    assert item["status"] != "ready"
    assert item["selected_id"] != blank or item["status"] == "unsigned"
    assert result.receipt["by_status"]["ready"] == 0
    assert page_doc not in json.dumps(result.overview)


# --------------------------------------------------------------- defect 5


def test_05_dated_without_a_date_evidence_record_is_rejected(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """[5] dated:'dated' needs no date evidence record — undated page reads as
    ready with a date nobody observed. Now the twin of the appears-signed rule
    applies: rejected as dated without date evidence."""

    doc = folder.pdf(
        "Share Purchase Agreement (Executed).pdf",
        [cover(SPA), "terms", _both(None)],
    )
    run = audit(checklist=checklist([("1.1", SPA, True)]))
    fam = run.family_of(doc)
    no_date_seen = record(
        fam,
        pick=doc,
        status="ready",
        execution_expected=True,
        apparent="appears-signed",
        dated="dated",
        document_date=CLOSING_DATE_TEXT,
        signature_pages=[{"document_id": doc, "page": 3}],
        evidence=[
            evidence(
                "execution", "visual-inspection", "page 3", "both blocks signed", doc
            )
        ],
        validate=False,
    )
    result = run.reconcile([no_date_seen])
    assert result.receipt["inspection"]["rejected"] == 1
    assert "dated without a date evidence record" in _section(
        result.exceptions, "Rejected inspection records"
    )
    item = result.item(SPA)
    assert item["status"] == "unsigned" and item["document_date"] is None
    assert result.overview_doc(item["item_id"])["dating_unresolved"] is True
    # The honest record — the page is signed, the date line blank — lands undated.
    honest = rec_signed(fam, doc, page=3, date=None)
    assert run.reconcile([honest]).item(SPA)["status"] == "undated"


# --------------------------------------------------------------- defect 6


def test_06_not_inspected_carries_no_date(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """[6] not-inspected record may carry dated:'dated' + document_date; the
    index and overview then show a document date with evidence_source none
    and dating_unresolved false. Now that record is rejected; the honest one
    (dated unclear, document_date null) is read and dating stays unresolved."""

    doc = folder.pdf("Deed of Release - EXECUTED.pdf", [cover("Deed of Release")])
    run = audit(checklist=checklist([("3", "Deed of Release", True)]))
    fam = run.family_of(doc)
    identity = evidence(
        "identity", "filename", "Deed of Release - EXECUTED.pdf", "named", doc
    )
    dated_blind = record(
        fam,
        pick=doc,
        status="unsigned",
        execution_expected=True,
        apparent="not-inspected",
        dated="dated",
        document_date=CLOSING_DATE_TEXT,
        evidence=[identity],
        note="render failed",
        validate=False,
    )
    with pytest.raises(ValueError, match="not-inspected requires dated: unclear"):
        models.FamilyInspection.from_dict(dated_blind)
    result = run.reconcile([dated_blind])
    assert result.receipt["inspection"]["rejected"] == 1
    honest = record(
        fam,
        pick=doc,
        status="unsigned",
        execution_expected=True,
        apparent="not-inspected",
        dated="unclear",
        evidence=[identity],
        note="render failed",
    )
    result = run.reconcile([honest])
    assert result.receipt["inspection"] == {
        "families": 1,
        "inspected": 1,
        "rejected": 0,
    }
    item = result.item("Deed of Release")
    assert item["status"] == "unsigned"
    assert item["document_date"] is None
    assert item["execution"]["evidence_source"] == "none"
    doc_view = result.overview_doc(item["item_id"])
    assert doc_view["document_date"] is None
    assert doc_view["dating_unresolved"] is True


# --------------------------------------------------------------- defect 7


def test_07_held_sheet_is_appears_incomplete_never_signed(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """[7] A HELD page (signed, chosen return, no placed_in) is flattened into
    appears-signed → ready; the executed file lacks that page's signed sheet.
    Now mapping row 5 applies: appears-incomplete with the sheet named, the
    ledger-citing appears-signed record is rejected, and the honest record
    lands unsigned."""

    folder.pdf(EXECUTION_REL, [cover(SPA), "terms", BLANK_BLOCK, BLANK_BLOCK])
    executed = folder.pdf(
        EXECUTED_REL,
        [cover(SPA), "terms", signed_page(date=CLOSING_DATE_TEXT), BLANK_BLOCK],
    )
    led = ledger(
        [
            ledger_page(
                "SPA-p3",
                "(Final) Share Purchase Agreement.pdf",
                3,
                SPA,
                [
                    ledger_block(
                        1,
                        SELLER.upper(),
                        "signed",
                        dated=CLOSING_DATE_TEXT,
                        placed_in=f"{EXECUTED_NAME}#3",
                    )
                ],
            ),
            ledger_page(
                "SPA-p4",
                "(Final) Share Purchase Agreement.pdf",
                4,
                SPA,
                [ledger_block(1, BUYER.upper(), "signed", dated=CLOSING_DATE_TEXT)],
            ),
        ]
    )
    run = audit(checklist=checklist([("1.1", SPA, True)]), sigpack=led)
    fam = run.family_of(executed)
    cites = [
        evidence("execution", "sigpack-ledger", p, "signed", executed)
        for p in ("SPA-p3", "SPA-p4")
    ]
    lying = record(
        fam,
        pick=executed,
        status="ready",
        execution_expected=True,
        apparent="appears-signed",
        dated="dated",
        document_date=CLOSING_DATE_TEXT,
        signature_pages=[{"document_id": executed, "page": 3}],
        evidence=cites
        + [evidence("date", "sigpack-ledger", "SPA-p3", "dated", executed)],
    )
    result = run.reconcile([lying])
    assert result.receipt["inspection"]["rejected"] == 1
    assert "the ledger reads appears-incomplete" in result.exceptions
    assert result.receipt["by_status"]["ready"] == 0

    honest = record(
        fam,
        pick=executed,
        status="unsigned",
        execution_expected=True,
        apparent="appears-incomplete",
        dated="dated",
        document_date=CLOSING_DATE_TEXT,
        signature_pages=[{"document_id": executed, "page": 3}],
        evidence=cites
        + [evidence("date", "sigpack-ledger", "SPA-p3", "dated", executed)],
        note="buyer's signed sheet is still held by sigpack",
    )
    result = run.reconcile([honest])
    assert result.receipt["inspection"]["rejected"] == 0
    item = result.item(SPA)
    assert item["status"] == "unsigned"
    assert item["execution"]["evidence_source"] == "sigpack-ledger"
    assert item["execution"]["apparent_status"] == "appears-incomplete"
    assert item["execution"]["ledger_page_ids"] == ["SPA-p3", "SPA-p4"]
    assert "signed sheet for `SPA-p4` held, not placed" in item["qualification"]
    doc_view = result.overview_doc(item["item_id"])
    assert "signed sheet for `SPA-p4` held, not placed" in doc_view["exceptions"]
    assert doc_view["signature_pages"] == [{"document_id": executed, "page": 3}]
    assert [b["status"] for b in doc_view["blocks"]] == ["signed", "signed"]
    assert result.receipt["outcome"] == "qualified"


# --------------------------------------------------------------- defect 8


def test_08_dated_is_per_block_and_the_worst_wins(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """[8] One dated block makes the whole document 'dated'; a second signed
    block with date_field true and no date is silently ignored → ready instead
    of undated. Now the undated block governs: the item is undated, the
    record claiming dated is rejected."""

    folder.pdf(EXECUTION_REL, [cover(SPA), "terms", BLANK_BLOCK, BLANK_BLOCK])
    executed = folder.pdf(
        EXECUTED_REL,
        [
            cover(SPA),
            "terms",
            signed_page(date=CLOSING_DATE_TEXT),
            signed_page(party=BUYER, date=None),
        ],
    )
    led = ledger(
        [
            ledger_page(
                "SPA-p3",
                "(Final) Share Purchase Agreement.pdf",
                3,
                SPA,
                [
                    ledger_block(
                        1,
                        SELLER.upper(),
                        "signed",
                        dated=CLOSING_DATE_TEXT,
                        placed_in=f"{EXECUTED_NAME}#3",
                    )
                ],
            ),
            ledger_page(
                "SPA-p4",
                "(Final) Share Purchase Agreement.pdf",
                4,
                SPA,
                [
                    ledger_block(
                        1, BUYER.upper(), "signed", placed_in=f"{EXECUTED_NAME}#4"
                    )
                ],
            ),
        ]
    )
    run = audit(checklist=checklist([("1.1", SPA, True)]), sigpack=led)
    fam = run.family_of(executed)
    cites = [
        evidence("execution", "sigpack-ledger", p, "signed", executed)
        for p in ("SPA-p3", "SPA-p4")
    ]
    claims_dated = rec_signed(
        fam,
        executed,
        page=3,
        source="sigpack-ledger",
        locator="SPA-p3",
        extra_evidence=cites[1:],
    )
    result = run.reconcile([claims_dated])
    assert result.receipt["inspection"]["rejected"] == 1
    assert "the ledger reads appears-signed/undated" in result.exceptions
    honest = record(
        fam,
        pick=executed,
        status="undated",
        execution_expected=True,
        apparent="appears-signed",
        dated="undated",
        signature_pages=[{"document_id": executed, "page": 3}],
        evidence=cites,
    )
    result = run.reconcile([honest])
    assert result.receipt["inspection"]["rejected"] == 0
    item = result.item(SPA)
    assert item["status"] == "undated"
    assert item["execution"]["dated"] == "undated"
    assert item["document_date"] is None
    assert "no completion date" in item["qualification"]
    assert result.overview_doc(item["item_id"])["dating_unresolved"] is True
    assert result.receipt["by_status"]["ready"] == 0


# --------------------------------------------------------------- defect 9


def test_09_date_field_false_everywhere_records_dated_not_expected_and_lands_ready(
    folder: Folder, audit: Callable[..., Audit], out_dir: Path
) -> None:
    """[9] date_field false on every block: the record SKILL.md tells the model
    to write is always rejected, and the family lands version-conflict. Now
    execution expected with dated not-expected validates, and the ledger
    settles the item ready — through the API and the CLI."""

    folder.pdf(EXECUTION_REL, [cover(SPA), "terms", BLANK_BLOCK, BLANK_BLOCK])
    executed = folder.pdf(
        EXECUTED_REL,
        [
            cover(SPA),
            "terms",
            signed_page(date=None),
            signed_page(party=BUYER, date=None),
        ],
    )
    led = ledger(
        [
            ledger_page(
                f"SPA-p{n}",
                "(Final) Share Purchase Agreement.pdf",
                n,
                SPA,
                [
                    ledger_block(
                        1,
                        party.upper(),
                        "signed",
                        date_field=False,
                        placed_in=f"{EXECUTED_NAME}#{n}",
                    )
                ],
            )
            for n, party in ((3, SELLER), (4, BUYER))
        ]
    )
    ledger_path = folder.json("sigpack.ledger.json", led)
    run = audit(
        checklist=checklist([("1.1", SPA, True)]), sigpack=led, sigpack_path=ledger_path
    )
    fam = run.family_of(executed)
    per_skill = record(
        fam,
        pick=executed,
        status="ready",
        execution_expected=True,
        apparent="appears-signed",
        dated="not-expected",
        signature_pages=[
            {"document_id": executed, "page": 3},
            {"document_id": executed, "page": 4},
        ],
        evidence=[
            evidence(
                "execution", "sigpack-ledger", p, "signed; no date field", executed
            )
            for p in ("SPA-p3", "SPA-p4")
        ],
    )
    result = run.reconcile([per_skill])
    # Two families: the SPA and the ledger's own file, set aside.
    assert result.receipt["inspection"] == {
        "families": 2,
        "inspected": 1,
        "rejected": 0,
    }
    item = result.item(SPA)
    assert item["status"] == "ready"
    assert item["execution"] == {
        "evidence_source": "sigpack-ledger",
        "apparent_status": "appears-signed",
        "dated": "not-expected",
        "ledger_page_ids": ["SPA-p3", "SPA-p4"],
    }
    assert item["document_date"] is None
    assert result.overview_doc(item["item_id"])["dating_unresolved"] is False
    assert result.receipt["outcome"] == "complete"

    paths = write_cli_inputs(run, out_dir, [per_skill])
    proc = run_cli(
        "reconcile",
        "--manifest",
        paths["manifest"],
        "--families",
        paths["families"],
        "--inspection",
        paths["inspection"],
        "--checklist",
        paths["checklist"],
        "--sigpack",
        ledger_path,
        "--root",
        folder.root,
        "--out-dir",
        out_dir,
        "--as-of",
        AS_OF,
    )
    assert "1 expected · 1 ready" in proc.stdout and "COMPLETE" in proc.stdout
    assert load(out_dir / "closing-index.json")["items"][0]["status"] == "ready"
    assert run_cli("status", "--out-dir", out_dir).stdout.strip() == proc.stdout.strip()


# --------------------------------------------------------------- defect 10


def test_10_a_ledger_that_fails_the_gate_is_no_phantom_item(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """[10] A non-current ledger sitting in the folder becomes a phantom
    expected item, reported 'missing', and fails the receipt. Now it
    contributes nothing, and its own file is still set aside by hash."""

    executed = folder.pdf(EXECUTED_REL, [cover(SPA), "terms", _both(CLOSING_DATE_TEXT)])
    stale = _spa_ledger(
        [
            ledger_block(
                1,
                SELLER.upper(),
                "signed",
                dated=CLOSING_DATE_TEXT,
                placed_in="(Executed) Something Else.pdf#2",
            )
        ]
    )
    stale["signature_pages"][0]["file"] = "Share Purchase Agreement v9.pdf"
    ledger_path = folder.json("sigpack.ledger.json", stale)
    run = audit(sigpack=stale, sigpack_path=ledger_path)  # no checklist
    result = run.reconcile([rec_signed(run.family_of(executed), executed, page=3)])
    assert result.receipt["sigpack"]["ledger_current"] is False
    assert [i["title"] for i in result.index["items"]] == [
        run.family_of(executed)["title_hint"]
    ]
    assert result.receipt["by_status"]["missing"] == 0
    assert result.index["unexpected_families"] == []
    assert result.line() == (
        "1 expected · 1 ready · 0 unsigned · 0 undated · 0 incomplete · "
        "0 version-conflict · 0 missing · 0 unreadable · 0 not-required · 0 unexpected · COMPLETE"
    )
    ledger_family = run.family_of(run.document("sigpack.ledger.json")["id"])
    plan = result.plan_family(ledger_family["family_id"])
    assert plan["resolved_status"] == "not-required" and plan["item_id"] is None
    assert "does not match the folder" in result.exceptions


# --------------------------------------------------------------- defect 11


def test_11_readability_is_per_document_and_unreadable_wins(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """[11] A zero-byte 'Escrow Agreement (Executed).pdf' the census marks
    corrupt reaches a ready item and a COMPLETE receipt with
    sources.unreadable 0 because readability is taken from the first path of
    the shared (empty) hash. Now: zero bytes is corrupt whatever the
    extension, every row of an id carries its worst readability, suspect
    counts as unreadable, and no unreadable id is ever selected."""

    for name in (
        "Board Minutes.txt",
        "Consent Letter.docx",
        "Escrow Agreement (Executed).pdf",
    ):
        (folder.root / name).write_bytes(b"")
    (folder.root / "Side Letter.html").write_text("<html><body>text with no close")
    run = audit(
        checklist=checklist(
            [("1", "Escrow Agreement", False), ("2", "Side Letter", True)]
        )
    )
    rows = [d for d in run.manifest["documents"] if d["bytes"] == 0]
    assert len(rows) == 3 and len({d["id"] for d in rows}) == 1
    assert {d["readability"] for d in rows} == {"corrupt"}
    assert run.manifest["counts"]["corrupt"] == 3
    assert run.document("Side Letter.html")["readability"] == "suspect"
    empty = rows[0]["id"]
    escrow = run.family_of(empty)
    claims_ready = rec_not_expected(escrow, empty)
    result = run.reconcile([claims_ready])
    assert result.receipt["inspection"]["rejected"] == 1
    assert f"the census marks {empty} as corrupt" in result.exceptions
    assert result.item("Escrow Agreement")["status"] == "unreadable"
    assert result.item("Escrow Agreement")["selected_id"] is None
    assert result.item("Side Letter")["status"] == "unreadable"
    assert result.receipt["sources"]["unreadable"] == 2
    assert result.receipt["outcome"] == "failed"
    assert all(i["status"] != "ready" for i in result.index["items"])
    # The rule holds when a hand-edited manifest disagrees with itself on readability.
    from closing_bible.reconcile import readability_by_id

    edited = json.loads(json.dumps(run.manifest))
    for d in edited["documents"]:
        if d["path"] == "Board Minutes.txt":
            d["readability"] = "native"
    assert readability_by_id(edited)[empty] == "corrupt"


# --------------------------------------------------------------- defect 12


def test_12_skipped_entries_are_listed_counted_and_keep_the_receipt_from_complete(
    folder: Folder, audit: Callable[..., Audit], out_dir: Path, tmp_path: Path
) -> None:
    """[12] Symlinked documents/folders and hidden entries are dropped from the
    census with no notice, so the receipt balances and reads COMPLETE while
    whole documents were never inventoried. Now every skipped entry is in the
    manifest with its reason, printed by census, named in exceptions.md,
    counted in sources.skipped, and the receipt is never complete."""

    dl = folder.pdf(
        "Disclosure Letter.pdf", [cover("DL"), "t", _both(CLOSING_DATE_TEXT)]
    )
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "Executed").mkdir(parents=True)
    (elsewhere / "Share Purchase Agreement (Executed).pdf").write_bytes(b"%PDF-1.4 x")
    os.symlink(
        elsewhere / "Share Purchase Agreement (Executed).pdf",
        folder.root / "Share Purchase Agreement (Executed).pdf",
    )
    os.symlink(elsewhere / "Executed", folder.root / "Executed")
    (folder.root / ".Executed").mkdir()
    (folder.root / ".Executed" / "Escrow Agreement (Executed).pdf").write_bytes(b"x")
    (folder.root / "._Escrow Agreement (Executed).pdf").write_bytes(b"x")
    run = audit(checklist=checklist([("1", "Disclosure Letter", True)]))
    assert run.manifest["counts"]["files"] == 1
    assert run.manifest["skipped"] == [
        {"path": ".Executed", "reason": "hidden"},
        {"path": "._Escrow Agreement (Executed).pdf", "reason": "hidden"},
        {"path": "Executed", "reason": "symlink-outside-root"},
        {
            "path": "Share Purchase Agreement (Executed).pdf",
            "reason": "symlink-outside-root",
        },
    ]
    result = run.reconcile([rec_signed(run.family_of(dl), dl, page=3)])
    # Two symlinks out of the folder count; the two hidden entries are listed
    # but are the operating system's, not the closing's (status-taxonomy.md).
    assert result.receipt["sources"]["skipped"] == 2
    assert result.receipt["by_status"]["ready"] == 1
    assert result.receipt["outcome"] == "qualified"
    not_inventoried = _section(result.exceptions, "Not inventoried")
    assert (
        "- Executed (symlink-outside-root): not inventoried by the census"
        in not_inventoried
    )
    assert "- .Executed (hidden)" in not_inventoried
    proc = run_cli(
        "census", "--root", folder.root, "--out", out_dir / "source-manifest.json"
    )
    assert "1 files · 1 distinct · 0 duplicate group(s) · 4 skipped" in proc.stdout
    assert "skipped: Executed (symlink-outside-root)" in proc.stdout
    assert "skipped: .Executed (hidden)" in proc.stdout
    assert (
        models.outcome_for(
            {s: 0 for s in models.RECEIPT_STATUSES} | {"ready": 1},
            0,
            {**result.receipt["sources"], "skipped": 1},
        )
        == "qualified"
    )


# --------------------------------------------------------------- defect 13


def test_13_a_manifest_that_disagrees_with_itself_is_refused(
    folder: Folder, audit: Callable[..., Audit], out_dir: Path
) -> None:
    """[13] source-manifest.json is trusted verbatim downstream: a document row
    deleted after census leaves corpus_id and counts intact and the receipt
    balances. Now families and reconcile re-derive corpus_id and check the
    counts, and refuse (exit 2) a manifest whose rows do not match."""

    from closing_bible import families as fam_mod

    spa = folder.pdf(
        "Share Purchase Agreement (Executed).pdf",
        [cover(SPA), "t", _both(CLOSING_DATE_TEXT)],
    )
    folder.pdf(
        "Side Letter (Executed).pdf",
        [cover("Side Letter"), "t", _both(CLOSING_DATE_TEXT)],
    )
    run = audit()
    edited = json.loads(json.dumps(run.manifest))
    edited["documents"] = [d for d in edited["documents"] if d["id"] == spa]
    with pytest.raises(ValueError, match="does not agree with itself"):
        fam_mod.build_families(edited)
    run.manifest = edited
    with pytest.raises(ValueError, match="does not agree with itself"):
        run.reconcile([rec_signed(run.family_of(spa), spa, page=3)])
    # Counts edited to match but corpus_id left alone: still refused.
    edited["counts"]["files"] = edited["counts"]["distinct"] = 1
    with pytest.raises(ValueError, match="corpus_id"):
        fam_mod.check_manifest(edited)
    (out_dir / "source-manifest.json").write_text(json.dumps(edited))
    proc = run_cli(
        "families",
        "--manifest",
        out_dir / "source-manifest.json",
        "--out",
        out_dir / "families.json",
        check=False,
    )
    assert proc.returncode == 2 and "does not agree with itself" in proc.stderr
    assert not (out_dir / "families.json").exists()


# --------------------------------------------------------------- defect 14


def test_14_the_ledger_is_set_aside_by_hash_never_by_family_title(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """[14] The ledger is excluded by family, not by hash: any document whose
    normalised title collides with the ledger's is silently recorded
    not-required and never listed as unexpected. Now exactly the document
    whose hash equals the supplied file is set aside; the stale copy and the
    misnamed PDF stay in the reconciliation as an unexpected family."""

    folder.pdf(
        "execution/Voting Agreement.pdf", [cover("Voting Agreement"), "t", BLANK_BLOCK]
    )
    executed = folder.pdf(
        "executed/(Executed) Voting Agreement.pdf",
        [cover("Voting Agreement"), "t", signed_page(date=CLOSING_DATE_TEXT)],
    )
    led = ledger(
        [
            ledger_page(
                "VA-p3",
                "Voting Agreement.pdf",
                3,
                "Voting Agreement",
                [
                    ledger_block(
                        1,
                        SELLER.upper(),
                        "signed",
                        dated=CLOSING_DATE_TEXT,
                        placed_in="(Executed) Voting Agreement.pdf#3",
                    )
                ],
            )
        ]
    )
    ledger_path = folder.json("sigpack.ledger.json", led)
    stale = json.loads(json.dumps(led))
    stale["receipt"]["as_of"] = "2026-02-28"
    folder.json("sigpack.ledger (2).json", stale)
    misnamed = folder.pdf(
        "Sigpack Ledger.pdf", ["This is actually a side letter someone misnamed"]
    )
    run = audit(sigpack=led, sigpack_path=ledger_path)
    ledger_id = run.document("sigpack.ledger.json")["id"]
    stale_id = run.document("sigpack.ledger (2).json")["id"]
    fam = run.family_of(ledger_id)
    assert set(fam["member_ids"]) == {ledger_id, stale_id, misnamed}  # grouped by title
    result = run.reconcile(
        [
            rec_signed(
                run.family_of(executed),
                executed,
                page=3,
                source="sigpack-ledger",
                locator="VA-p3",
            )
        ]
    )
    assert result.item("Voting Agreement")["status"] == "ready"
    [unexpected] = result.index["unexpected_families"]
    assert unexpected["family_id"] == fam["family_id"]
    assert unexpected["member_ids"] == sorted([stale_id, misnamed])
    assert ledger_id not in json.dumps(result.index)
    assert result.receipt["unexpected_families"] == 1
    assert result.receipt["outcome"] == "qualified"
    plan = result.plan_family(fam["family_id"])
    assert plan["resolved_status"] == "unexpected"
    assert plan["member_ids"] == sorted([stale_id, misnamed])
    assert (
        result.receipt["sources"]["in_families"]
        == result.receipt["sources"]["distinct"]
        == 5
    )
    notes = _section(result.exceptions, "Ledger notes")
    assert f"{ledger_id} in {fam['family_id']} is the ledger itself" in notes
    assert "Sigpack Ledger.pdf" in notes and "reconciled as documents" in notes
    assert fam["family_id"] in _section(result.exceptions, "Not inspected")
    # A record proposing the ledger file as a document is rejected by name.
    picks_ledger = rec_not_expected(fam, ledger_id)
    result = run.reconcile([picks_ledger])
    assert "is the sigpack ledger file itself" in result.exceptions


# --------------------------------------------- settlements from the same round


def test_checklist_changed_between_families_and_reconcile_is_refused(
    folder: Folder, audit: Callable[..., Audit], out_dir: Path
) -> None:
    """Checklist rows bind to families by bare ref, so a checklist edited
    between families and reconcile yields a complete receipt whose items
    select the wrong files. Now families.json records checklist_sha256 and
    reconcile refuses a checklist whose hash differs — API and CLI."""

    spa = folder.pdf(
        "(Executed) Share Purchase Agreement.pdf",
        [cover(SPA), "t", _both(CLOSING_DATE_TEXT)],
    )
    dl = folder.pdf(
        "Disclosure Letter.pdf",
        [cover("Disclosure Letter"), "t", _both(CLOSING_DATE_TEXT)],
    )
    rows = checklist([("1.1", SPA, True), ("1.2", "Disclosure Letter", True)])
    run = audit(checklist=rows)
    assert isinstance(run.families["checklist_sha256"], str)
    records = [
        rec_signed(run.family_of(spa), spa, page=3),
        rec_signed(run.family_of(dl), dl, page=3),
    ]
    assert run.reconcile(records).receipt["outcome"] == "complete"
    swapped = checklist([("1.2", SPA, True), ("1.1", "Disclosure Letter", True)])
    run.checklist = swapped
    with pytest.raises(
        ValueError, match="checklist changed between families and reconcile"
    ):
        run.reconcile(records)
    run.checklist = rows
    paths = write_cli_inputs(run, out_dir, records)
    paths["checklist"].write_text(json.dumps(swapped))
    proc = run_cli(
        "reconcile",
        "--manifest",
        paths["manifest"],
        "--families",
        paths["families"],
        "--inspection",
        paths["inspection"],
        "--checklist",
        paths["checklist"],
        "--out-dir",
        out_dir,
        "--as-of",
        AS_OF,
        check=False,
    )
    assert proc.returncode == 2 and "checklist" in proc.stderr
    assert not (out_dir / "closing-receipt.json").exists()
    # A checklist given to reconcile but never to families is refused too.
    bare = audit()
    bare.checklist = rows
    with pytest.raises(ValueError, match="built without one"):
        bare.reconcile(records)


def test_approved_index_for_another_corpus_is_refused(
    folder: Folder, audit: Callable[..., Audit], out_dir: Path
) -> None:
    """An approved --index from a different corpus_id is accepted silently
    and drives the expected set. Now it is refused, exit 2."""

    spa = folder.pdf(
        "(Executed) Share Purchase Agreement.pdf",
        [cover(SPA), "t", _both(CLOSING_DATE_TEXT)],
    )
    run = audit(checklist=checklist([("1.1", SPA, True)]))
    records = [rec_signed(run.family_of(spa), spa, page=3)]
    approved = json.loads(json.dumps(run.reconcile(records).index))
    approved["approved"] = True
    approved["corpus_id"] = "f" * 16
    with pytest.raises(ValueError, match="taken about other files"):
        run.reconcile(records, index=approved)
    paths = write_cli_inputs(run, out_dir, records)
    (out_dir / "approved.json").write_text(json.dumps(approved))
    proc = run_cli(
        "reconcile",
        "--manifest",
        paths["manifest"],
        "--families",
        paths["families"],
        "--inspection",
        paths["inspection"],
        "--checklist",
        paths["checklist"],
        "--index",
        out_dir / "approved.json",
        "--out-dir",
        out_dir,
        "--as-of",
        AS_OF,
        check=False,
    )
    assert proc.returncode == 2 and "corpus_id" in proc.stderr
    assert not (out_dir / "closing-receipt.json").exists()


def test_status_recomputes_the_receipt_and_refuses_an_edited_one(
    folder: Folder, audit: Callable[..., Audit], out_dir: Path
) -> None:
    """`status` prints complete from a hand-edited receipt that contradicts the
    closing-index.json beside it — only the arithmetic is checked. Now the
    receipt is recomputed from the index (and the manifest and families
    beside it) and a receipt that says otherwise is refused."""

    spa = folder.pdf(
        "(Executed) Share Purchase Agreement.pdf",
        [cover(SPA), "t", _both(CLOSING_DATE_TEXT)],
    )
    run = audit(
        checklist=checklist([("1.1", SPA, True), ("1.2", "Landlord Consent", True)])
    )
    paths = write_cli_inputs(
        run, out_dir, [rec_signed(run.family_of(spa), spa, page=3)]
    )
    run_cli(
        "reconcile",
        "--manifest",
        paths["manifest"],
        "--families",
        paths["families"],
        "--inspection",
        paths["inspection"],
        "--checklist",
        paths["checklist"],
        "--out-dir",
        out_dir,
        "--as-of",
        AS_OF,
    )
    honest = run_cli("status", "--out-dir", out_dir).stdout
    assert "1 missing" in honest and "FAILED" in honest
    receipt = load(out_dir / "closing-receipt.json")
    receipt["by_status"]["missing"] = 0
    receipt["by_status"]["ready"] = 2
    receipt["outcome"] = "complete"
    (out_dir / "closing-receipt.json").write_text(json.dumps(receipt))
    proc = run_cli("status", "--out-dir", out_dir, check=False)
    assert proc.returncode == 2
    assert "does not match the outputs beside it" in proc.stderr
    assert "by_status" in proc.stderr
    assert "COMPLETE" not in proc.stdout


def test_empty_expected_set_fails(folder: Folder, audit: Callable[..., Audit]) -> None:
    """An empty closing folder (no checklist) produces `0 expected · complete`
    and a proposed index that 'stands on its own'. Now it fails: nothing to
    audit is not a clean closing."""

    result = audit().reconcile([])
    assert result.receipt["expected_items"] == 0
    assert result.receipt["outcome"] == "failed"
    assert result.line().endswith("· FAILED")


def test_as_of_must_be_a_real_date(
    folder: Folder, audit: Callable[..., Audit], out_dir: Path
) -> None:
    """--as-of 2026-99-99 accepted. Now the API and the CLI refuse it plainly."""

    spa = folder.pdf(
        "(Executed) Share Purchase Agreement.pdf",
        [cover(SPA), "t", _both(CLOSING_DATE_TEXT)],
    )
    run = audit(checklist=checklist([("1.1", SPA, True)]))
    records = [rec_signed(run.family_of(spa), spa, page=3)]
    with pytest.raises(ValueError, match="not a real date"):
        run.reconcile(records, as_of="2026-99-99")
    paths = write_cli_inputs(run, out_dir, records)
    proc = run_cli(
        "reconcile",
        "--manifest",
        paths["manifest"],
        "--families",
        paths["families"],
        "--inspection",
        paths["inspection"],
        "--checklist",
        paths["checklist"],
        "--out-dir",
        out_dir,
        "--as-of",
        "2026-99-99",
        check=False,
    )
    assert proc.returncode == 2
    assert "--as-of '2026-99-99' is not a real date" in proc.stderr
    assert not (out_dir / "closing-receipt.json").exists()


def test_unexpected_family_nobody_inspected_is_named_under_not_inspected(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """A side letter not on the checklist and never inspected is listed as
    unexpected but absent from 'Not inspected'. Now it is named there too."""

    spa = folder.pdf(
        "(Executed) Share Purchase Agreement.pdf",
        [cover(SPA), "t", _both(CLOSING_DATE_TEXT)],
    )
    side = folder.pdf(
        "Side Letter re Earn-out.pdf", [cover("Side Letter"), "t", _both(None)]
    )
    run = audit(checklist=checklist([("1.1", SPA, True)]))
    result = run.reconcile([rec_signed(run.family_of(spa), spa, page=3)])
    side_family = run.family_of(side)["family_id"]
    assert [u["family_id"] for u in result.index["unexpected_families"]] == [
        side_family
    ]
    assert (
        f"- {side_family} side letter re earn out: unexpected and no valid inspection record"
        in _section(result.exceptions, "Not inspected")
    )
    # Once inspected, it leaves that section but stays unexpected.
    result = run.reconcile(
        [
            rec_signed(run.family_of(spa), spa, page=3),
            rec_signed(run.family_of(side), side, page=3, date=None),
        ]
    )
    assert side_family not in _section(result.exceptions, "Not inspected")
    assert result.receipt["unexpected_families"] == 1


# ---------------------------------------------------------- round 2 (single probe)


def test_r2_placed_in_page_zero_is_no_page(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """A placed_in of "…#0" must not write page 0 into the overview; the schema
    wants 1 or more, so an unparseable page number reads as unknown (null)."""

    folder.pdf(EXECUTION_REL, [cover(SPA), "terms", BLANK_BLOCK])
    spa = folder.pdf(EXECUTED_REL, [cover(SPA), "terms", _both(CLOSING_DATE_TEXT)])
    led = _spa_ledger(
        [
            ledger_block(
                1,
                SELLER.upper(),
                "signed",
                dated=CLOSING_DATE_TEXT,
                placed_in=f"{EXECUTED_NAME}#0",
            )
        ]
    )
    run = audit(checklist=checklist([("1.1", SPA, True)]), sigpack=led)
    result = run.reconcile([rec_signed(run.family_of(spa), spa, page=3)])
    pages = result.overview_doc(result.item(SPA)["item_id"])["signature_pages"]
    assert all(p["page"] is None or p["page"] >= 1 for p in pages)


def test_r2_index_that_is_not_a_closing_index_is_refused(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """Passing the checklist file as --index by mistake is refused with a plain
    hint, never silently run through."""

    dl = folder.pdf("Disclosure Letter.pdf", [cover("DL"), "t"])
    run = audit(checklist=checklist([("1", "Disclosure Letter", False)]))
    with pytest.raises(ValueError, match="not a closing-index.json.*--checklist"):
        run.reconcile(
            [rec_not_expected(run.family_of(dl), dl)],
            index={
                "matter": "x",
                "items": [{"ref": "1", "title": "DL", "execution_expected": False}],
            },
        )
