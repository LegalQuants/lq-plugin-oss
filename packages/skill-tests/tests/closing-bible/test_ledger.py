"""How a sigpack ledger is read, and what it may and may not decide
(references/sigpack-ledger-consumption.md; status-taxonomy.md rule 4 and
"Not inspected"). Rows 8–10 of the matrix cover the happy paths; these pin
the edges an adversarial reviewer found."""

from __future__ import annotations

import json
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
    rec_signed,
    record,
    run_cli,
    signed_page,
    write_cli_inputs,
)

SPA = "Share Purchase Agreement"
DL = "Disclosure Letter"
EXECUTION_REL = "execution/(Final) Share Purchase Agreement.pdf"
EXECUTED_REL = "executed/(Executed) Share Purchase Agreement.pdf"
PLACED = "(Executed) Share Purchase Agreement.pdf#3"


def _both(date: str | None) -> str:
    return (
        signed_page(party=SELLER, date=date)
        + "\n"
        + signed_page(party=BUYER, date=date)
    )


def _spa_ledger(
    *, block2: str = "signed", placed: str | None = PLACED, chosen: bool = True
) -> dict[str, Any]:
    blocks = [
        ledger_block(
            1, SELLER.upper(), "signed", dated=CLOSING_DATE_TEXT, placed_in=placed
        ),
        ledger_block(
            2,
            BUYER.upper(),
            block2,
            dated=CLOSING_DATE_TEXT if block2 == "signed" else None,
            placed_in=placed if block2 == "signed" else None,
        ),
    ]
    for block in blocks:
        for ret in block["returned"]:
            ret["chosen"] = chosen
    return ledger(
        [ledger_page("SPA-p3", "(Final) Share Purchase Agreement.pdf", 3, SPA, blocks)]
    )


@pytest.fixture
def two_versions(folder: Folder) -> tuple[str, str]:
    """The unsigned execution version and the executed compilation, one family."""

    execution = folder.pdf(EXECUTION_REL, [cover(SPA), "terms", _both(None)])
    executed = folder.pdf(EXECUTED_REL, [cover(SPA), "terms", _both(CLOSING_DATE_TEXT)])
    return execution, executed


# --------------------------------------------------- not inspected, two members


def test_uninspected_multi_member_family_has_no_pick_even_with_placed_in(
    two_versions: tuple[str, str], audit: Callable[..., Audit]
) -> None:
    """status-taxonomy.md "Not inspected": several members and no look is
    `version-conflict` — not even a ledger `placed_in` naming one member picks
    it, because the ledger speaks to execution, not to which version is final."""

    execution, executed = two_versions
    run = audit(checklist=checklist([("1.1", SPA, True)]), sigpack=_spa_ledger())
    fam = run.family_of(executed)
    assert set(fam["member_ids"]) == {execution, executed}
    result = run.reconcile([])
    item = result.item(SPA)
    assert item["status"] == "version-conflict"
    assert item["selected_id"] is None
    assert item["qualification"] == (
        "not inspected; 2 versions in the folder and none can be selected without a look"
    )
    assert item["execution"]["evidence_source"] == "none"
    assert result.plan_family(fam["family_id"])["selected_id"] is None
    assert result.receipt["inspection"] == {
        "families": 1,
        "inspected": 0,
        "rejected": 0,
    }
    assert result.receipt["sigpack"]["documents_cited"] == 0
    assert result.receipt["by_status"]["version-conflict"] == 1
    assert SPA in result.exceptions and "Not inspected" in result.exceptions


# ------------------------------------------------------ citations are checked


