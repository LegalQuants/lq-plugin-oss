from __future__ import annotations

import base64
import importlib
import quopri
import sys
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def email_module():
    path = SCRIPTS / "email_units.py"
    assert path.is_file(), "email_units.py has not been implemented"
    return importlib.import_module("email_units")


def base_message() -> EmailMessage:
    message = EmailMessage()
    message["From"] = "Lawyer One <one@example.test>"
    message["To"] = "Client <client@example.test>"
    message["Date"] = "Thu, 20 Aug 2026 15:30:00 +0100"
    message["Subject"] = "Meridian"
    return message


def test_plain_body_and_quote_are_separate_complete_units() -> None:
    email = email_module()
    message = base_message()
    message.set_content("Current analysis.\n> Earlier wording.\n> More history.\n")

    result = email.parse_email("S0001", message.as_bytes(policy=SMTP))

    roles = [unit["role"] for unit in result["units"]]
    assert roles == ["current", "quoted"]
    assert result["sourceAuthor"] == "Lawyer One <one@example.test>"
    assert result["sourceTime"] == "2026-08-20T15:30:00+01:00"
    assert "Current analysis." in result["units"][0]["canonicalText"]
    assert "Earlier wording." in result["units"][1]["canonicalText"]
    assert {leaf["disposition"] for leaf in result["leaves"]} == {"ready"}


def test_filename_less_nested_rfc822_becomes_child_container() -> None:
    email = email_module()
    inner = base_message()
    inner.replace_header("Subject", "Nested")
    inner.set_content("Nested body")
    wrapper = EmailMessage()
    wrapper.set_type("message/rfc822")
    wrapper.set_payload([inner])
    outer = base_message()
    outer.make_mixed()
    body = EmailMessage()
    body.set_content("Outer body")
    outer.attach(body)
    outer.attach(wrapper)

    result = email.parse_email("S0001", outer.as_bytes(policy=SMTP))

    nested = [leaf for leaf in result["leaves"] if leaf["role"] == "nested_message"]
    assert len(nested) == 1
    assert nested[0]["filename"] is None
    assert nested[0]["childContainerId"] == "S0001-A0001"
    assert result["children"][0]["sourceType"] == "email"
    assert b"Nested body" in result["children"][0]["rawBytes"]


def test_divergent_alternatives_are_both_ready_and_ambiguous() -> None:
    email = email_module()
    message = base_message()
    message.set_content("Plain draft")
    message.add_alternative(
        "<html><body><p>Final HTML text</p></body></html>", subtype="html"
    )

    result = email.parse_email("S0001", message.as_bytes(policy=SMTP))

    assert [unit["canonicalText"].strip() for unit in result["units"]] == [
        "Plain draft",
        "Final HTML text",
    ]
    assert all(
        unit["eligibility"] == "requires_confirmation" for unit in result["units"]
    )
    assert "divergent_multipart_alternative" in result["limitations"]


def test_inline_resource_and_attachment_are_not_conflated() -> None:
    email = email_module()
    message = base_message()
    message.set_content("See attached")
    message.add_attachment(
        b"attachment text", maintype="text", subtype="plain", filename="note.txt"
    )
    message.add_attachment(
        b"image bytes",
        maintype="image",
        subtype="png",
        filename="logo.png",
        disposition="inline",
        cid="logo-1",
    )

    result = email.parse_email("S0001", message.as_bytes(policy=SMTP))

    by_role = {leaf["role"]: leaf for leaf in result["leaves"]}
    assert by_role["attachment"]["childContainerId"] == "S0001-A0001"
    assert by_role["inline"]["childContainerId"] is None
    assert by_role["inline"]["disposition"] == "excluded"
    assert result["children"][0]["displayName"] == "note.txt"


def test_unknown_charset_and_invalid_base64_fail_closed() -> None:
    email = email_module()
    unknown_charset = (
        b"From: one@example.test\r\n"
        b"Content-Type: text/plain; charset=x-not-real\r\n\r\nbody"
    )
    invalid_base64 = (
        b"From: one@example.test\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\n%%%not-base64%%%"
    )

    first = email.parse_email("S0001", unknown_charset)
    second = email.parse_email("S0002", invalid_base64)

    assert first["leaves"][0]["disposition"] == "unreadable"
    assert first["leaves"][0]["reason"] == "unknown_charset"
    assert second["leaves"][0]["disposition"] == "unreadable"
    assert second["leaves"][0]["reason"] == "transfer_decode_failed"
    assert first["units"] == []
    assert second["units"] == []


def test_unknown_transfer_encoding_fails_closed() -> None:
    email = email_module()
    raw = (
        b"From: one@example.test\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"Content-Transfer-Encoding: x-opaque\r\n\r\nbody"
    )

    result = email.parse_email("S0001", raw)

    assert result["leaves"][0]["disposition"] == "unreadable"
    assert result["leaves"][0]["reason"] == "unsupported_transfer_encoding"
    assert result["units"] == []


