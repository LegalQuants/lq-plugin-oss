#!/usr/bin/env python3
"""Capture authentic source excerpts, raster PDF companions, and popup records.

PDF capture requires PyMuPDF. Web capture requires Playwright for Python and a
local Chromium. If capture is unavailable, use the exact excerpt and the link;
disclose that no clip was captured.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import json
import math
import mimetypes
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

VERSION = "1.2.1"
FALLBACK = "use the exact excerpt and the link; disclose that no clip was captured"
PDF_DEPENDENCY = f"PyMuPDF is required for PDF capture; {FALLBACK}."
WEB_DEPENDENCY = (
    "Playwright for Python and a local Chromium are required for web capture; "
    f"{FALLBACK}."
)


class ExhibitError(ValueError):
    """A clean, user-facing capture failure."""


def _load_fitz() -> Any:
    try:
        fitz = importlib.import_module("fitz")
    except ImportError as exc:
        raise ExhibitError(
            "PyMuPDF is required for PDF capture; use the exact excerpt and the "
            "link; disclose that no clip was captured."
        ) from exc
    return fitz


def _load_playwright() -> Any:
    try:
        sync_api = importlib.import_module("playwright.sync_api")
    except ImportError as exc:
        raise ExhibitError(
            "Playwright for Python and a local Chromium are required for web "
            "capture; use the exact excerpt and the link; disclose that no clip "
            "was captured."
        ) from exc
    return sync_api.sync_playwright


def validate_url(value: str) -> str:
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ExhibitError("--url must be an absolute http or https URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ExhibitError("--url must be an absolute http or https URL")
    return value


def _nonempty(value: str, flag: str) -> str:
    if not value or not value.strip():
        raise ExhibitError(f"{flag} must not be empty")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rect_values(rect: Any) -> list[float]:
    return [
        round(float(rect.x0), 3),
        round(float(rect.y0), 3),
        round(float(rect.x1), 3),
        round(float(rect.y1), 3),
    ]


def _metadata_path(output: Path) -> Path:
    return Path(f"{output}.json")


def _output_path(value: str, suffix: str) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink():
        raise ExhibitError("Output must not be a symbolic link")
    path = path.resolve()
    if path.suffix.lower() != suffix:
        raise ExhibitError(f"Output must have a {suffix} extension")
    return path


def _check_paths(outputs: list[Path], inputs: list[Path]) -> None:
    if len(set(outputs)) != len(outputs):
        raise ExhibitError("Output paths must be distinct")
    for index, output in enumerate(outputs):
        if output.is_symlink():
            raise ExhibitError("Output must not be a symbolic link")
        for other in inputs + outputs[:index]:
            if output == other or (
                output.exists() and other.exists() and output.samefile(other)
            ):
                raise ExhibitError("Output must not overwrite or alias an input/output")


def _commit_outputs(payloads: dict[Path, bytes]) -> None:
    """Never replace existing files; roll back only this call's new files."""
    if any(path.exists() or path.is_symlink() for path in payloads):
        raise ExhibitError("Output already exists; use new output paths")
    created: list[Path] = []
    try:
        for path, data in payloads.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                created.append(path)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _commit_capture(
    output: Path,
    data: bytes,
    payload: dict[str, Any],
    companions: dict[Path, bytes] | None = None,
) -> None:
    companions = companions or {}
    payload.update(
        timestamp=datetime.now(UTC).isoformat(),
        tool_version=VERSION,
        output_sha256=hashlib.sha256(data).hexdigest(),
        output_bytes=len(data),
        companions=[
            {
                "path": str(path),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "kind": "same-PNG raster PDF",
            }
            for path, raw in companions.items()
        ],
    )
    _commit_outputs(
        {output: data, **companions, _metadata_path(output): _json_bytes(payload)}
    )


