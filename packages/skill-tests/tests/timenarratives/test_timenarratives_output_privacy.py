"""Deterministic model-output path and packet-excerpt privacy gates."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest
from test_timenarratives_contracts import make_confirmation, make_map, make_packet

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))
canonical_sha256 = importlib.import_module("canonical_json").canonical_sha256
validate_map = importlib.import_module("map_semantics").validate_map
_renderer = importlib.import_module("render_deliverable")
build_rendered = _renderer.build_rendered
_privacy = importlib.import_module("output_privacy")
scan_model_output = _privacy.scan_model_output
scan_rendered = _privacy.scan_rendered

BLOCKED_OUTPUTS = (
    ("Took 90m.", "duration_data"),
    ("Worked from 09.30 to 10.30.", "duration_data"),
    ("The billing classification was L120.", "billing_code"),
    ("The work was chargeable.", "billability_decision"),
    ("Entered the time entry into the billing system.", "posting_decision"),
    ("Settlement value was five million GBP.", "money_data"),
    ("Prepared claim analysis for Meridian.", "packet_excerpt"),
    ("Reviewed /data/matters/secret.txt.", "absolute_path_disclosure"),
)


def _codes(result: dict) -> set[str]:
    return {fault["code"] for fault in result["faults"]}


def _packet_with_text(text: str) -> tuple[dict, dict]:
    packet = make_packet()
    encoded = text.encode("utf-8")
    unit = packet["units"][0]
    unit.update(
        canonicalText=text,
        canonicalUtf8Sha256=hashlib.sha256(encoded).hexdigest(),
        utf8Start=0,
        utf8End=len(encoded),
    )
    packet["budget"]["modelVisibleUtf8Bytes"] = len(encoded)
    packet.pop("packetDigestSha256")
    packet["packetDigestSha256"] = canonical_sha256(packet)
    return packet, make_map(packet)


@pytest.mark.parametrize(
    "disclosure",
    [
        r"Reviewed C:\Private\Client\source.txt for the selected matter.",
        r"Reviewed \\server\secret-share\source.txt for the selected matter.",
        "Reviewed file:///home/private/source.txt for the selected matter.",
        "Reviewed /home/private/source.txt for the selected matter.",
        "Reviewed /Users/private/source.txt for the selected matter.",
    ],
)
def test_preconfirmation_rejects_recognized_absolute_path_disclosure(
    disclosure: str,
) -> None:
    packet = make_packet()
    mapping = make_map(packet)
    mapping["clauses"][0]["text"] = disclosure
    result = validate_map(packet, mapping)
    assert "absolute_path_disclosure" in _codes(result)
    assert disclosure not in json.dumps(result)
    confirmation = make_confirmation(packet, mapping)
    rendered = build_rendered(packet, mapping, confirmation)
    assert rendered["deliverable"] is None and rendered["markdown"] is None


def test_final_privacy_scan_rejects_a_path_without_echoing_it() -> None:
    disclosure = "file:///home/private/client-source.txt"
    result = _renderer.scan_rendered({"narratives": [{"text": disclosure}]}, disclosure)
    assert "absolute_path_disclosure" in {fault["code"] for fault in result}
    assert disclosure not in json.dumps(result)


SOURCE = (
    "Counsel reviewed the detailed synthetic disclosure chronology and prepared "
    "the revised witness evidence strategy for the selected matter."
)


@pytest.mark.parametrize("field", ["clause", "action", "label"])
def test_full_model_field_cannot_copy_a_threshold_packet_excerpt(field: str) -> None:
    packet, mapping = _packet_with_text(SOURCE)
    if field == "clause":
        mapping["clauses"][0]["text"] = SOURCE
    elif field == "action":
        mapping["events"][0]["action"] = SOURCE
    else:
        mapping["workstreams"][0]["label"] = SOURCE
    assert "packet_excerpt" in _codes(validate_map(packet, mapping))


def test_long_interior_packet_excerpt_is_rejected() -> None:
    packet, mapping = _packet_with_text(SOURCE)
    mapping["clauses"][0]["text"] = (
        "Summarised the detailed synthetic disclosure chronology and prepared "
        "the revised witness evidence for strategy."
    )
    assert "packet_excerpt" in _codes(validate_map(packet, mapping))


def test_excerpt_matching_normalizes_unicode_and_whitespace() -> None:
    source = (
        "Counsel\u00a0reviewed   the de\u0301tailed\nsynthetic disclosure chronology "
        "and prepared the revised witness evidence strategy."
    )
    packet, mapping = _packet_with_text(source)
    mapping["clauses"][0]["text"] = (
        "COUNSEL reviewed the détailed synthetic disclosure chronology and "
        "prepared the revised witness evidence strategy."
    )
    assert "packet_excerpt" in _codes(validate_map(packet, mapping))


@pytest.mark.parametrize(
    ("source", "copied"),
    [
        (
            "Prepared claim analysis for Meridian.",
            "Pre\u200bpared claim analysis for Meridian.",
        ),
        (
            "Counsel’s detailed review supported the Meridian claim.",
            "Counsel's detailed review supported the Meridian claim.",
        ),
    ],
)
def test_complete_copy_normalizes_format_characters_and_apostrophes(
    source: str, copied: str
) -> None:
    packet, mapping = _packet_with_text(source)
    mapping["clauses"][0]["text"] = copied

    assert "packet_excerpt" in {
        issue["code"] for issue in scan_model_output(mapping, packet)
    }
    assert _codes(validate_map(packet, mapping)) & {
        "narrative_layout",
        "packet_excerpt",
    }


def test_partial_copy_normalizes_embedded_format_characters() -> None:
    packet, mapping = _packet_with_text(SOURCE)
    mapping["clauses"][0]["text"] = (
        "det\u200bai\u200bled synthetic disclosure chronology and prepared the revised"
    )

    assert "packet_excerpt" in {
        issue["code"] for issue in scan_model_output(mapping, packet)
    }
    assert "narrative_layout" in _codes(validate_map(packet, mapping))


def test_short_document_title_and_case_reference_are_not_excerpts() -> None:
    packet, mapping = _packet_with_text(SOURCE)
    mapping["clauses"][0]["text"] = (
        "Reviewed Project Atlas Agreement and Smith against Jones."
    )
    assert validate_map(packet, mapping)["faults"] == []


def test_non_authored_map_fields_are_outside_the_privacy_guard() -> None:
    packet = make_packet()
    mapping = make_map(packet)
    mapping["events"][0]["assertedBy"] = r"C:\Private\Client\source.txt"

    assert scan_model_output(mapping, packet) == []


def test_non_narrative_rendered_fields_are_outside_the_privacy_guard() -> None:
    disclosure = r"C:\Private\Client\source.txt"
    deliverable = {
        "narratives": [
            {"workstreamId": "WORK", "text": "Prepared the claim analysis."}
        ],
        "receipt": {"diagnostic": disclosure, "counts": {"units": 120}},
    }
    markdown = (
        "# Time Narratives\n\n### WORK\n\nPrepared the claim analysis.\n\n"
        "Support: documentary_supported\n\nExceptions recorded: 120\n"
    )

    assert scan_rendered(deliverable, markdown) == []


@pytest.mark.parametrize(("text", "expected_code"), BLOCKED_OUTPUTS)
def test_validate_map_refuses_bounded_output_bypasses(
    text: str, expected_code: str
) -> None:
    packet = make_packet()
    mapping = make_map(packet)
    mapping["clauses"][0]["text"] = text

    result = validate_map(packet, mapping)

    assert expected_code in _codes(result)
    assert text not in json.dumps(result)


@pytest.mark.parametrize(("text", "expected_code"), BLOCKED_OUTPUTS)
def test_render_cli_refuses_bounded_output_bypasses_without_artifacts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    text: str,
    expected_code: str,
) -> None:
    packet = make_packet()
    mapping = make_map(packet)
    mapping["clauses"][0]["text"] = text
    confirmation = make_confirmation(packet, mapping)
    paths: dict[str, Path] = {}
    for name, value in (
        ("request", {}),
        ("packet", packet),
        ("map", mapping),
        ("confirmation", confirmation),
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        paths[name] = path
    output = tmp_path / "rendered"

    code = _renderer.main(
        [
            "--request",
            str(paths["request"]),
            "--source-root",
            str(tmp_path),
            "--packet",
            str(paths["packet"]),
            "--map",
            str(paths["map"]),
            "--confirmation",
            str(paths["confirmation"]),
            "--out-dir",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    faults = json.loads(captured.out)["faults"]
    assert code == 1
    assert expected_code in {fault["code"] for fault in faults}
    assert text not in captured.out + captured.err
    assert not output.exists()