def test_ledger_citation_of_a_page_the_ledger_does_not_hold_is_rejected(
    two_versions: tuple[str, str], audit: Callable[..., Audit]
) -> None:
    """A `sigpack-ledger` evidence locator is a ledger page id
    (inspection.schema.json). One the ledger does not hold for this family is
    not a citation: the record is rejected, counted, and its invented locator
    reaches no artifact."""

    _, executed = two_versions
    run = audit(checklist=checklist([("1.1", SPA, True)]), sigpack=_spa_ledger())
    fam = run.family_of(executed)
    fake = rec_signed(fam, executed, page=3, source="sigpack-ledger", locator="XYZ-p99")
    result = run.reconcile([fake])
    assert result.receipt["inspection"] == {
        "families": 1,
        "inspected": 0,
        "rejected": 1,
    }
    assert (
        f"- CB-001 {fam['family_id']}: cites sigpack ledger page(s) XYZ-p99 that the "
        "ledger does not hold for this family (its pages: SPA-p3)"
    ) in result.exceptions
    assert result.item(SPA)["status"] == "version-conflict"  # not inspected, 2 members
    for artifact in (result.index, result.plan, result.overview):
        assert "XYZ-p99" not in json.dumps(artifact)


def test_ledger_citing_record_for_the_wrong_file_says_so(
    two_versions: tuple[str, str], audit: Callable[..., Audit]
) -> None:
    """The record picks the unsigned execution version and truthfully reports
    what the ledger says (appears-signed). It is rejected — the ledger speaks
    about the executed compilation, not the pick — and the reason says that,
    not that the ledger reads unsigned."""

    execution, _ = two_versions
    run = audit(checklist=checklist([("1.1", SPA, True)]), sigpack=_spa_ledger())
    fam = run.family_of(execution)
    wrong_file = rec_signed(
        fam, execution, page=3, source="sigpack-ledger", locator="SPA-p3"
    )
    result = run.reconcile([wrong_file])
    assert result.receipt["inspection"]["rejected"] == 1
    [line] = [
        line
        for line in result.exceptions.splitlines()
        if line.startswith(f"- CB-001 {fam['family_id']}: cites the sigpack ledger")
    ]
    assert "not the executed compilation the ledger placed its pages into" in line
    assert "The ledger speaks about the executed file" in line
    assert "the ledger reads appears-unsigned" not in line


# ------------------------------------------------------ what is read, and not


@pytest.mark.parametrize("chosen", [True, False], ids=["chosen", "not-chosen"])
def test_only_the_chosen_return_is_read(
    folder: Folder, audit: Callable[..., Audit], chosen: bool
) -> None:
    """sigpack-ledger-consumption.md "Fields not read": every `returned[]`
    entry not `chosen`, placed_in or not. With no chosen return the block's
    `dated` is unknown, so the document is `undated` and no page is placed."""

    execution = folder.pdf(EXECUTION_REL, [cover(SPA), "terms", _both(None)])
    led = _spa_ledger(chosen=chosen)  # placed_in names a compilation not in the folder
    run = audit(checklist=checklist([("1.1", SPA, True)]), sigpack=led)
    assert run.family_of(execution)["member_ids"] == [execution]
    result = run.reconcile([])
    item = result.item(SPA)
    assert result.receipt["sigpack"]["ledger_current"] is True
    assert item["execution"]["evidence_source"] == "sigpack-ledger"
    assert item["execution"]["apparent_status"] == "appears-unsigned"
    assert "executed compilation not in folder" in item["qualification"]
    assert item["execution"]["dated"] == ("dated" if chosen else "undated")
    assert item["document_date"] is None
    doc_view = result.overview_doc(item["item_id"])
    assert doc_view["signature_pages"] == []
    assert [b["status"] for b in doc_view["blocks"]] == ["signed", "signed"]


def test_block_with_no_status_makes_the_ledger_not_current(
    two_versions: tuple[str, str], audit: Callable[..., Audit]
) -> None:
    _, executed = two_versions
    led = _spa_ledger()
    del led["signature_pages"][0]["blocks"][1]["status"]
    run = audit(checklist=checklist([("1.1", SPA, True)]), sigpack=led)
    fam = run.family_of(executed)
    result = run.reconcile([rec_signed(fam, executed, page=3)])
    assert result.receipt["sigpack"] == {
        "ledger_supplied": True,
        "ledger_current": False,
        "documents_cited": 0,
    }
    assert result.overview["sigpack"]["ledger_current"] is False
    assert "SPA-p3 block 2: no status" in result.exceptions
    assert "does not match the folder" in result.exceptions
    # Execution evidence then comes from inspection alone.
    item = result.item(SPA)
    assert item["status"] == "ready"
    assert item["execution"]["evidence_source"] == "visual-inspection"
    assert result.overview_doc(item["item_id"])["blocks"] == []


