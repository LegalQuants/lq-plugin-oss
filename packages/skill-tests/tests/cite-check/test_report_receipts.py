from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
AGGREGATOR = ROOT / "skills/litigation/cite-check/scripts/aggregate_report.py"

spec = importlib.util.spec_from_file_location("cite_check_report_receipts", AGGREGATOR)
assert spec is not None and spec.loader is not None
aggregate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aggregate)


def _report(*, complete: bool = True) -> dict[str, Any]:
    manifest = {
        "schemaVersion": "cite-check.manifest.v2",
        "runId": "report-golden-001",
        "target": {
            "path": "input/brief.md",
            "fullDocumentRef": "input/brief.md",
            "displayName": "Synthetic filing brief",
        },
        "authorities": [
            {
                "sourceId": "A0001",
                "path": "authorities/example.docx",
                "filename": "example.docx",
                "readability": "readable",
                "contentIdentity": {
                    "caseName": "Example v. Smith",
                    "reporterCitation": "1 F.4th 2",
                },
            }
        ],
        "units": [
            {
                "unitId": "P0001",
                "kind": "paragraph",
                "path": "input/brief.md",
                "lineStart": 1,
                "lineEnd": 1,
                "footnoteAnchorUnitId": None,
            },
            {
                "unitId": "P0002",
                "kind": "paragraph",
                "path": "input/brief.md",
                "lineStart": 2,
                "lineEnd": 2,
                "footnoteAnchorUnitId": None,
            },
        ],
        "limitations": [],
    }
    citation = {
        "citation_as_written_in_unit": "Example v. Smith, 1 F.4th 2",
        "matched_citation": "Example v. Smith, 1 F.4th 2",
        "proposition": "The supplied authority supports the stated rule.",
        "matched_source_id": "A0001",
        "source_excerpt": "The court held that the rule applies.",
        "source_locator": "p. 1",
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
    results = (
        [
            {
                "unitId": "P0001",
                "disposition": "citations_found",
                "citations": [citation],
            }
        ]
        if complete
        else []
    )
    return aggregate.build_report(
        manifest,
        results,
        execution={
            "provider": "openai-codex",
            "surface": "local_cli",
            "model": "gpt-5.6-luna",
            "reasoningEffort": "xhigh",
            "startedAt": None,
            "finishedAt": None,
        },
        target_context={
            "intendedUse": "proposed filing",
            "tribunal": "Example Court",
            "jurisdiction": "Example jurisdiction",
            "proceduralPosture": "motion to dismiss",
            "asOfDate": "2026-08-17",
        },
    )


def test_receipts_are_visible_but_cannot_upgrade_core_completeness() -> None:
    report = _report(complete=False)
    final_coverage = {
        "schemaVersion": "cite-check.coverage.v2",
        "runId": report["runId"],
        "phase": "final",
        "unitStates": [
            {"unitId": "P0001", "state": "complete"},
            {"unitId": "P0002", "state": "still_missing"},
        ],
        "retriedUnitIds": [],
        "status": "incomplete",
        "isComplete": False,
    }

    aggregate.ingest_receipts(report, coverage=final_coverage)

    assert report["status"] == "incomplete"
    assert report["coverage"]["isComplete"] is False
    assert report["receipts"]["coverage"]["isComplete"] is False
    assert any("cannot change report completeness" in note for note in report["notes"])


def test_receipt_ingestion_preserves_runtime_retry_failure_and_cache_metadata() -> None:
    report = _report()
    capability = {
        "schemaVersion": "cite-check.runner-capability.v1",
        "provider": "openai-codex",
        "requestedModel": "gpt-5.6-luna",
        "requestedReasoningEffort": "xhigh",
        "selectedRuntime": "local_cli",
        "fallback": "native workers after local CLI preflight failure",
        "preflight": {"status": "failed", "reason": "runtime_startup"},
        "fallbackPreflight": {"status": "passed", "reason": "ok"},
        "cacheTelemetry": {
            "inputTokens": 1200,
            "cachedInputTokens": 900,
            "cacheWriteInputTokens": 300,
            "status": "observed",
        },
        "clientText": "do not copy this client text",
        "absolutePath": "/home/lawyer/client/brief.docx",
    }
    attempts = [
        {
            "unitId": "P0001",
            "attempts": [
                {
                    "attempt": 1,
                    "status": "rejected",
                    "code": "schema_error",
                    "retryable": True,
                    "message": "malformed result",
                },
                {"attempt": 2, "status": "accepted"},
            ],
        }
    ]
    failures = [
        {
            "unitId": "P0002",
            "code": "timeout",
            "retryable": True,
            "cancelled": False,
            "message": "/home/lawyer/client/secret.txt leaked text",
        }
    ]

    aggregate.ingest_receipts(
        report,
        capability=capability,
        attempts=attempts,
        failures=failures,
    )
    serialized = aggregate._canonical_json(report)

    assert report["receipts"]["capability"]["fallback"] == (
        "native workers after local CLI preflight failure"
    )
    assert report["receipts"]["capability"]["preflight"]["status"] == "failed"
    assert (
        report["receipts"]["capability"]["cacheTelemetry"]["cachedInputTokens"] == 900
    )
    assert report["receipts"]["attempts"][0]["unitId"] == "P0001"
    assert report["receipts"]["attempts"][0]["retryCount"] == 1
    assert report["receipts"]["attempts"][0]["failureReasons"] == ["schema_error"]
    assert report["receipts"]["failures"][0]["unitId"] == "P0002"
    assert report["receipts"]["failures"][0]["reason"] == "timeout"
    assert "/home/lawyer" not in serialized
    assert "do not copy this client text" not in serialized
    assert "secret.txt" not in serialized


def test_renderers_show_v2_context_sources_and_claimed_unverified_rows() -> None:
    report = _report()
    aggregate.ingest_receipts(
        report,
        capability={
            "schemaVersion": "cite-check.runner-capability.v1",
            "provider": "openai-codex",
            "requestedModel": "gpt-5.6-luna",
            "requestedReasoningEffort": "xhigh",
            "selectedRuntime": "local_cli",
            "cacheTelemetry": {"status": "unavailable"},
        },
    )
    report["unitResults"][0]["citations"][0]["validation_flags"] = ["missing_locator"]

    summary = aggregate.render_summary(report)
    html = aggregate.render_html(report)

    for fragment in (
        "Intended use",
        "proposed filing",
        "Tribunal",
        "Example Court",
        "Jurisdiction",
        "Procedural posture",
        "As-of date",
        "Example v. Smith",
        "readable",
        "authorities/example.docx",
        "Proposition",
        "Source locator",
        "Source excerpt",
        "missing_locator",
        "Caveats / Issues",
    ):
        assert fragment in summary
        assert fragment in html or fragment.replace("/", "\\u002f") in html


def test_capability_receipt_preserves_runner_schema_version() -> None:
    report = _report()
    aggregate.ingest_receipts(
        report,
        capability={
            "schemaVersion": "cite-check.runner-capability.v2",
            "provider": "openai-codex",
            "requestedModel": "gpt-5.6-luna",
            "requestedReasoningEffort": "xhigh",
            "selectedRuntime": "codex_exec",
        },
    )
    assert (
        report["receipts"]["capability"]["schemaVersion"]
        == "cite-check.runner-capability.v2"
    )


@pytest.mark.parametrize("provider", ["native", "anthropic"])
def test_capability_receipt_preserves_non_codex_provider(provider: str) -> None:
    report = _report()

    aggregate.ingest_receipts(
        report,
        capability={
            "schemaVersion": "cite-check.runner-capability.v2",
            "provider": provider,
            "selectedRuntime": "native_workers",
            "observedModel": "host-selected-model",
        },
    )

    assert report["receipts"]["capability"] == {
        "schemaVersion": "cite-check.runner-capability.v2",
        "provider": provider,
        "observedModel": "host-selected-model",
        "selectedRuntime": "native_workers",
    }
    assert not any("Capability receipt was ignored" in note for note in report["notes"])


def test_group_by_authority_markdown_uses_the_report_rollup() -> None:
    report = _report()
    grouped = aggregate.render_summary(report, group_by_authority=True)
    ungrouped = aggregate.render_summary(report, group_by_authority=False)
    assert "## Results by authority" in grouped
    assert "`A0001`" in grouped
    assert "## Results by authority" not in ungrouped
    assert "## Citation-level results" in ungrouped


def test_write_artifacts_rejects_symlinked_output_dir(tmp_path: Path) -> None:
    report = _report()
    boundary = tmp_path / "run"
    boundary.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    output_dir = boundary / "out"
    output_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(aggregate.ReportInputError, match="symlink"):
        aggregate.write_artifacts(report, output_dir)

    assert list(outside.iterdir()) == []


def test_write_artifacts_rejects_symlinked_ancestor(tmp_path: Path) -> None:
    report = _report()
    boundary = tmp_path / "run"
    boundary.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    nested = boundary / "nested"
    nested.symlink_to(outside, target_is_directory=True)
    output_dir = nested / "out"

    with pytest.raises(aggregate.ReportInputError, match="symlink"):
        aggregate.write_artifacts(report, output_dir)

    assert list(outside.iterdir()) == []


def test_write_artifacts_writes_into_a_normal_directory(tmp_path: Path) -> None:
    report = _report()
    output_dir = tmp_path / "run" / "out"

    artifacts = aggregate.write_artifacts(report, output_dir)

    assert artifacts["json"].is_file()
    assert artifacts["markdown"].is_file()
    assert artifacts["html"].is_file()
    assert artifacts["json"].parent == output_dir
    assert output_dir.is_dir()
    assert not output_dir.is_symlink()
