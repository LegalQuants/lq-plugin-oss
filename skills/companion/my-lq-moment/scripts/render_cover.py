#!/usr/bin/env python3
"""Render a "My LQ Moment" cover: two approved sentences set on the template.

Usage:
  render_cover.py --before "SENTENCE" --after "SENTENCE" [--out-dir DIR]
                  [--practice] [--svg-only]

The template is the only foundation. The script writes an SVG that embeds the
template and sets the two sentences over its open upper area, then rasterises
it to PNG with whatever SVG renderer the host has (rsvg-convert, ImageMagick,
Inkscape, macOS Quick Look, or a headless Chromium-family browser). Standard
library only. Output filenames are fixed so nothing private can leak into them.

Prints one JSON object: {"svg": path, "png": path or null, "renderer": name or
null, "attempts": [...], "message": text}. Each attempt records the renderer
tried, its exit status, elapsed seconds and the tail of its stderr, so a
failure explains itself. Exit status 0 when the PNG was written, 3 when only
the SVG could be written, 2 on bad input.
"""

from __future__ import annotations

import argparse
import base64
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = HERE.parent / "assets" / "cover-template.png"
SVG_NAME = "my-lq-moment-cover.svg"
PNG_NAME = "my-lq-moment-cover.png"
PRACTICE_LABEL = "Practice example — fictional training"

SIZE = 1200
LEFT = 95
RIGHT = 1040
TOP = 130
BOTTOM = 800
# Conservative by design: lawyers do not format. Short sentences, fixed large
# type, no shrinking to fit. Anything longer is refused with a word budget.
MAX_SENTENCE_CHARS = 90
MAX_SENTENCE_WORDS = 12
BEFORE_SIZE, AFTER_SIZE = 64, 72
MAX_BEFORE_LINES, MAX_AFTER_LINES = 3, 3
FONT_STACK = "Avenir Next, Helvetica Neue, Segoe UI, Arial, sans-serif"
RENDER_TIMEOUT = 90  # seconds per renderer; a PNG present after a timeout counts

# Approximate advance widths (in em) for a geometric sans, used only to wrap.
# Deliberately generous so lines break early rather than overflow the frame,
# even if the host substitutes a wider fallback font.
_NARROW = set("iljtfrI.,;:'!|1 ")
_WIDE = set("mwMW@%")
_CAPS = set("ABCDEFGHJKLNOPQRSTUVXYZ")


def estimate_width(text: str, size: float, bold: bool) -> float:
    base = 0.64 if bold else 0.60
    total = 0.0
    for ch in text:
        if ch in _NARROW:
            total += 0.34
        elif ch in _WIDE:
            total += 0.98
        elif ch in _CAPS:
            total += 0.75
        else:
            total += base
    return total * size


