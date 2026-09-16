#!/usr/bin/env python3
"""Build a deterministic independent-checker plan for every present finding.

Selection is factual and deliberately independent of materiality. Run this
against the checked sample ledger or the full ledger that the lawyer approved;
every present finding in that ledger becomes one checker job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def load(path, label, required):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"build_checker_plan: cannot read {label}: {exc}")
    for key in required:
        if key not in value:
            sys.exit(f"build_checker_plan: {label} missing key {key!r}")
    return value


def canonical_digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def result_name(finding_id):
    return hashlib.sha256(finding_id.encode("utf-8")).hexdigest()[:16] + ".json"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--findings", required=True)
    parser.add_argument("--framework", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    findings = load(args.findings, "findings", ["framework_version", "findings"])
    framework = load(args.framework, "framework", ["framework_version", "lenses"])
    errors = []
    if findings["framework_version"] != framework["framework_version"]:
        errors.append("findings and framework versions do not match")
    issue_lens = {
        item.get("issue_id"): lens.get("lens_id")
        for lens in framework["lenses"]
        for item in lens.get("items", [])
    }
    jobs = []
    seen = set()
    for finding in findings["findings"]:
        if finding.get("status") != "present":
            continue
        finding_id = finding.get("finding_id")
        issue_id = finding.get("issue_id")
        lens_id = finding.get("lens_id")
        if not isinstance(finding_id, str) or not finding_id:
            errors.append("present finding has no finding_id")
            continue
        if finding_id in seen:
            errors.append(f"present finding ID repeats: {finding_id}")
            continue
        seen.add(finding_id)
        if issue_lens.get(issue_id) != lens_id:
            errors.append(f"present finding {finding_id} names the wrong lens or issue")
        if not str(finding.get("quote") or "").strip():
            errors.append(f"present finding {finding_id} has no quote")
        if not str(finding.get("section") or "").strip():
            errors.append(f"present finding {finding_id} has no section locator")
        if (finding.get("quote_verification") or {}).get("status") != "confirmed":
            errors.append(
                f"present finding {finding_id} lacks a confirmed quote receipt"
            )
        result_file = result_name(finding_id)
        jobs.append(
            {
                "doc_id": finding.get("doc_id"),
                "finding_id": finding_id,
                "issue_id": issue_id,
                "job_id": result_file[:-5],
                "lens_id": lens_id,
                "result_file": result_file,
                "unit_id": finding.get("unit_id"),
            }
        )
    if errors:
        sys.exit("build_checker_plan: " + "; ".join(sorted(errors)))
    jobs.sort(key=lambda row: row["job_id"])
    plan = {
        "framework_digest": canonical_digest(framework),
        "framework_version": framework["framework_version"],
        "jobs": jobs,
        "selection_rule": "every-present-finding-in-approved-ledger",
        "source_findings_digest": canonical_digest(findings),
        "source_review_plan_id": findings.get("review_plan_id"),
        "version": 1,
    }
    plan["plan_id"] = canonical_digest(plan)[:16]
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {args.out}: {len(jobs)} independent checker job(s)")


if __name__ == "__main__":
    main()
