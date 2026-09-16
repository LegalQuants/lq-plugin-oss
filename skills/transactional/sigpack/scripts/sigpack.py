#!/usr/bin/env python3
"""sigpack — ledger-driven mechanics for the /sigpack skill. The model classifies and reads renders; this script cuts, merges, OCRs, tracks, and reports.

One ledger per matter: sigpack.ledger.json in the closing folder (see references/ledger_schema.md).

    python3 sigpack.py draft   --ledger L --matrix matrix.json --template <sigpage.docx> --out-dir drafted/ [--execution <folder>]  # declared start: generate pages from the firm template
    python3 sigpack.py convert <folder-with-docx> --out-dir <pdf-folder>          # docx/doc -> PDF via bundled LibreOffice (soffice); honest fallback if absent
    python3 sigpack.py scan    <execution-folder> --out candidates.json [--ocr] [--triage-dir tmp/triage] [--emit-batches N --batch-dir tmp/scan-batches]
    python3 sigpack.py assemble --batches <folder-of-filled-scan-batches> --execution <folder> --out classified.json   # fold parallel classification back; refuses unanswered candidates
    python3 sigpack.py init    --ledger L --execution <folder> --classified classified.json [--matter NAME]
    python3 sigpack.py build   --ledger L --group agreement|counterparty|signatory --out-dir packs/ [--copies N] [--no-duplicate] [--name "Signature Pack – {group}"]
    python3 sigpack.py read    --ledger L --returned <folder> [--ocr] [--render-dir tmp/renders] [--emit-batches N --batch-dir tmp/batches]
    python3 sigpack.py merge   --ledger L --verdicts <folder-of-worker-json>     # fold per-page verdicts (from parallel workers or your own read) into the ledger
    python3 sigpack.py compile --ledger L --out-dir executed/ [--date "29 May 2025"] [--separator] [--place-partial]
    python3 sigpack.py status  --ledger L

Runs on pypdf. Text via Poppler pdftotext when present (fast on long documents), pypdf otherwise. OCR via pdftoppm + tesseract when present.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from collections import defaultdict
from pathlib import Path

try:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (
        ArrayObject,
        DictionaryObject,
        FloatObject,
        NameObject,
        TextStringObject,
    )
except ImportError:  # pragma: no cover
    sys.exit("Error: pypdf is required but is not available in this environment.")

MARKERS = re.compile(
    r"(?<!\w)(Signature|Execution|Excution|Signatory|Executed|Signed|Witness|Agreed\s+and\s+Accepted|"
    r"Accepted\s+by|Acknowledged\s+by|Duly\s+Authori[sz]ed|By:|Name:|Title:|Position:|Date:)(?!\w)",
    re.IGNORECASE,
)
# Party is the LAST dash-separated segment; agreement is greedy (Co-Sale hyphens survive). Party segment optional (English-law style).
# A footer is a LINE that begins with the phrase (optionally bracketed) — never "signature page" mid-sentence in body prose.
FOOTER = re.compile(
    r"^[ \t]*\[?\s*Signature\s+Page(?:\s+to(?:\s+the)?)?\s*[–—\-~:]*\s*(?P<agreement>[^\n\]]+?)(?:\s+[–—~\-]{1,2}\s+(?P<party>[^\n\]]+?))?\s*\]?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
NEGATIVE = re.compile(
    r"signature\s+page\s+(to\s+follow|follows)|signatures?\s+appear\s+on\s+(the\s+)?next\s+page|intentionally\s+left\s+blank",
    re.IGNORECASE,
)
FORM_LIKE = re.compile(
    r"^\s*(form\s+of|exhibit\s+[a-z0-9]|schedule\s+[a-z0-9]|annex\s+[a-z0-9]|appendix\s+[a-z0-9]|template|sample|pro\s+forma)\b|\[insert\s|\[•\]|\[name\]",
    re.IGNORECASE,
)
VERSION = re.compile(r"\b(\d{8,}-v\d+)\b")
ESIG = re.compile(
    r"docusign|adobe\s*sign|envelope\s*id|certificate\s+of\s+completion|electronic\s+record\s+and\s+signature",
    re.IGNORECASE,
)
_PDFTOTEXT = shutil.which("pdftotext")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[–—~\-‑]+", "-", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def today() -> str:
    return _dt.date.today().isoformat()


def page_text(reader: PdfReader, i: int, pdf: Path | None = None) -> str:
    if _PDFTOTEXT and pdf is not None:
        r = subprocess.run(
            [_PDFTOTEXT, "-f", str(i + 1), "-l", str(i + 1), "-layout", str(pdf), "-"],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            return r.stdout or ""
    try:
        return reader.pages[i].extract_text() or ""
    except Exception:
        return ""


def ocr_page(pdf: Path, page1: int) -> str:
    if not (shutil.which("pdftoppm") and shutil.which("tesseract")):
        return ""
    with tempfile.TemporaryDirectory() as td:
        prefix = Path(td) / "pg"
        subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                "200",
                "-f",
                str(page1),
                "-l",
                str(page1),
                str(pdf),
                str(prefix),
            ],
            capture_output=True,
        )
        pngs = sorted(Path(td).glob("pg*.png"))
        if not pngs:
            return ""
        r = subprocess.run(
            ["tesseract", str(pngs[0]), "-"], capture_output=True, text=True
        )
        return r.stdout or ""


def render_page(pdf: Path, page1: int, out_dir: Path, dpi: int = 80) -> str | None:
    if not shutil.which("pdftoppm"):
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / f"{pdf.stem}-p{page1:03d}"
    subprocess.run(
        [
            "pdftoppm",
            "-png",
            "-r",
            str(dpi),
            "-f",
            str(page1),
            "-l",
            str(page1),
            "-singlefile",
            str(pdf),
            str(prefix),
        ],
        capture_output=True,
    )
    png = Path(str(prefix) + ".png")
    return str(png) if png.exists() else None


def load(path) -> dict:
    return json.loads(Path(path).read_text())


def save(path, obj) -> None:
    """Write atomically: a half-written ledger is never left on disk."""
    target = Path(path)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False))
    os.replace(tmp, target)


def sheet_hash(page) -> str | None:
    """Content identity of one returned sheet: its content streams plus any image
    XObjects. The same scan under a new filename hashes the same; a different scan
    of the same page does not. None when the page cannot be read."""
    h = hashlib.sha256()
    try:
        contents = page.get_contents()
        if contents is not None:
            h.update(contents.get_data())
        resources = page.get("/Resources")
        xobjects = resources.get("/XObject") if resources else None
        if xobjects:
            for key in sorted(str(k) for k in xobjects.keys()):
                obj = xobjects[key].get_object()
                try:
                    h.update(obj.get_data())
                except Exception:  # noqa: BLE001 - non-stream object; identity still useful
                    h.update(key.encode())
    except Exception:  # noqa: BLE001
        return None
    return h.hexdigest()


WRITE_ARGS = ("ledger", "out_dir", "out", "render_dir", "triage_dir", "batch_dir")


def workspace_of(args) -> Path:
    """The matter folder every write must stay inside: the ledger's folder when
    the command has one, otherwise the current directory."""
    explicit = getattr(args, "workspace", None)
    if explicit:
        return Path(explicit).resolve()
    ledger = getattr(args, "ledger", None)
    return Path(ledger).resolve().parent if ledger else Path.cwd().resolve()


def contain_writes(args) -> None:
    """Refuse any output path that resolves outside the workspace. Inputs may be
    read from anywhere; nothing is ever written anywhere else unless the user
    says --allow-outside on this run."""
    ws = workspace_of(args)
    args.workspace = ws
    if getattr(args, "allow_outside", False):
        return
    for name in WRITE_ARGS:
        value = getattr(args, name, None)
        if not value:
            continue
        target = Path(value).resolve()
        if name == "ledger":
            continue  # the ledger defines the workspace
        if not target.is_relative_to(ws):
            print(
                f"refused: --{name.replace('_', '-')} {value} resolves to {target}, "
                f"outside the matter folder {ws}. Every output stays beside the "
                "ledger; pass --allow-outside if you really mean it.",
                file=sys.stderr,
            )
            sys.exit(2)


STAGING_PREFIX = ".staging-"


def clear_staging(folder: Path) -> int:
    """Remove staging folders a crashed run left behind. Returns how many."""
    n = 0
    if folder.is_dir():
        for stale in folder.glob(STAGING_PREFIX + "*"):
            if stale.is_dir():
                shutil.rmtree(stale, ignore_errors=True)
                n += 1
    return n


@contextlib.contextmanager
def staged(folder: Path, tag: str):
    """Write a set of files into a staging folder; on success move them into
    `folder` in one pass, on failure remove the staging folder so nothing
    half-written is left beside real outputs."""
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", tag)[:80] or "run"
    stage = folder / f"{STAGING_PREFIX}{safe}"
    if stage.exists():
        shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    try:
        yield stage
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    for item in sorted(stage.iterdir()):
        os.replace(item, folder / item.name)
    stage.rmdir()


def own_pdfs(folder: Path) -> list[Path]:
    """PDFs in a source folder, skipping symlinks that point outside it."""
    root = folder.resolve()
    keep = []
    for pdf in sorted(folder.glob("*.pdf")):
        if pdf.is_symlink() and not pdf.resolve().is_relative_to(root):
            print(f"skipped {pdf.name}: symlink to {pdf.resolve()} outside {folder}")
            continue
        keep.append(pdf)
    return keep


def short_code(agreement: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", agreement or "") if w]
    stop = {"of", "the", "and", "to", "a", "an", "in", "for", "agreement", "letter"}
    return "".join(w[0].upper() for w in words if w.lower() not in stop)[:5] or "DOC"


# ---------------------------------------------------------------- receipt
def page_is_live(p: dict) -> bool:
    """A page counts toward the closing unless it is a reserved spare with no
    party assigned yet. Assign a party to a reserved page and it becomes live."""
    if not p.get("reserved"):
        return True
    return any(
        b.get("party") not in (None, "", "Unknown", "unassigned") for b in p["blocks"]
    )


CHECKPOINT_CAP = 50


def _block_states(led: dict) -> dict[str, str]:
    return {
        f"{p['id']}#{b['block']}": b.get("status", "required")
        for p in led["signature_pages"]
        for b in p["blocks"]
        if page_is_live(p)
    }


def _outcome_counts(led: dict) -> dict[str, int]:
    cnt: dict = defaultdict(int)
    for r in led.get("returned_pages", []):
        if r.get("page"):
            cnt[r.get("outcome") or "pending"] += 1
    return dict(cnt)


def checkpoint(led: dict, label: str) -> dict:
    """Record the closing's state so a later run can say what moved since."""
    cp = {
        "at": _dt.datetime.now().isoformat(timespec="seconds"),
        "label": label,
        "blocks": _block_states(led),
        "receipt": dict(led.get("receipt") or {}),
        "returned": sum(1 for r in led.get("returned_pages", []) if r.get("page")),
        "outcomes": _outcome_counts(led),
        "unmatched": len(led.get("unmatched_returns", [])),
    }
    cps = led.setdefault("checkpoints", [])
    cps.append(cp)
    del cps[:-CHECKPOINT_CAP]
    return cp