def _checked_receipt(output: Path) -> dict[str, Any]:
    """Check byte integrity, not publisher authenticity or legal support."""
    try:
        receipt = json.loads(_metadata_path(output).read_text(encoding="utf-8"))
        if not isinstance(receipt, dict):
            raise ValueError("invalid receipt")
        if (
            receipt["output_sha256"] != _sha256(output)
            or receipt["output_bytes"] != output.stat().st_size
        ):
            raise ValueError("output changed")
        for companion in receipt.get("companions", []):
            path = Path(companion["path"])
            if (
                _sha256(path) != companion["sha256"]
                or path.stat().st_size != companion["bytes"]
            ):
                raise ValueError("companion changed")
        if receipt.get("input_sha256") and receipt.get("source"):
            source = Path(receipt["source"])
            if _sha256(source) != receipt["input_sha256"]:
                raise ValueError("source changed")
        for resource in receipt.get("local_resources", []):
            path = Path(resource["path"])
            if _sha256(path) != resource["sha256"]:
                raise ValueError("local resource changed")
        for resource in receipt.get("missing_resources", []):
            if resource.get("path") and Path(resource["path"]).exists():
                raise ValueError("a previously missing resource is now present")
        return receipt
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ExhibitError(
            "Capture receipt or source/output bytes do not match"
        ) from exc


def _printed_lines(page: Any, fitz: Any) -> list[tuple[Any, str]]:
    lines: list[tuple[Any, str]] = []
    for block in page.get_text("dict", sort=True).get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            if text.strip():
                lines.append((fitz.Rect(line["bbox"]), text))
    return lines


def _line_range(
    page: Any, fitz: Any, start: str, end: str
) -> tuple[list[tuple[Any, str]], int, int, list[Any]]:
    lines = _printed_lines(page, fitz)
    starts = [index for index, (_, text) in enumerate(lines) if start in text]
    if not starts:
        raise ExhibitError(f"--start not found on page: {start!r}")
    if len(starts) != 1 or lines[starts[0]][1].count(start) != 1:
        raise ExhibitError("--start is ambiguous; use a longer unique passage")
    start_index = starts[0]
    ends = [
        index
        for index, (_, text) in enumerate(lines[start_index:], start_index)
        if end in text
    ]
    if not ends:
        raise ExhibitError(f"--end not found at or after --start: {end!r}")
    if len(ends) != 1 or lines[ends[0]][1].count(end) != 1:
        raise ExhibitError("--end is ambiguous; use a longer unique passage")
    end_index = ends[0]
    if start_index == end_index and lines[start_index][1].index(end) < lines[
        start_index
    ][1].index(start):
        raise ExhibitError("--end precedes --start")

    rects = [fitz.Rect(lines[index][0]) for index in range(start_index, end_index + 1)]
    for rect in rects:
        rect.y0 -= 0.6
        rect.y1 += 0.6

    def matching_rect(text: str, band: Any) -> Any | None:
        for quad in page.search_for(text, quads=True):
            if quad.rect.intersects(band):
                return quad.rect
        return None

    first = matching_rect(start, rects[0])
    last = matching_rect(end, rects[-1])
    if first is not None:
        rects[0].x0 = max(rects[0].x0, first.x0)
    if last is not None:
        rects[-1].x1 = min(rects[-1].x1, last.x1)
    return lines, start_index, end_index, rects


def _reuse_pdf(output: Path, request: dict[str, Any]) -> bool:
    """Reuse only a byte-verified derivative of the same source and selection."""
    if not output.exists() and not _metadata_path(output).exists():
        return False
    try:
        metadata = _checked_receipt(output)
        if (
            metadata.get("request") == request
            and metadata.get("tool_version") == VERSION
            and [item["path"] for item in metadata.get("companions", [])]
            == ([request["pdf_out"]] if request.get("pdf_out") else [])
        ):
            return True
    except (OSError, ValueError):
        pass
    raise ExhibitError(
        "Output already exists but is not the same verified capture; "
        "use a new --out path"
    )


