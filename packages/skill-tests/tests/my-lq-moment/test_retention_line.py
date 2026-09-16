"""The §3.5 retention payload the skill documents is what the store accepts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STORE = ROOT / "skills/companion/lq-reflect/scripts/profile_store.py"
SKILL = ROOT / "skills/companion/my-lq-moment/SKILL.md"

LINE = (
    "Earned My LQ Moment: lawyer-steered redline issue map grouped by commercial "
    "effect; caught a mislabelled indemnity cap; coverage check plus spot-check."
)
EVENT = {
    "type": "lq_moment",
    "source": "user",
    "what": LINE,
    "technique": "set severity rules up front; check labels against source clauses",
}


def _store(root: Path, verb: str, payload: dict | None = None):
    command = [sys.executable, str(STORE), "--root", str(root), verb]
    if verb == "save":
        command.append("--confirmed")
    return subprocess.run(
        command,
        input=json.dumps(payload) if payload is not None else "",
        text=True,
        capture_output=True,
    )


def test_skill_documents_the_exact_event_shape() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "exactly one `lq_moment`" in text
    assert "source is `user`" in text
    assert "`save --confirmed`" in text


def test_documented_payload_is_accepted_and_writes_one_event(tmp_path: Path) -> None:
    root = tmp_path / "lq"
    payload = {
        "operation_id": "my-lq-moment-test-accepted",
        "quoting": "B",
        "events": [EVENT],
    }
    done = _store(root, "save", payload)
    assert done.returncode == 0, done.stderr
    lines = (root / "journey.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["type"] == "lq_moment"
    status = json.loads(_store(root, "status").stdout)
    assert status["lq_moments"] == 1


def test_store_refuses_a_line_with_matter_substance(tmp_path: Path) -> None:
    root = tmp_path / "lq"
    bad = dict(EVENT, what="Earned My LQ Moment: Northstar Biologics deal at $68000000")
    payload = {
        "operation_id": "my-lq-moment-test-refused",
        "quoting": "B",
        "events": [bad],
    }
    done = _store(root, "save", payload)
    assert done.returncode != 0
    assert "shape-never-substance" in done.stderr
    assert not root.exists()


def test_save_is_idempotent_on_operation_id(tmp_path: Path) -> None:
    root = tmp_path / "lq"
    payload = {
        "operation_id": "my-lq-moment-test-idempotent",
        "quoting": "B",
        "events": [EVENT],
    }
    assert _store(root, "save", payload).returncode == 0
    assert _store(root, "save", payload).returncode == 0
    lines = (root / "journey.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
