#!/usr/bin/env python3
"""Merge one independent checker result for every job in checker-plan.json.

Each result must contain exactly the plan ID, finding ID, verdict
(`confirmed`, `refuted`, or `unresolved`), and an objection string. Missing,
duplicated, stale, or invalid results fail closed before output. Confirmed
results receive a checker receipt; all other verdicts become unresolved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

VERDICTS = {"confirmed", "refuted", "unresolved"}
RESULT_KEYS = {"checker_plan_id", "finding_id", "objection", "verdict"}


def load(path, label, required):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"merge_checker_results: cannot read {label}: {exc}")
    for key in required:
        if key not in value:
            sys.exit(f"merge_checker_results: {label} missing key {key!r}")
    return value


def canonical_digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--findings", required=True)
    parser.add_argument("--checker-plan", required=True)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    findings = load(args.findings, "findings", ["framework_version", "findings"])
    plan = load(
        args.checker_plan,
        "checker plan",
        ["framework_version", "jobs", "plan_id", "source_findings_digest"],
    )
    if findings["framework_version"] != plan["framework_version"]:
        sys.exit("merge_checker_results: findings and checker plan versions differ")
    if canonical_digest(findings) != plan["source_findings_digest"]:
        sys.exit(
            "merge_checker_results: checker plan is stale for this findings ledger"
        )
    unsigned_plan = {key: value for key, value in plan.items() if key != "plan_id"}
    if canonical_digest(unsigned_plan)[:16] != plan["plan_id"]:
        sys.exit("merge_checker_results: checker plan ID does not match its contents")
    results_dir = Path(args.results_dir)
    if not results_dir.is_dir():
        sys.exit(f"merge_checker_results: results directory not found: {results_dir}")
    by_finding = {row.get("finding_id"): row for row in findings["findings"]}
    if len(by_finding) != len(findings["findings"]):
        sys.exit("merge_checker_results: findings ledger repeats a finding_id")

    planned_ids = [job.get("finding_id") for job in plan["jobs"]]
    present_ids = [
        row.get("finding_id")
        for row in findings["findings"]
        if row.get("status") == "present"
    ]
    if any(not isinstance(value, str) or not value for value in planned_ids):
        sys.exit("merge_checker_results: checker plan has an invalid finding ID")
    if any(not isinstance(value, str) or not value for value in present_ids):
        sys.exit("merge_checker_results: present finding has an invalid finding ID")
    if len(planned_ids) != len(set(planned_ids)):
        sys.exit("merge_checker_results: checker plan repeats a finding ID")
    result_files = [job.get("result_file") for job in plan["jobs"]]
    if any(not isinstance(name, str) or not name for name in result_files):
        sys.exit("merge_checker_results: checker plan has an invalid result filename")
    if any(
        Path(name).name != name or Path(name).suffix != ".json" for name in result_files
    ):
        sys.exit("merge_checker_results: checker plan result filename is unsafe")
    if len(result_files) != len(set(result_files)):
        sys.exit("merge_checker_results: checker plan repeats a result filename")
    if sorted(planned_ids) != sorted(present_ids):
        sys.exit(
            "merge_checker_results: checker plan does not cover every present finding"
        )

    errors = []
    results = {}
    expected_files = {job["result_file"] for job in plan["jobs"]}
    actual_files = {path.name for path in results_dir.glob("*.json")}
    missing = sorted(expected_files - actual_files)
    extra = sorted(actual_files - expected_files)
    if missing:
        errors.append("missing result file(s): " + ", ".join(missing))
    if extra:
        errors.append("unexpected result file(s): " + ", ".join(extra))
    for job in plan["jobs"]:
        path = results_dir / job["result_file"]
        if not path.is_file():
            continue
        result = load(path, f"checker result {path.name}", [])
        if set(result) != RESULT_KEYS:
            errors.append(f"{path.name} has invalid keys")
            continue
        if result.get("checker_plan_id") != plan["plan_id"]:
            errors.append(f"{path.name} carries a stale checker plan ID")
        if result.get("finding_id") != job["finding_id"]:
            errors.append(f"{path.name} carries the wrong finding ID")
        if result.get("verdict") not in VERDICTS:
            errors.append(f"{path.name} has invalid verdict {result.get('verdict')!r}")
        if not isinstance(result.get("objection"), str):
            errors.append(f"{path.name} has a non-string objection")
        if (
            result.get("verdict") != "confirmed"
            and not result.get("objection", "").strip()
        ):
            errors.append(f"{path.name} must explain a non-confirming verdict")
        if result.get("finding_id") in results:
            errors.append(f"checker result repeats {result.get('finding_id')}")
        results[result.get("finding_id")] = result
    if errors:
        sys.exit("merge_checker_results: " + "; ".join(sorted(errors)))

    for job in plan["jobs"]:
        finding = by_finding.get(job["finding_id"])
        if finding is None or finding.get("status") != "present":
            sys.exit(
                "merge_checker_results: planned finding "
                f"{job['finding_id']} is not present"
            )
        result = results[job["finding_id"]]
        verdict = result["verdict"]
        finding["verification"] = {
            "checker": "independent",
            "objection": result["objection"],
            "status": "confirmed" if verdict == "confirmed" else verdict,
        }
        if verdict != "confirmed":
            finding["status"] = "unresolved"

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(findings, indent=2, sort_keys=True) + "\n")
    confirmed = sum(row["verdict"] == "confirmed" for row in results.values())
    print(
        f"Wrote {args.out}: {confirmed} confirmed, "
        f"{len(results) - confirmed} changed to unresolved"
    )


if __name__ == "__main__":
    main()
