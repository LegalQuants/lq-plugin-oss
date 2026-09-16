"""Exact map assessment disposition/reason contract."""

from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

import pytest
from test_timenarratives_contracts import make_map, schema_accepts

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "skills" / "core" / "timenarratives" / "scripts"))
validate_structure = importlib.import_module("structural_contracts").validate_structure

QUESTION_REASONS = (
    "actor_unclear",
    "matter_unclear",
    "action_unclear",
    "object_unclear",
    "source_unsupported",
    "source_unreadable",
    "source_partially_read",
)
VALID_PAIRS = [
    ("used", None),
    ("read_but_unused", "not_relevant"),
    ("excluded_other_actor", "other_actor"),
    ("excluded_other_matter", "other_matter"),
    ("excluded_non_work", "non_work"),
    *(("needs_confirmation", reason) for reason in QUESTION_REASONS),
]


@pytest.mark.parametrize(("disposition", "reason"), VALID_PAIRS)
def test_exact_assessment_pair_is_accepted(
    disposition: str, reason: str | None
) -> None:
    mapping = make_map()
    mapping["unitAssessment"][0].update(disposition=disposition, reason=reason)
    assert schema_accepts("timenarratives-map.schema.json", mapping)
    assert validate_structure("map", mapping) == []


@pytest.mark.parametrize(
    ("disposition", "wrong_reason"),
    [
        ("used", "not_relevant"),
        ("read_but_unused", None),
        ("excluded_other_actor", "other_matter"),
        ("excluded_other_matter", "other_actor"),
        ("excluded_non_work", "not_relevant"),
        ("needs_confirmation", None),
        ("needs_confirmation", "not_relevant"),
    ],
)
def test_contradictory_assessment_pair_is_rejected(
    disposition: str, wrong_reason: str | None
) -> None:
    mapping = make_map()
    mapping["unitAssessment"][0].update(disposition=disposition, reason=wrong_reason)
    assert not schema_accepts("timenarratives-map.schema.json", mapping)
    faults = validate_structure("map", mapping)
    assert {fault["code"] for fault in faults} == {"assessment_reason"}
    assert faults[0]["path"] == "$.unitAssessment[0].reason"


def test_all_assessment_rows_use_the_same_exact_matrix() -> None:
    mapping = make_map()
    second = copy.deepcopy(mapping["unitAssessment"][0])
    second.update(unitId="C0001-U0002", disposition="used", reason="non_work")
    mapping["unitAssessment"].append(second)
    assert not schema_accepts("timenarratives-map.schema.json", mapping)
    assert "assessment_reason" in {
        fault["code"] for fault in validate_structure("map", mapping)
    }