def _tight_crop(
    page: Any,
    fitz: Any,
    lines: list[tuple[Any, str]],
    selected: int,
    highlight: Any,
    scale: int = 3,
) -> Any:
    """Separate adjacent lines without trimming the selected font-metric bounds."""
    crop = fitz.Rect(highlight) & page.rect
    target = lines[selected][0]
    centre = (target.y0 + target.y1) / 2
    for index, (rect, _) in enumerate(lines):
        if index == selected or rect.x1 <= crop.x0 or rect.x0 >= crop.x1:
            continue
        other_centre = (rect.y0 + rect.y1) / 2
        if other_centre < centre:
            crop.y0 = max(crop.y0, (rect.y1 + target.y0) / 2)
        elif other_centre > centre:
            crop.y1 = min(crop.y1, (target.y1 + rect.y0) / 2)
    # PyMuPDF rounds render bounds outward. Snap inward at the render scale so
    # a fractional blank gutter cannot bring the neighboring ink row back in.
    crop.y0 = math.ceil(crop.y0 * scale) / scale
    crop.y1 = math.floor(crop.y1 * scale) / scale
    if crop.is_empty or crop.y0 > target.y0 or crop.y1 < target.y1:
        raise ExhibitError(
            "--tight cannot isolate this line without cutting its text bounds; "
            "use a contextual crop"
        )
    return crop


def capture_pdf(args: argparse.Namespace) -> None:
    fitz = _load_fitz()
    pdf = Path(args.pdf).expanduser().resolve()
    output = _output_path(args.out, ".png")
    companion = _output_path(args.pdf_out, ".pdf") if args.pdf_out else None
    if not pdf.is_file():
        raise ExhibitError(f"PDF file does not exist: {pdf}")
    outputs = [output, _metadata_path(output)] + ([companion] if companion else [])
    _check_paths(outputs, [pdf, _metadata_path(pdf)])
    origin = None
    if _metadata_path(pdf).exists():
        origin = _checked_receipt(pdf)
        if origin.get("capture_status") != "browser_rendered_supplied_html_unverified":
            raise ExhibitError("Input PDF sidecar is not a local-HTML render receipt")
        _check_paths(outputs, [Path(origin["source"])])
    input_digest = _sha256(pdf)
    request = {
        "input_sha256": input_digest,
        "page": args.page,
        "start": args.start,
        "end": args.end,
        "context": args.context,
        "tight": args.tight,
        "pdf_out": str(companion) if companion else None,
        "origin_receipt_sha256": _sha256(_metadata_path(pdf)) if origin else None,
    }
    if _reuse_pdf(output, request):
        return
    if any(path.exists() or path.is_symlink() for path in outputs):
        raise ExhibitError("Output already exists; use new output paths")
    document = fitz.open(pdf)
    try:
        if args.page > document.page_count:
            message = (
                f"page {args.page} out of range "
                f"(document has {document.page_count} pages)"
            )
            raise ExhibitError(message)
        page = document[args.page - 1]
        lines, start_index, end_index, rects = _line_range(
            page, fitz, args.start, args.end
        )
        if args.tight and (
            start_index != end_index
            or not any(
                quad.rect.intersects(rects[0])
                for quad in page.search_for(args.start, quads=True)
            )
            or not any(
                quad.rect.intersects(rects[-1])
                for quad in page.search_for(args.end, quads=True)
            )
        ):
            raise ExhibitError(
                "--tight requires one uniquely matched printed line; "
                "use a contextual crop for multiline text"
            )
        annotation = page.add_highlight_annot(rects)
        annotation.update()

        context_lines = [
            rect
            for rect, _ in lines[
                max(0, start_index - args.context) : end_index + args.context + 1
            ]
        ]
        xs = [value for rect in context_lines for value in (rect.x0, rect.x1)]
        ys = [value for rect in context_lines for value in (rect.y0, rect.y1)]
        crop = fitz.Rect(
            max(page.rect.x0, min(xs) - 12),
            max(page.rect.y0, min(ys) - 8),
            min(page.rect.x1, max(xs) + 12),
            min(page.rect.y1, max(ys) + 8),
        )
        if args.tight:
            crop = _tight_crop(page, fitz, lines, start_index, rects[0])
        pixmap = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=crop, alpha=False)
        png = pixmap.tobytes("png")
        companions = {}
        if companion:
            with fitz.open() as derivative:
                target = derivative.new_page(width=crop.width, height=crop.height)
                target.insert_image(target.rect, stream=png)
                derivative.set_metadata(
                    {
                        "title": "Highlighted source excerpt (raster derivative)",
                        "subject": "Same pixels as the PNG clip; not the original PDF",
                        "creator": f"LegalDesign exhibit {VERSION}",
                    }
                )
                companions[companion] = derivative.tobytes(garbage=4, deflate=True)
        excerpt = [text for _, text in lines[start_index : end_index + 1]]
        excerpt[0] = excerpt[0][excerpt[0].index(args.start) :]
        excerpt[-1] = excerpt[-1][: excerpt[-1].index(args.end) + len(args.end)]
        if _sha256(pdf) != input_digest:
            raise ExhibitError("Input PDF changed during capture")
        _commit_capture(
            output,
            png,
            {
                "source": str(pdf),
                "url": None,
                "page": args.page,
                "crop_box": _rect_values(crop),
                "highlight_rectangles": [_rect_values(rect) for rect in rects],
                "input_sha256": input_digest,
                "input_bytes": pdf.stat().st_size,
                "request": request,
                "source_excerpt": "\n".join(excerpt),
                "coordinate_system": "PDF points, top-left origin",
                "render_box": _rect_values(page.rect),
                "render_scale": 3,
                "tight_crop": args.tight,
                "renderer": f"PyMuPDF {fitz.VersionBind}",
                "capture_status": "generated_from_matched_source",
                "origin": origin,
            },
            companions,
        )
    finally:
        document.close()


