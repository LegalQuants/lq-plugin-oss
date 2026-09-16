#!/usr/bin/env python3
"""
parse_redline_pdf.py — extract structured change data from an
already-rendered redline PDF (a marked-up compare document exported by a
redline/compare tool: strikethrough = deleted text, underline = inserted
text, colored by revision author/tool).

PDFs carry no semantic track-changes metadata, so this reconstructs it from
visual formatting: text color plus the position of thin drawn lines relative
to each text span (mid-height line = strikethrough, baseline line =
underline). Everything is calibrated per document — no color's meaning is
hardcoded, because different firms/tools use different conventions.

Runs on `pdfplumber` rather than PyMuPDF/`fitz`. The script requires no network
access, but it can run only when `pdfplumber` is already available in the host.

What it handles (each learned from real-world redlines):
  - Per-document color calibration: the dominant color is body text; other
    colors are classified as del/ins by their strikethrough/underline
    geometry. A colour that carries no strike or underline anywhere is never
    counted as a change on its own: coloured headings and house-style text
    are the common case, and calling them insertions is a false positive.
    Such colours are reported as undecorated so the lawyer can confirm, and
    `--insert-color` / `--delete-color` count one when the compare tool
    really does render block insertions or deletions without decoration.
    Decoration evidence overrides both span-length and dominance heuristics:
    a color whose spans are frequently struck/underlined is always revision
    markup, never body text or structural noise.
  - Color-matched decorators: a strike/underline line is only counted for a
    span when the line's own color matches the span's text color (red strike
    for red deletion, blue underline for blue insertion). This is what keeps
    the many stray black hairline segments pdfplumber surfaces from being
    misread as decorations on body text — a black line can only ever match
    black body text, which is the default color and never gets a revision
    role. (PyMuPDF's get_drawings didn't surface those stray segments, so the
    old code used pure geometry; pdfplumber exposes more raw vector data, so
    color-matching is the equivalent safeguard.)
  - Single-colour conventions: one revision colour carrying BOTH mark kinds
    (strikes = deletions, underlines = insertions) calibrates as "mixed" and
    resolves role below word level via decoration x-ranges, splitting per
    char when a struck word and an inserted word share one extracted word
    ("procuredirect"). Learned from a real Litera compare regression.
  - Page furniture: identical (color, text) recurring across many pages
    (running headers, VDR watermarks like a downloader's name/timestamp) is
    excluded before calibration so it can't poison the color statistics.
  - Structural noise: colors whose spans average <2 words (TOC dot-leader
    entries, auto-numbered section labels) are never treated as revisions —
    unless they carry substantial strike/underline evidence, which fragmen-
    ted real revisions do (fragmented insertions average <2 words/span).
  - Summary-page validation: when the compare tool's own scoreboard is
    present on the last page (Litera "Changes: Add N / Delete N"), the
    calibrated del/ins mark counts are cross-checked against it and a
    SUSPECT warning is printed on order-of-magnitude disagreement.
  - Drafting-note asides ("Note to ...") are excluded from both sides.
  - Compare-tool move annotations ("Moved from", "Table Delete", ...) —
    double-decorated meta-labels about relocated passages — are recognized
    and reported separately (a moved provision is itself worth flagging),
    not folded into the text.
  - Reading-order scrambling: rare pages where the PDF's internal text order
    doesn't match visual order produce letter-spaced garbage. A cheap
    token-shape detector flags these, one automatic recovery (geometric
    re-sort) is attempted, and anything still garbled is QUARANTINED and
    reported — never silently included or silently dropped. Quarantine is
    per paragraph block, so one bad clause doesn't take a page down with it.

Usage:

    # 1. ALWAYS calibrate first and show the user what was detected:
    python3 parse_redline_pdf.py redline.pdf --calibrate-only

    # 2. Then run the full extraction:
    python3 parse_redline_pdf.py redline.pdf output.json
    python3 parse_redline_pdf.py redline.pdf output.json --body-start-page 5

Options:
    --calibrate-only      Print detected colors/roles/furniture and exit.
                          Review this with the user before extracting.
    --body-start-page N   0-indexed first page of the document body; use to
                          skip cover pages whose styling differs (default 0).
    --note-pattern REGEX  Regex for drafting-note asides to exclude
                          (default: "^\\s*Note to\\b", case-insensitive).

Output JSON shape:

    {
      "source_pdf": "...",
      "pages": [
        {"number": 6, "width": 612.0, "height": 792.0, "rotation": 0},
        ...                                  # one per page, 0-indexed number
      ],
      "calibration": {
        "default_color": 0,
        "roles": {"16711680": "del", "255": "ins"},
        "furniture_examples": ["<downloader name>", "<running header>"],
        "excluded_structural_colors": [65536]
      },
      "pairs": [
        {"pair_id": "p6-004", "page": 6,
         "old_text": "...", "new_text": "...",
         "boxes": {"del": [[x0, top, x1, bottom], ...],
                   "ins": [[x0, top, x1, bottom], ...]},
         "changed": true},
        ...
      ],
      "move_annotations": [{"page": 85, "label": "Moved from"}],
      "quarantined": [
        {"page": 15, "reason": "garbled-after-resort-attempt",
         "raw_text_preview": "T h e M a n a g e r ...",
         "page_bbox": [x0, top, x1, bottom]}
      ],
      "stats": {"pages": 87, "paragraphs": 412, "changed_paragraphs": 32,
                "quarantined_paragraphs": 2}
    }

``pairs`` includes unchanged paragraphs too (changed: false) so downstream
viewers can show full document context. Each pair maps directly onto the
{old_text, new_text} shape the annotation pipeline consumes. QUARANTINED
paragraphs are excluded from pairs — whoever
runs this must surface them to the user for manual review, per the skill's
accuracy rules.

Geometry fields (added for downstream PDF annotation — consumers that only
read old_text/new_text can ignore them):
  - ``pages``    — page geometry for every page. **All bbox coordinates below
                   are pdfplumber's top-down space** (``top``/``bottom`` are
                   measured from the top of the page). PDF annotation space is
                   bottom-up, so a consumer converts with
                   ``pdf_y = page_height - top`` using this page's ``height``.
                   ``number`` is the 0-indexed page index and matches each
                   pair's ``page`` (and pypdf's ``reader.pages[number]``).
  - ``pair_id``  — stable per-run id ``p<page>-<ordinal>`` (ordinal counts
                   emitted pairs within a page). Lets a downstream table row
                   reference the exact pair(s) its geometry came from.
  - ``boxes``    — deleted-text and inserted-text boxes for this pair, ONE BOX
                   PER LINE (per span), never one merged paragraph box: a
                   highlight is a list of per-line quads, so a multi-line
                   change needs its lines kept separate. Empty lists for an
                   unchanged pair.
  - ``page_bbox``— on each quarantined entry, the region the unreadable
                   paragraph occupies, so its spot is still flaggable on-page.

Requires: pdfplumber.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from typing import TypedDict

try:
    import pdfplumber
except ImportError:
    print(
        "Error: pdfplumber is required but is not available in this environment.",
        file=sys.stderr,
    )
    sys.exit(1)

# Short numeric/lettered labels e.g. "3.7", "(iii)", "Exhibit A)", "1.2.3" —
# auto-numbered fields and enumerators, not authored prose.
STRUCTURAL_LABEL = re.compile(
    r"^\s*[\(\[]?[A-Za-z0-9]{1,3}(\.[A-Za-z0-9]{1,3}){0,3}[\)\].]?\s*$"
    r"|^\s*Exhibit\s+[A-Z0-9]+[\)\.]?\s*$",
    re.IGNORECASE,
)

# Compare-tool meta-labels marking relocated passages.
MOVE_LABEL = re.compile(
    r"^\s*(moved?\s+(from|to)|deletion|delete|insertion|"
    r"table\s+(delete|insert|moves?\s+(from|to)))\s*$",
    re.IGNORECASE,
)

MIN_AVG_WORDS_PER_SPAN = 2.0  # below this a color is structural, not prose
MIN_WORDS_FOR_ROLE = 15  # min word volume before an undecorated colour is reported
DECORATION_MARK_FRAC = 0.2  # >= this fraction of exclusively struck/underlined
# spans means the color carries revision markup —
# it can be neither body text nor structural noise,
# regardless of span length or dominance
FURNITURE_MIN_PAGES = 3  # identical text on >= max(this, 15% of pages) = furniture
FURNITURE_PAGE_FRAC = 0.15
THIN_LINE_MAX_HEIGHT = (
    2.0  # drawn rects/lines thinner than this are strike/underline lines
)
LINE_Y_TOL = 2.0  # y-distance tolerance matching a line to a span
LINE_MIN_OVERLAP = 0.5  # min horizontal overlap fraction span<->line
LINE_OVERLAP_FRAC = (
    0.5  # a word joins the current line if it overlaps it vertically by >= this
)
PARA_GAP_ABS = 3.0  # vertical gap (pts) above which a new line starts a new block
PARA_GAP_FRAC = 0.6  # ...or this fraction of the line's own height, whichever is larger
WORD_GAP_PT = 1.0  # horizontal gap (pts) between consecutive same-line
# words that means a real space char was there —
# colour changes split words, and mid-word splits
# have ~0 gap while real spaces are wider


# ---------------------------------------------------------------------------
# Color: pdfplumber fill/stroke color -> packed sRGB int (matches PyMuPDF's
# span["color"] values, so calibration output stays comparable across engines)
# ---------------------------------------------------------------------------


def _to_packed(c):
    """Normalize a pdfplumber color (DeviceGray/RGB/CMYK tuple, or None) to a
    packed 0xRRGGBB integer. None -> 0 (black), matching untagged body text."""
    if c is None:
        return 0
    if isinstance(c, (int, float)):
        vals = [float(c)]
    elif isinstance(c, (list, tuple)):
        try:
            vals = [float(x) for x in c]
        except (TypeError, ValueError):
            return 0
    else:
        return 0

    def s(x):  # 0..1 channel -> 0..255, clamped
        return max(0, min(255, int(round(x * 255))))

    if len(vals) == 1:
        v = s(vals[0])
        return (v << 16) | (v << 8) | v
    if len(vals) == 3:
        r, g, b = (s(v) for v in vals)
        return (r << 16) | (g << 8) | b
    if len(vals) == 4:
        cc, m, y, k = vals
        r = s((1 - cc) * (1 - k))
        g = s((1 - m) * (1 - k))
        b = s((1 - y) * (1 - k))
        return (r << 16) | (g << 8) | b
    return 0


# ---------------------------------------------------------------------------
# Geometry: strikethrough / underline detection (color-matched)
# ---------------------------------------------------------------------------


def _build_decorators(page):
    """Thin horizontal decorators on a page as (x0, x1, y_center, color).
    Strikes are usually filled rects, underlines usually stroked lines, but
    both are gathered and disambiguated later by geometry + color."""
    decs = []
    for r in page.rects:
        if r.get("height", 1e9) <= THIN_LINE_MAX_HEIGHT:
            decs.append(
                (
                    r["x0"],
                    r["x1"],
                    (r["top"] + r["bottom"]) / 2,
                    _to_packed(r.get("non_stroking_color")),
                )
            )
    for ln in page.lines:
        if abs(ln["top"] - ln["bottom"]) <= THIN_LINE_MAX_HEIGHT:
            decs.append(
                (
                    ln["x0"],
                    ln["x1"],
                    (ln["top"] + ln["bottom"]) / 2,
                    _to_packed(ln.get("stroking_color")),
                )
            )
    return decs


def _decorations(decorators, bbox, color):
    """Return (has_mid, has_base): a color-matched thin line at the span's
    mid-height / baseline. Only decorators whose own color equals the span's
    text color count — this is what filters out stray black hairlines.

    Each matching line is assigned to mid OR baseline by nearest position, not
    both: on small text the mid and baseline are only a point or two apart, so
    a single underline must not register as a strikethrough too (that would
    misread an insertion as an ambiguous/moved span). A span only ends up with
    both when there are genuinely two separate lines on it (a real
    double-decorated move label)."""
    x0, y0, x1, y1 = bbox
    mid = (y0 + y1) / 2
    width = max(x1 - x0, 1e-6)
    has_mid = has_base = False
    for dx0, dx1, dy, dcol in decorators:
        if dcol != color:
            continue
        overlap = max(0.0, min(dx1, x1) - max(dx0, x0))
        if overlap / width < LINE_MIN_OVERLAP:
            continue
        d_mid = abs(dy - mid)
        d_base = abs(dy - y1)
        if d_mid >= LINE_Y_TOL and d_base >= LINE_Y_TOL:
            continue  # too far from either to be this span's decoration
        if d_mid < d_base:
            has_mid = True
        else:
            has_base = True
    return has_mid, has_base


# ---------------------------------------------------------------------------
# Garble detection (reading-order scrambling safety net)
# ---------------------------------------------------------------------------


def _decoration_ranges(decorators, bbox, color):
    """Color-matched decorator x-ranges over a word, split into
    (mid_ranges, base_ranges), each a list of (x0, x1) clipped to the word.

    Unlike _decorations' >=50%-of-width rule, ANY overlap >= 2pt counts here:
    this feeds the single-colour convention's per-word/per-char role split,
    where a strike may cover only the first half of what pdfplumber sees as
    one word ("procuredirect" — deleted and inserted text adjacent with no
    space character between them)."""
    x0, y0, x1, y1 = bbox
    mid = (y0 + y1) / 2
    mid_ranges, base_ranges = [], []
    for dx0, dx1, dy, dcol in decorators:
        if dcol != color:
            continue
        ov0, ov1 = max(dx0, x0), min(dx1, x1)
        if ov1 - ov0 < 2.0:
            continue
        d_mid = abs(dy - mid)
        d_base = abs(dy - y1)
        if d_mid >= LINE_Y_TOL and d_base >= LINE_Y_TOL:
            continue
        (mid_ranges if d_mid < d_base else base_ranges).append((ov0, ov1))
    return mid_ranges, base_ranges


def _garble_metrics(text):
    tokens = [t for t in text.split() if t]
    if len(tokens) < 6:
        return None  # too short to judge
    avg_len = sum(len(t) for t in tokens) / len(tokens)
    single_frac = sum(1 for t in tokens if len(t) == 1) / len(tokens)
    return avg_len, single_frac


def _is_garbled(text):
    m = _garble_metrics(text)
    if m is None:
        return False
    avg_len, single_frac = m
    return avg_len < 2.3 or single_frac > 0.35


# ---------------------------------------------------------------------------
# Extraction (pdfplumber): chars -> spans -> lines -> paragraph blocks
# ---------------------------------------------------------------------------


def _vert_overlap(top1, bot1, top2, bot2):
    """Fraction of the shorter box's height that the two vertical spans share."""
    ov = max(0.0, min(bot1, bot2) - max(top1, top2))
    h = min(bot1 - top1, bot2 - top2)
    return ov / h if h > 0 else 0.0


