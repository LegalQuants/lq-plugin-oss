#!/usr/bin/env python3
"""profile_store — every write to ~/.lq/ goes through here, one invocation per verb.

Commands:
  open       create a minimal store with the quoting posture ({"quoting": "A|B|C"})
  init       create the store from baseline answers (JSON on stdin or --file)
  save       the one door every companion skill uses: create-if-missing, then
             append; idempotent on operation_id; requires --confirmed (the caller
             showed the exact content and got an explicit yes — the flag records
             that decision, it does not authenticate it)
  rebaseline append a new fluency reading to the level history
  append     append journey events to an EXISTING store (JSON on stdin or --file);
             updates the scan watermark when a debrief_run event carries files_read
  render     regenerate lqprofile.md (counters computed from the journey, never stored)
  status     one-line profile summary + counters (the check-in's data); on a fresh
             root answers {"exists": false} — never a traceback
  export     write a full copy of the store to --out
  forget     --entry <id> removes one journey event; --all removes the store's
             own files only (requires --confirm; offer export first — the caller
             shows, this executes). Anything else in the directory survives.

Disciplines: atomic writes (tmp+rename); a lockfile makes concurrent mutations refuse
politely; append-only journey with sequential ids; state never duplicates what the
journey can recompute. Stdlib only. --root overrides ~/.lq for tests.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import sys
from typing import Any

EVENT_TYPES = {
    "lq_moment",
    "friction",
    "technique",
    "repetition",
    "debrief_run",
    "office_hours_run",
}
SOURCES = {"user", "debrief", "office-hours", "baseline"}
QUOTING = {"A", "B", "C"}


def now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


MARKER = ".lq-store"  # written at init; forget --all refuses any root lacking it


def root_of(args) -> pathlib.Path:
    return pathlib.Path(args.root) if args.root else pathlib.Path.home() / ".lq"


def require_store(root: pathlib.Path) -> None:
    """Guard destructive ops: the root must be a real lq store, never $HOME or /."""
    rp = root.resolve()
    if rp == pathlib.Path.home().resolve() or rp == rp.anchor or rp.parent == rp:
        sys.exit(f"refusing: {rp} is not an lq store (home/root guard).")
    if not (root / MARKER).exists() or not (root / "profile.json").exists():
        sys.exit(f"refusing: {rp} has no {MARKER}/profile.json — not an lq store.")


def atomic_write(path: pathlib.Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(text)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    # os.replace, not Path.rename: on Windows rename refuses an existing target,
    # so every second write of the store or marker failed there.
    os.replace(tmp, path)


class Lock:
    def __init__(self, root: pathlib.Path):
        self.path = root / ".lock"

    def __enter__(self):
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
        except FileExistsError:
            sys.exit(
                "another profile-store operation is running (lockfile held). "
                "If that is wrong, "
                f"remove {self.path} and retry."
            )
        return self

    def __exit__(self, *_):
        self.path.unlink(missing_ok=True)


def read_payload(args):
    raw = pathlib.Path(args.file).read_text() if args.file else sys.stdin.read()
    return json.loads(raw)


def load_json(path: pathlib.Path):
    return json.loads(path.read_text())


def load_profile(root: pathlib.Path, verb: str):
    """profile.json with a clean refusal, never a traceback, when it is damaged."""
    try:
        return load_json(root / "profile.json")
    except (json.JSONDecodeError, ValueError):
        sys.exit(
            f"{verb} refused: profile.json is unreadable. Repair or export the "
            "store first — nothing was changed."
        )


def store_exists(root: pathlib.Path) -> bool:
    return (root / MARKER).exists() and (root / "profile.json").exists()


def refuse_no_store(root: pathlib.Path, verb: str) -> None:
    """Clean refusal, never a traceback: a missing store is a normal state."""
    if not store_exists(root):
        sys.exit(
            f"{verb} refused: no lq store at {root}. Create one with save "
            "(create-if-missing) or open first — see references/store-contract.md."
        )


def journey_events(root: pathlib.Path, *, strict: bool = False):
    """Read the journey. A malformed line is never silently discarded: writers
    (strict) refuse and preserve everything; readers skip it and say so."""
    jf = root / "journey.jsonl"
    if not jf.exists():
        return []
    events = []
    bad = []
    for n, line in enumerate(jf.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            if strict:
                sys.exit(
                    f"write refused: journey.jsonl line {n} is unreadable. Repair "
                    "or export the store first — nothing was changed."
                )
            bad.append(n)
            continue
        if isinstance(e, dict):
            events.append(e)
    if bad:
        print(
            f"warning: journey.jsonl has {len(bad)} unreadable line(s) — "
            "skipped, never deleted. Repair the store.",
            file=sys.stderr,
        )
    return events


def next_seq(events) -> int:
    """Monotonic id: max existing j-NNNN + 1, never len (survives forget --entry)."""
    hi = 0
    for e in events:
        m = re.match(r"j-(\d+)$", str(e.get("id", "")))
        if m:
            hi = max(hi, int(m.group(1)))
    return hi


# shape-never-substance backstop: reject events whose free-text fields look like
# they carry client substance (long digit runs = account/matter numbers; several
# capitalised multi-word proper nouns = party names). Coarse on purpose — the model
# is the primary guard; this is the mechanical floor so the promise is never only prose.
_DIGIT_RUN = re.compile(r"\d{6,}")
_PROPER = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,})\b")
_TEXT_FIELDS = ("what", "lesson", "signature", "scaffold", "technique", "opener")


def _string_risk(where: str, v: str) -> str | None:
    if _DIGIT_RUN.search(v):
        return f"{where} contains a long digit run (account/matter number?)"
    if len(_PROPER.findall(v)) >= 2:
        return f"{where} contains multiple proper-noun phrases (party names?)"
    return None


def substance_risk(event) -> str | None:
    """Best-effort shape-never-substance net over an event's known text fields."""
    for k in _TEXT_FIELDS:
        v = event.get(k)
        if isinstance(v, str):
            r = _string_risk(repr(k), v)
            if r:
                return r
    return None


