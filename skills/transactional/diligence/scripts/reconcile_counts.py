#!/usr/bin/env python3
"""Verify that every issue × substantive unit is accounted for.

Usage:
    python3 reconcile_counts.py --manifest manifest.json --findings findings.json \
        --framework framework.json [--families families.json]

Reviewable units are substantive manifest documents with readability native or
scanned, collapsed to unique unit ids (a family counts once; member docs never
double-count; --families supplies the doc-to-family map). Documents explicitly
marked review_role=runner-control stay in the corpus census but are not review
units. For each framework issue, every reviewable unit must have exactly one
present, absent, or unresolved result unless that unit is visibly parked.

Global checks reject unknown or duplicate issue/unit pairs, issue/lens drift,
findings against runner-control documents, and present findings without a quote,
section locator, deterministic quote receipt, and independent checker receipt.

Exit 0 when every lens reconciles and no global check fails, 1 otherwise,
with a precise per-lens report on stdout. Importable:
reconcile(manifest, findings, framework, families=None) -> result dict.
render_report.py refuses to issue the Gate 3 report unless this passes.
"""

import argparse
import json
import sys
from typing import Any

REVIEWABLE = {"native", "scanned"}


def load(path, kind, required_keys):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"reconcile_counts: cannot read {kind} at {path}: {e}")
    for k in required_keys:
        if k not in data:
            sys.exit(f"reconcile_counts: {kind} missing key '{k}'")
    return data


def unit_map(manifest, families):
    """Map doc_id to family_id or the standalone doc_id."""
    to_unit = {}
    substantive = {
        d["id"]
        for d in manifest.get("documents", [])
        if d.get("review_role", "substantive") != "runner-control"
    }
    if families:
        for fam in families.get("families", []):
            fid = fam.get("family_id", "")
            for m in fam.get("members", []):
                if m["id"] in substantive:
                    to_unit[m["id"]] = fid
    for d in manifest.get("documents", []):
        if d["id"] in substantive:
            to_unit.setdefault(d["id"], d["id"])
    return to_unit


