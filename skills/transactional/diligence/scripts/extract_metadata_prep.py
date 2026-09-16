#!/usr/bin/env python3
"""Public Diligence entrypoint for shared metadata preparation."""

from __future__ import annotations

import json
import runpy
import shutil
import sys
from pathlib import Path

SHARED_DIR = Path(__file__).with_name("shared")


def main() -> None:
    sys.path.insert(0, str(SHARED_DIR))
    runpy.run_path(str(SHARED_DIR / "extract_metadata_prep.py"), run_name="__main__")
    try:
        outdir = Path(sys.argv[sys.argv.index("--outdir") + 1])
    except (ValueError, IndexError):
        return
    records = outdir / "regex-metadata"
    legacy_records = outdir / "metadata"
    legacy_records.mkdir(parents=True, exist_ok=True)
    for source in sorted(records.glob("*.json")):
        shutil.copyfile(source, legacy_records / source.name)
    read_plan_path = outdir / "read-plan.json"
    if not read_plan_path.is_file():
        return
    read_plan = json.loads(read_plan_path.read_text(encoding="utf-8"))
    needs_model = sorted(
        row["id"]
        for row in read_plan.get("documents", [])
        if row.get("disposition") in {"reader-required", "regex-audit"}
    )
    (outdir / "worklist.json").write_text(
        json.dumps({"needs_model": needs_model}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
