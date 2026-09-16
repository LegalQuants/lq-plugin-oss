#!/usr/bin/env python3
"""
annotate_pdf.py — stamp significance highlights and reviewer comments
directly into a redline PDF, producing an annotated copy that opens with a
full comment thread in a PDF reader's Comments pane. This is the skill's
only deliverable: it hands the reviewer back the document they were already
reading, marked up.

Division of labour (deliberate, do not blur it):
  - This script owns ALL geometry. It never decides what is significant.
  - The analysis layer owns ALL judgment. It never touches a coordinate.
The join between them is `pair_id`: parse_redline_pdf.py assigns one to
every paragraph pair, and each row lists the pair_ids it covers in
`source_pair_ids`. One row may cover several pairs.

Only changes the analysis layer chose to surface are annotated. Changes
below that bar stay visible anyway — the compare tool already struck or
underlined them; the highlights are a significance layer on top of that.

Runs on `pypdf` (BSD-3, pure Python) rather than PyMuPDF (AGPL). See
parse_redline_pdf.py's header for the same constraint on the read side.

Two coordinate traps this script exists to get right, both of which produce
valid-looking JSON and visibly wrong PDFs:

  1. Y-AXIS FLIP. pdfplumber measures `top`/`bottom` down from the top of the
     page. PDF annotations measure up from the bottom. Every box must be
     converted with `y_pdf = page_height - y_plumber`, which is why the parser
     has to emit per-page height and why this script refuses to guess it.

  2. QUADPOINTS ORDER. A highlight is not a rectangle, it is a list of quads —
     one per line of text. A change spanning three lines needs three quads, or
     the highlight paints the empty margin between them. The corner order that
     Acrobat actually honours is upper-left, upper-right, lower-left,
     lower-right — NOT clockwise, despite what the spec's wording suggests.

Usage:

    python3 annotate_pdf.py redline.pdf --pairs extract.json --rows rows.json \
        --out "Agreement - Annotated Redline.pdf"

    # See what would be annotated without writing a file:
    python3 annotate_pdf.py redline.pdf --pairs extract.json --rows rows.json \
        --dry-run

Inputs:
  redline.pdf   The same PDF that was fed to parse_redline_pdf.py. Annotating
                any other file would place highlights at meaningless offsets,
                so the page count is checked against the extract and a mismatch
                is fatal.
  --pairs       parse_redline_pdf.py's output JSON. Supplies geometry: each
                pair's `pair_id` and `boxes`, plus top-level `pages` with each
                page's height. Also supplies `quarantined`.
  --rows        JSON list of rows (the analysis layer's output), each
                carrying `source_pair_ids`.
  --out         Path for the annotated copy. The source PDF is never modified.

The calibration gate is enforced: calibration.confirmed.json must sit beside
--pairs, match the current extract hash, and carry a valid status (see
calibration_gate.py); without it this script refuses to run. --check-contract
runs from the parser session, before the gate exists, and is exempt.

Exit codes: 0 ok, 1 bad input, 2 nothing to annotate.

Requires: pypdf 5.9.0 or a compatible release.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    from pypdf import PdfReader, PdfWriter
    from pypdf.annotations import Highlight, Text
    from pypdf.generic import (
        ArrayObject,
        FloatObject,
        NameObject,
        TextStringObject,
    )
except ImportError:  # pragma: no cover - environment guard
    sys.exit("pypdf is required but is not available in this environment.")

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from calibration_gate import gate_state_line, require_gate  # noqa: E402

# Highlight fill per significance tier. Self-contained: these are the only
# colors the skill uses, so a tier maps straight to a highlight color here.
MATERIALITY_COLORS = {
    "High": "F8D7DA",
    "Medium": "FFF3CD",
    "Low": "D4EDDA",
}

# Deliberately outside the materiality palette: a quarantine marker is an
# accuracy warning, not a materiality rating, and must not be mistaken for one.
QUARANTINE_COLOR = "D0C4E8"

# Shown as the comment author in Acrobat. Every mark this plugin leaves on a
# document is authored "LegalQuants", so nobody mistakes machine-generated
# markup for a colleague's and the whole layer can be filtered or removed by
# reviewer in one action.
ANNOTATION_AUTHOR = "LegalQuants"

MATERIALITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def _fail(msg: str) -> None:
    sys.exit(f"ERROR: {msg}")


def to_pdf_quad(box, page_height):
    """Convert one pdfplumber box to eight PDF quadpoint floats.

    `box` is [x0, top, x1, bottom] in pdfplumber's top-down space. Returns the
    corners in the order Acrobat honours: UL, UR, LL, LR.
    """
    x0, top, x1, bottom = box
    y_upper = page_height - top
    y_lower = page_height - bottom
    return [x0, y_upper, x1, y_upper, x0, y_lower, x1, y_lower]


LINE_TOL = 3.0  # pts: chars this close vertically are the same line
MIN_LINE_CHARS = 10  # fewer than this on a line = watermark noise, not text


def provision_boxes(boxes):
    """Raw boxes for one changed pair, provision extent preferred.

    `boxes["provision"]` is one box per line of the whole changed block at full
    text width, which paints the change as a single continuous ribbon. The
    per-role `del`/`ins` boxes bound only the coloured runs, which leaves the
    struck-through text between them unpainted — a single definition then
    renders as disconnected islands with bare gaps.

    Either shape is accepted here because `expand_to_lines` normalises both to
    full line extents before anything is drawn.
    """
    if boxes.get("provision"):
        return boxes["provision"]
    return [b for role in ("del", "ins") for b in boxes.get(role, [])]


def page_line_extents(pdf_path, wanted_pages, page_base):
    """Full-width text extent of every line on the pages we need.

    Returns {page_no: [[x0, top, x1, bottom], ...]} in pdfplumber's top-down
    space, one entry per visual line.

    Lines under MIN_LINE_CHARS characters are dropped as watermark noise. A
    data-room stamp (confidentiality notice, downloader name, timestamp) is
    often UPRIGHT rather than rotated — every character reports upright=True —
    so it cannot be filtered on that flag. Its characters scatter across the
    page and form sparse phantom lines between the real ones; left in, they
    both inflate line boxes and fragment provisions.
    """
    import pdfplumber  # local: only needed when expanding, and only in this path

    extents = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page_no in sorted(wanted_pages):
            idx = page_no - page_base
            if not (0 <= idx < len(pdf.pages)):
                continue
            buckets = defaultdict(list)
            for c in pdf.pages[idx].chars:
                buckets[round(c["top"] / LINE_TOL) * LINE_TOL].append(c)
            lines = []
            for key in sorted(buckets):
                chars = buckets[key]
                if len(chars) < MIN_LINE_CHARS:
                    continue
                lines.append(
                    [
                        min(c["x0"] for c in chars),
                        min(c["top"] for c in chars),
                        max(c["x1"] for c in chars),
                        max(c["bottom"] for c in chars),
                    ]
                )
            extents[page_no] = lines
    return extents


def expand_to_lines(boxes, lines):
    """Widen raw boxes to the full extent of every line they touch.

    The parser reports where the changed *characters* sit. What a reviewer
    wants highlighted is the provision those characters belong to, so each box
    is snapped out to the full width of its line and adjacent touched lines are
    kept as separate quads — giving one continuous band down the provision
    rather than islands around the coloured runs.

    Falls back to the raw boxes if the page yielded no usable lines, so a page
    this heuristic cannot read still gets marked rather than silently skipped.
    """
    if not lines:
        return boxes

    touched = []
    for _x0, top, _x1, bottom in boxes:
        for line in lines:
            # vertical overlap, tolerant of a point or two of drift
            if line[3] > top + 1.0 and line[1] < bottom - 1.0:
                if line not in touched:
                    touched.append(line)
    return touched or boxes


def union_rect(quads):
    """Bounding rect (x0, y0, x1, y1) over a flat list of quadpoint floats."""
    xs = quads[0::2]
    ys = quads[1::2]
    return (min(xs), min(ys), max(xs), max(ys))


def build_comment(row):
    """Return the model-authored comment body for one row.

    The comment is written by the analysis layer, NOT assembled here from the
    table's columns. Per SKILL.md step 3, a comment is "a one-to-two sentence
    plain-English summary of *what changed and why it matters* — not a
    restatement of the diff", which is the same voice the Word redline's
    comments use. Stitching the table cells together instead produces a
    WAS/NOW/WHY block that restates the diff — exactly what that rule forbids —
    so the script's only job is to place the prose it is given.
    """
    comment = (row.get("comment") or "").strip()
    if not comment:
        raise KeyError(
            f"Row {row.get('provision', '?')!r} has no 'comment'. Each row needs a "
            "one-to-two sentence plain-English summary of what changed and why it "
            "matters (SKILL.md step 3) — the script does not generate this."
        )
    return comment


def load_geometry(pairs_path):
    """Read parse_redline_pdf.py output; return (pair_id -> pair, page -> height)."""
    with open(pairs_path, encoding="utf-8") as f:
        extract = json.load(f)

    pages = extract.get("pages")
    if not pages:
        _fail(
            f"{pairs_path} has no top-level 'pages' list, so page heights are "
            "unknown and every highlight would be vertically mirrored. Re-run "
            "parse_redline_pdf.py with the geometry fields enabled."
        )
    heights = {p["number"]: float(p["height"]) for p in pages}

    # parse_redline_pdf.py numbers pages from 0, so pair["page"] indexes
    # reader.pages directly. Derived rather than hardcoded: an off-by-one here
    # puts every highlight on the wrong page, and that is a silent failure —
    # the output still looks like a properly annotated document.
    page_base = min(p["number"] for p in pages)
    if page_base not in (0, 1):
        _fail(f"page numbering starts at {page_base}; expected 0 or 1.")

    by_id = {}
    missing_boxes = 0
    for pair in extract.get("pairs", []):
        pid = pair.get("pair_id")
        if pid is None:
            continue
        if not pair.get("boxes"):
            if pair.get("changed"):
                missing_boxes += 1
            continue
        by_id[pid] = pair

    if not by_id:
        _fail(
            f"{pairs_path} contains no pairs with 'pair_id' and 'boxes'. This "
            "script needs the geometry fields that parse_redline_pdf.py emits; "
            "an older extract will not work."
        )
    if missing_boxes:
        print(
            f"  ! {missing_boxes} changed pair(s) carry no boxes and cannot be "
            "highlighted; they will be reported as unplaceable.",
            file=sys.stderr,
        )

    return extract, by_id, heights, page_base


def collect_annotations(rows, by_id, heights, line_extents=None):
    """Turn rows + geometry into per-page annotation specs.

    Returns (annotations, unplaceable) where annotations is
    {page_number: [ {quads, color, comment, subject}, ... ]}.
    """
    annotations = defaultdict(list)
    unplaceable = []

    ordered = sorted(rows, key=lambda r: MATERIALITY_ORDER.get(r.get("materiality"), 9))

    for row in ordered:
        pair_ids = row.get("source_pair_ids") or []
        if not pair_ids:
            unplaceable.append((row.get("provision", "?"), "no source_pair_ids"))
            continue

        # A row can span several paragraphs and therefore several pages; each
        # page gets its own annotation carrying the same comment, so the
        # reviewer sees the note wherever they happen to be reading.
        quads_by_page = defaultdict(list)
        for pid in pair_ids:
            pair = by_id.get(pid)
            if pair is None:
                unplaceable.append(
                    (row.get("provision", "?"), f"unknown pair_id {pid}")
                )
                continue
            page_no = pair["page"]
            height = heights.get(page_no)
            if height is None:
                unplaceable.append(
                    (row.get("provision", "?"), f"no height for page {page_no}")
                )
                continue
            raw = provision_boxes(pair["boxes"])
            boxes = expand_to_lines(raw, (line_extents or {}).get(page_no))
            for box in boxes:
                quads_by_page[page_no].extend(to_pdf_quad(box, height))

        if not quads_by_page:
            continue

        try:
            comment = build_comment(row)
        except KeyError as exc:
            unplaceable.append((row.get("provision", "?"), str(exc)))
            continue

        # Materiality and provision ride in /Subj rather than the body, so the
        # body stays the clean plain-English sentence the rule asks for while
        # Acrobat still shows the tier at a glance above each comment. A row
        # direction, when present, prefixes that head.
        tier = row.get("materiality", "")
        direction = row.get("direction", "")
        provision = row.get("provision", "")
        label = f"{direction} · {tier}" if direction else tier
        subject = (
            f"{label} — {provision}" if label and provision else (provision or label)
        )

        color = MATERIALITY_COLORS.get(tier, "FFF3CD")
        for page_no, quads in quads_by_page.items():
            annotations[page_no].append(
                {
                    "quads": quads,
                    "color": color,
                    "comment": comment,
                    "subject": subject,
                }
            )

    return annotations, unplaceable


def collect_quarantine_notes(extract, heights):
    """One sticky note per quarantined paragraph.

    A quarantined paragraph was never analysed. In a Word table that absence is
    visible; in a PDF an un-annotated page silently reads as 'reviewed and
    nothing material here', which is the more dangerous failure for a document
    that may circulate. So these are stamped explicitly.
    """
    notes = defaultdict(list)
    for q in extract.get("quarantined", []):
        page_no = q.get("page")
        height = heights.get(page_no)
        if height is None:
            continue
        bbox = q.get("page_bbox")
        if bbox:
            x0, top, _x1, _bottom = bbox
            x, y = x0, height - top
        else:
            x, y = 36.0, height - 36.0
        notes[page_no].append(
            {
                "point": (x, y),
                "comment": (
                    "NOT MACHINE-ANALYSED — MANUAL REVIEW REQUIRED\n\n"
                    f"Reason: {q.get('reason', 'unknown')}\n"
                    f"Preview: {q.get('raw_text_preview', '')[:300]}"
                ),
            }
        )
    return notes


def write_annotated_pdf(src_pdf, out_path, annotations, quarantine_notes, page_base):
    reader = PdfReader(src_pdf)
    writer = PdfWriter()
    writer.append(reader)

    written = 0
    for page_no, specs in annotations.items():
        idx = page_no - page_base
        if not (0 <= idx < len(writer.pages)):
            print(f"  ! page {page_no} out of range; skipped", file=sys.stderr)
            continue
        for spec in specs:
            quads = spec["quads"]
            annot = Highlight(
                rect=union_rect(quads),
                # Must be a pypdf ArrayObject of FloatObject: handing pypdf a
                # plain Python list raises AttributeError at save time.
                quad_points=ArrayObject([FloatObject(v) for v in quads]),
                highlight_color=spec["color"],
                printing=True,
            )
            annot[NameObject("/Contents")] = TextStringObject(spec["comment"])
            annot[NameObject("/T")] = TextStringObject(ANNOTATION_AUTHOR)
            if spec["subject"]:
                annot[NameObject("/Subj")] = TextStringObject(spec["subject"])
            writer.add_annotation(page_number=idx, annotation=annot)
            written += 1

    for page_no, specs in quarantine_notes.items():
        idx = page_no - page_base
        if not (0 <= idx < len(writer.pages)):
            continue
        for spec in specs:
            x, y = spec["point"]
            note = Text(rect=(x, y - 20, x + 20, y), text=spec["comment"], open=False)
            note[NameObject("/T")] = TextStringObject(ANNOTATION_AUTHOR)
            note[NameObject("/Subj")] = TextStringObject("Quarantined — not analysed")
            note[NameObject("/C")] = ArrayObject(
                [
                    FloatObject(int(QUARANTINE_COLOR[i : i + 2], 16) / 255.0)
                    for i in (0, 2, 4)
                ]
            )
            writer.add_annotation(page_number=idx, annotation=note)
            written += 1

    with open(out_path, "wb") as f:
        writer.write(f)

    return written


def self_check(out_path, expected, source_pages):
    """Re-open the saved file and prove the annotations are really in it.

    Post-save verification: a silently broken deliverable is worse than a
    loud failure, because this one gets circulated.
    """
    reader = PdfReader(out_path)
    if len(reader.pages) != source_pages:
        _fail(
            f"self-check: output has {len(reader.pages)} pages, source had "
            f"{source_pages}. Refusing to ship a truncated document."
        )

    found = 0
    for page in reader.pages:
        annots = page.get("/Annots") or []
        for ref in annots:
            obj = ref.get_object()
            if obj.get("/Subtype") in ("/Highlight", "/Text"):
                if obj.get("/T") == ANNOTATION_AUTHOR:
                    found += 1

    if found != expected:
        _fail(
            f"self-check: wrote {expected} annotations but only {found} survived "
            "the save. The output is not trustworthy."
        )
    return found


def check_contract(pdf_path, pairs_path):
    """Validate a parse_redline_pdf.py extract against the geometry contract.

    Exists so the parser session can confirm its own output is consumable
    without a round trip through the annotator session. Returns a process exit
    code: 0 conforming, 1 not.

    Checks the failure modes that produce a valid-looking JSON and a visibly
    wrong PDF — missing page heights, boxes outside the page, and top-down vs
    bottom-up coordinate confusion — plus the one that silently degrades
    output quality: per-role boxes with no provision extent.
    """
    errors, warnings = [], []

    with open(pairs_path, encoding="utf-8") as f:
        extract = json.load(f)

    src_pages = PdfReader(pdf_path).pages
    n_src = len(src_pages)

    pages = extract.get("pages")
    if not pages:
        errors.append(
            "missing top-level 'pages'; page heights are required for the Y-flip"
        )
        heights = {}
    else:
        if len(pages) != n_src:
            errors.append(f"'pages' has {len(pages)} entries but the PDF has {n_src}")
        heights = {}
        for p in pages:
            for key in ("number", "width", "height", "rotation"):
                if key not in p:
                    errors.append(f"page entry {p.get('number', '?')} missing '{key}'")
            if "number" in p and "height" in p:
                heights[p["number"]] = float(p["height"])
            if p.get("rotation"):
                warnings.append(
                    f"page {p.get('number')} has rotation={p['rotation']}; "
                    "the annotator assumes 0 and would place quads incorrectly"
                )

    pairs = extract.get("pairs", [])
    if not pairs:
        errors.append("no 'pairs' in extract")

    seen, no_id, changed, with_prov, with_roles, boxless = set(), 0, 0, 0, 0, 0
    for pair in pairs:
        pid = pair.get("pair_id")
        if pid is None:
            no_id += 1
            continue
        if pid in seen:
            errors.append(f"duplicate pair_id {pid!r}")
        seen.add(pid)

        if not pair.get("changed"):
            continue
        changed += 1

        boxes = pair.get("boxes") or {}
        if boxes.get("provision"):
            with_prov += 1
        elif boxes.get("del") or boxes.get("ins"):
            with_roles += 1
        else:
            boxless += 1
            continue

        page_no = pair.get("page")
        height = heights.get(page_no)
        for box in provision_boxes(boxes):
            if not (isinstance(box, (list, tuple)) and len(box) == 4):
                errors.append(f"{pid}: box is not [x0, top, x1, bottom]: {box!r}")
                continue
            x0, top, x1, bottom = box
            if x1 <= x0 or bottom <= top:
                errors.append(
                    f"{pid}: degenerate box {box!r} (need x0<x1 and top<bottom)"
                )
            if height and (top > height or bottom > height):
                errors.append(f"{pid}: box {box!r} exceeds page height {height}")

    if no_id:
        errors.append(f"{no_id} pair(s) have no 'pair_id'")
    if boxless:
        errors.append(
            f"{boxless} changed pair(s) carry no boxes and cannot be highlighted"
        )
    if with_roles and not with_prov:
        warnings.append(
            f"{with_roles} changed pair(s) supply only per-role del/ins boxes and no "
            "'provision' extent. Accepted — the annotator expands them to full line "
            "extents itself, so the highlight still renders as one continuous band. "
            "Emitting boxes['provision'] directly would let it skip re-reading the "
            "PDF, but nothing is lost by not doing so."
        )

    # Top-down vs bottom-up confusion: in pdfplumber space the first changed
    # thing on a page sits near the TOP, so small `top` values should exist. If
    # every box hugs the bottom of the page, coordinates were probably already
    # flipped, and the annotator would flip them a second time.
    tops = [
        b[1]
        for p in pairs
        if p.get("changed") and p.get("boxes")
        for b in provision_boxes(p["boxes"])
        if isinstance(b, (list, tuple)) and len(b) == 4
    ]
    if tops and heights:
        median_page_h = sorted(heights.values())[len(heights) // 2]
        if min(tops) > median_page_h * 0.75:
            warnings.append(
                "every box sits in the bottom quarter of its page. If these are "
                "already bottom-up PDF coordinates, remove the flip — the annotator "
                "expects pdfplumber's top-down 'top'/'bottom'."
            )

    quarantined = extract.get("quarantined", [])
    missing_qbox = sum(1 for q in quarantined if not q.get("page_bbox"))
    if missing_qbox:
        warnings.append(
            f"{missing_qbox} quarantine entr(ies) lack 'page_bbox'; their sticky note "
            "falls back to the page's top-left corner"
        )

    print(f"Contract check: {pairs_path}")
    print(f"  pages           {len(pages) if pages else 0} (PDF has {n_src})")
    print(f"  pairs           {len(pairs)}  ({changed} changed)")
    print(
        f"  provision boxes {with_prov}   per-role only {with_roles}   none {boxless}"
    )
    print(f"  quarantined     {len(quarantined)}")
    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  FAIL  {e}")
    print(
        "\n"
        + (
            "CONFORMS — annotator can consume this."
            if not errors
            else f"NOT CONFORMING — {len(errors)} error(s)."
        )
    )
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(
        description="Stamp materiality highlights and comments into a redline PDF."
    )
    parser.add_argument("pdf", help="The redline PDF that was parsed.")
    parser.add_argument(
        "--pairs", required=True, help="parse_redline_pdf.py output JSON."
    )
    parser.add_argument("--rows", help="Rows JSON (the analysis layer's output).")
    parser.add_argument("--out", help="Output path for the annotated PDF.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be annotated; write nothing.",
    )
    parser.add_argument(
        "--check-contract",
        action="store_true",
        help="Validate --pairs against the geometry contract and exit. Needs no "
        "rows. Run this from the parser session to confirm its output is "
        "consumable before handing it over.",
    )
    args = parser.parse_args()

    if args.check_contract:
        sys.exit(check_contract(args.pdf, args.pairs))

    if not args.rows:
        _fail("--rows is required unless --check-contract is given.")
    if not args.dry_run and not args.out:
        _fail("--out is required unless --dry-run is given.")

    gate = require_gate(args.pairs)
    print(gate_state_line(gate))

    extract, by_id, heights, page_base = load_geometry(args.pairs)

    with open(args.rows, encoding="utf-8") as f:
        rows = json.load(f)
    if not isinstance(rows, list):
        _fail(f"{args.rows} must contain a JSON list of row dicts.")

    source_pages = len(PdfReader(args.pdf).pages)
    extract_pages = extract.get("stats", {}).get("pages")
    if extract_pages and extract_pages != source_pages:
        _fail(
            f"{args.pdf} has {source_pages} pages but the extract was built from "
            f"a {extract_pages}-page document. These are different files; every "
            "highlight would land at a meaningless offset."
        )

    wanted = {p["page"] for p in by_id.values()}
    extents = page_line_extents(args.pdf, wanted, page_base)
    annotations, unplaceable = collect_annotations(rows, by_id, heights, extents)
    quarantine_notes = collect_quarantine_notes(extract, heights)

    total = sum(len(v) for v in annotations.values())
    total_q = sum(len(v) for v in quarantine_notes.values())

    print(f"Rows supplied:        {len(rows)}")
    print(f"Highlights to place:  {total} across {len(annotations)} page(s)")
    print(f"Quarantine notes:     {total_q}")
    if unplaceable:
        print(f"Unplaceable rows:     {len(unplaceable)}")
        for provision, reason in unplaceable:
            print(f"  ! {provision} — {reason}")

    if args.dry_run:
        return

    if total == 0 and total_q == 0:
        sys.exit(2)

    written = write_annotated_pdf(
        args.pdf, args.out, annotations, quarantine_notes, page_base
    )
    verified = self_check(args.out, written, source_pages)
    print(f"\nWrote {verified} annotations to {args.out} (verified after save).")
    if unplaceable:
        print(
            "Surface the unplaceable rows above to the user — they were "
            "analysed but are NOT marked in this PDF."
        )


if __name__ == "__main__":
    main()
