"""v2.9 delivery contracts; deterministic fixtures, no model adjudication."""

import copy
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

REPO = Path(__file__).resolve().parents[4]
SCRIPTS = REPO / "skills" / "litigation" / "pressuretest" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import render_brief as rb  # noqa: E402
from render_fixtures import SOURCES, base, breaker, internal  # noqa: E402


def chat_fixture(**over):
    d = base(method_version="lq.pressuretest.method.v2.9")
    d["brief"] = {
        key: d["brief"][key] for key in ("position_name", "run_date", "summary")
    }
    d["checkpoint"]["status"] = "confirmed"
    d["sources"] = {
        "C1.md": {"name": "Master Services Agreement", "date": "2024-01-03"},
        "C4.md": {"name": "Acceptance and Waiver Side Letter", "date": None},
    }
    d.update(over)
    return d


def all_findings():
    result = [breaker(), internal()]
    for index, cls in enumerate(("defeated", "weakens_route", "proof_gap", "context")):
        f = copy.deepcopy(base()["findings"][0])
        f.update(id=f"N{index}", title=f"Question {index}", classification=cls)
        f["statement"] = f"The alternative reading numbered {index} was tested."
        f["dispositive_anchor_note"] = f"The express override answers reading {index}."
        result.append(f)
    result.append(breaker("A7", "If accepted, the seventh entitlement fails."))
    return result


