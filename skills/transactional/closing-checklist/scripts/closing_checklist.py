"""Optional local checklist tooling. Semantic review and consent remain human-led."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from zipfile import BadZipFile

import checklist_docx as word


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_new(path, data):
    # Exclusive creation protects both supplied files and earlier work product.
    with Path(path).open("xb") as stream:
        stream.write(data)


def fingerprint(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": digest(path.read_bytes())}


def extract(path):
    """Text with stable snapshot-local locators, not a legal completeness check."""
    path = Path(path)
    warnings = []
    units = []
    if path.suffix.lower() in (".txt", ".md"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                units.append({"id": f"L{i}", "text": line})
    elif path.suffix.lower() == ".docx":
        parts = word.package(path)
        for name, data in sorted(parts.items()):
            if not name.startswith("word/") or not name.endswith(".xml"):
                continue
            root = word.xml(data)
            if any(
                root.find(f".//w:{t}", word.NS) is not None
                for t in ("ins", "del", "drawing", "pict", "altChunk", "object", "sdt")
            ):
                warnings.append(
                    f"{name}: revisions, images or complex content; inspect in host"
                )
            for i, p in enumerate(root.iter(word.tag("p")), 1):
                value = word.text(p)
                if value.strip():
                    units.append({"id": f"{name}:P{i}", "text": value})
        warnings.append(
            "Paragraph extraction is not visual/OCR coverage; inspect source layout"
        )
    else:
        raise ValueError(
            "Use readable TXT/MD/DOCX; stage host-extracted PDF text with provenance"
        )
    if not units:
        raise ValueError(f"No readable text: {path.name}")
    return {**fingerprint(path), "units": units, "warnings": warnings}


def prepare(paths):
    return {
        "schema_version": 1,
        "sources": [
            {"id": f"S{i}", **extract(path)} for i, path in enumerate(paths, 1)
        ],
    }


def verify_sources(bundle):
    if bundle.get("schema_version") != 1:
        raise ValueError("Unsupported source schema")
    sources = {}
    for source in bundle["sources"]:
        if source["id"] in sources:
            raise ValueError("Duplicate source ID")
        fresh = extract(source["path"])
        if fresh["sha256"] != source["sha256"] or fresh["units"] != source["units"]:
            raise ValueError(
                "Source changed or extracted text was altered; prepare again"
            )
        sources[source["id"]] = {u["id"]: u["text"] for u in source["units"]}
    return sources


def validate(spec, bundle):
    sources = verify_sources(bundle)
    if spec["mode"] not in ("create", "revise"):
        raise ValueError("Mode must be create or revise")
    proposals = spec["items"] if spec["mode"] == "create" else spec["operations"]
    if spec["mode"] == "create" and not spec.get("template"):
        word.front_matter(spec)
    if not proposals:
        raise ValueError(
            "No proposals: report no changes without rewriting the checklist"
        )
    seen = set()
    for proposal in proposals:
        identity = proposal["id"]
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError("Unique nonempty proposal IDs required")
        seen.add(identity)
        basis = proposal["basis"]
        if basis not in ("document", "practice", "instruction"):
            raise ValueError("Unknown proposal basis")
        if not proposal.get("reason"):
            raise ValueError("Each proposal needs a review explanation")
        evidence = proposal.get("evidence", [])
        if basis == "document" and not evidence:
            raise ValueError("Document-derived proposal lacks evidence")
        for ev in evidence:
            passage = sources[ev["source_id"]][ev["unit_id"]]
            if not ev["quote"].strip() or ev["quote"] not in passage:
                raise ValueError("Evidence quote not found in the source unit")
    return proposals


def make_plan(spec, bundle):
    spec, bundle = json.loads(encoded(spec)), json.loads(encoded(bundle))
    validate(spec, bundle)
    inputs = []
    for key in ("baseline", "template"):
        if spec.get(key):
            inputs.append({"role": key, **fingerprint(spec[key])})
            spec = {**spec, key: inputs[-1]["path"]}
    if spec["mode"] == "revise" and not spec.get("baseline"):
        raise ValueError("Revision requires the latest checklist")
    if spec["mode"] == "revise" and spec.get("template"):
        raise ValueError(
            "Revision edits the baseline; template replacement is not supported"
        )
    payload = {"schema_version": 1, "spec": spec, "sources": bundle, "inputs": inputs}
    return {**payload, "plan_sha256": digest(encoded(payload))}


def apply(plan, approval):
    payload = {key: value for key, value in plan.items() if key != "plan_sha256"}
    sha = digest(encoded(payload))
    if sha != plan["plan_sha256"] or sha != approval["plan_sha256"]:
        raise ValueError("Approval does not match this plan")
    if not approval.get("user_instruction", "").strip():
        raise ValueError("Record the user's explicit approval; never infer consent")
    for item in plan["inputs"]:
        if fingerprint(item["path"])["sha256"] != item["sha256"]:
            raise ValueError(
                "Checklist/template changed; re-review against latest Word"
            )
    spec = plan["spec"]
    proposals = validate(spec, plan["sources"])
    approved = approval["approved_ids"]
    ids = {p["id"] for p in proposals}
    if not approved or len(set(approved)) != len(approved) or not set(approved) <= ids:
        raise ValueError("Approval must name unique proposal IDs present in the plan")
    chosen = [p for p in proposals if p["id"] in approved]
    if spec["mode"] == "revise":
        parts = word.patch(word.package(spec["baseline"]), chosen)
    elif spec.get("template"):
        parts = word.from_template(
            word.package(spec["template"]), spec["layout"], chosen
        )
    else:
        # Approval filtering, not the author, decides which numbers survive.
        parts = word.generic(
            spec["title"],
            spec["headings"],
            word.sequenced(spec["headings"], chosen),
            spec,
        )
    # Validate serialisation before any output is written.
    word.xml(parts["word/document.xml"])
    return word.archive(parts)


def external_copy(path, table_index, column):
    """Narrow safe path: helper-created packages only; refuse recoverable data."""
    parts = word.package(path)
    if not word.GENERIC_PARTS >= set(parts) or "word/document.xml" not in parts:
        raise ValueError(
            "External copy needs host sanitisation: ancillary package parts present"
        )
    root = word.xml(parts["word/document.xml"])
    word.editable(root, parts)
    # Accept only this helper's inert package vocabulary, not arbitrary OOXML.
    safe_tags = {
        "document",
        "body",
        "p",
        "pPr",
        "spacing",
        "keepNext",
        "r",
        "rPr",
        "rFonts",
        "sz",
        "b",
        "i",
        "t",
        "br",
        "tab",
        "tbl",
        "tblPr",
        "tblW",
        "tblLayout",
        "tblBorders",
        "top",
        "left",
        "bottom",
        "right",
        "insideH",
        "insideV",
        "tblCellMar",
        "tblGrid",
        "gridCol",
        "tr",
        "trPr",
        "cantSplit",
        "tblHeader",
        "tc",
        "tcPr",
        "tcW",
        "vAlign",
        "gridSpan",
        "shd",
        "sectPr",
        "footerReference",
        "pgSz",
        "pgMar",
    }
    footer_tags = {
        "ftr",
        "p",
        "pPr",
        "tabs",
        "tab",
        "spacing",
        "r",
        "rPr",
        "rFonts",
        "sz",
        "t",
        "fldSimple",
    }
    for data, allowed in (
        (parts["word/document.xml"], safe_tags),
        (parts.get("word/footer1.xml"), footer_tags),
    ):
        if data and any(
            n.tag not in {word.tag(t) for t in allowed} for n in word.xml(data).iter()
        ):
            raise ValueError(
                "Unknown content: use a host editor and package-level review"
            )
    title, front, headings, records, index = word.parse_generic(parts, table_index)
    if type(column) is not int or not 0 <= column < len(headings):
        raise ValueError("Notes column index outside the checklist table")
    heading = headings[column].strip().lower()
    if not any(word_ in heading for word_ in ("note", "comment", "remark")):
        raise ValueError(
            "Confirm the internal column: heading does not look like notes"
        )
    if len(headings) - 1 < 5:
        raise ValueError("External copy would have fewer than five columns")
    secrets = {record["cells"][column].strip() for record in records}
    secrets.discard("")
    public_headings = [h for i, h in enumerate(headings) if i != column]
    public_records = [
        {**record, "cells": [c for i, c in enumerate(record["cells"]) if i != column]}
        for record in records
    ]
    # Rebuild from visible public strings only: no original attributes or metadata.
    rebuilt = word.generic(title, public_headings, public_records, front)
    remaining = word.text(word.xml(rebuilt["word/document.xml"])) + word.text(
        word.xml(rebuilt["word/footer1.xml"])
    )
    if any(s in remaining for s in secrets):
        raise ValueError(
            "Removed notes text also appears elsewhere; review before release"
        )
    return word.archive(rebuilt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("sources", nargs="+")
    prep.add_argument("--out", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("checklist")
    plan = sub.add_parser("plan")
    plan.add_argument("--spec", required=True)
    plan.add_argument("--sources", required=True)
    plan.add_argument("--out", required=True)
    run = sub.add_parser("apply")
    run.add_argument("--plan", required=True)
    run.add_argument("--approval", required=True)
    run.add_argument("--out", required=True)
    external = sub.add_parser("external")
    external.add_argument("checklist")
    external.add_argument("--table", type=int, default=None)
    external.add_argument("--notes-column", type=int, required=True)
    external.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            write_new(args.out, encoded(prepare(args.sources)))
        elif args.command == "inspect":
            print(encoded(word.inspect(args.checklist)).decode())
        elif args.command == "plan":
            result = make_plan(read(args.spec), read(args.sources))
            write_new(args.out, encoded(result))
            print(result["plan_sha256"])
        elif args.command == "apply":
            write_new(args.out, apply(read(args.plan), read(args.approval)))
        elif args.command == "external":
            write_new(
                args.out, external_copy(args.checklist, args.table, args.notes_column)
            )
    except (
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        OSError,
        BadZipFile,
        word.ET.ParseError,
    ) as exc:
        print(f"Checklist not written: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
