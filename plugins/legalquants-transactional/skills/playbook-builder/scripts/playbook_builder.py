#!/usr/bin/env python3
"""Deterministic command-line helpers for playbook-builder."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shared.playbook_runtime import (
    PlaybookError,
    build_receipt,
    build_source_manifest,
    import_playbook_table,
    load_json,
    register_playbook,
    render_playbook_html,
    render_playbook_markdown,
    seal_playbook,
    validate_playbook,
    write_json_atomic,
    write_text_atomic,
)


def _role_map(values: list[str]) -> dict[str, str]:
    roles: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise PlaybookError("--role must use FILE=ROLE")
        name, role = value.split("=", 1)
        roles[name] = role
    return roles


def _manifest(args: argparse.Namespace) -> int:
    manifest = build_source_manifest(
        [Path(source) for source in args.sources],
        Path(args.boundary),
        _role_map(args.role),
        max_sources=args.max_sources,
    )
    write_json_atomic(Path(args.out), manifest)
    print(f"Wrote {args.out} with {len(manifest['documents'])} documents")
    return 0


def _validate(args: argparse.Namespace) -> int:
    errors = validate_playbook(load_json(Path(args.playbook)))
    print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    return 1 if errors else 0


def _receipt(args: argparse.Namespace) -> int:
    playbook_path = Path(args.playbook)
    playbook = load_json(playbook_path)
    receipt = build_receipt(
        playbook,
        load_json(Path(args.manifest)),
    )
    write_json_atomic(Path(args.out), receipt)
    print(json.dumps(receipt, indent=2))
    if not receipt["validationErrors"] and playbook.get("status") == "approved":
        package_dir = playbook_path.parent
        try:
            register_playbook(playbook, package_dir)
            print(
                f"Registered playbook {playbook.get('playbookId')} in playbook-registry.json"
            )
        except Exception as exc:
            print(f"Warning: could not register playbook: {exc}", file=sys.stderr)
    return 1 if receipt["validationErrors"] else 0


def _register(args: argparse.Namespace) -> int:
    playbook_path = Path(args.playbook)
    package_path = (
        Path(args.package_path) if args.package_path else playbook_path.parent
    )
    registry_path = Path(args.registry) if args.registry else None
    playbook = load_json(playbook_path)
    register_playbook(playbook, package_path, registry_path)
    print(f"Registered {playbook.get('playbookId')} (v{playbook.get('version')})")
    return 0


def _render(args: argparse.Namespace) -> int:
    rendered = render_playbook_html(load_json(Path(args.playbook)))
    write_text_atomic(Path(args.out), rendered)
    print(f"Wrote {args.out}")
    return 0


def _render_md(args: argparse.Namespace) -> int:
    manifest = load_json(Path(args.manifest)) if args.manifest else None
    rendered = render_playbook_markdown(load_json(Path(args.playbook)), manifest)
    write_text_atomic(Path(args.out), rendered)
    print(f"Wrote {args.out}")
    return 0


def _seal(args: argparse.Namespace) -> int:
    playbook_path = Path(args.playbook)
    playbook = load_json(playbook_path)
    manifest = load_json(Path(args.manifest))
    package_path = (
        Path(args.package_path) if args.package_path else playbook_path.parent
    )
    registry_path = Path(args.registry) if args.registry else None

    result = seal_playbook(
        playbook,
        manifest,
        version=args.version,
        package_path=package_path,
        registry_path=registry_path,
    )

    out_playbook = Path(args.out_playbook) if args.out_playbook else playbook_path
    write_json_atomic(out_playbook, result["playbook"])
    print(f"Wrote sealed playbook to {out_playbook}")

    if args.out_receipt:
        write_json_atomic(Path(args.out_receipt), result["receipt"])
        print(f"Wrote build receipt to {args.out_receipt}")

    if args.out_markdown:
        write_text_atomic(Path(args.out_markdown), result["markdown"])
        print(f"Wrote markdown to {args.out_markdown}")

    print(
        f"Sealed {result['playbook'].get('playbookId')} (v{result['playbook'].get('version')}) successfully."
    )
    return 0


def _import_playbook(args: argparse.Namespace) -> int:
    registry_path = Path(args.registry) if args.registry else None
    result = import_playbook_table(
        source_path=args.table,
        title=args.title,
        playbook_id=args.playbook_id,
        perspective=args.perspective,
        family=args.family,
        governing_law=args.governing_law,
        version=args.version,
        out_dir=args.out_dir,
        approve_note=args.approve_all,
        seal=args.seal,
        registry_path=registry_path,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "playbookId": result["playbookId"],
                "version": result["version"],
                "issuesCount": result["issuesCount"],
                "rowsSkipped": result["rowsSkipped"],
                "columnMap": result["columnMap"],
                "packageDir": result["packageDir"],
                "sealed": result["sealed"],
            },
            indent=2,
        )
    )
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Hash, inventory and validate Playbook Engine build artifacts"
    )
    commands = root.add_subparsers(dest="command", required=True)

    import_cmd = commands.add_parser(
        "import-playbook",
        help="Import a playbook from a Word (.docx), Excel (.xlsx), or CSV table",
    )
    import_cmd.add_argument("table", help="Path to .docx, .xlsx, or .csv table file")
    import_cmd.add_argument("--title", required=True, help="Playbook title")
    import_cmd.add_argument(
        "--playbook-id", required=True, help="Playbook identifier (slug)"
    )
    import_cmd.add_argument(
        "--perspective",
        required=True,
        help="Represented party the table is written for (e.g. supplier, customer)",
    )
    import_cmd.add_argument(
        "--family",
        required=True,
        help="Agreement family the table covers (e.g. MSA, SaaS, NDA)",
    )
    import_cmd.add_argument(
        "--governing-law",
        default=None,
        help="Governing law the table assumes, if the lawyer states one",
    )
    import_cmd.add_argument(
        "--version", default="1.0.0", help="Playbook version (default: 1.0.0)"
    )
    import_cmd.add_argument(
        "--out-dir", help="Directory to save imported playbook package"
    )
    import_cmd.add_argument(
        "--approve-all",
        metavar="NOTE",
        help=(
            "Mark every imported row approved, recording the lawyer's confirmation "
            "that the table is approved firm policy. Without it rows are imported "
            "as candidates in a draft playbook"
        ),
    )
    import_cmd.add_argument(
        "--seal",
        action="store_true",
        help="Seal and register the imported playbook (requires --approve-all)",
    )
    import_cmd.add_argument("--registry", help="Path to playbook-registry.json")
    import_cmd.set_defaults(handler=_import_playbook)

    manifest = commands.add_parser("manifest", help="Create a frozen source manifest")
    manifest.add_argument("sources", nargs="+")
    manifest.add_argument("--boundary", required=True)
    manifest.add_argument("--role", action="append", default=[], metavar="FILE=ROLE")
    manifest.add_argument(
        "--max-sources",
        type=int,
        default=5,
        help="Maximum allowed source files (default: 5)",
    )
    manifest.add_argument("--out", required=True)
    manifest.set_defaults(handler=_manifest)

    validate = commands.add_parser("validate", help="Validate playbook invariants")
    validate.add_argument("playbook")
    validate.set_defaults(handler=_validate)

    receipt = commands.add_parser(
        "receipt", help="Create a deterministic build receipt"
    )
    receipt.add_argument("manifest")
    receipt.add_argument("playbook")
    receipt.add_argument("--out", required=True)
    receipt.set_defaults(handler=_receipt)

    seal_cmd = commands.add_parser(
        "seal", help="Validate, seal, and register an approved playbook package"
    )
    seal_cmd.add_argument("playbook", help="Path to candidate playbook.json")
    seal_cmd.add_argument(
        "--manifest", required=True, help="Path to source-manifest.json"
    )
    seal_cmd.add_argument("--version", help="Optional version to seal (e.g. 1.0.0)")
    seal_cmd.add_argument("--package-path", help="Path to playbook package directory")
    seal_cmd.add_argument("--registry", help="Path to playbook-registry.json")
    seal_cmd.add_argument("--out-playbook", help="Path to write sealed playbook.json")
    seal_cmd.add_argument("--out-receipt", help="Path to write build-receipt.json")
    seal_cmd.add_argument("--out-markdown", help="Path to write playbook.md")
    seal_cmd.set_defaults(handler=_seal)

    register_cmd = commands.add_parser(
        "register", help="Register playbook in the playbook registry"
    )
    register_cmd.add_argument("playbook", help="Path to playbook.json")
    register_cmd.add_argument(
        "--package-path", help="Path to playbook package directory"
    )
    register_cmd.add_argument("--registry", help="Path to playbook-registry.json")
    register_cmd.set_defaults(handler=_register)

    render = commands.add_parser(
        "render", help="Render a standalone local HTML playbook"
    )
    render.add_argument("playbook")
    render.add_argument("--out", required=True)
    render.set_defaults(handler=_render)

    render_md = commands.add_parser(
        "render-md", help="Render a standalone local Markdown playbook"
    )
    render_md.add_argument("playbook")
    render_md.add_argument(
        "--manifest", help="Optional path to source-manifest.json for file names"
    )
    render_md.add_argument("--out", required=True)
    render_md.set_defaults(handler=_render_md)
    return root


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        return args.handler(args)
    except (OSError, json.JSONDecodeError, PlaybookError) as exc:
        print(f"playbook-builder: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
