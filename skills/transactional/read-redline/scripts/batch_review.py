#!/usr/bin/env python3
"""
batch_review.py — validate the redline-review mechanical pipeline across a
folder of redline PDFs.

For every *.pdf in the folder it runs two passes and records the result,
never aborting the whole run on one bad file:

  (A) Parser QA — parse the PDF to <stem>.extract.json and read back its
      calibration roles, change count, and quarantine count. Warns when a
      colour shows BOTH strikes and underlines (a likely move-colour that
      needs --moved-color), when zero changes are detected, or when the parse
      fails outright (e.g. a scanned/image-only PDF).

  (B) Annotator smoke test — auto-generate trivial rows (one per changed
      pair; tier by a cheap heuristic: text contains a digit -> Medium, else
      Low; placeholder comment) and run annotate_pdf.py. This proves the
      geometry places correctly and the post-save self-check passes, WITHOUT
      needing model-authored comments. It does not judge significance.

Comment/tier *quality* is a per-file model task and is out of scope here.

Usage:
    python3 batch_review.py <folder-of-pdfs> --out <report-dir>

Requires: pdfplumber + pypdf (via the two sibling scripts). Stdlib otherwise.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARSE = HERE / "parse_redline_pdf.py"
ANNOTATE = HERE / "annotate_pdf.py"


def _run(args):
    return subprocess.run(
        [sys.executable, *map(str, args)], capture_output=True, text=True
    )


def _smoke_rows(extract):
    """One trivial row per changed pair. Tier heuristic only — not judgment."""
    rows = []
    for p in extract.get("pairs", []):
        if not p.get("changed"):
            continue
        text = f"{p.get('old_text') or ''} {p.get('new_text') or ''}"
        tier = "Medium" if any(ch.isdigit() for ch in text) else "Low"
        rows.append(
            {
                "provision": (p.get("new_text") or p.get("old_text") or "")[:40]
                or "change",
                "source_pair_ids": [p["pair_id"]],
                "comment": "Smoke-test placeholder comment (batch validation only).",
                "materiality": tier,
            }
        )
    return rows


def review_one(pdf: Path, out_dir: Path) -> dict:
    rec = {
        "file": pdf.name,
        "pages": None,
        "changes": None,
        "quarantined": None,
        "roles": {},
        "calibration_ok": False,
        "annotate_ok": False,
        "warnings": [],
    }

    extract_path = out_dir / f"{pdf.stem}.extract.json"
    r = _run([PARSE, pdf, extract_path])
    if r.returncode != 0:
        rec["warnings"].append(
            f"parse failed: "
            f"{r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'unknown'}"
        )
        return rec

    extract = json.loads(extract_path.read_text())
    rec["calibration_ok"] = True
    rec["pages"] = extract["stats"]["pages"]
    rec["changes"] = extract["stats"]["changed_paragraphs"]
    rec["quarantined"] = extract["stats"]["quarantined_paragraphs"]
    rec["roles"] = extract["calibration"]["roles"]
    if rec["changes"] == 0:
        rec["warnings"].append("zero changes detected — is this actually a redline?")
    if rec["quarantined"]:
        rec["warnings"].append(
            f"{rec['quarantined']} quarantined paragraph(s) — manual review needed"
        )

    # move-colour tell: a color reporting both strikes and underlines. Re-read
    # the calibration report to see per-colour strike/underline counts.
    cal = _run([PARSE, pdf, "--calibrate-only"])
    for line in cal.stdout.splitlines():
        # "  color=  32768  spans=.. words=.. strike=  12  underline=  10  -> ..."
        if "strike=" in line and "underline=" in line and "REVISION" in line:
            try:
                strike = int(line.split("strike=")[1].split()[0])
                under = int(line.split("underline=")[1].split()[0])
            except (IndexError, ValueError):
                continue
            if strike > 0 and under > 0:
                color = line.split("color=")[1].split()[0]
                rec["warnings"].append(
                    f"colour {color} shows both strikes ({strike}) and underlines "
                    f"({under}) — possible move-colour; consider --moved-color {color}"
                )

    rows = _smoke_rows(extract)
    if not rows:
        rec["annotate_ok"] = True  # nothing to place; not a failure
        return rec
    rows_path = out_dir / f"{pdf.stem}.rows.json"
    rows_path.write_text(json.dumps(rows))
    out_pdf = out_dir / f"{pdf.stem}.annotated.pdf"
    a = _run(
        [ANNOTATE, pdf, "--pairs", extract_path, "--rows", rows_path, "--out", out_pdf]
    )
    rec["annotate_ok"] = a.returncode == 0
    if a.returncode != 0:
        tail = (a.stderr or a.stdout).strip().splitlines()
        rec["warnings"].append(
            f"annotate smoke test failed: {tail[-1] if tail else 'unknown'}"
        )
    return rec


def main():
    ap = argparse.ArgumentParser(
        description="Validate the redline pipeline across a PDF folder."
    )
    ap.add_argument("folder", help="Folder containing redline PDFs.")
    ap.add_argument(
        "--out", required=True, help="Report/output directory (created if absent)."
    )
    args = ap.parse_args()

    folder = Path(args.folder)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"No .pdf files in {folder}")

    records = [review_one(p, out_dir) for p in pdfs]
    (out_dir / "report.json").write_text(json.dumps(records, indent=2))

    print(
        f"{'file':40} {'pages':>5} {'chg':>4} {'quar':>4} {'cal':>4} {'ann':>4}  "
        "warnings"
    )
    ok = True
    for r in records:
        cal = "ok" if r["calibration_ok"] else "FAIL"
        ann = "ok" if r["annotate_ok"] else "FAIL"
        if not (r["calibration_ok"] and r["annotate_ok"]):
            ok = False
        pages = "-" if r["pages"] is None else str(r["pages"])
        changes = "-" if r["changes"] is None else str(r["changes"])
        quarantined = "0" if r["quarantined"] is None else str(r["quarantined"])
        print(
            f"{r['file'][:40]:40} {pages:>5} {changes:>4} "
            f"{quarantined:>4} {cal:>4} {ann:>4}  "
            f"{'; '.join(r['warnings']) if r['warnings'] else ''}"
        )
    print(f"\n{len(records)} file(s). Report: {out_dir / 'report.json'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
