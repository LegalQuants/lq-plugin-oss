#!/usr/bin/env python3
"""Run one prepared stage through an explicitly configured local host adapter."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from _runtime_gate import require_supported_python

require_supported_python()

from definition_check.review_packets import ReviewPacketError
from definition_check.stage_runner import (
    adapter_packet,
    collected_packet_numbers,
    compact_stage_checkpoint,
    default_stage_concurrency,
    run_stage,
    summarize_worker_attempts,
)
from definition_check.response_publication import (
    publication_contract,
    atomic_create,
    dumps,
)
from definition_check.workspace import ensure_workspace


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument(
        "--stage",
        choices=["discovery", "semantic", "reference", "occurrence"],
        required=True,
    )
    parser.add_argument(
        "--adapter-command",
        required=True,
        help="JSON argv array; receives request JSON on stdin and returns response JSON on stdout",
    )
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--timeout-seconds", type=float, default=600)
    parser.add_argument("--named-responses", action="store_true")
    parser.add_argument(
        "--packets", help="Comma-separated packet numbers; omitted schedules all"
    )
    parser.add_argument(
        "--run-name", help="Fresh stage-runs directory name; defaults to the stage"
    )
    args = parser.parse_args()
    concurrency = (
        args.concurrency
        if args.concurrency is not None
        else default_stage_concurrency(args.stage)
    )
    command = json.loads(args.adapter_command)
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(x, str) or not x for x in command)
    ):
        parser.error("adapter-command must be a non-empty JSON string array")
    if args.timeout_seconds <= 0:
        parser.error("timeout-seconds must be positive")
    root = ensure_workspace(args.work_dir.resolve())[0]
    manifest = json.loads(
        (root / "private" / f"{args.stage}-manifest.json").read_text(encoding="utf-8")
    )
    selected = (
        {int(value) for value in args.packets.split(",")}
        if args.packets
        else {packet["packet"] for packet in manifest["packets"]}
    )
    if not selected <= {packet["packet"] for packet in manifest["packets"]}:
        parser.error("selected packet is absent from the stage manifest")
    scheduling_manifest = {
        **manifest,
        "packets": [
            packet for packet in manifest["packets"] if packet["packet"] in selected
        ],
    }
    run_name = args.run_name or args.stage
    if not run_name or Path(run_name).name != run_name or run_name in {".", ".."}:
        parser.error("run-name must be one directory name")
    # A fresh directory prevents accidental replay or overwrite of prior evidence.
    destination = root / "stage-runs" / run_name
    destination.mkdir(parents=True, exist_ok=False)
    validation_path = destination / "validation-manifest.json"
    validation_path.write_text(
        json.dumps(manifest, ensure_ascii=True), encoding="utf-8"
    )
    atomic_create(
        destination / "run-metadata.json",
        dumps(
            {
                "stage": args.stage,
                "concurrency": concurrency,
                "selected_packets": sorted(selected),
                "validation_manifest": str(
                    root / "private" / f"{args.stage}-manifest.json"
                ),
            }
        ),
    )
    journal = destination / "events.jsonl"
    checkpoint = destination / "checkpoint.json"
    attempts_seen: dict[int, int] = {}

    def event(value: dict) -> None:
        packet = value.get("packet")
        attempt = value.get("attempt")
        if isinstance(packet, int) and isinstance(attempt, int):
            attempts_seen[packet] = max(attempts_seen.get(packet, 0), attempt)
        with journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=True) + "\n")

    async def dispatch(packet: int, attempt: int, correction: dict | None) -> object:
        payload = json.loads(
            (root / "packets" / args.stage / f"packet-{packet:03d}.json").read_text(
                encoding="utf-8"
            )
        )
        if args.named_responses:
            payload = adapter_packet(payload)
        request = {
            "packet": payload,
            "attempt": attempt,
            "correction": correction,
            "publication_contract": publication_contract(
                destination / "validation-manifest.json",
                packet,
                args.stage,
                args.timeout_seconds,
            ),
        }
        prefix = destination / f"packet-{packet:03d}-attempt-{attempt}"
        prefix.with_suffix(".request.json").write_text(
            json.dumps(request, ensure_ascii=True), encoding="utf-8"
        )
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                **os.environ,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            },
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(
                    json.dumps(request, ensure_ascii=True).encode("ascii")
                ),
                timeout=args.timeout_seconds,
            )
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.communicate()
            raise
        prefix.with_suffix(".stdout").write_bytes(stdout)
        prefix.with_suffix(".stderr").write_bytes(stderr)
        if process.returncode:
            raise ReviewPacketError(
                f"adapter failed for packet {packet}; see retained stderr"
            )
        try:
            return json.loads(stdout)
        except (ValueError, UnicodeError) as exc:
            raise ReviewPacketError(
                f"adapter returned invalid JSON for packet {packet}"
            ) from exc

    def collect(packet: int, response: dict) -> None:
        atomic_create(destination / f"packet-{packet:03d}.json", dumps(response))

    stage_started = time.perf_counter()
    try:
        result = await run_stage(
            scheduling_manifest,
            dispatch,
            collect,
            event,
            concurrency=concurrency,
            validation_manifest=manifest,
        )
    except ReviewPacketError:
        completed = collected_packet_numbers(destination)
        atomic_create(
            checkpoint,
            dumps(
                compact_stage_checkpoint(
                    manifest,
                    completed_packets=completed,
                    failed_packets=selected - completed,
                    attempts=attempts_seen,
                    status="failed",
                )
            ),
        )
        raise
    atomic_create(
        checkpoint,
        dumps(
            compact_stage_checkpoint(
                manifest,
                completed_packets=set(result),
                attempts=attempts_seen,
                status="packet_validation_complete",
            )
        ),
    )
    status = (
        "packet_validation_complete"
        if len(selected) == len(manifest["packets"])
        else "selected_packet_validation_complete"
    )
    summary = {
        "status": status,
        "stage": args.stage,
        "selected_packets": sorted(selected),
        "concurrency": concurrency,
        "packets": len(result),
        "output": str(destination),
        "stage_wall_seconds": time.perf_counter() - stage_started,
        "worker_telemetry": summarize_worker_attempts(destination),
        "next": "Expand all responses and run stage-wide validation before advancing.",
    }
    atomic_create(destination / "stage-result.json", dumps(summary))
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