def payload_risk(obj, path="") -> str | None:
    """Best-effort net over every string in a baseline/rebaseline payload."""
    if isinstance(obj, str):
        return _string_risk(path or "value", obj)
    if isinstance(obj, dict):
        for k, v in obj.items():
            r = payload_risk(v, f"{path}.{k}" if path else str(k))
            if r:
                return r
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            r = payload_risk(v, f"{path}[{i}]")
            if r:
                return r
    return None


def counters(events):
    c = {
        "lq_moments": 0,
        "lessons_kept": 0,
        "lessons_graduated": 0,
        "debriefs": 0,
        "office_hours": 0,
    }
    grad_lessons = {
        e.get("lesson")
        for e in events
        if e.get("type") == "friction" and e.get("status") == "graduated"
    }
    for e in events:
        t = e.get("type")
        if t == "lq_moment":
            c["lq_moments"] += 1
        elif t == "friction":
            if e.get("status") == "graduated":
                c["lessons_graduated"] += 1
            elif e.get("lesson") not in grad_lessons:
                c["lessons_kept"] += 1  # a later graduation supersedes this lesson
        elif t == "debrief_run":
            c["debriefs"] += 1
        elif t == "office_hours_run":
            c["office_hours"] += 1
    return c


def _create_store(root: pathlib.Path, quoting: str) -> None:
    """The file writes of store creation. Caller holds the Lock."""
    prof = {
        "practice": {"sentence": "A lawyer"},
        "preferences": {"quoting": quoting},
        "fluency": {},
    }
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    (root / MARKER).write_text("lq profile store\n")
    atomic_write(root / "profile.json", json.dumps(prof, indent=1))
    atomic_write(root / "scan_state.json", json.dumps({"scanned": []}, indent=1))
    atomic_write(root / "state.json", json.dumps({"markers": {}, "proactive": True}))
    (root / "journey.jsonl").touch()


def cmd_open(args):
    """Create a minimal store: no baseline, no level. Just the quoting posture."""
    root = root_of(args)
    if (root / "profile.json").exists():
        sys.exit("~/.lq already exists — nothing to open.")
    payload = read_payload(args)
    quoting = payload.get("quoting")
    if quoting not in QUOTING:
        sys.exit('open payload needs {"quoting": "A|B|C"}')
    root.mkdir(parents=True, exist_ok=True)  # the lockfile needs the dir to exist
    with Lock(root):
        _create_store(root, quoting)
        render(root)
    print(f"opened {root} — quoting posture {quoting} remembered.")


