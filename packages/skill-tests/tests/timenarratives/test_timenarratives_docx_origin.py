"""DOCX unit-to-package-part provenance binding regressions."""

from __future__ import annotations

import copy
import importlib
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from test_timenarratives_contracts import make_confirmation, make_packet
from test_timenarratives_docx_units import W, _document, _docx
from test_timenarratives_packet import _assert_schema_valid, request

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))
build_packet = importlib.import_module("build_packet")
packet_sha256 = importlib.import_module("canonical_json").packet_sha256
validate_map = importlib.import_module("map_semantics").validate_map
build_rendered = importlib.import_module("render_deliverable").build_rendered
contracts = importlib.import_module("structural_contracts")

Mutation = Callable[[dict, dict, dict[str, dict]], None]


def _minimal_docx() -> bytes:
    body = f'<w:p xmlns:w="{W}"><w:r><w:t>Reviewed synthetic filing.</w:t></w:r></w:p>'
    return _docx(_document(body, "w"))


def _compile_docx(tmp_path: Path, variant: str) -> dict:
    source = tmp_path / f"{variant}.docx"
    source.write_bytes(
        _minimal_docx()
        if variant == "minimal"
        else _docx(
            _document(
                f'<w:p xmlns:w="{W}"><w:r><w:t>Tracked synthetic '
                "filing.</w:t></w:r></w:p>",
                "w",
            )
        )
    )
    value = request([{"kind": "file", "path": source.name}])
    value["runId"] = f"DocxOrigin-{variant}"
    value["filters"]["sourceTypes"] = ["docx"]
    return build_packet.compile_packet(value, tmp_path)


def _review_map(packet: dict) -> dict:
    assessment = []
    for unit in packet["units"]:
        if unit["coverageDisposition"] != "pending":
            continue
        if unit["eligibility"] == "eligible":
            assessment.append(
                {
                    "unitId": unit["unitId"],
                    "disposition": "read_but_unused",
                    "reason": "not_relevant",
                }
            )
        elif unit["eligibility"] == "requires_confirmation":
            assessment.append(
                {
                    "unitId": unit["unitId"],
                    "disposition": "needs_confirmation",
                    "reason": "actor_unclear",
                }
            )
    return {
        "schemaVersion": "timenarratives.map.v1",
        "runId": packet["runId"],
        "packetDigest": packet["packetDigestSha256"],
        "unitAssessment": assessment,
        "atoms": [],
        "events": [],
        "workstreams": [],
        "clauses": [],
    }


def _part_index(packet: dict) -> dict[str, dict]:
    return {part["partId"]: part for part in packet["parts"]}


def _assert_refused_at_every_boundary(packet: dict, tmp_path: Path) -> None:
    packet["packetDigestSha256"] = packet_sha256(packet)
    mapping = _review_map(packet)
    confirmation = make_confirmation(packet, mapping)
    _assert_schema_valid(tmp_path, "timenarratives-packet.schema.json", packet)
    assert contracts.validate_packet_structure(packet) == []
    assert "packet_provenance" in {
        fault["code"] for fault in contracts.validate_packet_semantic_boundary(packet)
    }
    assert "packet_provenance" in {
        fault["code"] for fault in validate_map(packet, mapping)["faults"]
    }
    rendered = build_rendered(packet, mapping, confirmation)
    assert rendered["deliverable"] is None and rendered["markdown"] is None
    assert "packet_provenance" in {fault["code"] for fault in rendered["faults"]}


@pytest.mark.parametrize("variant", ["minimal", "tracked"])
def test_real_docx_units_are_bound_to_their_declared_parts(
    tmp_path: Path, variant: str
) -> None:
    packet = _compile_docx(tmp_path, variant)
    parts = _part_index(packet)

    _assert_schema_valid(tmp_path, "timenarratives-packet.schema.json", packet)
    assert contracts.validate_packet_semantic_boundary(packet) == []
    for unit in packet["units"]:
        if not unit["kind"].startswith("docx_"):
            continue
        part = parts[unit["originId"]]
        declared_name = part["locator"].removeprefix("docx:")
        assert part["containerId"] == unit["containerId"]
        assert part["unitIds"].count(unit["unitId"]) == 1
        assert unit["metadata"]["partName"] == declared_name
        assert unit["locator"].startswith(f"{part['locator']}#")
    mapping = _review_map(packet)
    assert validate_map(packet, mapping)["faults"] == []
    assert (
        build_rendered(packet, mapping, make_confirmation(packet, mapping))["faults"]
        == []
    )


