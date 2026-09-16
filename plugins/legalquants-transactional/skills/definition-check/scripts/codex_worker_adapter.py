#!/usr/bin/env python3
"""Run one Definition Check packet in a fresh, isolated Codex CLI session."""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from _runtime_gate import require_supported_python

require_supported_python()

from definition_check.response_publication import atomic_create, dumps, marked_root

REQUIRED_MODEL = "gpt-5.6-luna"
REQUIRED_EFFORT = "medium"
STAGES = {"discovery", "semantic", "reference", "occurrence"}
REQUEST_FIELDS = {"packet", "attempt", "correction", "publication_contract"}


class AdapterError(RuntimeError):
    """A worker attempt could not be trusted or completed."""


def positive_seconds(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return number


def argv_array(value: str) -> list[str]:
    try:
        command = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError("must be a JSON argv array") from exc
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(item, str) or not item for item in command)
    ):
        raise argparse.ArgumentTypeError("must be a non-empty JSON string array")
    return command


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def read_request(raw: bytes) -> tuple[dict[str, Any], Path]:
    try:
        request = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AdapterError("request is not valid UTF-8 JSON") from exc
    if not isinstance(request, dict) or set(request) != REQUEST_FIELDS:
        raise AdapterError("request has an unexpected shape")
    packet = request.get("packet")
    attempt = request.get("attempt")
    correction = request.get("correction")
    contract = request.get("publication_contract")
    if not isinstance(packet, dict) or not isinstance(contract, dict):
        raise AdapterError("request packet or publication contract is malformed")
    stage = packet.get("stage")
    number = packet.get("packet")
    if stage not in STAGES:
        raise AdapterError("request has an unsupported stage")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in (number, attempt)
    ):
        raise AdapterError("packet and attempt must be positive integers")
    if correction is not None and not isinstance(correction, dict):
        raise AdapterError("correction must be an object or null")
    if contract.get("stage") != stage or contract.get("packet") != number:
        raise AdapterError("publication contract does not match the packet")
    manifest_value = contract.get("manifest")
    workspace_value = contract.get("workspace")
    if not isinstance(manifest_value, str) or not isinstance(workspace_value, str):
        raise AdapterError("publication contract paths are malformed")
    manifest = Path(manifest_value).resolve()
    workspace = Path(workspace_value).resolve()
    if marked_root(manifest) != workspace:
        raise AdapterError("publication manifest is outside its marked workspace")
    evidence_root = manifest.parent / "workers"
    if not manifest.parent.resolve().is_relative_to(workspace):
        raise AdapterError("worker evidence directory escapes the marked workspace")
    evidence = evidence_root / stage / f"packet-{number:03d}-attempt-{attempt}"
    return request, evidence


def worker_input(request: dict[str, Any]) -> dict[str, Any]:
    """Return the complete and deliberately narrow worker-visible payload."""
    return {
        "packet": request["packet"],
        "correction": request["correction"],
    }


