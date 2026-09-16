from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT_DIR = ROOT / "skills/litigation/cite-check/scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common.contracts import validate_unit_result  # noqa: E402
from common.core import (  # noqa: E402
    attempt_receipt,
    strict_normalized_report_result,
    terminal_schema_errors,
)
from common.report_core import (  # noqa: E402
    ReportInputError,
    build_report,
    repair_report_once,
)
from common.report_render import (  # noqa: E402
    render_html,
    render_summary,
)


def _collision_authorities() -> list[dict[str, Any]]:
    return [
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


def _manifest(*unit_ids: str) -> dict[str, Any]:
    return {
        "schemaVersion": "cite-check.manifest.v2",
        "runId": "v2-report-run",
        "target": {
            "path": "input/brief.md",
            "fullDocumentRef": "input/brief.md",
            "displayName": "Synthetic brief",
        },
        "authorities": [
            {
                "sourceId": "A0001",
                "path": "authorities/example.md",
                "filename": "example.md",
                "readability": "readable",
                "contentIdentity": {"caseName": "Example v. Smith"},
            }
        ],
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


def _citation(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "citation_as_written_in_unit": "Example v. Smith, 1 F.4th 2",
        "matched_citation": "Example v. Smith, 1 F.4th 2",
        "proposition": "The rule applies.",
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


def _result(unit_id: str = "P0001", *citations: dict[str, Any]) -> dict[str, Any]:
    return {
        "unitId": unit_id,
        "disposition": "citations_found" if citations else "no_citations_found",
        "citations": list(citations),
    }


def test_report_consumes_v2_rows_without_parent_inventory_or_sol_contract() -> None:
    result = _result("P0001", _citation(source_excerpt=None, source_locator=None))

    report = build_report(_manifest("P0001"), [result])

    assert report["schemaVersion"] == "cite-check.report.v2"
    assert report["status"] == "complete"
    assert report["senseCheck"]["passCount"] == 1
    assert report["senseCheck"]["maxRetryRoundCount"] == 1
    assert report["senseCheck"]["maxTargetedRepairCount"] == 1
    assert report["senseCheck"]["retryRoundCount"] == 0
    assert report["unitResults"][0]["citations"][0]["proposition"] == (
        "The rule applies."
    )
    assert report["unitResults"][0]["citations"][0]["matched_source_id"] == "A0001"
    assert set(report["unitResults"][0]["citations"][0]["validation_flags"]) == {
        "missing_excerpt",
        "missing_locator",
    }
    assert "selection" not in report
    assert "solReview" not in report


def test_report_without_execution_metadata_does_not_assume_codex() -> None:
    report = build_report(_manifest("P0001"), [_result("P0001")])

    assert report["execution"] == {
        "provider": "unknown",
        "surface": "unknown",
        "model": "unknown",
        "reasoningEffort": "unknown",
    }


def test_report_does_not_drop_or_merge_repeated_citation_propositions() -> None:
    first = _citation(proposition="The rule supplies the standard.")
    second = _citation(proposition="The court applied the standard.")

    report = build_report(_manifest("P0001"), [_result("P0001", first, second)])

    assert [row["proposition"] for row in report["unitResults"][0]["citations"]] == [
        "The rule supplies the standard.",
        "The court applied the standard.",
    ]


def test_empty_authority_inventory_does_not_deny_or_drop_unit() -> None:
    manifest = _manifest("P0001")
    manifest["authorities"] = []
    result = _result("P0001", _citation(matched_source_id="A0001"))

    report = build_report(manifest, [result])

    assert report["status"] == "complete"
    assert report["unitResults"][0]["citations"][0]["matched_source_id"] == "A0001"
    assert (
        "source_not_found"
        in report["unitResults"][0]["citations"][0]["validation_flags"]
    )
    summary = render_summary(report)
    html = render_html(report)
    assert "Untrusted out-of-universe source claim" in summary
    assert "Untrusted out-of-universe source claim" in html
    assert "A0001" in summary and "A0001" in html


def test_unknown_source_is_a_citation_flag_not_a_unit_rejection() -> None:
    result = _result("P0001", _citation(matched_source_id="A9999"))

    report = build_report(_manifest("P0001"), [result])

    assert report["status"] == "complete"
    assert report["unitResults"][0]["citations"][0]["matched_source_id"] == "A9999"
    assert (
        "source_not_in_authority_universe"
        in report["unitResults"][0]["citations"][0]["validation_flags"]
    )
    summary = render_summary(report)
    html = render_html(report)
    assert "Untrusted out-of-universe source claim" in summary
    assert "Untrusted out-of-universe source claim" in html
    assert "A9999" in summary and "A9999" in html


def test_runner_style_malformed_evidence_is_retained_as_amber_report_row() -> None:
    raw = _result(
        "P0001",
        _citation(
            matched_source_id=7,
            source_resolution={"resolution": "not-a-source-resolution"},
            fabrication_indicators=[{"indicator": "not-a-fabrication-indicator"}],
            colliding_source_id={"source": "A0001"},
            existence_check_notes=["not a note"],
        ),
    )
    validation = validate_unit_result(raw, "P0001", authority_ids={"A0001"})
    assert validation["hard_errors"] == []
    assert terminal_schema_errors(validation) == []
    normalized = strict_normalized_report_result(validation)
    assert normalized is not None
    attempt = attempt_receipt(1, raw, validation)
    report = build_report(_manifest("P0001"), [normalized])

    row = report["unitResults"][0]["citations"][0]
    assert attempt["rawResult"] == raw
    assert raw["citations"][0]["matched_source_id"] == 7
    assert row["matched_source_id"] is None
    assert row["source_resolution"] == "not_supplied_search_unavailable"
    assert row["fabrication_indicators"] == []
    assert row["colliding_source_id"] is None
    assert row["existence_check_notes"] is None
    assert "malformed_source_id" in row["validation_flags"]
    assert "malformed_citation" in row["validation_flags"]
    assert row["severity"] == "amber"
    assert report["coverage"]["unitStates"] == [
        {"unitId": "P0001", "state": "complete"}
    ]


def test_runner_style_missing_evidence_is_retained_as_amber_report_row() -> None:
    raw_citation = _citation()
    del raw_citation["matched_source_id"]
    del raw_citation["source_resolution"]
    del raw_citation["fabrication_indicators"]
    raw = _result("P0001", raw_citation)

    validation = validate_unit_result(raw, "P0001", authority_ids={"A0001"})
    assert validation["hard_errors"] == []
    assert terminal_schema_errors(validation) == []
    normalized = strict_normalized_report_result(validation)
    assert normalized is not None
    report = build_report(_manifest("P0001"), [normalized])

    row = report["unitResults"][0]["citations"][0]
    assert row["matched_source_id"] is None
    assert row["source_resolution"] == "not_supplied_search_unavailable"
    assert row["fabrication_indicators"] == []
    assert "malformed_source_id" in row["validation_flags"]
    assert "malformed_citation" in row["validation_flags"]
    assert row["severity"] == "amber"


def test_runner_terminal_legal_fields_are_not_manufactured() -> None:
    raw = _result(
        "P0001",
        _citation(
            citation_kind=7,
            proposition={"claim": "bad"},
            source_excerpt=["not text"],
            recommended_changes={"change": "bad"},
            accuracy_of_source_characterization="not-a-judgment",
        ),
    )
    validation = validate_unit_result(raw, "P0001", authority_ids={"A0001"})

    assert validation["hard_errors"] == []
    normalized = validation["normalized"]
    assert normalized is not None
    assert terminal_schema_errors(validation)
    assert strict_normalized_report_result(validation) is None
    row = normalized["citations"][0]
    assert row["citation_kind"] == 7
    assert row["proposition"] == {"claim": "bad"}
    assert row["source_excerpt"] == ["not text"]
    assert row["recommended_changes"] == {"change": "bad"}
    assert row["accuracy_of_source_characterization"] == "not-a-judgment"


def test_missing_result_is_visible_in_v2_coverage_appendix() -> None:
    report = build_report(_manifest("P0001", "P0002"), [_result("P0001")])

    assert report["status"] == "incomplete"
    assert report["coverage"]["unitStates"] == [
        {"unitId": "P0001", "state": "no_citations_found"},
        {"unitId": "P0002", "state": "still_missing"},
    ]
    assert "P0002" in render_summary(report)


def test_renderer_exposes_v2_fields_and_escapes_payload() -> None:
    result = _result(
        "P0001",
        _citation(
            proposition='<script>alert("x")</script>',
            source_excerpt="<unsafe> excerpt",
            source_locator="¶ 4",
        ),
    )
    report = build_report(_manifest("P0001"), [result])

    summary = render_summary(report)
    html = render_html(report)

    assert "<script>alert" not in html
    assert "source_excerpt" in html
    assert "matched_source_id" in html
    assert "validation_flags" in html
    assert "Proposition:" in summary
    assert "&lt;unsafe&gt; excerpt" in summary


def test_html_keeps_designed_report_chrome() -> None:
    html = (
        ROOT / "skills/litigation/cite-check/assets/report-template.html"
    ).read_text(encoding="utf-8")

    assert "Cite-Check Ledger" in html
    assert (
        "Every citation, checked against the source that was actually supplied." in html
    )
    assert (
        "This report checks citations against the sources supplied for this run; "
        "it does not check later case history or replace full legal research." in html
    )
    assert "Iowan Old Style" in html
    assert "cc-masthead" in html
    assert "unitResults" in html
    assert "Caveats / Issues" in html
    assert "Coverage appendix" in html
    assert "workerResults" not in html
    assert "--caution" in html
    assert "✖" in html
    assert "Findings" in html
    assert "By authority" in html
    assert "Review status" in html
    assert "Do not file as-is" in html
    assert "The environment could not search" in html
    assert "Search did not find the case — it may be hallucinated" in html
    assert "Case found but not supplied for substantive checking" in html
    assert "real aggregator" not in html
    assert "All corpus material is synthetic or public domain" not in html
    assert "parked outside the alarm lane" not in html
    assert "triage.headline" in html
    assert 'complete ? "Complete"' not in html


def test_rendered_report_payload_leads_with_fabricated_case_names() -> None:
    carter = _citation(
        citation_as_written_in_unit="State v. Carter, 72 Ohio App.3d 553",
        matched_citation="State v. Carter, 72 Ohio App.3d 553",
        matched_source_id=None,
        source_excerpt=None,
        source_locator=None,
        source_resolution="not_supplied_search_unavailable",
        accuracy_of_source_characterization="source_not_found_unable_to_characterize",
    )
    milam = _citation(
        citation_as_written_in_unit="State v. Milam, 2022-Ohio-3965",
        matched_citation="State v. Milam, 2022-Ohio-3965",
        matched_source_id=None,
        source_excerpt=None,
        source_locator=None,
        source_resolution="not_supplied_search_unavailable",
        accuracy_of_source_characterization="source_not_found_unable_to_characterize",
    )
    manifest = _manifest("P0016", "P0017")
    manifest["authorities"] = _collision_authorities()
    report = build_report(manifest, [_result("P0016", carter), _result("P0017", milam)])
    html = render_html(report)
    headline = report["triage"]["headline"]
    assert "State v. Carter" in headline
    assert "State v. Milam" in headline
    assert headline in html
    assert report["triage"]["worst"] == "red"


def test_html_binds_v2_rows_and_union_coverage_appendix(tmp_path: Path) -> None:
    brief = tmp_path / "input/brief.md"
    brief.parent.mkdir(parents=True)
    brief.write_text(
        "The rule applies. Example v. Smith, 1 F.4th 2\n", encoding="utf-8"
    )
    manifest = _manifest("P0001", "P0002")
    result = _result("P0001", _citation(source_excerpt="The rule applies."))
    report = build_report(manifest, [result], source_root=tmp_path)

    html = render_html(report)

    assert "workerResults" not in html
    assert "Brief cite:" in html
    assert "Source excerpt:" in html
    assert "Matched source:" in html
    assert "Coverage appendix" in html
    assert '"unitId": "P0001"' in html
    assert '"unitId": "P0002"' in html
    assert '"state": "complete"' in html
    assert '"state": "still_missing"' in html
    assert "Caveats / Issues" in html
    assert "incomplete" in html
    assert report["unitResults"][0]["unitText"] == (
        "The rule applies. Example v. Smith, 1 F.4th 2"
    )


def test_input_result_is_not_mutated_by_normalization() -> None:
    result = _result("P0001", _citation(source_excerpt=None))
    original = copy.deepcopy(result)

    build_report(_manifest("P0001"), [result])

    assert result == original


def test_execution_metadata_is_allowlisted_and_bounded() -> None:
    report = build_report(
        _manifest("P0001"),
        [_result("P0001")],
        execution={
            "provider": "openai-codex",
            "surface": "local",
            "model": "gpt-5.6-luna",
            "reasoningEffort": "xhigh",
            "clientText": "must not enter the report",
            "absolutePath": "/private/client/brief.docx",
        },
    )

    assert report["execution"] == {
        "provider": "openai-codex",
        "surface": "local",
        "model": "gpt-5.6-luna",
        "reasoningEffort": "xhigh",
    }

    with pytest.raises(ReportInputError, match="bounded length"):
        build_report(
            _manifest("P0001"),
            [_result("P0001")],
            execution={"model": "x" * 161},
        )


def test_sense_check_flags_face_level_contradiction_without_dropping_rows() -> None:
    citation = _citation()
    contradictory = _citation(
        accuracy_of_source_characterization=(
            "objectively_false_or_unreasonable_characterization_of_source"
        )
    )
    report = build_report(
        _manifest("P0001"), [_result("P0001", citation, contradictory)]
    )

    assert len(report["unitResults"][0]["citations"]) == 2
    issues = report["senseCheck"]["issues"]
    assert any(item["code"] == "sense_check_face_contradiction" for item in issues)
    assert any(
        item["code"] == "sense_check_face_contradiction"
        for item in report["limitations"]
    )


def test_sense_check_repair_is_one_callback_and_one_bounded_pass(
    tmp_path: Path,
) -> None:
    brief = tmp_path / "input/brief.md"
    brief.parent.mkdir(parents=True)
    brief.write_text("Example v. Smith, 1 F.4th 2\n", encoding="utf-8")
    manifest = _manifest("P0001")
    report = build_report(manifest, [_result("P0001")], source_root=tmp_path)
    calls: list[tuple[str, ...]] = []

    def repair(unit_ids: tuple[str, ...]) -> dict[str, Any]:
        calls.append(unit_ids)
        return {"P0001": _result("P0001", _citation())}

    repaired = repair_report_once(report, manifest, repair, source_root=tmp_path)

    assert calls == [("P0001",)]
    assert repaired["senseCheck"]["retryRoundCount"] == 1
    assert repaired["senseCheck"]["targetedRepairCount"] == 1
    assert repaired["senseCheck"]["unresolvedIssueCount"] == 0
    assert repaired["status"] == "complete"

    repair_report_once(repaired, manifest, repair, source_root=tmp_path)
    assert calls == [("P0001",)]


@pytest.mark.parametrize(
    "text",
    [
        "See 42 U.S.C. § 1983.",
        "See Fed. R. Civ. P. 12(b)(6).",
        "See 123 N.Y.3d 456, 460.",
        "See 123 A.D.2d 456.",
        "See 456 S.E.2d 789.",
        "See 123 N.Y.S.3d 456.",
        "See Aplt. Appx. at 1007.",
        "See R. 4 at 12; https://example.test/opinion; Id.; supra note 3.",
    ],
)
def test_sense_check_detects_broader_advisory_citation_families(
    tmp_path: Path, text: str
) -> None:
    brief = tmp_path / "input/brief.md"
    brief.parent.mkdir(parents=True)
    brief.write_text(text + "\n", encoding="utf-8")
    report = build_report(_manifest("P0001"), [_result("P0001")], source_root=tmp_path)

    assert any(
        item["code"] == "sense_check_citation_gap"
        for item in report["senseCheck"]["issues"]
    )
