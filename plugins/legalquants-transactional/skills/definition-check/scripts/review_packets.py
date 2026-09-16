#!/usr/bin/env python3
"""Build compact review packets or expand numeric worker responses."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from _runtime_gate import require_supported_python

require_supported_python()

from definition_check.prompts import PromptRegistryError, render_dispatch_prompt
from definition_check.review_packets import (
    DEFAULT_HARD_MAX_CHARACTERS,
    DEFAULT_TARGET_CHARACTERS,
    ReviewPacketError,
    build_discovery_packets,
    build_occurrence_packets,
    build_reference_packets,
    build_semantic_packets,
    expand_discovery_responses,
    expand_occurrence_responses,
    expand_reference_responses,
    expand_semantic_responses,
    validate_packet_response,
    validate_review_packet,
    write_packet_builds,
)
from definition_check.workspace import (
    WorkspaceError,
    cleanup_workspace,
    create_workspace,
    ensure_workspace,
    require_within_workspace,
)


AGENT_BUNDLE_SCHEMA_VERSION = "agent-bundle-v1"


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewPacketError(f"unable to read JSON artifact {path}") from exc


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite artifact: {path}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
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


def _source_sha256(payload: object, explicit: Optional[str]) -> Optional[str]:
    if explicit is not None:
        return explicit
    if not isinstance(payload, dict):
        return None
    source = payload.get("source")
    if isinstance(source, dict) and source.get("sha256") is not None:
        return str(source["sha256"])
    value = payload.get("source_sha256")
    return None if value is None else str(value)


def _records(payload: object, field: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        value = payload
    elif isinstance(payload, dict):
        value = payload.get(field)
    else:
        value = None
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ReviewPacketError(f"input must contain a {field} array")
    return value


def _response_specs(values: list[str]) -> dict[int, object]:
    responses: dict[int, object] = {}
    for value in values:
        number, separator, raw_path = value.partition("=")
        if not separator or not number.isdigit() or int(number) < 1 or not raw_path:
            raise ReviewPacketError("--response must use PACKET_NUMBER=JSON_PATH")
        packet = int(number)
        if packet in responses:
            raise ReviewPacketError("duplicate --response packet number")
        responses[packet] = _read_json(Path(raw_path).resolve())
    return responses


def _manifest_packet_numbers(manifest: dict[str, Any], stage: str) -> list[int]:
    if manifest.get("stage") != stage:
        raise ReviewPacketError("manifest stage does not match --stage")
    packets = manifest.get("packets")
    if not isinstance(packets, list):
        raise ReviewPacketError("manifest packets must be an array")
    numbers = []
    for packet in packets:
        if not isinstance(packet, dict):
            raise ReviewPacketError("manifest packet entry must be an object")
        number = packet.get("packet")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise ReviewPacketError("manifest packet number must be positive")
        numbers.append(number)
    if len(numbers) != len(set(numbers)):
        raise ReviewPacketError("manifest contains duplicate packet numbers")
    return sorted(numbers)


def _canonical_response_path(work_dir: Path, stage: str, packet: int) -> Path:
    return work_dir / "responses" / stage / f"packet-{packet:03d}.json"


def _canonical_response_specs(
    manifest: dict[str, Any], work_dir: Path, stage: str
) -> dict[int, object]:
    responses = {}
    for packet in _manifest_packet_numbers(manifest, stage):
        path = _canonical_response_path(work_dir, stage, packet)
        if not path.is_file():
            raise ReviewPacketError(
                f"missing canonical {stage} response for packet {packet}: {path}"
            )
        responses[packet] = _read_json(path)
    return responses


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build definition-check worker packets or expand compact responses."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser(
        "build", help="Build worker packets and a private manifest"
    )
    build.add_argument(
        "--stage",
        choices=("discovery", "semantic", "occurrence", "reference"),
        required=True,
    )
    build.add_argument("--input", type=Path, required=True)
    build_directory = build.add_mutually_exclusive_group(required=True)
    build_directory.add_argument("--work-dir", type=Path)
    build_directory.add_argument(
        "--output-dir",
        dest="work_dir",
        type=Path,
        help="Deprecated alias for --work-dir",
    )
    build.add_argument("--source-sha256")
    build.add_argument(
        "--target-characters", type=int, default=DEFAULT_TARGET_CHARACTERS
    )
    build.add_argument(
        "--hard-max-characters", type=int, default=DEFAULT_HARD_MAX_CHARACTERS
    )
    build.add_argument(
        "--group-by-context",
        action="store_true",
        help="Experimental occurrence paragraph grouping; preserves every item",
    )

    expand = commands.add_parser(
        "expand", help="Expand numeric responses into an agent bundle"
    )
    expand.add_argument(
        "--stage",
        choices=("discovery", "semantic", "occurrence", "reference"),
        required=True,
    )
    expand.add_argument("--work-dir", type=Path, required=True)
    expand.add_argument("--manifest", type=Path, required=True)
    expand.add_argument(
        "--response",
        action="append",
        default=[],
        metavar="PACKET=PATH",
        help="Packet number and JSON rows; repeat once per packet",
    )
    expand.add_argument("--output", type=Path, required=True)
    expand.add_argument("--base-bundle", type=Path)
    expand.add_argument("--source-sha256")
    expand.add_argument("--agent-role")
    expand.add_argument("--model-id")
    expand.add_argument("--prompt-version")

    create = commands.add_parser(
        "workspace-create", help="Create a marked run workspace"
    )
    create.add_argument("--source-sha256")
    create.add_argument("--workspace-root", type=Path)

    cleanup = commands.add_parser(
        "workspace-cleanup", help="Delete one exact marked temporary workspace"
    )
    cleanup.add_argument("--work-dir", type=Path, required=True)

    dispatch = commands.add_parser(
        "render-dispatch", help="Render the standardized generic-worker task"
    )
    dispatch.add_argument(
        "--stage",
        choices=("discovery", "semantic", "occurrence", "reference"),
        required=True,
    )
    dispatch.add_argument("--work-dir", type=Path, required=True)
    dispatch.add_argument("--packet", type=Path, required=True)
    dispatch.add_argument(
        "--response",
        type=Path,
        help="Deprecated explicit path; it must equal the canonical packet response path",
    )

    validate = commands.add_parser(
        "validate-response", help="Validate one compact worker response"
    )
    validate.add_argument(
        "--stage",
        choices=("discovery", "semantic", "occurrence", "reference"),
        required=True,
    )
    validate.add_argument("--work-dir", type=Path, required=True)
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--packet-number", type=int, required=True)
    validate.add_argument("--response", type=Path, required=True)
    return parser


def _build(args: argparse.Namespace) -> dict[str, object]:
    payload = _read_json(args.input.resolve())
    source_sha256 = _source_sha256(payload, args.source_sha256)
    if args.stage == "discovery":
        build = build_discovery_packets(
            _records(payload, "seeds"), source_sha256=source_sha256
        )
    elif args.stage == "semantic":
        build = build_semantic_packets(
            _records(payload, "envelopes"),
            source_sha256=source_sha256,
            target_characters=args.target_characters,
            hard_max_characters=args.hard_max_characters,
        )
    elif args.stage == "occurrence":
        build = build_occurrence_packets(
            _records(payload, "envelopes"),
            source_sha256=source_sha256,
            target_characters=args.target_characters,
            hard_max_characters=args.hard_max_characters,
            group_by_context=args.group_by_context,
        )
    else:
        build = build_reference_packets(
            _records(payload, "envelopes"),
            source_sha256=source_sha256,
            target_characters=args.target_characters,
            hard_max_characters=args.hard_max_characters,
        )
    root = ensure_workspace(args.work_dir.resolve(), source_sha256=source_sha256)[0]
    root = write_packet_builds(root, [build])
    return {
        "status": "completed",
        "stage": args.stage,
        "packets": len(build.packets),
        "output": str(root),
        "manifest": str(root / "private" / f"{args.stage}-manifest.json"),
    }


def _expand(args: argparse.Namespace) -> dict[str, object]:
    work_dir = ensure_workspace(args.work_dir.resolve())[0]
    paths = [args.manifest, args.output, args.base_bundle]
    paths.extend(Path(value.partition("=")[2]) for value in args.response)
    for path in paths:
        if path is None:
            continue
        require_within_workspace(path, work_dir, label="internal review artifact")
    manifest = _read_json(args.manifest.resolve())
    if not isinstance(manifest, dict):
        raise ReviewPacketError("manifest root must be an object")
    responses = (
        _response_specs(args.response)
        if args.response
        else _canonical_response_specs(manifest, work_dir, args.stage)
    )
    bundle: dict[str, Any]
    if args.base_bundle:
        base = _read_json(args.base_bundle.resolve())
        if not isinstance(base, dict):
            raise ReviewPacketError("base bundle root must be an object")
        bundle = dict(base)
        if bundle.get("schema_version") != AGENT_BUNDLE_SCHEMA_VERSION:
            raise ReviewPacketError("base bundle has an unsupported schema_version")
    else:
        bundle = {"schema_version": AGENT_BUNDLE_SCHEMA_VERSION}
    if args.stage == "discovery":
        submissions = expand_discovery_responses(
            manifest,
            responses,
            agent_role=args.agent_role or "discovery_reviewer",
            model_id=args.model_id,
            prompt_version=args.prompt_version or manifest.get("prompt_version"),
            expected_source_sha256=args.source_sha256,
        )
        field = "candidate_proposals"
        bundle["discovery_review"] = {
            field: manifest[field]
            for field in ("source_sha256", "prompt_sha256", "queue_sha256")
        }
        bundle["discovery_review"]["responses"] = [
            {
                "packet": packet,
                "rows": (response["rows"] if isinstance(response, dict) else response),
            }
            for packet, response in sorted(responses.items())
        ]
    elif args.stage == "semantic":
        submissions = expand_semantic_responses(
            manifest,
            responses,
            agent_role=args.agent_role or "semantic_reviewer",
            model_id=args.model_id,
            prompt_version=args.prompt_version or manifest.get("prompt_version"),
            expected_source_sha256=args.source_sha256,
        )
        field = "semantic_adjudications"
    elif args.stage == "occurrence":
        submissions = expand_occurrence_responses(
            manifest,
            responses,
            agent_role=args.agent_role or "occurrence_reviewer",
            model_id=args.model_id,
            prompt_version=args.prompt_version or manifest.get("prompt_version"),
            expected_source_sha256=args.source_sha256,
        )
        field = "occurrence_adjudications"
    else:
        submissions = expand_reference_responses(
            manifest,
            responses,
            agent_role=args.agent_role or "reference_reviewer",
            model_id=args.model_id,
            prompt_version=args.prompt_version or manifest.get("prompt_version"),
            expected_source_sha256=args.source_sha256,
        )
        field = "reference_adjudications"
    bundle[field] = [asdict(item) for item in submissions]
    _write_json(args.output.resolve(), bundle)
    return {
        "status": "completed",
        "stage": args.stage,
        "decisions": len(submissions),
        "output": str(args.output.resolve()),
    }


def _create_workspace(args: argparse.Namespace) -> dict[str, object]:
    root, marker = create_workspace(
        source_sha256=args.source_sha256, workspace_root=args.workspace_root
    )
    return {
        "status": "completed",
        "work_dir": str(root),
        "run_id": marker["run_id"],
        "retention": "temporary_delete_after_handoff",
    }


def _cleanup_workspace(args: argparse.Namespace) -> dict[str, object]:
    removed = cleanup_workspace(args.work_dir.resolve())
    return {"status": "completed", "removed": str(removed)}


def _render_dispatch(args: argparse.Namespace) -> dict[str, object]:
    work_dir = ensure_workspace(args.work_dir.resolve())[0]
    packet = require_within_workspace(args.packet, work_dir, label="dispatch packet")
    match = packet.stem.rsplit("-", 1)
    if len(match) != 2 or not match[1].isdigit() or int(match[1]) < 1:
        raise ReviewPacketError(
            "dispatch packet filename must end in a positive number"
        )
    packet_number = int(match[1])
    expected_packet = (
        work_dir / "packets" / args.stage / f"packet-{packet_number:03d}.json"
    ).resolve()
    if packet != expected_packet:
        raise ReviewPacketError("dispatch packet is not at its canonical stage path")
    packet_payload = validate_review_packet(_read_json(packet))
    if packet_payload.get("stage") != args.stage:
        raise ReviewPacketError("dispatch packet stage does not match --stage")
    if packet_payload.get("packet") != packet_number:
        raise ReviewPacketError("dispatch packet ordinal does not match its filename")
    response_template = packet_payload.get("response_template")
    response_schema = packet_payload.get("response_schema")
    if not isinstance(response_template, dict) or not isinstance(response_schema, dict):
        raise ReviewPacketError("dispatch packet lacks its response contract")
    response = _canonical_response_path(work_dir, args.stage, packet_number).resolve()
    if args.response is not None:
        explicit_response = require_within_workspace(
            args.response, work_dir, label="dispatch response"
        )
        if explicit_response != response:
            raise ReviewPacketError(
                "dispatch response must use the canonical stage and packet path"
            )
    if response.exists():
        raise ReviewPacketError(
            "canonical response path already exists; the packet may already be dispatched"
        )
    _write_json(response, response_template)
    manifest = work_dir / "private" / f"{args.stage}-manifest.json"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "validate-response",
        "--stage",
        args.stage,
        "--work-dir",
        str(work_dir),
        "--manifest",
        str(manifest),
        "--packet-number",
        str(packet_number),
        "--response",
        str(response),
    ]
    validation_command = (
        subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
    )
    prompt = render_dispatch_prompt(
        args.stage, packet, response, validation_command=validation_command
    )
    return {
        "status": "completed",
        "stage": args.stage,
        "packet": str(packet),
        "response": str(response),
        "prompt": prompt,
        "validation_command": command,
    }


def _validate_response(args: argparse.Namespace) -> dict[str, object]:
    work_dir = ensure_workspace(args.work_dir.resolve())[0]
    manifest_path = require_within_workspace(
        args.manifest, work_dir, label="review manifest"
    )
    response_path = require_within_workspace(
        args.response, work_dir, label="review response"
    )
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ReviewPacketError("manifest root must be an object")
    rows = validate_packet_response(
        manifest,
        _read_json(response_path),
        stage=args.stage,
        packet_ordinal=args.packet_number,
    )
    return {
        "status": "completed",
        "stage": args.stage,
        "packet": args.packet_number,
        "rows": rows,
        "response": str(response_path),
    }


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        handlers = {
            "build": _build,
            "expand": _expand,
            "workspace-create": _create_workspace,
            "workspace-cleanup": _cleanup_workspace,
            "render-dispatch": _render_dispatch,
            "validate-response": _validate_response,
        }
        summary = handlers[args.command](args)
    except (
        FileExistsError,
        OSError,
        PromptRegistryError,
        ReviewPacketError,
        WorkspaceError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {"status": "failed", "error": str(exc)},
                ensure_ascii=True,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