def cmd_init(args):
    root = root_of(args)
    if (root / "profile.json").exists():
        sys.exit("~/.lq already exists — use rebaseline, or forget --all first.")
    payload = read_payload(args)
    for key in ("practice", "preferences", "fluency"):
        if key not in payload:
            sys.exit(f"init payload missing '{key}'")
    risk = payload_risk(payload)
    if risk:
        sys.exit(
            f"init refused (shape-never-substance): {risk}. The practice sentence "
            "should describe your practice, not name a client or matter."
        )
    payload["fluency"].setdefault("history", []).append(
        {
            "level": payload["fluency"].get("level"),
            "at": now(),
            "method": payload["fluency"].get("method", "baseline-self-placed"),
        }
    )
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)  # profile is the user's alone
    except OSError:
        pass
    with Lock(root):
        (root / MARKER).write_text("lq profile store\n")
        atomic_write(root / "profile.json", json.dumps(payload, indent=1))
        atomic_write(root / "scan_state.json", json.dumps({"scanned": []}, indent=1))
        atomic_write(
            root / "state.json", json.dumps({"markers": {}, "proactive": True})
        )
        (root / "journey.jsonl").touch()
        render(root)
    print(f"initialised {root} — profile born, trophy case empty and waiting.")


def cmd_rebaseline(args):
    root = root_of(args)
    refuse_no_store(root, "rebaseline")
    payload = read_payload(args)
    risk = payload_risk(payload)
    if risk:
        sys.exit(f"rebaseline refused (shape-never-substance): {risk}.")
    with Lock(root):
        prof = load_profile(root, "rebaseline")
        prof["fluency"]["level"] = payload["level"]
        if payload.get("archetype"):
            prof["fluency"]["archetype"] = payload["archetype"]
        prof["fluency"].setdefault("history", []).append(
            {
                "level": payload["level"],
                "at": now(),
                "method": payload.get("method", "rebaseline"),
            }
        )
        atomic_write(root / "profile.json", json.dumps(prof, indent=1))
        render(root)
    method = payload.get("method", "rebaseline")
    print(f"level history appended: {payload['level']} ({method})")


def _validate_events(events, verb: str):
    """The append/save payload gate: shape, known types/sources, no substance."""
    if isinstance(events, dict):
        events = [events]
    if not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
        sys.exit(f"{verb} refused: payload must be a JSON object or list of objects.")
    bad = [e for e in events if e.get("type") not in EVENT_TYPES]
    bad += [e for e in events if e.get("source") not in SOURCES]
    for e in events:
        fr = e.get("files_read")
        if fr is not None and (
            not isinstance(fr, list) or not all(isinstance(x, str) for x in fr)
        ):
            bad.append(e)
    if bad:
        sys.exit(f"{verb} refused: {len(bad)} invalid events. Nothing written.")
    for e in events:
        risk = substance_risk(e)
        if risk:
            sys.exit(
                f"{verb} refused (shape-never-substance): {risk}. "
                "Rewrite as matter-TYPE + technique, no names/numbers."
            )
    return events


def _append_events(root: pathlib.Path, events) -> None:
    """Seq-stamp, append, watermark, re-render. Caller holds the Lock."""
    seq = next_seq(journey_events(root, strict=True))
    lines = []
    for e in events:
        seq += 1
        e["id"] = f"j-{seq:04d}"
        e.setdefault("at", now())
        lines.append(json.dumps(e, ensure_ascii=False))
    if lines:
        with open(root / "journey.jsonl", "a") as f:
            f.write("\n".join(lines) + "\n")
    runs = [e for e in events if e.get("type") == "debrief_run" and e.get("files_read")]
    if runs:
        ss = load_json(root / "scan_state.json")
        known = {r["file"] for r in ss["scanned"]}
        for run in runs:
            for fname in run["files_read"]:
                if fname not in known:
                    ss["scanned"].append(
                        {"file": fname, "debrief": run["id"], "at": now()}
                    )
                    known.add(fname)
        atomic_write(root / "scan_state.json", json.dumps(ss, indent=1))
    render(root)


def cmd_append(args):
    root = root_of(args)
    events = _validate_events(read_payload(args), "append")
    refuse_no_store(root, "append")
    with Lock(root):
        _append_events(root, events)
    ids = ", ".join(e["id"] for e in events)
    print(f"appended {len(events)} events ({ids}) — profile updated.")


