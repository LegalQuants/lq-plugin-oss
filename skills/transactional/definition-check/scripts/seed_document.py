#!/usr/bin/env python3
"""Create bounded overlapping discovery seeds for definition-check workers."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

from _runtime_gate import require_supported_python

require_supported_python()

from definition_check.ooxml import IntakeError, extract_docx
from definition_check.seeds import generate_discovery_seeds
from definition_check.workspace import (
    WorkspaceError,
    ensure_workspace,
    require_within_workspace,
)


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite discovery seeds {path!s}")
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
        description="Create bounded definition-discovery seeds from one DOCX."
    )
    parser.add_argument("input", type=Path, help="Original DOCX path")
    parser.add_argument(
        "--output", type=Path, required=True, help="New JSON seed artifact"
    )
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--max-characters", type=int, default=4000)
    parser.add_argument("--overlap", type=int, default=300)
    parser.add_argument("--max-outline-items", type=int, default=32)
    parser.add_argument("--max-outline-characters", type=int, default=4000)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        work_dir = ensure_workspace(args.work_dir.resolve())[0]
        output = require_within_workspace(
            args.output, work_dir, label="discovery seed output"
        )
        source = extract_docx(args.input.resolve())
        seeds = generate_discovery_seeds(
            source,
            max_characters=args.max_characters,
            overlap=args.overlap,
            max_outline_items=args.max_outline_items,
            max_outline_characters=args.max_outline_characters,
        )
        payload = {
            "source": {
                "document_id": source.document_id,
                "name": source.name,
                "sha256": source.sha256,
            },
            "coverage": source.coverage,
            "warnings": source.warnings,
            "seed_count": len(seeds),
            "seeds": seeds,
        }
        _atomic_json(output, payload)
    except (IntakeError, OSError, ValueError, WorkspaceError) as exc:
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
                "status": "completed",
                "seeds": len(seeds),
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