def capture_html(args: argparse.Namespace) -> None:
    """Print unchanged local HTML through an offline, script-disabled browser."""
    sync_playwright = _load_playwright()
    source = Path(args.html).expanduser().resolve()
    output = _output_path(args.out, ".pdf")
    if not source.is_file():
        raise ExhibitError(f"HTML file does not exist: {source}")
    _check_paths([output, _metadata_path(output)], [source])
    source_bytes = source.read_bytes()
    digest = hashlib.sha256(source_bytes).hexdigest()
    request = {
        "input_sha256": digest,
        "source_url": args.source_url,
        "paper": args.paper,
        "browser": args.browser,
    }
    if _reuse_pdf(output, request):
        return
    origin = "https://legaldesign-local.invalid"
    main_url = origin + "/" + quote(source.name)
    resources: dict[str, dict[str, Any]] = {}
    missing: list[dict[str, str]] = []
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(
                headless=True, executable_path=args.browser
            )
        except Exception as exc:
            raise ExhibitError(WEB_DEPENDENCY) from exc
        try:
            context = browser.new_context(
                java_script_enabled=False,
                service_workers="block",
                accept_downloads=False,
            )

            def local_only(route: Any) -> None:
                url = route.request.url
                parsed = urlsplit(url)
                if f"{parsed.scheme}://{parsed.netloc}" != origin:
                    missing.append({"url": url, "reason": "non-local request blocked"})
                    route.abort()
                    return
                path = (source.parent / unquote(parsed.path).lstrip("/")).resolve()
                if not path.is_relative_to(source.parent):
                    missing.append({"url": url, "reason": "outside source folder"})
                    route.abort()
                    return
                if route.request.resource_type not in {
                    "document",
                    "image",
                    "stylesheet",
                    "font",
                } or (
                    route.request.resource_type == "document"
                    and (url != main_url or route.request.frame != page.main_frame)
                ):
                    missing.append(
                        {"url": url, "reason": "active or nested content blocked"}
                    )
                    route.abort()
                    return
                if not path.is_file():
                    missing.append(
                        {"url": url, "path": str(path), "reason": "local file missing"}
                    )
                    route.fulfill(status=404, body="")
                    return
                raw = source_bytes if path == source else path.read_bytes()
                resources[str(path)] = {
                    "path": str(path),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                }
                route.fulfill(
                    status=200,
                    body=raw,
                    content_type=mimetypes.guess_type(path.name)[0]
                    or "application/octet-stream",
                )

            context.route("**/*", local_only)
            page = context.new_page()
            page.goto(main_url, wait_until="networkidle", timeout=30000)
            if page.url != main_url:
                raise ExhibitError(
                    "Source HTML attempted to navigate away during rendering"
                )
            page.emulate_media(media="print")
            page.evaluate("() => document.fonts.ready.then(() => true)")
            settings = {
                "format": args.paper,
                "print_background": True,
                "prefer_css_page_size": True,
                "display_header_footer": False,
                "margin": {side: "0" for side in ("top", "bottom", "left", "right")},
            }
            pdf = page.pdf(**settings)
            failed_images = page.evaluate(
                "() => [...document.images].filter(i => !i.complete || "
                "!i.naturalWidth).map(i => i.currentSrc || i.src)"
            )
            missing.extend(
                {"url": url, "reason": "image unavailable or undecodable"}
                for url in failed_images
            )
            for resource in resources.values():
                if _sha256(Path(resource["path"])) != resource["sha256"]:
                    raise ExhibitError("Local source/resource changed during rendering")
            _commit_capture(
                output,
                pdf,
                {
                    "source": str(source),
                    "url": args.source_url,
                    "input_sha256": digest,
                    "input_bytes": len(source_bytes),
                    "request": request,
                    "renderer": f"Chromium {browser.version}",
                    "print_settings": settings,
                    "scripts_enabled": False,
                    "network_policy": (
                        "source-folder resources only; no external requests"
                    ),
                    "local_resources": list(resources.values()),
                    "missing_resources": missing,
                    "capture_status": "browser_rendered_supplied_html_unverified",
                    "description": (
                        "Browser-rendered PDF of supplied HTML, not a "
                        "publisher-original PDF; PDF page indices may differ "
                        "from printed source pages."
                    ),
                },
            )
        finally:
            browser.close()


