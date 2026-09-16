#!/usr/bin/env python3
"""Session-start banner for CODEX for Legal.

Codex shows a hook's ``systemMessage`` to the user and passes
``additionalContext`` to the model only, so the banner travels both ways: a
one-line status the host renders, and the full card for the model. Only the
Codex packages ship hooks, so this always speaks Codex; Codex sets
``CLAUDE_PLUGIN_ROOT`` for plugin hooks too, so that variable says nothing
about the host.

Every installed CODEX for Legal plugin carries this hook and Codex runs each
one at session start. The first to run leaves a marker for the session and
prints; the others find it and stand down, so one session shows one card.

Reads ``~/.lq/`` if it exists and never writes there. Prints nothing on any
error.

The card names one first move per plugin, e.g. "Have a markup? $read-redline
on it." That line is data: ``pluginctl pack`` writes it to ``banner.json``
beside this file from ``plugin.release.yaml``, and the banner shows it only
when every ``$name`` in it is in the live catalog. Never a skill from memory.
"""

from __future__ import annotations

import sys

# Codex and Claude Code run hooks with whatever `python3` is on PATH. Everything
# below needs 3.12 (datetime.UTC, PEP 695 in sibling skills). A hook must fail
# open: on an older interpreter, print nothing and exit 0, never a traceback.
if sys.version_info < (3, 12):  # noqa: UP036 - the probe is the point
    pass
    raise SystemExit(0)


import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
PACKAGED_CATALOG = HOOKS_DIR.parent / "skills" / "lq-start" / "scripts" / "catalog.py"
AUTHORED_CATALOG = (
    HOOKS_DIR.parent / "skills" / "core" / "lq-start" / "scripts" / "catalog.py"
)
CATALOG = PACKAGED_CATALOG if PACKAGED_CATALOG.is_file() else AUTHORED_CATALOG
MARK = (
    "██      ██████ ",
    "██      ██  ██ ",
    "██      ██ ▄██ ",
    "██████  █████▄ ",
)
BANNER_DATA = HOOKS_DIR / "banner.json"
NEW_HERE = "New here? $lq-start shows what's on the shelf."
NOT_ADVICE = "Not legal advice"
SKILL_TOKEN = re.compile(r"\$([a-z0-9-]+)")
SESSION_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _render(text: str, prefix: str) -> str:
    return SKILL_TOKEN.sub(lambda m: f"{prefix}{m.group(1)}", text)


def _session_id() -> str | None:
    """The session id from the hook input on stdin, or None."""
    try:
        data = json.load(sys.stdin)
    except (OSError, ValueError):
        return None
    value = data.get("session_id") if isinstance(data, dict) else None
    return value if isinstance(value, str) and SESSION_ID.match(value) else None


def _claim_session(session_id: str | None) -> bool:
    """True for the first banner of a session; False once a sibling has printed.

    The marker lives in the temp folder, keyed by session id, and is created
    exclusively, so two hooks racing cannot both win. Without a session id, or
    if the marker cannot be written, the card is shown: one card too many
    beats none."""
    if session_id is None:
        return True
    folder = (
        Path(os.environ.get("LQ_BANNER_DIR") or tempfile.gettempdir())
        / "lq-codex-banner"
    )
    try:
        folder.mkdir(parents=True, exist_ok=True)
        fd = os.open(folder / session_id, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    except OSError:
        return True
    os.close(fd)
    return True


def _banner_data() -> dict[str, str]:
    if not BANNER_DATA.is_file():
        return {}
    try:
        data = json.loads(BANNER_DATA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return (
        {k: v for k, v in data.items() if isinstance(v, str)}
        if isinstance(data, dict)
        else {}
    )


def _lq_home() -> Path:
    return Path(os.environ.get("LQ_HOME") or Path.home() / ".lq")


def _status_line() -> str | None:
    """Moments kept and last debrief from the store's own files, or None."""
    home = _lq_home()
    profile = home / "profile.json"
    if not profile.is_file():
        return None
    try:
        json.loads(profile.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    moments = 0
    last_debrief: datetime | None = None
    journey = home / "journey.jsonl"
    if journey.is_file():
        for raw in journey.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "lq_moment":
                moments += 1
            elif kind == "debrief_run":
                stamp = event.get("at") or event.get("ts")
                if isinstance(stamp, str):
                    try:
                        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=UTC)
                    if last_debrief is None or parsed > last_debrief:
                        last_debrief = parsed
    parts = [f"{moments} moment{'' if moments == 1 else 's'} kept"]
    if last_debrief is not None:
        days = (datetime.now(UTC) - last_debrief).days
        parts.append("debriefed today" if days < 1 else f"last debrief {days}d ago")
    return " · ".join(parts)


def _installed() -> tuple[set[str], set[str]]:
    """(skill names, plugin ids) the live catalog can see; empty when it cannot run."""
    if not CATALOG.is_file():
        return set(), set()
    try:
        out = subprocess.run(
            [sys.executable, str(CATALOG), "--all-plugins", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        ).stdout
        skills = json.loads(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return set(), set()
    if not isinstance(skills, list):
        return set(), set()
    names = {s["name"] for s in skills if isinstance(s, dict) and s.get("name")}
    plugins = {s["plugin"] for s in skills if isinstance(s, dict) and s.get("plugin")}
    return names, plugins


def _first_move(
    data: dict[str, str], installed: set[str], plugins: set[str]
) -> str | None:
    """The plugin's first move: only when every skill it names is installed,
    and only when this is the sole CODEX for Legal plugin here. With siblings
    installed, one plugin's first move would speak for all of them, so the
    card invites the shelf instead."""
    if len(plugins) > 1:
        return None
    move = data.get("first_move", "").strip()
    if not move:
        return None
    named = set(SKILL_TOKEN.findall(move))
    if not named or not named <= installed:
        return None
    return move


def build_card(
    status: str | None,
    first_move: str | None,
    installed: int,
    *,
    prefix: str = "$",
) -> list[str]:
    shelf = (
        f"Shelf: $lq-start   ·   {installed} skills installed"
        if installed
        else "Shelf: $lq-start"
    )
    right = [
        "CODEX FOR LEGAL   by LegalQuants",
        status or first_move or NEW_HERE,
        shelf,
        NOT_ADVICE,
    ]
    return [
        f"{mark}  {_render(text, prefix)}"
        for mark, text in zip(MARK, right, strict=True)
    ]


def main() -> int:
    if not _claim_session(_session_id()):
        return 0
    prefix = "$"
    status = _status_line()
    installed, plugins = _installed()
    first_move = _first_move(_banner_data(), installed, plugins)
    card = build_card(status, first_move, len(installed), prefix=prefix)
    context = (
        "\n".join(card)
        + "\n\nThis is the CODEX for Legal session card; the host has already "
        "shown it. Do not repeat it. If the user asks what the plugin can do, "
        f"run {prefix}lq-start."
    )
    short = (
        status.split(" · ")[0] if status else _render(first_move or "New here", prefix)
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                },
                "systemMessage": (
                    f"CODEX for Legal · {short} · {prefix}lq-start for the shelf"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 - a banner must never break a session
        raise SystemExit(0) from None