# --------------------------------------------------- the ledger governs, visibly


def test_ledger_overriding_a_visual_record_is_noted(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """A visual-inspection record that does not cite the ledger is not rejected
    for disagreeing with it (rule 4 rejects citing records only), but the
    inspector saw a signature where the ledger reads blank: that disagreement
    is written under "Ledger notes" and on the overview, and the ledger governs."""

    executed = folder.pdf(EXECUTED_REL, [cover(SPA), "terms", _both(CLOSING_DATE_TEXT)])
    run = audit(
        checklist=checklist([("1.1", SPA, True)]), sigpack=_spa_ledger(block2="blank")
    )
    fam = run.family_of(executed)
    result = run.reconcile(
        [rec_signed(fam, executed, page=3)]
    )  # visual, appears-signed
    item = result.item(SPA)
    assert item["status"] == "unsigned"
    assert item["execution"]["evidence_source"] == "sigpack-ledger"
    assert item["execution"]["apparent_status"] == "appears-incomplete"
    assert result.receipt["inspection"] == {
        "families": 1,
        "inspected": 1,
        "rejected": 0,
    }
    line = (
        "inspection disagrees with the ledger: the record saw appears-signed on visual "
        "inspection, the ledger reads appears-incomplete; the ledger governs (rule 4)"
    )
    assert line in result.overview_doc(item["item_id"])["exceptions"]
    ledger_notes = result.exceptions.split("## Ledger notes\n", 1)[1]
    assert f"- CB-001 {SPA}: {line}" in ledger_notes


# ------------------------------------------- an unverified citation, said plainly


def test_unverified_ledger_citation_says_which_way_it_failed(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """Rule 4: a citation this run cannot check against the ledger is not
    evidence. The qualification says why — current but not covering this
    document, or not matching the folder — and never claims a visual inspection
    that did not happen."""

    executed = folder.pdf(EXECUTED_REL, [cover(SPA), "terms", _both(CLOSING_DATE_TEXT)])
    dl = folder.pdf(
        "Disclosure Letter.pdf", [cover(DL), "terms", _both(CLOSING_DATE_TEXT)]
    )
    rows = checklist([("1.1", SPA, True), ("1.2", DL, True)])

    # Current ledger, covering the SPA only; the DL record cites it anyway.
    run = audit(checklist=rows, sigpack=_spa_ledger())
    citing_dl = rec_signed(
        run.family_of(dl), dl, page=3, source="sigpack-ledger", locator="DL-p9"
    )
    result = run.reconcile(
        [
            rec_signed(
                run.family_of(executed),
                executed,
                page=3,
                source="sigpack-ledger",
                locator="SPA-p3",
            ),
            citing_dl,
        ]
    )
    assert result.item(SPA)["status"] == "ready"
    item = result.item(DL)
    assert item["status"] == "unsigned"
    assert item["execution"] == {
        "evidence_source": "none",
        "apparent_status": "unclear",
        "dated": "unclear",
        "ledger_page_ids": [],
    }
    assert item["qualification"] == (
        "execution evidence cites a sigpack ledger which is current but does not cover "
        "this document; no execution page was inspected"
    )
    assert "visual inspection" not in item["qualification"]
    assert result.overview_doc(item["item_id"])["exceptions"] == []

    # A ledger that does not match the folder: neither its execution version
    # nor an executed output is here.
    stale = _spa_ledger(placed="(Executed) Something Else.pdf#3")
    stale["signature_pages"][0]["file"] = "(Final) Other Agreement.pdf"
    run = audit(checklist=rows, sigpack=stale)
    result = run.reconcile([citing_dl])
    assert result.receipt["sigpack"]["ledger_current"] is False
    item = result.item(DL)
    assert item["qualification"] == (
        "execution evidence cites a sigpack ledger that does not match the folder; "
        "no execution page was inspected"
    )


# ------------------------------------------------ the ledger's own family


def test_the_supplied_ledger_file_is_excluded_whatever_its_name(
    two_versions: tuple[str, str],
    folder: Folder,
    audit: Callable[..., Audit],
    out_dir: Path,
) -> None:
    """sigpack-ledger-consumption.md: the family whose member hash-matches the
    supplied ledger is excluded from the index and from unexpected_families,
    recorded not-required in the plan, and still counted in sources.in_families.
    The file is identified by its hash, not by being named sigpack.ledger.json."""

    _, executed = two_versions
    led = _spa_ledger()
    ledger_path = folder.root / "ledger-final.json"
    ledger_path.write_text(json.dumps(led, indent=2, sort_keys=True))
    ledger_id = (
        "sha256:"
        + __import__("hashlib").sha256(ledger_path.read_bytes()).hexdigest()[:12]
    )

    run = audit(
        checklist=checklist([("1.1", SPA, True)]), sigpack=led, sigpack_path=ledger_path
    )
    ledger_family = run.family_of(ledger_id)["family_id"]
    result = run.reconcile(
        [
            rec_signed(
                run.family_of(executed),
                executed,
                page=3,
                source="sigpack-ledger",
                locator="SPA-p3",
            )
        ]
    )
    assert result.index["unexpected_families"] == []
    assert result.receipt["unexpected_families"] == 0
    assert result.receipt["outcome"] == "complete"
    plan = result.plan_family(ledger_family)
    assert plan["item_id"] is None
    assert plan["resolved_status"] == "not-required"
    assert (
        result.receipt["sources"]["in_families"]
        == result.receipt["sources"]["distinct"]
        == 3
    )
    assert (
        f"{ledger_family} is the ledger itself, not a closing document (ledger-final.json)"
        in result.exceptions
    )

    # The CLI hashes the --sigpack path it was given.
    paths = write_cli_inputs(run, out_dir, [])
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
        "--sigpack",
        ledger_path,
        "--root",
        folder.root,
        "--out-dir",
        out_dir,
        "--as-of",
        AS_OF,
    )
    assert load(out_dir / "closing-index.json")["unexpected_families"] == []
    assert load(out_dir / "closing-receipt.json")["sigpack"]["ledger_current"] is True


def test_record_helper_still_validates(
    two_versions: tuple[str, str], audit: Callable[..., Audit]
) -> None:
    """Guard for this file's own fixtures: the honest P4b-shaped record — the
    execution version picked, `appears-unsigned` citing the ledger — is read,
    lands unsigned, and cites the ledger with the contract's wording."""

    execution, _ = two_versions
    run = audit(checklist=checklist([("1.1", SPA, True)]), sigpack=_spa_ledger())
    fam = run.family_of(execution)
    honest = record(
        fam,
        pick=execution,
        status="unsigned",
        execution_expected=True,
        apparent="appears-unsigned",
        dated="dated",
        document_date=CLOSING_DATE_TEXT,
        signature_pages=[{"document_id": execution, "page": 3}],
        evidence=[
            evidence(
                "execution",
                "sigpack-ledger",
                "SPA-p3",
                "ledger shows 2 of 2 blocks signed; the compilation is the other member",
                execution,
            ),
            evidence(
                "date",
                "sigpack-ledger",
                "SPA-p3",
                f"both blocks dated {CLOSING_DATE_TEXT} on the chosen returns",
                execution,
            ),
        ],
    )
    result = run.reconcile([honest])
    item = result.item(SPA)
    assert result.receipt["inspection"]["rejected"] == 0
    assert item["status"] == "unsigned"
    assert item["selected_id"] == execution
    assert item["execution"]["evidence_source"] == "sigpack-ledger"
    # The compilation is the other member, so the wording is "not the executed
    # compilation", not "not in folder" (sigpack-ledger-consumption.md).
    assert item["qualification"] == (
        "ledger shows 2 of 2 blocks signed; the selected file is not the executed compilation"
    )