def _line_to_spans(words, decorators, page, text_pages, page_chars):
    """One visual line's words -> spans (runs of same text color). Consecutive
    words of the same color merge into one span; a color change starts a new
    span. Words arrive in the PDF's own reading order, so an inline tracked
    insertion stays a contiguous run instead of interleaving with the text it
    was inserted into."""
    spans = []
    cur_words = []
    color = None
    bbox = None  # [x0, top, x1, bottom]
    last_x1 = None  # x1 of the previous word on this line, any colour
    cur_gap = False  # visible gap between that word and this span's first word

    def flush():
        nonlocal cur_words, color, bbox, cur_gap
        if cur_words and color is not None and bbox is not None:
            text = " ".join(w["text"] for w in cur_words)
            if text.strip():
                has_mid, has_base = _decorations(decorators, bbox, color)
                # Per-word decoration RANGES, kept alongside the span-level
                # flags: the single-colour convention (one revision colour
                # whose strikes mean deletion and underlines mean insertion)
                # resolves role below word level — deleted and inserted text
                # can sit adjacent with no space character between them, so
                # pdfplumber sees ONE word ("procuredirect") whose first half
                # is struck and second half underlined. Ranges + per-char
                # x-positions let reconstruction split that word correctly.
                # Chars are only gathered for words that actually carry both
                # mark kinds (rare), keeping the common path cheap.
                word_marks = []
                for w in cur_words:
                    wb = (w["x0"], w["top"], w["x1"], w["bottom"])
                    midr, baser = _decoration_ranges(decorators, wb, color)
                    entry = {
                        "text": w["text"],
                        "bbox": wb,
                        "mid_ranges": midr,
                        "base_ranges": baser,
                        "chars": None,
                    }
                    if midr and baser and page_chars is not None:
                        entry["chars"] = [
                            (c["text"], c["x0"], c["x1"])
                            for c in page_chars
                            if (
                                c["x0"] >= wb[0] - 0.5
                                and c["x1"] <= wb[2] + 0.5
                                and c["top"] < wb[3]
                                and c["bottom"] > wb[1]
                                and c["text"].strip()
                            )
                        ]
                        entry["chars"].sort(key=lambda t: t[1])
                    word_marks.append(entry)
                spans.append(
                    {
                        "text": text,
                        "color": color,
                        "bbox": (bbox[0], bbox[1], bbox[2], bbox[3]),
                        "has_mid": has_mid,
                        "has_base": has_base,
                        "word_marks": word_marks,
                        "gap_before": cur_gap,
                    }
                )
                text_pages[(color, text.strip())].add(page)
        cur_words = []
        color = None
        bbox = None
        cur_gap = False

    for w in words:
        col = _to_packed(w.get("non_stroking_color"))
        if color is not None and col != color:
            flush()
        if bbox is None:
            color = col
            bbox = [w["x0"], w["top"], w["x1"], w["bottom"]]
            cur_gap = last_x1 is not None and (w["x0"] - last_x1) > WORD_GAP_PT
        else:
            bbox[0] = min(bbox[0], w["x0"])
            bbox[1] = min(bbox[1], w["top"])
            bbox[2] = max(bbox[2], w["x1"])
            bbox[3] = max(bbox[3], w["bottom"])
        cur_words.append(w)
        last_x1 = w["x1"]
    flush()
    if spans:
        spans[-1]["eol"] = True
    return spans


