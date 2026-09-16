#!/usr/bin/env python3
# ruff: noqa: UP031 -- preserve historical CLI output text.
"""Derive framework-readback.json from a valid framework.json.

The read-back preserves the framework identity and carries one plain-English
row per item:
    {"framework_version", "approved", "items": [{"lens", "issue_id",
     "question", "hit_rule", "materiality", "evidence_required"}]}

materiality is a one-liner composed from optional lawyer-supplied bands
("default medium; high when ...; low when ..."). An item with no ranking
instruction renders as "not requested". hit_rule appends
exclusions as "does not count: X; Y" when present. Ordering is
deterministic: lenses as they appear in the framework, then item order.
The framework is validated (validate_framework logic) before rendering;
invalid input is refused.

Usage:
    python3 render_readback.py --framework framework.json \
        --out framework-readback.json

Exit codes: 0 written, 1 invalid framework, 2 I/O.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_framework  # noqa: E402

UNTUNED = "not requested"


def materiality_line(materiality):
    """Plain-English one-liner from default plus bands."""
    if materiality is None:
        return UNTUNED
    default = materiality["default"]
    bands = materiality["bands"]
    if default == "medium" and not bands:
        return UNTUNED
    parts = [f"default {default}"]
    for b in bands:
        parts.append("{} when {}".format(b["band"], b["when"]))
    return "; ".join(parts)


def hit_rule_line(item):
    """Hit rule with exclusions folded in as plain English."""
    rule = item["hit_rule"]
    exclusions = item["exclusions"]
    if exclusions:
        return "{} does not count: {}".format(rule, "; ".join(exclusions))
    return rule


def build_readback(framework):
    items = []
    for lens in framework["lenses"]:
        for item in lens["items"]:
            items.append(
                {
                    "lens": lens["name"],
                    "issue_id": item["issue_id"],
                    "question": item["question"],
                    "hit_rule": hit_rule_line(item),
                    "materiality": materiality_line(item.get("materiality")),
                    "evidence_required": item["evidence"]["required"],
                }
            )
    return {
        "approved": framework["approved"],
        "framework_version": framework["framework_version"],
        "items": items,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Render the plain-English read-back from framework.json."
    )
    ap.add_argument("--framework", required=True, help="framework.json to render.")
    ap.add_argument("--out", required=True, help="Path for framework-readback.json.")
    args = ap.parse_args()

    try:
        framework = validate_framework.load_json(args.framework, "framework")
        schema = validate_framework.load_json(
            validate_framework.DEFAULT_SCHEMA, "schema"
        )
    except ValueError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(2)

    # Approval state is irrelevant to rendering; validity is not.
    errors, unknown = validate_framework.validate(
        framework, schema, allow_approved=True
    )
    if unknown:
        print(
            "note: schema uses keyword(s) the validator does not enforce: {}".format(
                ", ".join(sorted(unknown))
            ),
            file=sys.stderr,
        )
    if errors:
        print(
            "REFUSED: %s is not a valid framework (%d error(s)); "
            "no read-back written" % (args.framework, len(errors)),
            file=sys.stderr,
        )
        for e in errors:
            print("  " + e, file=sys.stderr)
        sys.exit(1)

    readback = build_readback(framework)
    try:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(readback, indent=2, sort_keys=True) + "\n")
    except OSError as e:
        print(f"FATAL: cannot write {args.out}: {e}", file=sys.stderr)
        sys.exit(2)
    print("wrote %s: %d item(s)" % (args.out, len(readback["items"])))


if __name__ == "__main__":
    main()
