#!/usr/bin/env python3
"""Run the complete Definition Check review with fresh Codex workers."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Iterable
from typing import Any

from _runtime_gate import require_supported_python

require_supported_python()

from definition_check.analyze import build_usages, run_rules
from definition_check.extract import extract_quoted_observations
from definition_check.ooxml import extract_docx
from definition_check.models import CandidateProposal
from definition_check.prompts import prompt_inventory
from definition_check.response_publication import (
    atomic_create,
    dumps,
    publication_contract,
)
from definition_check.review_packets import (
    ReviewPacketError,
    build_discovery_packets,
    build_semantic_packets,
    expand_discovery_responses,
    expand_occurrence_responses,
    expand_reference_responses,
    expand_semantic_responses,
    validate_packet_response,
    write_packet_builds,
)
from definition_check.seeds import generate_discovery_seeds
from definition_check.semantic_review import (
    build_review_envelopes,
    build_term_candidates,
)
from definition_check.stage_runner import adapter_packet, normalize_response, run_stage
from definition_check.term_identity import TERM_NORMALIZATION_VERSION
from definition_check.workspace import (
    cleanup_workspace,
    create_workspace,
    ensure_workspace,
    require_disjoint_paths,
)

MODEL = "gpt-5.6-luna"
REASONING_EFFORT = "medium"
WORKFLOW_SCHEMA = "definition-check-review-workflow-v1"
STAGES = ("discovery", "semantic", "reference", "occurrence")


def _json_argv(value: str) -> list[str]:
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


def _max_workers(value: str) -> str | int:
    if value == "auto":
        return value
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be auto or a positive integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be auto or a positive integer")
    return number


def _resolved_worker_count(value: str | int) -> tuple[int, str]:
    if isinstance(value, int):
        return value, "explicit"
    for name in (
        "CODEX_HOST_WORKER_CAPACITY",
        "CODEX_MAX_WORKERS",
        "OPENAI_CODEX_MAX_WORKERS",
    ):
        raw = os.environ.get(name)
        if raw and raw.isdigit() and int(raw) > 0:
            return int(raw), name
    return 4, "default"


def _sha256_json(value: object) -> str:
    raw = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def _atomic_replace_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(value, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _provider_usage(work: Path) -> dict[str, Any]:
    fields = (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "model_calls",
        "total_tokens",
    )
    total = dict.fromkeys(fields, 0)
    by_stage: dict[str, dict[str, int]] = {}
    attempts_with_usage = 0
    for path in sorted((work / "private" / "workers").rglob("metadata.json")):
        metadata = _read_object(path)
        usage = metadata.get("usage")
        if not isinstance(usage, dict):
            continue
        stage = str(metadata.get("stage", "unknown"))
        stage_usage = by_stage.setdefault(stage, dict.fromkeys(fields, 0))
        for field in fields:
            value = usage.get(field, 0)
            if isinstance(value, int) and not isinstance(value, bool):
                total[field] += value
                stage_usage[field] += value
        attempts_with_usage += 1
    return {
        "provenance": "codex_jsonl_turn.completed",
        "attempts_with_usage": attempts_with_usage,
        "total": total,
        "by_stage": dict(sorted(by_stage.items())),
    }


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReviewPacketError(f"expected a JSON object: {path}")
    return value


class ReviewWorkflow:
    def __init__(self, args: argparse.Namespace) -> None:
        self.input = args.input.resolve()
        self.output = args.output_dir.resolve()
        self.command = args.codex_command_json
        self.timeout = args.worker_timeout_seconds
        self.worker_count, self.capacity_source = _resolved_worker_count(
            args.max_workers
        )
        self.keep_work_dir = args.keep_work_dir
        self.qa_annotated_document = args.qa_annotated_document
        self.started = time.perf_counter()
        self.started_at = datetime.now(UTC).isoformat()
        self.source = extract_docx(self.input)
        if args.resume:
            self.work, _ = ensure_workspace(
                args.resume.resolve(), source_sha256=self.source.sha256
            )
            self.created_workspace = False
        else:
            self.work, _ = create_workspace(source_sha256=self.source.sha256)
            self.created_workspace = True
        require_disjoint_paths(self.output, self.work)
        self.state_path = self.work / "workflow-state.json"
        self.events_path = self.work / "workflow-events.jsonl"
        self.state = self._load_or_create_state()
        self.capacity = asyncio.Semaphore(self.worker_count)
        self.actual_attempts: dict[tuple[str, int], int] = {}

    def _identity(self) -> dict[str, Any]:
        return {
            "schema": WORKFLOW_SCHEMA,
            "input": str(self.input),
            "source_sha256": self.source.sha256,
            "output": str(self.output),
            "prompt_inventory": prompt_inventory(),
            "normalization_version": TERM_NORMALIZATION_VERSION,
            "model": MODEL,
            "reasoning_effort": REASONING_EFFORT,
            "codex_command_sha256": _sha256_json(self.command),
        }

    def _load_or_create_state(self) -> dict[str, Any]:
        identity = self._identity()
        if self.state_path.exists():
            state = _read_object(self.state_path)
            recorded = state.get("identity")
            if recorded != identity:
                mismatches = sorted(
                    key
                    for key in identity
                    if not isinstance(recorded, dict)
                    or recorded.get(key) != identity[key]
                )
                raise ReviewPacketError(
                    f"resume identity mismatch: {mismatches}",
                    code="resume_identity_mismatch",
                    correction="Resume with the original source, prompts, normalization, model, command, and output path.",
                )
            return state
        state = {
            "identity": identity,
            "status": "starting",
            "created_at": self.started_at,
            "stages": {},
            "rebuilds": [],
        }
        _atomic_replace_json(self.state_path, state)
        return state

    def checkpoint(self, status: str, **details: Any) -> None:
        self.state["status"] = status
        self.state["updated_at"] = datetime.now(UTC).isoformat()
        self.state.update(details)
        _atomic_replace_json(self.state_path, self.state)

    def event(self, name: str, **details: Any) -> None:
        value = {
            "event": name,
            "timestamp": datetime.now(UTC).isoformat(),
            "elapsed_seconds": time.perf_counter() - self.started,
            **details,
        }
        with self.events_path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(value, ensure_ascii=True, sort_keys=True) + "\n")

    def prepare_discovery(self) -> dict[str, Any]:
        build = build_discovery_packets(
            generate_discovery_seeds(self.source), source_sha256=self.source.sha256
        )
        existed = (self.work / "private" / "discovery-manifest.json").exists()
        write_packet_builds(self.work, [build])
        self.event(
            "stage_prepared",
            stage="discovery",
            packets=len(build.packets),
            rebuild=not existed,
        )
        if not existed:
            self.state["rebuilds"].append("discovery")
        return build.manifest

    def prepare_semantic(
        self, proposals: Iterable[CandidateProposal]
    ) -> dict[str, Any]:
        lexical = extract_quoted_observations(self.source)
        usages = build_usages(self.source, [])
        findings = run_rules(self.source, [], usages)
        candidates = build_term_candidates(
            self.source, [], findings, lexical, proposals
        )
        envelopes = build_review_envelopes(self.source, candidates)
        build = build_semantic_packets(envelopes, source_sha256=self.source.sha256)
        existed = (self.work / "private" / "semantic-manifest.json").exists()
        write_packet_builds(self.work, [build])
        self.event(
            "stage_prepared",
            stage="semantic",
            packets=len(build.packets),
            rebuild=not existed,
        )
        if not existed:
            self.state["rebuilds"].append("semantic")
        return build.manifest

    def load_manifest(self, stage: str) -> dict[str, Any]:
        manifest = _read_object(self.work / "private" / f"{stage}-manifest.json")
        if manifest.get("normalization_version") != TERM_NORMALIZATION_VERSION:
            raise ReviewPacketError(
                f"{stage} manifest normalization version drifted",
                stage=stage,
                code="normalization_drift",
            )
        self.state["stages"].setdefault(stage, {})["queue_sha256"] = manifest.get(
            "queue_sha256"
        )
        return manifest

    def _revision_dir(self, stage: str, packet: int) -> Path:
        return self.work / "orchestrator-responses" / stage / f"packet-{packet:03d}"

    def _selected_responses(self, manifest: dict[str, Any]) -> dict[int, dict]:
        stage = manifest["stage"]
        selected: dict[int, dict] = {}
        for packet_entry in manifest["packets"]:
            packet = packet_entry["packet"]
            canonical = self.work / "responses" / stage / f"packet-{packet:03d}.json"
            candidates = (
                [canonical]
                if canonical.is_file()
                else sorted(self._revision_dir(stage, packet).glob("revision-*.json"))
            )
            if candidates:
                path = candidates[-1]
                response = _read_object(path)
                validate_packet_response(
                    manifest, response, stage=stage, packet_ordinal=packet
                )
                selected[packet] = response
                continue
            evidence = sorted(
                (self.work / "private" / "workers" / stage).glob(
                    f"packet-{packet:03d}-attempt-*/response.json"
                ),
                reverse=True,
            )
            for path in evidence:
                try:
                    response = normalize_response(manifest, packet, _read_object(path))
                    if not isinstance(response, dict):
                        continue
                    validate_packet_response(
                        manifest, response, stage=stage, packet_ordinal=packet
                    )
                except (OSError, ValueError, ReviewPacketError):
                    continue
                directory = self._revision_dir(stage, packet)
                directory.mkdir(parents=True, exist_ok=True)
                revision = len(list(directory.glob("revision-*.json"))) + 1
                atomic_create(
                    directory / f"revision-{revision:03d}.json", dumps(response)
                )
                self.event(
                    "worker_response_recovered",
                    stage=stage,
                    packet=packet,
                    source=str(path),
                )
                selected[packet] = response
                break
        return selected

    def _next_actual_attempt(self, stage: str, packet: int) -> int:
        key = (stage, packet)
        if key not in self.actual_attempts:
            worker_root = self.work / "private" / "workers" / stage
            existing = []
            for path in worker_root.glob(f"packet-{packet:03d}-attempt-*"):
                suffix = path.name.rpartition("-")[2]
                if suffix.isdigit():
                    existing.append(int(suffix))
            self.actual_attempts[key] = max(existing, default=0)
        self.actual_attempts[key] += 1
        return self.actual_attempts[key]

    async def _dispatch(
        self,
        manifest: dict[str, Any],
        stage: str,
        packet: int,
        correction: dict | None,
    ) -> object:
        actual_attempt = self._next_actual_attempt(stage, packet)
        packet_path = self.work / "packets" / stage / f"packet-{packet:03d}.json"
        payload = adapter_packet(_read_object(packet_path))
        request = {
            "packet": payload,
            "attempt": actual_attempt,
            "correction": correction,
            "publication_contract": publication_contract(
                self.work / "private" / f"{stage}-manifest.json",
                packet,
                stage,
                self.timeout,
            ),
        }
        adapter = Path(__file__).resolve().with_name("codex_worker_adapter.py")
        command = [
            sys.executable,
            str(adapter),
            "--codex-command",
            json.dumps(self.command, ensure_ascii=True),
            "--model",
            MODEL,
            "--reasoning-effort",
            REASONING_EFFORT,
            "--timeout-seconds",
            str(self.timeout),
        ]
        capacity_queued = time.perf_counter()
        async with self.capacity:
            capacity_acquired = time.perf_counter()
            launch_recorded = time.perf_counter()
            self.event(
                "worker_launch",
                stage=stage,
                packet=packet,
                attempt=actual_attempt,
                capacity_wait_seconds=capacity_acquired - capacity_queued,
                launch_delay_seconds=launch_recorded - capacity_acquired,
                launch_delay_kind="permit_to_process",
            )
            process_startup_started = time.perf_counter()
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
            worker_started = time.perf_counter()
            self.event(
                "worker_process_started",
                stage=stage,
                packet=packet,
                attempt=actual_attempt,
                process_startup_seconds=worker_started - process_startup_started,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(
                        json.dumps(request, ensure_ascii=True).encode("ascii")
                    ),
                    timeout=self.timeout + 30,
                )
            except BaseException:
                if process.returncode is None:
                    process.kill()
                await process.communicate()
                raise
            finally:
                self.event(
                    "worker_complete",
                    stage=stage,
                    packet=packet,
                    attempt=actual_attempt,
                    worker_duration_seconds=time.perf_counter() - worker_started,
                )
        if process.returncode:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise ReviewPacketError(
                f"Codex adapter failed for {stage} packet {packet}: {message[-1000:]}",
                stage=stage,
                packet=packet,
                code="worker_failure",
            )
        try:
            return json.loads(stdout)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ReviewPacketError(
                "Codex adapter returned invalid UTF-8 JSON",
                stage=stage,
                packet=packet,
                code="invalid_worker_json",
            ) from exc

    async def execute_stage(
        self,
        manifest: dict[str, Any],
        *,
        packets: set[int] | None = None,
        corrections: dict[int, dict[str, Any]] | None = None,
    ) -> dict[int, dict]:
        stage = manifest["stage"]
        selected = self._selected_responses(manifest)
        all_packets = {entry["packet"] for entry in manifest["packets"]}
        scheduled = packets if packets is not None else all_packets - set(selected)
        if not scheduled:
            self.event("stage_reused", stage=stage, packets=len(selected))
            return selected
        scheduling_manifest = {
            **manifest,
            "packets": [
                entry for entry in manifest["packets"] if entry["packet"] in scheduled
            ],
        }
        stage_started = time.perf_counter()

        def stage_event(value: dict) -> None:
            details = dict(value)
            kind = details.pop("event", "unknown")
            self.event(f"packet_{kind}", stage=stage, **details)

        def collect(packet: int, response: dict) -> None:
            directory = self._revision_dir(stage, packet)
            directory.mkdir(parents=True, exist_ok=True)
            revision = len(list(directory.glob("revision-*.json"))) + 1
            atomic_create(directory / f"revision-{revision:03d}.json", dumps(response))
            selected[packet] = response

        await run_stage(
            scheduling_manifest,
            lambda packet, attempt, correction: self._dispatch(
                manifest, stage, packet, correction
            ),
            collect,
            stage_event,
            concurrency=max(1, len(scheduled)),
            validation_manifest=manifest,
            initial_corrections=corrections,
        )
        duration = time.perf_counter() - stage_started
        self.state["stages"].setdefault(stage, {}).update(
            {
                "status": "packet_validation_complete",
                "packets": len(selected),
                "wall_seconds": duration,
            }
        )
        self.checkpoint(f"{stage}_packets_complete")
        self.event("stage_packets_complete", stage=stage, wall_seconds=duration)
        return selected

    def publish_stage(
        self, manifest: dict[str, Any], responses: dict[int, dict]
    ) -> None:
        stage = manifest["stage"]
        expected = {entry["packet"] for entry in manifest["packets"]}
        if set(responses) != expected:
            raise ReviewPacketError(f"{stage} response coverage is incomplete")
        for packet, response in sorted(responses.items()):
            path = self.work / "responses" / stage / f"packet-{packet:03d}.json"
            if path.exists():
                if _read_object(path) != response:
                    raise ReviewPacketError("accepted response is immutable")
                continue
            atomic_create(path, dumps(response))
        self.state["stages"].setdefault(stage, {})["status"] = "complete"
        self.checkpoint(f"{stage}_complete")
        self.event("stage_complete", stage=stage, packets=len(responses))

    def write_bundle(self, name: str, value: dict[str, Any]) -> Path:
        path = self.work / "bundles" / name
        raw = dumps(value)
        canonical = json.loads(raw)
        if path.exists():
            if _read_object(path) != canonical:
                raise ReviewPacketError(f"immutable bundle changed: {name}")
        else:
            atomic_create(path, raw)
        return path

    def run_pipeline(self, bundle: Path, *, prepare_only: bool, label: str) -> float:
        before = {
            stage: (
                _read_object(self.work / "private" / f"{stage}-manifest.json").get(
                    "queue_sha256"
                )
                if (self.work / "private" / f"{stage}-manifest.json").is_file()
                else None
            )
            for stage in STAGES
        }
        script = Path(__file__).resolve().with_name("definition_check.py")
        command = [
            sys.executable,
            str(script),
            str(self.input),
            "--output-dir",
            str(self.output),
            "--work-dir",
            str(self.work),
            "--agent-bundle",
            str(bundle),
        ]
        if prepare_only:
            command.append("--prepare-only")
        else:
            command.append("--debug-telemetry")
            if self.qa_annotated_document:
                command.append("--qa-annotated-document")
        started = time.perf_counter()
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            },
        )
        duration = time.perf_counter() - started
        self.event(
            "pipeline_pass",
            label=label,
            prepare_only=prepare_only,
            wall_seconds=duration,
            returncode=result.returncode,
        )
        if result.returncode:
            error = result.stderr.decode("utf-8", errors="replace").strip()
            raise ReviewPacketError(f"{label} failed: {error[-2000:]}")
        for stage in STAGES:
            path = self.work / "private" / f"{stage}-manifest.json"
            after = _read_object(path).get("queue_sha256") if path.is_file() else None
            if after is not None and before[stage] != after:
                if stage not in self.state["rebuilds"]:
                    self.state["rebuilds"].append(stage)
                self.event(
                    "stage_rebuilt",
                    stage=stage,
                    previous_queue_sha256=before[stage],
                    queue_sha256=after,
                    label=label,
                )
        return duration

    async def run(self) -> dict[str, Any]:
        completed_report = self.output / "definition-check-run.json"
        if self.state.get("status") == "complete" and completed_report.is_file():
            self.event("workflow_reused", status="complete")
            report = _read_object(completed_report)
            if "provider_usage" not in report:
                report["provider_usage"] = _provider_usage(self.work)
                _atomic_replace_json(completed_report, report)
            return report
        self.checkpoint("preparing_discovery")
        discovery_manifest = self.prepare_discovery()
        discovery_responses = await self.execute_stage(discovery_manifest)
        proposals = expand_discovery_responses(
            discovery_manifest,
            discovery_responses,
            model_id=MODEL,
            prompt_version=discovery_manifest["prompt_version"],
            expected_source_sha256=self.source.sha256,
        )
        self.publish_stage(discovery_manifest, discovery_responses)
        bundle: dict[str, Any] = {
            "schema_version": "agent-bundle-v1",
            "candidate_proposals": [asdict(item) for item in proposals],
            "discovery_review": {
                key: discovery_manifest[key]
                for key in ("source_sha256", "prompt_sha256", "queue_sha256")
            },
        }
        bundle["discovery_review"]["responses"] = [
            discovery_responses[packet] for packet in sorted(discovery_responses)
        ]
        self.write_bundle("01-discovery.json", bundle)

        semantic_manifest = self.prepare_semantic(proposals)
        semantic_responses = await self.execute_stage(semantic_manifest)
        for correction_round in range(2):
            try:
                semantic = expand_semantic_responses(
                    semantic_manifest,
                    semantic_responses,
                    model_id=MODEL,
                    prompt_version=semantic_manifest["prompt_version"],
                    expected_source_sha256=self.source.sha256,
                )
                break
            except ReviewPacketError as exc:
                if exc.code != "cross_packet_alias_conflict" or exc.item is None:
                    raise
                item = int(exc.item)
                packet = next(
                    entry["packet"]
                    for entry in semantic_manifest["items"]
                    if entry["ordinal"] == item
                )
                self.event(
                    "cross_packet_correction",
                    stage="semantic",
                    packet=packet,
                    item=item,
                    round=correction_round + 1,
                )
                semantic_responses = await self.execute_stage(
                    semantic_manifest,
                    packets={packet},
                    corrections={
                        packet: {
                            "response": semantic_responses[packet],
                            "error": str(exc),
                            "validation_error": exc.to_dict(),
                            "replace_item_ordinals": [item],
                            "preserve_item_ordinals": [
                                ordinal
                                for ordinal in next(
                                    entry["item_ordinals"]
                                    for entry in semantic_manifest["packets"]
                                    if entry["packet"] == packet
                                )
                                if ordinal != item
                            ],
                        }
                    },
                )
        else:
            raise ReviewPacketError("semantic cross-packet correction did not converge")
        self.publish_stage(semantic_manifest, semantic_responses)
        bundle["semantic_adjudications"] = [asdict(item) for item in semantic]
        semantic_bundle = self.write_bundle("02-semantic.json", bundle)

        self.run_pipeline(
            semantic_bundle, prepare_only=True, label="downstream_preparation"
        )
        reference_manifest = self.load_manifest("reference")
        occurrence_manifest = self.load_manifest("occurrence")
        reference_responses, occurrence_responses = await asyncio.gather(
            self.execute_stage(reference_manifest),
            self.execute_stage(occurrence_manifest),
        )
        references = expand_reference_responses(
            reference_manifest,
            reference_responses,
            model_id=MODEL,
            prompt_version=reference_manifest["prompt_version"],
            expected_source_sha256=self.source.sha256,
        )
        occurrence_payloads: dict[int, object] = dict(occurrence_responses)
        occurrences = expand_occurrence_responses(
            occurrence_manifest,
            occurrence_payloads,
            model_id=MODEL,
            prompt_version=occurrence_manifest["prompt_version"],
            expected_source_sha256=self.source.sha256,
        )
        self.publish_stage(reference_manifest, reference_responses)
        self.publish_stage(occurrence_manifest, occurrence_responses)
        bundle["reference_adjudications"] = [asdict(item) for item in references]
        bundle["occurrence_adjudications"] = [asdict(item) for item in occurrences]
        complete_bundle = self.write_bundle("03-complete.json", bundle)

        final_seconds = self.run_pipeline(
            complete_bundle, prepare_only=False, label="final_validation_and_render"
        )
        elapsed = time.perf_counter() - self.started
        events = [
            json.loads(line)
            for line in self.events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        launch_delays = [
            event["launch_delay_seconds"]
            for event in events
            if event.get("event") == "worker_launch"
            and event.get("launch_delay_kind") == "permit_to_process"
        ]
        launches: dict[tuple[str, int], int] = {}
        for event in events:
            if event.get("event") != "worker_launch":
                continue
            key = (str(event.get("stage")), int(event.get("packet", 0)))
            launches[key] = launches.get(key, 0) + 1
        retries = sum(max(value - 1, 0) for value in launches.values())
        report = {
            "schema": WORKFLOW_SCHEMA,
            "status": "complete",
            "source_sha256": self.source.sha256,
            "normalization_version": TERM_NORMALIZATION_VERSION,
            "model": MODEL,
            "reasoning_effort": REASONING_EFFORT,
            "max_workers": self.worker_count,
            "capacity_source": self.capacity_source,
            "packet_counts": {
                stage: len(self.load_manifest(stage)["packets"]) for stage in STAGES
            },
            "stage_wall_seconds": {
                stage: self.state["stages"].get(stage, {}).get("wall_seconds", 0.0)
                for stage in STAGES
            },
            "worker_attempts": sum(launches.values()),
            "retries": retries,
            "provider_usage": _provider_usage(self.work),
            "maximum_worker_launch_delay_seconds": max(launch_delays, default=0.0),
            "scheduler_idle_seconds": sum(launch_delays),
            "final_validation_and_render_seconds": final_seconds,
            "total_elapsed_seconds": elapsed,
            "work_dir": str(self.work),
            "events": str(self.output / "definition-check-events.jsonl"),
        }
        atomic_create(
            self.output / "definition-check-events.jsonl",
            self.events_path.read_bytes(),
        )
        _atomic_replace_json(self.output / "definition-check-run.json", report)
        self.checkpoint("complete", completed_at=datetime.now(UTC).isoformat())
        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--codex-command-json",
        type=_json_argv,
        required=True,
        help='Codex executable argv prefix, for example ["codex"]',
    )
    parser.add_argument("--max-workers", type=_max_workers, default="auto")
    parser.add_argument("--worker-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--keep-work-dir", action="store_true")
    parser.add_argument("--qa-annotated-document", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.worker_timeout_seconds <= 0:
        raise SystemExit("--worker-timeout-seconds must be positive")
    workflow: ReviewWorkflow | None = None
    try:
        workflow = ReviewWorkflow(args)
        report = asyncio.run(workflow.run())
    except (OSError, ValueError, ReviewPacketError) as exc:
        error: dict[str, Any] = {"status": "failed", "error": str(exc)}
        if workflow is not None:
            workflow.checkpoint("failed", error=str(exc))
            error["work_dir"] = str(workflow.work)
        if isinstance(exc, ReviewPacketError):
            error["validation_error"] = exc.to_dict()
        print(json.dumps(error, ensure_ascii=True, sort_keys=True), file=sys.stderr)
        return 2
    work_dir = workflow.work
    if workflow.created_workspace and not workflow.keep_work_dir:
        cleanup_workspace(work_dir)
        report["work_dir_retained"] = False
    else:
        report["work_dir_retained"] = True
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
