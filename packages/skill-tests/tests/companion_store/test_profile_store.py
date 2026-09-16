"""PRD-03 acceptance: the store that never existed.

A fresh user is a normal state: reads answer cleanly, every companion skill can
open a store through one consent-gated `save` door, and a retried save never
duplicates. Reproduces the 6 Sep 2026 fresh-root FileNotFoundError.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "skills" / "companion" / "lq-reflect" / "scripts" / "profile_store.py"
COMPANION = ROOT / "skills" / "companion"
CONTRACT = (
    ROOT / "skills" / "companion" / "lq-reflect" / "references" / "store-contract.md"
)

EVENT = {
    "type": "friction",
    "source": "debrief",
    "lesson": "walk through a real user action before approving a design",
    "status": "kept",
}


def run(root: Path, *args: str, payload: dict | list | None = None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        input=json.dumps(payload) if payload is not None else "",
        capture_output=True,
        text=True,
    )


def test_fresh_status_answers_cleanly(tmp_path):
    r = run(tmp_path / "fresh", "status")
    assert r.returncode == 0
    assert json.loads(r.stdout) == {"exists": False}
    assert "Traceback" not in r.stderr


def test_fresh_status_since_never_writes(tmp_path):
    fresh = tmp_path / "fresh"
    r = run(fresh, "status", "--since")
    assert r.returncode == 0
    assert json.loads(r.stdout) == {"exists": False}
    assert not fresh.exists()


def test_save_creates_store_and_appends(tmp_path):
    root = tmp_path / "lq"
    r = run(
        root,
        "save",
        "--confirmed",
        payload={"operation_id": "t1", "quoting": "C", "events": [EVENT]},
    )
    assert r.returncode == 0, r.stderr
    assert (root / ".lq-store").exists()
    assert (root / "lqprofile.md").exists()
    events = [
        json.loads(line) for line in (root / "journey.jsonl").read_text().splitlines()
    ]
    assert len(events) == 1
    assert events[0]["id"] == "j-0001"
    assert events[0]["operation_id"] == "t1"


def test_save_is_idempotent_on_operation_id(tmp_path):
    root = tmp_path / "lq"
    payload = {"operation_id": "t1", "quoting": "C", "events": [EVENT]}
    assert run(root, "save", "--confirmed", payload=payload).returncode == 0
    again = run(root, "save", "--confirmed", payload=payload)
    assert again.returncode == 0
    assert "nothing new" in again.stdout
    assert len((root / "journey.jsonl").read_text().splitlines()) == 1


def test_save_appends_to_existing_store_without_quoting(tmp_path):
    root = tmp_path / "lq"
    run(root, "save", "--confirmed", payload={"quoting": "C", "events": []})
    r = run(
        root,
        "save",
        "--confirmed",
        payload={"operation_id": "t2", "events": [EVENT]},
    )
    assert r.returncode == 0, r.stderr
    assert len((root / "journey.jsonl").read_text().splitlines()) == 1
    prof = json.loads((root / "profile.json").read_text())
    assert prof["preferences"]["quoting"] == "C"


def test_save_refuses_to_change_quoting_posture_silently(tmp_path):
    root = tmp_path / "lq"
    run(root, "save", "--confirmed", payload={"quoting": "C", "events": []})
    r = run(
        root,
        "save",
        "--confirmed",
        payload={"operation_id": "t3", "quoting": "A", "events": [EVENT]},
    )
    assert r.returncode != 0
    assert "quoting posture is already C" in r.stderr
    assert not (root / "journey.jsonl").read_text().strip()


def test_save_without_confirmed_writes_nothing(tmp_path):
    root = tmp_path / "lq"
    r = run(root, "save", payload={"quoting": "C", "events": [EVENT]})
    assert r.returncode != 0
    assert "Silence is not consent" in r.stderr
    assert not root.exists()


def test_save_creating_a_store_needs_a_quoting_posture(tmp_path):
    root = tmp_path / "lq"
    r = run(root, "save", "--confirmed", payload={"events": [EVENT]})
    assert r.returncode != 0
    assert "quoting" in r.stderr
    assert not root.exists()


def test_save_keeps_the_substance_backstop(tmp_path):
    risky = {
        **EVENT,
        "lesson": "matter 48219931 for Acme Corp and Beta LLC",
    }
    r = run(
        tmp_path / "lq",
        "save",
        "--confirmed",
        payload={"quoting": "C", "events": [risky]},
    )
    assert r.returncode != 0
    assert "shape-never-substance" in r.stderr


def test_append_render_export_refuse_cleanly_without_a_store(tmp_path):
    missing = tmp_path / "missing"
    for verb_args, payload in (
        (("append",), [EVENT]),
        (("render",), None),
        (("export", "--out", str(tmp_path / "out")), None),
    ):
        r = run(missing, *verb_args, payload=payload)
        assert r.returncode != 0
        assert "no lq store" in r.stderr
        assert "Traceback" not in r.stderr


def test_no_companion_skill_tells_the_user_to_wait_a_week():
    for skill in COMPANION.glob("*/SKILL.md"):
        text = skill.read_text(encoding="utf-8").lower()
        assert "week of real work" not in text, skill
        assert "wait a week" not in text, skill


@pytest.mark.parametrize(
    "skill", ["lq-apply", "lq-mirror", "legalquants", "my-lq-moment", "lq-reflect"]
)
def test_every_store_touching_companion_skill_points_at_the_contract(skill: str):
    text = (COMPANION / skill / "SKILL.md").read_text(encoding="utf-8")
    assert "store-contract.md" in text, f"{skill} does not reference the contract"


def test_save_refuses_same_operation_id_with_different_content(tmp_path):
    root = tmp_path / "lq"
    payload = {"operation_id": "t1", "quoting": "C", "events": [EVENT]}
    assert run(root, "save", "--confirmed", payload=payload).returncode == 0
    changed = {
        "operation_id": "t1",
        "events": [{**EVENT, "lesson": "a different lesson entirely"}],
    }
    r = run(root, "save", "--confirmed", payload=changed)
    assert r.returncode != 0
    assert "already used for different content" in r.stderr
    assert len((root / "journey.jsonl").read_text().splitlines()) == 1


def test_corrupt_journey_line_refuses_writes_and_preserves_bytes(tmp_path):
    root = tmp_path / "lq"
    ok = run(root, "save", "--confirmed", payload={"quoting": "C", "events": [EVENT]})
    assert ok.returncode == 0
    jf = root / "journey.jsonl"
    with open(jf, "a") as f:
        f.write("{not json\n")
    before = jf.read_bytes()
    r = run(root, "save", "--confirmed", payload={"events": [EVENT]})
    assert r.returncode != 0
    assert "line 2" in r.stderr
    assert jf.read_bytes() == before  # preserved, nothing appended
    s = run(root, "status")  # readers still answer, loudly
    assert s.returncode == 0
    assert json.loads(s.stdout)["exists"] is True
    assert "unreadable" in s.stderr


def test_corrupt_profile_json_refuses_cleanly(tmp_path):
    root = tmp_path / "lq"
    ok = run(root, "save", "--confirmed", payload={"quoting": "C", "events": []})
    assert ok.returncode == 0
    (root / "profile.json").write_text("{not json")
    r = run(root, "save", "--confirmed", payload={"events": [EVENT]})
    assert r.returncode != 0
    assert "profile.json is unreadable" in r.stderr
    assert "Traceback" not in r.stderr
    s = run(root, "status")
    assert s.returncode != 0
    assert "Traceback" not in s.stderr


def test_forget_all_removes_only_store_owned_files(tmp_path):
    root = tmp_path / "lq"
    ok = run(root, "save", "--confirmed", payload={"quoting": "C", "events": [EVENT]})
    assert ok.returncode == 0
    (root / "onboarding.json").write_text("{}")  # another component's UI state
    (root / "notes to self.txt").write_text("keep me")
    r = run(root, "forget", "--all", "--confirm")
    assert r.returncode == 0, r.stderr
    assert (root / "notes to self.txt").read_text() == "keep me"
    assert (root / "onboarding.json").exists()
    for owned in (
        ".lq-store",
        "profile.json",
        "journey.jsonl",
        "scan_state.json",
        "state.json",
        "lqprofile.md",
    ):
        assert not (root / owned).exists(), owned
    assert root.is_dir()  # the directory itself stays