def wrap(text: str, size: float, bold: bool, max_width: float) -> list[str]:
    """Greedy word wrap on estimated widths. Never splits a word."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and estimate_width(candidate, size, bold) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def layout(before: str, after: str) -> dict:
    """Fixed type sizes; report whether both sentences fit their line budgets."""
    width = RIGHT - LEFT
    before_lh, after_lh = round(BEFORE_SIZE * 1.22), round(AFTER_SIZE * 1.3)
    gap = 44
    before_lines = wrap(before, BEFORE_SIZE, False, width)
    after_lines = wrap(after, AFTER_SIZE, True, width)
    height = len(before_lines) * before_lh + gap + len(after_lines) * after_lh
    fits = (
        len(before_lines) <= MAX_BEFORE_LINES
        and len(after_lines) <= MAX_AFTER_LINES
        and height <= BOTTOM - TOP
    )
    y = TOP + max(0, (BOTTOM - TOP - height) // 2)
    return {
        "before": {
            "lines": before_lines,
            "size": BEFORE_SIZE,
            "line_height": before_lh,
        },
        "after": {"lines": after_lines, "size": AFTER_SIZE, "line_height": after_lh},
        "gap": gap,
        "y": y,
        "fits": fits,
    }


def build_svg(
    before: str, after: str, template_png: bytes, *, practice: bool = False
) -> str:
    plan = layout(before, after)
    data = base64.b64encode(template_png).decode("ascii")
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{SIZE}" height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}">',
        f'<image xlink:href="data:image/png;base64,{data}" x="0" y="0" '
        f'width="{SIZE}" height="{SIZE}"/>',
    ]
    if practice:
        parts.append(
            f'<text x="{LEFT}" y="86" font-family="{FONT_STACK}" '
            'font-weight="700" font-size="28" fill="#ffffff" '
            f'fill-opacity="0.84">{escape(PRACTICE_LABEL)}</text>'
        )
    y = plan["y"]
    b = plan["before"]
    for line in b["lines"]:
        baseline = y + round(b["size"] * 0.95)
        parts.append(
            f'<text x="{LEFT}" y="{baseline}" font-family="{FONT_STACK}" '
            f'font-weight="500" font-size="{b["size"]}" fill="#ffffff" '
            f'fill-opacity="0.72">{escape(line)}</text>'
        )
        y += b["line_height"]
    y += plan["gap"]
    a = plan["after"]
    for line in a["lines"]:
        baseline = y + round(a["size"] * 0.95)
        parts.append(
            f'<text x="{LEFT}" y="{baseline}" font-family="{FONT_STACK}" '
            f'font-weight="700" font-size="{a["size"]}" fill="#ffffff">'
            f"{escape(line)}</text>"
        )
        y += a["line_height"]
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _chromium_candidates() -> list[str]:
    names = [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "msedge",
    ]
    found = [path for name in names if (path := shutil.which(name))]
    if platform.system() == "Darwin":
        for app in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ):
            if Path(app).exists():
                found.append(app)
    return found


def rasterise(svg_path: Path, png_path: Path) -> tuple[str | None, list[dict]]:
    """Try each available renderer in turn.

    Returns the name of the renderer that produced the PNG (or None) and a
    record of every attempt, so the caller can say why rendering failed.
    """
    attempts: list[tuple[str, list[str]]] = []
    if tool := shutil.which("rsvg-convert"):
        attempts.append(
            (
                "rsvg-convert",
                [
                    tool,
                    "-w",
                    str(SIZE),
                    "-h",
                    str(SIZE),
                    "-o",
                    str(png_path),
                    str(svg_path),
                ],
            )
        )
    if tool := shutil.which("magick"):
        attempts.append(
            ("magick", [tool, "-density", "96", str(svg_path), str(png_path)])
        )
    elif tool := shutil.which("convert"):
        attempts.append(
            ("convert", [tool, "-density", "96", str(svg_path), str(png_path)])
        )
    if tool := shutil.which("inkscape"):
        attempts.append(
            (
                "inkscape",
                [
                    tool,
                    str(svg_path),
                    f"--export-filename={png_path}",
                    f"--export-width={SIZE}",
                ],
            )
        )
    if platform.system() == "Darwin" and (tool := shutil.which("qlmanage")):
        attempts.append(
            (
                "qlmanage",
                [
                    tool,
                    "-t",
                    "-s",
                    str(SIZE),
                    "-o",
                    str(png_path.parent),
                    str(svg_path),
                ],
            )
        )
    for browser in _chromium_candidates():
        attempts.append(
            (
                Path(browser).name,
                [
                    browser,
                    "--headless=new",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    f"--window-size={SIZE},{SIZE}",
                    f"--screenshot={png_path}",
                    svg_path.resolve().as_uri(),
                ],
            )
        )

    record: list[dict] = []
    for name, command in attempts:
        png_path.unlink(missing_ok=True)
        ql_output = png_path.parent / f"{svg_path.name}.png"
        if name == "qlmanage":
            ql_output.unlink(missing_ok=True)
        started = time.monotonic()
        status: str | int
        stderr = ""
        try:
            done = subprocess.run(
                command, capture_output=True, text=True, timeout=RENDER_TIMEOUT
            )
            status = done.returncode
            stderr = (done.stderr or done.stdout or "").strip()
        except subprocess.TimeoutExpired as exc:
            status = "timeout"
            raw = exc.stderr or b""
            stderr = (
                raw.decode(errors="replace") if isinstance(raw, bytes) else raw
            ).strip()
        except OSError as exc:
            status = "os-error"
            stderr = str(exc)
        if name == "qlmanage":
            if ql_output.exists():
                ql_output.replace(png_path)
        produced_this_attempt = status == 0 or status == "timeout"
        ok = produced_this_attempt and valid_png(png_path)
        if not ok:
            png_path.unlink(missing_ok=True)
        record.append(
            {
                "renderer": name,
                "status": status,
                "seconds": round(time.monotonic() - started, 1),
                "stderr_tail": stderr[-240:],
                "png_written": ok,
            }
        )
        if ok:
            return name, record
    return None, record


def valid_png(path: Path) -> bool:
    """A renderer succeeds only with a fresh 1200-square PNG."""
    try:
        header = path.read_bytes()[:24]
    except OSError:
        return False
    return (
        len(header) == 24
        and header[:8] == b"\x89PNG\r\n\x1a\n"
        and int.from_bytes(header[16:20], "big") == SIZE
        and int.from_bytes(header[20:24], "big") == SIZE
    )


def validate_sentence(label: str, text: str) -> str:
    cleaned = " ".join(text.split())
    words = len(cleaned.split())
    if not cleaned:
        raise ValueError(f"the {label} sentence is empty")
    if "\n" in text.strip() or cleaned.count(". ") > 1:
        raise ValueError(
            f"the {label} text reads as more than one sentence; "
            "the cover takes exactly two"
        )
    if words > MAX_SENTENCE_WORDS or len(cleaned) > MAX_SENTENCE_CHARS:
        over_words = max(0, words - MAX_SENTENCE_WORDS)
        over_chars = max(0, len(cleaned) - MAX_SENTENCE_CHARS)
        raise ValueError(
            f"the {label} sentence is too long for the cover: cut about "
            f"{max(over_words, -(-over_chars // 6))} word(s) "
            f"(limit {MAX_SENTENCE_WORDS} words, {MAX_SENTENCE_CHARS} characters)"
        )
    return cleaned


def check_fit(before: str, after: str) -> None:
    plan = layout(before, after)
    if plan["fits"]:
        return
    b, a = len(plan["before"]["lines"]), len(plan["after"]["lines"])
    if b > MAX_BEFORE_LINES:
        raise ValueError(
            f"the before sentence wraps to {b} lines; the cover allows "
            f"{MAX_BEFORE_LINES}. Cut a few words"
        )
    raise ValueError(
        f"the after sentence wraps to {a} lines; the cover allows "
        f"{MAX_AFTER_LINES}. Cut a few words"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--before", required=True, help="first sentence: the before")
    parser.add_argument(
        "--after", required=True, help="second sentence: the after and the added value"
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("outputs"),
        help="directory for the cover files",
    )
    parser.add_argument(
        "--practice",
        action="store_true",
        help="mark a fictional training cover visibly as a practice example",
    )
    parser.add_argument(
        "--svg-only", action="store_true", help="write the SVG and skip rasterising"
    )
    args = parser.parse_args(argv)

    try:
        before = validate_sentence("before", args.before)
        after = validate_sentence("after", args.after)
        check_fit(before, after)
        template_png = DEFAULT_TEMPLATE.read_bytes()
    except (ValueError, OSError) as exc:
        print(
            json.dumps(
                {"svg": None, "png": None, "renderer": None, "message": str(exc)}
            )
        )
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    svg_path = args.out_dir / SVG_NAME
    png_path = args.out_dir / PNG_NAME
    png_path.unlink(missing_ok=True)
    svg_path.write_text(
        build_svg(before, after, template_png, practice=args.practice),
        encoding="utf-8",
    )

    if args.svg_only:
        print(
            json.dumps(
                {
                    "svg": str(svg_path),
                    "png": None,
                    "renderer": None,
                    "message": "SVG written; rasterising skipped",
                }
            )
        )
        return 0

    renderer, attempts = rasterise(svg_path, png_path)
    if renderer is None:
        if attempts:
            tried = ", ".join(f"{a['renderer']} ({a['status']})" for a in attempts)
            message = (
                f"every available renderer failed: {tried}. On a restricted host "
                "spawning Quick Look or a browser is "
                "often blocked; re-run this exact command with the host's "
                "escalated permission before falling back to the SVG"
            )
        else:
            message = (
                "no SVG renderer found on this host (rsvg-convert, ImageMagick, "
                "Inkscape, Quick Look or a Chromium-family browser); the SVG is "
                "written and is the cover"
            )
        print(
            json.dumps(
                {
                    "svg": str(svg_path),
                    "png": None,
                    "renderer": None,
                    "attempts": attempts,
                    "message": message,
                }
            )
        )
        return 3
    print(
        json.dumps(
            {
                "svg": str(svg_path),
                "png": str(png_path),
                "renderer": renderer,
                "attempts": attempts,
                "message": "cover written",
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
