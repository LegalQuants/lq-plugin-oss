#!/usr/bin/env python3
"""Execute one bounded context request against a DOCX for an agent worker."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from _runtime_gate import require_supported_python

require_supported_python()

from definition_check.context import RetrievalBudget, RetrievalState, retrieve
from definition_check.matter import qualify_location
from definition_check.models import ContextRequest, Location
from definition_check.ooxml import IntakeError, extract_docx
from definition_check.workspace import (
    WorkspaceError,
    ensure_workspace,
    require_within_workspace,
)

_MAX_REQUEST_BYTES = 64 * 1024
CONTEXT_REQUEST_SCHEMA_VERSION = "context-request-v1"
CONTEXT_RESULT_SCHEMA_VERSION = "context-result-v1"


def _read_object(path: Path) -> dict:
    if path.stat().st_size > _MAX_REQUEST_BYTES:
        raise ValueError(f"request file exceeds {_MAX_REQUEST_BYTES} bytes")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("request file must contain one JSON object")
    return value


def _request(value: dict) -> ContextRequest:
    allowed = {
        "schema_version",
        "id",
        "candidate_id",
        "request_type",
        "query",
        "reason",
        "requested_by",
        "status",
        "hop",
        "max_results",
        "result_evidence_ids",
    }
    extra = set(value) - allowed
    if extra:
        raise ValueError(f"unsupported request fields: {sorted(extra)}")
    if value.get("schema_version") != CONTEXT_REQUEST_SCHEMA_VERSION:
        raise ValueError("context request has an unsupported schema_version")
    for field in ("id", "candidate_id", "query", "reason", "requested_by"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError(f"context request {field} must be a non-empty string")
    results = value.get("result_evidence_ids", [])
    if not isinstance(results, list) or any(
        not isinstance(item, str) for item in results
    ):
        raise ValueError("result_evidence_ids must be an array of strings")
    return ContextRequest(
        id=str(value["id"]),
        candidate_id=str(value["candidate_id"]),
        request_type=str(value["request_type"]),
        query=str(value["query"]),
        reason=str(value["reason"]),
        requested_by=str(value["requested_by"]),
        status=str(value.get("status", "requested")),
        hop=int(value.get("hop", 1)),
        max_results=int(value.get("max_results", 20)),
        result_evidence_ids=tuple(results),
    )


def _location(value: Optional[dict]) -> Optional[Location]:
    if value is None:
        return None
    allowed = {"part", "block_id", "block_order", "char_start", "char_end"}
    extra = set(value) - allowed
    if extra:
        raise ValueError(f"unsupported location fields: {sorted(extra)}")
    return Location(
        part=str(value["part"]),
        block_id=str(value["block_id"]),
        block_order=int(value["block_order"]),
        char_start=int(value["char_start"]),
        char_end=int(value["char_end"]),
    )


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite context response {path!s}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute one bounded definition-check context request."
    )
    parser.add_argument("input", type=Path, help="Original DOCX path")
    parser.add_argument(
        "--request", type=Path, required=True, help="One ContextRequest JSON object"
    )
    parser.add_argument(
        "--location", type=Path, help="Candidate Location JSON for expand_location"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="New JSON response path"
    )
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--max-requests", type=int, default=8)
    parser.add_argument("--max-hops", type=int, default=3)
    parser.add_argument("--max-results", type=int, default=20)
    parser.add_argument("--max-characters", type=int, default=12_000)
    parser.add_argument("--matter-id")
    parser.add_argument("--document-id")
    parser.add_argument("--version-id")
    parser.add_argument("--snapshot-sha256")
    parser.add_argument("--expected-source-sha256")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        work_dir = ensure_workspace(args.work_dir.resolve())[0]
        request_path = require_within_workspace(
            args.request, work_dir, label="context request"
        )
        output = require_within_workspace(
            args.output, work_dir, label="context response"
        )
        request = _request(_read_object(request_path))
        location = (
            _location(
                _read_object(
                    require_within_workspace(
                        args.location,
                        work_dir,
                        label="context request location",
                    )
                )
            )
            if args.location
            else None
        )
        budget = RetrievalBudget(
            max_requests=args.max_requests,
            max_hops=args.max_hops,
            max_results=args.max_results,
            max_characters=args.max_characters,
        )
        if (
            min(
                budget.max_requests,
                budget.max_hops,
                budget.max_results,
                budget.max_characters,
            )
            < 1
        ):
            raise ValueError("all retrieval budgets must be positive")
        source = extract_docx(args.input.resolve())
        matter_scope = (
            args.matter_id,
            args.document_id,
            args.version_id,
            args.snapshot_sha256,
        )
        if any(matter_scope) and not all(matter_scope):
            raise ValueError(
                "matter-aware retrieval requires matter, document, version, and snapshot IDs"
            )
        if args.snapshot_sha256 and not re.fullmatch(
            r"[0-9a-f]{64}", args.snapshot_sha256
        ):
            raise ValueError("snapshot SHA-256 is invalid")
        if args.expected_source_sha256 and source.sha256 != args.expected_source_sha256:
            raise ValueError(
                "source SHA-256 does not match the selected document version"
            )
        result = retrieve(source, request, RetrievalState(budget), location=location)
        payload = {
            "schema_version": CONTEXT_RESULT_SCHEMA_VERSION,
            "source": {"document_id": source.document_id, "sha256": source.sha256},
            "request": {
                "schema_version": CONTEXT_REQUEST_SCHEMA_VERSION,
                **asdict(result.request),
            },
            "evidence": [asdict(item) for item in result.evidence],
            "note": result.note,
        }
        if all(matter_scope):
            payload.update(
                {
                    "view_type": "bounded_context_retrieval",
                    "authority": "source_evidence_only",
                    "matter_id": args.matter_id,
                    "document_id": args.document_id,
                    "version_id": args.version_id,
                    "snapshot_sha256": args.snapshot_sha256,
                }
            )
            for evidence in payload["evidence"]:
                evidence["location"] = qualify_location(
                    evidence["location"],
                    matter_id=args.matter_id,
                    document_id=args.document_id,
                    version_id=args.version_id,
                )
        _atomic_json(output, payload)
    except (
        IntakeError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
        WorkspaceError,
        json.JSONDecodeError,
    ) as exc:
        print(
            json.dumps(
                {"status": "failed", "error": str(exc)},
                ensure_ascii=True,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": result.request.status,
                "evidence": len(result.evidence),
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