def reconcile(manifest, findings, framework, families=None):
    """Return {"ok", "lines", "errors", "totals", "per_lens", plus unit lists}."""
    to_unit = unit_map(manifest, families)
    docs = {d["id"]: d for d in manifest.get("documents", [])}

    control_ids = {
        d["id"]
        for d in manifest.get("documents", [])
        if d.get("review_role", "substantive") == "runner-control"
    }
    substantive_ids = set(docs) - control_ids
    unit_docs = {}
    for did in substantive_ids:
        unit_docs.setdefault(to_unit[did], set()).add(did)
    all_units = set(unit_docs)
    reviewable = {
        u
        for u, ds in unit_docs.items()
        if any(docs[d].get("readability") in REVIEWABLE for d in ds)
    }
    unreadable = all_units - reviewable

    errors = []
    if families:
        for fam in families.get("families", []):
            mixed = [
                m.get("id", "")
                for m in fam.get("members", [])
                if m.get("id") in control_ids
            ]
            if mixed:
                family_id = fam.get("family_id", "")
                controls = ", ".join(sorted(mixed))
                errors.append(
                    f"family {family_id} contains runner-control "
                    f"document(s): {controls}"
                )
    fw_v = framework.get("framework_version")
    fi_v = findings.get("framework_version")
    if fw_v != fi_v:
        errors.append(
            f"findings carry framework_version {fi_v} but framework is version {fw_v}"
        )

    parked_units = set()
    for p in findings.get("parked", []):
        did = p.get("doc_id", "")
        if did not in docs:
            errors.append(f"parked entry references doc {did} absent from the manifest")
            continue
        if did in control_ids:
            errors.append(f"parked entry references runner-control document {did}")
            continue
        parked_units.add(to_unit[did])

    lens_ids = [lens["lens_id"] for lens in framework.get("lenses", [])]
    issue_lens = {
        item["issue_id"]: lens["lens_id"]
        for lens in framework.get("lenses", [])
        for item in lens.get("items", [])
    }
    per_issue: dict[str, dict[str, Any]] = {
        iid: {
            "found_units": set(),
            "status_counts": {"present": 0, "absent": 0, "unresolved": 0},
        }
        for iid in issue_lens
    }
    per_lens: dict[str, dict[str, Any]] = {
        lid: {
            "found_units": set(),
            "result_pairs": set(),
            "status_counts": {"present": 0, "absent": 0, "unresolved": 0},
        }
        for lid in lens_ids
    }
    finding_ids = set()
    pairs = set()

    for f in findings.get("findings", []):
        fid = f.get("finding_id", "<no id>")
        if fid in finding_ids:
            errors.append(f"duplicate finding_id {fid}")
        finding_ids.add(fid)
        did = f.get("doc_id", "")
        if did not in docs:
            errors.append(
                f"finding {fid} references doc {did} absent from the manifest"
            )
            continue
        if did in control_ids:
            errors.append(f"finding {fid} references runner-control document {did}")
            continue
        status = f.get("status", "")
        if status not in {"present", "absent", "unresolved"}:
            errors.append(f"finding {fid} has unsupported status {status!r}")
            continue
        if status == "present":
            if not (f.get("quote") or "").strip():
                errors.append(f"finding {fid} has status present with an empty quote")
            if not (f.get("section") or "").strip():
                errors.append(
                    f"finding {fid} has status present with an empty section locator"
                )
            quote_receipt = f.get("quote_verification") or {}
            if quote_receipt.get("status") != "confirmed":
                errors.append(
                    f"finding {fid} lacks a confirmed deterministic quote receipt"
                )
            checker_receipt = f.get("verification") or {}
            if checker_receipt.get("status") != "confirmed":
                errors.append(
                    f"finding {fid} lacks a confirmed independent checker receipt"
                )
        unit = f.get("unit_id")
        if not isinstance(unit, str) or not unit:
            errors.append(f"finding {fid} has no unit_id")
            continue
        if unit != to_unit[did]:
            errors.append(
                f"finding {fid} claims unit {unit} but doc {did} maps to {to_unit[did]}"
            )
        lid = f.get("lens_id", "")
        if lid not in per_lens:
            errors.append(f"finding {fid} references unknown lens '{lid}'")
            continue
        iid = f.get("issue_id", "")
        if iid not in issue_lens:
            errors.append(f"finding {fid} references unknown issue '{iid}'")
            continue
        if issue_lens[iid] != lid:
            expected_lens = issue_lens[iid]
            errors.append(
                f"finding {fid} places issue {iid} in lens {lid}; "
                f"expected {expected_lens}"
            )
            continue
        pair = (iid, unit)
        if pair in pairs:
            errors.append(f"duplicate issue/unit result for {iid} and {unit}")
            continue
        pairs.add(pair)
        per_issue[iid]["found_units"].add(unit)
        per_issue[iid]["status_counts"][status] += 1
        per_lens[lid]["found_units"].add(unit)
        per_lens[lid]["result_pairs"].add(pair)
        counts = per_lens[lid]["status_counts"]
        counts[status] += 1

    lines = []
    ok = not errors
    for iid in issue_lens:
        info = per_issue[iid]
        covered = info["found_units"] | parked_units
        missing = sorted(reviewable - covered)
        extra = sorted(covered - reviewable)
        overlap = sorted(info["found_units"] & parked_units)
        lens_ok = not missing and not extra and not overlap
        info.update(
            missing=missing,
            extra=extra,
            overlap=overlap,
            ok=lens_ok,
            parked=len(parked_units),
            found_units=sorted(info["found_units"]),
        )
        line = (
            f"issue {iid}: {len(info['found_units'])} result units + "
            f"{len(parked_units)} parked = {len(covered)} of "
            f"{len(reviewable)} reviewable units: "
            f"{'OK' if lens_ok else 'FAIL'}"
        )
        if missing:
            line += f" (missing: {', '.join(missing)})"
        if extra:
            line += f" (not reviewable: {', '.join(extra)})"
        if overlap:
            line += f" (both found and parked: {', '.join(overlap)})"
        lines.append(line)
        ok = ok and lens_ok

    for lid in lens_ids:
        info = per_lens[lid]
        info["found_units"] = sorted(info["found_units"])
        info["result_pairs"] = sorted([list(pair) for pair in info["result_pairs"]])
        info["parked"] = len(parked_units)
        info["ok"] = all(
            per_issue[item["issue_id"]]["ok"]
            for lens in framework.get("lenses", [])
            if lens["lens_id"] == lid
            for item in lens.get("items", [])
        )
    ok = ok and not errors
    totals = {
        "corpus_files": len(manifest.get("documents", [])),
        "control_inputs": len(control_ids),
        "substantive_files": len(substantive_ids),
        "units": len(all_units),
        "reviewable": len(reviewable),
        "unreadable": len(unreadable),
        "parked": len(parked_units),
        "reviewed": len(reviewable - parked_units),
        "issues": len(issue_lens),
        "expected_results": len(issue_lens) * len(reviewable - parked_units),
        "results": len(pairs),
    }
    return {
        "ok": ok,
        "lines": lines,
        "errors": errors,
        "totals": totals,
        "per_lens": per_lens,
        "per_issue": per_issue,
        "reviewable_units": sorted(reviewable),
        "unreadable_units": sorted(unreadable),
        "parked_units": sorted(parked_units),
    }


def main():
    ap = argparse.ArgumentParser(
        description="Reconcile findings coverage against the manifest."
    )
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--findings", required=True)
    ap.add_argument("--framework", required=True)
    ap.add_argument("--families", default=None)
    args = ap.parse_args()

    manifest = load(args.manifest, "manifest", ["documents", "counts"])
    findings = load(args.findings, "findings", ["findings"])
    framework = load(args.framework, "framework", ["framework_version", "lenses"])
    families = load(args.families, "families", ["families"]) if args.families else None

    r = reconcile(manifest, findings, framework, families)
    t = r["totals"]
    print(
        f"corpus: {t['corpus_files']} files, {t['control_inputs']} runner-control, "
        f"{t['substantive_files']} substantive"
    )
    print(
        f"units: {t['units']} total, {t['reviewable']} reviewable, "
        f"{t['unreadable']} unreadable"
    )
    print(
        f"equation: {t['reviewed']} reviewed + {t['parked']} parked + "
        f"{t['unreadable']} unreadable = {t['units']} manifest units"
    )
    print(
        f"matrix: {t['issues']} issues x {t['reviewed']} reviewed units = "
        f"{t['expected_results']} expected results; {t['results']} received"
    )
    for line in r["lines"]:
        print(line)
    for e in r["errors"]:
        print(f"error: {e}")
    print("RECONCILED" if r["ok"] else "NOT RECONCILED")
    sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()
