"""Independent literal mention inventory and explicit review dispositions.

This audits coverage, not correctness of model decisions. It rescans accepted
labels independently of the usage builder and also accounts for candidate
locations. It never invents a semantic or occurrence decision.
"""

from collections import Counter

from .term_identity import term_key, term_pattern


def audit_mentions(data: dict, blocks: list[dict]) -> dict:
    def span(loc):
        return (loc["part"], loc["block_id"], loc["char_start"], loc["char_end"])

    decisions = {x["review_id"]: x for x in data["semantic_adjudications"]}
    occurrences = {x["usage_id"]: x for x in data["occurrence_adjudications"]}
    candidates = {x["normalized_term"]: x for x in data["term_candidates"]}
    labels: dict[str, tuple[str, str, str]] = {}
    mentions = {}
    for key, candidate in candidates.items():
        decision = decisions.get(candidate["review_id"], {})
        status = decision.get("decision", "unreviewed")
        canonical = term_key(decision.get("canonical_term") or candidate["term"])
        labels[key] = (candidate["term"], status, canonical)
        for loc in candidate["locations"]:
            mentions[(key, span(loc))] = loc
    definitions = {}
    for definition in data["definitions"]:
        key = definition["normalized_term"]
        definitions.setdefault(key, set()).add(span(definition["location"]))
        labels.setdefault(key, (definition["term"], "confirmed_defined", key))
        for alias in definition["aliases"]:
            labels.setdefault(term_key(alias), (alias, "confirmed_alias", key))
    # Independent exact-label rescan. Existing variant locations are included
    # separately; this is not a claim to discover arbitrary new spellings.
    for key, (label, status, _) in labels.items():
        if status not in {
            "confirmed_defined",
            "confirmed_alias",
            "confirmed_undefined",
        }:
            continue
        pattern = term_pattern(label)
        for block in blocks:
            for match in pattern.finditer(block["text"]):
                loc = {
                    "part": block["part"],
                    "block_id": block["id"],
                    "block_order": block["order"],
                    "char_start": match.start(),
                    "char_end": match.end(),
                }
                mentions[(key, span(loc))] = loc
    usages = {}
    for usage in data["usages"]:
        key = usage["normalized_term"]
        usages[(key, span(usage["location"]))] = usage
        mentions.setdefault((key, span(usage["location"])), usage["location"])
    retained = [
        (key, loc)
        for key, loc in mentions
        if labels.get(key, (None, None))[1]
        in {"confirmed_defined", "confirmed_alias", "confirmed_undefined"}
    ]
    rows = []
    for (key, loc), location in sorted(mentions.items()):
        _, decision, canonical = labels.get(key, (key, "unreviewed", key))
        usage = usages.get((canonical, loc))
        reason = None
        if loc in definitions.get(canonical, set()):
            disposition = "definition_label"
        elif any(
            other[:2] == loc[:2]
            and other[2] <= loc[2]
            and loc[3] <= other[3]
            and other != loc
            for _, other in retained
        ):
            disposition = "contained_in_longer_retained_label"
        elif decision in {"confirmed_defined", "confirmed_alias"}:
            if usage is None:
                disposition, reason = (
                    "coverage_gap",
                    "accepted_label_missing_from_usage_index",
                )
            elif usage["is_definition_occurrence"]:
                disposition, reason = "coverage_gap", "non_label_marked_as_definition"
            elif usage["id"] in occurrences:
                disposition = occurrences[usage["id"]]["decision"]
            else:
                disposition = "unreviewed_occurrence"
        else:
            disposition = decision
        rows.append(
            {
                "term": key,
                "location": location,
                "disposition": disposition,
                "reason": reason,
            }
        )
    contradictions = []
    for finding in data["findings"]:
        if finding["rule_id"] != "DEF-001":
            continue
        candidate = candidates.get(finding["normalized_term"])
        decision = decisions.get(candidate["review_id"], {}) if candidate else {}
        status = decision.get("decision")
        if status and status != "confirmed_undefined":
            contradictions.append(
                {
                    "finding_id": finding["id"],
                    "term": finding["normalized_term"],
                    "decision": status,
                    "reason": "undefined_finding_contradicts_semantic_decision",
                }
            )
    counts = Counter(row["disposition"] for row in rows)
    return {
        "schema_version": "mention-coverage-v2",
        "source_sha256": data["source"]["sha256"],
        "scope": "candidate locations, independent accepted-label literal rescan, and recorded variants; not semantic accuracy",
        "counts": dict(counts),
        "gap_count": counts["coverage_gap"],
        "contradiction_count": len(contradictions),
        "contradictions": contradictions,
        "mentions": rows,
    }
