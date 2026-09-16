#!/usr/bin/env python3
"""annotate_docx.py — write the review as Word comments into a separately
named copy of a tracked-changes .docx. On request only; the issues list is
the default deliverable on the Word path.

    python3 annotate_docx.py redline.docx --pairs extract.json --rows rows.json \\
        --out "Agreement - Annotated.docx"

One comment per row, anchored on the paragraph of the row's first
``source_pair_id``, authored "LegalQuants" so the whole layer can be filtered
or deleted by reviewer in one action. The comment reads
``[High] Provision — comment`` — prefixed with the direction when the row
carries one: ``[favours-them · High] Provision — comment``. Nothing else in
the document changes: no
shading, no colour, the lawyer's own tracked changes and comments untouched.
The source file is never written; ``--out`` must be a different path.

Runs on the standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from calibration_gate import gate_state_line, require_gate  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
AUTHOR = "LegalQuants"
INITIALS = "LQ"
COMMENTS_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
)
COMMENTS_CT = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
)
P_OPEN = re.compile(r"<w:p(?=[\s>/])[^>]*?(?<!/)>")
PPR_BLOCK = re.compile(
    r"^\s*<w:pPr(?:\s[^>]*)?>.*?</w:pPr>|^\s*<w:pPr(?:\s[^>]*)?/>", re.S
)


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _paragraph_spans(document: str) -> list[tuple[int, int]]:
    """(start, end) offsets of every <w:p>...</w:p> in document order, in the
    same order the parser numbers paragraphs (nesting not expected in body
    text; a nested paragraph would be counted by the parser first, so we
    mirror that by scanning opens and matching closes with a stack)."""
    spans: list[tuple[int, int]] = []
    stack: list[int] = []
    token = r"<w:p(?=[\s>/])[^>]*?/>|<w:p(?=[\s>/])[^>]*?>|</w:p>"
    for m in re.finditer(token, document):
        tok = m.group(0)
        if tok.endswith("/>"):
            spans.append((m.start(), m.end()))
        elif tok.startswith("</"):
            if stack:
                spans.append((stack.pop(), m.end()))
        else:
            stack.append(m.start())
    # parser order = document order of the opening tag
    return sorted(spans)


def build_comment(row: dict) -> str:
    comment = (row.get("comment") or "").strip()
    if not comment:
        raise KeyError(f"Row {row.get('provision', '?')!r} has no 'comment'.")
    tier = (row.get("materiality") or "").strip()
    direction = (row.get("direction") or "").strip()
    label = f"{direction} · {tier}" if direction else tier
    provision = (row.get("provision") or "").strip()
    head = f"[{label}] {provision}".strip()
    return f"{head} — {comment}" if head else comment


def annotate(src: Path, out: Path, pairs_path: Path, rows_path: Path) -> int:
    if out.resolve() == src.resolve():
        raise SystemExit("--out must differ from the source; it is never modified")
    gate = require_gate(pairs_path)
    print(gate_state_line(gate))
    extract = json.loads(pairs_path.read_text(encoding="utf-8"))
    rows = json.loads(rows_path.read_text(encoding="utf-8"))
    by_id = {p["pair_id"]: p for p in extract["pairs"]}

    with zipfile.ZipFile(src) as zf:
        names = zf.namelist()
        parts = {n: zf.read(n) for n in names}
    document = parts["word/document.xml"].decode("utf-8")
    spans = _paragraph_spans(document)

    existing = parts.get("word/comments.xml", b"").decode("utf-8")
    used_ids = {int(x) for x in re.findall(r'w:id="(\d+)"', existing)} | {
        int(x) for x in re.findall(r'<w:comment[^>]*w:id="(\d+)"', document)
    }
    next_id = (max(used_ids) + 1) if used_ids else 0
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    placements: list[tuple[int, int, str]] = []  # (paragraph index, comment id, text)
    unplaceable: list[str] = []
    for row in rows:
        pid = next((p for p in row.get("source_pair_ids", []) if p in by_id), None)
        if pid is None or by_id[pid].get("paragraph") is None:
            unplaceable.append(row.get("provision", "?"))
            continue
        idx = int(by_id[pid]["paragraph"])
        if idx >= len(spans):
            unplaceable.append(row.get("provision", "?"))
            continue
        placements.append((idx, next_id, build_comment(row)))
        next_id += 1

    # Insert from the last paragraph backwards so offsets stay valid.
    for idx, cid, _text in sorted(placements, key=lambda t: -t[0]):
        start, end = spans[idx]
        para = document[start:end]
        if para.endswith("/>"):
            # empty paragraph: make it a real one holding only the marks
            open_tag = para[:-2] + ">"
            body = ""
            close = "</w:p>"
        else:
            opened = P_OPEN.match(para)
            if opened is None:
                raise SystemExit(
                    f"paragraph {idx} has no opening tag; refusing to guess"
                )
            open_tag = opened.group(0)
            body = para[len(open_tag) : -len("</w:p>")]
            close = "</w:p>"
        ppr = PPR_BLOCK.match(body)
        ppr_text = ppr.group(0) if ppr else ""
        rest = body[len(ppr_text) :]
        new_para = (
            f"{open_tag}{ppr_text}"
            f'<w:commentRangeStart w:id="{cid}"/>{rest}'
            f'<w:commentRangeEnd w:id="{cid}"/>'
            f'<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>'
            f'<w:commentReference w:id="{cid}"/></w:r>{close}'
        )
        document = document[:start] + new_para + document[end:]

    comment_xml = "".join(
        f'<w:comment w:id="{cid}" w:author="{AUTHOR}" w:initials="{INITIALS}" '
        f'w:date="{stamp}"><w:p><w:r><w:t xml:space="preserve">{_esc(text)}</w:t>'
        "</w:r></w:p></w:comment>"
        for _idx, cid, text in placements
    )
    if existing:
        comments = existing.replace("</w:comments>", comment_xml + "</w:comments>")
    else:
        comments = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:comments xmlns:w="{W}">{comment_xml}</w:comments>'
        )
    parts["word/comments.xml"] = comments.encode("utf-8")
    parts["word/document.xml"] = document.encode("utf-8")

    rels_name = "word/_rels/document.xml.rels"
    rels = parts.get(rels_name, b"").decode("utf-8")
    if COMMENTS_REL not in rels:
        if not rels:
            rels = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'
            )
        rid = f"rId{len(re.findall(r'<Relationship ', rels)) + 900}"
        rels = rels.replace(
            "</Relationships>",
            f'<Relationship Id="{rid}" Type="{COMMENTS_REL}" Target="comments.xml"/>'
            "</Relationships>",
        )
        parts[rels_name] = rels.encode("utf-8")
    ct = parts["[Content_Types].xml"].decode("utf-8")
    if "/word/comments.xml" not in ct:
        ct = ct.replace(
            "</Types>",
            f'<Override PartName="/word/comments.xml" ContentType="{COMMENTS_CT}"/>'
            "</Types>",
        )
        parts["[Content_Types].xml"] = ct.encode("utf-8")

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in names:
            zf.writestr(name, parts[name])
        if "word/comments.xml" not in names:
            zf.writestr("word/comments.xml", parts["word/comments.xml"])

    # Self-check: the copy must open and carry every comment we placed.
    with zipfile.ZipFile(out) as zf:
        comments_part = zf.read("word/comments.xml").decode("utf-8")
        body_part = zf.read("word/document.xml").decode("utf-8")
    placed = comments_part.count(f'w:author="{AUTHOR}"')
    doc_refs = body_part.count("<w:commentReference ")
    if placed < len(placements):
        raise SystemExit(
            f"self-check failed: placed {placed} of {len(placements)} comments"
        )
    print(
        f"Wrote {out} — {len(placements)} comment(s) by {AUTHOR}; "
        f"{doc_refs} reference(s) in the body."
    )
    for name in unplaceable:
        print(f"  UNPLACEABLE: {name!r} (no paragraph for its source pairs)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="annotate_docx.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("docx")
    ap.add_argument("--pairs", required=True, help="extract.json from the parser")
    ap.add_argument("--rows", required=True, help="rows.json from the analysis layer")
    ap.add_argument(
        "--out", required=True, help="annotated copy path (never the source)"
    )
    a = ap.parse_args(argv[1:])
    return annotate(Path(a.docx), Path(a.out), Path(a.pairs), Path(a.rows))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
