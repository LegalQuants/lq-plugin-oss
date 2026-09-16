from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
SCRIPT_DIR = ROOT / "skills/litigation/cite-check/scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common.contracts import (  # noqa: E402
    validate_unit_result,
)
from common.core import (  # noqa: E402
    attempt_receipt,
    should_retry,
)


def _citation(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "citation_as_written_in_unit": "Example v. Smith, 1 F.4th 2, 4",
        "matched_citation": "Example v. Smith, 1 F.4th 2, 4",
        "proposition": None,
        "matched_source_id": "A0001",
        "source_excerpt": "The rule applies.",
        "source_locator": "p. 4",
        "citation_kind": "case",
        "source_resolution": "matched_supplied_source",
        "fabrication_indicators": [],
        "accuracy_of_source_characterization": (
            "confirmed_fair_characterization_of_source"
        ),
        "pincite_accuracy": "pincite_confirmed_accurate",
        "accuracy_of_direct_quotation": "NA_no_direct_quotation_for_this_citation",
        "recommended_changes": None,
    }
    value.update(overrides)
    return value


def _result(*citations: dict[str, Any], unit_id: str = "P0001") -> dict[str, Any]:
    return {
        "unitId": unit_id,
        "disposition": "citations_found" if citations else "no_citations_found",
        "citations": list(citations),
    }


def test_missing_evidence_is_an_advisory_citation_flag_and_unit_is_retained() -> None:
    raw = _result(_citation(source_excerpt=None, source_locator=None))

    validation = validate_unit_result(raw, "P0001", authority_ids={"A0001"})

    assert validation["hard_errors"] == []
    assert validation["salvageable"] is True
    normalized = validation["normalized"]
    assert normalized is not None
    assert normalized["citations"][0]["source_excerpt"] is None
    assert normalized["citations"][0]["source_locator"] is None
    assert set(normalized["citations"][0]["validation_flags"]) == {
        "missing_excerpt",
        "missing_locator",
    }
    assert {item["code"] for item in validation["warnings"]} == {
        "missing_excerpt",
        "missing_locator",
    }
    assert should_retry(validation, 1) is False


def test_one_problem_citation_does_not_drop_other_rows_or_mutate_worker_fields() -> (
    None
):
    good = _citation()
    bad = _citation(
        source_excerpt=None,
        source_locator=None,
        pincite_accuracy="pincite_inaccurate",
    )
    raw = _result(good, bad)
    original = json.loads(json.dumps(raw))

    validation = validate_unit_result(raw, "P0001", authority_ids={"A0001"})

    normalized = validation["normalized"]
    assert normalized is not None
    assert len(normalized["citations"]) == 2
    assert normalized["citations"][0]["validation_flags"] == []
    assert "missing_excerpt" in normalized["citations"][1]["validation_flags"]
    assert "pincite_inaccurate" in normalized["citations"][1]["validation_flags"]
    assert raw == original
    assert validation["hard_errors"] == []


def test_empty_authority_universe_is_not_an_empty_allow_list_deny() -> None:
    validation = validate_unit_result(
        _result(_citation(matched_source_id="A0001")),
        "P0001",
        authority_ids=set(),
    )

    assert validation["hard_errors"] == []
    normalized = validation["normalized"]
    assert normalized is not None
    assert normalized["citations"][0]["matched_source_id"] == "A0001"
    assert normalized["citations"][0]["validation_flags"] == [
        "source_not_in_authority_universe",
        "source_not_found",
    ]
    assert should_retry(validation, 1) is False


def test_multiple_citation_rows_are_retained_without_parent_inventory() -> None:
    raw = _result(_citation())
    raw["citations"].append(_citation(proposition="A second proposition"))

    validation = validate_unit_result(raw, "P0001", authority_ids={"A0001"})

    assert validation["hard_errors"] == []
    assert len(validation["normalized"]["citations"]) == 2