@pytest.mark.parametrize("variant", ["minimal", "tracked"])
def test_paired_docx_origin_to_container_mutation_is_refused(
    tmp_path: Path, variant: str
) -> None:
    packet = _compile_docx(tmp_path, variant)
    unit = next(row for row in packet["units"] if row["kind"].startswith("docx_"))
    part = _part_index(packet)[unit["originId"]]
    part["unitIds"].remove(unit["unitId"])
    unit["originId"] = unit["containerId"]

    _assert_refused_at_every_boundary(packet, tmp_path)


def test_docx_container_unit_cannot_be_relabelled_as_generic(tmp_path: Path) -> None:
    packet = _compile_docx(tmp_path, "minimal")
    unit = next(row for row in packet["units"] if row["kind"].startswith("docx_"))
    part = _part_index(packet)[unit["originId"]]
    part["unitIds"].remove(unit["unitId"])
    unit.update(
        originId=unit["containerId"],
        kind="text_block",
        role="current",
        locator="text:utf8:0-28",
    )
    unit.pop("metadata")

    _assert_refused_at_every_boundary(packet, tmp_path)


def _rebind_part(unit: dict, original: dict, parts: dict[str, dict]) -> None:
    target = next(part for part in parts.values() if part is not original)
    original["unitIds"].remove(unit["unitId"])
    target["unitIds"].append(unit["unitId"])
    unit["originId"] = target["partId"]


def _change_part_name(unit: dict, _part: dict, _parts: dict[str, dict]) -> None:
    unit["metadata"]["partName"] = "word/other.xml"


def _change_locator(unit: dict, _part: dict, _parts: dict[str, dict]) -> None:
    unit["locator"] = "docx:word/other.xml#body/p[1]"


@pytest.mark.parametrize(
    "mutate",
    [_rebind_part, _change_part_name, _change_locator],
    ids=["same-container-part", "metadata-part-name", "unit-locator"],
)
def test_docx_declared_part_binding_mutations_are_refused(
    tmp_path: Path, mutate: Mutation
) -> None:
    packet = _compile_docx(tmp_path, "minimal")
    unit = next(row for row in packet["units"] if row["kind"].startswith("docx_"))
    parts = _part_index(packet)
    original = parts[unit["originId"]]
    mutate(unit, original, parts)

    _assert_refused_at_every_boundary(packet, tmp_path)


def test_docx_unit_cannot_be_rebound_to_excluded_package_part(
    tmp_path: Path,
) -> None:
    packet = _compile_docx(tmp_path, "minimal")
    unit = next(row for row in packet["units"] if row["kind"].startswith("docx_"))
    parts = _part_index(packet)
    original = parts[unit["originId"]]
    target = next(
        part
        for part in parts.values()
        if part is not original
        and part["role"] == "package_part"
        and part["disposition"] == "excluded"
    )
    original["unitIds"].remove(unit["unitId"])
    target["unitIds"].append(unit["unitId"])
    unit["originId"] = target["partId"]
    unit["metadata"]["partName"] = target["locator"].removeprefix("docx:")
    unit["locator"] = f"{target['locator']}#body/p[1]"

    _assert_refused_at_every_boundary(packet, tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [("role", "package_part"), ("disposition", "excluded")],
)
def test_docx_owning_part_must_be_ready_story(
    tmp_path: Path, field: str, value: str
) -> None:
    packet = _compile_docx(tmp_path, "minimal")
    unit = next(row for row in packet["units"] if row["kind"].startswith("docx_"))
    part = _part_index(packet)[unit["originId"]]
    part[field] = value
    if field == "disposition":
        part_id = part["partId"]
        packet["partitions"]["parts"]["ready"].remove(part_id)
        packet["partitions"]["parts"]["excluded"].append(part_id)

    _assert_refused_at_every_boundary(packet, tmp_path)


def test_non_docx_unit_may_retain_its_container_origin() -> None:
    packet = copy.deepcopy(make_packet())
    assert packet["units"][0]["kind"] == "text_block"
    assert packet["units"][0]["originId"] == packet["units"][0]["containerId"]
    assert contracts.validate_packet_semantic_boundary(packet) == []