class VisualLine(TypedDict):
    words: list
    top: float
    bottom: float


def _collect_spans(pdf, body_start_page, body_end_page=None):
    """Pass 1: every non-empty span with color + line geometry, grouped by
    paragraph block so quarantine can work at paragraph granularity.

    pdfplumber gives flat characters, so structure is rebuilt here — but using
    the PDF's native character flow, not a geometric re-sort:
      - `extract_words(use_text_flow=True, ...)` yields words in reading order,
        each a single color (color changes split words), so inline tracked
        insertions rendered at a slightly offset baseline don't scramble.
      - words -> visual lines by VERTICAL OVERLAP (an offset insertion still
        overlaps its line, so it stays put; a genuine next line does not).
      - lines -> paragraph blocks where the vertical gap between lines exceeds
        a leading-sized threshold."""
    blocks = []  # list of {"page": int, "spans": [span, ...]}
    text_pages = defaultdict(set)  # (color, text) -> pages seen on
    pages = pdf.pages
    end = len(pages) if body_end_page is None else min(body_end_page + 1, len(pages))
    for pno in range(body_start_page, end):
        page = pages[pno]
        words = page.extract_words(
            use_text_flow=True,
            extra_attrs=["non_stroking_color"],
            keep_blank_chars=False,
        )
        if not words:
            continue
        decorators = _build_decorators(page)
        page_chars = page.chars

        # words -> visual lines (vertical-overlap grouping, flow order preserved)
        lines: list[VisualLine] = []
        cur = []
        cur_top = cur_bottom = None
        for w in words:
            top, bottom = float(w["top"]), float(w["bottom"])
            if (
                cur
                and cur_top is not None
                and cur_bottom is not None
                and _vert_overlap(top, bottom, cur_top, cur_bottom) < LINE_OVERLAP_FRAC
            ):
                lines.append({"words": cur, "top": cur_top, "bottom": cur_bottom})
                cur = []
                cur_top = cur_bottom = None
            cur.append(w)
            cur_top = top if cur_top is None else min(cur_top, top)
            cur_bottom = bottom if cur_bottom is None else max(cur_bottom, bottom)
        if cur and cur_top is not None and cur_bottom is not None:
            lines.append({"words": cur, "top": cur_top, "bottom": cur_bottom})

        # lines -> paragraph blocks (split on vertical gaps)
        block_lines = []
        prev_bottom = None
        for L in lines:
            if prev_bottom is not None:
                gap = L["top"] - prev_bottom
                lh = max(L["bottom"] - L["top"], 1e-6)
                if gap > max(PARA_GAP_ABS, PARA_GAP_FRAC * lh):
                    _emit_block(
                        blocks, pno, block_lines, decorators, text_pages, page_chars
                    )
                    block_lines = []
            block_lines.append(L)
            prev_bottom = L["bottom"]
        _emit_block(blocks, pno, block_lines, decorators, text_pages, page_chars)

    return blocks, text_pages


