#!/usr/bin/env python3
"""Build, dispatch, and expand conform's mapping-stage packets; manage its workspace."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from _runtime_gate import require_supported_python

require_supported_python()

from conform.packets import (  # noqa: E402
    PacketError,
    build_mapping_packets,
    canonical_response_path,
    expand_responses,
    prefill_response,
    validate_response,
)
from conform.prompts import render_mapping_dispatch_prompt  # noqa: E402
from conform.workspace import (  # noqa: E402
    WorkspaceError,
    cleanup_workspace,
    create_workspace,
    require_within_workspace,
)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PacketError(f"unable to read JSON artifact {path}") from exc


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _cmd_workspace_create(args: argparse.Namespace) -> dict[str, Any]:
    root, marker = create_workspace(
        fingerprint=args.fingerprint, workspace_root=args.workspace_root
    )
    return {"work_dir": str(root), "marker": marker}


def _cmd_workspace_cleanup(args: argparse.Namespace) -> dict[str, Any]:
    root = cleanup_workspace(args.work_dir)
    return {"cleaned_up": str(root)}


def _cmd_build(args: argparse.Namespace) -> dict[str, Any]:
    source_ledger = _read_json(args.source_ledger)
    core_ledger = _read_json(args.core_ledger)
    selected_text = None
    if args.selected_text is not None:
        payload = _read_json(args.selected_text)
        if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
            raise PacketError(
                "--selected-text file must contain a JSON object with a text field"
            )
        selected_text = payload["text"]

    packets, manifest = build_mapping_packets(
        source_ledger,
        core_ledger,
        mode=args.mode,
        selected_text=selected_text,
        target_items_per_packet=args.target_items_per_packet,
    )

    work_dir = args.work_dir.resolve()
    packet_dir = require_within_workspace(
        work_dir / "packets" / "mapping", work_dir, label="packet directory"
    )
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_paths = []
    for packet in packets:
        packet_path = packet_dir / f"packet-{packet['packet']:03d}.json"
        if packet_path.exists():
            raise PacketError(f"refusing to overwrite existing packet: {packet_path}")
        _write_json(packet_path, packet)
        packet_paths.append(str(packet_path))

    manifest_path = require_within_workspace(
        work_dir / "private" / "mapping-manifest.json", work_dir, label="manifest path"
    )
    if manifest_path.exists():
        raise PacketError(f"refusing to overwrite existing manifest: {manifest_path}")
    _write_json(manifest_path, manifest)

    return {
        "manifest": str(manifest_path),
        "packets": packet_paths,
        "item_count": len(manifest["items"]),
        "packet_count": len(packets),
    }


def _cmd_render_dispatch(args: argparse.Namespace) -> dict[str, Any]:
    work_dir = args.work_dir.resolve()
    packet_path = require_within_workspace(args.packet, work_dir, label="packet")
    packet = _read_json(packet_path)
    response_path = prefill_response(work_dir, packet)
    validation_command = (
        "python conform_packets.py validate-response --work-dir "
        f"{work_dir} --manifest {work_dir / 'private' / 'mapping-manifest.json'} "
        f"--packet-number {packet['packet']} --response {response_path}"
    )
    prompt = render_mapping_dispatch_prompt(
        packet_path=packet_path,
        response_path=response_path,
        validation_command=validation_command,
    )
    return {"response_path": str(response_path), "prompt": prompt}


def _cmd_validate_response(args: argparse.Namespace) -> dict[str, Any]:
    work_dir = args.work_dir.resolve()
    manifest = _read_json(args.manifest)
    packet_path = (
        work_dir / "packets" / "mapping" / f"packet-{args.packet_number:03d}.json"
    )
    packet = _read_json(packet_path)
    response = _read_json(args.response)
    validate_response(packet, manifest, response)
    return {"valid": True, "packet": args.packet_number}


def _cmd_expand(args: argparse.Namespace) -> dict[str, Any]:
    work_dir = args.work_dir.resolve()
    manifest = _read_json(args.manifest)
    packets_by_number = {}
    responses_by_number = {}
    for entry in manifest.get("packets", []):
        number = entry["packet"]
        packet_path = work_dir / "packets" / "mapping" / f"packet-{number:03d}.json"
        packets_by_number[number] = _read_json(packet_path)
        response_path = canonical_response_path(work_dir, number)
        if not response_path.is_file():
            raise PacketError(
                f"missing canonical mapping response for packet {number}: {response_path}"
            )
        responses_by_number[number] = _read_json(response_path)

    bundle = expand_responses(manifest, packets_by_number, responses_by_number)
    if args.base_bundle is not None and args.base_bundle.is_file():
        base = _read_json(args.base_bundle)
        if isinstance(base, dict) and isinstance(base.get("decisions"), list):
            bundle["decisions"] = base["decisions"] + bundle["decisions"]

    output_path = args.output.resolve()
    _write_json(output_path, bundle)
    return {"output": str(output_path), "decision_count": len(bundle["decisions"])}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build conform mapping-stage packets or expand compact worker responses."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser(
        "workspace-create", help="Create a marked run workspace"
    )
    create.add_argument("--fingerprint")
    create.add_argument("--workspace-root", type=Path)

    cleanup = commands.add_parser(
        "workspace-cleanup", help="Delete one exact marked temporary workspace"
    )
    cleanup.add_argument("--work-dir", type=Path, required=True)

    build = commands.add_parser(
        "build", help="Build mapping packets and a private manifest"
    )
    build.add_argument("--stage", choices=("mapping",), required=True)
    build.add_argument("--work-dir", type=Path, required=True)
    build.add_argument("--source-ledger", type=Path, required=True)
    build.add_argument("--core-ledger", type=Path, required=True)
    build.add_argument("--selected-text", type=Path)
    build.add_argument(
        "--mode",
        choices=("conform_selected_text", "precedent_leakage_check"),
        default="conform_selected_text",
    )
    build.add_argument("--target-items-per-packet", type=int, default=6)

    dispatch = commands.add_parser(
        "render-dispatch", help="Render the standardized generic-worker task"
    )
    dispatch.add_argument("--stage", choices=("mapping",), required=True)
    dispatch.add_argument("--work-dir", type=Path, required=True)
    dispatch.add_argument("--packet", type=Path, required=True)

    validate = commands.add_parser(
        "validate-response", help="Validate one compact worker response"
    )
    validate.add_argument("--stage", choices=("mapping",), required=True)
    validate.add_argument("--work-dir", type=Path, required=True)
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--packet-number", type=int, required=True)
    validate.add_argument("--response", type=Path, required=True)

    expand = commands.add_parser(
        "expand", help="Expand validated responses into a mapping bundle"
    )
    expand.add_argument("--stage", choices=("mapping",), required=True)
    expand.add_argument("--work-dir", type=Path, required=True)
    expand.add_argument("--manifest", type=Path, required=True)
    expand.add_argument("--output", type=Path, required=True)
    expand.add_argument("--base-bundle", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "workspace-create": _cmd_workspace_create,
        "workspace-cleanup": _cmd_workspace_cleanup,
        "build": _cmd_build,
        "render-dispatch": _cmd_render_dispatch,
        "validate-response": _cmd_validate_response,
        "expand": _cmd_expand,
    }
    try:
        result = handlers[args.command](args)
    except (PacketError, WorkspaceError) as exc:
        print(
            json.dumps(
                {"status": "failed", "error": str(exc)}, indent=2, sort_keys=True
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
