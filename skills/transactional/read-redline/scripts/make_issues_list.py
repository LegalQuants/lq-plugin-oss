#!/usr/bin/env python3
"""make_issues_list.py — build the theme-grouped Word issues list: the
briefing artifact that sits beside the annotated PDF (the full record).

A biglaw-style .docx table from the skill's three JSON outputs: theme band
rows (label + direction summary), and per row: provision + tier, the redline
itself (red strikethrough deletions, blue underline insertions, word-level
diff of the pair's old/new text), and the plain-English comment. Housekeeping
rows compress to one closing section; standalone rows get their own band.
The receipt line closes the document.

    python3 make_issues_list.py extract.json rows.json themes.json out.docx

Requires: python-docx.
"""

import difflib
import json
import sys
from datetime import date
from pathlib import Path

try:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor
except ImportError:
    print(
        "Error: python-docx is required but is not available in this environment.",
        file=sys.stderr,
    )
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from calibration_gate import gate_state_line, require_gate  # noqa: E402

RED = RGBColor(0xC0, 0x00, 0x00)
BLUE = RGBColor(0x1F, 0x4E, 0xC9)
GREY = RGBColor(0x59, 0x59, 0x59)
AMBER = RGBColor(0xB0, 0x6D, 0x00)
BAND = "D9E2F3"  # theme band fill
HEAD = "BDD0E9"  # column header fill

MAX_CHARS_PER_ROW = 700  # redline cell stays a summary; the PDF holds the rest


def shade(cell, hexfill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hexfill)
    tcPr.append(shd)


def add_runs(par, old, new):
    """Word-level diff: deletions red-struck, insertions blue-underlined.
    Compare tools often render inline replacements with NO space around the
    struck/inserted word, so the extracted text has 'withpromptwritten' at
    colour boundaries. Runs here are colour-coded, so we insert a space at
    every run boundary that lacks one — readable beats byte-faithful in a
    review artifact."""
    sm = difflib.SequenceMatcher(None, old.split(), new.split())
    total = 0
    prev_ended_space = True  # paragraph start needs no leading space

    def emit(text, color=None, strike=False, underline=False):
        nonlocal total, prev_ended_space
        if not text:
            return
        if not prev_ended_space and not text.startswith(" "):
            par.add_run(" ")
        r = par.add_run(text)
        if color is not None:
            r.font.color.rgb = color
        r.font.strike = strike
        r.font.underline = underline
        prev_ended_space = text.endswith(" ")
        total += len(text)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            emit(" ".join(old.split()[i1:i2]) + " ")
        elif tag == "delete":
            emit(" ".join(old.split()[i1:i2]) + " ", RED, strike=True)
        elif tag == "insert":
            emit(" ".join(new.split()[j1:j2]) + " ", BLUE, underline=True)
        else:  # replace
            emit(" ".join(old.split()[i1:i2]) + " ", RED, strike=True)
            emit(" ".join(new.split()[j1:j2]) + " ", BLUE, underline=True)
        if total > MAX_CHARS_PER_ROW:
            par.add_run(" […]")
            return