def attach_exhibit(args: argparse.Namespace) -> None:
    png = Path(args.png).expanduser().resolve()
    output = _output_path(args.out, ".json")
    receipt = _checked_receipt(png)
    inputs = [png, _metadata_path(png)]
    if receipt.get("source"):
        inputs.append(Path(receipt["source"]))
    inputs.extend(Path(item["path"]) for item in receipt.get("companions", []))
    _check_paths([output], inputs)
    raw = png.read_bytes()
    if (
        not raw.startswith(b"\x89PNG\r\n\x1a\n")
        or not raw.endswith(b"IEND\xaeB`\x82")
        or len(raw) > 4 * 1024 * 1024
    ):
        raise ExhibitError("Popup clip must be a PNG under 4 MiB")
    source_digest = receipt.get("input_sha256") or receipt.get("source_dom_sha256")
    if (
        not isinstance(source_digest, str)
        or len(source_digest) != 64
        or any(char not in "0123456789abcdef" for char in source_digest)
    ):
        raise ExhibitError("Capture receipt has no source integrity hash")
    if receipt.get("capture_status") not in {
        "generated_from_matched_source",
        "captured_live_web_unverified",
    }:
        raise ExhibitError("Unsupported image capture status; no verification inferred")
    method = f"{receipt['capture_status']} · {receipt['renderer']}"
    origin = receipt.get("origin")
    if origin:
        parent = _checked_receipt(Path(receipt["source"]))
        if parent != origin:
            raise ExhibitError("Origin render receipt changed since passage capture")
        method += (
            " · Browser-rendered supplied HTML, not publisher-original PDF"
            f" · HTML SHA-256 {origin['input_sha256']}"
            f" · {len(origin.get('missing_resources', []))} "
            "missing/blocked resource records"
        )
    elif receipt.get("source_dom_sha256"):
        method += (
            " · DOM hash records capture integrity only, not authenticated source bytes"
        )
    for item in receipt.get("companions", []):
        method += f" · Same-PNG raster PDF SHA-256 {item['sha256']}"
    record = {
        "data": "data:image/png;base64," + base64.b64encode(raw).decode("ascii"),
        "sha256": receipt["output_sha256"],
        "sourceSha256": source_digest,
        "locator": args.locator,
        "captureMethod": method,
        "capturedAt": receipt["timestamp"],
        "alt": args.alt,
    }
    data = _json_bytes(record)
    if output.exists():
        if output.read_bytes() == data:
            return
        raise ExhibitError("Output already exists but differs; use a new --out path")
    _commit_outputs({output: data})


