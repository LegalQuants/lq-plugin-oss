#!/usr/bin/env python3
"""Verify every present finding quote against its manifest source document.

Confirmed matches receive a deterministic quote receipt. A missing or
non-matching quote becomes unresolved with a rejected receipt; stale independent
checker state is removed. File identity or I/O drift fails closed before output.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

_VERIFY_SPEC = importlib.util.spec_from_file_location(
    "diligence_verify_quotes", Path(__file__).with_name("verify_quotes.py")
)
if _VERIFY_SPEC is None or _VERIFY_SPEC.loader is None:
    raise RuntimeError("cannot load sibling verify_quotes.py")
verify_quotes = importlib.util.module_from_spec(_VERIFY_SPEC)
_VERIFY_SPEC.loader.exec_module(verify_quotes)


def load(path, label, required):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"verify_finding_quotes: cannot read {label}: {exc}")
    for key in required:
        if key not in value:
            sys.exit(f"verify_finding_quotes: {label} missing key {key!r}")
    return value


def hash_id(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()[:12]


def source_path(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe manifest path: {relative}")
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"manifest path escapes room root: {relative}") from exc
    return candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--findings", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--room-root", required=True)
    parser.add_argument("--extractor", choices=["auto", "stdlib"], default="auto")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    findings = load(args.findings, "findings", ["findings"])
    manifest = load(args.manifest, "manifest", ["documents", "counts"])
    root = Path(args.room_root).expanduser().resolve()
    if not root.is_dir():
        sys.exit(f"verify_finding_quotes: room root is not a directory: {root}")
    documents = {row["id"]: row for row in manifest["documents"]}
    sources = {}
    errors = []
    for doc_id, document in sorted(documents.items()):
        try:
            path = source_path(root, document["path"])
            if not path.is_file():
                errors.append(f"source document does not exist: {document['path']}")
            elif hash_id(path) != doc_id:
                errors.append(f"manifest identity changed for {document['path']}")
            else:
                sources[doc_id] = path
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    if errors:
        sys.exit("verify_finding_quotes: " + "; ".join(sorted(errors)))

    text_cache = {}
    confirmed = 0
    rejected = 0
    for row in findings["findings"]:
        if row.get("status") != "present":
            continue
        row.pop("verification", None)
        finding_id = row.get("finding_id", "<no id>")
        doc_id = row.get("doc_id")
        path = sources.get(doc_id)
        if path is None:
            sys.exit(
                f"verify_finding_quotes: finding {finding_id} cites "
                f"unknown document {doc_id}"
            )
        if path not in text_cache:
            try:
                text_cache[path] = verify_quotes.normalize(
                    verify_quotes.extract_text(str(path), args.extractor)
                )
            except OSError as exc:
                sys.exit(f"verify_finding_quotes: cannot extract {path}: {exc}")
        quote = str(row.get("quote") or "")
        normalized = verify_quotes.normalize(quote)
        if normalized and normalized in text_cache[path]:
            row["quote_verification"] = {
                "checker": "deterministic-text-match",
                "status": "confirmed",
            }
            confirmed += 1
        else:
            reason = (
                "empty quote" if not normalized else "quote not found in source text"
            )
            row["status"] = "unresolved"
            row["quote_verification"] = {"reason": reason, "status": "rejected"}
            rejected += 1

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(findings, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {args.out}: {confirmed} confirmed, {rejected} changed to unresolved")


if __name__ == "__main__":
    main()
