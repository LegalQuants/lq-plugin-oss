"""CLI and metadata discovery for the confirmed-selection session reader."""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path


def project_matches(reader, raw, project):
    # Local metadata check only. Never return raw first-line text to the model.
    for line in raw.split(b"\n", 4)[:4]:
        if len(line) > reader.MAX_LINE:
            continue
        try:
            event = json.loads(line)
            meta = (
                event.get("payload", {})
                if event.get("type") == "session_meta"
                else event
            )
            cwd = meta.get("cwd")
            if isinstance(cwd, str) and Path(cwd).expanduser().resolve().is_relative_to(
                project
            ):
                return True
        except (ValueError, AttributeError, TypeError):
            continue
    return False


def run(reader):
    parser = argparse.ArgumentParser(description=reader.__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--list", action="store_true")
    modes.add_argument("--read", action="store_true")
    modes.add_argument(
        "--session",
        help="Legacy exact-name read; still requires a confirmed selection manifest.",
    )
    parser.add_argument("--store", action="append", default=[], type=Path)
    parser.add_argument("--file", action="append", default=[], type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--confirmed", action="store_true")
    parser.add_argument("--excerpt-file", action="store_true")
    parser.add_argument(
        "--lines",
        nargs=2,
        type=int,
        metavar=("START", "END"),
        help="retrieve complete messages from an inclusive range in one transcript",
    )
    parser.add_argument("--window", default="7d")
    parser.add_argument("--since")
    args = parser.parse_args()
    try:
        if args.lines is not None and (args.list or args.excerpt_file):
            raise ValueError(
                "--lines requires a confirmed transcript read, not a list or excerpt."
            )
        if args.list:
            if not args.file and not args.store:
                raise ValueError(
                    "Choose explicit files or a project/session folder. No automatic "
                    "home-wide scan."
                )
            if args.store and not args.project:
                raise ValueError(
                    "Folder discovery requires --project. Alternatively select exact "
                    "--file paths."
                )
            if args.manifest.exists():
                raise ValueError(
                    "Selection manifest already exists; use a fresh filename."
                )
            paths = list(args.file)
            if args.store:
                if not re.fullmatch(r"[1-9][0-9]{0,3}d", args.window):
                    raise ValueError(
                        "window must be a positive number of days, for example 7d."
                    )
                cutoff = (
                    dt.datetime.fromisoformat(args.since)
                    .replace(tzinfo=dt.UTC)
                    .timestamp()
                    if args.since
                    else dt.datetime.now(dt.UTC).timestamp()
                    - int(args.window[:-1]) * 86400
                )
                project = args.project.expanduser().resolve()
                for folder in args.store:
                    for path in sorted(folder.expanduser().rglob("*.jsonl")):
                        if reader.excluded(path, args.exclude):
                            continue
                        # mtime, not filename date: resumed sessions stay visible.
                        if path.stat().st_mtime < cutoff:
                            continue
                        record, raw = reader.snapshot(path)
                        if project_matches(reader, raw, project):
                            paths.append(path)
                        if len(paths) > reader.MAX_FILES:
                            raise ValueError(
                                "Too many matches. Narrow the project or time window."
                            )
            result = reader.selection(paths, args.exclude)
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            reader.atomic_json(args.manifest, result)
        else:
            if not args.confirmed:
                raise ValueError(
                    "Show the scope and obtain consent before --read --confirmed."
                )
            if args.store or args.file or args.project:
                raise ValueError(
                    "Read only the approved manifest; file discovery cannot be mixed "
                    "with reading."
                )
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            if args.session:
                matches = [
                    r for r in manifest["files"] if Path(r["path"]).name == args.session
                ]
                if len(matches) != 1:
                    raise ValueError(
                        "Exact session name is absent or ambiguous in the approved "
                        "manifest."
                    )
                manifest["files"] = matches
            result = reader.summarise(
                reader.read_selection(manifest, args.exclude),
                args.excerpt_file,
                args.lines,
            )
        sys.stdout.buffer.write(
            (json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8")
        )
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(
            json.dumps({"error": str(error), "transcript_returned": False}),
            file=sys.stderr,
        )
        return 2
    return 0