def _emit_block(blocks, pno, block_lines, decorators, text_pages, page_chars=None):
    """Turn a run of consecutive lines into one paragraph block of spans."""
    if not block_lines:
        return
    block_spans = []
    for L in block_lines:
        block_spans.extend(
            _line_to_spans(L["words"], decorators, pno, text_pages, page_chars)
        )
    if block_spans:
        blocks.append({"page": pno, "spans": block_spans})


def _calibrate(blocks, text_pages, n_pages):
    """Decide which colors are revision markup and what role each plays."""
    furniture_threshold = max(FURNITURE_MIN_PAGES, FURNITURE_PAGE_FRAC * n_pages)
    furniture_keys = {
        k for k, pages in text_pages.items() if len(pages) >= furniture_threshold
    }

    color_stats = defaultdict(Counter)
    color_words = Counter()
    color_samples = {}
    for block in blocks:
        for s in block["spans"]:
            if (s["color"], s["text"].strip()) in furniture_keys:
                continue
            st = color_stats[s["color"]]
            if s["color"] not in color_samples and len(s["text"].split()) >= 2:
                color_samples[s["color"]] = s["text"].strip()[:80]
            st["total"] += 1
            color_words[s["color"]] += len(s["text"].split())
            if s["has_mid"] and not s["has_base"]:
                st["mid"] += 1
            elif s["has_base"] and not s["has_mid"]:
                st["base"] += 1
            elif s["has_mid"] and s["has_base"]:
                st["both"] += 1
            else:
                st["none"] += 1

    if not color_stats:
        raise RuntimeError("no text spans found — is this a scanned/image-only PDF?")

    # A color whose spans are frequently struck through or underlined is
    # revision markup, whatever its other stats say. Span length and dominance
    # must not override decoration evidence: fragmented insertions average <2
    # words/span (real revision colors were wrongly discarded as "structural"),
    # and a mostly-deleted document can make the deletion color the most common
    # one (it was wrongly crowned body text, inverting every role).
    def _mark_frac(color):
        st = color_stats[color]
        return (st["mid"] + st["base"]) / max(st["total"], 1)

    body_candidates = [c for c in color_stats if _mark_frac(c) < DECORATION_MARK_FRAC]
    default_color = max(
        body_candidates or list(color_stats), key=lambda c: color_stats[c]["total"]
    )

    structural_colors = []
    candidates = {}
    for color, st in color_stats.items():
        if color == default_color:
            continue
        if (
            color_words[color] / max(st["total"], 1) < MIN_AVG_WORDS_PER_SPAN
            and _mark_frac(color) < DECORATION_MARK_FRAC
        ):
            structural_colors.append(color)
            continue
        candidates[color] = st

    roles = {}
    undecided = []
    for color, st in candidates.items():
        if (
            st["mid"] >= 2
            and st["base"] >= 2
            and min(st["mid"], st["base"]) >= 0.1 * max(st["mid"], st["base"])
        ):
            # Single-colour convention: ONE revision colour whose strikes mean
            # deletion and underlines mean insertion (a common Litera default).
            # Both exclusive mark kinds present in volume across DIFFERENT
            # spans — distinct from a moved colour, whose spans carry both
            # marks on the SAME text (span-level "both"; still confirmed with
            # the user and overridable via --moved-color, which wins over this).
            # The kinds must also be roughly balanced (>=10%): a colour with
            # 882 strikes and 3 stray underlines is a deletion colour, not a
            # mixed convention. Role is resolved per WORD at reconstruction
            # time.
            roles[color] = "mixed"
        elif st["mid"] > st["base"] and st["mid"] > 0:
            roles[color] = "del"
        elif st["base"] > st["mid"] and st["base"] > 0:
            roles[color] = "ins"
        else:
            undecided.append(color)

    # Undecorated colours: prose-volume text in a colour that is never struck
    # or underlined. Pure blue without an underline and pure red without a
    # strikethrough are not changes — coloured headings and house styles look
    # exactly like this — so they get no role. They are reported so the lawyer
    # can confirm, and `--insert-color` / `--delete-color` count one when the
    # compare tool really does render block changes without decoration.
    undecided.sort(key=lambda c: -color_words[c])
    undecorated = [c for c in undecided if color_words[c] >= MIN_WORDS_FOR_ROLE]

    return {
        "default_color": default_color,
        "roles": roles,
        "furniture_keys": furniture_keys,
        "structural_colors": structural_colors,
        "undecorated_colors": undecorated,
        "color_samples": color_samples,
        "color_stats": {c: dict(st) for c, st in color_stats.items()},
        "color_words": dict(color_words),
    }


