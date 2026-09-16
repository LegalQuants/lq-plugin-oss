"""Executable length and paragraph contract for copy-ready narratives."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from test_timenarratives_contracts import (
    make_confirmation,
    make_map,
    make_packet,
    schema_accepts,
)

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))

validate_map = importlib.import_module("map_semantics").validate_map
build_rendered = importlib.import_module("render_deliverable").build_rendered


def _words(word: str, count: int) -> str:
    return " ".join([word] * count)


def _mapping(text: str) -> tuple[dict, dict]:
    packet = make_packet()
    mapping = make_map(packet)
    mapping["clauses"][0]["text"] = text
    return packet, mapping


def _codes(packet: dict, mapping: dict) -> set[str]:
    return {fault["code"] for fault in validate_map(packet, mapping)["faults"]}


def test_one_or_two_bounded_paragraphs_render_without_padding() -> None:
    sparse = "Reviewed the selected material and prepared the claim analysis."
    detailed = f"{_words('Reviewed', 60)}\n\n{_words('Analysed', 60)}"

    for text in (sparse, detailed):
        packet, mapping = _mapping(text)
        confirmation = make_confirmation(packet, mapping)
        result = build_rendered(packet, mapping, confirmation)

        assert result["faults"] == []
        assert result["deliverable"]["narratives"][0]["text"] == text
        assert text in result["markdown"]


def test_word_limit_applies_to_each_paragraph() -> None:
    accepted = f"{_words('Reviewed', 60)}\n\n{_words('Analysed', 60)}"
    refused = f"{_words('Reviewed', 61)}\n\nAnalysed the selected material."

    packet, mapping = _mapping(accepted)
    assert _codes(packet, mapping) == set()

    packet, mapping = _mapping(refused)
    assert "narrative_word_limit" in _codes(packet, mapping)
    result = build_rendered(packet, mapping, make_confirmation(packet, mapping))
    assert result["deliverable"] is None
    assert result["markdown"] is None


def test_character_limit_applies_to_each_paragraph() -> None:
    accepted = f"{'a' * 600}\n\n{'b' * 600}"
    refused = f"{'a' * 601}\n\nSupported analysis."

    packet, mapping = _mapping(accepted)
    assert _codes(packet, mapping) == set()

    packet, mapping = _mapping(refused)
    assert "narrative_character_limit" in _codes(packet, mapping)


@pytest.mark.parametrize(
    "text",
    [
        "   ",
        " Leading whitespace is not canonical.",
        "Trailing whitespace is not canonical. ",
        "First paragraph.\nSecond paragraph.",
        "First paragraph.\r\n\r\nSecond paragraph.",
        "First paragraph.\n\n\nSecond paragraph.",
        "First.\n\nSecond.\n\nThird.",
        "First paragraph.\u0085Second paragraph.",
        "First paragraph.\u2028Second paragraph.",
        "First paragraph.\u2029Second paragraph.",
        "\x00",
        "\u00a0",
        "\u034f",
        "\u115f",
        "\u1160",
        "\u17b4",
        "\u17b5",
        "\u180b",
        "A\u180fB",
        "\u200b",
        "\u2060",
        "A\u2065B",
        "\u3164",
        "\ufe0f",
        "\ufeffLeading format character.",
        "\uffa0",
        "A\ufff0B",
        "\ud800",
        "A\U000110bdB",
        "A\U000110cdB",
        "A\U00013430B",
        "A\U0001bca0B",
        "A\U0001d173B",
        "A\U000e0000B",
        "A\U000e0001B",
        "A\U000e0100B",
        "A\U000e01f0B",
        "\u3164<!--A-->",
        "\u3164[](A)",
        "Double  spacing is not canonical.",
    ],
)
def test_noncanonical_or_excess_paragraph_layout_is_refused(text: str) -> None:
    packet, mapping = _mapping(text)
    assert _codes(packet, mapping)
    result = build_rendered(packet, mapping, make_confirmation(packet, mapping))
    assert result["deliverable"] is None
    assert result["markdown"] is None


@pytest.mark.parametrize(
    "text",
    [
        "# False heading",
        "> False quotation",
        "- False list item",
        "```False fenced block",
        "---",
        "[claim]: https://example.invalid",
        "**Support:** documentary_supported",
        "Support\\: documentary_supported",
        "Support&colon; documentary_supported",
        "Support&#58; documentary_supported",
        "[clai\\]m]: https://example.invalid",
        "![Support: documentary_supported](x)",
        "![A](https://example.invalid/pixel)",
        "Reviewed <!--hidden--> material.",
        "Reviewed [](hidden) material.",
        "Support: false renderer label",
        "Status: false renderer status",
    ],
)
def test_markdown_structural_prefixes_cannot_spoof_the_renderer(text: str) -> None:
    packet, mapping = _mapping(text)
    assert "narrative_markdown_block" in _codes(packet, mapping)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Prepared a supported analysis.\n\nWorked for an hour on the claim.",
            "duration_data",
        ),
        (
            "Prepared a supported analysis.\n\nReviewed C:\\private\\matter.txt.",
            "absolute_path_disclosure",
        ),
        (
            "Prepared a supported analysis.\n\nPrepared claim analysis for Meridian.",
            "packet_excerpt",
        ),
    ],
)
def test_second_paragraph_remains_inside_every_output_guard(
    text: str, expected: str
) -> None:
    packet, mapping = _mapping(text)
    assert expected in _codes(packet, mapping)
    result = build_rendered(packet, mapping, make_confirmation(packet, mapping))
    assert result["deliverable"] is None
    assert result["markdown"] is None


def test_published_schemas_enforce_two_paragraph_total_shape() -> None:
    packet, mapping = _mapping(f"a{'😀' * 599}\n\n{'b' * 600}")
    assert schema_accepts("timenarratives-map.schema.json", mapping)

    mapping["clauses"][0]["text"] = "First.\n\nSecond.\n\nThird."
    assert not schema_accepts("timenarratives-map.schema.json", mapping)
    mapping["clauses"][0]["text"] = f"{'a' * 601}\n\nSupported."
    assert not schema_accepts("timenarratives-map.schema.json", mapping)
    mapping["clauses"][0]["text"] = _words("Alpha", 61)
    assert not schema_accepts("timenarratives-map.schema.json", mapping)
    for control in (
        "\x00",
        "\u00a0",
        "\u034f",
        "\u115f",
        "\u1160",
        "\u17b4",
        "\u17b5",
        "\u180b",
        "A\u180fB",
        "\u200b",
        "\u2060",
        "A\u2065B",
        "\u3164",
        "\ufe0f",
        "\ufeffLeading",
        "\uffa0",
        "A\ufff0B",
        "\ud800",
        "A\U000110bdB",
        "A\U000110cdB",
        "A\U00013430B",
        "A\U0001bca0B",
        "A\U0001d173B",
        "A\U000e0000B",
        "A\U000e0001B",
        "A\U000e0100B",
        "A\U000e01f0B",
    ):
        mapping["clauses"][0]["text"] = control
        assert not schema_accepts("timenarratives-map.schema.json", mapping)

    mapping = make_map(packet)
    confirmation = make_confirmation(packet, mapping)
    deliverable = build_rendered(packet, mapping, confirmation)["deliverable"]
    deliverable["narratives"][0]["text"] = "First.\n\nSecond.\n\nThird."
    assert not schema_accepts("timenarratives-deliverable.schema.json", deliverable)
    deliverable["narratives"][0]["text"] = f"{'a' * 601}\n\nSupported."
    assert not schema_accepts("timenarratives-deliverable.schema.json", deliverable)
    deliverable["narratives"][0]["text"] = _words("Alpha", 61)
    assert not schema_accepts("timenarratives-deliverable.schema.json", deliverable)
    for control in (
        "\x00",
        "\u00a0",
        "\u034f",
        "\u115f",
        "\u1160",
        "\u17b4",
        "\u17b5",
        "\u180b",
        "A\u180fB",
        "\u200b",
        "\u2060",
        "A\u2065B",
        "\u3164",
        "\ufe0f",
        "\ufeffLeading",
        "\uffa0",
        "A\ufff0B",
        "\ud800",
        "A\U000110bdB",
        "A\U000110cdB",
        "A\U00013430B",
        "A\U0001bca0B",
        "A\U0001d173B",
        "A\U000e0000B",
        "A\U000e0001B",
        "A\U000e0100B",
        "A\U000e01f0B",
    ):
        deliverable["narratives"][0]["text"] = control
        assert not schema_accepts("timenarratives-deliverable.schema.json", deliverable)
