#!/usr/bin/env python3
"""calibration_gate.py — record and enforce the calibration gate.

The calibration gate is an artifact, not a memory: once the colour table (PDF)
or the tracked-change report (Word) is confirmed, this script writes
``calibration.confirmed.json`` beside ``extract.json`` carrying the
calibration block, a status, and the SHA-256 of the extract it confirms.
``make_issues_list.py`` and both annotators refuse to build without a valid
artifact, so no deliverable can drift away from the calibration the reviewer
signed off.

    # after a human confirmed the calibration table:
    python3 scripts/calibration_gate.py extract.json --status confirmed

    # scripted, non-interactive runs only, with an explicit reason:
    python3 scripts/calibration_gate.py extract.json --status declared-default \\
        --reason "batch run over a folder; no reviewer present"

Re-run the same command after any edit to extract.json (for example appending
manual-review items under ``quarantined``): the artifact hashes the extract,
so a changed extract invalidates the old gate on purpose.

Runs on the standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

GATE_NAME = "calibration.confirmed.json"
STATUSES = ("confirmed", "declared-default")


def extract_sha256(extract_path: Path) -> str:
    return hashlib.sha256(Path(extract_path).read_bytes()).hexdigest()


def gate_path_for(extract_path: Path) -> Path:
    return Path(extract_path).resolve().parent / GATE_NAME


def gate_state_line(gate: dict) -> str:
    """One plain sentence for receipts, identical across every downstream
    artifact."""
    if gate.get("status") == "confirmed":
        return "Calibration gate: confirmed."
    return f"Calibration gate: declared default — {gate.get('reason', '')}"


def write_gate(extract_path: Path, status: str, reason: str | None = None) -> Path:
    extract_path = Path(extract_path)
    if status not in STATUSES:
        raise SystemExit(
            f"--status must be one of {', '.join(STATUSES)}; got {status!r}."
        )
    if status == "declared-default" and not (reason or "").strip():
        raise SystemExit(
            "declared-default requires --reason: say why no human confirmed "
            "the calibration."
        )
    try:
        extract = json.loads(extract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read {extract_path}: {exc}") from exc
    calibration = extract.get("calibration")
    if not isinstance(calibration, dict):
        raise SystemExit(
            f"{extract_path} has no 'calibration' block; re-run the parser "
            "before recording the gate."
        )
    gate = {
        "artifact": "calibration.confirmed",
        "extract_sha256": extract_sha256(extract_path),
        "status": status,
        "calibration": calibration,
    }
    if (reason or "").strip():
        gate["reason"] = (reason or "").strip()
    out = gate_path_for(extract_path)
    out.write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({gate_state_line(gate)})")
    return out


def require_gate(extract_path: Path) -> dict:
    """Return the gate for ``extract_path`` or exit nonzero with a plain
    message. Downstream scripts call this before building anything."""
    extract_path = Path(extract_path)
    path = gate_path_for(extract_path)
    if not path.exists():
        raise SystemExit(
            f"refusing to build: {GATE_NAME} not found beside {extract_path}. "
            "Record the calibration gate first "
            "(python3 scripts/calibration_gate.py extract.json --status confirmed, "
            "or --status declared-default --reason ... in a scripted run)."
        )
    try:
        gate = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"refusing to build: cannot read {path}: {exc}") from exc
    if not isinstance(gate, dict):
        raise SystemExit(f"refusing to build: {path} must contain a JSON object.")
    status = gate.get("status")
    if status not in STATUSES:
        raise SystemExit(
            f"refusing to build: {path} carries status {status!r}; "
            f"expected one of {', '.join(STATUSES)}."
        )
    if status == "declared-default" and not (gate.get("reason") or "").strip():
        raise SystemExit(
            f"refusing to build: {path} is declared-default with no reason."
        )
    if not isinstance(gate.get("calibration"), dict):
        raise SystemExit(f"refusing to build: {path} has no 'calibration' block.")
    recorded = gate.get("extract_sha256")
    current = extract_sha256(extract_path)
    if recorded != current:
        raise SystemExit(
            f"refusing to build: {path} confirms extract hash "
            f"{str(recorded)[:12]}… but the current extract hashes "
            f"{current[:12]}…. extract.json changed after the gate was "
            "recorded; re-run scripts/calibration_gate.py with the same "
            "status to re-stamp it."
        )
    return gate


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="calibration_gate.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("extract", help="extract.json from either redline parser")
    ap.add_argument("--status", required=True, choices=STATUSES)
    ap.add_argument(
        "--reason",
        help="why no human confirmed the calibration (required for declared-default)",
    )
    a = ap.parse_args(argv[1:])
    write_gate(Path(a.extract), a.status, a.reason)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
