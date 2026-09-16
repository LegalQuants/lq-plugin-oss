#!/usr/bin/env python3
"""Ledger preflight for /conform: a hard stop, not a soft warning.

Recomputes each document's content hash using the same raw-bytes SHA-256
approach `/definition-check` uses for `source.sha256`
(`../definition-check/scripts/definition_check/ooxml.py:_hash_file`,
replicated here rather than imported across a skill boundary), compares it
against each ledger's recorded `source.sha256`, and validates schema version,
run status, and review completion. Emits a structured JSON stop-reason object
on any failure and exits non-zero with a distinguishable exit code and
`stop_reason` string per failure class. Emits a small JSON success summary
otherwise.
"""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from _runtime_gate import require_supported_python

require_supported_python()

REQUIRED_SCHEMA_VERSION = "0.14.0"
COMPLETED_RUN_STATUSES = frozenset({"completed", "completed_reduced_assurance"})
REVIEW_STAGES = ("semantic_review", "occurrence_review", "reference_review")
_HASH_CHUNK_BYTES = 1024 * 1024

EXIT_CODES = {
    "missing_document": 10,
    "missing_ledger": 11,
    "stale_schema_version": 12,
    "hash_mismatch": 13,
    "incomplete_run": 14,
    "incomplete_review": 15,
}


class PreflightFailure(Exception):
    """Raised for one distinguishable, lawyer-explainable stop reason."""

    def __init__(
        self, stop_reason: str, document: str, message: str, **detail: Any
    ) -> None:
        super().__init__(message)
        self.stop_reason = stop_reason
        self.document = document
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "failed",
            "stop_reason": self.stop_reason,
            "document": self.document,
            "message": self.message,
        }
        if self.detail:
            payload["detail"] = self.detail
        return payload


def _hash_file(path: Path) -> str:
    """Raw SHA-256 of file bytes, chunked identically to definition-check's ooxml._hash_file."""

    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_ledger(role: str, ledger_path: Path) -> dict[str, Any]:
    if not ledger_path.is_file():
        raise PreflightFailure(
            "missing_ledger",
            role,
            f"No current definition check ledger found for the {role} document. "
            f"Run /definition-check on it first.",
            ledger_path=str(ledger_path),
        )
    try:
        text = ledger_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PreflightFailure(
            "missing_ledger",
            role,
            f"The {role} document's definition-check ledger could not be read.",
            ledger_path=str(ledger_path),
            error=str(exc),
        ) from exc
    try:
        ledger = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PreflightFailure(
            "missing_ledger",
            role,
            f"The {role} document's definition-check ledger is not valid JSON.",
            ledger_path=str(ledger_path),
            error=str(exc),
        ) from exc
    if not isinstance(ledger, dict):
        raise PreflightFailure(
            "missing_ledger",
            role,
            f"The {role} document's definition-check ledger is not a JSON object.",
            ledger_path=str(ledger_path),
        )
    return ledger


def check_document(role: str, docx_path: str, ledger_path: str) -> dict[str, Any]:
    """Run the full preflight for one document; raise PreflightFailure on any stop condition."""

    docx = Path(docx_path)
    if not docx.is_file():
        raise PreflightFailure(
            "missing_document",
            role,
            f"The {role} document was not found at the supplied path.",
            docx_path=str(docx),
        )

    ledger = _load_ledger(role, Path(ledger_path))

    schema_version = ledger.get("schema_version")
    if schema_version != REQUIRED_SCHEMA_VERSION:
        raise PreflightFailure(
            "stale_schema_version",
            role,
            f"The {role} document's definition-check ledger uses schema "
            f"{schema_version!r}, not the current {REQUIRED_SCHEMA_VERSION}. "
            f"Re-run /definition-check to regenerate it.",
            found_schema_version=schema_version,
            required_schema_version=REQUIRED_SCHEMA_VERSION,
        )

    current_hash = _hash_file(docx)
    raw_source_block = ledger.get("source")
    source_block: dict[str, Any] = (
        raw_source_block if isinstance(raw_source_block, dict) else {}
    )
    recorded_hash = source_block.get("sha256")
    if recorded_hash != current_hash:
        raise PreflightFailure(
            "hash_mismatch",
            role,
            f"The {role} document has changed since it was last checked. "
            f"Re-run /definition-check before conforming.",
            recorded_sha256=recorded_hash,
            current_sha256=current_hash,
        )

    run_status = ledger.get("run_status")
    if run_status not in COMPLETED_RUN_STATUSES:
        raise PreflightFailure(
            "incomplete_run",
            role,
            f"The {role} document's earlier definition check did not finish "
            f"({run_status!r}). Re-run /definition-check.",
            run_status=run_status,
        )

    incomplete_stages = []
    for stage in REVIEW_STAGES:
        stage_block = ledger.get(stage)
        status = stage_block.get("status") if isinstance(stage_block, dict) else None
        if status != "complete":
            incomplete_stages.append({"stage": stage, "status": status})
    if incomplete_stages:
        raise PreflightFailure(
            "incomplete_review",
            role,
            f"The {role} document's definition check is only partly done. "
            f"/conform cannot rely on it yet; re-run /definition-check.",
            incomplete_stages=incomplete_stages,
        )

    return {
        "document_id": ledger.get("source", {}).get("document_id"),
        "name": ledger.get("source", {}).get("name"),
        "sha256": current_hash,
        "schema_version": schema_version,
        "run_status": run_status,
        "coverage": source_block.get("coverage", {}),
        "methods_run": ledger.get("methods_run", []),
        "methods_not_run": ledger.get("methods_not_run", []),
    }


def run_preflight(
    source_docx: str, source_ledger: str, core_docx: str, core_ledger: str
) -> dict[str, Any]:
    """Run the complete two-document preflight; raise PreflightFailure on any stop condition."""

    source_summary = check_document("source", source_docx, source_ledger)
    core_summary = check_document("core", core_docx, core_ledger)
    return {
        "status": "ok",
        "source": source_summary,
        "core": core_summary,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-docx", required=True)
    parser.add_argument("--source-ledger", required=True)
    parser.add_argument("--core-docx", required=True)
    parser.add_argument("--core-ledger", required=True)
    parser.add_argument(
        "--output",
        help="Optional path to also write the JSON result to, in addition to stdout.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = run_preflight(
            args.source_docx, args.source_ledger, args.core_docx, args.core_ledger
        )
        exit_code = 0
    except PreflightFailure as exc:
        result = exc.to_dict()
        exit_code = EXIT_CODES[exc.stop_reason]

    payload = json.dumps(result, indent=2, sort_keys=True)
    print(payload)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
