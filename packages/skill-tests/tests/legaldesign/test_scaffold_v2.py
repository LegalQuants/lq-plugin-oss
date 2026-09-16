from __future__ import annotations

import copy
import importlib.util
import json
import sys
from argparse import Namespace
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "skills" / "core" / "legaldesign" / "scripts" / "scaffold.py"
VALID = ROOT / "packages/skill-tests/tests/legaldesign/fixtures/valid-build-spec.json"
SPEC = importlib.util.spec_from_file_location("legaldesign_scaffold_v2", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
scaffold = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scaffold
SPEC.loader.exec_module(scaffold)


def canonical() -> dict[str, Any]:
    return json.loads(VALID.read_text(encoding="utf-8"))


def test_template_check_rejects_fixture_matter_terms(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    template = tmp_path / "template.html"
    args = Namespace(path=template, asset="stacked-explainer.html")
    template.write_text("<html><body>[Neutral heading]</body></html>", encoding="utf-8")
    assert scaffold._command_template_check(args) == 0
    capsys.readouterr()
    template.write_text("<html><body>Delaware</body></html>", encoding="utf-8")
    assert scaffold._command_template_check(args) == 1
    assert "matter term 'Delaware'" in capsys.readouterr().err


def unknown_component(payload: dict[str, Any]) -> None:
    payload["units"][1]["variants"]["a"]["component"] = "before-after"


def over_capacity(payload: dict[str, Any]) -> None:
    payload["units"][1]["variants"]["a"]["params"]["itemsB"].extend(
        [{"title": "Extra 1"}, {"title": "Extra 2"}]
    )


def missing_treatment(payload: dict[str, Any]) -> None:
    del payload["units"][0]["variants"]["b"]


def identical_treatments(payload: dict[str, Any]) -> None:
    payload["units"][0]["variants"]["b"] = copy.deepcopy(
        payload["units"][0]["variants"]["a"]
    )


def unknown_relationship(payload: dict[str, Any]) -> None:
    payload["units"][0]["relationship"] = "adjacency"


def missing_placeholder(payload: dict[str, Any]) -> None:
    del payload["units"][0]["placeholder"]


def missing_reader(payload: dict[str, Any]) -> None:
    payload["brief"]["reader"] = ""


def unknown_parameter(payload: dict[str, Any]) -> None:
    payload["units"][1]["variants"]["a"]["params"]["silent"] = "ignored"


def unknown_nested_field(payload: dict[str, Any]) -> None:
    payload["units"][1]["variants"]["b"]["params"]["branches"][0]["leaves"] = [
        {"title": "Item", "silent": "ignored"}
    ]


FAIL_CLOSED: list[tuple[str, Callable[[dict[str, Any]], None], str]] = [
    ("unknown component", unknown_component, "unknown component ID 'before-after'"),
    ("over-capacity list", over_capacity, "expected 1 to 3 items"),
    ("missing treatment", missing_treatment, "expected exactly 2 variants"),
    ("identical treatments", identical_treatments, "have identical content"),
    ("unknown relationship", unknown_relationship, "$.units[0].relationship"),
    (
        "missing placeholder",
        missing_placeholder,
        "missing required field 'placeholder'",
    ),
    ("missing reader", missing_reader, "$.brief.reader: expected a non-empty string"),
    ("unknown parameter", unknown_parameter, "unknown field 'silent'"),
    ("unknown nested field", unknown_nested_field, "unknown field 'silent'"),
]


def test_canonical_v2_spec_is_valid() -> None:
    assert scaffold.validate_spec(canonical()) == []


def test_v2_keeps_legacy_per_unit_ab_variants() -> None:
    payload = canonical()

    assert all(set(unit["variants"]) == {"a", "b"} for unit in payload["units"])
    assert "approaches" not in payload


def test_v2_non_single_unit_requires_b_variant_for_schema_parity() -> None:
    payload = canonical()
    unit = payload["units"][0]
    assert unit.get("single", False) is False
    del unit["variants"]["b"]

    errors = scaffold.validate_spec(payload)

    assert any("missing required field 'b'" in error for error in errors), errors
    assert any("expected exactly 2 variants, got 1" in error for error in errors), (
        errors
    )


@pytest.mark.parametrize(
    "field",
    [
        "composition",
        "approaches",
        "claims",
        "claimRefs",
        "decision-fields",
        "encoding",
        "evidence-fields",
    ],
)
def test_v2_rejects_v3_only_fields(field: str) -> None:
    payload = canonical()
    if field == "composition":
        payload["composition"] = {}
    elif field == "approaches":
        payload["approaches"] = {"a": {}, "b": {}}
    elif field == "claims":
        payload["claims"] = []
    elif field == "claimRefs":
        payload["units"][0]["claimRefs"] = ["claim-1"]
    elif field == "decision-fields":
        payload["units"][0]["question"] = "Choose?"
    elif field == "encoding":
        payload["units"][0]["variants"]["a"]["encoding"] = "Reading order."
    else:
        payload["evidence"][0]["sourceId"] = "memo"
    errors = scaffold.validate_spec(payload)
    assert any("unknown field" in error for error in errors), (field, errors)


@pytest.mark.parametrize(("name", "mutate", "message"), FAIL_CLOSED)
def test_fail_closed_fixture_names_the_error(
    name: str,
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    payload = canonical()
    mutate(payload)
    errors = scaffold.validate_spec(payload)
    assert any(message in error for error in errors), f"{name}: {errors!r}"