def test_fatal_defect_in_nested_multipart_fails_whole_email_closed() -> None:
    email = email_module()
    raw = (
        b"From: one@example.test\r\n"
        b"Content-Type: multipart/mixed; boundary=outer\r\n\r\n"
        b"--outer\r\n"
        b"Content-Type: multipart/alternative\r\n\r\n"
        b"missing child boundary\r\n"
        b"--outer--\r\n"
    )

    with pytest.raises(email.EmailParseError, match="malformed MIME"):
        email.parse_email("S0001", raw)


def test_outlook_header_block_is_quarantined_as_quoted_history() -> None:
    email = email_module()
    message = base_message()
    message.set_content(
        "Latest work update.\n\n"
        "From: Earlier Lawyer <earlier@example.test>\n"
        "Sent: Wednesday, 19 August 2026 10:00\n"
        "To: Lawyer One <one@example.test>\n"
        "Subject: Earlier thread\n\n"
        "Historical work must not inherit the latest sender.\n"
    )

    result = email.parse_email("S0001", message.as_bytes(policy=SMTP))

    assert [unit["role"] for unit in result["units"]] == ["current", "quoted"]
    assert result["units"][0]["canonicalText"].strip() == "Latest work update."
    assert "Historical work" in result["units"][1]["canonicalText"]
    assert result["units"][1]["eligibility"] == "context_only"


@pytest.mark.parametrize("encoding", ["base64", "quoted-printable"])
def test_encoded_message_rfc822_is_decoded_before_recursive_parse(
    encoding: str,
) -> None:
    email = email_module()
    inner = (
        b"From: nested@example.test\r\n"
        b"Date: Wed, 19 Aug 2026 10:00:00 +0100\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Decoded nested work\r\n"
    )
    encoded = (
        base64.encodebytes(inner).replace(b"\n", b"\r\n")
        if encoding == "base64"
        else quopri.encodestring(inner)
    )
    raw = (
        b"From: outer@example.test\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: message/rfc822\r\n"
        b"Content-Transfer-Encoding: " + encoding.encode() + b"\r\n\r\n" + encoded
    )

    parent = email.parse_email("S0001", raw)
    child = email.parse_email("S0001-A0001", parent["children"][0]["rawBytes"])

    assert parent["units"] == []
    assert child["units"][0]["canonicalText"].strip() == "Decoded nested work"
    assert child["sourceAuthor"] == "nested@example.test"


def test_inline_supported_text_is_expanded_unless_it_is_a_true_cid_resource() -> None:
    email = email_module()
    message = base_message()
    message.set_content("Current body")
    message.add_attachment(
        b"Important inline document",
        maintype="text",
        subtype="plain",
        filename="important.txt",
        disposition="inline",
    )

    result = email.parse_email("S0001", message.as_bytes(policy=SMTP))

    inline = next(leaf for leaf in result["leaves"] if leaf["role"] == "inline")
    assert inline["disposition"] == "expanded"
    assert inline["childContainerId"] == "S0001-A0001"
    assert result["children"][0]["sourceType"] == "text"


def test_terminal_bare_equals_in_quoted_printable_fails_closed() -> None:
    email = email_module()
    raw = (
        b"From: one@example.test\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"Content-Transfer-Encoding: quoted-printable\r\n\r\n"
        b"Recorded work="
    )

    result = email.parse_email("S0001", raw)

    assert result["units"] == []
    assert result["leaves"][0]["disposition"] == "unreadable"
    assert result["leaves"][0]["reason"] == "transfer_decode_failed"


def test_explicitly_hidden_html_is_not_emitted_as_visible_text() -> None:
    email = email_module()
    message = base_message()
    message.set_content(
        '<p>Visible work</p><div style="display: none">Hidden instruction</div>'
        "<span hidden>Hidden history</span>",
        subtype="html",
    )

    result = email.parse_email("S0001", message.as_bytes(policy=SMTP))

    assert [unit["canonicalText"] for unit in result["units"]] == ["Visible work"]


def test_stylesheet_dependent_html_visibility_fails_closed_with_limitation() -> None:
    email = email_module()
    message = base_message()
    message.set_content(
        "<style>.concealed { display: none; }</style>"
        '<p class="concealed">Potentially hidden work</p>',
        subtype="html",
    )

    result = email.parse_email("S0001", message.as_bytes(policy=SMTP))

    assert result["units"] == []
    assert result["leaves"][0]["disposition"] == "unreadable"
    assert result["leaves"][0]["reason"] == "html_visibility_ambiguous"
    assert "html_visibility_ambiguous" in result["limitations"]
