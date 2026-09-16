#!/usr/bin/env python3
"""parse_redline_docx.py — extract old/new paragraph pairs from a Word file
with tracked changes.

The Word path of /read-redline. Where the PDF parser has to recover changes
from colours and drawn lines, a .docx carries them as tags: ``w:ins``,
``w:del``, ``w:moveFrom``, ``w:moveTo``, each with an author and a date. No
calibration is needed and nothing is inferred from colour.

Output is the same shape as ``parse_redline_pdf.py`` so the rating, the
issues list and the annotated copy are one code path:

    {
      "source_docx": "...", "source_pdf": "...",   # both set; consumers read either
      "pages": [],                                  # Word has no fixed pages
      "calibration": {"kind": "docx-tracked-changes", "authors": {...},
                      "revisions": {"ins": n, "del": n, "moveFrom": n, "moveTo": n},
                      "comments": n, "validation": [...]},
      "pairs": [{"pair_id": "d-0007", "page": 0, "paragraph": 7,
                 "old_text": "...", "new_text": "...", "changed": true,
                 "boxes": {"del": [], "ins": []},
                 "revisions": [{"kind": "ins", "author": "...", "date": "...",
                                "text": "..."}]}],
      "comments": [{"id": "1", "author": "...", "date": "...", "text": "...",
                    "paragraph": 7, "pair_id": "d-0007"}],
      "move_annotations": [], "quarantined": [],
      "stats": {...}
    }

``old_text`` is the paragraph with every change rejected; ``new_text`` with
every change accepted. A paragraph whose only revision is a formatting or
paragraph-mark change has identical texts and ``changed: false``.

    python3 parse_redline_docx.py <redline.docx> --calibrate-only
    python3 parse_redline_docx.py <redline.docx> extract.json

Runs on the standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path
from typing import TypedDict

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W_STRICT = "http://purl.oclc.org/ooxml/wordprocessingml/main"
WORD_NAMESPACES = {W, W_STRICT}
REVISION_TAGS = ("ins", "del", "moveFrom", "moveTo")


class Revision(TypedDict):
    kind: str
    author: str
    date: str
    text: str


class Pair(TypedDict):
    pair_id: str
    page: int
    paragraph: int
    old_text: str
    new_text: str
    changed: bool
    boxes: dict[str, list[list[float]]]
    revisions: list[Revision]


class Comment(TypedDict):
    id: str
    author: str
    date: str
    text: str
    paragraph: int | None
    pair_id: str | None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _is_word(element: ET.Element) -> bool:
    return _ns(element.tag) in WORD_NAMESPACES


def _attr(element: ET.Element, name: str) -> str:
    for key, value in element.attrib.items():
        if _local(key) == name and _ns(key) in WORD_NAMESPACES:
            return value
    return ""


def _run_text(element: ET.Element, *, accepted: bool) -> str:
    """Text of a run-level subtree with changes accepted or rejected."""
    local = _local(element.tag) if _is_word(element) else ""
    if local in {"del", "moveFrom"} and accepted:
        return ""
    if local in {"ins", "moveTo"} and not accepted:
        return ""
    if local == "t":
        return element.text or ""
    if local == "delText":
        return "" if accepted else (element.text or "")
    if local == "tab":
        return "\t"
    if local in {"br", "cr"}:
        return "\n"
    if local in {"rPr", "pPr", "commentRangeStart", "commentRangeEnd"}:
        return ""
    return "".join(_run_text(child, accepted=accepted) for child in element)


def _revisions_in(paragraph: ET.Element) -> list[Revision]:
    found: list[Revision] = []

    def visit(element: ET.Element, inside_ppr: bool) -> None:
        local = _local(element.tag) if _is_word(element) else ""
        if local == "pPr":
            inside_ppr = True
        if local in REVISION_TAGS and not inside_ppr:
            text = _run_text(element, accepted=local in {"ins", "moveTo"})
            found.append(
                {
                    "kind": local,
                    "author": _attr(element, "author"),
                    "date": _attr(element, "date"),
                    "text": text,
                }
            )
            return
        for child in element:
            visit(child, inside_ppr)

    visit(paragraph, False)
    return found


def _paragraphs(root: ET.Element) -> list[ET.Element]:
    """Body paragraphs in document order, table cells included, nested
    paragraphs (text boxes inside a paragraph) counted once."""
    out: list[ET.Element] = []

    def visit(element: ET.Element) -> None:
        if _is_word(element) and _local(element.tag) == "p":
            out.append(element)
            return
        for child in element:
            visit(child)

    visit(root)
    return out


def _comment_anchors(root: ET.Element, paragraphs: list[ET.Element]) -> dict[str, int]:
    """comment id -> index of the paragraph holding its range start."""
    index = {id(p): i for i, p in enumerate(paragraphs)}
    anchors: dict[str, int] = {}

    def visit(element: ET.Element, current: int | None) -> None:
        if _is_word(element):
            local = _local(element.tag)
            if local == "p":
                current = index.get(id(element), current)
            elif local in {"commentRangeStart", "commentReference"}:
                cid = _attr(element, "id")
                if cid and cid not in anchors and current is not None:
                    anchors[cid] = current
        for child in element:
            visit(child, current)

    visit(root, None)
    return anchors


def _read_comments(zf: zipfile.ZipFile) -> list[tuple[str, str, str, str]]:
    if "word/comments.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("word/comments.xml"))
    out = []
    for c in root:
        if not (_is_word(c) and _local(c.tag) == "comment"):
            continue
        text = " ".join(
            _run_text(p, accepted=True).strip()
            for p in _paragraphs(c)
            if _run_text(p, accepted=True).strip()
        )
        out.append((_attr(c, "id"), _attr(c, "author"), _attr(c, "date"), text))
    return out


def extract(docx_path: str | Path) -> dict:
    path = Path(docx_path)
    with zipfile.ZipFile(path) as zf:
        if "word/document.xml" not in zf.namelist():
            raise RuntimeError("not a Word document: word/document.xml is missing")
        root = ET.fromstring(zf.read("word/document.xml"))
        raw_comments = _read_comments(zf)

    paragraphs = _paragraphs(root)
    pairs: list[Pair] = []
    move_annotations: list[dict[str, object]] = []
    authors: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    formatting_changes = 0
    changed = 0
    for i, p in enumerate(paragraphs):
        old = " ".join(_run_text(p, accepted=False).split())
        new = " ".join(_run_text(p, accepted=True).split())
        revisions = _revisions_in(p)
        formatting_changes += sum(
            1
            for e in p.iter()
            if _is_word(e) and _local(e.tag) in {"rPrChange", "pPrChange"}
        )
        for r in revisions:
            authors[r["author"] or "(no author)"] += 1
            kinds[r["kind"]] += 1
        only_moves = bool(revisions) and all(
            r["kind"] in {"moveFrom", "moveTo"} for r in revisions
        )
        if only_moves:
            # Text that moved is not a change at either end. Report it as a
            # move, as the PDF path does, and keep the pair unchanged.
            for r in revisions:
                move_annotations.append(
                    {
                        "page": 0,
                        "paragraph": i,
                        "pair_id": f"d-{i:04d}",
                        "label": (
                            "Moved from" if r["kind"] == "moveFrom" else "Moved to"
                        ),
                        "text": r["text"],
                        "author": r["author"],
                    }
                )
            old = new = old or new
        is_changed = old != new
        changed += int(is_changed)
        pairs.append(
            {
                "pair_id": f"d-{i:04d}",
                "page": 0,
                "paragraph": i,
                "old_text": old,
                "new_text": new,
                "changed": is_changed,
                "boxes": {"del": [], "ins": []},
                "revisions": revisions,
            }
        )

    anchors = _comment_anchors(root, paragraphs)
    comments: list[Comment] = []
    for cid, author, date, text in raw_comments:
        para = anchors.get(cid)
        comments.append(
            {
                "id": cid,
                "author": author,
                "date": date,
                "text": text,
                "paragraph": para,
                "pair_id": f"d-{para:04d}" if para is not None else None,
            }
        )

    validation: list[str] = []
    if not kinds and formatting_changes:
        validation.append(
            f"Only formatting changes are tracked ({formatting_changes}); no text "
            "was inserted, deleted or moved. Nothing to rate."
        )
    elif not kinds:
        validation.append(
            "No tracked changes found — every paragraph reads the same with "
            "changes accepted or rejected. If this is meant to be a redline, "
            "the changes were accepted before saving, or the file is a clean "
            "draft. Nothing to review."
        )
    return {
        "source_docx": str(path),
        "source_pdf": str(path),
        "pages": [],
        "calibration": {
            "kind": "docx-tracked-changes",
            "authors": dict(authors.most_common()),
            "revisions": {k: kinds.get(k, 0) for k in REVISION_TAGS},
            "comments": len(comments),
            "formatting_only_changes": formatting_changes,
            "validation": validation,
        },
        "pairs": pairs,
        "comments": comments,
        "move_annotations": move_annotations,
        "quarantined": [],
        "stats": {
            "pages": 0,
            "body_start_page": 0,
            "paragraphs": len(pairs),
            "changed_paragraphs": changed,
            "quarantined_paragraphs": 0,
            "comments": len(comments),
        },
    }


def print_report(result: dict) -> None:
    cal = result["calibration"]
    print(f"Tracked-changes report for: {result['source_docx']}")
    st = result["stats"]
    print(f"Paragraphs: {st['paragraphs']}  changed: {st['changed_paragraphs']}")
    rev = cal["revisions"]
    print(
        f"Revisions: insertions={rev['ins']}  deletions={rev['del']}  "
        f"moved from={rev['moveFrom']}  moved to={rev['moveTo']}  "
        f"formatting-only={cal['formatting_only_changes']}  comments={cal['comments']}"
    )
    for m in result["move_annotations"]:
        print(f"  {m['label']:10} paragraph {m['paragraph']}: {str(m['text'])[:60]!r}")
    if cal["authors"]:
        print("By author:")
        for author, n in cal["authors"].items():
            print(f"  {author:30} {n:5} revisions")
    for w in cal["validation"]:
        print(f"\nWARNING: {w}")
    if not cal["validation"]:
        print(
            "\nEvery change above is a tag written by Word, not an inference from "
            "colour. Confirm the authors are who you expect before rating."
        )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="parse_redline_docx.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("docx", help="Path to the Word file with tracked changes.")
    parser.add_argument("output_json", nargs="?", default=None)
    parser.add_argument(
        "--calibrate-only",
        action="store_true",
        help="Print the revision report and exit.",
    )
    args = parser.parse_args(argv[1:])
    result = extract(args.docx)
    if args.calibrate_only:
        print_report(result)
        return 0
    if not args.output_json:
        print(
            "Error: output_json is required unless --calibrate-only is set.",
            file=sys.stderr,
        )
        return 1
    Path(args.output_json).write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    s = result["stats"]
    print(f"Wrote {args.output_json}")
    print(
        f"  paragraphs: {s['paragraphs']}  changed: {s['changed_paragraphs']}  "
        f"comments: {s['comments']}"
    )
    for w in result["calibration"]["validation"]:
        print(f"\nWARNING: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
