"""Project occurrence adjudications into lawyer-facing usages and findings."""

from __future__ import annotations

from typing import Any


def project_reviewed_inventory(
    data: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return reviewed usages and findings without mutating the canonical ledger."""

    usages = list(data.get("usages") or [])
    findings = list(data.get("findings") or [])
    if (data.get("occurrence_review") or {}).get("status") != "complete":
        return usages, findings

    decisions = {
        item["usage_id"]: item["decision"]
        for item in data.get("occurrence_adjudications", [])
    }
    decision_by_location = {
        (
            item["location"]["block_id"],
            item["location"]["char_start"],
            item["location"]["char_end"],
        ): decisions[item["id"]]
        for item in usages
        if item["id"] in decisions
    }
    usage_by_location = {
        (
            item["location"]["block_id"],
            item["location"]["char_start"],
            item["location"]["char_end"],
        ): item
        for item in usages
    }

    reviewed_usages = [
        item
        for item in usages
        if decisions.get(item["id"])
        in {
            None,
            "defined_term_use",
            "inconsistent_capitalization",
        }
    ]
    reviewed_findings: list[dict[str, Any]] = []
    for finding in findings:
        rule_id = finding.get("rule_id")
        if rule_id == "DEF-001":
            projected_evidence = [
                location
                for location in finding.get("evidence") or []
                if decision_by_location.get(
                    (
                        location["block_id"],
                        location["char_start"],
                        location["char_end"],
                    )
                )
                not in {
                    "defined_term_use",
                    "inconsistent_capitalization",
                    "ordinary_language",
                    "proper_name_component",
                    "shadowed_by_overlapping_term",
                }
            ]
            if not projected_evidence:
                continue
            projected = dict(finding)
            projected["evidence"] = projected_evidence
            reviewed_findings.append(projected)
            continue
        if rule_id not in {"DEF-004", "DEF-005"}:
            reviewed_findings.append(finding)
            continue
        original_evidence = list(finding.get("evidence") or [])
        if rule_id == "DEF-004" and len(original_evidence) >= 2:
            prefix, candidate_evidence, suffix = (
                original_evidence[:1],
                original_evidence[1:],
                [],
            )
        elif rule_id == "DEF-005" and len(original_evidence) >= 2:
            prefix, candidate_evidence, suffix = (
                [],
                original_evidence[:-1],
                original_evidence[-1:],
            )
        else:
            prefix, candidate_evidence, suffix = [], original_evidence, []
        projected_evidence = []
        for location in candidate_evidence:
            decision = decision_by_location.get(
                (
                    location["block_id"],
                    location["char_start"],
                    location["char_end"],
                )
            )
            if decision in {
                "ordinary_language",
                "proper_name_component",
                "shadowed_by_overlapping_term",
            }:
                continue
            if rule_id == "DEF-004" and decision == "defined_term_use":
                continue
            projected_evidence.append(location)
        if candidate_evidence and not projected_evidence:
            continue
        projected = dict(finding)
        projected["evidence"] = [*prefix, *projected_evidence, *suffix]
        if rule_id == "DEF-004" and projected_evidence:
            first_variant = usage_by_location.get(
                (
                    projected_evidence[0]["block_id"],
                    projected_evidence[0]["char_start"],
                    projected_evidence[0]["char_end"],
                )
            )
            if first_variant is not None:
                projected["message"] = (
                    f"'{first_variant['term']}' is used as "
                    f"'{first_variant['observed_form']}', which is not an allowed alias."
                )
        reviewed_findings.append(projected)
    return reviewed_usages, reviewed_findings
