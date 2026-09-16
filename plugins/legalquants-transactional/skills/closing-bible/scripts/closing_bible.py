#!/usr/bin/env python3
"""closing-bible — deterministic census, family grouping and reconciliation.

    closing_bible.py census    --root <folder> --out source-manifest.json [--extractor auto|stdlib]
    closing_bible.py families  --manifest source-manifest.json --out families.json
                               [--sigpack sigpack.ledger.json] [--checklist checklist.json]
                               [--root <folder>]
    closing_bible.py reconcile --manifest source-manifest.json --families families.json
                               --inspection inspection.json --out-dir <dir>
                               [--checklist checklist.json] [--index closing-index.json]
                               [--sigpack sigpack.ledger.json] [--as-of YYYY-MM-DD]
                               [--root <folder>]
    closing_bible.py status    --out-dir <dir>
    closing_bible.py plan      --out-dir <audit dir> --root <folder> --out build-plan.json
                               [--include-qualified] [--volume-pages N] [--prior <closing-bible-vNNN>]
                               [--package-parent <dir>]
    closing_bible.py build     --plan build-plan.json --out-dir <audit dir> --root <folder>
                               --package-parent <dir beside the folder> [--as-of YYYY-MM-DD]
    closing_bible.py update    --prior <closing-bible-vNNN> --plan build-plan.json
                               --out-dir <audit dir> --root <folder> --package-parent <dir>
                               [--as-of YYYY-MM-DD]

Standard library only, Python 3.12 or newer. Poppler is probed by the census
when present and never required. Sources are read, never written: every
output lands inside --out-dir (or beside --out) and the script refuses any
path that resolves elsewhere unless --allow-outside is passed for that run.
--root on families/reconcile does one thing: refuse an --out/--out-dir that
resolves inside the closing folder (rule 6). Writes are atomic (temp file,
then rename). Exit codes: 0 ok, 2 refused or invalid input, 1 unexpected error.

plan/build/update (wave 2, references/assembly-rules.md): the package is a
new closing-bible-vNNN folder under --package-parent (default: beside the
closing folder), written whole or not at all. pypdf, soffice and Poppler are
probed at run time; each absence is named in the receipt, never bypassed.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from _runtime_gate import require_supported_python

require_supported_python()

from closing_bible import assemble  # noqa: E402
from closing_bible.families import (  # noqa: E402
    build_families,
    check_families,
    check_manifest,
)
from closing_bible.models import RECEIPT_STATUSES, Receipt  # noqa: E402
from closing_bible.reconcile import (  # noqa: E402
    UNREADABLE,
    readability_by_id,
    reconcile,
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REFUSED = 2

RECONCILE_OUTPUTS = (
    "closing-index.json",
    "selection-plan.json",
    "execution-overview.json",
    "closing-receipt.json",
    "exceptions.md",
)


class Refused(Exception):
    """A plain-language stop the lawyer can act on; exits 2."""


# ------------------------------------------------------------------ I/O


def _load_json(path: str, what: str) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        raise Refused(f"{what} not found: {path}")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Refused(f"{what} could not be read as JSON ({path}): {error}") from error
    if not isinstance(data, dict):
        raise Refused(f"{what} must be a JSON object: {path}")
    return data


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _write_atomic(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


def contain_writes(container: Path, targets: list[Path], allow_outside: bool) -> None:
    """Refuse any output path that resolves outside the container. Inputs may
    be read from anywhere; nothing is written anywhere else unless the user
    says --allow-outside on this run."""

    if allow_outside:
        return
    root = container.resolve()
    for target in targets:
        resolved = target.resolve()
        if not resolved.is_relative_to(root):
            raise Refused(
                f"refused: {target} resolves to {resolved}, outside {root}. Every output "
                "stays inside the output folder; pass --allow-outside if you really mean it."
            )


def keep_out_of_root(
    root_arg: str | None, targets: list[Path], allow_outside: bool, flag: str
) -> None:
    """Rule 6: nothing is written under the closing folder. `--root` on
    families/reconcile exists only for this check (README "Fixed surface")."""

    if root_arg is None or allow_outside:
        return
    root = Path(root_arg)
    if not root.is_dir():
        raise Refused(f"--root is not a folder: {root_arg}")
    for target in targets:
        if target.resolve().is_relative_to(root.resolve()):
            raise Refused(
                f"refused: {flag} {target} lies inside the closing folder {root_arg}; "
                "write outputs beside the folder, not into it"
            )


# ------------------------------------------------------------ subcommands


def cmd_census(args: argparse.Namespace) -> int:
    # The census helper is a sibling module; resolved at run time so the other
    # subcommands work even where it is not shipped.
    try:
        build_manifest = importlib.import_module("closing_bible.census").build_manifest
    except (ImportError, AttributeError) as error:
        raise Refused(f"census helper unavailable: {error}") from error

    root = Path(args.root)
    if not root.is_dir():
        raise Refused(f"--root is not a folder: {args.root}")
    out = Path(args.out)
    contain_writes(out.parent, [out], args.allow_outside)
    if out.resolve().is_relative_to(root.resolve()):
        raise Refused(
            f"refused: --out {args.out} lies inside the source folder; write the manifest "
            "beside the folder, not into it"
        )
    manifest = build_manifest(root, extractor=args.extractor)
    _write_atomic(out, _dump(manifest))
    counts = manifest.get("counts", {})
    skipped = manifest.get("skipped", [])
    print(
        f"{out}: {counts.get('files', 0)} files · {counts.get('distinct', 0)} distinct · "
        f"{len(manifest.get('duplicate_groups', []))} duplicate group(s) · "
        f"{len(skipped)} skipped"
    )
    # Nothing is dropped silently: every entry not inventoried is named.
    for entry in skipped:
        print(f"skipped: {entry['path']} ({entry['reason']})")
    return EXIT_OK


def _sha256_of(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cmd_families(args: argparse.Namespace) -> int:
    manifest = _load_json(args.manifest, "manifest")
    sigpack = _load_json(args.sigpack, "sigpack ledger") if args.sigpack else None
    checklist = _load_json(args.checklist, "checklist") if args.checklist else None
    out = Path(args.out)
    contain_writes(out.parent, [out], args.allow_outside)
    keep_out_of_root(args.root, [out], args.allow_outside, "--out")
    families = build_families(
        manifest,
        sigpack=sigpack,
        checklist=checklist,
        checklist_sha256=_sha256_of(args.checklist) if args.checklist else None,
    )
    _write_atomic(out, _dump(families))
    counts = families["counts"]
    print(
        f"{out}: {counts['families']} family(ies) over "
        f"{counts['distinct_documents']} distinct document(s)"
    )
    return EXIT_OK


def cmd_reconcile(args: argparse.Namespace) -> int:
    manifest = _load_json(args.manifest, "manifest")
    families = _load_json(args.families, "families")
    inspection = _load_json(args.inspection, "inspection")
    checklist = _load_json(args.checklist, "checklist") if args.checklist else None
    index = _load_json(args.index, "index") if args.index else None
    sigpack = _load_json(args.sigpack, "sigpack ledger") if args.sigpack else None
    sigpack_path = Path(args.sigpack).resolve() if args.sigpack else None
    sigpack_dir = sigpack_path.parent if sigpack_path else None
    out_dir = Path(args.out_dir)
    targets = [out_dir / name for name in RECONCILE_OUTPUTS]
    contain_writes(out_dir, targets, args.allow_outside)
    keep_out_of_root(args.root, targets, args.allow_outside, "--out-dir")
    try:
        _dt.date.fromisoformat(args.as_of)
    except ValueError as error:
        raise Refused(
            f"--as-of {args.as_of!r} is not a real date; give it as YYYY-MM-DD"
        ) from error

    closing_index, selection_plan, execution_overview, receipt, exceptions_md = (
        reconcile(
            manifest,
            families,
            inspection,
            checklist=checklist,
            index=index,
            sigpack=sigpack,
            sigpack_dir=sigpack_dir,
            sigpack_path=sigpack_path,
            checklist_sha256=_sha256_of(args.checklist) if args.checklist else None,
            as_of=args.as_of,
        )
    )
    payloads = (
        _dump(closing_index),
        _dump(selection_plan),
        _dump(execution_overview),
        _dump(receipt),
        exceptions_md,
    )
    for target, payload in zip(targets, payloads, strict=True):
        _write_atomic(target, payload)
    print(_receipt_line(receipt))
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    """Print the receipt line — recomputed from closing-index.json (and the
    manifest and families beside it when present), never read off a receipt
    that could have been edited. A receipt on disk that says something else
    is refused."""

    out_dir = Path(args.out_dir)
    receipt = _load_json(str(out_dir / "closing-receipt.json"), "closing receipt")
    index = _load_json(str(out_dir / "closing-index.json"), "closing index")
    recomputed = _recompute_receipt(index, receipt, out_dir)
    disagreements = [
        f"{key}: receipt says {receipt.get(key)!r}, {source} gives {value!r}"
        for key, value, source in recomputed
        if receipt.get(key) != value
    ]
    if disagreements:
        raise Refused(
            "refused: closing-receipt.json does not match the outputs beside it "
            "(" + "; ".join(disagreements) + "); re-run reconcile"
        )
    print(_receipt_line(receipt))
    return EXIT_OK


def _recompute_receipt(
    index: dict[str, Any], receipt: dict[str, Any], out_dir: Path
) -> list[tuple[str, Any, str]]:
    """(field, value, where it came from) for every receipt field the other
    outputs determine: the index gives the counts by status, the corpus, the
    approval and the unexpected families; the manifest and families give the
    source counts. The outcome is derived by Receipt itself."""

    items = index.get("items")
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise Refused("closing-index.json: items must be a list of objects")
    by_status = {s: 0 for s in RECEIPT_STATUSES}
    for item in items:
        status = item.get("status")
        if status not in by_status:
            raise Refused(
                f"closing-index.json: {item.get('item_id')} has status {status!r}"
            )
        by_status[status] += 1
    unexpected = index.get("unexpected_families")
    out: list[tuple[str, Any, str]] = [
        ("corpus_id", index.get("corpus_id"), "closing-index.json"),
        ("index_approved", index.get("approved"), "closing-index.json"),
        ("expected_items", len(items), "closing-index.json"),
        ("by_status", by_status, "closing-index.json"),
        (
            "unexpected_families",
            len(unexpected) if isinstance(unexpected, list) else None,
            "closing-index.json",
        ),
    ]
    manifest_path = out_dir / "source-manifest.json"
    families_path = out_dir / "families.json"
    if manifest_path.is_file() and families_path.is_file():
        manifest = _load_json(str(manifest_path), "manifest")
        families = _load_json(str(families_path), "families")
        try:
            docs = check_manifest(manifest)
            ids = {d["id"] for d in docs}
            check_families(families, sorted(ids))
        except ValueError as error:
            raise Refused(f"outputs beside the receipt: {error}") from error
        worst = readability_by_id(manifest)
        skipped = manifest.get("skipped")
        out.append(
            (
                "sources",
                {
                    "files": len(docs),
                    "distinct": len(ids),
                    "in_families": int(families["counts"]["in_families"]),
                    "duplicates": len(docs) - len(ids),
                    "unreadable": sum(1 for i in ids if worst.get(i) in UNREADABLE),
                    "skipped": (
                        sum(1 for s in skipped if s.get("reason") != "hidden")
                        if isinstance(skipped, list)
                        else None
                    ),
                },
                "source-manifest.json and families.json",
            )
        )
    return out


def _receipt_line(receipt: dict[str, Any]) -> str:
    try:
        return Receipt(
            corpus_id=receipt["corpus_id"],
            mode=receipt["mode"],
            index_approved=receipt["index_approved"],
            expected_items=receipt["expected_items"],
            by_status=dict(receipt["by_status"]),
            unexpected_families=receipt["unexpected_families"],
            sources=dict(receipt["sources"]),
            inspection=dict(receipt["inspection"]),
            sigpack=dict(receipt["sigpack"]),
            as_of=receipt["as_of"],
            included_outputs=tuple(receipt.get("included_outputs") or ()),
            package=receipt.get("package"),
            schema_version=receipt.get("schema_version", "1.0.0"),
        ).line()
    except (KeyError, TypeError, ValueError) as error:
        raise Refused(
            f"closing-receipt.json does not balance or is malformed: {error}"
        ) from error


# ------------------------------------------------------------ wave 2: assembly


def _package_parent(args: argparse.Namespace) -> Path:
    """Default: beside the closing folder (assembly-rules.md 'The package')."""

    if args.package_parent:
        return Path(args.package_parent)
    return Path(args.root).resolve().parent


def cmd_plan(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if not root.is_dir():
        raise Refused(f"--root is not a folder: {args.root}")
    out_dir = Path(args.out_dir)
    index = _load_json(str(out_dir / "closing-index.json"), "closing index")
    selection = _load_json(str(out_dir / "selection-plan.json"), "selection plan")
    manifest = _load_json(str(out_dir / "source-manifest.json"), "manifest")
    overview = _load_json(
        str(out_dir / "execution-overview.json"), "execution overview"
    )
    out = Path(args.out)
    contain_writes(out_dir, [out], args.allow_outside)
    keep_out_of_root(args.root, [out], args.allow_outside, "--out")
    package_parent = _package_parent(args)
    keep_out_of_root(
        args.root, [package_parent], args.allow_outside, "--package-parent"
    )
    plan = assemble.plan(
        index,
        selection,
        manifest,
        overview,
        include_qualified=args.include_qualified,
        volume_pages=args.volume_pages,
        prior_folder=args.prior,
        package_parent=package_parent,
    )
    _write_atomic(out, _dump(plan))
    print(
        f"{out}: {len(plan['entries'])} item(s) enter the bible, {len(plan['excluded'])} "
        f"excluded → {plan['package']['folder']} (approved: false; Gate 2 next)"
    )
    for x in plan["excluded"]:
        print(f"excluded: {x['item_id']} {x['title']} — {x['reason']}")
    return EXIT_OK


def _run_assembly(args: argparse.Namespace, *, update: bool) -> int:
    root = Path(args.root)
    if not root.is_dir():
        raise Refused(f"--root is not a folder: {args.root}")
    plan = _load_json(args.plan, "build plan")
    prior = (
        plan.get("package", {}).get("prior_folder")
        if isinstance(plan.get("package"), dict)
        else None
    )
    if update:
        if prior is None:
            raise Refused(
                "refused: this plan carries no prior package; run plan with --prior for an update"
            )
        if Path(args.prior).name != prior:
            raise Refused(
                f"refused: --prior {Path(args.prior).name} is not the plan's prior package {prior}"
            )
    elif prior is not None:
        raise Refused(
            f"refused: this plan updates {prior}; run `update --prior {prior}` rather than build"
        )
    package_parent = Path(args.package_parent)
    keep_out_of_root(
        args.root, [package_parent], args.allow_outside, "--package-parent"
    )
    receipt, log, report = assemble.build(
        plan,
        root=root,
        audit_dir=Path(args.out_dir),
        package_parent=package_parent,
        as_of=args.as_of,
    )
    package = receipt["package"]
    print(f"{package_parent / package['folder']}: " + _receipt_line(receipt))
    if package["combined_pdf"] is None and not package["volumes"]:
        print(
            "the combined PDF could not be built here (pypdf absent); the indexed set is complete"
        )
    for conv in log["conversions"]:
        if not conv["verified"]:
            print(f"unverified: {conv['source_path']} — {conv['note']}")
    if report is not None:
        print(f"change report: {package['folder']}/change-report.md")
    return EXIT_OK


def cmd_build(args: argparse.Namespace) -> int:
    return _run_assembly(args, update=False)


def cmd_update(args: argparse.Namespace) -> int:
    return _run_assembly(args, update=True)


# ------------------------------------------------------------------- main


def _today() -> str:
    """The only place a clock is read."""

    return _dt.date.today().isoformat()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="closing_bible.py",
        description="closing-bible: census, families and reconciliation for a closing folder.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    census = sub.add_parser(
        "census", help="inventory a closing folder → source-manifest.json"
    )
    census.add_argument("--root", required=True, help="the closing folder (read only)")
    census.add_argument("--out", required=True, help="source-manifest.json to write")
    census.add_argument("--extractor", choices=("auto", "stdlib"), default="auto")
    census.set_defaults(func=cmd_census)

    families = sub.add_parser("families", help="group the manifest → families.json")
    families.add_argument("--manifest", required=True)
    families.add_argument("--out", required=True, help="families.json to write")
    families.add_argument("--sigpack", help="sigpack.ledger.json (optional)")
    families.add_argument("--checklist", help="checklist.json (optional)")
    families.add_argument(
        "--root",
        help="the closing folder; used only to refuse an --out inside it (optional)",
    )
    families.set_defaults(func=cmd_families)

    rec = sub.add_parser(
        "reconcile",
        help="reconcile families and inspection against the expected set → --out-dir",
    )
    rec.add_argument("--manifest", required=True)
    rec.add_argument("--families", required=True)
    rec.add_argument("--inspection", required=True)
    rec.add_argument("--out-dir", required=True, help="folder for the five outputs")
    rec.add_argument(
        "--checklist",
        help="the lawyer's checklist.json, the same one given to families (optional)",
    )
    rec.add_argument(
        "--index",
        help="an approved closing-index.json from an earlier run; wins over --checklist (optional)",
    )
    rec.add_argument("--sigpack", help="sigpack.ledger.json (optional)")
    rec.add_argument("--as-of", default=None, help="YYYY-MM-DD; defaults to today")
    rec.add_argument(
        "--root",
        help="the closing folder; used only to refuse an --out-dir inside it (optional)",
    )
    rec.set_defaults(func=cmd_reconcile)

    status = sub.add_parser("status", help="print the receipt line from --out-dir")
    status.add_argument("--out-dir", required=True)
    status.set_defaults(func=cmd_status)

    plan = sub.add_parser(
        "plan", help="build-plan.json from the approved audit outputs (Gate 2)"
    )
    plan.add_argument("--out-dir", required=True, help="the audit output folder")
    plan.add_argument("--root", required=True, help="the closing folder (read only)")
    plan.add_argument("--out", required=True, help="build-plan.json to write")
    plan.add_argument(
        "--include-qualified",
        action="store_true",
        help="on the lawyer's express instruction: unsigned/undated/incomplete items enter, visibly qualified",
    )
    plan.add_argument(
        "--volume-pages",
        type=int,
        default=None,
        help="split the combined PDF into numbered volumes of at most N pages (N ≥ 50)",
    )
    plan.add_argument(
        "--prior", help="the prior package (closing-bible-vNNN) for an update"
    )
    plan.add_argument(
        "--package-parent",
        help="where the package will be written; default: beside the closing folder",
    )
    plan.set_defaults(func=cmd_plan)

    build = sub.add_parser(
        "build", help="assemble the package the approved plan describes"
    )
    upd = sub.add_parser(
        "update",
        help="assemble the next version beside a prior package, with a change report",
    )
    upd.add_argument(
        "--prior", required=True, help="the prior package (closing-bible-vNNN)"
    )
    for p in (build, upd):
        p.add_argument("--plan", required=True, help="the approved build-plan.json")
        p.add_argument("--out-dir", required=True, help="the audit output folder")
        p.add_argument("--root", required=True, help="the closing folder (read only)")
        p.add_argument(
            "--package-parent", required=True, help="folder beside the closing folder"
        )
        p.add_argument("--as-of", default=None, help="YYYY-MM-DD; defaults to today")
    build.set_defaults(func=cmd_build)
    upd.set_defaults(func=cmd_update)

    for p in (census, families, rec, status, plan, build, upd):
        p.add_argument(
            "--allow-outside",
            action="store_true",
            help="permit an output path outside the output folder, this run only",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd in ("reconcile", "build", "update") and not args.as_of:
        args.as_of = _today()
    try:
        return int(args.func(args))
    except Refused as error:
        print(str(error), file=sys.stderr)
        return EXIT_REFUSED
    except ValueError as error:
        message = str(error)
        print(
            message if message.startswith("refused") else f"refused: {message}",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    except Exception as error:  # the last line before exit 1
        print(f"error: {type(error).__name__}: {error}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
