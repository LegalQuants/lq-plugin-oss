#!/usr/bin/env python3
"""Optional Codex lifecycle adapter for the provider-neutral /wiki engine.

This file is deliberately outside the packaged ``skills/wiki`` tree. ChatGPT
Work never needs or discovers it; a Codex lifecycle event is the sole capability
proof. The adapter is inert by default, has no per-matter state, and always
fails open.
"""

from __future__ import annotations

import sys

# Codex and Claude Code run hooks with whatever `python3` is on PATH. Everything
# below needs 3.12 (datetime.UTC, PEP 695 in sibling skills). A hook must fail
# open: on an older interpreter, say so once at session start and exit 0,
# never a traceback.
if sys.version_info < (3, 12):  # noqa: UP036 - the probe is the point
    if "session-start" in sys.argv:
        found = f"{sys.version_info[0]}.{sys.version_info[1]}"
        print(
            "CODEX for Legal: Wiki automation is off because its hooks need "
            f"Python 3.12 or newer on PATH (found {found})."
        )
    raise SystemExit(0)


import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PACKAGED_SCRIPTS = PLUGIN_ROOT / "skills" / "wiki" / "scripts"
AUTHORED_SCRIPTS = PLUGIN_ROOT / "skills" / "core" / "wiki" / "scripts"
# Choose by the engine file, not the folder: a stale empty folder must not win.
SCRIPTS = (
    PACKAGED_SCRIPTS if (PACKAGED_SCRIPTS / "wiki.py").is_file() else AUTHORED_SCRIPTS
)
# The Companion ships this hook without the wiki skill. No engine, nothing to
# do: exit quietly rather than fail the hook on every session start and prompt.
if not (SCRIPTS / "wiki.py").is_file():
    raise SystemExit(0)
sys.path.insert(0, str(SCRIPTS))

import wiki  # noqa: E402, I001


AUTOMATION_NOTICE = (
    "Codex can optionally bring relevant Wiki notes into selected projects or "
    "all projects. Use $wiki and ask for automation settings if you want it."
)
RUNTIME_SCHEMA_VERSION = 1


def read_input() -> dict:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _confirmed_automation_enabled(setting: str) -> bool:
    """Read only the confirmed Wiki automation setting, last value wins.

    This intentionally duplicates a few lines of the retrieval parser. The
    hook must decide *before* it accesses a prompt, so it cannot depend on a
    retrieval entrypoint that may already have read it.
    """
    playbook = wiki.user_playbook_path()
    if not playbook.is_file():
        return False
    confirmed = False
    value: str | None = None
    prefix = f"- [wiki] automatic {setting}:"
    try:
        lines = playbook.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    for raw in lines:
        line = raw.strip()
        if line.startswith("## "):
            confirmed = line == "## Confirmed"
            continue
        if not confirmed or not line.casefold().startswith(prefix):
            continue
        candidate = line[len(prefix) :].strip().split(maxsplit=1)
        if candidate:
            value = candidate[0].casefold()
    return value == "on"


def _default_wiki() -> Path | None:
    """Resolve only the user-level default wiki; never create or guess one."""
    try:
        candidate = wiki.resolve_wiki(
            argparse.Namespace(wiki=None, wiki_name=None, ignore_current=True)
        )
    except (OSError, ValueError, wiki.WikiError):
        return None
    if not (
        candidate.is_dir()
        and (candidate / ".wiki").is_dir()
        and (candidate / "index.md").is_file()
    ):
        return None
    return candidate


def _runtime_path() -> Path:
    """Operational-only Codex capability/notice state, never legal content."""
    return wiki.user_registry_path().parent / "runtime.json"


def _load_runtime(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def _mark_capability_and_take_notice() -> bool:
    """Record that a Codex hook ran and atomically consume the one-time notice."""
    path = _runtime_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name("runtime.lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return False
    try:
        os.close(fd)
        data = _load_runtime(path)
        lifecycle = data.get("codex_lifecycle")
        if not isinstance(lifecycle, dict):
            lifecycle = {}
        show_notice = not bool(lifecycle.get("automation_notice_shown"))
        lifecycle.update(
            {
                "last_seen_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "automation_notice_shown": True,
            }
        )
        data["schema_version"] = RUNTIME_SCHEMA_VERSION
        data["codex_lifecycle"] = lifecycle
        wiki.atomic_write_text(
            path, json.dumps(data, indent=1, ensure_ascii=False) + "\n"
        )
        return show_notice
    except (OSError, UnicodeDecodeError):
        # The notice is intentionally best-effort. A read-only home must not
        # make a lifecycle hook fail or repeatedly announce itself.
        return False
    finally:
        lock.unlink(missing_ok=True)


def session_start(payload: dict) -> int:
    # A successful hook invocation is the capability proof. Do not expose an
    # automation journey before the user has a real, registered wiki.
    del payload
    if _default_wiki() is None:
        return 0
    if _mark_capability_and_take_notice():
        print(AUTOMATION_NOTICE)
    return 0


def prompt_submit(payload: dict) -> int:
    target = _default_wiki()
    if target is None:
        return 0
    # Do not access the prompt when automatic retrieval is disabled. The host
    # may have supplied it in stdin, but this adapter neither uses nor logs it.
    if not _confirmed_automation_enabled(
        "retrieval"
    ) or not wiki.automation_scope_allows(payload.get("cwd")):
        return 0
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        return 0
    args = argparse.Namespace(
        wiki=str(target),
        state=None,
        wiki_name=None,
        # The hook has already checked the confirmed automatic setting. This
        # value keeps the retrieval engine from coupling automatic activation
        # to the former generic `retrieval: on` preference.
        playbook=None,
        automatic=True,
        query=prompt,
        limit=3,
        deadline_ms=800,
        today=None,
        json=False,
        quiet=True,
    )
    try:
        import wiki_retrieval

        wiki_retrieval.cmd_retrieve(args)
    except (AttributeError, ImportError, OSError, ValueError, wiki.WikiError):
        return 0
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="wiki_hook.py")
    parser.add_argument("event", choices=("session-start", "prompt-submit"))
    args = parser.parse_args(argv[1:])
    payload = read_input()
    if args.event == "session-start":
        return session_start(payload)
    return prompt_submit(payload)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
