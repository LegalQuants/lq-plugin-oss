"""Unit suite for the /pressuretest period calculator (method v2.8).

Run from the repo root: uv run pytest tests/pressuretest -q
"""

import json
import subprocess
import sys
import unittest
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SCRIPTS = REPO / "skills" / "litigation" / "pressuretest" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import compute_period as cp  # noqa: E402


class TestCalendarCounting(unittest.TestCase):
    def test_period_ends_on_nth_calendar_day_after_start(self):
        r = cp.compute(date(2026, 6, 1), 7)
        self.assertEqual(r["boundary_day"], "2026-06-08")
        self.assertEqual(r["permitted_day"], "2026-06-08")
        self.assertEqual(r["counted"][0], "2026-06-02")
        self.assertEqual(len(r["counted"]), 7)

    def test_clear_days_exclude_both_boundary_days(self):
        r = cp.compute(date(2026, 6, 1), 7, convention="clear")
        self.assertEqual(r["boundary_day"], "2026-06-08")
        self.assertEqual(r["permitted_day"], "2026-06-09")

    def test_statement_names_the_convention(self):
        r = cp.compute(date(2026, 6, 1), 7, convention="clear")
        self.assertIn("clear", r["statement"])
        self.assertIn("2026-06-09", r["statement"])


class TestBusinessCounting(unittest.TestCase):
    def test_weekend_days_are_not_counted(self):
        r = cp.compute(date(2026, 6, 19), 5, unit="business")  # a Friday
        self.assertEqual(
            r["counted"],
            [
                "2026-06-22",
                "2026-06-23",
                "2026-06-24",
                "2026-06-25",
                "2026-06-26",
            ],
        )
        self.assertEqual(r["boundary_day"], "2026-06-26")

    def test_listed_holidays_are_not_counted(self):
        r = cp.compute(
            date(2026, 8, 28), 2, unit="business", holidays=[date(2026, 8, 31)]
        )
        self.assertEqual(r["counted"], ["2026-09-01", "2026-09-02"])
        self.assertIn("2026-08-31", r["holidays"])

    def test_fifteen_clear_business_days_from_a_friday(self):
        r = cp.compute(date(2026, 6, 19), 15, unit="business", convention="clear")
        self.assertEqual(r["boundary_day"], "2026-07-10")
        self.assertEqual(r["permitted_day"], "2026-07-11")

    def test_custom_weekend(self):
        r = cp.compute(date(2026, 6, 18), 2, unit="business", weekend=("fri", "sat"))
        self.assertEqual(r["counted"], ["2026-06-21", "2026-06-22"])


class TestBackwardCounting(unittest.TestCase):
    def test_notice_before_an_event_counts_backward(self):
        r = cp.compute(date(2026, 7, 20), 14, convention="clear", direction="backward")
        self.assertEqual(r["boundary_day"], "2026-07-06")
        self.assertEqual(r["permitted_day"], "2026-07-05")


class TestDeadlineCheck(unittest.TestCase):
    def test_deadline_on_final_counted_day_fails_the_clear_convention(self):
        r = cp.compute(date(2026, 6, 19), 15, unit="business", convention="clear")
        c = cp.check_deadline(r, datetime(2026, 7, 10, 17, 0), "not-before")
        self.assertFalse(c["deadline_ok"])
        self.assertEqual(c["shortfall_days"], 1)
        self.assertIn("2026-07-11", c["statement"])

    def test_same_deadline_passes_the_period_convention_but_is_intra_day(self):
        r = cp.compute(date(2026, 6, 19), 15, unit="business", convention="period")
        c = cp.check_deadline(r, datetime(2026, 7, 10, 17, 0), "not-before")
        self.assertTrue(c["deadline_ok"])
        self.assertTrue(c["intra_day_on_final_day"])
        self.assertEqual(c["shortfall_days"], 0)

    def test_date_only_deadline_is_not_intra_day(self):
        r = cp.compute(date(2026, 6, 1), 7)
        c = cp.check_deadline(r, date(2026, 6, 8), "due-by")
        self.assertTrue(c["deadline_ok"])
        self.assertFalse(c["intra_day_on_final_day"])

    def test_backward_deadline_after_permitted_day_is_late(self):
        r = cp.compute(date(2026, 7, 20), 14, convention="clear", direction="backward")
        c = cp.check_deadline(r, date(2026, 7, 6), "due-by")
        self.assertFalse(c["deadline_ok"])
        self.assertEqual(c["shortfall_days"], 1)


class TestInputValidation(unittest.TestCase):
    def test_days_must_be_positive(self):
        with self.assertRaises(ValueError):
            cp.compute(date(2026, 6, 1), 0)

    def test_unit_and_convention_are_closed_sets(self):
        with self.assertRaises(ValueError):
            cp.compute(date(2026, 6, 1), 3, unit="lunar")
        with self.assertRaises(ValueError):
            cp.compute(date(2026, 6, 1), 3, convention="vibes")


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "compute_period.py"), *args],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_cli_prints_json_with_the_check(self):
        code, out, _ = self.run_cli(
            "--start",
            "2026-06-19",
            "--days",
            "15",
            "--unit",
            "business",
            "--convention",
            "clear",
            "--holidays",
            "2026-07-03",
            "--deadline",
            "2026-07-10T17:00",
            "--semantics",
            "not-before",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["boundary_day"], "2026-07-13")
        self.assertFalse(payload["check"]["deadline_ok"])

    def test_cli_rejects_a_bad_date_with_exit_2(self):
        code, out, err = self.run_cli(
            "--start",
            "2026-13-01",
            "--days",
            "3",
            "--unit",
            "calendar",
            "--convention",
            "period",
        )
        self.assertEqual(code, 2)
        self.assertEqual(out.strip(), "")
        self.assertIn("start", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