def capture_web(args: argparse.Namespace) -> None:
    sync_playwright = _load_playwright()
    url = validate_url(args.url)
    output = _output_path(args.out, ".png")
    _check_paths([output, _metadata_path(output)], [])
    if output.exists() or _metadata_path(output).exists():
        raise ExhibitError(
            "Web output already exists; use a new --out path for a fresh capture"
        )
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(
                headless=True, executable_path=args.browser
            )
        except Exception as exc:
            raise ExhibitError(WEB_DEPENDENCY) from exc
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 1800})
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            validate_url(page.url)
            source_dom = page.content()
            box = page.evaluate(
                """needle => {
                  const selector = 'p,li,tr,blockquote,pre,article,section,div';
                  const matches = [...document.querySelectorAll(selector)].filter(el =>
                    el.textContent.includes(needle) && el.getClientRects().length &&
                    !el.closest('script,style,noscript,template,[hidden]'));
                  const smallest = matches.filter(el => !matches.some(other =>
                    other !== el && el.contains(other)));
                  if (smallest.length > 1 || (smallest[0] &&
                    smallest[0].textContent.split(needle).length !== 2))
                    return {ambiguous:true};
                  if (smallest.length) {
                    const target = smallest[0];
                    target.dataset.legaldesignExhibit = 'true';
                    target.style.background = '#fff59b';
                    target.style.outline = '3px solid #c92014';
                    target.style.outlineOffset = '3px';
                    const rect = target.getBoundingClientRect();
                    return {
                      x: rect.x,
                      y: rect.y + window.scrollY,
                      width: rect.width,
                      height: rect.height,
                      excerpt: target.textContent
                    };
                  }
                  return null;
                }""",
                args.contains,
            )
            if box is None:
                raise ExhibitError(
                    f"--contains text not found on page: {args.contains!r}"
                )
            if box.get("ambiguous"):
                raise ExhibitError(
                    "--contains is ambiguous; use a longer unique passage"
                )
            document_height = page.evaluate("document.documentElement.scrollHeight")
            crop = {
                "x": max(0, box["x"] - 24),
                "y": max(0, box["y"] - 48),
                "width": min(1280 - max(0, box["x"] - 24), box["width"] + 48),
                "height": min(
                    document_height - max(0, box["y"] - 48), box["height"] + 96
                ),
            }
            png = page.screenshot(clip=crop, type="png")
            _commit_capture(
                output,
                png,
                {
                    "source": None,
                    "url": url,
                    "page": None,
                    "crop_box": [
                        round(crop["x"], 3),
                        round(crop["y"], 3),
                        round(crop["x"] + crop["width"], 3),
                        round(crop["y"] + crop["height"], 3),
                    ],
                    "highlight_rectangles": [
                        [
                            round(box["x"], 3),
                            round(box["y"], 3),
                            round(box["x"] + box["width"], 3),
                            round(box["y"] + box["height"], 3),
                        ]
                    ],
                    "input_sha256": None,
                    "source_dom_sha256": hashlib.sha256(
                        source_dom.encode()
                    ).hexdigest(),
                    "resolved_url": page.url,
                    "source_excerpt": box["excerpt"],
                    "coordinate_system": "CSS pixels, document top-left origin",
                    "viewport": {"width": 1280, "height": 1800},
                    "renderer": f"Chromium {browser.version}",
                    "capture_status": "captured_live_web_unverified",
                },
            )
        finally:
            browser.close()


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--version", action="version", version=VERSION)
    subcommands = command.add_subparsers(dest="command", required=True)

    pdf = subcommands.add_parser(
        "pdf",
        help="highlight whole printed lines on one PDF page (requires PyMuPDF)",
        description=f"Highlight whole printed lines and crop them. {PDF_DEPENDENCY}",
    )
    pdf.add_argument("--pdf", required=True)
    pdf.add_argument("--page", required=True, type=int)
    pdf.add_argument("--start", required=True, help="first words of the passage")
    pdf.add_argument("--end", required=True, help="last words of the passage")
    pdf.add_argument("--out", required=True)
    pdf.add_argument("--pdf-out", help="optional same-PNG raster PDF companion")
    pdf.add_argument("--context", type=int, default=2, metavar="LINES")
    pdf.add_argument(
        "--tight",
        action="store_true",
        help="crop to the matched phrase on one printed line; requires --context 0",
    )
    pdf.set_defaults(handler=capture_pdf)

    web = subcommands.add_parser(
        "web",
        help="highlight a live page block (requires Playwright and local Chromium)",
        description=(
            f"Render the page with its own CSS and crop the match. {WEB_DEPENDENCY}"
        ),
    )
    web.add_argument("--url", required=True)
    web.add_argument("--contains", required=True, help="text in the block to highlight")
    web.add_argument("--out", required=True)
    web.add_argument("--browser", help="optional path to an installed Chromium browser")
    web.set_defaults(handler=capture_web)

    html = subcommands.add_parser(
        "html", help="print local HTML as a script-disabled, offline browser PDF"
    )
    html.add_argument("--html", required=True)
    html.add_argument(
        "--source-url", help="canonical HTTP(S) source URL; recorded, never fetched"
    )
    html.add_argument(
        "--out", required=True, help="browser-rendered PDF, not publisher-original"
    )
    html.add_argument("--paper", choices=("Letter", "A4"), default="Letter")
    html.add_argument(
        "--browser", help="optional path to an installed Chromium browser"
    )
    html.set_defaults(handler=capture_html)

    attach = subcommands.add_parser(
        "attach",
        help="make a ready-to-attach exhibit JSON from a verified capture receipt",
    )
    attach.add_argument("--png", required=True)
    attach.add_argument("--locator", required=True)
    attach.add_argument("--alt", required=True)
    attach.add_argument("--out", required=True)
    attach.set_defaults(handler=attach_exhibit)
    return command


def validate_args(args: argparse.Namespace) -> None:
    if args.command == "pdf":
        if args.page < 1:
            raise ExhibitError("--page must be at least 1")
        if args.context < 0:
            raise ExhibitError("--context must be at least 0")
        if args.tight and args.context != 0:
            raise ExhibitError("--tight requires --context 0")
        _nonempty(args.start, "--start")
        _nonempty(args.end, "--end")
    elif args.command == "web":
        validate_url(args.url)
        _nonempty(args.contains, "--contains")
    elif args.command == "html":
        if args.source_url is not None:
            validate_url(args.source_url)
    elif args.command == "attach":
        _nonempty(args.locator, "--locator")
        _nonempty(args.alt, "--alt")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        validate_args(args)
        args.handler(args)
    except ExhibitError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: Capture I/O failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