def find_checkpoint(led: dict, since: str | None) -> dict | None:
    """The checkpoint to diff against: the last one by default; with --since,
    the earliest whose label matches, or the earliest at or after that date."""
    cps = led.get("checkpoints") or []
    if not cps:
        return None
    if not since:
        return cps[-1]
    for cp in cps:
        if cp["label"] == since:
            return cp
    dated = [cp for cp in cps if cp["at"][:10] >= since[:10]]
    if dated:
        return dated[0]
    sys.exit(
        f"no checkpoint labelled or dated {since!r}; labels: {[c['label'] for c in cps]}"
    )


def delta(led: dict, since: str | None = None) -> dict | None:
    """What moved between a checkpoint and the ledger as it stands now."""
    cp = find_checkpoint(led, since)
    if cp is None:
        return None
    before, after = cp["blocks"], _block_states(led)
    moved: dict[str, list[str]] = defaultdict(list)
    for key, status in after.items():
        if before.get(key) != status:
            moved[status.replace("-", "_")].append(key)
    still_missing = sorted(k for k, s in after.items() if s in ("required", "sent"))
    then, now = cp.get("outcomes", {}), _outcome_counts(led)
    returns = {
        "registered": sum(1 for r in led.get("returned_pages", []) if r.get("page"))
        - cp.get("returned", 0),
        **{
            k: now.get(k, 0) - then.get(k, 0)
            for k in (
                "chosen",
                "spare",
                "wrong-version",
                "name-mismatch",
                "duplicate",
                "unmatched",
            )
        },
    }
    returns["rejected"] = returns.pop("wrong-version") + returns.pop("name-mismatch")
    recompute_receipt(led)
    return {
        "since": {"at": cp["at"], "label": cp["label"]},
        "blocks": {
            **{k: sorted(v) for k, v in moved.items()},
            "still_missing": still_missing,
        },
        "returns": returns,
        "receipt_before": cp["receipt"],
        "receipt_after": led["receipt"],
        "moved": bool(moved) or any(v for v in returns.values()),
    }


def print_delta(d: dict | None) -> None:
    if not d or not d["moved"]:
        return
    parts = []
    for status, label in (
        ("signed", "signed"),
        ("partial", "partial"),
        ("blank", "blank"),
        ("unclear", "unclear"),
        ("wrong_version", "wrong-version"),
    ):
        n = len(d["blocks"].get(status, []))
        if n:
            parts.append(f"+{n} {label}")
    r = d["returns"]
    for key, label in (
        ("spare", "spares"),
        ("rejected", "REJECTED"),
        ("duplicate", "duplicates"),
        ("unmatched", "unmatched"),
    ):
        if r.get(key):
            parts.append(f"{r[key]} {label}")
    when = d["since"]["at"][:10]
    print(
        f"Since {d['since']['label']} ({when}): "
        + ", ".join(parts)
        + f"; still missing {len(d['blocks']['still_missing'])}."
    )


def recompute_receipt(led: dict) -> dict:
    blocks = [(p, b) for p in led["signature_pages"] for b in p["blocks"]]
    live = [(p, b) for p, b in blocks if page_is_live(p)]
    cnt: dict = defaultdict(int)
    for _p, b in live:
        cnt[b.get("status", "required")] += 1
    spare = sum(1 for _p, b in blocks for r in b.get("returned", []) if r.get("spare"))
    missing = sum(1 for _p, b in live if b.get("status") in ("required", "sent"))
    rec = {
        "pages_required": len([p for p in led["signature_pages"] if page_is_live(p)]),
        "blocks_required": len(live),
        "blocks_signed": cnt["signed"],
        "blocks_partial": cnt["partial"],
        "blocks_blank": cnt["blank"],
        "blocks_unclear": cnt["unclear"],
        "blocks_wrong_version": cnt["wrong-version"],
        "blocks_missing": missing,
        "spare_originals": spare,
        "unmatched_returns": len(led.get("unmatched_returns", [])),
        "reserved_unassigned": sum(
            1
            for p in led["signature_pages"]
            if p.get("reserved") and not page_is_live(p)
        ),
        "complete": bool(live) and all(b.get("status") == "signed" for _p, b in live),
        "as_of": today(),
    }
    led["receipt"] = rec
    return rec


def print_receipt(led: dict) -> None:
    r = led["receipt"]
    print(
        f"{r['pages_required']} pages / {r['blocks_required']} blocks required · {r['blocks_signed']} signed · "
        f"{r['blocks_partial']} partial · {r['blocks_blank']} blank · {r['blocks_unclear']} unclear · "
        f"{r['blocks_wrong_version']} wrong-version · {r['blocks_missing']} missing · {r['unmatched_returns']} unmatched returns · "
        f"{r['spare_originals']} spare originals · {'COMPLETE' if r['complete'] else 'NOT COMPLETE'}"
    )
    miss = [
        (p["id"], b["block"], b.get("party"))
        for p in led["signature_pages"]
        for b in p["blocks"]
        if page_is_live(p) and b.get("status") in ("required", "sent")
    ]
    for pid, bn, party in miss[:40]:
        print(f"  MISSING  {pid} block {bn}  {party}")
    if len(miss) > 40:
        print(f"  … and {len(miss) - 40} more")
    for p in led["signature_pages"]:
        if p.get("held"):
            print(
                f"  HELD  {p['id']} — signed sheets in hand but page not placed; waiting on {', '.join(p['held']['waiting_on'])}"
            )


# ---------------------------------------------------------------- draft (declared start)
def _fill_docx(template: Path, out_docx: Path, mapping: dict) -> None:
    """Fill {{PLACEHOLDER}}s in a docx (a zip of XML) with stdlib only."""
    import zipfile

    with zipfile.ZipFile(template) as zin, zipfile.ZipFile(out_docx, "w") as zout:
        for item in zin.namelist():
            data = zin.read(item)
            if item.endswith(".xml"):
                text = data.decode("utf-8")
                for k, v in mapping.items():
                    text = text.replace("{{" + k + "}}", v)
                data = text.encode("utf-8")
            zout.writestr(item, data)


def cmd_draft(args):
    """Declared start: the lawyer-confirmed signing matrix + the firm's template -> drafted signature
    pages (separate files, circulated with the escrow note) + a ledger with origin 'drafted'.
    Drafting happens BEFORE circulation and is gated by the lawyer; nothing is ever added to a page
    after agreement or signing (see the document-integrity rule)."""
    matrix = load(args.matrix)
    template = Path(args.template)
    soffice = _find_soffice()
    if not soffice:
        sys.exit(
            "draft: LibreOffice (soffice) not found — cannot render the template. Stop and say so."
        )
    exec_dir = Path(args.execution) if args.execution else Path(".")
    out_dir = Path(args.out_dir)
    drafted_dir = out_dir
    drafted_dir.mkdir(parents=True, exist_ok=True)
    ledger_pages = []
    n = 0
    with tempfile.TemporaryDirectory() as td:
        for doc in matrix["signature_pages"]:
            title = doc.get("agreement") or Path(doc.get("file", "Document")).stem
            for b in doc.get("blocks") or []:
                sigs = b.get("signatures") or [
                    {
                        "name": b.get("signatory") or "",
                        "capacity": b.get("capacity") or "",
                        "role": "signatory",
                    }
                ]
                primary = sigs[0]
                mapping = {
                    "DOC_TITLE": title,
                    "PARTY": b.get("party") or "",
                    "SIGNATORY": primary.get("name") or "",
                    "TITLE": primary.get("capacity") or "",
                }
                safe_party = re.sub(
                    r'[/\\?%*:|"<>]', "", b.get("party") or "party"
                ).strip()
                stem = f"Signature Page – {title} – {safe_party}"
                fdocx = Path(td) / f"{n}.docx"
                _fill_docx(template, fdocx, mapping)
                # render via bundled soffice with a per-run profile (same recipe as convert)
                profile = Path(td) / f"prof{n}"
                profile.mkdir()
                env = dict(__import__("os").environ)
                env["HOME"] = str(profile)
                prof_arg = f"-env:UserInstallation={profile.resolve().as_uri()}"
                subprocess.run(
                    [
                        soffice,
                        prof_arg,
                        "--invisible",
                        "--headless",
                        "--norestore",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        str(td),
                        str(fdocx),
                    ],
                    env=env,
                    capture_output=True,
                    timeout=600,
                )
                pdf_tmp = Path(td) / f"{n}.pdf"
                target = drafted_dir / f"{stem}.pdf"
                if pdf_tmp.exists() and pdf_tmp.stat().st_size > 0:
                    shutil.copy(pdf_tmp, target)
                else:
                    sys.exit(f"draft: render failed for {stem}")
                ledger_pages.append(
                    {
                        "file": str(target.relative_to(exec_dir))
                        if str(target).startswith(str(exec_dir))
                        else str(target),
                        "page": 1,
                        "agreement": title,
                        "is_signature_page": True,
                        "origin": "drafted",
                        "blocks": [dict(b)],
                    }
                )
                n += 1
    cl = Path(args.out_dir) / "declared-classified.json"
    save(cl, {"signature_pages": ledger_pages})
    print(
        f"drafted {n} signature pages from the template -> {drafted_dir}/ ; declared classification -> {cl}"
    )
    print(
        "GATE: render and show the lawyer a sample page before circulating. Then `init --ledger ... --execution <closing folder> --classified "
        + str(cl)
        + "` and continue with the pack workflow."
    )