def parse_events(raw: bytes) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    events: list[dict[str, Any]] = []
    totals = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
    }
    completed_turns = 0
    actual_models: set[str] = set()
    actual_efforts: set[str] = set()
    turn_started_at: str | None = None
    turn_completed_at: str | None = None
    for line in raw.splitlines():
        try:
            value = json.loads(line)
        except (UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        events.append(value)
        event_type = value.get("type")
        if isinstance(event_type, str) and not event_type.startswith("item."):
            model = value.get("actual_model", value.get("model"))
            effort = value.get(
                "actual_effort",
                value.get("reasoning_effort", value.get("effort")),
            )
            if isinstance(model, str) and model:
                actual_models.add(model)
            if isinstance(effort, str) and effort:
                actual_efforts.add(effort)
            timestamp = value.get("timestamp")
            if isinstance(timestamp, str) and timestamp:
                if event_type == "turn.started" and turn_started_at is None:
                    turn_started_at = timestamp
                elif event_type == "turn.completed":
                    turn_completed_at = timestamp
        if event_type != "turn.completed" or not isinstance(value.get("usage"), dict):
            continue
        usage = value["usage"]
        parsed: dict[str, int] = {}
        for key in totals:
            count = usage.get(key, 0)
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                break
            parsed[key] = count
        else:
            completed_turns += 1
            for key, count in parsed.items():
                totals[key] += count
    usage_result: dict[str, int] | None = None
    if completed_turns:
        usage_result = {
            **totals,
            "model_calls": completed_turns,
            "total_tokens": totals["input_tokens"] + totals["output_tokens"],
        }
    return events, {
        "usage": usage_result,
        "usage_provenance": "codex_jsonl_turn.completed" if usage_result else None,
        "actual_models": sorted(actual_models),
        "actual_reasoning_efforts": sorted(actual_efforts),
        "provider_turn_started_at": turn_started_at,
        "provider_turn_completed_at": turn_completed_at,
    }


def verify_runtime(events: dict[str, Any], model: str, effort: str) -> None:
    models = events["actual_models"]
    efforts = events["actual_reasoning_efforts"]
    if models and models != [model]:
        raise AdapterError("Codex reported a different worker model")
    if efforts and efforts != [effort]:
        raise AdapterError("Codex reported a different reasoning effort")


def read_response(path: Path, events: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[object] = []
    if path.is_file():
        try:
            candidates.append(json.loads(path.read_bytes()))
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    for event in reversed(events):
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            continue
        text = item.get("text")
        if isinstance(text, str):
            try:
                candidates.append(json.loads(text))
            except json.JSONDecodeError:
                continue
    for candidate in candidates:
        if isinstance(candidate, dict):
            dumps(candidate)  # Reject NaN and other non-portable values.
            return candidate
    raise AdapterError("Codex did not return one JSON object")


def terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(  # noqa: S603 - exact argv, bounded process-tree cleanup
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()


def run_codex(
    request: dict[str, Any],
    evidence: Path,
    command_prefix: list[str],
    model: str,
    effort: str,
    timeout: float,
) -> dict[str, Any]:
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(exist_ok=False)
    prompt_value = worker_input(request)
    prompt = json.dumps(
        prompt_value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    )
    atomic_create(evidence / "worker-input.json", prompt.encode("utf-8"))
    adapter_started_at = utc_now()
    adapter_started_ns = time.perf_counter_ns()
    metadata: dict[str, Any] = {
        "schema": "definition-check-codex-attempt-v1",
        "stage": request["packet"]["stage"],
        "packet": request["packet"]["packet"],
        "attempt": request["attempt"],
        "adapter_pid": os.getpid(),
        "adapter_started_at": adapter_started_at,
        "adapter_started_monotonic_ns": adapter_started_ns,
        "requested_model": model,
        "requested_reasoning_effort": effort,
        "configuration_confirmation": "explicit_cli_arguments_with_strict_config",
        "status": "starting",
    }
    with tempfile.TemporaryDirectory(prefix="definition-check-codex-") as temporary:
        isolated_root = Path(temporary).resolve()
        response_path = isolated_root / "response.json"
        command = [
            *command_prefix,
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--strict-config",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--model",
            model,
            "--config",
            f'model_reasoning_effort="{effort}"',
            "--output-last-message",
            str(response_path),
            "--cd",
            str(isolated_root),
            "--",
            "-",
        ]
        metadata["command"] = command
        metadata["isolated_working_directory"] = str(isolated_root)
        creation: dict[str, Any] = {}
        if os.name == "nt":
            creation["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            creation["start_new_session"] = True
        process_started_at = utc_now()
        process_started_wall_ns = time.time_ns()
        process_started_ns = time.perf_counter_ns()
        process = cast(
            subprocess.Popen[bytes],
            subprocess.Popen(  # noqa: S603 - command is an explicit argv array
                command,
                cwd=isolated_root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={
                    **os.environ,
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                },
                **creation,
            ),
        )
        metadata.update(
            {
                "codex_pid": process.pid,
                "process_started_at": process_started_at,
                "process_started_unix_ns": process_started_wall_ns,
                "process_started_monotonic_ns": process_started_ns,
            }
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(
                prompt.encode("utf-8"), timeout=timeout
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_process(process)
            stdout, stderr = process.communicate()
        process_completed_ns = time.perf_counter_ns()
        metadata.update(
            {
                "process_completed_at": utc_now(),
                "process_completed_monotonic_ns": process_completed_ns,
                "process_wall_seconds": (process_completed_ns - process_started_ns)
                / 1_000_000_000,
                "returncode": process.returncode,
            }
        )
        atomic_create(evidence / "codex-events.jsonl", stdout)
        atomic_create(evidence / "codex-stderr.txt", stderr)
        parsed_events, event_summary = parse_events(stdout)
        metadata.update(event_summary)
        try:
            if timed_out:
                raise AdapterError("Codex worker timed out")
            if process.returncode:
                raise AdapterError("Codex worker returned a nonzero status")
            verify_runtime(event_summary, model, effort)
            response = read_response(response_path, parsed_events)
            atomic_create(evidence / "response.json", dumps(response))
            metadata["status"] = "completed"
            return response
        except BaseException:
            metadata["status"] = "timed_out" if timed_out else "failed"
            raise
        finally:
            metadata["adapter_completed_at"] = utc_now()
            metadata["adapter_wall_seconds"] = (
                time.perf_counter_ns() - adapter_started_ns
            ) / 1_000_000_000
            # The isolated directory is intentionally ephemeral; retain only that it
            # was unique for this attempt, not its contents.
            atomic_create(evidence / "metadata.json", dumps(metadata))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--codex-command",
        type=argv_array,
        required=True,
        help='JSON argv prefix for the installed Codex CLI, for example ["codex"]',
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning-effort", required=True)
    parser.add_argument("--timeout-seconds", type=positive_seconds, default=600.0)
    args = parser.parse_args()
    if args.model != REQUIRED_MODEL or args.reasoning_effort != REQUIRED_EFFORT:
        parser.error(
            f"Definition Check workers require {REQUIRED_MODEL} with {REQUIRED_EFFORT} reasoning"
        )
    try:
        request, evidence = read_request(sys.stdin.buffer.read())
        response = run_codex(
            request,
            evidence,
            args.codex_command,
            args.model,
            args.reasoning_effort,
            args.timeout_seconds,
        )
    except (AdapterError, OSError, ValueError, KeyError) as exc:
        print(f"codex worker adapter: {exc}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(dumps(response))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