def cmd_save(args):
    """One door for every companion skill: create-if-missing, then append.

    Idempotent on operation_id: a retried save appends nothing twice — but the
    same operation_id carrying different content is a refused conflict, never a
    silent no-op.
    --confirmed records the caller's preview+consent decision; not proof of it.
    """
    root = root_of(args)
    if not args.confirmed:
        sys.exit(
            "save needs --confirmed: show the exact content first and continue "
            "only on an explicit yes. Silence is not consent."
        )
    payload = read_payload(args)
    if not isinstance(payload, dict):
        sys.exit("save refused: payload must be a JSON object.")
    events = _validate_events(payload.get("events", []), "save")
    op_id = payload.get("operation_id")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    creating = not store_exists(root)
    if creating and payload.get("quoting") not in QUOTING:
        sys.exit('save creating a store needs {"quoting": "A|B|C"}')
    root.mkdir(parents=True, exist_ok=True)  # the lockfile needs the dir to exist
    with Lock(root):
        if creating:
            _create_store(root, payload["quoting"])
        else:
            quoting = payload.get("quoting")
            current = load_profile(root, "save").get("preferences", {}).get("quoting")
            if quoting is not None and quoting != current:
                sys.exit(
                    f"save refused: quoting posture is already {current}. Confirm a "
                    "change with the user explicitly rather than overwriting it here."
                )
        if op_id:
            seen = [
                e
                for e in journey_events(root, strict=True)
                if e.get("operation_id") == op_id
            ]
            if seen:
                prior = next(
                    (e["operation_digest"] for e in seen if e.get("operation_digest")),
                    None,
                )
                if prior is not None and prior != digest:
                    sys.exit(
                        f"save refused: operation_id {op_id} was already used for "
                        "different content. Nothing changed."
                    )
                print(f"already saved (operation_id {op_id}) — nothing new appended.")
                return
            for e in events:
                e.setdefault("operation_id", op_id)
                e.setdefault("operation_digest", digest)
        _append_events(root, events)
    print(f"saved {len(events)} events — profile updated.")


def cmd_mark(args):
    """Write a state.json marker (bail flags, nudge ledger, proactive toggle)."""
    root = root_of(args)
    root.mkdir(parents=True, exist_ok=True)
    with Lock(root):
        sf = root / "state.json"
        st: dict[str, Any] = (
            load_json(sf) if sf.exists() else {"markers": {}, "proactive": True}
        )
        if args.key:
            st.setdefault("markers", {})[args.key] = args.value or True
        if args.proactive is not None:
            st["proactive"] = args.proactive == "on"
        atomic_write(root / "state.json", json.dumps(st, indent=1))
    print("state updated.")


def render(root: pathlib.Path) -> None:
    prof = load_profile(root, "render")
    events = journey_events(root)
    c = counters(events)
    fl = prof.get("fluency", {})
    moments = [e for e in events if e.get("type") == "lq_moment"][-5:]
    # graduation supersedes by lesson text: a friction that later graduated leaves
    # "in play" and appears only under Graduated (append-only store, no in-place edit).
    grad_lessons = {
        e.get("lesson")
        for e in events
        if e.get("type") == "friction" and e.get("status") == "graduated"
    }
    lessons = [
        e
        for e in events
        if e.get("type") == "friction"
        and e.get("status") != "graduated"
        and e.get("lesson") not in grad_lessons
    ][-5:]
    grads = [
        e
        for e in events
        if e.get("type") == "friction" and e.get("status") == "graduated"
    ][-3:]
    header = (
        f"**Level:** {fl['level']} · **archetype:** {fl.get('archetype', 'tbd')} · "
        if fl.get("level")
        else ""
    )
    lines = [
        f"# {prof.get('practice', {}).get('sentence', 'A lawyer')}",
        "",
        f"{header}**moments kept:** {c['lq_moments']} · **debriefs:** {c['debriefs']}",
        "",
        "## Moments kept" + ("" if moments else " (0) — your first debrief fills this"),
    ]
    for m in moments:
        tech, at = m.get("technique", "?"), m.get("at", "")[:10]
        lines.append(f"- {m.get('what', '?')} *({tech}, {at})*")
    lines.append("")
    lines.append("## Lessons in play" + ("" if lessons else " — none; clean sheet"))
    for e in lessons:
        lines.append(
            f"- {e.get('lesson', '?')} *(signature: {e.get('signature', '?')})*"
        )
    if grads:
        lines.append("")
        lines.append("## Graduated 🎓")
        for e in grads:
            lines.append(f"- {e.get('lesson', '?')}")
    if fl.get("history"):
        lines.append("")
        hist = " → ".join(f"{h['level']} ({h['at'][:10]})" for h in fl["history"])
        lines.append(f"*Level history: {hist}*")
    atomic_write(root / "lqprofile.md", "\n".join(lines) + "\n")


