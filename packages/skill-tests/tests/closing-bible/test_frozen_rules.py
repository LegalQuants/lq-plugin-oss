"""Anchor A2: one test per rule in references/status-taxonomy.md, "Rules that
do not move". Each fails if the rule is weakened. Rules 1, 2, 5 and 7 bite in
models.py; rules 3, 4 and 6 bite in the census/reconcile behaviour and the
CLI (rule 6 doubles as anchor A4, rule 7's CLI half as anchor A5)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

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
    hash_tree,
    ledger,
    ledger_block,
    ledger_page,
    load,
    rec_conflict,
    rec_signed,
    run_cli,
    signed_page,
)
from closing_bible import models

FAM = "fam_" + "0" * 12
DOC = "sha256:" + "a" * 12
SPA = "Share Purchase Agreement"


def _finding(
    apparent: str, dated: str, date: str | None = None
) -> models.ExecutionFinding:
    return models.ExecutionFinding(
        apparent_status=apparent, dated=dated, document_date=date
    )


def _agreement(
    folder: Folder,
    rel: str,
    title: str,
    *,
    signed: bool = True,
    date: str | None = CLOSING_DATE_TEXT,
) -> str:
    execution = (
        signed_page(party=SELLER, date=date)
        + "\n"
        + signed_page(party=BUYER, date=date)
        if signed
        else f"SIGNED by ______________\nfor and on behalf of {SELLER}\nDated: ______________"
    )
    return folder.pdf(
        rel, [cover(title), f"1. Definitions\n2. {title} operative terms.", execution]
    )


# ----------------------------------------------------------------- rule 1


def test_rule_1_filename_is_not_evidence() -> None:
    # A filename may speak to version or identity, nothing else.
    models.Evidence("version", "filename", DOC, "(Final) SPA.pdf", "marked final")
    models.Evidence("identity", "filename", DOC, "SPA.pdf", "named as the SPA")
    for claim in ("execution", "date", "completeness"):
        with pytest.raises(ValueError, match="rule 1|rules 1 and 3"):
            models.Evidence(
                claim, "filename", DOC, "(Executed) SPA.pdf", "says executed"
            )
    # Execution evidence needs the ledger or a look at the page — not a text
    # extraction, not the checklist.
    for source in ("text-extraction", "checklist"):
        with pytest.raises(ValueError, match="rules 1 and 3"):
            models.Evidence("execution", source, DOC, "page 3", "signed")
    # appears-signed on a filename alone is rejected, with the rule named.
    filename_only = (
        models.Evidence(
            "version", "filename", DOC, "(Executed) SPA.pdf", "says executed"
        ),
    )
    with pytest.raises(ValueError, match="rule 1"):
        models.FamilyInspection(
            family_id=FAM,
            member_ids=(DOC,),
            proposed_pick=DOC,
            proposed_status="ready",
            execution_expected=True,
            execution=_finding("appears-signed", "dated", CLOSING_DATE_TEXT),
            evidence=filename_only,
        )
    # The same record with a visual-inspection execution record (and the date
    # record `dated` needs under rule 3) is accepted.
    looked = filename_only + (
        models.Evidence(
            "execution", "visual-inspection", DOC, "page 3", "signed by both"
        ),
        models.Evidence(
            "date", "visual-inspection", DOC, "page 3", f"dated {CLOSING_DATE_TEXT}"
        ),
    )
    accepted = models.FamilyInspection(
        family_id=FAM,
        member_ids=(DOC,),
        proposed_pick=DOC,
        proposed_status="ready",
        execution_expected=True,
        execution=_finding("appears-signed", "dated", CLOSING_DATE_TEXT),
        evidence=looked,
    )
    assert accepted.derived_status() == "ready"
    # And an index row cannot be ready with no execution evidence source.
    with pytest.raises(ValueError, match="rule 1"):
        models.IndexItem(
            item_id="CB-001",
            order=1,
            title=SPA,
            checklist_ref="1.1",
            execution_expected=True,
            status="ready",
            family_id=FAM,
            selected_id=DOC,
            execution=models.ExecutionRecord("none", "appears-signed", "dated"),
        )


# ----------------------------------------------------------------- rule 2


def test_rule_2_version_conflict_is_a_stop(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    # In the model: no pick may ride on a version-conflict, in either artifact.
    with pytest.raises(ValueError, match="rule 2"):
        models.FamilyInspection(
            family_id=FAM,
            member_ids=(DOC,),
            proposed_pick=DOC,
            proposed_status="version-conflict",
            execution_expected=True,
            execution=_finding("appears-signed", "dated", CLOSING_DATE_TEXT),
            evidence=(
                models.Evidence("execution", "visual-inspection", DOC, "p3", "signed"),
            ),
        )
    with pytest.raises(ValueError, match="rule 2"):
        models.IndexItem(
            item_id="CB-001",
            order=1,
            title=SPA,
            checklist_ref="1.1",
            execution_expected=True,
            status="version-conflict",
            family_id=FAM,
            selected_id=DOC,
            execution=models.ExecutionRecord(
                "visual-inspection", "appears-signed", "dated"
            ),
            qualification="two plausible finals",
        )
    # In the behaviour: the family stops, nothing is selected anywhere.
    a = _agreement(folder, "(Final) Escrow Agreement.pdf", "Escrow Agreement")
    b = folder.pdf(
        "(Executed) Escrow Agreement.pdf",
        [
            cover("Escrow Agreement"),
            "Clause 5 amended.",
            signed_page(party=SELLER, date=CLOSING_DATE_TEXT),
        ],
    )
    run = audit(checklist=checklist([("1", "Escrow Agreement", True)]))
    fam = run.family_of(a)
    assert set(fam["member_ids"]) == {a, b}
    result = run.reconcile(
        [rec_conflict(fam, "both carry signatures and the same date; clause 5 differs")]
    )
    item = result.item("Escrow Agreement")
    assert item["status"] == "version-conflict"
    assert item["selected_id"] is None
    assert item["family_id"] == fam["family_id"]
    plan = result.plan_family(fam["family_id"])
    assert plan["resolved_status"] == "version-conflict"
    assert plan["selected_id"] is None
    assert result.receipt["by_status"]["version-conflict"] == 1
    assert result.receipt["outcome"] == "qualified"
    assert result.receipt["included_outputs"] == []


# ----------------------------------------------------------------- rule 3


def test_rule_3_timestamps_are_not_dates(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    # A date in the filename and an old mtime, but the execution page has no date.
    rel = "Share Purchase Agreement signed 2026-03-01.pdf"
    doc = folder.pdf(
        rel,
        [cover(SPA), "operative terms", signed_page(party=SELLER, date=None)],
        mtime="2023-11-14T09:00:00",
    )
    run = audit(checklist=checklist([("1.1", SPA, True)]))
    fam = run.family_of(doc)
    result = run.reconcile(
        [
            rec_signed(
                fam,
                doc,
                page=3,
                date=None,
                extra_evidence=[
                    evidence(
                        "version",
                        "filename",
                        rel,
                        "filename carries 'signed' and a date",
                        doc,
                    )
                ],
            )
        ]
    )
    item = result.item(SPA)
    assert item["status"] == "undated"
    assert item["document_date"] is None
    assert item["execution"]["dated"] == "undated"
    doc_view = result.overview_doc(item["item_id"])
    assert doc_view["document_date"] is None
    assert doc_view["dating_unresolved"] is True
    # Nothing in any artifact turns the filename date or the mtime into a date.
    everything = json.dumps(
        [result.index, result.plan, result.overview, result.receipt]
    )
    for forbidden in ("2026-03-01", "2023-11-14"):
        assert forbidden not in everything.replace(rel, ""), forbidden
    assert result.receipt["as_of"] == AS_OF  # only the explicit --as-of
    # And the model refuses a date claim sourced from a filename.
    with pytest.raises(ValueError, match="rules 1 and 3"):
        models.Evidence("date", "filename", doc, rel, "filename says 2026-03-01")


# ----------------------------------------------------------------- rule 4


def test_rule_4_ledger_is_authoritative_and_never_reclassified(
    folder: Folder, audit: Callable[..., Audit], tmp_path: Path
) -> None:
    # Ledger: block 1 signed, block 2 came back blank. Only the execution
    # version is in the folder (sigpack has not compiled), which passes the gate.
    exec_rel = "execution/(Final) Share Purchase Agreement.pdf"
    doc = _agreement(folder, exec_rel, SPA, signed=False)
    led = ledger(
        [
            ledger_page(
                "SPA-p3",
                "(Final) Share Purchase Agreement.pdf",
                3,
                SPA,
                [
                    ledger_block(1, SELLER.upper(), "signed", dated=CLOSING_DATE_TEXT),
                    ledger_block(2, BUYER.upper(), "blank"),
                ],
            )
        ]
    )
    ledger_path = tmp_path / "sigpack.ledger.json"
    ledger_path.write_text(json.dumps(led, indent=2, sort_keys=True))
    ledger_bytes = ledger_path.read_bytes()
    run = audit(
        checklist=checklist([("1.1", SPA, True)]), sigpack=led, sigpack_dir=folder.root
    )
    fam = run.family_of(doc)
    # The inspection record cites the ledger but contradicts it: says signed, ready.
    lying = rec_signed(fam, doc, page=3, source="sigpack-ledger", locator="SPA-p3")
    result = run.reconcile([lying])
    # Rejected and counted; never absorbed.
    assert result.receipt["inspection"]["rejected"] == 1
    assert result.receipt["inspection"]["inspected"] == 0
    assert fam["family_id"] in result.exceptions
    # The ledger's block statuses are what every output shows, verbatim.
    item = result.item(SPA)
    assert item["status"] == "unsigned"
    assert item["execution"]["evidence_source"] == "sigpack-ledger"
    assert item["execution"]["apparent_status"] == "appears-incomplete"
    assert item["execution"]["ledger_page_ids"] == ["SPA-p3"]
    doc_view = result.overview_doc(item["item_id"])
    assert [b["status"] for b in doc_view["blocks"]] == ["signed", "blank"]
    assert [b["party"] for b in doc_view["blocks"]] == [SELLER.upper(), BUYER.upper()]
    assert f"block 2 (`{BUYER.upper()}`) not signed" in doc_view["exceptions"]
    assert result.overview["sigpack"]["ledger_current"] is True
    assert result.overview["sigpack"]["ledger_receipt"] == led["receipt"]
    assert result.receipt["sigpack"] == {
        "ledger_supplied": True,
        "ledger_current": True,
        "documents_cited": 1,
    }
    assert result.receipt["by_status"]["ready"] == 0
    # Read-only consumer: the ledger on disk and the dict handed in are untouched.
    assert ledger_path.read_bytes() == ledger_bytes
    assert led == json.loads(ledger_bytes)


def test_rule_4_ledger_citation_without_a_ledger_is_not_evidence(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    # The record's only execution evidence cites a sigpack ledger, but no
    # ledger was supplied: an unverified citation cannot make the item ready
    # (rules 1 and 4). It lands unsigned, and says why.
    doc = _agreement(folder, "(Executed) Share Purchase Agreement.pdf", SPA)
    run = audit(checklist=checklist([("1.1", SPA, True)]))
    fam = run.family_of(doc)
    citing = rec_signed(fam, doc, page=3, source="sigpack-ledger", locator="SPA-p3")
    result = run.reconcile([citing])
    item = result.item(SPA)
    assert item["status"] == "unsigned"
    assert item["selected_id"] == doc
    assert item["execution"]["evidence_source"] == "none"
    assert item["execution"]["ledger_page_ids"] == []
    assert item["document_date"] is None
    assert "sigpack ledger" in item["qualification"]
    assert "not supplied" in item["qualification"]
    assert result.receipt["sigpack"] == {
        "ledger_supplied": False,
        "ledger_current": None,
        "documents_cited": 0,
    }
    assert result.receipt["by_status"]["ready"] == 0
    assert result.receipt["outcome"] == "qualified"
    assert SPA in result.exceptions and "not supplied" in result.exceptions


# ----------------------------------------------------------------- rule 5


def test_rule_5_never_infer_authority_or_delivery(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    # The vocabulary is qualified: nothing in the model says "valid" or "executed".
    for word in models.APPARENT_STATUSES:
        assert "valid" not in word and "executed" not in word and "deliver" not in word
    assert {
        "appears-signed",
        "appears-incomplete",
        "appears-unsigned",
        "unclear",
    } < models.APPARENT_STATUSES
    # A ready, signed document produces no claim of due execution, authority
    # or delivery anywhere in the outputs.
    doc = _agreement(folder, "(Executed) Share Purchase Agreement.pdf", SPA)
    run = audit(checklist=checklist([("1.1", SPA, True)]))
    result = run.reconcile([rec_signed(run.family_of(doc), doc, page=3)])
    assert result.item(SPA)["status"] == "ready"
    lowered = result.all_text().lower()
    for forbidden in (
        "validly executed",
        "duly executed",
        "valid execution",
        "due execution",
        "duly authorised",
        "duly authorized",
        "has authority",
        "delivered",
    ):
        assert forbidden not in lowered, forbidden


# ----------------------------------------------------------------- rule 6


def test_rule_6_nothing_deleted_renamed_moved_or_overwritten(
    folder: Folder, out_dir: Path, tmp_path: Path
) -> None:
    """Anchor A4: the tree hash is identical before and after every CLI command."""

    doc = _agreement(folder, "(Executed) Share Purchase Agreement.pdf", SPA)
    folder.copy_of("(Executed) Share Purchase Agreement.pdf", "scans/SPA scan copy.pdf")
    folder.pdf(
        "(Draft) Share Purchase Agreement v2.pdf", [cover(SPA) + "\nDRAFT", "terms"]
    )
    folder.pdf("Tax Deed.pdf", ["TAX DEED"], encrypt=True)
    folder.pdf("Escrow Agreement.pdf", ["ESCROW"], corrupt=True)
    checklist_path = tmp_path / "checklist.json"
    checklist_path.write_text(json.dumps(checklist([("1.1", SPA, True)])))
    before = hash_tree(folder.root)
    mtimes_before = {
        p: p.stat().st_mtime_ns for p in folder.root.rglob("*") if p.is_file()
    }

    run_cli("census", "--root", folder.root, "--out", out_dir / "source-manifest.json")
    assert hash_tree(folder.root) == before, "census touched the source tree"

    run_cli(
        "families",
        "--manifest",
        out_dir / "source-manifest.json",
        "--out",
        out_dir / "families.json",
        "--checklist",
        checklist_path,
    )
    assert hash_tree(folder.root) == before, "families touched the source tree"

    manifest = load(out_dir / "source-manifest.json")
    fams = load(out_dir / "families.json")
    spa = next(f for f in fams["families"] if doc in f["member_ids"])
    (out_dir / "inspection.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "corpus_id": manifest["corpus_id"],
                "families": [rec_signed(spa, doc, page=3)],
            }
        )
    )
    proc = run_cli(
        "reconcile",
        "--manifest",
        out_dir / "source-manifest.json",
        "--families",
        out_dir / "families.json",
        "--inspection",
        out_dir / "inspection.json",
        "--out-dir",
        out_dir,
        "--as-of",
        AS_OF,
        check=False,
    )
    # Two unreadable sources fail the receipt; that is a written receipt, not a crash.
    assert proc.returncode in (0, 1), proc.stderr
    assert hash_tree(folder.root) == before, "reconcile touched the source tree"
    assert (out_dir / "closing-receipt.json").exists()

    proc = run_cli("status", "--out-dir", out_dir, check=False)
    assert proc.returncode in (0, 1), proc.stderr
    assert hash_tree(folder.root) == before, "status touched the source tree"
    assert {
        p: p.stat().st_mtime_ns for p in folder.root.rglob("*") if p.is_file()
    } == mtimes_before

    # Duplicates are grouped, never removed: both paths are still there.
    assert (
        set(hash_tree(folder.root))
        == set(before)
        == {
            "(Executed) Share Purchase Agreement.pdf",
            "scans/SPA scan copy.pdf",
            "(Draft) Share Purchase Agreement v2.pdf",
            "Tax Deed.pdf",
            "Escrow Agreement.pdf",
        }
    )
    assert manifest["counts"]["files"] == 5
    assert manifest["counts"]["distinct"] == 4
    assert [g["id"] for g in manifest["duplicate_groups"]] == [doc]
    receipt = load(out_dir / "closing-receipt.json")
    assert receipt["sources"]["files"] == 5
    assert receipt["sources"]["distinct"] == 4
    assert receipt["sources"]["duplicates"] == 1
    # Every output landed in --out-dir, and no artifact carries an absolute path.
    written = {p.name for p in out_dir.iterdir()}
    assert {
        "closing-index.json",
        "selection-plan.json",
        "execution-overview.json",
        "closing-receipt.json",
        "exceptions.md",
    } <= written
    for name in written:
        if name.endswith((".json", ".md")):
            assert str(tmp_path) not in (out_dir / name).read_text(), name


def test_rule_6_output_inside_the_closing_folder_is_refused(
    folder: Folder, out_dir: Path
) -> None:
    """Rule 6 at the CLI: with `--root` given, `families --out` and
    `reconcile --out-dir` inside the closing folder exit 2 and write nothing
    under it; `--allow-outside` is the only override (README "Fixed surface")."""

    doc = _agreement(folder, "(Executed) Share Purchase Agreement.pdf", SPA)
    before = hash_tree(folder.root)
    run_cli("census", "--root", folder.root, "--out", out_dir / "source-manifest.json")

    proc = run_cli(
        "families",
        "--manifest",
        out_dir / "source-manifest.json",
        "--out",
        folder.root / "audit" / "families.json",
        "--root",
        folder.root,
        check=False,
    )
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "inside the closing folder" in proc.stderr
    assert not (folder.root / "audit").exists()
    assert hash_tree(folder.root) == before

    run_cli(
        "families",
        "--manifest",
        out_dir / "source-manifest.json",
        "--out",
        out_dir / "families.json",
        "--root",
        folder.root,
    )
    manifest = load(out_dir / "source-manifest.json")
    fams = load(out_dir / "families.json")
    spa = next(f for f in fams["families"] if doc in f["member_ids"])
    (out_dir / "inspection.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "corpus_id": manifest["corpus_id"],
                "families": [rec_signed(spa, doc, page=3)],
            }
        )
    )
    args = (
        "reconcile",
        "--manifest",
        out_dir / "source-manifest.json",
        "--families",
        out_dir / "families.json",
        "--inspection",
        out_dir / "inspection.json",
        "--out-dir",
        folder.root / "audit",
        "--root",
        folder.root,
        "--as-of",
        AS_OF,
    )
    proc = run_cli(*args, check=False)
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "inside the closing folder" in proc.stderr
    assert not (folder.root / "audit").exists()
    assert hash_tree(folder.root) == before

    proc = run_cli(*args, "--allow-outside", check=False)
    assert proc.returncode == 0, proc.stderr
    assert (folder.root / "audit" / "closing-receipt.json").exists()


# ----------------------------------------------------------------- rule 7


def _receipt(**overrides: object) -> models.Receipt:
    base: dict = {
        "corpus_id": "0" * 16,
        "mode": "audit",
        "index_approved": False,
        "expected_items": 3,
        "by_status": {s: 0 for s in models.RECEIPT_STATUSES} | {"ready": 3},
        "unexpected_families": 0,
        "sources": {
            "files": 4,
            "distinct": 3,
            "in_families": 3,
            "duplicates": 1,
            "unreadable": 0,
            "skipped": 0,
        },
        "inspection": {"families": 3, "inspected": 3, "rejected": 0},
        "sigpack": {
            "ledger_supplied": False,
            "ledger_current": None,
            "documents_cited": 0,
        },
        "as_of": AS_OF,
    }
    base.update(overrides)
    return models.Receipt(**base)


def test_rule_7_receipt_balances_or_is_not_written(
    folder: Folder, out_dir: Path
) -> None:
    # Balanced: complete, and the line reads like sigpack's.
    ok = _receipt()
    assert ok.outcome == "complete"
    assert ok.line() == (
        "3 expected · 3 ready · 0 unsigned · 0 undated · 0 incomplete · "
        "0 version-conflict · 0 missing · 0 unreadable · 0 not-required · 0 unexpected · COMPLETE"
    )
    # expected_items must equal the sum by status.
    with pytest.raises(ValueError, match="rule 7"):
        _receipt(expected_items=4)
    # Every distinct source sits in exactly one family.
    with pytest.raises(ValueError, match="rule 7"):
        _receipt(
            sources={
                "files": 4,
                "distinct": 3,
                "in_families": 2,
                "duplicates": 1,
                "unreadable": 0,
                "skipped": 0,
            }
        )
    # duplicates = files - distinct.
    with pytest.raises(ValueError, match="rule 7"):
        _receipt(
            sources={
                "files": 4,
                "distinct": 3,
                "in_families": 3,
                "duplicates": 0,
                "unreadable": 0,
                "skipped": 0,
            }
        )
    # Outcome is derived from the counts, never chosen.
    counts = {s: 0 for s in models.RECEIPT_STATUSES}
    assert (
        models.outcome_for(counts | {"ready": 2, "missing": 1}, 0, ok.sources)
        == "failed"
    )
    assert (
        models.outcome_for(counts | {"ready": 2, "unreadable": 1}, 0, ok.sources)
        == "failed"
    )
    assert (
        models.outcome_for(counts | {"ready": 3}, 0, {**ok.sources, "unreadable": 1})
        == "failed"
    )
    assert (
        models.outcome_for(counts | {"ready": 2, "unsigned": 1}, 0, ok.sources)
        == "qualified"
    )
    assert (
        models.outcome_for(counts | {"ready": 2, "version-conflict": 1}, 0, ok.sources)
        == "qualified"
    )
    assert models.outcome_for(counts | {"ready": 3}, 1, ok.sources) == "qualified"
    assert (
        models.outcome_for(counts | {"ready": 2, "not-required": 1}, 0, ok.sources)
        == "complete"
    )
    assert _receipt(by_status=counts | {"ready": 2, "missing": 1}).outcome == "failed"

    # Anchor A5: an unbalanced state injected on disk — a families.json that
    # leaves one distinct document in no family — makes the script exit 2 and
    # write no receipt.
    doc = _agreement(folder, "(Executed) Share Purchase Agreement.pdf", SPA)
    folder.pdf("Schedule 1.pdf", ["SCHEDULE 1\nProperties"])
    run_cli("census", "--root", folder.root, "--out", out_dir / "source-manifest.json")
    run_cli(
        "families",
        "--manifest",
        out_dir / "source-manifest.json",
        "--out",
        out_dir / "families.json",
    )
    manifest = load(out_dir / "source-manifest.json")
    fams = load(out_dir / "families.json")
    assert fams["counts"]["in_families"] == fams["counts"]["distinct_documents"] == 2
    spa = next(f for f in fams["families"] if doc in f["member_ids"])
    fams["families"] = [
        spa
    ]  # Schedule 1 now sits in no family; counts left as they were
    (out_dir / "families.json").write_text(json.dumps(fams))
    (out_dir / "inspection.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "corpus_id": manifest["corpus_id"],
                "families": [rec_signed(spa, doc, page=3)],
            }
        )
    )
    proc = run_cli(
        "reconcile",
        "--manifest",
        out_dir / "source-manifest.json",
        "--families",
        out_dir / "families.json",
        "--inspection",
        out_dir / "inspection.json",
        "--out-dir",
        out_dir,
        "--as-of",
        AS_OF,
        check=False,
    )
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert not (out_dir / "closing-receipt.json").exists()
    assert not (out_dir / "closing-index.json").exists()
