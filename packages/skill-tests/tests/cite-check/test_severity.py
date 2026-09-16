"""Derived severity rollup and reporter-collision cross-check."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT_DIR = ROOT / "skills/litigation/cite-check/scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common.report_core import (  # noqa: E402
    build_report,
)
from common.severity import (  # noqa: E402
    citation_severity,
    parse_reporter_coordinates,
    severity_reason,
)


def _citation(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "citation_as_written_in_unit": "Example v. Smith, 1 F.4th 2",
        "matched_citation": "Example v. Smith, 1 F.4th 2",
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


def _legacy_citation(**overrides: Any) -> dict[str, Any]:
    value = _citation()
    for key in (
        "citation_kind",
        "source_resolution",
        "fabrication_indicators",
        "colliding_source_id",
        "existence_check_notes",
    ):
        value.pop(key, None)
    value.update(overrides)
    return value


def _manifest(
    *unit_ids: str,
    authorities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if authorities is None:
        authorities = [
            {
                "sourceId": "A0001",
                "path": "authorities/example.md",
                "filename": "example.md",
                "readability": "readable",
                "contentIdentity": {
                    "caseName": "Example v. Smith",
                    "reporterCitation": "1 F.4th 2",
                },
            }
        ]
    return {
        "schemaVersion": "cite-check.manifest.v2",
        "runId": "severity-run",
        "target": {
            "path": "input/brief.md",
            "fullDocumentRef": "input/brief.md",
            "displayName": "Synthetic brief",
        },
        "authorities": authorities,
        "units": [
            {
                "unitId": unit_id,
                "kind": "paragraph",
                "path": "input/brief.md",
                "lineStart": index,
                "lineEnd": index,
                "footnoteAnchorUnitId": None,
            }
            for index, unit_id in enumerate(unit_ids, start=1)
        ],
        "limitations": [],
    }


def _result(unit_id: str, *citations: dict[str, Any]) -> dict[str, Any]:
    return {
        "unitId": unit_id,
        "disposition": "citations_found" if citations else "no_citations_found",
        "citations": list(citations),
    }


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (_citation(), "green"),
        (
            _citation(
                source_resolution="not_supplied_not_found_potential_hallucination",
                matched_source_id=None,
                source_excerpt=None,
                source_locator=None,
                accuracy_of_source_characterization=(
                    "source_not_found_unable_to_characterize"
                ),
                pincite_accuracy="source_not_found_unable_to_check_pincite",
                accuracy_of_direct_quotation=(
                    "source_not_found_unable_to_check_quotation"
                ),
            ),
            "red",
        ),
        (
            _citation(
                fabrication_indicators=[
                    "reporter_coordinates_belong_to_different_supplied_case"
                ]
            ),
            "red",
        ),
        (
            _citation(
                accuracy_of_source_characterization=(
                    "objectively_false_or_unreasonable_characterization_of_source"
                )
            ),
            "red",
        ),
        (
            _citation(accuracy_of_direct_quotation="quotation_objectively_inaccurate"),
            "red",
        ),
        (
            _citation(
                matched_source_id=None,
                source_excerpt=None,
                source_locator=None,
                source_resolution="not_supplied_search_unavailable",
                accuracy_of_source_characterization=(
                    "source_not_found_unable_to_characterize"
                ),
                pincite_accuracy="source_not_found_unable_to_check_pincite",
                accuracy_of_direct_quotation=(
                    "source_not_found_unable_to_check_quotation"
                ),
            ),
            "amber",
        ),
        (
            _citation(
                matched_source_id=None,
                source_excerpt=None,
                source_locator=None,
                source_resolution="not_supplied_confirmed_exists_elsewhere",
                accuracy_of_source_characterization=(
                    "source_not_found_unable_to_characterize"
                ),
            ),
            "amber",
        ),
        (
            _citation(pincite_accuracy="pincite_inaccurate"),
            "yellow",
        ),
        (
            _citation(
                accuracy_of_source_characterization=(
                    "potentially_unfair_or_unreasonable_characterization_of_source"
                )
            ),
            "yellow",
        ),
        (
            _citation(
                accuracy_of_direct_quotation=(
                    "quotation_technically_accurate_but_misleading_or_unfair"
                )
            ),
            "yellow",
        ),
        (
            _citation(
                pincite_accuracy="pincite_inaccurate",
                accuracy_of_source_characterization=(
                    "objectively_false_or_unreasonable_characterization_of_source"
                ),
            ),
            "red",
        ),
    ],
)
def test_severity_mapping_is_worst_of_worker_enums(
    row: dict[str, Any], expected: str
) -> None:
    tier, bucket = citation_severity(row)
    assert tier == expected
    assert bucket is None


def test_unsupplied_statute_parks_in_reference_material_bucket() -> None:
    row = _citation(
        citation_kind="statute",
        matched_source_id=None,
        source_excerpt=None,
        source_locator=None,
        source_resolution="not_supplied_search_unavailable",
        accuracy_of_source_characterization="source_not_found_unable_to_characterize",
        pincite_accuracy="source_not_found_unable_to_check_pincite",
        accuracy_of_direct_quotation="source_not_found_unable_to_check_quotation",
        citation_as_written_in_unit="42 U.S.C. § 1983",
        matched_citation="42 U.S.C. § 1983",
    )
    tier, bucket = citation_severity(row)
    assert tier == "amber"
    assert bucket == "reference_material_not_checked"


def test_misleading_quotation_stays_yellow_pending_dispositive_ruling() -> None:
    # Open question: whether a misleading quotation on a dispositive point
    # should escalate to red. Keep yellow until that is ruled.
    tier, _bucket = citation_severity(
        _citation(
            accuracy_of_direct_quotation=(
                "quotation_technically_accurate_but_misleading_or_unfair"
            )
        )
    )
    assert tier == "yellow"


@pytest.mark.parametrize(
    "validation_flag",
    [
        "source_not_in_authority_universe",
        "source_not_found",
        "missing_excerpt",
        "missing_locator",
        "malformed_citation",
        "malformed_source_id",
        "source_resolution_inconsistent",
    ],
)
def test_unusable_validator_evidence_caps_green_at_amber(
    validation_flag: str,
) -> None:
    tier, _bucket = citation_severity(_citation(validation_flags=[validation_flag]))

    assert tier == "amber"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {
                "fabrication_indicators": [
                    "reporter_coordinates_belong_to_different_supplied_case"
                ],
                "validation_flags": ["missing_excerpt"],
            },
            "red",
        ),
        (
            {
                "pincite_accuracy": "pincite_inaccurate",
                "validation_flags": ["missing_locator"],
            },
            "yellow",
        ),
    ],
)
def test_evidence_gate_preserves_worker_substantive_judgment(
    overrides: dict[str, Any], expected: str
) -> None:
    tier, _bucket = citation_severity(_citation(**overrides))

    assert tier == expected


def test_report_marks_missing_evidence_amber_and_never_verified() -> None:
    report = build_report(
        _manifest("P0001"),
        [_result("P0001", _citation(source_excerpt=None, source_locator=None))],
    )

    row = report["unitResults"][0]["citations"][0]
    assert set(row["validation_flags"]) == {"missing_excerpt", "missing_locator"}
    assert row["severity"] == "amber"
    assert "Supported by the supplied source" not in row["severity_reason"]
    assert report["triage"]["counts"]["amber"] == 1


def test_report_marks_out_of_universe_source_amber_and_never_verified() -> None:
    report = build_report(
        _manifest("P0001"),
        [_result("P0001", _citation(matched_source_id="A9999"))],
    )

    row = report["unitResults"][0]["citations"][0]
    assert set(row["validation_flags"]) >= {
        "source_not_in_authority_universe",
        "source_not_found",
    }
    assert row["severity"] == "amber"
    assert "Supported by the supplied source" not in row["severity_reason"]
    assert report["triage"]["counts"]["amber"] == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("State v. Carter, 72 Ohio App.3d 553 (2d Dist. 1991)", {"72 Ohio App.3d 553"}),
        (
            "Stull v. Combustion Engineering, Inc., 72 Ohio App.3d 553",
            {"72 Ohio App.3d 553"},
        ),
        ("State v. Milam, 2022-Ohio-3965 (10th Dist.)", {"2022-Ohio-3965"}),
        ("State v. Eddy, 2022-Ohio-3965", {"2022-Ohio-3965"}),
        ("United States v. Jackson, 180 F.3d 55", {"180 F.3d 55"}),
        ("821 F. Supp. 2d 912", {"821 F. Supp. 2d 912"}),
        ("Example v. Smith, 1 F.4th 2, 4", {"1 F.4th 2"}),
        ("Hecht v. Levin, 66 Ohio St. 3d 458", {"66 Ohio St.3d 458"}),
        ("Kulch, 78 Ohio St.3d 134", {"78 Ohio St.3d 134"}),
        ("605 F. App'x 473", {"605 F. App'x 473"}),
        ("39 Cal.4th 299", {"39 Cal.4th 299"}),
    ],
)
def test_reporter_coordinate_parser_covers_common_forms(
    text: str, expected: set[str]
) -> None:
    assert parse_reporter_coordinates(text) == expected


def test_fake_name_on_real_cite_goes_red_with_colliding_source_id() -> None:
    authorities = [
        {
            "sourceId": "A_STULL",
            "path": "authorities/a-stull.md",
            "filename": "a-stull.md",
            "readability": "readable",
            "contentIdentity": {
                "caseName": "Stull v. Combustion Engineering, Inc.",
                "reporterCitation": "72 Ohio App.3d 553",
            },
        },
        {
            "sourceId": "A_EDDY",
            "path": "authorities/a-eddy.md",
            "filename": "a-eddy.md",
            "readability": "readable",
            "contentIdentity": {
                "caseName": "State v. Eddy",
                "reporterCitation": "2022-Ohio-3965",
            },
        },
    ]
    carter = _legacy_citation(
        citation_as_written_in_unit=(
            "State v. Carter, 72 Ohio App.3d 553 (2d Dist. 1991)"
        ),
        matched_citation="State v. Carter, 72 Ohio App.3d 553 (2d Dist. 1991)",
        matched_source_id=None,
        source_excerpt=None,
        source_locator=None,
        accuracy_of_source_characterization="source_not_found_unable_to_characterize",
        pincite_accuracy="NA_no_pincite_for_this_citation",
        accuracy_of_direct_quotation="NA_no_direct_quotation_for_this_citation",
    )
    milam = _legacy_citation(
        citation_as_written_in_unit="State v. Milam, 2022-Ohio-3965 (10th Dist.)",
        matched_citation="State v. Milam, 2022-Ohio-3965 (10th Dist.)",
        matched_source_id=None,
        source_excerpt=None,
        source_locator=None,
        accuracy_of_source_characterization="source_not_found_unable_to_characterize",
        pincite_accuracy="NA_no_pincite_for_this_citation",
        accuracy_of_direct_quotation="NA_no_direct_quotation_for_this_citation",
    )

    report = build_report(
        _manifest("P0016", "P0017", authorities=authorities),
        [_result("P0016", carter), _result("P0017", milam)],
    )

    carter_row = report["unitResults"][0]["citations"][0]
    milam_row = report["unitResults"][1]["citations"][0]
    assert carter_row["citation_as_written_in_unit"].startswith("State v. Carter")
    assert carter_row["severity"] == "red"
    assert (
        "reporter_collision_with_supplied_authority" in carter_row["aggregator_flags"]
    )
    assert carter_row["aggregator_colliding_source_id"] == "A_STULL"
    assert milam_row["severity"] == "red"
    assert milam_row["aggregator_colliding_source_id"] == "A_EDDY"
    unused = {item["sourceId"] for item in report["unusedAuthorities"]}
    assert unused == {"A_STULL", "A_EDDY"}
    assert "citation_kind" not in carter
    headline = report["triage"]["headline"]
    assert "State v. Carter" in headline
    assert "State v. Milam" in headline
    assert "may be fabricated" in headline
    assert report["triage"]["worst"] == "red"


def test_filename_alone_cannot_create_a_reporter_collision() -> None:
    authority = {
        "sourceId": "A_OTHER",
        "path": "authorities/other-case.md",
        "filename": "wrong-72 Ohio App.3d 553.md",
        "readability": "readable",
        "contentIdentity": {
            "caseName": "Other v. Example",
            "reporterCitation": "10 F.4th 20",
        },
    }
    citation = _legacy_citation(
        citation_as_written_in_unit="State v. Carter, 72 Ohio App.3d 553",
        matched_citation="State v. Carter, 72 Ohio App.3d 553",
        matched_source_id=None,
        source_excerpt=None,
        source_locator=None,
        accuracy_of_source_characterization="source_not_found_unable_to_characterize",
    )

    report = build_report(
        _manifest("P0001", authorities=[authority]),
        [_result("P0001", citation)],
    )

    row = report["unitResults"][0]["citations"][0]
    assert "reporter_collision_with_supplied_authority" not in row["aggregator_flags"]
    assert "aggregator_colliding_source_id" not in row


def test_search_miss_reason_does_not_overclaim_global_coverage() -> None:
    row = _citation(
        matched_source_id=None,
        source_excerpt=None,
        source_locator=None,
        source_resolution="not_supplied_not_found_potential_hallucination",
        fabrication_indicators=[],
    )

    reason = severity_reason(row)

    assert reason == "Search did not find the case — it may be hallucinated"
    assert "anywhere" not in reason


def test_search_unavailable_wins_over_contradictory_search_indicator() -> None:
    row = _citation(
        matched_source_id=None,
        source_excerpt=None,
        source_locator=None,
        source_resolution="not_supplied_search_unavailable",
        fabrication_indicators=["not_found_in_external_search"],
        accuracy_of_source_characterization="source_not_found_unable_to_characterize",
        pincite_accuracy="source_not_found_unable_to_check_pincite",
        accuracy_of_direct_quotation="source_not_found_unable_to_check_quotation",
        validation_flags=["source_resolution_indicator_inconsistent"],
    )

    tier, _bucket = citation_severity(row)

    assert tier == "amber"
    assert severity_reason(row) == "The environment could not search"


@pytest.mark.parametrize(
    ("resolution", "expected"),
    [
        ("not_supplied_search_unavailable", "The environment could not search"),
        (
            "not_supplied_confirmed_exists_elsewhere",
            "Case found but not supplied for substantive checking",
        ),
    ],
)
def test_unsupplied_case_reasons_use_plain_search_outcomes(
    resolution: str, expected: str
) -> None:
    row = _citation(
        matched_source_id=None,
        source_excerpt=None,
        source_locator=None,
        source_resolution=resolution,
        accuracy_of_source_characterization="source_not_found_unable_to_characterize",
    )

    assert severity_reason(row) == expected


def test_amber_only_headline_does_not_claim_verification() -> None:
    row = _citation(
        matched_source_id=None,
        source_excerpt=None,
        source_locator=None,
        source_resolution="not_supplied_search_unavailable",
        accuracy_of_source_characterization="source_not_found_unable_to_characterize",
    )
    report = build_report(_manifest("P0001", authorities=[]), [_result("P0001", row)])

    assert report["triage"]["headline"] == "1 citation could not be verified."


def test_legacy_rows_fall_back_to_accuracy_enums_and_default_kind() -> None:
    row = _legacy_citation(
        accuracy_of_source_characterization=(
            "potentially_unfair_or_unreasonable_characterization_of_source"
        )
    )
    report = build_report(_manifest("P0001"), [_result("P0001", row)])
    annotated = report["unitResults"][0]["citations"][0]
    assert annotated["severity"] == "yellow"
    assert annotated["citation_kind"] == "case"
    assert "citation_kind" not in row


def test_collision_does_not_rewrite_worker_authored_fields() -> None:
    original = _legacy_citation(
        citation_as_written_in_unit="State v. Carter, 72 Ohio App.3d 553",
        matched_citation="State v. Carter, 72 Ohio App.3d 553",
        matched_source_id=None,
        source_excerpt=None,
        source_locator=None,
        accuracy_of_source_characterization="source_not_found_unable_to_characterize",
    )
    snapshot = json.loads(json.dumps(original))
    authorities = [
        {
            "sourceId": "A_STULL",
            "path": "authorities/a-stull.md",
            "filename": "a-stull.md",
            "readability": "readable",
            "contentIdentity": {
                "caseName": "Stull v. Combustion Engineering, Inc.",
                "reporterCitation": (
                    "Stull v. Combustion Engineering, Inc., 72 Ohio App.3d 553"
                ),
            },
        }
    ]
    report = build_report(
        _manifest("P0001", authorities=authorities), [_result("P0001", original)]
    )
    assert original == snapshot
    row = report["unitResults"][0]["citations"][0]
    assert row["accuracy_of_source_characterization"] == (
        "source_not_found_unable_to_characterize"
    )
    assert row["matched_source_id"] is None
    assert row["aggregator_colliding_source_id"] == "A_STULL"
