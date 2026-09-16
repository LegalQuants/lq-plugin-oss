"""Bounded safety regressions using ordinary unit inputs, not blind evals."""

import json
import subprocess
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_validate_deliverable import (  # noqa: E402
    SOURCES,
    base_deliverable,
    breaker,
    causation_attack,
    run_validator,
)

SCRIPTS = Path(__file__).resolve().parents[4] / "skills/litigation/pressuretest/scripts"
sys.path.insert(0, str(SCRIPTS))
import compute_period as cp  # noqa: E402


class TestOutstandingWork(unittest.TestCase):
    def test_outstanding_work_prevents_holds_but_not_pressure_points(self):
        for section, field in (
            ("routes", "parked"),
            ("routes", "indeterminate"),
            ("tests", "parked"),
        ):
            with self.subTest(section=section, field=field):
                deliverable = base_deliverable()
                deliverable[section][field] = ["Unfinished"]
                code, report = run_validator(deliverable, SOURCES)
                self.assertEqual(code, 1, report)
                self.assertEqual(report["derived_verdict"], "incomplete")
                deliverable["verdict"] = "incomplete"
                deliverable["incomplete_reason"] = "Outstanding work remains."
                code, report = run_validator(deliverable, SOURCES)
                self.assertEqual(code, 0, report)
                deliverable["verdict"] = "pressure_points"
                deliverable["findings"].append(breaker())
                code, report = run_validator(deliverable, SOURCES)
                self.assertEqual(code, 0, report)
                self.assertEqual(report["derived_verdict"], "pressure_points")


class TestCausationOwnership(unittest.TestCase):
    def two_positions(self):
        deliverable = base_deliverable()
        deliverable["positions"][0]["depends_on_other_party_breach"] = True
        deliverable["positions"].append(
            {
                **deliverable["positions"][0],
                "owner": "Other owner",
                "conclusion": "The other position also depends on breach.",
            }
        )
        deliverable["findings"].append(causation_attack())
        return deliverable

    def test_each_breach_dependent_owner_requires_its_own_attack(self):
        deliverable = self.two_positions()
        code, report = run_validator(deliverable, SOURCES)
        self.assertEqual(code, 1, report)
        self.assertIn("causation_attack_missing", str(report["faults"]))
        self.assertIn("Other owner", str(report["faults"]))
        deliverable["findings"].append(
            {**causation_attack(), "id": "A10", "position_owner": "Other owner"}
        )
        code, report = run_validator(deliverable, SOURCES)
        self.assertEqual(code, 0, report)

    def test_unflagged_owner_does_not_need_an_attack(self):
        deliverable = self.two_positions()
        deliverable["positions"][1]["depends_on_other_party_breach"] = False
        code, report = run_validator(deliverable, SOURCES)
        self.assertEqual(code, 0, report)

    def test_unknown_owner_cannot_satisfy_causation(self):
        deliverable = base_deliverable()
        deliverable["positions"][0]["depends_on_other_party_breach"] = True
        deliverable["findings"] = [
            {**causation_attack(), "position_owner": "Not a tested owner"}
        ]
        code, report = run_validator(deliverable, SOURCES)
        self.assertEqual(code, 1, report)
        self.assertIn("unknown_position_owner", str(report["faults"]))
        self.assertIn("causation_attack_missing", str(report["faults"]))

    def test_conflicting_or_unknown_target_cannot_cover_an_owner(self):
        for target in ("Other owner", "Not a tested owner"):
            for pressure_point in (False, True):
                with self.subTest(target=target, pressure_point=pressure_point):
                    deliverable = self.two_positions()
                    finding = breaker() if pressure_point else causation_attack()
                    finding.update(test_family="causation", against_position=target)
                    deliverable["findings"] = [finding]
                    code, report = run_validator(deliverable, SOURCES)
                    self.assertEqual(code, 1, report)
                    self.assertTrue(
                        {"bad_against_position", "position_owner_mismatch"}
                        & {fault["code"] for fault in report["faults"]},
                        report,
                    )
                    self.assertIn("causation_attack_missing", str(report["faults"]))

    def test_matching_explicit_target_passes(self):
        deliverable = base_deliverable()
        deliverable["positions"][0]["depends_on_other_party_breach"] = True
        deliverable["findings"] = [
            {**causation_attack(), "against_position": "Aerolith"}
        ]
        code, report = run_validator(deliverable, SOURCES)
        self.assertEqual(code, 0, report)