def main(extract_path, rows_path, themes_path, out_path):
    gate = require_gate(extract_path)
    rows = json.load(open(rows_path))
    extract = json.load(open(extract_path))
    themes = json.load(open(themes_path))
    pairs = {p["pair_id"]: p for p in extract["pairs"]}
    is_docx = "source_docx" in extract
    docname = (extract.get("source_docx") or extract["source_pdf"]).split("/")[-1]
    if docname.lower().endswith((".pdf", ".docx")):
        docname = docname.rsplit(".", 1)[0]
    docname = docname.replace("_", " ")

    doc = Document()
    # Generated documents carry LegalQuants as the author, not the library.
    doc.core_properties.author = "LegalQuants"
    doc.core_properties.last_modified_by = "LegalQuants"
    # landscape A4, narrow margins
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(29.7), Cm(21.0)
    for m in ("left", "right"):
        setattr(sec, f"{m}_margin", Cm(1.5))
    for m in ("top", "bottom"):
        setattr(sec, f"{m}_margin", Cm(1.8))
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    # header block
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = p.add_run(
        f"Date: {date.today().isoformat()}\nConfidential — draft for discussion"
    )
    r.font.size = Pt(9)
    t = doc.add_paragraph()
    r = t.add_run("Redline Review — Key Issues by Theme")
    r.font.size = Pt(18)
    r.font.bold = True
    cov = themes["coverage"]
    b = doc.add_paragraph()
    r = b.add_run(
        f"Review of {docname}. {cov['rows_total']} provisions analysed: "
        f"{len(themes['themes'])} themes covering {cov['rows_themed']}, "
        f"{cov['rows_housekeeping']} housekeeping, "
        f"{cov['rows_unclustered']} unclustered. "
        "Every provision is accounted for in this list."
    )
    r.font.size = Pt(9)
    r.font.italic = True

    table = doc.add_table(rows=0, cols=4)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    widths = (Cm(1.0), Cm(5.2), Cm(12.2), Cm(8.3))
    hdr = table.add_row().cells
    for c, txt, w in zip(
        hdr, ("No.", "Provision", "Redline", "Comment"), widths, strict=True
    ):
        c.width = w
        pr = c.paragraphs[0].add_run(txt)
        pr.font.bold = True
        pr.font.size = Pt(9)
        shade(c, HEAD)

    n = 0

    def issue_row(row_idx):
        nonlocal n
        n += 1
        row = rows[row_idx]
        cells = table.add_row().cells
        for c, w in zip(cells, widths, strict=True):
            c.width = w
        cells[0].paragraphs[0].add_run(f"{n}.").font.size = Pt(9)
        pr = cells[1].paragraphs[0]
        r = pr.add_run(row["provision"] + "\n")
        r.font.bold = True
        r.font.size = Pt(9)
        tier = row.get("materiality", "")
        tr = pr.add_run(tier)
        tr.font.size = Pt(9)
        tr.font.color.rgb = {"High": RED, "Medium": AMBER}.get(tier, GREY)
        if tier != "High":
            tr.font.italic = True
        direction = row.get("direction")
        if direction:
            dr = pr.add_run(f" · {direction}")
            dr.font.size = Pt(9)
            dr.font.color.rgb = GREY
            dr.font.italic = True
        first = next(
            (pairs[pid] for pid in row["source_pair_ids"] if pid in pairs), None
        )
        if first is not None:
            # parser indexes are 0-based; display is 1-based
            if is_docx and first.get("paragraph") is not None:
                location = f"¶ {first['paragraph'] + 1}"
            elif not is_docx and first.get("page") is not None:
                location = f"p. {first['page'] + 1}"
            else:
                location = None
            if location:
                lr = pr.add_run(f"\n{location}")
                lr.font.size = Pt(8)
                lr.font.color.rgb = GREY
        rl = cells[2].paragraphs[0]
        shown = 0
        for pid in row["source_pair_ids"]:
            p = pairs.get(pid)
            if not p:
                continue
            old, new = p.get("old_text") or "", p.get("new_text") or ""
            if not old and not new:
                continue
            add_runs(rl, old, new)
            shown += 1
            if shown >= 2 and len(row["source_pair_ids"]) > 2:
                more = len(row["source_pair_ids"]) - 2
                rl.add_run(f" [+{more} more pairs — see the annotated copy]")
                break
        for run in rl.runs:
            if run.font.size is None:
                run.font.size = Pt(8.5)
        cr = cells[3].paragraphs[0].add_run(row.get("comment", ""))
        cr.font.size = Pt(9)

    for i, theme in enumerate(themes["themes"], 1):
        band = table.add_row().cells
        band[0].merge(band[3])
        pr = band[0].paragraphs[0]
        r = pr.add_run(f"Theme {i} — {theme['label']}")
        r.font.bold = True
        r.font.size = Pt(10)
        sr = pr.add_run(f"\n{theme['summary']}")
        sr.font.italic = True
        sr.font.size = Pt(8.5)
        sr.font.color.rgb = GREY
        shade(band[0], BAND)
        for ri in theme["row_refs"]:
            issue_row(ri)

    if themes["unclustered"]:
        band = table.add_row().cells
        band[0].merge(band[3])
        r = band[0].paragraphs[0].add_run("Standalone items (no shared theme)")
        r.font.bold = True
        shade(band[0], BAND)
        for u in themes["unclustered"]:
            issue_row(u["row_ref"])

    hk = themes["housekeeping"]
    p = doc.add_paragraph()
    r = p.add_run(
        f"Housekeeping ({hk['count']} provisions): renumbering, cross-reference, "
        "pagination and draft-date mechanics only — listed here for completeness, "
        "nothing to negotiate."
    )
    r.font.size = Pt(9)
    r.font.italic = True
    names = "; ".join(rows[i]["provision"] for i in hk["row_refs"][:12])
    p2 = doc.add_paragraph()
    r2 = p2.add_run(names + ("; …" if hk["count"] > 12 else ""))
    r2.font.size = Pt(8)
    r2.font.color.rgb = GREY

    f = doc.add_paragraph()
    fr = f.add_run(
        f"Receipt: {cov['rows_themed']} themed + "
        f"{cov['rows_housekeeping']} housekeeping "
        f"+ {cov['rows_unclustered']} standalone = {cov['rows_total']} provisions. "
        f"{gate_state_line(gate)} "
        "Full markup in the annotated PDF."
    )
    fr.font.size = Pt(8)
    fr.font.color.rgb = GREY

    doc.save(out_path)
    print("wrote", out_path, f"({gate_state_line(gate)})")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(
            "usage: make_issues_list.py extract.json rows.json themes.json out.docx",
            file=sys.stderr,
        )
        sys.exit(1)
    main(*sys.argv[1:5])