# Litera-style scoreboard on the compare's last page:
#   "Changes:\nAdd\n53\nDelete\n37\nMove From\n0..."
# Label on one line, count on the next; the main Add/Delete precede the
# Table Insert/Table Delete rows, so the first regex match is the main one.
_SUMMARY_ADD = re.compile(r"^\s*Add\s*$\s*(\d+)", re.MULTILINE)
_SUMMARY_DEL = re.compile(r"^\s*Delete\s*$\s*(\d+)", re.MULTILINE)


def _summary_totals(last_page_text):
    """Compare-tool scoreboard totals from the last page, or None."""
    if not last_page_text or "Changes:" not in last_page_text:
        return None
    add = _SUMMARY_ADD.search(last_page_text)
    delete = _SUMMARY_DEL.search(last_page_text)
    if not add and not delete:
        return None
    return {
        "add": int(add.group(1)) if add else None,
        "delete": int(delete.group(1)) if delete else None,
    }


def _validate_calibration(cal, summary):
    """Cross-check calibration for the two ways it can silently produce
    nothing: no revision colours found at all (works without a scoreboard —
    covers producers that print no totals), and calibrated mark counts
    disagreeing with the compare tool's scoreboard by an order of magnitude
    (scoreboard = change operations, marks = decorated spans, so this only
    fires when a role the scoreboard says is busy came out nearly empty).
    Returns a list of warning strings."""
    warnings = []
    if not cal["roles"]:
        hint = ""
        if cal.get("undecorated_colors"):
            hint = (
                " Undecorated colours were found; if the compare tool marks "
                "changes by colour alone, re-run with --insert-color / "
                "--delete-color."
            )
        warnings.append(
            "No revision colours calibrated at all — every colour was "
            "classified as body text, structural noise or undecorated. If "
            "this document is a compare/redline, the colour convention was "
            "likely misread; render a page and check before trusting an "
            "empty extraction." + hint
        )
    if not summary:
        return warnings
    roles = cal["roles"]
    del_marks = sum(
        st.get("mid", 0)
        for c, st in cal["color_stats"].items()
        if roles.get(c) in ("del", "mixed")
    )
    ins_marks = sum(
        st.get("base", 0)
        for c, st in cal["color_stats"].items()
        if roles.get(c) in ("ins", "mixed")
    )
    if (
        summary.get("delete")
        and summary["delete"] >= 10
        and del_marks < summary["delete"] / 10
    ):
        warnings.append(
            f"SUSPECT calibration: scoreboard reports {summary['delete']} "
            f"deletions but calibrated roles yield only {del_marks} struck "
            f"spans — a deletion color was likely misclassified (structural "
            f"or body). Review the color table above against the rendered PDF."
        )
    if summary.get("add") and summary["add"] >= 10 and ins_marks < summary["add"] / 10:
        warnings.append(
            f"SUSPECT calibration: scoreboard reports {summary['add']} "
            f"insertions but calibrated roles yield only {ins_marks} "
            f"underlined spans — an insertion color was likely misclassified "
            f"(structural or body). Review the color table above against the "
            f"rendered PDF."
        )
    return warnings


def _bbox_list(bbox):
    """A span bbox as a rounded [x0, top, x1, bottom] list (top-down coords)."""
    return [round(float(v), 2) for v in bbox]


def _push(parts, text, gap):
    """Append a span's text to old/new parts, restoring the space that a
    colour boundary removed: spans split on colour change, so without this
    'Counterparties' (body) + 'have' (struck) reconstructs as
    'Counterpartieshave'. `gap` is the span's measured gap_before — True only
    when a real space-width gap preceded it, so mid-word splits
    ('procure|direct') stay joined."""
    if gap and parts and not parts[-1].endswith(" "):
        parts.append(" ")
    parts.append(text)


