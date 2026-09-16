"""How the expected set is formed when the checklist is thin or absent:
the four precedence tiers and nothing else (the closing-bible skill's documented
"Fixed surface"), the tie rule, and the presumption that a document nobody
has classified is one the parties sign (status-taxonomy.md "Not inspected")."""

from __future__ import annotations

from collections.abc import Callable

from cb_support import (
    BUYER,
    CLOSING_DATE_TEXT,
    SELLER,
    Audit,
    Folder,
    checklist,
    cover,
    signed_page,
)

SPA = "Share Purchase Agreement"


def _both(date: str | None) -> str:
    return (
        signed_page(party=SELLER, date=date)
        + "\n"
        + signed_page(party=BUYER, date=date)
    )


def test_unclassified_document_presumes_execution_expected(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """status-taxonomy.md "Not inspected": "When nothing — checklist, ledger or
    inspection — says whether a document is one the parties sign, execution is
    presumed expected." So it lands unsigned, never incomplete."""

    folder.pdf("Deed of Release.pdf", [cover("Deed of Release"), "terms", _both(None)])
    result = audit().reconcile([])
    assert result.index["index_source"] == "drafted-from-census"
    item = result.item("deed of release")
    assert item["execution_expected"] is True
    assert item["status"] == "unsigned"
    assert item["qualification"] == "not inspected"
    assert item["execution"]["apparent_status"] == "not-inspected"


def test_checklist_refs_in_families_are_not_a_tier(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """README "Fixed surface": exactly four tiers — approved index, checklist,
    current ledger, drafted from census. A families.json carrying checklist_refs
    without the checklist passed to reconcile falls through; the refs stay
    informational and a row with no family is not listed missing."""

    spa = folder.pdf(
        "(Executed) Share Purchase Agreement.pdf",
        [cover(SPA), "terms", _both(CLOSING_DATE_TEXT)],
    )
    rows = checklist([("1.1", SPA, True), ("1.2", "Landlord Consent", True)])
    run = audit(checklist=rows)
    assert run.family_of(spa)["checklist_ref"] == "1.1"
    run.checklist = None  # the same families.json, reconcile without --checklist
    result = run.reconcile([])
    assert result.index["index_source"] == "drafted-from-census"
    assert [i["title"] for i in result.index["items"]] == [
        run.family_of(spa)["title_hint"]
    ]
    assert result.receipt["by_status"]["missing"] == 0
    assert "Landlord Consent" not in result.index["items"].__repr__()
    assert (
        "families.json carries checklist rows but no --checklist was given to reconcile"
        in result.exceptions
    )


def test_a_row_two_families_match_equally_binds_to_neither(
    folder: Folder, audit: Callable[..., Audit]
) -> None:
    """README "Fixed surface": a tie between equal candidates is no match. Two
    deeds of release overlap the row "Deed of Release" equally; the families
    stage gives the row to neither, reconcile lists the row missing and both
    families unexpected, and says so under the notes for the lawyer at Gate 1."""

    seller = folder.pdf(
        "Deed of Release Seller.pdf",
        [cover("Deed of Release"), "the Seller releases", _both(CLOSING_DATE_TEXT)],
    )
    buyer = folder.pdf(
        "Deed of Release Buyer.pdf",
        [cover("Deed of Release"), "the Buyer releases", _both(CLOSING_DATE_TEXT)],
    )
    run = audit(checklist=checklist([("3.1", "Deed of Release", True)]))
    fam_seller, fam_buyer = run.family_of(seller), run.family_of(buyer)
    assert fam_seller["family_id"] != fam_buyer["family_id"]
    assert fam_seller["checklist_ref"] is None and fam_buyer["checklist_ref"] is None
    result = run.reconcile([])
    assert result.item("Deed of Release")["status"] == "missing"
    assert {u["family_id"] for u in result.index["unexpected_families"]} == {
        fam_seller["family_id"],
        fam_buyer["family_id"],
    }
    assert "'Deed of Release' matches 2 families equally" in result.exceptions
    assert "the lawyer decides at Gate 1" in result.exceptions
