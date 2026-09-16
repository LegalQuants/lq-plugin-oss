"""Contract-analysis objects are not invoicing instructions."""

from __future__ import annotations

import pytest
from test_timenarratives_prohibited import scan_text


@pytest.mark.parametrize(
    "text",
    [
        "Reviewed the suspension trigger and its treatment of disputed invoices.",
        "Analysed whether unpaid invoices justified contractual termination.",
        "Prepared the invoice response.",
        "Drafted the invoice dispute defence.",
        "Invoice dispute",
        "Invoice clause analysis",
        "Invoice response",
    ],
)
def test_invoice_as_legal_object_is_permitted(text: str) -> None:
    assert scan_text(text, "$.text") == []


@pytest.mark.parametrize(
    "text",
    [
        "Invoice the client.",
        "Please invoice the client.",
        "We invoice the client.",
        "Draft an invoice.",
        "Prepared the invoice.",
        "Prepared a client invoice.",
        "Created the client invoice.",
        "Generate a new invoice for this work.",
        "Send the invoice.",
        "The client was invoiced.",
        "Reviewed the contract; invoice the client.",
        "Please in\u200bvoice the client.",
    ],
)
def test_invoicing_actions_remain_blocked(text: str) -> None:
    assert "posting_decision" in {fault["code"] for fault in scan_text(text, "$.text")}
