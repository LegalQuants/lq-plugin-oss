"""Canonical internal identity for contract terms.

Source spelling and source offsets must never be rewritten with this module.
``term_key`` is only for dictionary keys and equality checks.
"""

from __future__ import annotations

import re
import unicodedata

TERM_NORMALIZATION_VERSION = "term-key-v1"

_UNICODE_WHITESPACE = re.compile(r"\s+", re.UNICODE)
_IDENTITY_PUNCTUATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u02bc": "'",
        "\uff07": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u00ab": '"',
        "\u00bb": '"',
        "\uff02": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\ufe58": "-",
        "\ufe63": "-",
        "\uff0d": "-",
    }
)
_APOSTROPHE_PATTERN = r"['\u2018\u2019\u201a\u201b\u02bc\uff07]"
_QUOTE_PATTERN = r'["\u201c\u201d\u201e\u201f\u00ab\u00bb\uff02]'
_HYPHEN_PATTERN = r"[-\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d]"


def term_key(value: str) -> str:
    """Return the versioned internal identity key for a source-facing label."""

    normalized = unicodedata.normalize("NFKC", str(value)).translate(
        _IDENTITY_PUNCTUATION
    )
    return _UNICODE_WHITESPACE.sub(" ", normalized).strip().casefold()


def same_term(left: str, right: str) -> bool:
    """Compare two labels with the canonical internal identity rules."""

    return term_key(left) == term_key(right)


def term_pattern(value: str, *, allow_possessive: bool = False) -> re.Pattern[str]:
    """Compile a source-text matcher for one normalized label identity."""

    pieces: list[str] = []
    for character in term_key(value):
        if character == " ":
            if not pieces or pieces[-1] != r"\s+":
                pieces.append(r"\s+")
        elif character == "'":
            pieces.append(_APOSTROPHE_PATTERN)
        elif character == '"':
            pieces.append(_QUOTE_PATTERN)
        elif character == "-":
            pieces.append(_HYPHEN_PATTERN)
        else:
            pieces.append(re.escape(character))
    suffix = rf"(?:{_APOSTROPHE_PATTERN}s)?" if allow_possessive else ""
    return re.compile(r"(?<!\w)" + "".join(pieces) + suffix + r"(?!\w)", re.I)
