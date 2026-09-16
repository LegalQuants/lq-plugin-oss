"""Unit suite for the /pressuretest brief renderer (method v2.8).

The model writes deliverable.json once; render_brief.py emits the exported
document; validate_deliverable.py then binds the two. Run from the repo
root: uv run pytest tests/pressuretest -q
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SCRIPTS = REPO / "skills" / "litigation" / "pressuretest" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import render_brief as rb  # noqa: E402
from render_fixtures import MACHINE, SOURCES, base, breaker, internal  # noqa: E402

BREAKS_LINE = "Verdict: the position does not hold as stated — pressure points found."
INTERNAL_LINE = (
    "but the position as drafted contradicts itself — pressure points found."
)


def run_script(name, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestHoldsBrief(unittest.TestCase):
    def setUp(self):
        self.text = rb.render(base())

    def test_shape_and_verdict_line(self):
        self.assertIn("# Pressure test: Milestone 3 charge", self.text)
        self.assertIn("## What this document is", self.text)
        self.assertIn(
            "Verdict: the position holds on the supplied documents.", self.text
        )
        self.assertIn("| # | Attack tested | Outcome | Answered by |", self.text)
        self.assertIn("## How this review was done", self.text)
        self.assertIn("This review can only test the routes it identified", self.text)

    def test_register_row_uses_plain_words_and_the_document_key(self):
        self.assertIn("| A1 |", self.text)
        self.assertIn("defeated — the documents answer it", self.text)
        self.assertIn("C4 = Acceptance & Waiver Side Letter, 12 Dec 2024", self.text)

    def test_no_machine_vocabulary_or_telemetry(self):
        self.assertIsNone(MACHINE.search(self.text))
        self.assertNotIn("active mode", self.text.lower())

    def test_hand_off_and_review_status(self):
        self.assertIn("run /cite-check on this document", self.text)
        self.assertIn("proposed by the machine", self.text)


class TestPressurePointBrief(unittest.TestCase):
    def test_breaks_line_table_and_detail(self):
        d = base(verdict="pressure_points", findings=[base()["findings"][0], breaker()])
        text = rb.render(d)
        self.assertIn(BREAKS_LINE, text)
        self.assertIn(
            "| # | Finding | Whose case it hits | How serious | Where |", text
        )
        self.assertIn("| A2 |", text)
        self.assertIn("Breaks the position", text)
        self.assertIn("## A2 — The waiver expired before the assessment date", text)
        self.assertIn("If accepted, the charge was not due on 1 April 2025.", text)
        self.assertIn("Next step", text)

    def test_surviving_attacks_are_listed_in_a_broken_position_brief(self):
        d = base(verdict="pressure_points", findings=[base()["findings"][0], breaker()])
        text = rb.render(d)
        self.assertIn("## Other attacks tested", text)
        self.assertIn("**A1**", text)
        self.assertIn("defeated — the documents answer it", text)
        self.assertLess(text.index("## A2 —"), text.index("## Other attacks tested"))

    def test_passages_render_as_separate_quotes(self):
        text = rb.render(base(verdict="pressure_points", findings=[internal()]))
        self.assertIn('(C1 §3.1)\n\n> "during the Waiver Period"', text)

    def test_internal_only_uses_the_contradiction_line(self):
        text = rb.render(base(verdict="pressure_points", findings=[internal()]))
        self.assertIn(INTERNAL_LINE, text)
        self.assertIn("Contradiction as drafted", text)

    def test_breaks_rank_above_contradictions_in_the_detail(self):
        pps = [internal("D1")] + [
            breaker(f"A{i}", f"If accepted, limb {i} fails.") for i in range(2, 5)
        ]
        text = rb.render(base(verdict="pressure_points", findings=pps))
        self.assertLess(text.index("## A2 —"), text.index("## D1 —"))
        self.assertLess(text.index("## A4 —"), text.index("## D1 —"))

    def test_sixth_pressure_point_gets_a_note_not_full_detail(self):
        pps = [breaker(f"A{i}", f"If accepted, limb {i} fails.") for i in range(2, 8)]
        text = rb.render(base(verdict="pressure_points", findings=pps))
        self.assertIn("## A6 —", text)
        self.assertIn("**A7**", text)
        self.assertNotIn("## A7 —", text)


class TestIncompleteBrief(unittest.TestCase):
    def test_lists_what_is_missing_instead_of_a_table(self):
        d = base(verdict="incomplete", incomplete_reason="C4.md was parked.")
        text = rb.render(d)
        self.assertIn("Verdict: this review is incomplete.", text)
        self.assertIn("## What is missing", text)
        self.assertIn("C4.md was parked.", text)
        self.assertNotIn("| # | Attack tested", text)


class TestRefusals(unittest.TestCase):
    def test_missing_brief_prose_is_refused_with_field_names(self):
        d = base()
        del d["brief"]["summary"]
        with self.assertRaises(rb.RenderError) as ctx:
            rb.render(d)
        self.assertIn("brief.summary", str(ctx.exception))

    def test_pressure_point_without_next_step_is_refused(self):
        f = breaker()
        del f["next_step"]
        d = base(verdict="pressure_points", findings=[f])
        with self.assertRaises(rb.RenderError) as ctx:
            rb.render(d)
        self.assertIn("A2", str(ctx.exception))


class TestRoundTrip(unittest.TestCase):
    """render -> validate must pass by construction."""

    def run_both(self, deliverable):
        tmp = Path(tempfile.mkdtemp(prefix="ptv28_"))
        try:
            root = tmp / "input"
            root.mkdir()
            for name, text in SOURCES.items():
                (root / name).write_text(text, encoding="utf-8")
            dpath = tmp / "deliverable.json"
            dpath.write_text(json.dumps(deliverable), encoding="utf-8")
            bpath = tmp / "brief.md"
            r = run_script("render_brief.py", str(dpath), "--out", str(bpath))
            self.assertEqual(r.returncode, 0, r.stderr)
            v = run_script(
                "validate_deliverable.py",
                str(dpath),
                "--source-root",
                str(root),
                "--brief",
                str(bpath),
            )
            return v.returncode, json.loads(v.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_holds_round_trip(self):
        code, out = self.run_both(base())
        self.assertEqual(code, 0, out)

    def test_pressure_points_round_trip(self):
        d = base(verdict="pressure_points", findings=[base()["findings"][0], breaker()])
        code, out = self.run_both(d)
        self.assertEqual(code, 0, out)

    def test_cli_refusal_exits_1_with_json(self):
        tmp = Path(tempfile.mkdtemp(prefix="ptv28r_"))
        try:
            d = base()
            del d["brief"]["meaning"]
            dpath = tmp / "deliverable.json"
            dpath.write_text(json.dumps(d), encoding="utf-8")
            r = run_script("render_brief.py", str(dpath), "--out", str(tmp / "b.md"))
            self.assertEqual(r.returncode, 1)
            self.assertIn("brief.meaning", json.loads(r.stdout)["faults"][0]["detail"])
            self.assertFalse((tmp / "b.md").exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
