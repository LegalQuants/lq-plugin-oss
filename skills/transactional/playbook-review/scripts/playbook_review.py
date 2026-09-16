#!/usr/bin/env python3
"""Deterministic command-line helpers for playbook-review."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shared.playbook_runtime import (
    PlaybookError,
    adapt_drafting_to_term_map,
    build_coverage_receipt,
    build_markup_segments,
    build_review_receipt,
    build_source_manifest,
    build_term_map_skeleton,
    compile_effective_stance,
    extract_sample_text_from_file,
    format_playbook_picker,
    format_playbook_suggestion,
    list_registered_playbooks,
    load_json,
    match_playbook_candidate,
    populate_issues_markup,
    render_issues_docx,
    render_issues_html,
    run_review_pipeline,
    setup_review_pipeline,
    source_text_index,
    validate_issues_list,
    validate_term_map,
    write_json_atomic,
    write_text_atomic,
)


def _manifest(args: argparse.Namespace) -> int:
    sources = [Path(source) for source in args.sources]
    roles = {source.name: "contract-under-review" for source in sources}
    manifest = build_source_manifest(
        sources, Path(args.boundary), roles, max_sources=args.max_sources
    )
    write_json_atomic(Path(args.out), manifest)
    print(f"Wrote {args.out} with {len(manifest['documents'])} documents")
    return 0


def _compile(args: argparse.Namespace) -> int:
    stance = compile_effective_stance(
        load_json(Path(args.playbook)),
        load_json(Path(args.activation)),
    )
    write_json_atomic(Path(args.out), stance)
    print(
        json.dumps(
            {"status": stance["status"], "conflicts": stance["conflicts"]}, indent=2
        )
    )
    return 1 if stance["status"] == "blocked" else 0


def _markup(args: argparse.Namespace) -> int:
    original = Path(args.original).read_text(encoding="utf-8")
    proposed = Path(args.proposed).read_text(encoding="utf-8")
    segments = build_markup_segments(original, proposed)
    write_json_atomic(Path(args.out), {"markupSegments": segments})
    return 0


def _term_map(args: argparse.Namespace) -> int:
    term_map = build_term_map_skeleton(
        load_json(Path(args.playbook_manifest)),
        load_json(Path(args.contract_manifest)),
        load_json(Path(args.playbook)),
        args.run_id,
    )
    write_json_atomic(Path(args.out), term_map)
    counts: dict[str, int] = {}
    for entry in term_map["entries"]:
        relation = entry["relation"]
        counts[relation] = counts.get(relation, 0) + 1
    print(
        json.dumps({"entries": len(term_map["entries"]), "relations": counts}, indent=2)
    )
    return 0


def _validate_term_map(args: argparse.Namespace) -> int:
    errors = validate_term_map(load_json(Path(args.term_map)))
    print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    return 1 if errors else 0


def _adapt_drafting(args: argparse.Namespace) -> int:
    proposed = Path(args.proposed).read_text(encoding="utf-8")
    result = adapt_drafting_to_term_map(
        proposed,
        load_json(Path(args.term_map)),
    )
    write_json_atomic(Path(args.out), result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "substitutions": len(result["substitutions"]),
                "definitionInsertions": len(result["definitionInsertions"]),
                "hardStops": len(result["hardStops"]),
            },
            indent=2,
        )
    )
    return 1 if result["status"] == "blocked" else 0


def _validate_issues(args: argparse.Namespace) -> int:
    manifest = load_json(Path(args.manifest)) if args.manifest else None
    index = source_text_index(manifest) if manifest else None
    manifest_sha256 = manifest.get("manifestSha256") if manifest else None
    errors = validate_issues_list(
        load_json(Path(args.issues)),
        index,
        manifest_sha256,
    )
    print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    return 1 if errors else 0


def _render(args: argparse.Namespace) -> int:
    rendered = render_issues_html(load_json(Path(args.issues)))
    write_text_atomic(Path(args.out), rendered)
    print(f"Wrote {args.out}")
    return 0


def _coverage(args: argparse.Namespace) -> int:
    receipt = build_coverage_receipt(load_json(Path(args.counts)))
    write_json_atomic(Path(args.out), receipt)
    print(json.dumps(receipt, indent=2))
    return 1 if not receipt["reconciled"] else 0


def _markup_issues(args: argparse.Namespace) -> int:
    issues = load_json(Path(args.issues))
    populated = populate_issues_markup(issues)
    out_path = Path(args.out) if args.out else Path(args.issues)
    write_json_atomic(out_path, populated)
    print(f"Populated markup segments in {out_path}")
    return 0


def _review_receipt(args: argparse.Namespace) -> int:
    issues = load_json(Path(args.issues))
    coverage = load_json(Path(args.coverage)) if args.coverage else None
    receipt = build_review_receipt(issues, coverage)
    write_json_atomic(Path(args.out), receipt)
    print(json.dumps(receipt, indent=2))
    return 0


def _export_docx(args: argparse.Namespace) -> int:
    issues = load_json(Path(args.issues))
    playbook = load_json(Path(args.playbook)) if args.playbook else None
    render_issues_docx(
        issues,
        Path(args.out),
        playbook=playbook,
        contract_name=args.contract_name,
        audience=args.audience,
    )
    print(f"Wrote {args.out} ({args.audience} cut)")
    return 0


def _discover_playbooks(args: argparse.Namespace) -> int:
    registry_path = Path(args.registry) if args.registry else None
    search_dir = Path(args.search_dir) if args.search_dir else None
    playbooks = list_registered_playbooks(
        registry_path=registry_path, search_dir=search_dir
    )
    if not playbooks:
        if args.json:
            print(json.dumps({"playbooks": [], "suggestion": None}))
        else:
            print("No approved playbooks found in registry.")
        return 1

    suggestion = None
    if getattr(args, "contract", None):
        contract_path = Path(args.contract)
        sample = extract_sample_text_from_file(contract_path)
        suggestion = match_playbook_candidate(
            playbooks, source_names=[contract_path], sample_text=sample
        )
    elif getattr(args, "manifest", None):
        try:
            manifest_data = load_json(Path(args.manifest))
            docs = manifest_data.get("documents", [])
            source_names = [
                doc.get("fileName", "") for doc in docs if isinstance(doc, dict)
            ]
            sample_texts = []
            for doc in docs:
                if isinstance(doc, dict):
                    elements = doc.get("elements", [])
                    for el in elements[:6]:
                        if isinstance(el, dict):
                            sample_texts.append(el.get("sourceText", ""))
            sample = " ".join(sample_texts)
            suggestion = match_playbook_candidate(
                playbooks, source_names=source_names, sample_text=sample
            )
        except Exception:
            pass

    if args.json:
        print(
            json.dumps(
                {
                    "playbooks": playbooks,
                    "suggestion": suggestion,
                },
                indent=2,
            )
        )
    else:
        if suggestion:
            print(format_playbook_suggestion(suggestion))
        else:
            print(format_playbook_picker(playbooks))
    return 0


def _setup_review(args: argparse.Namespace) -> int:
    result = setup_review_pipeline(
        sources=args.sources,
        boundary=args.boundary,
        playbook_path=args.playbook,
        playbook_manifest_path=args.playbook_manifest,
        activation_path=args.activation,
        confirmation=args.confirm,
        selected_lenses=args.lens,
        run_id=args.run_id,
        out_dir=args.out_dir,
        contract_name=args.contract_name,
    )
    print(json.dumps(result, indent=2))
    # 2: Gate 1 still needs the lawyer; 1: the stance is blocked by a conflict.
    if result["status"] == "awaiting-gate-1":
        return 2
    return 1 if result["status"] == "blocked" else 0


def _run_all(args: argparse.Namespace) -> int:
    result = run_review_pipeline(
        issues_path=args.issues,
        manifest_path=args.manifest,
        stance_path=args.stance,
        playbook_path=args.playbook,
        term_map_path=args.term_map,
        out_dir=args.out_dir,
        contract_name=args.contract_name,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["reconciled"] else 1


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Compile stances, verify issues and render Playbook Engine reviews"
    )
    commands = root.add_subparsers(dest="command", required=True)

    setup_cmd = commands.add_parser(
        "setup-review",
        help="Prepare manifest, stance, and term map for a review run",
    )
    setup_cmd.add_argument("sources", nargs="+", help="Contract files to review")
    setup_cmd.add_argument("--boundary", required=True, help="Input boundary directory")
    setup_cmd.add_argument("--playbook", required=True, help="Path to playbook.json")
    setup_cmd.add_argument(
        "--playbook-manifest",
        help="Optional path to playbook's source-manifest.json",
    )
    setup_cmd.add_argument(
        "--activation", help="Path to a lawyer-confirmed matter-lens-activation.json"
    )
    setup_cmd.add_argument(
        "--confirm",
        help=(
            "The lawyer's own words settling Gate 1 (e.g. 'confirm Standard "
            "Baseline only'); quoted into confirmationNote. Without --confirm or "
            "--activation the command stops after the manifest and reports "
            "awaiting-gate-1"
        ),
    )
    setup_cmd.add_argument(
        "--lens",
        action="append",
        default=[],
        help="Matter Lens ID the lawyer asked to activate (needs --confirm)",
    )
    setup_cmd.add_argument(
        "--run-id",
        default="review-run",
        help="Run identifier (default: review-run)",
    )
    setup_cmd.add_argument(
        "--out-dir", required=True, help="Output directory for review run"
    )
    setup_cmd.add_argument("--contract-name", help="Contract or counterparty name")
    setup_cmd.set_defaults(handler=_setup_review)

    run_all_cmd = commands.add_parser(
        "run-all",
        help="Execute full review verification, coverage reconciliation, receipts, and dual Word/HTML exports",
        allow_abbrev=False,
    )
    run_all_cmd.add_argument("issues", help="Path to issues-list.json")
    run_all_cmd.add_argument(
        "--manifest", help="Optional path to contract source-manifest.json"
    )
    run_all_cmd.add_argument("--stance", help="Optional path to effective-stance.json")
    run_all_cmd.add_argument("--playbook", help="Optional path to playbook.json")
    run_all_cmd.add_argument(
        "--term-map", help="Optional path to term-map.json (defaults to run folder)"
    )
    run_all_cmd.add_argument(
        "--out-dir",
        help="Directory to write all output deliverables (defaults to issues directory)",
    )
    run_all_cmd.add_argument(
        "--contract-name",
        help="Contract or counterparty name for report headers",
    )
    run_all_cmd.set_defaults(handler=_run_all)

    manifest = commands.add_parser(
        "manifest", help="Create a contract-package manifest"
    )
    manifest.add_argument("sources", nargs="+")
    manifest.add_argument("--boundary", required=True)
    manifest.add_argument(
        "--max-sources",
        type=int,
        default=25,
        help="Maximum allowed source files (default: 25)",
    )
    manifest.add_argument("--out", required=True)
    manifest.set_defaults(handler=_manifest)

    compile_command = commands.add_parser(
        "compile-stance", help="Compile only lawyer-confirmed Matter Lenses"
    )
    compile_command.add_argument("playbook")
    compile_command.add_argument("activation")
    compile_command.add_argument("--out", required=True)
    compile_command.set_defaults(handler=_compile)

    term_map = commands.add_parser(
        "term-map", help="Build a deterministic defined-term mapping skeleton"
    )
    term_map.add_argument("playbook_manifest")
    term_map.add_argument("contract_manifest")
    term_map.add_argument("playbook")
    term_map.add_argument("--run-id", required=True)
    term_map.add_argument("--out", required=True)
    term_map.set_defaults(handler=_term_map)

    validate_term_map_command = commands.add_parser(
        "validate-term-map", help="Validate term mapping controls and citations"
    )
    validate_term_map_command.add_argument("term_map")
    validate_term_map_command.set_defaults(handler=_validate_term_map)

    adapt = commands.add_parser(
        "adapt-drafting", help="Adapt approved wording through a validated term map"
    )
    adapt.add_argument("proposed", help="UTF-8 file containing approved house wording")
    adapt.add_argument("term_map")
    adapt.add_argument("--out", required=True)
    adapt.set_defaults(handler=_adapt_drafting)

    markup = commands.add_parser("markup", help="Create reconstructable inline markup")
    markup.add_argument("original", help="UTF-8 file containing exact source text")
    markup.add_argument("proposed", help="UTF-8 file containing clean proposed text")
    markup.add_argument("--out", required=True)
    markup.set_defaults(handler=_markup)

    markup_issues = commands.add_parser(
        "markup-issues",
        help="Populate inline diff markup segments across an issues list",
    )
    markup_issues.add_argument("issues")
    markup_issues.add_argument("--out")
    markup_issues.set_defaults(handler=_markup_issues)

    validate = commands.add_parser("validate-issues", help="Validate an issues list")
    validate.add_argument("issues")
    validate.add_argument("--manifest")
    validate.set_defaults(handler=_validate_issues)

    render = commands.add_parser("render-issues", help="Render local standalone HTML")
    render.add_argument("issues")
    render.add_argument("--out", required=True)
    render.set_defaults(handler=_render)

    coverage = commands.add_parser("coverage", help="Reconcile coverage counts")
    coverage.add_argument("counts")
    coverage.add_argument("--out", required=True)
    coverage.set_defaults(handler=_coverage)

    receipt_cmd = commands.add_parser(
        "review-receipt",
        help="Generate a deterministic review receipt summarizing an issues list",
    )
    receipt_cmd.add_argument("issues")
    receipt_cmd.add_argument("--coverage", help="Optional coverage receipt JSON")
    receipt_cmd.add_argument("--out", required=True)
    receipt_cmd.set_defaults(handler=_review_receipt)

    export_docx_cmd = commands.add_parser(
        "export-docx",
        help="Export issues list to firm-neutral landscape Word (.docx)",
        # No prefix matching: `--contract` is a file path on discover-playbooks
        # and must not silently resolve to `--contract-name` here.
        allow_abbrev=False,
    )
    export_docx_cmd.add_argument("issues", help="Path to issues-list.json")
    export_docx_cmd.add_argument(
        "--playbook", help="Optional path to playbook.json for metadata"
    )
    export_docx_cmd.add_argument(
        "--contract-name",
        dest="contract_name",
        help="Optional contract or counterparty name for the title block",
    )
    export_docx_cmd.add_argument(
        "--audience",
        choices=("internal", "external"),
        default="internal",
        help=(
            "internal (default): privileged matrix with risk guidance for the "
            "represented party; external: counterparty-safe cut with the "
            "internal guidance, playbook references and risk ratings removed"
        ),
    )
    export_docx_cmd.add_argument("--out", required=True, help="Output .docx file path")
    export_docx_cmd.set_defaults(handler=_export_docx)

    discover_cmd = commands.add_parser(
        "discover-playbooks",
        help="Discover and pick registered playbooks from playbook-registry.json",
    )
    discover_cmd.add_argument(
        "--registry", help="Explicit path to playbook-registry.json"
    )
    discover_cmd.add_argument("--search-dir", help="Directory to search from")
    discover_cmd.add_argument(
        "--contract",
        help="Optional contract file path for first-guess playbook suggestion",
    )
    discover_cmd.add_argument(
        "--manifest",
        help="Optional source-manifest.json path for first-guess suggestion",
    )
    discover_cmd.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted picker",
    )
    discover_cmd.set_defaults(handler=_discover_playbooks)
    return root


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        return args.handler(args)
    except (OSError, json.JSONDecodeError, PlaybookError) as exc:
        print(f"playbook-review: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