def _reconstruct_block(
    spans, roles, default_color, note_pattern, furniture_keys, move_annotations, page
):
    """Build (old_text, new_text, del_boxes, ins_boxes) for one paragraph block.

    del_boxes / ins_boxes each hold one bbox per contributing span — and a span
    is a single visual line, so these are per-LINE boxes, deliberately NOT
    collapsed into one paragraph-wide box: a highlight annotation is a list of
    per-line quads, and a single merged box over a 3-line change would paint
    the margins between the lines too. Each box is pdfplumber's native top-down
    [x0, top, x1, bottom]; the annotator flips to PDF bottom-up using the page
    height in the top-level `pages` list."""
    old_parts, new_parts = [], []
    del_boxes, ins_boxes = [], []
    for s in spans:
        text = s["text"]
        if (s["color"], text.strip()) in furniture_keys:
            continue
        if note_pattern.match(text):
            continue
        role = roles.get(s["color"]) if s["color"] != default_color else None
        if role == "moved":
            # relocated text (color-coded, per-document override): report as
            # a move, don't fold into old/new so it isn't miscounted as a
            # substantive insertion/deletion.
            stripped = text.strip()
            if stripped:
                move_annotations.append(
                    {"page": page, "label": stripped, "moved_text": True}
                )
            continue
        if role == "mixed":
            # Single-colour convention: role below word level, by decoration.
            # Struck text is deleted, underlined text inserted; adjacent
            # same-role words merge into one run (one highlight box per run).
            # A word can carry BOTH mark kinds on DISJOINT x-ranges — deleted
            # and inserted text adjacent with no space char between them reads
            # as one word ("procuredirect") — and is split per CHAR by which
            # decorator covers each char's x-centre (unresolved chars inherit
            # their neighbour's role). An undecorated word in a revision
            # colour is unchanged text on both sides: colour alone is never a
            # change.
            # NOTE: this must run BEFORE the span-level both-marks branch
            # below — a mixed span has both marks at span level by design.
            run_role = None
            run_texts = []
            run_bbox = None
            # a visible gap before this span must surface as a space on EACH
            # side the span's runs land on (del runs -> old, ins runs -> new)
            gap_old = bool(s.get("gap_before"))
            gap_new = gap_old

            def _flush_run():
                nonlocal run_role, run_texts, run_bbox, gap_old, gap_new
                if run_texts:
                    run_text = " ".join(run_texts)
                    if run_role == "del":
                        _push(old_parts, run_text + " ", gap_old)
                        gap_old = False
                        del_boxes.append(_bbox_list(run_bbox))
                    elif run_role == "ins":
                        _push(new_parts, run_text + " ", gap_new)
                        gap_new = False
                        ins_boxes.append(_bbox_list(run_bbox))
                    else:  # undecorated words in this colour: unchanged
                        _push(old_parts, run_text + " ", gap_old)
                        _push(new_parts, run_text + " ", gap_new)
                        gap_old = gap_new = False
                run_role = None
                run_texts = []
                run_bbox = None

            def _add(piece_role, piece_text, pb):
                nonlocal run_role, run_bbox
                if not piece_text:
                    return
                if piece_role != run_role and run_texts:  # noqa: B023
                    _flush_run()
                run_role = piece_role
                run_texts.append(piece_text)  # noqa: B023
                if run_bbox is None:
                    run_bbox = [pb[0], pb[1], pb[2], pb[3]]
                else:
                    run_bbox = [
                        min(run_bbox[0], pb[0]),
                        min(run_bbox[1], pb[1]),
                        max(run_bbox[2], pb[2]),
                        max(run_bbox[3], pb[3]),
                    ]

            def _covered(cx, ranges):
                return any(a - 0.5 <= cx <= b + 0.5 for a, b in ranges)

            for wm in s.get("word_marks", []):
                midr, baser = wm["mid_ranges"], wm["base_ranges"]
                wb = wm["bbox"]
                if midr and baser and wm.get("chars"):
                    # char-level split
                    char_roles: list[tuple[str | None, str, float, float]] = []
                    for ct, cx0, cx1 in wm["chars"]:
                        x0, x1 = float(cx0), float(cx1)
                        cx = (x0 + x1) / 2
                        if _covered(cx, midr):
                            r = "del"
                        elif _covered(cx, baser):
                            r = "ins"
                        else:
                            r = None
                        char_roles.append((r, str(ct), x0, x1))
                    # unresolved chars inherit: backward fill from previous,
                    # then forward fill for any leading run of Nones
                    filled: list[tuple[str | None, str, float, float]] = []
                    prev = None
                    for role, ct, x0, x1 in char_roles:
                        if role is None:
                            role = prev
                        else:
                            prev = role
                        filled.append((role, ct, x0, x1))
                    nxt = None
                    resolved: list[tuple[str | None, str, float, float]] = []
                    for role, ct, x0, x1 in reversed(filled):
                        if role is None:
                            role = nxt
                        else:
                            nxt = role
                        resolved.append((role, ct, x0, x1))
                    resolved.reverse()
                    # emit role-runs of chars as text pieces
                    piece = []
                    piece_role = None
                    px0 = px1 = None
                    for role, ct, x0, x1 in resolved:
                        r = role or "ins"
                        if piece and r != piece_role:
                            _add(piece_role, "".join(piece), (px0, wb[1], px1, wb[3]))
                            piece = []
                            px0 = px1 = None
                        piece_role = r
                        piece.append(ct)
                        px0 = x0 if px0 is None else min(px0, x0)
                        px1 = x1 if px1 is None else max(px1, x1)
                    if piece:
                        _add(piece_role, "".join(piece), (px0, wb[1], px1, wb[3]))
                elif midr and not baser:
                    _add("del", wm["text"], wb)
                elif baser and not midr:
                    _add("ins", wm["text"], wb)
                elif midr and baser:
                    # both marks but no chars available: fall back to the
                    # larger total coverage, and report the ambiguity
                    mlen = sum(b - a for a, b in midr)
                    blen = sum(b - a for a, b in baser)
                    _add("del" if mlen >= blen else "ins", wm["text"], wb)
                    move_annotations.append(
                        {"page": page, "label": wm["text"].strip(), "ambiguous": True}
                    )
                else:
                    _add(None, wm["text"], wb)
            _flush_run()
            if s.get("eol"):
                if old_parts and not old_parts[-1].endswith(" "):
                    old_parts.append(" ")
                if new_parts and not new_parts[-1].endswith(" "):
                    new_parts.append(" ")
            continue
        if role is not None and s["has_mid"] and s["has_base"]:
            stripped = text.strip()
            if MOVE_LABEL.match(stripped):
                move_annotations.append({"page": page, "label": stripped})
            elif STRUCTURAL_LABEL.match(stripped):
                pass  # auto-numbered field noise, drop by design
            else:
                # genuine ambiguous span inside an otherwise-fine block:
                # keep the block, but record it (handled by caller via marker)
                move_annotations.append(
                    {"page": page, "label": stripped, "ambiguous": True}
                )
            continue
        if role is None:
            _push(old_parts, text, s.get("gap_before"))
            _push(new_parts, text, s.get("gap_before"))
        elif role == "del":
            _push(old_parts, text, s.get("gap_before"))
            del_boxes.append(_bbox_list(s["bbox"]))
        elif role == "ins":
            _push(new_parts, text, s.get("gap_before"))
            ins_boxes.append(_bbox_list(s["bbox"]))
        if s.get("eol"):
            # line break inside the paragraph: keep words on adjacent
            # physical lines from mashing together on reconstruction
            if old_parts and not old_parts[-1].endswith(" "):
                old_parts.append(" ")
            if new_parts and not new_parts[-1].endswith(" "):
                new_parts.append(" ")
    return (
        "".join(old_parts).strip(),
        "".join(new_parts).strip(),
        del_boxes,
        ins_boxes,
    )