def cmd_render(args):
    root = root_of(args)
    refuse_no_store(root, "render")
    render(root)
    print("lqprofile.md rendered.")


def cmd_status(args):
    root = root_of(args)
    if not store_exists(root):
        print(json.dumps({"exists": False}))  # a fresh user is a normal answer
        return
    prof = load_profile(root, "status")
    cur = counters(journey_events(root))
    out = {"exists": True, "level": prof.get("fluency", {}).get("level"), **cur}
    if args.since:
        # The check-in's growth line. Diff current cumulative counters against the
        # snapshot stamped at the LAST check-in, then re-stamp — so "+2 LQ moments"
        # is a real delta, never a fabricated or cumulative number. One write.
        with Lock(root):
            sf = root / "state.json"
            st: dict[str, Any] = (
                load_json(sf) if sf.exists() else {"markers": {}, "proactive": True}
            )
            seen = st.get("markers", {}).get("last_seen")
            st.setdefault("markers", {})["last_seen"] = {**cur, "at": now()}
            atomic_write(sf, json.dumps(st, indent=1))
        if not isinstance(seen, dict):
            out["since_last"] = None  # first check-in: no prior snapshot to diff
        else:
            delta = {k: cur[k] - int(seen.get(k, 0)) for k in cur}
            out["since_last"] = {k: v for k, v in delta.items() if v}
            out["since_at"] = seen.get("at")
    print(json.dumps(out))


def cmd_export(args):
    root = root_of(args)
    refuse_no_store(root, "export")
    out = pathlib.Path(args.out)
    if out.exists():
        sys.exit(f"export refused: {out} already exists.")
    with Lock(root):
        shutil.copytree(root, out, ignore=shutil.ignore_patterns(".lock"))
    print(f"exported to {out}")


def cmd_forget(args):
    root = root_of(args)
    if args.all:
        if not args.confirm:
            sys.exit("forget --all needs --confirm (the caller shows what dies first).")
        require_store(root)  # never remove home/root or a non-store directory
        with Lock(root):
            # Only files this store owns; anything else the user keeps in the
            # directory survives, and the directory itself stays.
            for name in (
                MARKER,
                "profile.json",
                "journey.jsonl",
                "scan_state.json",
                "state.json",
                "lqprofile.md",
            ):
                p = root / name
                if p.is_symlink() or p.is_file():
                    p.unlink()
        print(f"{root} store files removed. The profile was yours; it is gone.")
        return
    if not args.entry:
        sys.exit("forget needs --entry <id> or --all")
    require_store(root)
    with Lock(root):
        events = journey_events(root, strict=True)
        kept = [e for e in events if e.get("id") != args.entry]
        if len(kept) == len(events):
            sys.exit(f"no journey entry {args.entry}")
        atomic_write(
            root / "journey.jsonl",
            "\n".join(json.dumps(e, ensure_ascii=False) for e in kept)
            + ("\n" if kept else ""),
        )
        render(root)
    print(f"forgot {args.entry}.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", help="override ~/.lq (tests)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("open", "init", "rebaseline", "append", "save"):
        s = sub.add_parser(name)
        s.add_argument("--file", help="JSON payload file (default: stdin)")
        if name == "save":
            s.add_argument(
                "--confirmed",
                action="store_true",
                help="caller has shown the exact content and obtained an explicit "
                "yes; this flag records that decision, it is not proof of it",
            )
    sub.add_parser("render")
    st = sub.add_parser("status")
    st.add_argument(
        "--since", action="store_true", help="add since-last-check-in delta; re-stamps"
    )
    mk = sub.add_parser("mark")
    mk.add_argument("--key")
    mk.add_argument("--value")
    mk.add_argument("--proactive", choices=["on", "off"])
    e = sub.add_parser("export")
    e.add_argument("--out", required=True)
    f = sub.add_parser("forget")
    f.add_argument("--entry")
    f.add_argument("--all", action="store_true")
    f.add_argument("--confirm", action="store_true")
    args = ap.parse_args()
    {
        "open": cmd_open,
        "init": cmd_init,
        "rebaseline": cmd_rebaseline,
        "append": cmd_append,
        "save": cmd_save,
        "mark": cmd_mark,
        "render": cmd_render,
        "status": cmd_status,
        "export": cmd_export,
        "forget": cmd_forget,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
