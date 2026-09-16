"""The debrief's store and scanner, mechanically: a store opens without a
baseline, kept items are shape not substance, and a planted week surfaces."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "companion" / "lq-reflect" / "scripts"
STORE = SCRIPTS / "profile_store.py"
SCAN = SCRIPTS / "debrief_scan.py"


def _store(root: Path, cmd: str, payload: dict | list | None = None, *extra: str):
    return subprocess.run(
        [sys.executable, str(STORE), "--root", str(root), cmd, *extra],
        input=json.dumps(payload) if payload is not None else "",
        capture_output=True,
        text=True,
        check=False,
    )


def test_open_creates_a_store_without_a_level(tmp_path: Path) -> None:
    root = tmp_path / "lq"
    out = _store(root, "open", {"quoting": "B"})
    assert out.returncode == 0, out.stderr
    prof = json.loads((root / "profile.json").read_text())
    assert prof["preferences"]["quoting"] == "B"
    assert "level" not in prof["fluency"]
    status = json.loads(_store(root, "status").stdout)
    assert status["level"] is None
    rendered = (root / "lqprofile.md").read_text()
    assert "Level:" not in rendered
    assert "moments kept" in rendered


def test_open_refuses_an_unknown_posture(tmp_path: Path) -> None:
    out = _store(tmp_path / "lq", "open", {"quoting": "yes please"})
    assert out.returncode != 0


def test_kept_change_and_moment_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "lq"
    assert _store(root, "open", {"quoting": "A"}).returncode == 0
    events = [
        {
            "type": "friction",
            "source": "debrief",
            "lesson": "ask for clause numbers before analysis",
            "signature": "drafting sessions whose first ask names a clause",
            "status": "kept",
        },
        {
            "type": "lq_moment",
            "source": "debrief",
            "what": "caught a per-claim cap read as aggregate and had the exposure "
            "table redone before it went to the client",
            "technique": "directed and corrected the model on the draft's terms",
        },
        {"type": "debrief_run", "source": "debrief", "files_read": ["s-1.jsonl"]},
    ]
    out = _store(root, "append", events)
    assert out.returncode == 0, out.stderr
    status = json.loads(_store(root, "status").stdout)
    assert status["lq_moments"] == 1
    assert status["lessons_kept"] == 1
    assert status["debriefs"] == 1
    scanned = json.loads((root / "scan_state.json").read_text())["scanned"]
    assert [s["file"] for s in scanned] == ["s-1.jsonl"]


def test_append_refuses_a_moment_that_names_parties(tmp_path: Path) -> None:
    root = tmp_path / "lq"
    assert _store(root, "open", {"quoting": "A"}).returncode == 0
    out = _store(
        root,
        "append",
        {
            "type": "lq_moment",
            "source": "debrief",
            "what": "redid the exposure table for Acme Holdings against Beta Capital",
            "technique": "corrected the model",
        },
    )
    assert out.returncode != 0
    assert "shape-never-substance" in out.stderr
    assert (root / "journey.jsonl").read_text() == ""


def _session(store: Path, tag: str, prompts: list[str]) -> str:
    today = date.today().isoformat()
    name = f"rollout-{today}-{tag}.jsonl"
    lines = [
        json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": text},
                "timestamp": f"{today}T1{i}:00:00Z",
            }
        )
        for i, text in enumerate(prompts)
    ]
    (store / name).write_text("\n".join(lines) + "\n")
    return name


def test_planted_week_surfaces_in_the_scan(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    state = tmp_path / "lq"
    assert _store(state, "open", {"quoting": "A"}).returncode == 0

    uncited = "summarise the change of control provisions and what they mean for us"
    manual = "here is the next section of the markup, what changed here?"
    win = (
        "no, the indemnity cap in the draft is per claim not aggregate, "
        "redo the exposure table"
    )
    _session(store, "spa", [uncited, "thanks, put that in the note"])
    _session(store, "redline-1", [manual, manual, manual])
    _session(store, "redline-2", [manual, "and this section?"])
    _session(store, "cap", ["build the exposure table from the draft", win])

    out = subprocess.run(
        [
            sys.executable,
            str(SCAN),
            "--store",
            str(store),
            "--state",
            str(state),
            "--window",
            "7d",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    summary = json.loads(out.stdout)
    assert summary["stats"]["sessions_scanned"] == 4
    seen = " ".join(p for s in summary["sessions"] for p in s["prompts"])
    for planted in (uncited, win):
        assert planted[:40] in seen, planted
    reps = summary["repetitions"]
    assert reps and reps[0]["count"] >= 4, "the manual redline should cluster first"
    assert reps[0]["untrusted"] is True
    assert "UNTRUSTED" in summary["_warning"]