# ---------------------------------------------------------------- convert (docx -> pdf)
def _find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        w = shutil.which(name)
        if w:
            return w
    runtime = (
        Path.home()
        / ".cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override"
    )
    candidates = [
        runtime / "soffice",
        runtime / "soffice.exe",
        Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
        Path("/opt/homebrew/bin/soffice"),
        Path("/usr/bin/soffice"),
        Path("/usr/lib/libreoffice/program/soffice"),
    ]
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "LibreOffice" / "program" / "soffice.exe")
            candidates.append(
                Path(base) / "Programs" / "LibreOffice" / "program" / "soffice.exe"
            )
    for cand in candidates:
        if cand.exists():
            return str(cand)
    return None


def cmd_convert(args):
    """docx/doc -> PDF with the bundled LibreOffice, the way the host's own document skill does it.
    Never claims success on stderr silence: a PDF must exist and be non-empty. If soffice is absent, say so and stop."""
    src = Path(args.folder)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    soffice = _find_soffice()
    docs = sorted([*src.glob("*.docx"), *src.glob("*.doc"), *src.glob("*.rtf")])
    if not docs:
        print(f"no docx/doc/rtf in {src}")
        return
    if not soffice:
        sys.exit(
            f"convert: LibreOffice (soffice) not found. {len(docs)} Word documents cannot be converted here. Ask the user to supply PDFs or convert locally; do not proceed as if they were converted."
        )
    ok, failed = [], []
    with tempfile.TemporaryDirectory() as td:
        profile = Path(td) / "lo_profile"
        profile.mkdir()
        env = dict(**{k: v for k, v in __import__("os").environ.items()})
        env["HOME"] = str(profile)
        env.setdefault("XDG_CONFIG_HOME", str(profile / "xdg_config"))
        env.setdefault("XDG_CACHE_HOME", str(profile / "xdg_cache"))
        Path(env["XDG_CONFIG_HOME"]).mkdir(parents=True, exist_ok=True)
        Path(env["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)
        prof_arg = f"-env:UserInstallation={profile.resolve().as_uri()}"
        for d in docs:
            target = out / (d.stem + ".pdf")
            if target.exists() and target.stat().st_size > 0 and not args.force:
                ok.append((d.name, "already converted"))
                continue
            base = [
                soffice,
                prof_arg,
                "--invisible",
                "--headless",
                "--norestore",
                "--convert-to",
            ]
            subprocess.run(
                [*base, "pdf", "--outdir", str(out), str(d)],
                env=env,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if target.exists() and target.stat().st_size > 0:
                ok.append((d.name, "pdf"))
                continue
            # fallback: docx -> odt -> pdf
            subprocess.run(
                [*base, "odt", "--outdir", td, str(d)],
                env=env,
                capture_output=True,
                text=True,
                timeout=600,
            )
            odt = Path(td) / (d.stem + ".odt")
            if odt.exists():
                subprocess.run(
                    [*base, "pdf", "--outdir", str(out), str(odt)],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
            if target.exists() and target.stat().st_size > 0:
                ok.append((d.name, "pdf via odt"))
            else:
                failed.append(d.name)
    print(
        f"converted {len(ok)}/{len(docs)} -> {out}/"
        + (f"; FAILED: {failed}" if failed else "")
    )
    if failed:
        sys.exit(1)


# ---------------------------------------------------------------- scan
def _page_features(pg, text):
    """Language-agnostic per-page features. Geometry is the recall anchor."""
    h_lines = sum(
        1
        for ln in pg.lines
        if abs(ln["top"] - ln["bottom"]) < 1.5 and (ln["x1"] - ln["x0"]) > 60
    )
    h_rects = sum(
        1 for r in pg.rects if (r["x1"] - r["x0"]) > 60 and (r["bottom"] - r["top"]) < 3
    )
    underscore_runs = len(re.findall(r"[_.]{8,}", text))
    sig_lines = h_lines + h_rects + underscore_runs
    words = len(text.split())
    lines = [ln for ln in text.splitlines() if ln.strip()]
    short_ratio = (
        (sum(1 for ln in lines if len(ln.strip()) < 40) / len(lines)) if lines else 0.0
    )
    return sig_lines, words, round(short_ratio, 2)


def cmd_scan(args):
    """v3 (ruled 2026-08-18): every page is scored and tiered; no page is excluded by text.
    Tier 1 = read at full size now (geometry, footer, markers, or position). Tier 2 = look on a
    contact sheet; unsure -> zoom. Keywords accelerate and annotate; they never gate."""
    folder = Path(args.folder)
    out = {"documents": [], "pages": [], "candidates": []}
    sheets_src = []  # (file, page1, pdf_path) for tier-2
    try:
        import pdfplumber as _plumber_probe  # noqa: F401

        plumber_available = True
    except Exception:
        plumber_available = False
    for pdf in own_pdfs(folder):
        rd = PdfReader(str(pdf))
        n = len(rd.pages)
        out["documents"].append({"file": pdf.name, "pages": n})
        try:
            import pdfplumber

            plumber = pdfplumber.open(str(pdf))
        except Exception:
            plumber = None
        # find first schedule/exhibit heading page to bound "body"
        body_end = n
        for i in range(n):
            t0 = page_text(rd, i, pdf)
            if re.match(
                r"\s*(SCHEDULE|EXHIBIT|ANNEX|APPENDIX)\s+[A-Z0-9]",
                t0.strip()[:40],
                re.IGNORECASE,
            ):
                body_end = i
                break
        for i in range(n):
            t = page_text(rd, i, pdf)
            scanned = len(t.strip()) < 5
            if scanned and args.ocr:
                t = ocr_page(pdf, i + 1)
            sig_lines, words, short_ratio = (0, 0, 0.0)
            if plumber is not None:
                try:
                    sig_lines, words, short_ratio = _page_features(plumber.pages[i], t)
                except Exception:
                    pass
            hits = MARKERS.findall(t)
            foot = FOOTER.search(t)
            vm = VERSION.search(t)
            position_prior = body_end - 3 <= i < body_end
            tier = 2
            reasons = []
            if foot:
                tier = 1
                reasons.append("footer")
            if sig_lines >= 2:
                tier = 1
                reasons.append(f"geometry:{sig_lines}")
            if len(hits) >= 2 and (sig_lines >= 1 or short_ratio > 0.5):
                tier = 1
                reasons.append("markers+shape")
            if position_prior:
                tier = 1
                reasons.append("position")
            if scanned:
                tier = 1
                reasons.append("scanned")
            rec = {
                "file": pdf.name,
                "page": i + 1,
                "tier": tier,
                "reasons": reasons,
                "scanned": scanned,
                "marker_hits": len(hits),
                "sig_lines": sig_lines,
                "words": words,
                "short_line_ratio": short_ratio,
                "footer_agreement": foot.group("agreement").strip() if foot else None,
                "footer_party": ((foot.group("party") or "").strip() or None)
                if foot
                else None,
                "version_marker": vm.group(1) if vm else None,
                "negative_signal": bool(NEGATIVE.search(t)),
                "form_like": bool(FORM_LIKE.search(t)),
                "text_preview": re.sub(r"\s+", " ", t)[:300] if tier == 1 else "",
            }
            out["pages"].append(rec)
            if tier == 1:
                out["candidates"].append(rec)
            else:
                sheets_src.append((pdf.name, i + 1, pdf))
        if plumber is not None:
            plumber.close()
    # contact sheets for tier 2 — the model LOOKS at every remaining page
    out["sheets"] = []
    save(args.out, out)  # candidates first; sheets are appended below and saved again
    if args.triage_dir and sheets_src and shutil.which("pdftoppm"):
        from PIL import Image, ImageDraw

        tdir = Path(args.triage_dir)
        tdir.mkdir(parents=True, exist_ok=True)
        for stale in tdir.glob(".sheet-*.png.tmp"):
            stale.unlink(missing_ok=True)
        pending_sheets: list[tuple[Path, Path]] = []
        PER, COLS, TW, TH = 20, 4, 220, 300
        for si in range(0, len(sheets_src), PER):
            chunk = sheets_src[si : si + PER]
            rows = (len(chunk) + COLS - 1) // COLS
            sheet = Image.new("RGB", (COLS * TW, rows * (TH + 18)), "white")
            draw = ImageDraw.Draw(sheet)
            cells = []
            with tempfile.TemporaryDirectory() as td:
                for ci, (fname, page1, pdfp) in enumerate(chunk):
                    prefix = Path(td) / f"c{ci}"
                    subprocess.run(
                        [
                            "pdftoppm",
                            "-png",
                            "-r",
                            "36",
                            "-f",
                            str(page1),
                            "-l",
                            str(page1),
                            "-singlefile",
                            str(pdfp),
                            str(prefix),
                        ],
                        capture_output=True,
                    )
                    png = Path(str(prefix) + ".png")
                    x, y = (ci % COLS) * TW, (ci // COLS) * (TH + 18)
                    if png.exists():
                        im = Image.open(png)
                        im.thumbnail((TW - 8, TH - 8))
                        sheet.paste(im, (x + 4, y + 4))
                    label = f"{ci + 1}: {fname[:22]} p{page1}"
                    draw.text((x + 4, y + TH + 2), label, fill="black")
                    cells.append({"cell": ci + 1, "file": fname, "page": page1})
            sp = tdir / f"sheet-{si // PER + 1:02d}.png"
            tmp = tdir / f".{sp.name}.tmp"
            sheet.save(tmp, format="PNG")
            pending_sheets.append((tmp, sp))
            out["sheets"].append({"sheet": str(sp), "cells": cells})
        for tmp, sp in pending_sheets:  # every sheet exists before any is final
            os.replace(tmp, sp)
    save(args.out, out)
    if getattr(args, "emit_batches", 0):
        # Classification fan-out. Whole documents per batch — a candidate is judged with
        # its document in view (file name, cover page, exhibit context), so a document is
        # never split across workers.
        bdir = (
            Path(args.batch_dir)
            if args.batch_dir
            else args.workspace / "tmp/sigpack/scan-batches"
        )
        bdir.mkdir(parents=True, exist_ok=True)
        rdir = Path(args.render_dir or (bdir / "renders"))
        rdir.mkdir(parents=True, exist_ok=True)
        by_doc: dict[str, list] = {}
        for cand in out["candidates"]:
            by_doc.setdefault(cand["file"], []).append(cand)
        cap = max(1, int(args.emit_batches))
        batches: list[list[tuple[str, list]]] = [[]]
        count = 0
        for fname, cands in by_doc.items():
            if count and count + len(cands) > cap:
                batches.append([])
                count = 0
            batches[-1].append((fname, cands))
            count += len(cands)
        for bi, docs in enumerate(batches, 1):
            entry_docs = []
            for fname, cands in docs:
                pdfp = folder / fname
                pages_entries = []
                for cand in cands:
                    render = render_page(pdfp, cand["page"], rdir)
                    pages_entries.append(
                        {
                            **{
                                k: cand.get(k)
                                for k in (
                                    "page",
                                    "reasons",
                                    "marker_hits",
                                    "sig_lines",
                                    "footer_agreement",
                                    "footer_party",
                                    "version_marker",
                                    "negative_signal",
                                    "form_like",
                                    "text_preview",
                                )
                            },
                            "render": render,
                            "is_signature_page": None,
                            "agreement": None,
                            "blocks": None,
                            "reserved": False,
                            "esig_separator": False,
                        }
                    )
                entry_docs.append(
                    {
                        "file": fname,
                        "source_pdf": str(pdfp),
                        "pages_total": next(
                            d["pages"] for d in out["documents"] if d["file"] == fname
                        ),
                        "candidates": pages_entries,
                    }
                )
            save(
                bdir / f"scan-batch-{bi:02d}.json",
                {
                    "instructions": "For each candidate: open `render` and look at it beside `text_preview`, with the whole document in view (`file`, `source_pdf` for the cover page, exhibit/schedule context) per references/signature_page_rules.md. Fill `is_signature_page` (true/false). If true: fill `agreement` and `blocks` — one record per block, {party, signatory, capacity, copies_required?, signatures?}; mark spare blank pages `reserved` and pages needing a separator sheet `esig_separator`. Blank fields are 'Unknown'. If false, leave blocks null. Never guess; never skip a candidate.",
                    "documents": entry_docs,
                },
            )
        print(
            f"emitted {len(batches)} classification batches (<= {cap} candidate pages each, whole documents) -> {bdir}/ (fill and `assemble`). Contact sheets stay with you: LOOK at every sheet regardless."
        )
    n_pages = len(out["pages"])
    n_t1 = len(out["candidates"])
    n_t2 = n_pages - n_t1
    print(
        f"scanned {len(out['documents'])} documents, {n_pages} pages: {n_t1} tier-1 (read at full size), {n_t2} tier-2 on {len(out['sheets'])} contact sheets -> {args.out}"
    )
    if not plumber_available:
        print(
            "WARNING: pdfplumber is not installed — geometry features (drawn signature lines, word/short-line density) are all zero. Tiering fell back to markers/footers/position only; recall is weaker. Install pdfplumber or treat every tier-2 page as unconfirmed."
        )
    if n_t2 and not out["sheets"]:
        why = (
            "no --triage-dir given"
            if not args.triage_dir
            else "pdftoppm (Poppler) not found"
        )
        print(
            f"WARNING: {n_t2} tier-2 pages have NO contact sheets ({why}) — they have not been looked at and are NOT covered. Re-run with --triage-dir (and Poppler installed) or render those pages yourself before claiming the denominator."
        )
    else:
        print(
            "Denominator: every page is either tier-1 or on a sheet; nothing was excluded by text."
        )
    print(
        "Next: read every tier-1 candidate (render it); LOOK at every sheet and mark cells yes/unsure; zoom unsure; then write classified.json and `init`."
    )


# ---------------------------------------------------------------- init
def cmd_init(args):
    """Open the ledger from the model's classification.
    classified.json = {"signature_pages":[{file,page,agreement,blocks:[{party,signatory,capacity,copies_required?}],reserved?,esig_separator?}]}"""
    ledger_path = Path(args.ledger)
    if ledger_path.exists():
        if not getattr(args, "force", False):
            sys.exit(
                f"init refused: {ledger_path} already exists and holds a matter's ledger. "
                "Use `status` to read it, or `init --force` to start over (the old file "
                "is kept as a .bak copy)."
            )
        stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        backup = ledger_path.with_name(ledger_path.name + f".bak-{stamp}")
        shutil.copy2(ledger_path, backup)
        print(f"init --force: previous ledger kept at {backup.name}")
    cl = load(args.classified)
    exec_dir = Path(args.execution)
    led = {
        "matter": args.matter or exec_dir.resolve().parent.name,
        "created": today(),
        "closing_date": None,
        "execution_dir": str(exec_dir),
        "returned_dirs": [],
        "signature_pages": [],
        "packs_sent": [],
        "returned_pages": [],
        "unmatched_returns": [],
        "receipt": {},
    }
    counts: dict = defaultdict(int)
    for p in cl["signature_pages"]:
        if not p.get("is_signature_page", True):
            continue
        code = short_code(p.get("agreement") or Path(p["file"]).stem)
        pid = f"{code}-p{p['page']}"
        if any(x["id"] == pid for x in led["signature_pages"]):
            counts[pid] += 1
            pid = f"{pid}-{counts[pid]}"
        try:
            rd = PdfReader(str(exec_dir / p["file"]))
            t = page_text(rd, p["page"] - 1, exec_dir / p["file"])
        except Exception:
            t = ""
        foot = FOOTER.search(t)
        vm = VERSION.search(t)
        blocks = []
        for i, b in enumerate(p.get("blocks") or [{}], 1):
            sigs = b.get("signatures") or []
            if not sigs and (b.get("signatory") or b.get("capacity")):
                sigs = [
                    {
                        "name": b.get("signatory") or "Unknown",
                        "capacity": b.get("capacity") or "Unknown",
                        "role": "signatory",
                    }
                ]
            blocks.append(
                {
                    "block": i,
                    "party": b.get("party") or "Unknown",
                    "signatory": b.get("signatory") or "Unknown",
                    "capacity": b.get("capacity") or "Unknown",
                    "signatures": sigs,
                    "signatures_required": max(1, len(sigs)),
                    "date_field": bool(re.search(r"\bDated?:", t)),
                    "copies_required": int(b.get("copies_required") or 1),
                    "status": "required",
                    "returned": [],
                }
            )
        led["signature_pages"].append(
            {
                "id": pid,
                "file": p["file"],
                "page": p["page"],
                "agreement": p.get("agreement") or Path(p["file"]).stem,
                "footer": (foot.group(0).strip() if foot else None),
                "version_marker": vm.group(1) if vm else None,
                "reserved": bool(p.get("reserved")),
                "origin": p.get("origin", "discovered"),
                "esig_separator": bool(p.get("esig_separator")),
                "blocks": blocks,
            }
        )
    recompute_receipt(led)
    save(args.ledger, led)
    print(
        f"ledger opened: {args.ledger} — {len(led['signature_pages'])} signature pages, {led['receipt']['blocks_required']} blocks"
    )
    print_receipt(led)


# ---------------------------------------------------------------- build
def cmd_build(args):
    led = load(args.ledger)
    exec_dir = Path(led["execution_dir"])
    pages = [p for p in led["signature_pages"] if page_is_live(p)]
    groups: dict = defaultdict(list)  # group -> [(page, block)]
    for p in pages:
        if args.group == "agreement":
            for b in p["blocks"]:
                groups[p["agreement"]].append((p, b))
        else:
            key = "party" if args.group == "counterparty" else "signatory"
            seen = set()
            for b in p["blocks"]:
                k = (b.get(key) or "Unknown").strip()
                if k in seen and (args.no_duplicate or args.group == "signatory"):
                    continue
                seen.add(k)
                groups[k].append((p, b))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pack_cm = staged(out_dir, "packs")
    pack_stage = pack_cm.__enter__()
    readers: dict = {}
    sent: list[dict[str, object]] = []
    for g, items in groups.items():
        seen_pages = set()
        ordered = []
        for p, b in sorted(
            items, key=lambda x: (x[0]["file"], x[0]["page"], x[1]["block"])
        ):
            if args.group == "agreement" and p["id"] in seen_pages:
                continue
            seen_pages.add(p["id"])
            ordered.append((p, b))
        w = PdfWriter()
        page_ids = []
        for p, b in ordered:
            rd = readers.setdefault(p["file"], PdfReader(str(exec_dir / p["file"])))
            copies = max(int(args.copies or 1), int(b.get("copies_required") or 1))
            for _ in range(copies):
                w.add_page(rd.pages[p["page"] - 1])
            page_ids.append(p["id"])
            for bb in p["blocks"]:
                if bb.get("status") == "required" and (
                    args.group == "agreement" or bb is b
                ):
                    bb["status"] = "sent"
        safe = re.sub(r'[/\\?%*:|"<>]', "", args.name.format(group=g)).strip()
        path = pack_stage / f"{safe}.pdf"
        with open(path, "wb") as fh:
            w.write(fh)
        sent.append(
            {
                "group_by": args.group,
                "group": g,
                "file": path.name,
                "sent": today(),
                "pages": page_ids,
                "copies": int(args.copies or 1),
            }
        )
    led["packs_sent"].extend(sent)
    rows = [
        {
            "party": b["party"],
            "document": p["agreement"],
            "sign_as": b["capacity"],
            "by": b["signatory"],
            "copies": max(int(args.copies or 1), int(b.get("copies_required") or 1)),
            "page_id": p["id"],
        }
        for p in pages
        for b in p["blocks"]
    ]
    rows.sort(key=lambda r: (str(r["party"]), str(r["document"])))
    save(out_dir / "instructions.json", rows)
    save(out_dir / "packs.json", {"group_by": args.group, "packs": sent})
    recompute_receipt(led)
    save(args.ledger, led)
    pack_cm.__exit__(None, None, None)  # ledger saved: the packs become real
    print(
        f"built {len(sent)} packs by {args.group} -> {out_dir}/ ; instructions.json has {len(rows)} rows; ledger updated"
    )
    for s in sent:
        pages = s["pages"]
        page_count = len(pages) if isinstance(pages, list) else 0
        print(f"  {s['file']}: {page_count} page ids")


# ---------------------------------------------------------------- read
def _read_one_page(rd, i: int, pdf: Path, batch: str, args, stage) -> dict:
    """One returned page's registry record; the render goes into `stage`."""
    t = page_text(rd, i, pdf)
    scanned = len(t.strip()) < 5
    src = "native"
    if scanned and args.ocr:
        t = ocr_page(pdf, i + 1)
        src = "ocr"
    foot = FOOTER.search(t)
    vm = VERSION.search(t)
    fa = foot.group("agreement").strip() if foot else None
    fp = ((foot.group("party") or "").strip() or None) if foot else None
    return {
        "pack": pdf.name,
        "page": i + 1,
        "batch": batch,
        "scanned": scanned,
        "text_source": src,
        "footer_agreement": fa,
        "footer_party": fp,
        "version_marker": vm.group(1) if vm else None,
        "esign_artifact": bool(ESIG.search(t)),
        "sheet_hash": sheet_hash(rd.pages[i]),
        "render": render_page(pdf, i + 1, stage) if stage is not None else None,
        "agreement": fa,
        "party": fp,
        "execution": "unknown",  # model fills: signed | partial | blank | unclear | not-a-signature-page
        "printed_name": None,
        "dated": None,
        "text_preview": re.sub(r"\s+", " ", t)[:200],
    }


def cmd_read(args):
    """Register a batch of returned pages against the ledger. Emits execution:'unknown' per page for the model to fill from the render."""
    led = load(args.ledger)
    folder = Path(args.returned)
    batch = str(folder)
    if batch not in led["returned_dirs"]:
        led["returned_dirs"].append(batch)
    render_dir = Path(args.render_dir) if args.render_dir else None
    if render_dir is not None:
        clear_staging(render_dir)
    reg = led.setdefault("returned_pages", [])
    known = {(r["pack"], r.get("page"), r["batch"]) for r in reg}
    new = 0
    for pdf in own_pdfs(folder):
        try:
            rd = PdfReader(str(pdf))
            if rd.is_encrypted:
                try:
                    rd.decrypt("")
                except Exception:
                    if (pdf.name, None, batch) not in known:
                        reg.append(
                            {
                                "pack": pdf.name,
                                "page": None,
                                "batch": batch,
                                "error": "encrypted; unlock/flatten first if permitted",
                            }
                        )
                    continue
        except Exception as e:  # noqa: BLE001
            if (pdf.name, None, batch) not in known:
                reg.append(
                    {
                        "pack": pdf.name,
                        "page": None,
                        "batch": batch,
                        "error": f"unreadable: {e.__class__.__name__}",
                    }
                )
            continue
        # Renders for this PDF land in a staging folder and become real only once
        # every page of it has been read; a failure leaves nothing half-written.
        stage_cm = (
            staged(render_dir, pdf.stem) if render_dir else contextlib.nullcontext()
        )
        added: list[dict] = []
        with stage_cm as stage:
            for i in range(len(rd.pages)):
                if (pdf.name, i + 1, batch) in known:
                    continue
                added.append(_read_one_page(rd, i, pdf, batch, args, stage))
        for rec in added:
            if rec.get("render") and render_dir is not None:
                rec["render"] = str(render_dir / Path(rec["render"]).name)
            reg.append(rec)
            new += 1
        save(args.ledger, led)  # per source PDF: a later failure leaves it consistent
    recompute_receipt(led)
    checkpoint(led, folder.name)
    save(args.ledger, led)
    if getattr(args, "emit_batches", 0):
        bdir = (
            Path(args.batch_dir)
            if args.batch_dir
            else args.workspace / "tmp/sigpack/batches"
        )
        bdir.mkdir(parents=True, exist_ok=True)
        todo = [
            r
            for r in reg
            if r.get("page") and r["batch"] == batch and r.get("execution") == "unknown"
        ]
        n = max(1, int(args.emit_batches))
        for i in range(0, len(todo), n):
            chunk = todo[i : i + n]
            save(
                bdir / f"batch-{i // n + 1:02d}.json",
                {
                    "instructions": "For each page: open `render`, decide `execution` (signed|partial|blank|unclear|not-a-signature-page) per references/signature_page_rules.md; fill `agreement` and `party` if null from the block/footer; `printed_name` as printed; `dated` if a date is already on the page. Return the same list with those fields filled. Never guess; use unclear.",
                    "pages": [
                        {
                            k: r.get(k)
                            for k in (
                                "pack",
                                "page",
                                "batch",
                                "render",
                                "footer_agreement",
                                "footer_party",
                                "agreement",
                                "party",
                                "execution",
                                "printed_name",
                                "dated",
                                "text_preview",
                            )
                        }
                        for r in chunk
                    ],
                },
            )
        print(
            f"emitted {(len(todo) + n - 1) // n} worker batches of <= {n} pages -> {bdir}/ (fill and `merge`)"
        )
    need_ap = [
        r
        for r in reg
        if r.get("page") and r["batch"] == batch and not r.get("agreement")
    ]
    print(
        f"registered {new} new returned pages from {batch} -> ledger; {len(need_ap)} need agreement/party from the render; every page needs `execution` filled from the render before compile."
    )


# ---------------------------------------------------------------- merge (worker verdicts -> ledger)
def cmd_assemble(args):
    """Fold filled scan-classification batches into one classified.json. Refuses while any candidate is unanswered — the classification denominator must balance before init."""
    bdir = Path(args.batches)
    bfiles = sorted(bdir.glob("scan-batch-*.json"))
    if not bfiles:
        sys.exit(f"assemble: no scan-batch-*.json in {bdir}")
    pages = []
    unanswered = []
    bad = []
    judged = 0
    rejected = 0
    for bf in bfiles:
        d = load(bf)
        for doc in d.get("documents", []):
            for cand in doc.get("candidates", []):
                judged += 1
                isp = cand.get("is_signature_page")
                if not isinstance(isp, bool):
                    unanswered.append((bf.name, doc["file"], cand.get("page")))
                    continue
                if not isp:
                    rejected += 1
                    continue
                blocks = cand.get("blocks")
                if not blocks or not all(b.get("party") for b in blocks):
                    bad.append((bf.name, doc["file"], cand.get("page")))
                    continue
                pages.append(
                    {
                        "file": doc["file"],
                        "page": cand["page"],
                        "agreement": cand.get("agreement")
                        or cand.get("footer_agreement")
                        or Path(doc["file"]).stem,
                        "is_signature_page": True,
                        "blocks": blocks,
                        **({"reserved": True} if cand.get("reserved") else {}),
                        **(
                            {"esig_separator": True}
                            if cand.get("esig_separator")
                            else {}
                        ),
                    }
                )
    if unanswered or bad:
        for src, f, p in unanswered[:5]:
            print(f"  UNANSWERED  {src}: {f} p{p} — is_signature_page not filled")
        for src, f, p in bad[:5]:
            print(f"  BAD  {src}: {f} p{p} — marked yes but blocks missing a party")
        sys.exit(
            f"assemble refused: {len(unanswered)} unanswered, {len(bad)} bad of {judged} candidates. Every candidate is answered or nothing assembles."
        )
    out = {"execution_dir": str(Path(args.execution)), "signature_pages": pages}
    save(args.out, out)
    print(
        f"assembled {len(pages)} signature pages from {judged} candidates across {len(bfiles)} batches ({rejected} rejected) -> {args.out}. Contact sheets are still yours to LOOK at before init."
    )


def cmd_merge(args):
    """Fold per-page verdicts back into the ledger. Verdict files are the batch files with fields filled, or any JSON list of {pack,page,batch,execution,agreement,party,printed_name,dated}."""
    led = load(args.ledger)
    idx = {
        (r["pack"], r.get("page"), r["batch"]): r for r in led.get("returned_pages", [])
    }
    n = 0
    bad = []
    for f in sorted(Path(args.verdicts).glob("*.json")):
        d = load(f)
        items = d.get("pages", d) if isinstance(d, dict) else d
        for v in items:
            r = idx.get((v.get("pack"), v.get("page"), v.get("batch")))
            if not r:
                bad.append((f.name, v.get("pack"), v.get("page")))
                continue
            ex = v.get("execution")
            if ex not in (
                "signed",
                "partial",
                "blank",
                "unclear",
                "not-a-signature-page",
            ):
                bad.append(
                    (f.name, v.get("pack"), v.get("page"), f"bad execution {ex!r}")
                )
                continue
            for k in ("agreement", "party", "printed_name", "dated"):
                if v.get(k) is not None:
                    r[k] = v[k]
            r["execution"] = ex
            r["verdict_source"] = f.name
            n += 1
    save(args.ledger, led)
    left = sum(
        1
        for r in led.get("returned_pages", [])
        if r.get("page") and r.get("execution") == "unknown"
    )
    print(
        f"merged {n} verdicts; {left} pages still unknown"
        + (f"; {len(bad)} rejected: {bad[:5]}" if bad else "")
    )
    if bad:
        sys.exit(1)


# ---------------------------------------------------------------- compile
def _target_index(led):
    by_ap: dict = {}
    by_as: dict = defaultdict(list)
    for p in led["signature_pages"]:
        for b in p["blocks"]:
            by_ap[(norm(p["agreement"]), norm(b["party"]))] = (p, b)
            if b.get("signatory") and b["signatory"] != "Unknown":
                by_as[(norm(p["agreement"]), norm(b["signatory"]))].append((p, b))
    return by_ap, by_as


def _match(r, by_ap, by_as):
    key = (norm(r.get("agreement") or ""), norm(r.get("party") or ""))
    hit = by_ap.get(key)
    if not hit and key[1]:
        cands = [
            k for k in by_ap if key[1] == k[1] and (key[0] in k[0] or k[0] in key[0])
        ]
        hit = by_ap[cands[0]] if len(cands) == 1 else None
    if not hit and key[1]:
        sc = by_as.get(key, [])
        sc_open = [t for t in sc if t[1].get("status") != "signed"]
        hit = sc_open[0] if len(sc_open) == 1 else (sc[0] if len(sc) == 1 else None)
    if not hit and key[0] and not key[1]:
        cands = [
            (p, b)
            for (a, _), (p, b) in by_ap.items()
            if a == key[0] or key[0] in a or a in key[0]
        ]
        open_ = [(p, b) for p, b in cands if b.get("status") != "signed"]
        hit = open_[0] if len(open_) == 1 else None
    return hit


def _free_text(
    page_height: float, text: str, x: float, y_from_top: float, w: float = 160.0
):
    y = page_height - y_from_top
    return DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/FreeText"),
            NameObject("/Rect"): ArrayObject(
                [
                    FloatObject(x),
                    FloatObject(y),
                    FloatObject(x + w),
                    FloatObject(y + 14),
                ]
            ),
            NameObject("/Contents"): TextStringObject(text),
            NameObject("/DA"): TextStringObject("/Helv 10 Tf 0 g"),
            NameObject("/T"): TextStringObject("LegalQuants"),
            NameObject("/F"): FloatObject(4),
        }
    )


def cmd_compile(args):
    dry = bool(getattr(args, "dry_run", False))
    led = load(args.ledger)
    if dry:
        # A preview never touches the ledger: work on a copy and write only the plan.
        led = copy.deepcopy(led)
    exec_dir = Path(led["execution_dir"])
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    placements: list[dict] = []
    spare_dir = out_dir / "spare-originals"
    by_ap, by_as = _target_index(led)
    reg = led.get("returned_pages", [])
    pending = [
        r for r in reg if r.get("page") and not r.get("_settled") and not r.get("error")
    ]
    unknown = [r for r in pending if r.get("execution") == "unknown"]
    if unknown:
        sys.exit(
            f"compile refused: {len(unknown)} returned pages still have execution='unknown' — look at the renders and fill signed/partial/blank/unclear/not-a-signature-page first (e.g. {unknown[0]['pack']} p{unknown[0]['page']})."
        )
    date = args.date or led.get("closing_date")
    rejected: list = []
    duplicates: list = []
    # Content index of every return already on a block: the same sheet arriving again
    # under another filename, or read as another party, is a duplicate, not new evidence.
    by_hash: dict = {}
    for p0 in led["signature_pages"]:
        for b0 in p0["blocks"]:
            for x0 in b0.get("returned", []):
                if x0.get("sheet_hash"):
                    by_hash.setdefault(x0["sheet_hash"], (p0["id"], b0["block"], x0))
    placed_now = 0
    for r in pending:
        r["_settled"] = True
        ex = r.get("execution")
        if ex == "not-a-signature-page" or (
            r.get("esign_artifact") and not r.get("agreement")
        ):
            r["outcome"] = "skipped-not-a-signature-page"
            continue
        hit = _match(r, by_ap, by_as)
        if not hit:
            led["unmatched_returns"].append(
                {
                    "pack": r["pack"],
                    "page": r["page"],
                    "batch": r["batch"],
                    "read_as": {
                        "agreement": r.get("agreement"),
                        "party": r.get("party"),
                    },
                    "reason": "no matching signature page (document not in execution set, or party not on that document)",
                }
            )
            r["outcome"] = "unmatched"
            continue
        p, b = hit
        rec = {
            "pack": r["pack"],
            "page": r["page"],
            "batch": r["batch"],
            "execution": ex,
            "printed_name_matches": (
                None
                if not r.get("printed_name") or b["signatory"] == "Unknown"
                else norm(r["printed_name"]) == norm(b["signatory"])
            ),
            "dated": r.get("dated"),
            "sheet_hash": r.get("sheet_hash"),
            "chosen": False,
            "placed_in": None,
            "spare": False,
        }
        earlier = by_hash.get(rec["sheet_hash"]) if rec["sheet_hash"] else None
        if earlier is not None:
            pid0, bn0, x0 = earlier
            rec["duplicate_of"] = {
                "page_id": pid0,
                "block": bn0,
                "pack": x0["pack"],
                "page": x0["page"],
                "batch": x0["batch"],
            }
            b["returned"].append(rec)
            r["outcome"] = "duplicate"
            duplicates.append(
                {
                    "pack": r["pack"],
                    "page": r["page"],
                    "batch": r["batch"],
                    **rec["duplicate_of"],
                }
            )
            continue
        if rec["sheet_hash"]:
            by_hash[rec["sheet_hash"]] = (p["id"], b["block"], rec)
        if (
            p.get("version_marker")
            and r.get("version_marker")
            and p["version_marker"] != r["version_marker"]
        ):
            # A block that is already signed is never downgraded by a later return.
            if b.get("status") != "signed":
                b["status"] = "wrong-version"
            rec["reason"] = f"version {r['version_marker']} != {p['version_marker']}"
            b["returned"].append(rec)
            r["outcome"] = "wrong-version"
            rejected.append(
                {
                    "pack": r["pack"],
                    "page": r["page"],
                    "batch": r["batch"],
                    "page_id": p["id"],
                    "block": b["block"],
                    "reason": rec["reason"],
                }
            )
            continue
        if ex in ("blank", "unclear"):
            if b.get("status") != "signed":
                b["status"] = ex
            b["returned"].append(rec)
            r["outcome"] = ex
            continue
        if ex == "partial":
            if b.get("status") != "signed":
                b["status"] = "partial"
            b["returned"].append(rec)
            r["outcome"] = "partial"
            continue
        need = int(b.get("signatures_required") or 1)
        present = r.get("signatures_present")
        if present is not None and int(present) < need:
            if b.get("status") != "signed":
                b["status"] = "partial"
            rec["reason"] = (
                f"{present} of {need} required marks present (multi-signature block)"
            )
            b["returned"].append(rec)
            r["outcome"] = "partial"
            continue
        if rec["printed_name_matches"] is False:
            if b.get("status") != "signed":
                b["status"] = "unclear"
            rec["reason"] = (
                f"printed name {r.get('printed_name')!r} != manifest {b['signatory']!r}"
            )
            b["returned"].append(rec)
            r["outcome"] = "name-mismatch"
            rejected.append(
                {
                    "pack": r["pack"],
                    "page": r["page"],
                    "batch": r["batch"],
                    "page_id": p["id"],
                    "block": b["block"],
                    "reason": rec["reason"],
                }
            )
            continue
        chosen_count = sum(
            1 for x in b["returned"] if x.get("chosen") or x.get("placed_in")
        )
        if chosen_count >= int(b.get("copies_required") or 1):
            rec["spare"] = True
            b["returned"].append(rec)
            r["outcome"] = "spare"
            continue
        b["status"] = "signed"
        # `chosen` = this is the return picked for this block. `placed_in` = on disk at
        # this address — written only by the writer, on the branch that writes the page.
        rec["chosen"] = True
        b["returned"].append(rec)
        r["outcome"] = "chosen"
        placed_now += 1
    ret_readers: dict = {}

    def reader_for(pack, batch):
        key = (pack, batch)
        if key not in ret_readers:
            ret_readers[key] = PdfReader(str(Path(batch) / pack))
        return ret_readers[key]

    # Clear stale placement claims before the writer runs — a separate pass, above any
    # skip, so documents the writer never reaches cannot keep a false address. Legacy
    # ledgers (placed_in written at match time) are migrated to `chosen` first.
    for p in led["signature_pages"]:
        p.pop("held", None)
        for b in p["blocks"]:
            for x in b.get("returned", []):
                if x.get("placed_in") and "chosen" not in x:
                    x["chosen"] = True
                x["placed_in"] = None
    new_keys = {(r["pack"], r["page"], r["batch"]) for r in pending}
    pages_placed_now = 0
    executed = []
    dated_n = 0
    newly_dated = 0
    already_dated = 0
    no_date_field = 0
    awaiting_instruction = 0
    spare_written = 0
    for doc in sorted({p["file"] for p in led["signature_pages"]}):
        rd = PdfReader(str(exec_dir / doc))
        w = PdfWriter()
        placed_here = 0
        seps = 0
        outp = out_dir / (
            doc
            if doc.startswith("(Executed)")
            else f"(Executed) {doc.replace('(Final) ', '')}"
        )
        pages_here = {p["page"]: p for p in led["signature_pages"] if p["file"] == doc}
        for i in range(len(rd.pages)):
            p = pages_here.get(i + 1)
            # Every chosen return for this page slot, one per block, deduplicated by
            # source sheet. A page executed in counterparts is genuinely several sheets:
            # all of them go into the binder, one after another, in block order.
            srcs = []
            if p:
                allsigned = all(b.get("status") == "signed" for b in p["blocks"])
                anysigned = any(b.get("status") == "signed" for b in p["blocks"])
                if allsigned or (args.place_partial and anysigned):
                    seen_sheets = set()
                    for b in p["blocks"]:
                        # every chosen return of the block: one sheet per
                        # required copy, counterparts back to back
                        for x in b["returned"]:
                            if x.get("chosen"):
                                k = x.get("sheet_hash") or (
                                    x["pack"],
                                    x["page"],
                                    x["batch"],
                                )
                                if k not in seen_sheets:
                                    seen_sheets.add(k)
                                    srcs.append(x)
                elif anysigned:
                    p["held"] = {
                        "waiting_on": [
                            b["party"]
                            for b in p["blocks"]
                            if b.get("status") != "signed"
                        ]
                    }
            if srcs and p is not None:
                placement = {
                    "document": outp.name,
                    "page": i + 1,
                    "sheets": [],
                    "dating": "not dating" if not date else None,
                    "separator": bool(args.separator and p.get("esig_separator")),
                }
                placements.append(placement)
                if args.separator and p.get("esig_separator"):
                    w.add_blank_page(width=612, height=792)
                    w.pages[-1][NameObject("/Annots")] = ArrayObject(
                        [
                            w._add_object(
                                _free_text(
                                    792,
                                    f"E-SIGNED PAGES FOLLOW — {p['agreement']}",
                                    150,
                                    380,
                                    320,
                                )
                            )
                        ]
                    )
                    seps += 1
                for src in srcs:
                    pg = reader_for(src["pack"], src["batch"]).pages[src["page"] - 1]
                    w.add_page(pg)
                    placed_here += 1
                    src["placed_in"] = f"(Executed) {outp.name}#{len(w.pages)}"
                    placement["sheets"].append(
                        {
                            "pack": src["pack"],
                            "page": src["page"],
                            "batch": src["batch"],
                            "new": (src["pack"], src["page"], src["batch"]) in new_keys,
                        }
                    )
                    if (src["pack"], src["page"], src["batch"]) in new_keys:
                        pages_placed_now += 1
                    # Dating is an instruction, never a default. A sheet dated on an
                    # earlier run keeps its date on every rebuild; a sheet placed for
                    # the first time is dated only when --date is given on this run.
                    sheet_date = src.get("dated_applied") or args.date
                    if date:
                        if src.get("dated"):
                            already_dated += 1
                            placement["dating"] = "already dated"
                        elif not any(b.get("date_field") for b in p["blocks"]):
                            no_date_field += 1
                            placement["dating"] = "no date field"
                        elif not sheet_date:
                            awaiting_instruction += 1
                            placement["dating"] = "awaiting instruction"
                        else:
                            placement["dating"] = f"dated {sheet_date}"
                            h = float(pg.mediabox.height)
                            existing = w.pages[-1].get("/Annots")
                            annots = ArrayObject(
                                list(existing.get_object())
                                if existing is not None
                                else []
                            )
                            annots.append(
                                w._add_object(
                                    _free_text(h, f"Dated: {sheet_date}", 400, 700)
                                )
                            )
                            w.pages[-1][NameObject("/Annots")] = annots
                            if not src.get("dated_applied"):
                                newly_dated += 1
                            src["dated_applied"] = sheet_date
                            dated_n += 1
            else:
                w.add_page(rd.pages[i])
        if not dry:
            with open(outp, "wb") as fh:
                w.write(fh)
        executed.append(
            {
                "file": outp.name,
                "pages": len(w.pages),
                "signed_pages_placed": placed_here,
                "separators": seps,
            }
        )
    for p in led["signature_pages"]:
        for b in p["blocks"]:
            for x in b["returned"]:
                if x.get("spare") and not x.get("spare_file"):
                    if dry:
                        spare_written += 1
                        continue
                    spare_dir.mkdir(parents=True, exist_ok=True)
                    sw = PdfWriter()
                    sw.add_page(reader_for(x["pack"], x["batch"]).pages[x["page"] - 1])
                    n = len([y for y in b["returned"] if y.get("spare_file")]) + 1
                    sf = spare_dir / f"{p['id']}-block{b['block']}-spare{n}.pdf"
                    with open(sf, "wb") as fh:
                        sw.write(fh)
                    x["spare_file"] = sf.name
                    spare_written += 1
    copies_outstanding = sum(
        max(
            0,
            int(b.get("copies_required") or 1)
            - sum(1 for x in b.get("returned", []) if x.get("chosen")),
        )
        for p in led["signature_pages"]
        for b in p["blocks"]
        if page_is_live(p) and b.get("status") == "signed"
    )
    if date:
        led["closing_date"] = date
    recompute_receipt(led)
    since_last = delta(led)
    if not dry:
        checkpoint(led, "compile")
        save(args.ledger, led)
    report = {
        "placed_now": placed_now,
        "pages_placed_now": pages_placed_now,
        "executed": executed,
        "receipt": led["receipt"],
        "unmatched": led["unmatched_returns"],
        "rejected": rejected,
        "duplicates": duplicates,
        "copies_outstanding": copies_outstanding,
        "since_last": since_last,
        "placements": placements,
        "dating": {
            "date": date,
            "dated": dated_n,
            "newly_dated": newly_dated,
            "already_dated": already_dated,
            "no_date_field": no_date_field,
            "awaiting_instruction": awaiting_instruction,
        }
        if date
        else None,
        "spare_written": spare_written,
    }
    if dry:
        plan = {
            "dry_run": True,
            "would_place_now": placed_now,
            "would_write_sheets": pages_placed_now,
            "would_reject": rejected,
            "would_duplicate": duplicates,
            "would_spare": spare_written,
            "placements": placements,
            "executed": executed,
            "dating": report["dating"],
            "receipt_after": led["receipt"],
            "since_last": since_last,
        }
        save(out_dir / "compile-plan.json", plan)
        print(
            f"DRY RUN — nothing written except compile-plan.json. Would choose {placed_now} "
            f"new blocks, write {pages_placed_now} newly signed sheets into "
            f"{len(executed)} documents, file {spare_written} spare originals"
            + (f", reject {len(rejected)}" if rejected else "")
            + (f", skip {len(duplicates)} duplicates" if duplicates else "")
            + "."
        )
        for pl in placements:
            if any(s["new"] for s in pl["sheets"]):
                sheets = ", ".join(f"{s['pack']} p{s['page']}" for s in pl["sheets"])
                print(
                    f"  {pl['document']} p{pl['page']}  <-  {sheets}  [{pl['dating']}]"
                )
        print_delta(since_last)
        print_receipt(led)
        return
    save(out_dir / "compile-report.json", report)
    (out_dir / "closing-checklist.md").write_text(render_checklist(led))
    print(
        f"chose {placed_now} new blocks · wrote {pages_placed_now} newly signed sheets · executed {len(executed)} documents · spare originals {spare_written}"
        + (
            f" · dated {dated_n} ({newly_dated} newly, already {already_dated}, "
            f"no field {no_date_field}, awaiting instruction {awaiting_instruction})"
            if date
            else ""
        )
        + (f" · REJECTED {len(rejected)}" if rejected else "")
        + (
            f" · copies still outstanding {copies_outstanding}"
            if copies_outstanding
            else ""
        )
        + (f" · DUPLICATE {len(duplicates)}" if duplicates else "")
    )
    for x in rejected:
        print(
            f"  REJECTED  {x['pack']} p{x['page']} -> {x['page_id']} block {x['block']}: {x['reason']}"
        )
    print_delta(since_last)
    for x in duplicates:
        print(
            f"  DUPLICATE {x['pack']} p{x['page']} = {x['pack']!s} already on {x['page_id']} block {x['block']} (from {x['batch']})"
        )
    print_receipt(led)


# ---------------------------------------------------------------- chase / checklist
MARK = {
    "signed": "\u2713",
    "partial": "\u25d0",
    "blank": "\u2717",
    "unclear": "\u2717",
    "wrong-version": "\u27f3",
    "required": "\u00b7",
    "sent": "\u00b7",
}


def _block_need(p: dict, b: dict) -> str | None:
    """Why this block is outstanding, in the ledger's own words, or None."""
    status = b.get("status", "required")
    returns = b.get("returned", [])
    if status in ("required", "sent"):
        return "not returned"
    if status == "blank":
        return "returned unsigned"
    if status == "unclear":
        last = next((x for x in reversed(returns) if x.get("reason")), None)
        return (
            f"unclear: {last['reason']}"
            if last
            else "scan unreadable; a clean copy is needed"
        )
    if status == "wrong-version":
        last = next((x for x in reversed(returns) if x.get("reason")), None)
        return (
            f"wrong version signed ({last['reason']})"
            if last
            else "wrong version signed"
        )
    if status == "partial":
        need = int(b.get("signatures_required") or 1)
        last = next((x for x in reversed(returns) if x.get("reason")), None)
        marks = ", ".join(
            f"{s.get('name') or s.get('role')} ({s.get('role')})"
            for s in b.get("signatures") or []
        )
        return (
            f"partly signed: {last['reason'] if last else f'{need} marks required'}"
            + (f"; marks: {marks}" if marks else "")
        )
    if status == "signed":
        copies = int(b.get("copies_required") or 1)
        chosen = sum(1 for x in returns if x.get("chosen"))
        if chosen < copies:
            return f"{copies - chosen} more original(s) to sign ({copies} required)"
    return None


def outstanding_by_party(led: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for p in led["signature_pages"]:
        if not page_is_live(p):
            continue
        for b in p["blocks"]:
            need = _block_need(p, b)
            if need:
                out[b.get("party") or "Unknown"].append(
                    {
                        "page_id": p["id"],
                        "document": p["agreement"],
                        "page": p["page"],
                        "block": b["block"],
                        "signatory": b.get("signatory"),
                        "need": need,
                    }
                )
    return dict(out)


def _packs_for(led: dict, page_ids: set[str]) -> list[dict]:
    return [
        pk for pk in led.get("packs_sent", []) if page_ids & set(pk.get("pages") or [])
    ]


def cmd_chase(args):
    """One Markdown file per party with anything outstanding: the facts, never a send."""
    led = load(args.ledger)
    recompute_receipt(led)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {}
    for party, items in sorted(outstanding_by_party(led).items()):
        held = [
            (p["agreement"], p["page"])
            for p in led["signature_pages"]
            for b in p["blocks"]
            if b.get("party") == party and b.get("status") == "signed"
        ]
        ids = {i["page_id"] for i in items}
        packs = _packs_for(led, ids)
        lines = [
            f"# {party} — signature pages still needed",
            "",
            f"Subject: {led['matter']}: signature pages still needed — {len(items)} item(s)",
            "",
            "## Still needed",
        ]
        for i in items:
            who = (
                f" ({i['signatory']})"
                if i.get("signatory") and i["signatory"] != "Unknown"
                else ""
            )
            lines.append(
                f"- {i['document']}, signature page {i['page']} (block {i['block']}){who}: {i['need']}"
            )
        if held:
            lines += ["", "## Already received, with thanks"]
            lines += [f"- {a}, page {pg}" for a, pg in held]
        if packs:
            lines += ["", "## Pack sent"]
            lines += [
                f"- {pk['file']} on {pk.get('sent')} ({pk.get('group_by')}: {pk.get('group')})"
                for pk in packs
            ]
        lines += [
            "",
            "_Facts from the ledger as of "
            + today()
            + ". Draft for the lawyer to send; nothing has been sent._",
        ]
        safe = re.sub(r'[/\\?%*:|"<>]', "", party).strip()[:80]
        f = out_dir / f"chase - {safe}.md"
        f.write_text("\n".join(lines) + "\n")
        index[party] = {"file": f.name, "items": len(items)}
    save(out_dir / "index.json", index)
    if not index:
        print("nothing outstanding — no chasers to write")
        return
    print(
        f"wrote {len(index)} chaser draft(s) -> {out_dir}/ (facts only; nothing sent)"
    )
    for party, meta in index.items():
        print(f"  {party}: {meta['items']} item(s) -> {meta['file']}")


def render_checklist(led: dict) -> str:
    recompute_receipt(led)
    r = led["receipt"]
    parties: list[str] = []
    docs: list[str] = []
    cells: dict[tuple[str, str], list[str]] = defaultdict(list)
    for p in led["signature_pages"]:
        if not page_is_live(p):
            continue
        if p["agreement"] not in docs:
            docs.append(p["agreement"])
        for b in p["blocks"]:
            party = b.get("party") or "Unknown"
            if party not in parties:
                parties.append(party)
            cells[(party, p["agreement"])].append(
                MARK.get(b.get("status", "required"), "?")
            )
    lines = [
        f"# Closing checklist — {led['matter']} (as of {today()})",
        "",
        f"{r['pages_required']} pages / {r['blocks_required']} blocks required · {r['blocks_signed']} signed · "
        f"{r['blocks_partial']} partial · {r['blocks_blank']} blank · {r['blocks_unclear']} unclear · "
        f"{r['blocks_wrong_version']} wrong-version · {r['blocks_missing']} missing · "
        f"{'COMPLETE' if r['complete'] else 'NOT COMPLETE'}",
        "",
        "\u2713 signed · \u25d0 partial · \u2717 blank or unclear · \u27f3 wrong version · \u00b7 not returned",
        "",
        "| Party | " + " | ".join(docs) + " |",
        "|---|" + "---|" * len(docs),
    ]
    for party in parties:
        row = [" ".join(cells.get((party, d), [])) or " " for d in docs]
        lines.append(f"| {party} | " + " | ".join(row) + " |")
    outstanding = outstanding_by_party(led)
    if outstanding:
        lines += ["", "## Outstanding"]
        for party, items in sorted(outstanding.items()):
            for i in items:
                lines.append(
                    f"- {party}: {i['document']} p{i['page']} block {i['block']} — {i['need']}"
                )
    return "\n".join(lines) + "\n"


def cmd_checklist(args):
    led = load(args.ledger)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_checklist(led))
    print(f"wrote {out}")


# ---------------------------------------------------------------- status
def cmd_status(args):
    led = load(args.ledger)
    recompute_receipt(led)
    print(
        f"{led['matter']} — created {led['created']} — closing date {led.get('closing_date') or 'not set'} — batches: {len(led['returned_dirs'])}"
    )
    if getattr(args, "since", None) is not None:
        d = delta(led, args.since or None)
        if d is None:
            print("no checkpoint yet — nothing to compare against")
        elif not d["moved"]:
            print(
                f"nothing moved since {d['since']['label']} ({d['since']['at'][:10]})"
            )
        else:
            print_delta(d)
    print_receipt(led)
    if led.get("unmatched_returns"):
        print(f"  unmatched returns: {len(led['unmatched_returns'])}")
        for u in led["unmatched_returns"][:10]:
            print(f"    {u['pack']} p{u['page']} read as {u['read_as']}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    dr = sub.add_parser("draft")
    dr.add_argument("--ledger", required=False)
    dr.add_argument("--matrix", required=True)
    dr.add_argument("--template", required=True)
    dr.add_argument("--out-dir", required=True)
    dr.add_argument("--execution", default=None)
    cv = sub.add_parser("convert")
    cv.add_argument("folder")
    cv.add_argument("--out-dir", required=True)
    cv.add_argument("--force", action="store_true")
    s = sub.add_parser("scan")
    s.add_argument("folder")
    s.add_argument("--out", default="candidates.json")
    s.add_argument("--ocr", action="store_true")
    s.add_argument("--triage-dir", default=None)
    s.add_argument(
        "--emit-batches",
        type=int,
        default=0,
        help="emit classification batches of <= N candidate pages (whole documents per batch) for parallel workers",
    )
    s.add_argument(
        "--batch-dir",
        default=None,
        help="where the scan-batch-NN.json worker files go (default tmp/sigpack/scan-batches)",
    )
    s.add_argument(
        "--render-dir",
        default=None,
        help="where candidate renders go (default <batch-dir>/renders)",
    )
    asm = sub.add_parser("assemble")
    asm.add_argument(
        "--batches",
        required=True,
        help="folder of filled scan-batch-NN.json files",
    )
    asm.add_argument("--execution", required=True, help="the execution-versions folder")
    asm.add_argument("--out", default="classified.json")
    i = sub.add_parser("init")
    i.add_argument("--ledger", required=True)
    i.add_argument("--execution", required=True)
    i.add_argument("--classified", required=True)
    i.add_argument("--matter", default=None)
    i.add_argument(
        "--force",
        action="store_true",
        help="Reinitialise over an existing ledger; the old file is kept as a .bak copy.",
    )
    b = sub.add_parser("build")
    b.add_argument("--ledger", required=True)
    b.add_argument(
        "--group", choices=["agreement", "counterparty", "signatory"], required=True
    )
    b.add_argument("--out-dir", required=True)
    b.add_argument("--copies", type=int, default=1)
    b.add_argument("--no-duplicate", action="store_true")
    b.add_argument("--name", default="Signature Pack – {group}")
    r = sub.add_parser("read")
    r.add_argument("--ledger", required=True)
    r.add_argument("--returned", required=True)
    r.add_argument("--ocr", action="store_true")
    r.add_argument("--render-dir", default=None)
    r.add_argument("--emit-batches", type=int, default=0)
    r.add_argument("--batch-dir", default=None)
    mg = sub.add_parser("merge")
    mg.add_argument("--ledger", required=True)
    mg.add_argument("--verdicts", required=True)
    c = sub.add_parser("compile")
    c.add_argument("--ledger", required=True)
    c.add_argument("--out-dir", required=True)
    c.add_argument("--date", default=None)
    c.add_argument("--separator", action="store_true")
    c.add_argument("--place-partial", action="store_true")
    c.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview: run matching and placement, write compile-plan.json only; "
        "no PDFs, no spare files, no ledger change.",
    )
    ch = sub.add_parser("chase")
    ch.add_argument("--ledger", required=True)
    ch.add_argument("--out-dir", required=True)
    ck = sub.add_parser("checklist")
    ck.add_argument("--ledger", required=True)
    ck.add_argument("--out", required=True)
    st = sub.add_parser("status")
    st.add_argument("--ledger", required=True)
    st.add_argument(
        "--since",
        nargs="?",
        const="",
        default=None,
        help="What moved since the last checkpoint, or since a batch folder name, "
        "a checkpoint label, or a YYYY-MM-DD date. Reads only.",
    )
    for parser in sub.choices.values():
        parser.add_argument(
            "--workspace",
            default=None,
            help="The matter folder every output must stay inside. Default: the "
            "ledger's folder, or the current directory for commands without one.",
        )
        parser.add_argument(
            "--allow-outside",
            action="store_true",
            help="Let this run write outside the matter folder (the ledger's folder, "
            "or the current directory for commands without a ledger).",
        )
    a = ap.parse_args(argv)
    contain_writes(a)
    {
        "draft": cmd_draft,
        "convert": cmd_convert,
        "scan": cmd_scan,
        "assemble": cmd_assemble,
        "init": cmd_init,
        "build": cmd_build,
        "read": cmd_read,
        "merge": cmd_merge,
        "compile": cmd_compile,
        "chase": cmd_chase,
        "checklist": cmd_checklist,
        "status": cmd_status,
    }[a.cmd](a)


if __name__ == "__main__":
    main()