def _geometric_resort(spans):
    return sorted(spans, key=lambda s: (round(s["bbox"][1], 0), s["bbox"][0]))


def _union_bbox(spans):
    """[x0, top, x1, bottom] enclosing every span in a block — the region a
    quarantined (unreadable) paragraph occupies, so a reviewer/annotator can
    still flag the spot on the page even though its text couldn't be parsed."""
    return [
        round(min(s["bbox"][0] for s in spans), 2),
        round(min(s["bbox"][1] for s in spans), 2),
        round(max(s["bbox"][2] for s in spans), 2),
        round(max(s["bbox"][3] for s in spans), 2),
    ]


def extract(
    pdf_path,
    body_start_page=0,
    note_pattern_str=r"^\s*Note to\b",
    moved_colors=None,
    body_end_page=None,
    insert_colors=None,
    delete_colors=None,
):
    note_pattern = re.compile(note_pattern_str, re.IGNORECASE)
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        # Page geometry for every page — the annotator needs `height` to convert
        # these top-down pdfplumber coordinates to PDF's bottom-up annotation
        # space, and `rotation` to place quads on rotated pages. `number` is the
        # 0-indexed page index, matching each pair's `page` field and pypdf's
        # reader.pages[number].
        pages_meta = []
        for i, pg in enumerate(pdf.pages):
            pages_meta.append(
                {
                    "number": i,
                    "width": round(float(pg.width), 2),
                    "height": round(float(pg.height), 2),
                    "rotation": int(getattr(pg, "rotation", 0) or 0),
                }
            )
        blocks, text_pages = _collect_spans(pdf, body_start_page, body_end_page)
        last_page_text = pdf.pages[-1].extract_text() or ""
    end = total_pages if body_end_page is None else min(body_end_page + 1, total_pages)
    n_pages = end - body_start_page
    cal = _calibrate(blocks, text_pages, n_pages)
    validation = _validate_calibration(cal, _summary_totals(last_page_text))
    roles = cal["roles"]
    for c in moved_colors or []:
        roles[c] = "moved"
    for c in insert_colors or []:
        roles[c] = "ins"
    for c in delete_colors or []:
        roles[c] = "del"
    undecorated = [
        {
            "color": c,
            "words": cal["color_words"].get(c, 0),
            "sample": cal["color_samples"].get(c, ""),
        }
        for c in cal["undecorated_colors"]
        if c not in roles
    ]
    default_color = cal["default_color"]
    furniture_keys = cal["furniture_keys"]

    pairs = []
    move_annotations = []
    quarantined = []
    changed = 0
    per_page_ord = defaultdict(int)  # stable per-page ordinal for pair_id

    for block in blocks:
        page = block["page"]
        spans = block["spans"]
        old_t, new_t, del_boxes, ins_boxes = _reconstruct_block(
            spans,
            roles,
            default_color,
            note_pattern,
            furniture_keys,
            move_annotations,
            page,
        )
        if not old_t and not new_t:
            continue
        if _is_garbled(old_t) or _is_garbled(new_t):
            # recovery attempt: rebuild in pure visual order
            r_old, r_new, r_del, r_ins = _reconstruct_block(
                _geometric_resort(spans),
                roles,
                default_color,
                note_pattern,
                furniture_keys,
                [],
                page,
            )
            if _is_garbled(r_old) or _is_garbled(r_new):
                quarantined.append(
                    {
                        "page": page,
                        "reason": "garbled-after-resort-attempt",
                        "raw_text_preview": (old_t or new_t)[:200],
                        "page_bbox": _union_bbox(spans),
                    }
                )
                continue
            old_t, new_t, del_boxes, ins_boxes = r_old, r_new, r_del, r_ins
        is_changed = old_t != new_t
        if is_changed:
            changed += 1
        per_page_ord[page] += 1
        pairs.append(
            {
                "pair_id": f"p{page}-{per_page_ord[page]:03d}",
                "page": page,
                "old_text": old_t if old_t else None,
                "new_text": new_t if new_t else None,
                "boxes": {"del": del_boxes, "ins": ins_boxes},
                "changed": is_changed,
            }
        )

    return {
        "source_pdf": str(pdf_path),
        "pages": pages_meta,
        "calibration": {
            "default_color": default_color,
            "roles": {str(c): r for c, r in roles.items()},
            "furniture_examples": sorted({t for (_c, t) in furniture_keys})[:10],
            "excluded_structural_colors": cal["structural_colors"],
            "undecorated_colors": undecorated,
            "validation": validation,
        },
        "pairs": pairs,
        "move_annotations": move_annotations,
        "quarantined": quarantined,
        "stats": {
            "pages": total_pages,
            "body_start_page": body_start_page,
            "paragraphs": len(pairs),
            "changed_paragraphs": changed,
            "quarantined_paragraphs": len(quarantined),
        },
    }


