from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
RUNNER_PATH = ROOT / "skills/litigation/cite-check/scripts/cite_check.py"
SCHEMA_PATH = (
    ROOT / "skills/litigation/cite-check/schemas/cite-check-unit-result.schema.json"
)
SPEC = importlib.util.spec_from_file_location("cite_check_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)

AGGREGATOR_PATH = ROOT / "skills/litigation/cite-check/scripts/aggregate_report.py"
AGGREGATOR_SPEC = importlib.util.spec_from_file_location(
    "cite_check_runner_aggregator", AGGREGATOR_PATH
)
assert AGGREGATOR_SPEC and AGGREGATOR_SPEC.loader
aggregator = importlib.util.module_from_spec(AGGREGATOR_SPEC)
sys.modules[AGGREGATOR_SPEC.name] = aggregator
AGGREGATOR_SPEC.loader.exec_module(aggregator)


def _manifest(tmp_path: Path, count: int = 8) -> Path:
    source = tmp_path / "prepared/brief.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "\n".join(f"Prepared unit {index}." for index in range(1, count + 1)) + "\n",
        encoding="utf-8",
    )
    authority = tmp_path / "prepared/authorities/example.txt"
    authority.parent.mkdir(parents=True, exist_ok=True)
    authority.write_text("The rule applies.\n", encoding="utf-8")
    units: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        units.append(
            {
                "unitId": f"P{index:04d}",
                "kind": "paragraph",
                "path": "prepared/brief.md",
                "lineStart": index,
                "lineEnd": index,
                "footnoteAnchorUnitId": "P0001" if index == count else None,
            }
        )
    payload = {
        "schemaVersion": "cite-check.manifest.v2",
        "runId": "runner-test-001",
        "target": {
            "path": "prepared/brief.md",
            "fullDocumentRef": "prepared/brief.md",
            "displayName": "brief.md",
        },
        "authorities": [
            {
                "sourceId": "A0001",
                "path": "prepared/authorities/example.txt",
                "filename": "example.txt",
                "readability": "readable",
                "contentIdentity": {"caseName": "Example v. Smith"},
            }
        ],
        "units": units,
        "limitations": [],
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest


def _result(unit_id: str, *, found: bool = True) -> dict[str, Any]:
    citations: list[dict[str, Any]] = []
    if found:
        citations.append(
            {
                "citation_as_written_in_unit": "Example v. Smith, 1 F.4th 2",
                "matched_citation": "Example v. Smith, 1 F.4th 2",
                "proposition": None,
                "matched_source_id": "A0001",
                "source_excerpt": "The rule applies.",
                "source_locator": "p. 1",
                "citation_kind": "case",
                "source_resolution": "matched_supplied_source",
                "fabrication_indicators": [],
                "accuracy_of_source_characterization": (
                    "confirmed_fair_characterization_of_source"
                ),
                "pincite_accuracy": "NA_no_pincite_for_this_citation",
                "accuracy_of_direct_quotation": (
                    "NA_no_direct_quotation_for_this_citation"
                ),
                "recommended_changes": None,
            }
        )
    return {
        "unitId": unit_id,
        "disposition": "citations_found" if found else "no_citations_found",
        "citations": citations,
    }


def _environment_receipt(
    tmp_path: Path, *, include_legacy_package_fields: bool = False
) -> Path:
    receipt = {
        "schemaVersion": "cite-check.environment-capability.v1",
        "local": {
            "filesystem": {"status": "pass"},
            "subprocess": {"status": "pass"},
            "processFanout": {"status": "pass", "width": 2},
        },
        "runtimes": {
            "codex": {
                "available": True,
                "help": {
                    "status": "pass",
                    "flags": {
                        "exec": True,
                        "ephemeral": True,
                        "json": True,
                        "readOnlySandbox": True,
                        "outputSchema": True,
                    },
                },
                "canary": {"status": "not_run", "reason": "passive_probe"},
            }
        },
        "probe": {
            "modelCalled": False,
            "matterContentUsed": False,
        },
        "recommendation": {"path": "packaged_codex_runner"},
    }
    if include_legacy_package_fields:
        receipt["package"] = {
            "openaiPackage": False,
            "name": "renamed-plugin",
            "version": "legacy",
        }
    path = tmp_path / "environment-receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


class FakeRuntime:
    surface = "fake"
    model = "gpt-5.6-luna"
    effort = "xhigh"

    def __init__(self, behavior: Any = None) -> None:
        self.behavior = behavior or (lambda task, attempt: _result(task.unit["unitId"]))
        self.calls: dict[str, int] = {}
        self.active = 0
        self.max_active = 0
        self.tasks: list[Any] = []

    async def run(self, task: Any) -> Any:
        unit_id = task.unit["unitId"]
        attempt = self.calls.get(unit_id, 0)
        self.calls[unit_id] = attempt + 1
        self.tasks.append(task)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.005)
            value = self.behavior(task, attempt)
            if isinstance(value, runner.WorkerResponse):
                return value
            return runner.WorkerResponse(
                payload=value,
                model=self.model,
                effort=self.effort,
            )
        finally:
            self.active -= 1

    async def close(self) -> None:
        return None


