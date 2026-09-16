#!/usr/bin/env python3
# ruff: noqa: B904, E501, UP031 -- preserve historical validator diagnostics.
"""Validate a framework.json against framework.schema.json, stdlib only.

Schema enforcement is driven by the schema file itself: type, enum, const,
pattern, minLength, maxLength, minimum, maximum, minItems, maxItems,
required, properties, additionalProperties, items, and anyOf are applied
recursively, so schema edits keep working without code changes. Keywords
the checker does not implement are reported as a note, never silently
ignored into a false pass.

Semantic checks beyond the schema: lens_id unique across lenses, issue_id
unique across ALL lenses, overlap_owner references an existing lens_id,
framework_version >= 1, and approved must be false unless --allow-approved.

Usage:
    python3 validate_framework.py --framework framework.json \
        [--schema ../references/framework.schema.json] [--allow-approved]

Exit codes: 0 valid, 1 invalid, 2 I/O or unusable schema.
"""

import argparse
import json
import os
import re
import sys

DEFAULT_SCHEMA = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "references",
        "framework.schema.json",
    )
)

TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}

# Keywords this checker enforces, plus pure metadata it may skip.
HANDLED = {
    "type",
    "enum",
    "const",
    "pattern",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
    "required",
    "properties",
    "additionalProperties",
    "items",
    "anyOf",
}
METADATA = {"$schema", "$id", "title", "description", "examples", "default"}