class TestExplicitPeriodSemantics(unittest.TestCase):
    def test_before_on_after_for_both_relations_and_directions(self):
        for direction in ("forward", "backward"):
            for convention in ("period", "clear"):
                result = cp.compute(
                    date(2026, 6, 15), 7, direction=direction, convention=convention
                )
                permitted = date.fromisoformat(result["permitted_day"])
                for semantics in ("due-by", "not-before"):
                    for offset in (-1, 0, 1):
                        event = date.fromordinal(permitted.toordinal() + offset)
                        with self.subTest(
                            direction=direction,
                            convention=convention,
                            semantics=semantics,
                            offset=offset,
                        ):
                            check = cp.check_deadline(result, event, semantics)
                            expected = (
                                offset <= 0 if semantics == "due-by" else offset >= 0
                            )
                            self.assertEqual(check["deadline_ok"], expected)
                            self.assertEqual(check["semantics"], semantics)
                            self.assertNotIn("is in time", check["statement"])

    def test_no_implicit_or_unknown_comparison(self):
        result = cp.compute(date(2026, 6, 1), 7)
        for semantics in (None, "guess"):
            with self.assertRaises(ValueError):
                cp.check_deadline(result, date(2026, 6, 9), semantics)

    def test_clock_is_not_certified_and_seconds_are_preserved(self):
        result = cp.compute(date(2026, 6, 1), 7)
        check = cp.check_deadline(result, datetime(2026, 6, 8, 17, 0, 30), "due-by")
        self.assertTrue(check["deadline_ok"])
        self.assertFalse(check["time_checked"])
        self.assertEqual(check["deadline_time"], "17:00:30")
        self.assertIn("date-only", check["statement"])

    def test_bad_calendar_inputs_fail_promptly(self):
        invalid = (
            {"days": True},
            {"start": datetime(2026, 6, 1, 17)},
            {"holidays": [datetime(2026, 6, 2, 17)]},
            {"weekend": ("mondayish",)},
        )
        for override in invalid:
            with self.subTest(override=override), self.assertRaises(ValueError):
                kwargs: dict[str, Any] = {
                    "start": date(2026, 6, 1),
                    "days": 1,
                    **override,
                }
                cp.compute(**kwargs)

    def test_cli_rejects_unsafe_inputs_without_tracebacks(self):
        base = [
            "--start",
            "2026-06-01",
            "--days",
            "7",
            "--unit",
            "business",
            "--convention",
            "period",
        ]
        cases = (
            [*base, "--weekend", "mon,tue,wed,thu,fri,sat,sun"],
            [*base, "--deadline", "2026-06-09"],
            [*base, "--start", "9999-12-31"],
            [*base, "--start", "0001-01-01", "--direction", "backward"],
            [*base, "--deadline", "2026-06-09T17:00Z", "--semantics", "due-by"],
            [*base, "--deadline", "2026-06-09T25:00", "--semantics", "due-by"],
            [*base, "--holidays", "2026-02-30"],
            ["--start", "2026-06-01", "--days", "7"],
        )
        for args in cases:
            with self.subTest(args=args):
                proc = subprocess.run(
                    [sys.executable, str(SCRIPTS / "compute_period.py"), *args],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(proc.returncode, 2, proc.stdout)
                self.assertEqual(proc.stdout, "")
                self.assertNotIn("Traceback", proc.stderr)

    def test_cli_due_by_rejects_late_event(self):
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "compute_period.py"),
                "--start",
                "2026-06-01",
                "--days",
                "7",
                "--unit",
                "calendar",
                "--convention",
                "period",
                "--deadline",
                "2026-06-09",
                "--semantics",
                "due-by",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(json.loads(proc.stdout)["check"]["deadline_ok"])


class TestQuoteCheckBoundary(unittest.TestCase):
    def test_occurrence_does_not_validate_locator_or_entailment(self):
        deliverable = base_deliverable()
        finding = deliverable["findings"][0]
        finding["anchors"][0]["locator"] = "Nonexistent paragraph 999"
        finding["anchors"][0]["quote"] = "notwithstanding\n  clause 2.3 of the MSA"
        finding["statement"] = "An unrelated unsupported assertion."
        code, report = run_validator(deliverable, SOURCES)
        self.assertEqual(code, 0, report)
        self.assertEqual(report["anchor_check_scope"], "normalised_text_occurrence")
        self.assertFalse(report["pinpoints_verified"])
        self.assertFalse(report["entailment_verified"])
