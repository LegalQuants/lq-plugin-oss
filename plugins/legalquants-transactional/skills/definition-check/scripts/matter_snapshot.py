#!/usr/bin/env python3
"""Create, validate, and project Definition Check matter snapshots."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from _runtime_gate import require_supported_python

require_supported_python()

from definition_check.matter import (
    MatterSnapshotError,
    assemble_legacy_ledgers,
    compare_versions,
    derive_snapshot,
    import_legacy_ledger,
    project_view,
    read_snapshot,
    render_lawyer_matter_html,
    review_companions,
    write_snapshot,
)


def _read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MatterSnapshotError(f"cannot read JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise MatterSnapshotError(f"JSON input must be an object: {path}")
    return value


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(value, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    importer = commands.add_parser("import-legacy")
    importer.add_argument("ledger", type=Path)
    importer.add_argument("output", type=Path)
    importer.add_argument("--matter-id", required=True)
    importer.add_argument("--document-id", required=True)
    importer.add_argument("--version-id", required=True)
    importer.add_argument("--snapshot-id", required=True)
    importer.add_argument("--created-at", required=True)
    importer.add_argument("--matter-name")
    importer.add_argument("--parent-snapshot-sha256")

    validator = commands.add_parser("validate")
    validator.add_argument("snapshot", type=Path)
    validator.add_argument("--expected-snapshot-sha256")
    validator.add_argument("--expected-parent-snapshot-sha256")

    projector = commands.add_parser("project")
    projector.add_argument("snapshot", type=Path)
    projector.add_argument("output", type=Path)
    projector.add_argument(
        "--view-type",
        required=True,
        choices=[
            "legacy_single_document",
            "defined_term_registry",
            "usage_index",
            "findings",
            "lawyer_report",
            "agent_review",
            "developer_audit",
            "version_comparison",
            "companion_review",
        ],
    )
    projector.add_argument("--document-id")
    projector.add_argument("--version-id")
    projector.add_argument("--authorize-provenance", action="store_true")

    renderer = commands.add_parser("render-lawyer")
    renderer.add_argument("snapshot", type=Path)
    renderer.add_argument("output", type=Path)

    assembler = commands.add_parser("assemble")
    assembler.add_argument("plan", type=Path)
    assembler.add_argument("output", type=Path)

    comparer = commands.add_parser("compare")
    comparer.add_argument("snapshot", type=Path)
    comparer.add_argument("mappings", type=Path)
    comparer.add_argument("output", type=Path)
    comparer.add_argument("--prior-version-id", required=True)
    comparer.add_argument("--current-version-id", required=True)
    comparer.add_argument("--snapshot-id", required=True)
    comparer.add_argument("--created-at", required=True)

    companion = commands.add_parser("review-companions")
    companion.add_argument("snapshot", type=Path)
    companion.add_argument("conclusions", type=Path)
    companion.add_argument("output", type=Path)
    companion.add_argument("--snapshot-id", required=True)
    companion.add_argument("--created-at", required=True)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "import-legacy":
            manifest, components = import_legacy_ledger(
                _read_object(args.ledger),
                matter_id=args.matter_id,
                document_id=args.document_id,
                version_id=args.version_id,
                snapshot_id=args.snapshot_id,
                created_at=args.created_at,
                matter_display_name=args.matter_name,
                parent_snapshot_sha256=args.parent_snapshot_sha256,
            )
            digest = write_snapshot(
                args.output,
                manifest,
                components,
                expected_parent_snapshot_sha256=args.parent_snapshot_sha256,
            )
            print(
                json.dumps(
                    {"status": "complete", "snapshot_sha256": digest}, sort_keys=True
                )
            )
        elif args.command == "validate":
            value = read_snapshot(
                args.snapshot,
                expected_snapshot_sha256=args.expected_snapshot_sha256,
                expected_parent_snapshot_sha256=args.expected_parent_snapshot_sha256,
            )
            print(
                json.dumps(
                    {
                        "status": "valid",
                        "matter_id": value["manifest"]["matter"]["matter_id"],
                        "snapshot_sha256": value["snapshot_sha256"],
                    },
                    sort_keys=True,
                )
            )
        elif args.command == "project":
            snapshot = read_snapshot(args.snapshot)
            value = project_view(
                snapshot,
                view_type=args.view_type,
                document_id=args.document_id,
                version_id=args.version_id,
                authorized_provenance=args.authorize_provenance,
            )
            _atomic_text(
                args.output,
                json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            )
        elif args.command == "render-lawyer":
            _atomic_text(
                args.output, render_lawyer_matter_html(read_snapshot(args.snapshot))
            )
        elif args.command == "assemble":
            plan = _read_object(args.plan)
            entries = plan.get("entries")
            if not isinstance(entries, list):
                raise MatterSnapshotError("assembly plan entries must be an array")
            hydrated = []
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(
                    entry.get("ledger_path"), str
                ):
                    raise MatterSnapshotError("assembly entry requires ledger_path")
                item = dict(entry)
                ledger_path = Path(item.pop("ledger_path"))
                if not ledger_path.is_absolute():
                    ledger_path = args.plan.parent / ledger_path
                item["ledger"] = _read_object(ledger_path)
                hydrated.append(item)
            manifest, components = assemble_legacy_ledgers(
                hydrated,
                matter=plan.get("matter", {}),
                snapshot=plan.get("snapshot", {}),
                scope=plan.get("scope", {}),
                document_relationships=plan.get("document_relationships", []),
            )
            digest = write_snapshot(
                args.output,
                manifest,
                components,
                expected_parent_snapshot_sha256=manifest["snapshot"].get(
                    "parent_snapshot_sha256"
                ),
            )
            print(
                json.dumps(
                    {"status": "complete", "snapshot_sha256": digest}, sort_keys=True
                )
            )
        elif args.command == "compare":
            parent = read_snapshot(args.snapshot)
            mappings = json.loads(args.mappings.read_text(encoding="utf-8"))
            if not isinstance(mappings, list):
                raise MatterSnapshotError("comparison mappings must be an array")
            comparison = compare_versions(
                parent,
                prior_version_id=args.prior_version_id,
                current_version_id=args.current_version_id,
                reviewed_mappings=mappings,
            )
            manifest, components = derive_snapshot(
                parent,
                snapshot_id=args.snapshot_id,
                created_at=args.created_at,
                version_comparison=comparison,
            )
            digest = write_snapshot(
                args.output,
                manifest,
                components,
                expected_parent_snapshot_sha256=parent["snapshot_sha256"],
            )
            print(
                json.dumps(
                    {"status": "complete", "snapshot_sha256": digest}, sort_keys=True
                )
            )
        elif args.command == "review-companions":
            parent = read_snapshot(args.snapshot)
            conclusions = json.loads(args.conclusions.read_text(encoding="utf-8"))
            if not isinstance(conclusions, list):
                raise MatterSnapshotError("companion conclusions must be an array")
            review = review_companions(parent, conclusions=conclusions)
            manifest, components = derive_snapshot(
                parent,
                snapshot_id=args.snapshot_id,
                created_at=args.created_at,
                companion_review=review,
            )
            digest = write_snapshot(
                args.output,
                manifest,
                components,
                expected_parent_snapshot_sha256=parent["snapshot_sha256"],
            )
            print(
                json.dumps(
                    {"status": "complete", "snapshot_sha256": digest}, sort_keys=True
                )
            )
    except MatterSnapshotError as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, sort_keys=True))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
