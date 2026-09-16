"""Opt-in local stage journal. One supervisor writes; workers return measurements."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STAGES = {
    "retrieval",
    "intake",
    "orchestration",
    "discovery",
    "semantic",
    "reference",
    "occurrence",
    "finalization",
}
TOKENS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
STATUSES = {"completed", "failed", "cancelled"}


def timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        raise ValueError("timestamp must be an ISO 8601 datetime with timezone")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def usage(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {
        *TOKENS,
        "provenance",
        "request_id",
    }:
        raise ValueError("invalid usage fields")
    for name in TOKENS:
        count = value.get(name)
        if count is not None and (type(count) is not int or count < 0):
            raise ValueError(f"{name} must be a nonnegative integer or null")
    if any(value.get(name) is not None for name in TOKENS) and not value.get(
        "provenance"
    ):
        raise ValueError("provider-reported counters require provenance")
    for name in ("provenance", "request_id"):
        if name in value and (
            not isinstance(value[name], str) or not value[name].strip()
        ):
            raise ValueError(f"{name} must be a nonempty string")
    for subset, total in ((TOKENS[1], TOKENS[0]), (TOKENS[3], TOKENS[2])):
        if (
            value.get(subset) is not None
            and value.get(total) is not None
            and value[subset] > value[total]
        ):
            raise ValueError(f"{subset} exceeds {total}")
    return {
        **{name: value.get(name) for name in TOKENS},
        **{k: v for k, v in value.items() if k not in TOKENS},
    }


def payloads(paths: list[str]) -> dict[str, Any]:
    records = []
    total_characters = 0
    for path in paths:
        raw = Path(path).read_bytes()
        chars = len(raw.decode("utf-8-sig"))
        total_characters += chars
        records.append(
            {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "characters": chars,
                "utf8_bytes": len(raw),
            }
        )
    return {
        "files": records,
        "estimated_tokens": math.ceil(total_characters / 4),
        "estimate_method": "ceil(utf8_text_characters / 4); payload only, not billed tokens",
    }


def validate(
    events: list[dict[str, Any]], source_hash: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    stages: dict[str, Any] = {}
    attempts: dict[str, Any] = {}
    requests: set[str] = set()
    for event in events:
        if event.get("source_sha256") != source_hash or not re.fullmatch(
            r"[0-9a-f]{64}", source_hash
        ):
            raise ValueError("source hash mismatch")
        if event.get("schema_version") != "1.0.0":
            raise ValueError("unsupported journal schema")
        when = timestamp(event["at"])
        kind = event["event"]
        if kind == "stage-start":
            key = event["stage_id"]
            if not key or key in stages or event["stage"] not in STAGES:
                raise ValueError("invalid or duplicate stage")
            stages[key] = {"start": event, "end": None}
        elif kind == "stage-end":
            stage = stages.get(event["stage_id"])
            if not stage or stage["end"] or event["status"] not in STATUSES:
                raise ValueError("invalid or duplicate stage end")
            if any(
                a["start"]["stage_id"] == event["stage_id"] and not a["end"]
                for a in attempts.values()
            ):
                raise ValueError("stage has open attempts")
            stage["end"] = event
            if when < timestamp(stage["start"]["at"]):
                raise ValueError("stage ends before start")
            if any(
                a["start"]["stage_id"] == event["stage_id"]
                and when < timestamp(a["end"]["at"])
                for a in attempts.values()
            ):
                raise ValueError("stage ends before attempt")
        elif kind == "attempt-start":
            key = event["attempt_id"]
            stage = stages.get(event["stage_id"])
            if (
                not key
                or key in attempts
                or not stage
                or stage["end"]
                or not event["packet_id"]
            ):
                raise ValueError("invalid or duplicate attempt")
            if when < timestamp(stage["start"]["at"]):
                raise ValueError("attempt starts before stage")
            prior = [
                a
                for a in attempts.values()
                if (a["start"]["stage_id"], a["start"]["packet_id"])
                == (event["stage_id"], event["packet_id"])
            ]
            if prior:
                previous = prior[-1]
                if (
                    event.get("retry_of") != previous["start"]["attempt_id"]
                    or not previous["end"]
                    or when < timestamp(previous["end"]["at"])
                ):
                    raise ValueError("retry requires preceding ended attempt")
            elif event.get("retry_of"):
                raise ValueError("retry predecessor missing")
            attempts[key] = {"start": event, "end": None}
        elif kind == "attempt-end":
            attempt = attempts.get(event["attempt_id"])
            if not attempt or attempt["end"] or event["status"] not in STATUSES:
                raise ValueError("invalid or duplicate attempt end")
            if when < timestamp(attempt["start"]["at"]):
                raise ValueError("attempt ends before start")
            measured = usage(event.get("usage", {}))
            request = measured.get("request_id")
            if request and request in requests:
                raise ValueError("provider request_id already counted")
            if request:
                requests.add(request)
            attempt["end"] = event
        else:
            raise ValueError("unknown event")
    return stages, attempts


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def append(path: Path, source_hash: str, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    # Exclusive creation fails closed if another supervisor is writing. A stale
    # lock requires explicit inspection/removal; never steal it automatically.
    lock_handle = lock.open("x", encoding="utf-8")
    try:
        with lock_handle:
            events = read_events(path)
            event = {"schema_version": "1.0.0", "source_sha256": source_hash, **event}
            validate([*events, event], source_hash)
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    finally:
        lock.unlink()


def union_seconds(intervals: list[tuple[datetime, datetime]]) -> float:
    total = 0.0
    stop = None
    for start, end in sorted(intervals):
        total += max(0.0, (end - max(start, stop or start)).total_seconds())
        stop = max(end, stop or end)
    return total


def summarize(events: list[dict[str, Any]], source_hash: str) -> dict[str, Any]:
    stages, attempts = validate(events, source_hash)
    rows = []
    for key, stage in stages.items():
        selected = [a for a in attempts.values() if a["start"]["stage_id"] == key]
        ended = [a for a in selected if a["end"]]
        intervals = [
            (timestamp(a["start"]["at"]), timestamp(a["end"]["at"])) for a in ended
        ]
        counters: dict[str, Any] = {}
        for name in TOKENS:
            values = [a["end"].get("usage", {}).get(name) for a in ended]
            known = [v for v in values if v is not None]
            counters[name] = {
                "value": sum(known) if known else None,
                "status": "complete"
                if selected and len(known) == len(selected)
                else "partial"
                if known
                else "unavailable",
                "reported_attempts": len(known),
            }
        complete = all(
            counters[n]["status"] == "complete" for n in (TOKENS[0], TOKENS[2])
        )
        token_status = (
            "complete"
            if complete
            else "partial"
            if any(c["value"] is not None for c in counters.values())
            else "unavailable"
        )
        estimates = {}
        for direction, boundary in (
            ("input_tokens", "start"),
            ("output_tokens", "end"),
        ):
            known = [
                a[boundary]["payload"]["estimated_tokens"]
                for a in selected
                if a[boundary] and "payload" in a[boundary]
            ]
            estimates[direction] = {
                "value": sum(known) if known else None,
                "status": "complete"
                if selected and len(known) == len(selected)
                else "partial"
                if known
                else "unavailable",
                "reported_attempts": len(known),
            }
        rows.append(
            {
                "stage_id": key,
                "stage": stage["start"]["stage"],
                "status": stage["end"]["status"] if stage["end"] else "open",
                "wall_seconds": (
                    timestamp(stage["end"]["at"]) - timestamp(stage["start"]["at"])
                ).total_seconds()
                if stage["end"]
                else None,
                "summed_attempt_seconds": sum(
                    (end - start).total_seconds() for start, end in intervals
                ),
                "active_attempt_wall_seconds": union_seconds(intervals),
                "attempts": len(selected),
                "open_attempts": len(selected) - len(ended),
                "retries": sum(bool(a["start"].get("retry_of")) for a in selected),
                "failed_attempts": sum(a["end"]["status"] == "failed" for a in ended),
                "actual_tokens": {
                    "status": token_status,
                    **counters,
                    "total_tokens": counters[TOKENS[0]]["value"]
                    + counters[TOKENS[2]]["value"]
                    if complete
                    else None,
                },
                "payload_estimates": estimates,
            }
        )
    times = [timestamp(e["at"]) for e in events]
    return {
        "schema_version": "1.0.0",
        "source_sha256": source_hash,
        "status": "complete"
        if rows and all(r["status"] != "open" for r in rows)
        else "incomplete",
        "observed_run_span_seconds": (max(times) - min(times)).total_seconds()
        if times
        else None,
        "stages": rows,
        "notes": [
            "Complete means the telemetry intervals are closed, not that the legal review passed.",
            "UTC wall clock; clock corrections can affect durations. Open intervals have no final duration.",
            "Stages may overlap: do not sum stage wall times. Attempt sums include retries and parallel work.",
            "Input tokens include cached tokens; output tokens include reasoning tokens. Subsets are never added again.",
            "Partial counter values sum reported attempts only. Payload estimates exclude context, tools, hidden reasoning and caching; they are not provider usage.",
        ],
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Review telemetry",
        "",
        f"Status: {report['status']}. Observed run span: {report['observed_run_span_seconds']} seconds.",
        "",
        "| Stage ID | Stage | Status | Wall seconds | Attempt seconds | Attempts / retries | Actual input / output | Usage status | Estimated payload input / output (coverage) |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in report["stages"]:
        actual = row["actual_tokens"]
        estimates = row["payload_estimates"]
        estimate_text = " / ".join(
            f"{v['value']} ({v['status']})" for v in estimates.values()
        )
        lines.append(
            f"| {row['stage_id']} | {row['stage']} | {row['status']} | {row['wall_seconds']} | {row['summed_attempt_seconds']} | {row['attempts']} / {row['retries']} | {actual['input_tokens']['value']} / {actual['output_tokens']['value']} | {actual['status']} | {estimate_text} |"
        )
    return "\n".join([*lines, "", *report["notes"], ""])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in (
        "stage-start",
        "stage-end",
        "attempt-start",
        "attempt-end",
        "summarize",
    ):
        sub = commands.add_parser(command)
        if command == "summarize":
            sub.add_argument("--json-output", required=True, type=Path)
            sub.add_argument("--markdown-output", required=True, type=Path)
            continue
        sub.add_argument("--at", default=None)
        if command != "attempt-end":
            sub.add_argument("--stage-id", required=True)
        if command == "stage-start":
            sub.add_argument("--stage", required=True, choices=sorted(STAGES))
        if command.startswith("attempt"):
            sub.add_argument("--attempt-id", required=True)
            sub.add_argument("--payload", action="append", default=[])
        if command == "attempt-start":
            sub.add_argument("--packet-id", required=True)
            sub.add_argument("--retry-of")
        if command.endswith("end"):
            sub.add_argument("--status", required=True, choices=sorted(STATUSES))
        if command == "attempt-end":
            sub.add_argument("--usage-json", type=Path)
    args = parser.parse_args()
    try:
        source_hash = hashlib.sha256(args.source.read_bytes()).hexdigest()
        if args.command == "summarize":
            if args.json_output.resolve() in {
                args.source.resolve(),
                args.journal.resolve(),
            } or args.markdown_output.resolve() in {
                args.source.resolve(),
                args.journal.resolve(),
                args.json_output.resolve(),
            }:
                raise ValueError(
                    "summary outputs must be distinct from source and journal"
                )
            report = summarize(read_events(args.journal), source_hash)
            if args.json_output.exists() or args.markdown_output.exists():
                raise FileExistsError("summary outputs already exist; use fresh paths")
            args.json_output.write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            args.markdown_output.write_text(markdown(report), encoding="utf-8")
        else:
            if args.journal.resolve() == args.source.resolve():
                raise ValueError("journal must be distinct from source")
            event = {
                k: v
                for k, v in vars(args).items()
                if k
                not in {"journal", "source", "command", "payload", "usage_json", "at"}
                and v is not None
            }
            event.update(
                event=args.command, at=args.at or datetime.now(UTC).isoformat()
            )
            if getattr(args, "payload", []):
                event["payload"] = payloads(args.payload)
            if getattr(args, "usage_json", None):
                event["usage"] = usage(
                    json.loads(args.usage_json.read_text(encoding="utf-8"))
                )
            append(args.journal, source_hash, event)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"telemetry error: {exc}\n")


if __name__ == "__main__":
    main()