def print_calibration_report(
    pdf_path, body_start_page, note_pattern_str, body_end_page=None
):
    """--calibrate-only: human-readable report to review with the user."""
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        blocks, text_pages = _collect_spans(pdf, body_start_page, body_end_page)
        last_page_text = pdf.pages[-1].extract_text() or ""
    end = total_pages if body_end_page is None else min(body_end_page + 1, total_pages)
    n_pages = end - body_start_page
    cal = _calibrate(blocks, text_pages, n_pages)
    validation = _validate_calibration(cal, _summary_totals(last_page_text))

    print(f"Calibration report for: {pdf_path}")
    print(f"Pages: {total_pages} (body starts at page index {body_start_page})")
    print(f"\nDefault (body text) color: {cal['default_color']}")
    print("\nDetected colors:")
    for color, st in sorted(
        cal["color_stats"].items(), key=lambda kv: -kv[1].get("total", 0)
    ):
        words = cal["color_words"].get(color, 0)
        if color == cal["default_color"]:
            verdict = "body text (unchanged)"
        elif color in cal["roles"]:
            verdict = f"REVISION -> {cal['roles'][color].upper()}"
        elif color in cal["structural_colors"]:
            verdict = "structural/numbering (ignored)"
        elif color in cal["undecorated_colors"]:
            verdict = (
                "COLOURED, NO MARKS -> not counted "
                f"(e.g. {cal['color_samples'].get(color, '')[:40]!r}); "
                f"--insert-color {color} or --delete-color {color} counts it"
            )
        else:
            verdict = "ignored (low volume / no signal)"
        print(
            f"  color={color:>10}  spans={st.get('total', 0):5}  words={words:6}  "
            f"strike={st.get('mid', 0):4}  underline={st.get('base', 0):4}  "
            f"-> {verdict}"
        )
    furniture = sorted({t for (_c, t) in cal["furniture_keys"]})
    if furniture:
        print("\nPage furniture excluded (headers/watermarks):")
        for t in furniture[:10]:
            print(f"  {t[:80]!r}")
    if validation:
        print("\nValidation against compare-tool scoreboard:")
        for w in validation:
            print(f"  {w}")
    else:
        print(
            "\nValidation against compare-tool scoreboard: OK "
            "(or no scoreboard found on last page)"
        )
    print(
        "\nReview this with the user before full extraction: do the REVISION "
        "color assignments match what they see in the PDF (deleted text "
        "struck through, inserted text underlined)? A colour marked NO MARKS "
        "is treated as house style, not as a change, unless the user says "
        "the compare tool uses it for block insertions or deletions."
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Extract structured old/new change data from an already-rendered "
            "redline PDF via per-document color/geometry calibration."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("pdf", help="Path to the redline PDF.")
    parser.add_argument(
        "output_json",
        nargs="?",
        default=None,
        help="Path to write extraction JSON (omit with --calibrate-only).",
    )
    parser.add_argument(
        "--calibrate-only",
        action="store_true",
        help="Print detected colors/roles/furniture and exit.",
    )
    parser.add_argument(
        "--body-start-page",
        type=int,
        default=0,
        help="0-indexed first body page (skip cover pages).",
    )
    parser.add_argument(
        "--body-end-page",
        type=int,
        default=None,
        help="0-indexed last body page (exclude trailing "
        "compare-tool summary/scoreboard pages, whose "
        "Add/Delete tallies otherwise parse as false "
        "changes). Default: last page.",
    )
    parser.add_argument(
        "--note-pattern",
        default=r"^\s*Note to\b",
        help="Regex for drafting-note asides to exclude.",
    )
    parser.add_argument(
        "--moved-color",
        action="append",
        type=int,
        default=None,
        help="Force this calibrated color (integer, as shown in "
        "--calibrate-only) to role 'moved' instead of the "
        "auto-detected del/ins: text is reported in "
        "move_annotations and excluded from old/new pairs. "
        "Repeatable for multiple colors.",
    )
    parser.add_argument(
        "--insert-color",
        action="append",
        type=int,
        default=None,
        help="Count this undecorated calibrated color (integer, as shown in "
        "--calibrate-only) as inserted text. Only for compare tools that "
        "render block insertions without an underline; plain coloured "
        "headings are never counted by default. Repeatable.",
    )
    parser.add_argument(
        "--delete-color",
        action="append",
        type=int,
        default=None,
        help="Count this undecorated calibrated color as deleted text. "
        "Only for compare tools that render block deletions without a "
        "strikethrough. Repeatable.",
    )
    args = parser.parse_args()

    if args.calibrate_only:
        print_calibration_report(
            args.pdf,
            args.body_start_page,
            args.note_pattern,
            body_end_page=args.body_end_page,
        )
        return

    if not args.output_json:
        print(
            "Error: output_json is required unless --calibrate-only is set.",
            file=sys.stderr,
        )
        sys.exit(1)

    result = extract(
        args.pdf,
        args.body_start_page,
        args.note_pattern,
        moved_colors=args.moved_color,
        body_end_page=args.body_end_page,
        insert_colors=args.insert_color,
        delete_colors=args.delete_color,
    )
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    s = result["stats"]
    print(f"Wrote {args.output_json}")
    print(
        f"  paragraphs: {s['paragraphs']}  changed: {s['changed_paragraphs']}  "
        f"quarantined: {s['quarantined_paragraphs']}  "
        f"move annotations: {len(result['move_annotations'])}"
    )
    for w in result["calibration"].get("validation", []):
        print(f"\nWARNING: {w}")
    for u in result["calibration"].get("undecorated_colors", []):
        print(
            f"\nNOT COUNTED: color {u['color']} ({u['words']} words, no strike or "
            f"underline, e.g. {u['sample'][:40]!r}) was treated as house style. "
            f"Re-run with --insert-color {u['color']} or --delete-color "
            f"{u['color']} if the compare tool uses it for changes."
        )
    if result["quarantined"]:
        print(
            "\nWARNING: some paragraphs were QUARANTINED (unreadable reading "
            "order). These are NOT in the pairs output and MUST be reviewed "
            "manually against the PDF:"
        )
        for q in result["quarantined"]:
            print(f"  page {q['page']}: {q['raw_text_preview'][:80]!r}")


if __name__ == "__main__":
    main()
