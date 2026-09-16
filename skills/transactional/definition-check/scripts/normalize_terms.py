#!/usr/bin/env python3
"""Normalize defined terms into placeholder variables from versioned ledgers.

Single document:
    normalize_terms.py agreement.docx ledger.json --out normalization.json

Multiple documents (variables become document-qualified, e.g. «A:T001»):
    normalize_terms.py --doc a.docx --ledger a.json --doc b.docx --ledger b.json --out normalization.json

Exit codes: 0 success; 20 unsupported ledger schema; 21 ledger/source binding
mismatch; 22 span integrity failure; 23 unreadable input. Argument errors use
argparse's exit code 2. The source DOCX files are never modified.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _runtime_gate import require_supported_python

require_supported_python()

from definition_check.normalize import (
    NORMALIZATION_SCHEMA_VERSION,
    NormalizationError,
    normalize_pairs,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rewrite every accepted usage of a defined term into a placeholder "
            "variable, from 0.14.0 definition-check ledgers. Deterministic; "
            "never modifies the source documents."
        )
    )
    parser.add_argument("docx", nargs="?", type=Path, help="Path to the source DOCX")
    parser.add_argument(
        "ledger", nargs="?", type=Path, help="Path to the definition-check ledger JSON"
    )
    parser.add_argument(
        "--doc",
        action="append",
        default=[],
        type=Path,
        help="Source DOCX for multi-document runs; repeat once per --ledger",
    )
    parser.add_argument(
        "--ledger",
        dest="ledger_flag",
        action="append",
        default=[],
        type=Path,
        help="Ledger JSON for multi-document runs; repeat once per --doc",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output path for the normalization artifact JSON; must not exist",
    )
    return parser


def _resolve_pairs(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> list[tuple[Path, Path]]:
    positional = args.docx is not None or args.ledger is not None
    if positional:
        if args.docx is None or args.ledger is None:
            parser.error("single-document mode requires both DOCX and LEDGER")
        if args.doc or args.ledger_flag:
            parser.error("cannot mix positional DOCX LEDGER with --doc/--ledger pairs")
        return [(args.docx, args.ledger)]
    if not args.doc and not args.ledger_flag:
        parser.error("provide DOCX LEDGER or repeated --doc/--ledger pairs")
    if len(args.doc) != len(args.ledger_flag):
        parser.error("--doc and --ledger must repeat in equal pairs")
    return list(zip(args.doc, args.ledger_flag, strict=True))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    pairs = _resolve_pairs(parser, args)
    if args.out.exists():
        parser.error(f"output already exists: {args.out!s}")

    try:
        artifact = normalize_pairs(pairs)
    except NormalizationError as exc:
        print(
            json.dumps(
                {
                    "normalization_schema_version": NORMALIZATION_SCHEMA_VERSION,
                    "error": str(exc),
                },
                ensure_ascii=True,
            ),
            file=sys.stderr,
        )
        return exc.exit_code

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    summary = {
        "normalization_schema_version": artifact["normalization_schema_version"],
        "document_count": len(artifact["documents"]),
        "variable_count": sum(len(doc["variables"]) for doc in artifact["documents"]),
        "skipped_usage_count": sum(
            len(doc["skipped_usages"]) for doc in artifact["documents"]
        ),
        "output": str(args.out),
    }
    print(json.dumps(summary, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
