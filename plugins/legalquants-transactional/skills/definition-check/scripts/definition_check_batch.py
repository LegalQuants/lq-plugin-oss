"""Run multiple independent Definition Checks in one Python process."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, Optional

from _runtime_gate import require_supported_python

require_supported_python()

from definition_check.workspace import WorkspaceError, require_disjoint_paths


def _load_single_main():
    script = Path(__file__).with_name("definition_check.py")
    spec = importlib.util.spec_from_file_location(
        "_definition_check_single_cli", script
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Definition Check entry point: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


_single_main = _load_single_main()


BATCH_SCHEMA_VERSION = "definition-check-batch-v1"
TOP_LEVEL_FIELDS = {"schema_version", "jobs"}
JOB_FIELDS = {
    "id",
    "input",
    "output_dir",
    "work_dir",
    "agent_bundle",
    "common_terms",
    "include_internal_traces",
    "qa_annotated_document",
    "debug_telemetry",
}


class BatchManifestError(ValueError):
    """Raised when the batch contract is malformed or unsafe."""


@dataclass(frozen=True)
class BatchJob:
    job_id: str
    input_path: Path
    output_dir: Path
    work_dir: Optional[Path]
    agent_bundle: Optional[Path]
    common_terms: tuple[str, ...]
    include_internal_traces: bool
    qa_annotated_document: bool
    debug_telemetry: bool


def _reject(message: str) -> NoReturn:
    raise BatchManifestError(message)


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _reject(f"{label} must be a non-empty string")
    return value


def _optional_boolean(item: dict[str, object], field: str) -> bool:
    value = item.get(field, False)
    if not isinstance(value, bool):
        _reject(f"{field} must be a boolean")
    return value


def _path(value: object, label: str, manifest_dir: Path) -> Path:
    path = Path(_required_string(value, label))
    if not path.is_absolute():
        path = manifest_dir / path
    return path.resolve()


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def load_manifest(path: Path) -> tuple[BatchJob, ...]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BatchManifestError(f"cannot read batch manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BatchManifestError(
            f"batch manifest is malformed JSON at line {exc.lineno}, column {exc.colno}"
        ) from exc
    if not isinstance(value, dict):
        _reject("batch manifest must be a JSON object")
    unknown = sorted(set(value) - TOP_LEVEL_FIELDS)
    if unknown:
        _reject(f"batch manifest contains unknown fields: {', '.join(unknown)}")
    if value.get("schema_version") != BATCH_SCHEMA_VERSION:
        _reject(f"schema_version must equal {BATCH_SCHEMA_VERSION}")
    raw_jobs = value.get("jobs")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        _reject("jobs must be a non-empty array")

    manifest_dir = path.resolve().parent
    jobs: list[BatchJob] = []
    identifiers: set[str] = set()
    protected_paths: list[tuple[str, Path]] = []
    for index, raw_job in enumerate(raw_jobs):
        label = f"jobs[{index}]"
        if not isinstance(raw_job, dict):
            _reject(f"{label} must be an object")
        unknown = sorted(set(raw_job) - JOB_FIELDS)
        if unknown:
            _reject(f"{label} contains unknown fields: {', '.join(unknown)}")
        job_id = _required_string(raw_job.get("id"), f"{label}.id")
        if job_id in identifiers:
            _reject(f"duplicate job id: {job_id}")
        identifiers.add(job_id)
        input_path = _path(raw_job.get("input"), f"{label}.input", manifest_dir)
        output_dir = _path(
            raw_job.get("output_dir"), f"{label}.output_dir", manifest_dir
        )
        work_dir = (
            _path(raw_job["work_dir"], f"{label}.work_dir", manifest_dir)
            if "work_dir" in raw_job
            else None
        )
        agent_bundle = (
            _path(raw_job["agent_bundle"], f"{label}.agent_bundle", manifest_dir)
            if "agent_bundle" in raw_job
            else None
        )
        if agent_bundle is not None:
            if work_dir is None:
                _reject(f"{label}.agent_bundle requires an explicit work_dir")
            if agent_bundle == work_dir or work_dir not in agent_bundle.parents:
                _reject(f"{label}.agent_bundle must be within {label}.work_dir")
        common_terms = raw_job.get("common_terms", [])
        if not isinstance(common_terms, list) or not all(
            isinstance(item, str) and item.strip() for item in common_terms
        ):
            _reject(f"{label}.common_terms must be an array of non-empty strings")
        if len(common_terms) != len(set(common_terms)):
            _reject(f"{label}.common_terms must not contain duplicates")
        if work_dir is not None:
            try:
                require_disjoint_paths(output_dir, work_dir)
            except WorkspaceError as exc:
                raise BatchManifestError(f"{label}: {exc}") from exc
        job_paths = [(f"{label}.output_dir", output_dir)]
        if work_dir is not None:
            job_paths.append((f"{label}.work_dir", work_dir))
        for path_label, candidate in job_paths:
            for prior_label, prior in protected_paths:
                if _paths_overlap(candidate, prior):
                    _reject(f"{path_label} overlaps {prior_label}")
            protected_paths.append((path_label, candidate))
        jobs.append(
            BatchJob(
                job_id=job_id,
                input_path=input_path,
                output_dir=output_dir,
                work_dir=work_dir,
                agent_bundle=agent_bundle,
                common_terms=tuple(common_terms),
                include_internal_traces=_optional_boolean(
                    raw_job, "include_internal_traces"
                ),
                qa_annotated_document=_optional_boolean(
                    raw_job, "qa_annotated_document"
                ),
                debug_telemetry=_optional_boolean(raw_job, "debug_telemetry"),
            )
        )
    return tuple(jobs)


def _argv(job: BatchJob) -> list[str]:
    argv = [str(job.input_path), "--output-dir", str(job.output_dir)]
    if job.work_dir is not None:
        argv.extend(("--work-dir", str(job.work_dir)))
    if job.agent_bundle is not None:
        argv.extend(("--agent-bundle", str(job.agent_bundle)))
    for common_term in job.common_terms:
        argv.extend(("--common-term", common_term))
    if job.include_internal_traces:
        argv.append("--include-internal-traces")
    if job.qa_annotated_document:
        argv.append("--qa-annotated-document")
    if job.debug_telemetry:
        argv.append("--debug-telemetry")
    return argv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Batch manifest JSON")
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Run later jobs after a job returns a non-zero status",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        jobs = load_manifest(args.manifest.resolve())
    except BatchManifestError as exc:
        print(
            json.dumps(
                {"type": "batch_error", "status": "rejected", "error": str(exc)},
                ensure_ascii=True,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    started = time.perf_counter()
    completed = 0
    failed = 0
    for job in jobs:
        job_started = time.perf_counter()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            return_code = _single_main(_argv(job))
        raw_output = stdout.getvalue().strip()
        raw_error = stderr.getvalue().strip()
        try:
            result = json.loads(raw_output) if raw_output else None
        except json.JSONDecodeError:
            result = {"raw_stdout": raw_output}
        try:
            error = json.loads(raw_error) if raw_error else None
        except json.JSONDecodeError:
            error = {"raw_stderr": raw_error}
        duration_ms = round((time.perf_counter() - job_started) * 1000, 3)
        if return_code == 0:
            completed += 1
        else:
            failed += 1
        print(
            json.dumps(
                {
                    "type": "job_result",
                    "job_id": job.job_id,
                    "status": "complete" if return_code == 0 else "failed",
                    "return_code": return_code,
                    "duration_ms": duration_ms,
                    "result": result,
                    "error": error,
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        if return_code != 0 and not args.continue_on_error:
            break

    attempted = completed + failed
    print(
        json.dumps(
            {
                "type": "batch_summary",
                "schema_version": BATCH_SCHEMA_VERSION,
                "status": "complete"
                if failed == 0 and attempted == len(jobs)
                else "failed",
                "jobs_total": len(jobs),
                "jobs_attempted": attempted,
                "jobs_completed": completed,
                "jobs_failed": failed,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0 if failed == 0 and attempted == len(jobs) else 2


if __name__ == "__main__":
    raise SystemExit(main())