def test_worker_timeout_is_bounded_and_configurable(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, count=1)

    defaults = runner._parser().parse_args(
        ["--manifest", str(manifest), "--output-dir", str(tmp_path / "default")]
    )
    assert defaults.worker_timeout_seconds == 900

    with pytest.raises(runner.RunnerError, match="worker timeout must be between"):
        runner.run_manifest(
            manifest,
            tmp_path / "too-short",
            runtime=FakeRuntime(),
            worker_timeout_seconds=29,
        )

    args = runner._parser().parse_args(
        [
            "--manifest",
            str(manifest),
            "--output-dir",
            str(tmp_path / "configured"),
            "--worker-timeout-seconds",
            "900",
        ]
    )
    assert args.worker_timeout_seconds == 900


def _run(
    tmp_path: Path, runtime: Any, *, count: int = 8, **kwargs: Any
) -> dict[str, Any]:
    return runner.run_manifest(
        _manifest(tmp_path, count=count),
        tmp_path / "run/results",
        runtime=runtime,
        **kwargs,
    )


def test_default_fanout_is_six_wide_and_covers_every_unit(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    summary = _run(tmp_path, runtime)

    assert summary["exitCode"] == 0
    assert runtime.max_active == 6
    assert summary["coverage"]["schemaVersion"] == "cite-check.coverage.v2"
    assert {item["state"] for item in summary["coverage"]["unitStates"]} == {"complete"}
    assert len(list((tmp_path / "run/results/results").glob("P*.json"))) == 8


def test_documented_runner_to_aggregator_directory_handoff_is_complete(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path, count=1)
    run_output = tmp_path / "run/results"
    runner.run_manifest(manifest, run_output, runtime=FakeRuntime(), retries=0)

    report_output = tmp_path / "run/report"
    exit_code = aggregator.main(
        [
            "--manifest",
            str(manifest),
            "--results",
            str(run_output / "results"),
            "--receipt-dir",
            str(run_output),
            "--output-dir",
            str(report_output),
        ]
    )

    assert exit_code == 0
    report = json.loads((report_output / "cite-check-results.json").read_text())
    assert report["status"] == "complete"
    assert [item["unitId"] for item in report["unitResults"]] == ["P0001"]
    assert report["coverage"]["unitStates"] == [
        {"unitId": "P0001", "state": "complete"}
    ]


def test_worker_envelope_contains_unit_context_anchor_paths_and_lines(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime()
    _run(tmp_path, runtime, concurrency=1)

    assigned = next(task for task in runtime.tasks if task.unit["unitId"] == "P0008")
    assert assigned.unit_text == "Prepared unit 8."
    assert assigned.unit_path == tmp_path / "prepared/brief.md"
    assert assigned.context["footnoteAnchor"]["unitId"] == "P0001"
    assert len(assigned.context["before"]) == 5
    assert assigned.context["after"] == []
    assert str(tmp_path / "prepared/brief.md") in assigned.prompt
    assert '"lineStart": 8' in assigned.prompt
    assert '"lineEnd": 8' in assigned.prompt
    assert '"footnoteAnchorUnitId": "P0001"' in assigned.prompt
    assert '"citations": [' not in assigned.prompt
    assert "authoritySourceIds" not in assigned.prompt


def test_prompt_materialization_contains_unit_prompt_and_rubric(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    _run(tmp_path, runtime, concurrency=1)
    prompt = (tmp_path / "prompt.md").read_text(encoding="utf-8")

    assert "# Unit review prompt" in prompt
    assert "# Cite-check judgment rubric" in prompt
    assert "cite-check-unit-result.schema.json" in prompt
    assert "cite-check-work-unit-result.schema.json" not in prompt
    assert '"disposition"' in prompt


def test_empty_or_missing_parent_authority_candidates_do_not_filter_worker_rows(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path, count=1)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["authorities"] = []
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    runtime = FakeRuntime(lambda task, attempt: _result(task.unit["unitId"]))

    summary = runner.run_manifest(manifest, tmp_path / "run/results", runtime=runtime)

    assert summary["exitCode"] == 0
    result = json.loads((tmp_path / "run/results/results/P0001.json").read_text())
    assert result["citations"][0]["matched_source_id"] == "A0001"


def test_no_citations_found_is_a_terminal_unit_receipt(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        lambda task, attempt: _result(task.unit["unitId"], found=False)
    )
    summary = _run(tmp_path, runtime)

    assert summary["exitCode"] == 0
    assert {item["state"] for item in summary["coverage"]["unitStates"]} == {
        "no_citations_found"
    }


def test_same_run_resume_skips_terminal_receipts_and_retries_only_failed_units(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path, count=3)

    def first_behavior(task: Any, attempt: int) -> Any:
        if task.unit["unitId"] == "P0002":
            return runner.WorkerResponse(
                failure=runner.WorkerFailure("timeout", "worker timed out")
            )
        return _result(task.unit["unitId"], found=task.unit["unitId"] != "P0003")

    first_runtime = FakeRuntime(first_behavior)
    output = tmp_path / "run/results"
    first = runner.run_manifest(manifest, output, runtime=first_runtime, retries=0)

    assert first["coverage"]["status"] == "incomplete"
    assert set(first_runtime.calls) == {"P0001", "P0002", "P0003"}

    second_runtime = FakeRuntime()
    second = runner.run_manifest(manifest, output, runtime=second_runtime, retries=0)

    assert set(second_runtime.calls) == {"P0002"}
    assert second["coverage"]["status"] == "complete"
    assert second["coverage"]["retriedUnitIds"] == ["P0002"]
    assert json.loads((output / "results/P0001.json").read_text())["unitId"] == "P0001"
    assert not (output / "failures/P0002.json").exists()
    attempts = json.loads((output / "attempts/P0002.json").read_text())["attempts"]
    assert [item["attempt"] for item in attempts] == [1, 2]


def test_same_run_resume_retries_schema_invalid_terminal_receipt(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path, count=1)
    output = tmp_path / "run/results"
    output.joinpath("results").mkdir(parents=True)
    malformed = _result("P0001", found=False)
    malformed["unexpected"] = "not part of the worker contract"
    (output / "results/P0001.json").write_text(json.dumps(malformed), encoding="utf-8")

    runtime = FakeRuntime()
    summary = runner.run_manifest(manifest, output, runtime=runtime, retries=0)

    assert runtime.calls == {"P0001": 1}
    assert summary["coverage"]["status"] == "complete"
    stored = json.loads((output / "results/P0001.json").read_text())
    assert "unexpected" not in stored


def test_resume_rejects_changed_manifest_or_input_identity(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, count=1)
    output = tmp_path / "run/results"
    runner.run_manifest(manifest, output, runtime=FakeRuntime(), retries=0)

    changed = json.loads(manifest.read_text(encoding="utf-8"))
    changed["runId"] = "runner-test-changed"
    manifest.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(runner.RunnerError, match="run identity"):
        runner.run_manifest(manifest, output, runtime=FakeRuntime(), retries=0)


def test_nested_symlinked_receipt_directory_is_rejected(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, count=1)
    output = tmp_path / "run/results"
    output.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (output / "results").symlink_to(outside, target_is_directory=True)

    with pytest.raises(runner.RunnerError, match="must not be a symlink"):
        runner.run_manifest(manifest, output, runtime=FakeRuntime(), retries=0)


def test_attempt_receipt_records_requested_and_observed_runtime_values(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime()
    runtime.model = "host-observed-model"
    runtime.effort = "medium"
    runner.run_manifest(
        _manifest(tmp_path, count=1),
        tmp_path / "run/results",
        runtime=runtime,
        model="requested-model",
        effort="xhigh",
        retries=0,
    )

    attempt = json.loads((tmp_path / "run/results/attempts/P0001.json").read_text())[
        "attempts"
    ][0]
    assert attempt["requestedModel"] == "requested-model"
    assert attempt["requestedReasoningEffort"] == "xhigh"
    assert attempt["observedModel"] == "host-observed-model"
    assert attempt["observedReasoningEffort"] == "medium"


def test_fresh_schema_invalid_result_consumes_retry_budget(tmp_path: Path) -> None:
    def behavior(task: Any, attempt: int) -> Any:
        result = _result(task.unit["unitId"], found=False)
        if attempt == 0:
            result["unexpected"] = "not part of the worker contract"
        return result

    runtime = FakeRuntime(behavior)
    summary = runner.run_manifest(
        _manifest(tmp_path, count=1),
        tmp_path / "run/results",
        runtime=runtime,
        retries=1,
    )

    assert runtime.calls == {"P0001": 2}
    assert summary["coverage"]["status"] == "complete"
    attempts = json.loads((tmp_path / "run/results/attempts/P0001.json").read_text())[
        "attempts"
    ]
    assert attempts[0]["hardErrors"][0]["code"] == "schema_error"


def test_targeted_evidence_defect_is_retried_with_concise_validator_feedback(
    tmp_path: Path,
) -> None:
    prompts: list[str] = []

    def behavior(task: Any, attempt: int) -> Any:
        prompts.append(task.prompt)
        result = _result(task.unit["unitId"])
        if attempt == 0:
            result["citations"][0]["source_excerpt"] = None
            result["citations"][0]["source_locator"] = None
        return result

    runtime = FakeRuntime(behavior)
    summary = _run(tmp_path, runtime, count=1, retries=1)

    assert summary["exitCode"] == 0
    assert runtime.calls == {"P0001": 2}
    assert "Validator feedback for this retry" in prompts[1]
    assert "source_excerpt" in prompts[1]
    assert "source_locator" in prompts[1]
    attempts = json.loads((tmp_path / "run/results/attempts/P0001.json").read_text())[
        "attempts"
    ]
    assert len(attempts) == 2
    assert attempts[0]["rawResult"]["citations"][0]["source_excerpt"] is None
    assert attempts[0]["retryKind"] == "targeted_evidence_repair"
    final_result = json.loads((tmp_path / "run/results/results/P0001.json").read_text())
    assert final_result["citations"][0]["source_excerpt"] == "The rule applies."


def test_targeted_evidence_retry_is_capped_and_accepts_unresolved_result(
    tmp_path: Path,
) -> None:
    prompts: list[str] = []

    def behavior(task: Any, attempt: int) -> Any:
        prompts.append(task.prompt)
        result = _result(task.unit["unitId"])
        result["citations"][0]["matched_source_id"] = "A9999"
        return result

    runtime = FakeRuntime(behavior)
    summary = _run(tmp_path, runtime, count=1, retries=3)

    assert summary["exitCode"] == 0
    assert runtime.calls == {"P0001": 2}
    assert len(prompts) == 2
    assert "supplied authority" in prompts[1]
    attempts = json.loads((tmp_path / "run/results/attempts/P0001.json").read_text())[
        "attempts"
    ]
    assert len(attempts) == 2
    result = json.loads((tmp_path / "run/results/results/P0001.json").read_text())
    assert (
        "source_not_in_authority_universe" in result["citations"][0]["validation_flags"]
    )


def test_malformed_source_id_is_retried_once_then_retained_amber(
    tmp_path: Path,
) -> None:
    def behavior(task: Any, attempt: int) -> Any:
        result = _result(task.unit["unitId"])
        result["citations"][0]["matched_source_id"] = 7
        return result

    runtime = FakeRuntime(behavior)
    summary = _run(tmp_path, runtime, count=1, retries=3)

    assert summary["exitCode"] == 0
    assert runtime.calls == {"P0001": 2}
    result_path = tmp_path / "run/results/results/P0001.json"
    result = json.loads(result_path.read_text())
    assert result["citations"][0]["matched_source_id"] == 7
    assert "malformed_source_id" in result["citations"][0]["validation_flags"]
    attempts = json.loads((tmp_path / "run/results/attempts/P0001.json").read_text())[
        "attempts"
    ]
    assert attempts[0]["retryKind"] == "targeted_evidence_repair"
    assert len(attempts) == 2


def test_missing_evidence_links_are_retried_once_then_retained_amber(
    tmp_path: Path,
) -> None:
    def behavior(task: Any, attempt: int) -> Any:
        result = _result(task.unit["unitId"])
        citation = result["citations"][0]
        del citation["matched_source_id"]
        del citation["source_resolution"]
        del citation["fabrication_indicators"]
        return result

    runtime = FakeRuntime(behavior)
    summary = _run(tmp_path, runtime, count=1, retries=3)

    assert summary["exitCode"] == 0
    assert runtime.calls == {"P0001": 2}
    result = json.loads((tmp_path / "run/results/results/P0001.json").read_text())
    assert "matched_source_id" not in result["citations"][0]
    assert "source_resolution" not in result["citations"][0]
    assert "fabrication_indicators" not in result["citations"][0]
    attempts = json.loads((tmp_path / "run/results/attempts/P0001.json").read_text())[
        "attempts"
    ]
    assert attempts[0]["retryKind"] == "targeted_evidence_repair"
    assert len(attempts) == 2


def test_substantive_citation_disagreement_is_not_targeted_retried(
    tmp_path: Path,
) -> None:
    def behavior(task: Any, attempt: int) -> Any:
        result = _result(task.unit["unitId"])
        result["citations"][0]["accuracy_of_source_characterization"] = (
            "objectively_false_or_unreasonable_characterization_of_source"
        )
        return result

    runtime = FakeRuntime(behavior)
    summary = _run(tmp_path, runtime, count=1, retries=1)

    assert summary["exitCode"] == 0
    assert runtime.calls == {"P0001": 1}
    attempts = json.loads((tmp_path / "run/results/attempts/P0001.json").read_text())[
        "attempts"
    ]
    assert len(attempts) == 1
    assert "retryKind" not in attempts[0]


def test_targeted_retry_attempts_survive_same_run_resume(
    tmp_path: Path,
) -> None:
    def first_behavior(task: Any, attempt: int) -> Any:
        if attempt == 0:
            result = _result(task.unit["unitId"])
            result["citations"][0]["source_excerpt"] = None
            return result
        return runner.WorkerResponse(
            failure=runner.WorkerFailure(
                "cancelled", "worker cancelled", cancelled=True
            )
        )

    output = tmp_path / "run/results"
    first_runtime = FakeRuntime(first_behavior)
    first = runner.run_manifest(
        _manifest(tmp_path, count=1), output, runtime=first_runtime, retries=1
    )

    assert first["coverage"]["status"] == "incomplete"
    attempts = json.loads((output / "attempts/P0001.json").read_text())["attempts"]
    assert [item["attempt"] for item in attempts] == [1, 2]
    assert attempts[0]["retryKind"] == "targeted_evidence_repair"

    second_runtime = FakeRuntime()
    second = runner.run_manifest(
        _manifest(tmp_path, count=1), output, runtime=second_runtime, retries=0
    )

    assert second["coverage"]["status"] == "complete"
    assert second_runtime.calls == {"P0001": 1}
    attempts = json.loads((output / "attempts/P0001.json").read_text())["attempts"]
    assert [item["attempt"] for item in attempts] == [1, 2, 3]


def test_retryable_failure_is_retried_and_marked_in_coverage(tmp_path: Path) -> None:
    def behavior(task: Any, attempt: int) -> Any:
        if task.unit["unitId"] == "P0001" and attempt == 0:
            return runner.WorkerResponse(
                failure=runner.WorkerFailure(
                    "transient_runtime", "busy", retryable=True
                )
            )
        return _result(task.unit["unitId"])

    runtime = FakeRuntime(behavior)
    summary = _run(tmp_path, runtime)

    assert summary["exitCode"] == 0
    assert runtime.calls["P0001"] == 2
    assert summary["coverage"]["retriedUnitIds"] == ["P0001"]


def test_malformed_result_can_retry_but_permanent_failure_is_incomplete(
    tmp_path: Path,
) -> None:
    def behavior(task: Any, attempt: int) -> Any:
        if task.unit["unitId"] == "P0001":
            return {} if attempt == 0 else _result(task.unit["unitId"])
        if task.unit["unitId"] == "P0002":
            return runner.WorkerResponse(
                failure=runner.WorkerFailure("authentication", "unavailable")
            )
        return _result(task.unit["unitId"])

    summary = _run(tmp_path, FakeRuntime(behavior), retries=1)

    assert summary["exitCode"] == 1
    states = {
        item["unitId"]: item["state"] for item in summary["coverage"]["unitStates"]
    }
    assert states["P0001"] == "complete"
    assert states["P0002"] == "failed"


def test_cancelled_worker_uses_cancel_exit_and_failure_state(tmp_path: Path) -> None:
    def behavior(task: Any, attempt: int) -> Any:
        if task.unit["unitId"] == "P0001":
            raise asyncio.CancelledError()
        return _result(task.unit["unitId"])

    summary = _run(tmp_path, FakeRuntime(behavior), retries=0)

    assert summary["exitCode"] == 130
    states = {
        item["unitId"]: item["state"] for item in summary["coverage"]["unitStates"]
    }
    assert states["P0001"] == "failed"


def test_cli_unavailable_is_explicit(tmp_path: Path) -> None:
    summary = runner.run_manifest(
        _manifest(tmp_path),
        tmp_path / "run/results",
        runtime_name="cli",
        executable=str(tmp_path / "missing-codex"),
    )

    assert summary["exitCode"] == 3
    assert summary["coverage"]["isComplete"] is False
    assert (
        json.loads((tmp_path / "run/results/capability.json").read_text())[
            "selectedRuntime"
        ]
        is None
    )


def test_codex_runtime_requires_environment_probe_receipt(
    tmp_path: Path,
) -> None:
    class RecordingRuntime(FakeRuntime):
        surface = "codex_exec"

    runtime = RecordingRuntime()
    with pytest.raises(runner.RunnerError, match="environment probe receipt"):
        _run(tmp_path, runtime, retries=0)
    assert runtime.calls == {}


@pytest.mark.parametrize(
    "include_legacy_package_fields",
    [False, True],
    ids=["v1", "legacy-package-fields"],
)
def test_codex_runtime_starts_after_capability_receipt_passes(
    include_legacy_package_fields: bool,
    tmp_path: Path,
) -> None:
    class RecordingRuntime(FakeRuntime):
        surface = "codex_exec"

    runtime = RecordingRuntime()
    summary = _run(
        tmp_path,
        runtime,
        count=1,
        retries=0,
        environment_receipt=_environment_receipt(
            tmp_path,
            include_legacy_package_fields=include_legacy_package_fields,
        ),
    )

    assert summary["exitCode"] == 0
    assert runtime.calls == {"P0001": 1}


def test_codex_runtime_rejects_receipt_with_failed_capability(
    tmp_path: Path,
) -> None:
    class RecordingRuntime(FakeRuntime):
        surface = "codex_exec"

    receipt = _environment_receipt(tmp_path)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["local"]["subprocess"]["status"] = "fail"
    receipt.write_text(json.dumps(payload), encoding="utf-8")

    runtime = RecordingRuntime()
    with pytest.raises(runner.RunnerError, match="environment probe receipt"):
        _run(tmp_path, runtime, retries=0, environment_receipt=receipt)
    assert runtime.calls == {}


def test_malformed_environment_probe_receipt_fails_before_codex_runtime(
    tmp_path: Path,
) -> None:
    class RecordingRuntime(FakeRuntime):
        surface = "codex_exec"

    receipt = tmp_path / "environment-receipt.json"
    receipt.write_text('{"schemaVersion": "wrong"}', encoding="utf-8")
    runtime = RecordingRuntime()
    with pytest.raises(runner.RunnerError, match="environment probe receipt"):
        _run(tmp_path, runtime, retries=0, environment_receipt=receipt)
    assert runtime.calls == {}


def test_packaged_runtime_rejects_arbitrary_executable_wrapper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    canonical = tmp_path / "codex"
    canonical.write_text("#!/bin/sh\n", encoding="utf-8")
    canonical.chmod(0o755)
    wrapper = tmp_path / "codex-wrapper"
    wrapper.write_text('#!/bin/sh\nexec codex "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)

    def find_cli(candidate: str | None = None) -> str | None:
        return str(canonical) if candidate in {None, str(canonical)} else None

    monkeypatch.setattr(runner, "_find_cli", find_cli)
    runtime = runner.CliRuntime(
        str(wrapper),
        "gpt-5.6-luna",
        "xhigh",
        SCHEMA_PATH,
        tmp_path,
    )

    with pytest.raises(runner.RunnerError, match="arbitrary wrappers are rejected"):
        runner._validate_packaged_runtime(runtime)


def test_installed_codex_without_probe_receipt_fails_before_runtime_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runner, "_find_cli", lambda executable: "/usr/bin/codex")
    with pytest.raises(runner.RunnerError, match="environment probe receipt"):
        runner.run_manifest(
            _manifest(tmp_path, count=1),
            tmp_path / "run/results",
            runtime_name="cli",
            executable="codex",
            retries=0,
        )


def test_runner_rejects_output_outside_dedicated_run_directory(tmp_path: Path) -> None:
    with pytest.raises(runner.RunnerError, match="inside the dedicated"):
        runner.run_manifest(
            _manifest(tmp_path), tmp_path.parent / "outside", runtime=FakeRuntime()
        )


def test_atomic_receipt_write_does_not_follow_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("preserve\n", encoding="utf-8")
    output = tmp_path / "out"
    output.mkdir()
    (output / "receipt.json").symlink_to(source)

    runner._write_json(output / "receipt.json", {"ok": True}, {source.resolve()})

    assert source.read_text(encoding="utf-8") == "preserve\n"
    assert json.loads((output / "receipt.json").read_text()) == {"ok": True}


def test_help_calls_runner_recommended_and_documents_host_fallback() -> None:
    help_text = runner._parser().format_help()
    normalized = " ".join(help_text.split())
    assert "recommended six-wide, per-unit" in normalized
    assert "3-12 logical-segment host fallback" in normalized
    assert "sequential processing is the last resort" in normalized
    assert "--environment-receipt" in normalized
    assert "--authorize-codex" not in normalized
    assert "--codex-executable" not in normalized


def _progress_lines(stderr: str) -> list[str]:
    return [
        line for line in stderr.splitlines() if line.startswith("cite-check runner:")
    ]


def test_progress_startup_and_completion_once_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime = FakeRuntime()
    summary = runner.run_manifest(
        _manifest(tmp_path, count=3),
        tmp_path / "run/results",
        runtime=runtime,
        concurrency=2,
    )

    captured = capsys.readouterr()
    lines = _progress_lines(captured.err)
    assert captured.out == ""
    assert summary["exitCode"] == 0
    assert len(lines) == 2
    output_dir = tmp_path / "run/results"
    assert lines[0] == (
        f"cite-check runner: 3 units, concurrency 2, output {output_dir}"
    )
    assert re.fullmatch(
        r"cite-check runner: done — 3/3 units, 0 failed, \d+m\d+s",
        lines[1],
    )


def test_progress_counts_failures_on_completion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def behavior(task: Any, attempt: int) -> Any:
        if task.unit["unitId"] == "P0002":
            return runner.WorkerResponse(
                failure=runner.WorkerFailure("authentication", "unavailable")
            )
        return _result(task.unit["unitId"])

    summary = runner.run_manifest(
        _manifest(tmp_path, count=3),
        tmp_path / "run/results",
        runtime=FakeRuntime(behavior),
        concurrency=2,
        retries=0,
    )

    lines = _progress_lines(capsys.readouterr().err)
    assert summary["exitCode"] == 1
    assert re.fullmatch(
        r"cite-check runner: done — 3/3 units, 1 failed, \d+m\d+s",
        lines[-1],
    )


def test_progress_heartbeat_uses_counters_and_stops_when_idle() -> None:
    stream = io.StringIO()
    progress = runner.RunnerProgress(
        total=4,
        concurrency=2,
        output_dir=Path("/tmp/cite-check-run"),
        interval=0.05,
        stream=stream,
    )
    progress.running = 2
    progress.complete = 1
    stop = asyncio.Event()

    async def drive() -> None:
        task = asyncio.create_task(runner._progress_heartbeat(progress, stop))
        await asyncio.sleep(0.12)
        progress.running = 0
        progress.complete = 4
        stop.set()
        await task

    asyncio.run(drive())

    heartbeats = [
        line
        for line in stream.getvalue().splitlines()
        if "running" in line and "complete" in line
    ]
    assert heartbeats
    assert all(
        line == "cite-check runner: 2 running, 1/4 complete (0 failed), 1 remaining"
        for line in heartbeats
    )
    assert runner.HEARTBEAT_INTERVAL_S == 30.0


def test_progress_quiet_keeps_startup_and_completion_without_heartbeats() -> None:
    stream = io.StringIO()
    progress = runner.RunnerProgress(
        total=2,
        concurrency=2,
        output_dir=Path("/tmp/cite-check-run"),
        quiet=True,
        interval=0.05,
        stream=stream,
    )
    progress.running = 2
    stop = asyncio.Event()

    async def drive() -> None:
        progress.emit_startup()
        task = asyncio.create_task(runner._progress_heartbeat(progress, stop))
        await asyncio.sleep(0.12)
        stop.set()
        await task
        progress.running = 0
        progress.complete = 2
        progress.emit_completion()

    asyncio.run(drive())

    lines = stream.getvalue().splitlines()
    assert lines[0].startswith("cite-check runner: 2 units, concurrency 2, output ")
    assert lines[-1].startswith("cite-check runner: done — 2/2 units, 0 failed,")
    assert all("running" not in line for line in lines)


def test_cli_json_stdout_is_summary_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest(tmp_path, count=1)
    output = tmp_path / "run/results"
    monkeypatch.setattr(runner, "_find_cli", lambda _executable=None: None)
    exit_code = runner.main(
        [
            "--manifest",
            str(manifest),
            "--output-dir",
            str(output),
            "--runtime",
            "cli",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert exit_code == runner.EXIT_UNAVAILABLE
    assert summary["schemaVersion"] == "cite-check.runner-summary.v2"
    assert captured.out.endswith("\n")
    assert captured.out.count("\n") == 1
    assert captured.out.lstrip().startswith("{")
    assert "cite-check runner:" in captured.err
