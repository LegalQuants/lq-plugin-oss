"""The debrief watermark is the mining loop: files a debrief never recorded
must resurface on the next scan, and recorded ones must stay skipped — in the
content scan and in the consent preview alike."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "skills" / "companion" / "lq-reflect" / "scripts" / "debrief_scan.py"


def _store_with_session(tmp_path: Path, tag: str) -> tuple[Path, str]:
    store = tmp_path / "store"
    store.mkdir(exist_ok=True)
    today = date.today().isoformat()
    fname = f"rollout-{today}-{tag}.jsonl"
    (store / fname).write_text(
        json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": "a real prompt about contracts"},
                "timestamp": f"{today}T10:00:00Z",
            }
        )
        + "\n"
    )
    return store, fname


def _write_state(state_dir: Path, scanned: list[str]) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "scan_state.json").write_text(
        json.dumps(
            {
                "scanned": [
                    {"file": n, "debrief": "j-0001", "at": "2026-01-01T00:00:00Z"}
                    for n in scanned
                ]
            }
        )
    )
    return state_dir


def _scan(store: Path, state: Path, *extra: str) -> dict:
    out = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--store",
            str(store),
            "--state",
            str(state),
            "--window",
            "7d",
            *extra,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def test_unrecorded_session_resurfaces_on_next_scan(tmp_path: Path) -> None:
    store, fname = _store_with_session(tmp_path, "alpha")
    state = _write_state(tmp_path / "state", scanned=[])
    summary = _scan(store, state)
    assert fname in {s["file"] for s in summary["sessions"]}


def test_recorded_session_is_skipped(tmp_path: Path) -> None:
    store, fname = _store_with_session(tmp_path, "beta")
    state = _write_state(tmp_path / "state", scanned=[fname])
    summary = _scan(store, state)
    assert fname not in {s["file"] for s in summary["sessions"]}


def test_consent_preview_matches_the_watermark(tmp_path: Path) -> None:
    store, fname = _store_with_session(tmp_path, "gamma")
    pending = _write_state(tmp_path / "pending", scanned=[])
    listed = _scan(store, pending, "--list")
    assert fname in {f["file"] for f in listed["files"]}

    recorded = _write_state(tmp_path / "recorded", scanned=[fname])
    listed = _scan(store, recorded, "--list")
    assert fname not in {f["file"] for f in listed["files"]}
