from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def text_module():
    path = SCRIPTS / "text_units.py"
    assert path.is_file(), "text_units.py has not been implemented"
    return importlib.import_module("text_units")


def test_text_decode_is_strict_and_line_endings_are_versioned() -> None:
    text = text_module()

    decoded = text.decode_text(b"\xef\xbb\xbfFirst\r\nSecond\rThird")

    assert decoded.text == "First\nSecond\nThird"
    assert decoded.had_bom is True


@pytest.mark.parametrize("payload", [b"\xff", b"ok\x00hidden"])
def test_invalid_or_nul_text_is_not_replacement_decoded(payload: bytes) -> None:
    text = text_module()

    with pytest.raises(text.TextDecodeError):
        text.decode_text(payload)


def test_text_units_cover_all_utf8_bytes_without_truncation() -> None:
    text = text_module()
    payload = ("abé\n" * 7).encode()

    units = text.make_text_units(
        "S0001", payload, kind="text_block", role="current", max_unit_bytes=9
    )

    assert [unit["unitId"] for unit in units] == [
        "S0001-U0001",
        "S0001-U0002",
        "S0001-U0003",
        "S0001-U0004",
    ]
    assert "".join(unit["canonicalText"] for unit in units) == "abé\n" * 7
    assert units[0]["utf8Start"] == 0
    assert units[-1]["utf8End"] == len(payload)
    assert all(unit["utf8End"] - unit["utf8Start"] <= 9 for unit in units)
    assert all(len(unit["canonicalUtf8Sha256"]) == 64 for unit in units)


def test_user_note_units_are_attested_and_require_confirmation() -> None:
    text = text_module()

    unit = text.make_text_units(
        "S0002",
        b"Discussed strategy",
        kind="user_note",
        role="attested",
        eligibility="requires_confirmation",
        source_class="user_attested",
    )[0]

    assert unit["sourceClass"] == "user_attested"
    assert unit["eligibility"] == "requires_confirmation"
    assert unit["coverageDisposition"] == "pending"
