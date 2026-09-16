from __future__ import annotations

import http.server
import importlib.util
import json
import math
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "skills" / "core" / "legaldesign" / "scripts" / "exhibit.py"
SPEC = importlib.util.spec_from_file_location("legaldesign_exhibit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
exhibit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = exhibit
SPEC.loader.exec_module(exhibit)


class ExhibitTests(unittest.TestCase):
    def test_distinct_paths_and_transaction_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            source.write_text("unchanged")
            alias = root / "alias.txt"
            alias.hardlink_to(source)
            with self.assertRaisesRegex(exhibit.ExhibitError, "alias"):
                exhibit._check_paths([alias], [source])
            with self.assertRaisesRegex(exhibit.ExhibitError, "distinct"):
                exhibit._check_paths([alias, alias], [])
            first, second = root / "first.bin", root / "second.json"
            original_open = Path.open

            def fail_second(path: Path, *args: Any, **kwargs: Any) -> Any:
                if path == second:
                    raise OSError("injected paired-write failure")
                return original_open(path, *args, **kwargs)

            with mock.patch.object(Path, "open", fail_second):
                with self.assertRaisesRegex(OSError, "injected"):
                    exhibit._commit_outputs({first: b"first", second: b"second"})
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())
            self.assertEqual(source.read_text(), "unchanged")

    def test_pdf_argument_validation(self) -> None:
        self.assertEqual(
            exhibit.main(
                [
                    "pdf",
                    "--pdf",
                    "source.pdf",
                    "--page",
                    "0",
                    "--start",
                    "first",
                    "--end",
                    "last",
                    "--out",
                    "clip.png",
                ]
            ),
            2,
        )
        with self.assertRaises(exhibit.ExhibitError):
            args = exhibit.parser().parse_args(
                [
                    "pdf",
                    "--pdf",
                    "source.pdf",
                    "--page",
                    "1",
                    "--start",
                    " ",
                    "--end",
                    "last",
                    "--out",
                    "clip.png",
                ]
            )
            exhibit.validate_args(args)

    def test_url_validation(self) -> None:
        self.assertEqual(
            exhibit.validate_url("https://example.test/source"),
            "https://example.test/source",
        )
        for value in (
            "example.test/source",
            "file:///tmp/source.html",
            "javascript:alert(1)",
            "https://user:pass@example.test/source",
            "https://example.test/line\nbreak",
        ):
            with self.subTest(value=value), self.assertRaises(exhibit.ExhibitError):
                exhibit.validate_url(value)

    def test_dependency_failure_messages_name_fallback(self) -> None:
        original_import_module: Any = importlib.import_module

        def missing(name: str, *args: object, **kwargs: object) -> object:
            if name == "fitz" or name.startswith("playwright"):
                raise ImportError(name)
            return original_import_module(name, *args, **kwargs)

        with mock.patch("importlib.import_module", side_effect=missing):
            with self.assertRaisesRegex(exhibit.ExhibitError, "PyMuPDF.*exact excerpt"):
                exhibit._load_fitz()
            with self.assertRaisesRegex(
                exhibit.ExhibitError, "Playwright.*exact excerpt"
            ):
                exhibit._load_playwright()

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF is optional")
    def test_pdf_highlight_and_metadata(self) -> None:
        import fitz

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pdf"
            output = root / "clip.png"
            document = fitz.open()
            page = document.new_page()
            page.insert_text((72, 72), "First words of the passage")
            page.insert_text((72, 92), "Middle printed line")
            page.insert_text((72, 112), "Last words of the passage")
            document.save(source)
            document.close()
            source_hash = exhibit._sha256(source)

            result = exhibit.main(
                [
                    "pdf",
                    "--pdf",
                    str(source),
                    "--page",
                    "1",
                    "--start",
                    "First words",
                    "--end",
                    "Last words",
                    "--out",
                    str(output),
                    "--context",
                    "0",
                ]
            )
            self.assertEqual(result, 0)
            self.assertTrue(output.is_file())
            metadata = json.loads(Path(f"{output}.json").read_text())
            self.assertEqual(metadata["page"], 1)
            self.assertEqual(len(metadata["highlight_rectangles"]), 3)
            self.assertEqual(metadata["tool_version"], exhibit.VERSION)
            self.assertEqual(
                metadata["source_excerpt"],
                "First words of the passage\nMiddle printed line\nLast words",
            )
            self.assertEqual(metadata["input_sha256"], exhibit._sha256(source))
            self.assertEqual(source_hash, exhibit._sha256(source))
            self.assertEqual(metadata["output_sha256"], exhibit._sha256(output))
            self.assertEqual(
                metadata["capture_status"], "generated_from_matched_source"
            )
            stamp = output.stat().st_mtime_ns
            self.assertTrue(exhibit._reuse_pdf(output, metadata["request"]))
            self.assertEqual(stamp, output.stat().st_mtime_ns)
            with self.assertRaisesRegex(exhibit.ExhibitError, "already exists"):
                exhibit._reuse_pdf(
                    output, {**metadata["request"], "start": "different"}
                )

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF is optional")
    def test_pdf_repeated_text_fails_closed(self) -> None:
        import fitz

        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), "Repeated wording")
            page.insert_text((72, 92), "Repeated wording")
            page.insert_text((72, 112), "Last words")
            with self.assertRaisesRegex(exhibit.ExhibitError, "ambiguous"):
                exhibit._line_range(page, fitz, "Repeated wording", "Last words")

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF is optional")
    def test_pdf_selection_order_and_indented_lines(self) -> None:
        import fitz

        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), "First words then Last words")
            with self.assertRaisesRegex(exhibit.ExhibitError, "precedes"):
                exhibit._line_range(page, fitz, "Last words", "First words")
            page.insert_text((110, 92), "Indented continuation")
            page.insert_text((72, 112), "Final words")
            _, start, end, boxes = exhibit._line_range(
                page, fitz, "First words", "Final words"
            )
            self.assertEqual((start, end, len(boxes)), (0, 2, 3))

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF is optional")
    def test_pdf_companion_tight_crop_adapter_and_pair_integrity(self) -> None:
        import fitz

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, png, pdf = root / "source.pdf", root / "clip.png", root / "clip.pdf"
            with fitz.open() as document:
                page = document.new_page()
                page.insert_text(
                    (72, 72), "Context before selected source words context after"
                )
                page.insert_text((72, 92), "Other source context")
                document.save(source)
            original_hash = exhibit._sha256(source)
            command = [
                "pdf",
                "--pdf",
                str(source),
                "--page",
                "1",
                "--start",
                "selected",
                "--end",
                "words",
                "--context",
                "0",
                "--tight",
                "--out",
                str(png),
                "--pdf-out",
                str(pdf),
            ]
            self.assertEqual(exhibit.main(command), 0)
            receipt = exhibit._checked_receipt(png)
            self.assertEqual(receipt["source_excerpt"], "selected source words")
            self.assertTrue(receipt["tight_crop"])
            crop, highlight = receipt["crop_box"], receipt["highlight_rectangles"][0]
            self.assertEqual((crop[0], crop[2]), (highlight[0], highlight[2]))
            self.assertGreaterEqual(crop[1], highlight[1])
            self.assertLessEqual(crop[3], highlight[3])
            self.assertEqual(receipt["companions"][0]["sha256"], exhibit._sha256(pdf))
            with fitz.open(pdf) as companion:
                self.assertEqual(companion.page_count, 1)
                self.assertEqual(companion[0].get_text(), "")
                images = companion[0].get_images(full=True)
                self.assertEqual(len(images), 1)
                self.assertEqual(
                    fitz.Pixmap(companion, images[0][0]).samples,
                    fitz.Pixmap(png.read_bytes()).samples,
                )
            stamps = [path.stat().st_mtime_ns for path in (png, pdf)]
            self.assertEqual(exhibit.main(command), 0)
            self.assertEqual(stamps, [path.stat().st_mtime_ns for path in (png, pdf)])
            attachment = root / "clip.exhibit.json"
            attach = [
                "attach",
                "--png",
                str(png),
                "--locator",
                "Source page 1",
                "--alt",
                "Selected source words, highlighted",
                "--out",
                str(attachment),
            ]
            self.assertEqual(exhibit.main(attach), 0)
            item = json.loads(attachment.read_text())
            self.assertEqual(
                set(item),
                {
                    "data",
                    "sha256",
                    "sourceSha256",
                    "locator",
                    "captureMethod",
                    "capturedAt",
                    "alt",
                },
            )
            self.assertEqual(item["sourceSha256"], original_hash)
            self.assertIn("raster PDF", item["captureMethod"])
            self.assertNotIn(
                "verified", item["captureMethod"].replace("unverified", "")
            )
            self.assertEqual(exhibit.main(attach), 0)
            pdf.write_bytes(pdf.read_bytes() + b"tampered")
            self.assertEqual(exhibit.main(command), 2)
            self.assertEqual(exhibit.main(attach), 2)
            self.assertEqual(exhibit._sha256(source), original_hash)

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF is optional")
    def test_tight_dense_bold_italic_lines_keep_only_selected_glyphs(self) -> None:
        import fitz

        fontname, size = "Times-BoldItalic", 12
        font = fitz.Font(fontname)
        pitch = (font.ascender - font.descender) * size + 0.7
        phrase = "Agile glyphs fly"
        with fitz.open() as document, fitz.open() as isolated:
            page, reference = document.new_page(), isolated.new_page()
            for index, text in enumerate(
                ("gypsy glyphs jugs above", phrase, "Nearby text below")
            ):
                page.insert_text(
                    (72, 72 + pitch * index), text, fontname=fontname, fontsize=size
                )
            reference.insert_text(
                (72, 72 + pitch), phrase, fontname=fontname, fontsize=size
            )
            lines, selected, _, highlights = exhibit._line_range(
                page, fitz, phrase, phrase
            )
            crop = exhibit._tight_crop(page, fitz, lines, selected, highlights[0])
            target = lines[selected][0]
            top = (lines[selected - 1][0].y1 + target.y0) / 2
            bottom = (target.y1 + lines[selected + 1][0].y0) / 2
            self.assertEqual(crop.y0, math.ceil(top * 3) / 3)
            self.assertEqual(crop.y1, math.floor(bottom * 3) / 3)
            self.assertLessEqual(crop.y0, target.y0)
            self.assertGreaterEqual(crop.y1, target.y1)
            self.assertEqual(page.get_textbox(crop), phrase)
            for item in (page, reference):
                item.add_highlight_annot(highlights).update()
            # Same source-painted glyphs and highlight, with no neighboring ink.
            self.assertEqual(
                page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=crop).samples,
                reference.get_pixmap(matrix=fitz.Matrix(3, 3), clip=crop).samples,
            )
            unrelated_column = (
                fitz.Rect(crop.x1 + 10, target.y0 + 0.5, crop.x1 + 80, target.y1),
                "Other column",
            )
            self.assertEqual(
                crop,
                exhibit._tight_crop(
                    page, fitz, [*lines, unrelated_column], selected, highlights[0]
                ),
            )
            overlapping = [(fitz.Rect(rect), text) for rect, text in lines]
            overlapping[selected - 1][0].y1 = target.y0 + 1
            with self.assertRaisesRegex(exhibit.ExhibitError, "cutting its text"):
                exhibit._tight_crop(page, fitz, overlapping, selected, highlights[0])

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF is optional")
    def test_tight_multiline_and_partial_output_fail_closed(self) -> None:
        import fitz

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, png, pdf = root / "source.pdf", root / "clip.png", root / "clip.pdf"
            with fitz.open() as document:
                page = document.new_page()
                page.insert_text((72, 72), "First words")
                page.insert_text((72, 92), "Final words")
                document.save(source)
            command = [
                "pdf",
                "--pdf",
                str(source),
                "--page",
                "1",
                "--start",
                "First",
                "--end",
                "Final",
                "--context",
                "0",
                "--tight",
                "--out",
                str(png),
                "--pdf-out",
                str(pdf),
            ]
            self.assertEqual(exhibit.main(command), 2)
            self.assertFalse(png.exists())
            self.assertFalse(pdf.exists())
            pdf.write_bytes(b"existing unrelated companion")
            self.assertEqual(exhibit.main(command), 2)
            self.assertEqual(pdf.read_bytes(), b"existing unrelated companion")
            self.assertFalse(png.exists())

    @unittest.skipUnless(
        importlib.util.find_spec("playwright")
        and importlib.util.find_spec("fitz")
        and os.environ.get("LEGALDESIGN_CAPTURE_BROWSER"),
        "Offline HTML capture requires an optional browser and PyMuPDF",
    )
    def test_offline_html_pdf_provenance_resources_and_attachment(self) -> None:
        import fitz

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, stylesheet = root / "source.html", root / "local.css"
            stylesheet.write_text("body { font-family: sans-serif; font-size: 16px; }")
            source.write_text(
                '<!doctype html><html><head><link rel="stylesheet" href="local.css">'
                "</head><body><p>Unique printable source phrase.</p>"
                '<script>document.body.textContent = "FORBIDDEN SCRIPT OUTPUT";'
                "</script>"
                '<img src="missing.png"><img src="https://blocked.invalid/image.png">'
                "</body></html>"
            )
            original_hash = exhibit._sha256(source)
            pdf = root / "source.browser.pdf"
            command = [
                "html",
                "--html",
                str(source),
                "--source-url",
                "https://example.test/source",
                "--browser",
                os.environ["LEGALDESIGN_CAPTURE_BROWSER"],
                "--out",
                str(pdf),
            ]
            self.assertEqual(exhibit.main(command), 0)
            receipt = exhibit._checked_receipt(pdf)
            self.assertEqual(
                receipt["capture_status"], "browser_rendered_supplied_html_unverified"
            )
            self.assertFalse(receipt["scripts_enabled"])
            self.assertEqual(receipt["input_sha256"], original_hash)
            self.assertEqual(receipt["output_sha256"], exhibit._sha256(pdf))
            self.assertIn(
                str(stylesheet.resolve()),
                [item["path"] for item in receipt["local_resources"]],
            )
            reasons = [item["reason"] for item in receipt["missing_resources"]]
            self.assertIn("local file missing", reasons)
            self.assertIn("non-local request blocked", reasons)
            with fitz.open(pdf) as document:
                text = "".join(page.get_text() for page in document)
                self.assertIn("Unique printable source phrase.", text)
                self.assertNotIn("FORBIDDEN SCRIPT OUTPUT", text)
            stamp = pdf.stat().st_mtime_ns
            self.assertEqual(exhibit.main(command), 0)
            self.assertEqual(stamp, pdf.stat().st_mtime_ns)
            arrived = root / "missing.png"
            arrived.write_bytes(b"previously missing resource now present")
            self.assertEqual(exhibit.main(command), 2)
            self.assertEqual(stamp, pdf.stat().st_mtime_ns)
            arrived.unlink()
            png = root / "phrase.png"
            self.assertEqual(
                exhibit.main(
                    [
                        "pdf",
                        "--pdf",
                        str(pdf),
                        "--page",
                        "1",
                        "--start",
                        "Unique",
                        "--end",
                        "phrase.",
                        "--context",
                        "0",
                        "--tight",
                        "--out",
                        str(png),
                    ]
                ),
                0,
            )
            clip = exhibit._checked_receipt(png)
            self.assertEqual(clip["origin"], receipt)
            self.assertEqual(
                clip["request"]["origin_receipt_sha256"],
                exhibit._sha256(Path(f"{pdf}.json")),
            )
            attachment = root / "phrase.exhibit.json"
            self.assertEqual(
                exhibit.main(
                    [
                        "attach",
                        "--png",
                        str(png),
                        "--locator",
                        "Printed source / render page 1",
                        "--alt",
                        "Source phrase",
                        "--out",
                        str(attachment),
                    ]
                ),
                0,
            )
            item = json.loads(attachment.read_text())
            self.assertIn("not publisher-original PDF", item["captureMethod"])
            self.assertIn(original_hash, item["captureMethod"])
            self.assertEqual(item["sourceSha256"], exhibit._sha256(pdf))
            stylesheet.write_text("body { font-size: 30px; }")
            self.assertEqual(exhibit.main(command), 2)
            self.assertEqual(stamp, pdf.stat().st_mtime_ns)
            self.assertEqual(exhibit._sha256(source), original_hash)

    @unittest.skipUnless(
        importlib.util.find_spec("playwright")
        and os.environ.get("LEGALDESIGN_CAPTURE_BROWSER"),
        "Web capture uses an optional local browser",
    )
    def test_live_web_capture_and_ambiguity(self) -> None:
        class Source(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                passage = "<p>Unique <strong>source</strong> passage.</p>"
                if self.path == "/repeated":
                    passage += passage
                body = (
                    "<!doctype html><html><title>Source fixture</title>"
                    "<body><main><p>Context before.</p>"
                    f"{passage}<p>Context after.</p></main></body></html>"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Source)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                url = f"http://127.0.0.1:{server.server_port}"
                for name, path, needle, error in (
                    ("unique", "/", "Unique source passage.", None),
                    ("repeated", "/repeated", "Unique source passage.", "ambiguous"),
                    ("absent", "/", "Never present", "not found"),
                ):
                    output = Path(directory) / f"{name}.png"
                    args = exhibit.parser().parse_args(
                        [
                            "web",
                            "--url",
                            url + path,
                            "--contains",
                            needle,
                            "--out",
                            str(output),
                            "--browser",
                            os.environ["LEGALDESIGN_CAPTURE_BROWSER"],
                        ]
                    )
                    if error:
                        with self.assertRaisesRegex(exhibit.ExhibitError, error):
                            exhibit.capture_web(args)
                        self.assertFalse(output.exists())
                        continue
                    exhibit.capture_web(args)
                    metadata = json.loads(Path(f"{output}.json").read_text())
                    self.assertEqual(metadata["source_excerpt"], needle)
                    self.assertEqual(metadata["resolved_url"], url + path)
                    self.assertEqual(metadata["output_sha256"], exhibit._sha256(output))
                    self.assertIsNone(metadata["input_sha256"])
                    self.assertEqual(
                        metadata["capture_status"], "captured_live_web_unverified"
                    )
                    with self.assertRaisesRegex(exhibit.ExhibitError, "already exists"):
                        exhibit.capture_web(args)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