def test_only_three_report_blocking_conditions_are_hard_errors() -> None:
    cases = [
        ("not-json", "not_json"),
        (_result(_citation(), unit_id="P0002"), "wrong_unit_id"),
        ({"unitId": "P0001", "disposition": "citations_found"}, "nothing_salvageable"),
    ]

    for raw, expected_code in cases:
        validation = validate_unit_result(raw, "P0001", authority_ids={"A0001"})
        assert [item["code"] for item in validation["hard_errors"]] == [expected_code]
        assert should_retry(validation, 1) is True


def test_attempt_receipt_keeps_raw_and_normalized_layers() -> None:
    raw = _result(_citation(source_excerpt=None))
    validation = validate_unit_result(raw, "P0001", authority_ids={"A0001"})

    receipt = attempt_receipt(1, raw, validation, elapsed_ms=12)

    assert receipt["status"] == "accepted"
    assert receipt["rawResult"] == raw
    assert receipt["normalizedResult"]["citations"][0]["validation_flags"] == [
        "missing_excerpt"
    ]
    assert receipt["warnings"][0]["code"] == "missing_excerpt"


def test_wrapper_repair_stays_in_schema_and_is_receipted() -> None:
    raw = {
        "unitId": "P0001",
        "citations": [_citation()],
    }

    validation = validate_unit_result(raw, "P0001", authority_ids={"A0001"})
    receipt = attempt_receipt(1, raw, validation)

    assert validation["hard_errors"] == []
    normalized = validation["normalized"]
    assert normalized is not None
    assert normalized["disposition"] == "citations_found"
    assert normalized["citations"][0]["matched_source_id"] == "A0001"
    assert receipt["rawResult"] == raw
    assert receipt["normalizedResult"] == normalized
    assert receipt["warnings"][0]["code"] == "wrapper_repair_disposition"


def test_source_resolution_must_match_matched_source_id() -> None:
    matched_mismatch = _citation(
        source_resolution="not_supplied_search_unavailable",
    )
    unmatched_mismatch = _citation(
        matched_source_id=None,
        source_excerpt=None,
        source_locator=None,
        source_resolution="matched_supplied_source",
        accuracy_of_source_characterization="source_not_found_unable_to_characterize",
        pincite_accuracy="source_not_found_unable_to_check_pincite",
        accuracy_of_direct_quotation="source_not_found_unable_to_check_quotation",
    )
    consistent = _citation(
        citation_kind="case",
        source_resolution="matched_supplied_source",
        fabrication_indicators=[],
    )

    mismatched = validate_unit_result(
        _result(matched_mismatch, unmatched_mismatch),
        "P0001",
        authority_ids={"A0001"},
    )
    aligned = validate_unit_result(
        _result(consistent), "P0001", authority_ids={"A0001"}
    )

    assert mismatched["hard_errors"] == []
    assert mismatched["normalized"] is not None
    assert (
        "source_resolution_inconsistent"
        in mismatched["normalized"]["citations"][0]["validation_flags"]
    )
    assert (
        "source_resolution_inconsistent"
        in mismatched["normalized"]["citations"][1]["validation_flags"]
    )
    assert {item["code"] for item in mismatched["warnings"]} >= {
        "source_resolution_inconsistent"
    }
    assert aligned["normalized"] is not None
    assert aligned["normalized"]["citations"][0]["validation_flags"] == []


def test_legacy_rows_without_resolution_fields_are_not_flagged_inconsistent() -> None:
    validation = validate_unit_result(
        _result(_citation()), "P0001", authority_ids={"A0001"}
    )

    assert validation["hard_errors"] == []
    assert validation["normalized"] is not None
    assert (
        "source_resolution_inconsistent"
        not in validation["normalized"]["citations"][0]["validation_flags"]
    )


def test_empty_fabrication_indicators_default_is_accepted() -> None:
    validation = validate_unit_result(
        _result(_citation(fabrication_indicators=[])),
        "P0001",
        authority_ids={"A0001"},
    )

    assert validation["hard_errors"] == []
    assert validation["normalized"] is not None
    assert validation["normalized"]["citations"][0]["fabrication_indicators"] == []
