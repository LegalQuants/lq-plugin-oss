"""PRD-01 acceptance: the orientation marker — show once, never nag.

The marker is UI state, not learning data: no onboarding command may create
profile.json or journey.jsonl. Ported mechanism from the amended plugin's
shared/onboarding.py (claim/ack with an expiring token).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "skills" / "companion" / "legalquants" / "scripts" / "onboarding.py"
COMPANION = ROOT / "skills" / "companion"


def run(root: Path, *args: str):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        capture_output=True,
        text=True,
    )


def test_first_offer_claims_a_token(tmp_path):
    r = run(tmp_path, "offer")
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["show"] is True
    assert out["token"]


def test_second_offer_inside_the_window_does_not_double_show(tmp_path):
    token = json.loads(run(tmp_path, "offer").stdout)["token"]
    again = json.loads(run(tmp_path, "offer").stdout)
    assert again == {"show": False, "reason": "another_session_is_showing_it"}
    # after the claim expires, a fresh offer gets a new token
    state = json.loads((tmp_path / "onboarding.json").read_text())
    state["expires"] = time.time() - 1
    (tmp_path / "onboarding.json").write_text(json.dumps(state))
    fresh = json.loads(run(tmp_path, "offer").stdout)
    assert fresh["show"] is True and fresh["token"] != token


def test_shown_requires_the_matching_token(tmp_path):
    token = json.loads(run(tmp_path, "offer").stdout)["token"]
    bad = run(tmp_path, "shown", "--token", "wrong")
    assert bad.returncode != 0
    assert json.loads((tmp_path / "onboarding.json").read_text())["shown"] is False
    good = run(tmp_path, "shown", "--token", token)
    assert good.returncode == 0
    assert json.loads(run(tmp_path, "offer").stdout) == {
        "show": False,
        "reason": "already_shown",
    }


def test_corrupt_state_is_preserved_and_still_shows(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "onboarding.json").write_text("{ not json")
    out = json.loads(run(tmp_path, "offer").stdout)
    assert out["show"] is True
    assert "repair" in out["warning"]
    assert (tmp_path / "onboarding.json").read_text() == "{ not json"


def test_onboarding_never_creates_learning_files(tmp_path):
    run(tmp_path, "offer")
    token = json.loads((tmp_path / "onboarding.json").read_text())["token"]
    run(tmp_path, "shown", "--token", token)
    assert not (tmp_path / "profile.json").exists()
    assert not (tmp_path / "journey.jsonl").exists()


def test_no_slash_invocations_in_companion_copy():
    import re

    # Any backticked `/name` or `/name:sub` — the invocation forms Codex users
    # must never be told to type. URL paths like `/profile/<slug>` don't match
    # (no closing backtick after a bare name segment).
    pattern = re.compile(r"`/[a-z0-9-]+(:[a-z0-9-]+)?`")
    for skill_md in COMPANION.glob("*/SKILL.md"):
        assert not pattern.search(skill_md.read_text(encoding="utf-8")), (
            f"{skill_md} still invokes with /"
        )


def test_shown_before_any_offer_refuses_cleanly(tmp_path):
    r = run(tmp_path / "fresh", "shown", "--token", "abc")
    assert r.returncode != 0
    assert "no welcome claim" in r.stderr
    assert "Traceback" not in r.stderr


def test_every_companion_skill_runs_the_orientation_marker():
    # The first-use cold open must not depend on
    # discovering legalquants/lq-start first. Every companion skill offers the
    # marker; the procedure itself stays in legalquants §2 (one copy, no drift).
    for skill_md in sorted(COMPANION.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        assert "onboarding.py offer`" in text, f"{skill_md} never offers the marker"
        if skill_md.parent.name == "legalquants":
            continue  # legalquants owns the cold-open procedure (its §2)
        assert "../legalquants/scripts/onboarding.py" in text, skill_md
        assert "shown --token" in text, f"{skill_md} never closes the marker"
        assert "never gated" in text, f"{skill_md} may gate the task on onboarding"
        assert "onboarding.py preview" in text, f"{skill_md} has no replay path"


def test_legalquants_owns_the_replay_procedure():
    text = (COMPANION / "legalquants" / "SKILL.md").read_text(encoding="utf-8")
    assert "onboarding.py preview" in text
    assert "never read or written" in text  # replay never affects once-ever state


def test_preview_replays_without_touching_the_marker(tmp_path):
    root = tmp_path / "fresh"
    r = run(root, "preview")
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["show"] is True and out["preview"] is True
    assert not root.exists() or not (root / "onboarding.json").exists()
    # a real offer still fires afterwards — preview claimed nothing
    assert json.loads(run(root, "offer").stdout)["show"] is True


def test_preview_still_replays_after_shown(tmp_path):
    root = tmp_path / "lq"
    token = json.loads(run(root, "offer").stdout)["token"]
    assert run(root, "shown", "--token", token).returncode == 0
    assert json.loads(run(root, "offer").stdout)["show"] is False
    r = run(root, "preview")
    assert json.loads(r.stdout)["show"] is True
    # and the marker stays exactly as shown left it
    state = json.loads((root / "onboarding.json").read_text())
    assert state["shown"] is True and "token" not in state