def type_name(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return {dict: "object", list: "array", str: "string"}.get(
        type(value), type(value).__name__
    )


def json_equal(a, b):
    """Equality that keeps booleans apart from 0/1."""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def check_schema(value, schema, path, errors, unknown):
    """Apply one schema node to value, appending error strings with JSON paths."""
    for k in schema:
        if k not in HANDLED and k not in METADATA:
            unknown.add(k)

    if "anyOf" in schema:
        branch_fails = []
        for branch in schema["anyOf"]:
            trial = []
            check_schema(value, branch, path, trial, unknown)
            if not trial:
                branch_fails = None
                break
            branch_fails.append(trial[0])
        if branch_fails is not None:
            errors.append(
                "{}: no anyOf alternative matched ({})".format(
                    path, " | ".join(branch_fails)
                )
            )

    if "type" in schema:
        types = schema["type"]
        if not isinstance(types, list):
            types = [types]
        if not any(TYPE_CHECKS[t](value) for t in types):
            errors.append(
                "{}: expected type {}, got {}".format(
                    path, "/".join(types), type_name(value)
                )
            )
            return  # remaining keywords assume the declared type

    if "enum" in schema and not any(json_equal(value, o) for o in schema["enum"]):
        errors.append("{}: {!r} is not one of {}".format(path, value, schema["enum"]))
    if "const" in schema and not json_equal(value, schema["const"]):
        errors.append(
            "{}: must be exactly {!r}, got {!r}".format(path, schema["const"], value)
        )

    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(
                "{}: {!r} does not match pattern {}".format(
                    path, value, schema["pattern"]
                )
            )
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(
                "%s: string shorter than minLength %d" % (path, schema["minLength"])
            )
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(
                "%s: string longer than maxLength %d" % (path, schema["maxLength"])
            )

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(
                "{}: {!r} is below minimum {!r}".format(path, value, schema["minimum"])
            )
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(
                "{}: {!r} is above maximum {!r}".format(path, value, schema["maximum"])
            )

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(
                "%s: array has %d item(s), minItems is %d"
                % (path, len(value), schema["minItems"])
            )
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(
                "%s: array has %d item(s), maxItems is %d"
                % (path, len(value), schema["maxItems"])
            )
        if "items" in schema:
            for i, elem in enumerate(value):
                check_schema(
                    elem, schema["items"], "%s[%d]" % (path, i), errors, unknown
                )

    if isinstance(value, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in value:
                errors.append(f"{path}: missing required property '{req}'")
        for k, v in value.items():
            if k in props:
                check_schema(v, props[k], f"{path}.{k}", errors, unknown)
            elif "additionalProperties" in schema:
                ap = schema["additionalProperties"]
                if ap is False:
                    errors.append(f"{path}: unexpected property '{k}'")
                elif isinstance(ap, dict):
                    check_schema(v, ap, f"{path}.{k}", errors, unknown)

    return errors


def semantic_errors(fw, allow_approved=False):
    """Cross-field checks the schema language cannot express."""
    errors = []
    if not isinstance(fw, dict):
        return errors

    v = fw.get("framework_version")
    if isinstance(v, int) and not isinstance(v, bool) and v < 1:
        errors.append("$.framework_version: must be >= 1, got %d" % v)
    if fw.get("approved") is True and not allow_approved:
        errors.append(
            "$.approved: must be false before Gate 2 approval "
            "(pass --allow-approved to accept an approved framework)"
        )

    lenses = fw.get("lenses")
    if not isinstance(lenses, list):
        return errors
    lens_ids = {}
    issue_ids = {}
    for i, lens in enumerate(lenses):
        if not isinstance(lens, dict):
            continue
        lid = lens.get("lens_id")
        lpath = "$.lenses[%d]" % i
        if isinstance(lid, str):
            if lid in lens_ids:
                errors.append(
                    f"{lpath}.lens_id: duplicate lens_id {lid!r} (first used at {lens_ids[lid]})"
                )
            else:
                lens_ids[lid] = lpath
        items = lens.get("items")
        if not isinstance(items, list):
            continue
        for j, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            iid = item.get("issue_id")
            ipath = "%s.items[%d]" % (lpath, j)
            if isinstance(iid, str):
                if iid in issue_ids:
                    errors.append(
                        f"{ipath}.issue_id: duplicate issue_id {iid!r} (first used at {issue_ids[iid]}); "
                        "issue_id must be unique across all lenses"
                    )
                else:
                    issue_ids[iid] = ipath
    for i, lens in enumerate(lenses):
        if not isinstance(lens, dict):
            continue
        for j, item in enumerate(lens.get("items") or []):
            if not isinstance(item, dict):
                continue
            owner = item.get("overlap_owner")
            if owner is not None and isinstance(owner, str) and owner not in lens_ids:
                errors.append(
                    "$.lenses[%d].items[%d].overlap_owner: %r is not a "
                    "lens_id defined in this framework" % (i, j, owner)
                )
    return errors


def validate(framework, schema, allow_approved=False):
    """Full validation. Returns (errors, unknown_keywords)."""
    errors = []
    unknown = set()
    check_schema(framework, schema, "$", errors, unknown)
    errors.extend(semantic_errors(framework, allow_approved))
    return errors, unknown


def load_json(path, kind):
    """Load a JSON file or raise ValueError with a readable message."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"cannot read {kind} at {path}: {e}")


def main():
    ap = argparse.ArgumentParser(
        description="Validate framework.json against framework.schema.json."
    )
    ap.add_argument("--framework", required=True, help="framework.json to validate.")
    ap.add_argument(
        "--schema",
        default=DEFAULT_SCHEMA,
        help=f"Schema file (default: {DEFAULT_SCHEMA}).",
    )
    ap.add_argument(
        "--allow-approved",
        action="store_true",
        help="Accept approved: true (post-Gate 2 use).",
    )
    args = ap.parse_args()

    try:
        framework = load_json(args.framework, "framework")
        schema = load_json(args.schema, "schema")
    except ValueError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(2)

    errors, unknown = validate(framework, schema, args.allow_approved)
    if unknown:
        print(
            "note: schema uses keyword(s) this checker does not enforce: {}".format(
                ", ".join(sorted(unknown))
            ),
            file=sys.stderr,
        )
    if errors:
        print("INVALID: %s (%d error(s))" % (args.framework, len(errors)))
        for e in errors:
            print("  " + e)
        sys.exit(1)
    n_items = sum(len(lens.get("items", [])) for lens in framework.get("lenses", []))
    print(
        "OK: %s is valid (%d lens(es), %d item(s), version %s)"
        % (
            args.framework,
            len(framework.get("lenses", [])),
            n_items,
            framework.get("framework_version"),
        )
    )


if __name__ == "__main__":
    main()