class ChatDelivery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ptv29_")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "source files"
        self.root.mkdir()
        for name, content in SOURCES.items():
            (self.root / name).write_text(content, encoding="utf-8")
        self.path = Path(self.tmp.name) / "deliverable.json"

    def write(self, d):
        self.path.write_text(json.dumps(d), encoding="utf-8")

    def cli(self, name, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name), str(self.path), *map(str, args)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )

    def validate(self, d, text=None, output_format="chat"):
        self.write(d)
        args = ["--source-root", self.root]
        if text is not None:
            output = Path(self.tmp.name) / "output.md"
            output.write_text(text, encoding="utf-8")
            args.extend(["--chat" if output_format == "chat" else "--brief", output])
        result = self.cli("validate_deliverable.py", *args)
        self.assertIn(result.returncode, (0, 1, 2), result.stderr)
        return result.returncode, json.loads(result.stdout)

    def assert_fault(self, d, code=None):
        result, report = self.validate(d)
        self.assertEqual(result, 1, report)
        if code:
            self.assertIn(code, [f["code"] for f in report["faults"]], report)
        return report

    def test_compact_contract_passes_without_document_prose_or_key(self):
        d = chat_fixture()
        code, report = self.validate(d)
        self.assertEqual(code, 0, report)
        text = rb.render(d)
        self.assertTrue(text.startswith("## Summary\n"))
        self.assertIn(d["brief"]["summary"], text)
        self.assertLess(text.index("## Summary"), text.index(d["brief"]["summary"]))
        self.assertNotRegex(text, r"(?m)^\|.*\|.*\|.*\|")

    def test_missing_compact_field_is_refused(self):
        for field in chat_fixture()["brief"]:
            with self.subTest(field=field):
                d = chat_fixture()
                del d["brief"][field]
                self.assert_fault(d)
                with self.assertRaises(rb.RenderError):
                    rb.render(d)

    def test_sources_are_an_exact_partition_metadata_map(self):
        for mutation in "missing extra blank url bad_date bad_meta no_date".split():
            with self.subTest(mutation=mutation):
                d = chat_fixture()
                if mutation == "missing":
                    del d["sources"]["C1.md"]
                elif mutation == "extra":
                    d["sources"]["invented.md"] = {"name": "Invented", "date": None}
                elif mutation == "blank":
                    d["sources"]["C1.md"]["name"] = "   "
                elif mutation == "url":
                    d["sources"]["C1.md"]["url"] = "https://example.com"
                elif mutation == "bad_meta":
                    d["sources"]["C1.md"] = ["not", "metadata"]
                elif mutation == "no_date":
                    del d["sources"]["C1.md"]["date"]
                else:
                    d["sources"]["C1.md"]["date"] = 2024
                self.assert_fault(d)

    def test_locator_required_for_route_and_finding_anchors(self):
        for location in ("strongest_route", "finding"):
            for locator in (None, "", "   "):
                with self.subTest(location=location, locator=locator):
                    d = chat_fixture()
                    obj = (
                        d["strongest_route"]
                        if location == "strongest_route"
                        else d["findings"][0]
                    )
                    obj["anchors"][0]["locator"] = locator
                    self.assert_fault(d)

    def test_checkpoint_status_is_required_and_closed(self):
        for status in (None, "", "approved", False):
            with self.subTest(status=status):
                d = chat_fixture()
                d["checkpoint"]["status"] = status
                self.assert_fault(d)
        for status in ("confirmed", "amended", "non_interactive"):
            with self.subTest(status=status):
                d = chat_fixture()
                d["checkpoint"]["status"] = status
                code, report = self.validate(d)
                self.assertEqual(code, 0, report)

    def test_unanswered_never_derives_a_completed_verdict(self):
        for verdict, findings in (
            ("position_holds", base()["findings"]),
            ("pressure_points", [breaker()]),
        ):
            with self.subTest(verdict=verdict):
                d = chat_fixture(verdict=verdict, findings=findings)
                d["checkpoint"]["status"] = "unanswered"
                report = self.assert_fault(d)
                self.assertEqual(report["derived_verdict"], "incomplete")

    def test_all_seven_findings_have_complete_numbered_details_in_both_formats(self):
        d = chat_fixture(verdict="pressure_points", findings=all_findings())
        for output_format in ("chat", "document"):
            with self.subTest(output_format=output_format):
                text = rb.render(d, output_format=output_format)
                for f in d["findings"]:
                    self.assertIn(f["statement"], text)
                    self.assertRegex(text, rf"(?m)^.*\d+[.)].*{re.escape(f['title'])}")
                    for key in (
                        "flip_statement",
                        "defect_statement",
                        "survives",
                        "test_applied",
                        "next_step",
                        "dispositive_anchor_note",
                    ):
                        if key in f:
                            self.assertIn(f[key], text)
                    for anchor in f["anchors"]:
                        self.assertIn(anchor["quote"], text)
                self.assertNotIn("Additional pressure points", text)

    def test_every_quoted_anchor_has_readable_name_and_locator_beside_it(self):
        d = chat_fixture(verdict="pressure_points", findings=all_findings())
        text = rb.render(d)
        for owner in [d["strongest_route"], *d["findings"]]:
            for anchor in owner["anchors"]:
                occurrences = list(re.finditer(re.escape(anchor["quote"]), text))
                self.assertTrue(occurrences)
                for match in occurrences:
                    nearby = text[max(0, match.start() - 200) : match.end() + 200]
                    self.assertIn(d["sources"][anchor["source"]]["name"], nearby)
                    self.assertIn(anchor["locator"], nearby)

    def test_inventory_has_one_source_per_line_with_review_status(self):
        d = chat_fixture()
        text = rb.render(d)
        lines = text.splitlines()
        for metadata in d["sources"].values():
            inventory = [
                line
                for line in lines
                if metadata["name"] in line and "reviewed" in line.lower()
            ]
            self.assertEqual(len(inventory), 1, inventory)
            self.assertLess(
                text.index(d["findings"][0]["statement"]), text.index(inventory[0])
            )
        for line in text.split("## Sources reviewed", 1)[1].splitlines():
            self.assertFalse(
                all(meta["name"] in line for meta in d["sources"].values())
            )

    def test_links_only_come_from_local_source_root(self):
        d = chat_fixture()
        plain = rb.render(d)
        self.assertNotRegex(plain, r"\]\([^)]*\)")
        linked = rb.render(d, source_root=self.root)
        for name in d["sources"]:
            self.assertIn((self.root / name).resolve().as_posix(), unquote(linked))
        self.assertNotIn("https://", linked)
        self.assertNotIn("file://", linked)
        d["sources"]["C1.md"]["name"] = "[MSA](https://example.com)"
        escaped = rb.render(d, source_root=self.root)
        self.assertIn(r"\[MSA\](https://example.com)", escaped)
        self.assertNotRegex(escaped, r"(?<!\\)\]\(https?://")

    def test_inventory_discloses_selected_sources_that_were_not_reviewed(self):
        d = chat_fixture(
            verdict="incomplete", incomplete_reason="One source awaits review."
        )
        for status in ("parked", "excluded", "unreadable"):
            filename = f"{status}.md"
            (self.root / filename).write_text("A selected source.", encoding="utf-8")
            d["coverage"]["selected"].append(filename)
            d["coverage"][status].append(filename)
            d["sources"][filename] = {"name": f"Source marked {status}", "date": None}
        text = rb.render(d, source_root=self.root)
        inventory = text.split("## Sources reviewed", 1)[1]
        for status in ("parked", "excluded", "unreadable"):
            lines = [
                line
                for line in inventory.splitlines()
                if f"Source marked {status}" in line
            ]
            self.assertEqual(len(lines), 1)
            self.assertRegex(lines[0], r"unread|parked|excluded")
        code, report = self.validate(d, text)
        self.assertEqual(code, 0, report)

    def test_document_adds_standalone_context(self):
        d = chat_fixture()
        text = rb.render(d, output_format="document")
        self.assertIn(f"# Pressure test: {d['brief']['position_name']}", text)
        self.assertIn(d["brief"]["run_date"], text)
        self.assertIn("The lawyer confirmed the scope before testing.", text)

    def test_incomplete_output_preserves_adjudicated_work_and_missing_scope(self):
        d = chat_fixture(
            verdict="incomplete",
            incomplete_reason="The second route awaits instructions.",
        )
        d["routes"]["parked"] = ["R2"]
        text = rb.render(d, source_root=self.root)
        self.assertIn("Verdict: this review is incomplete.", text)
        self.assertIn(d["incomplete_reason"], text)
        self.assertIn(d["findings"][0]["statement"], text)
        self.assertIn(d["findings"][0]["dispositive_anchor_note"], text)
        code, report = self.validate(d, text)
        self.assertEqual(code, 0, report)

    def test_cli_defaults_to_chat_stdout_and_binds_both_formats(self):
        d = chat_fixture()
        self.write(d)
        result = self.cli("render_brief.py", "--source-root", self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, rb.render(d, source_root=self.root))
        for output_format in ("chat", "document"):
            output = Path(self.tmp.name) / f"{output_format}.md"
            result = self.cli(
                "render_brief.py",
                "--format",
                output_format,
                "--source-root",
                self.root,
                "--out",
                output,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            text = output.read_text(encoding="utf-8")
            code, report = self.validate(d, text, output_format)
            self.assertEqual(code, 0, report)

    def test_render_binding_rejects_altered_or_omitted_substance(self):
        d = chat_fixture(verdict="pressure_points", findings=all_findings())
        for output_format in ("chat", "document"):
            original = rb.render(d, output_format=output_format, source_root=self.root)
            targets = [
                d["findings"][-1]["flip_statement"],
                d["findings"][0]["anchors"][0]["quote"],
                d["findings"][3]["statement"],
                "## Summary",
                "How to read this review",
            ]
            for target in targets:
                for replacement in ("", "ALTERED"):
                    with self.subTest(
                        format=output_format, target=target, replacement=replacement
                    ):
                        altered = original.replace(target, replacement, 1)
                        self.assertNotEqual(altered, original)
                        code, report = self.validate(d, altered, output_format)
                        self.assertEqual(code, 1, report)

    def test_break_and_causation_gates_survive_delivery_change(self):
        d = chat_fixture(verdict="pressure_points", findings=[breaker()])
        del d["findings"][0]["flip_statement"]
        self.assert_fault(d, "missing_flip_statement")
        d = chat_fixture(verdict="pressure_points", findings=[breaker(), breaker("A3")])
        self.assert_fault(d, "duplicate_flip_statement")
        d = chat_fixture()
        d["positions"][0]["depends_on_other_party_breach"] = True
        self.assert_fault(d, "causation_attack_missing")


if __name__ == "__main__":
    unittest.main()
