"""Unit suite for the /pressuretest deliverable validator (method v2.8).

Run from the repo root: uv run pytest tests/pressuretest -q
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Tests live in tests/pressuretest/; the shipped script lives in
# skills/litigation/pressuretest/ (same split as the other skills).
REPO = Path(__file__).resolve().parents[4]
SKILL = REPO / "skills" / "litigation" / "pressuretest"
VALIDATOR = SKILL / "scripts" / "validate_deliverable.py"


def run_validator(
    deliverable: dict,
    sources: dict,
    drop_root: bool = False,
    brief: str | None = None,
    extra_files: dict | None = None,
):
    tmp = Path(tempfile.mkdtemp(prefix="ptv22_"))
    try:
        root = tmp / "input"
        root.mkdir()
        for name, text in sources.items():
            (root / name).write_text(text, encoding="utf-8")
        for name, data in (extra_files or {}).items():
            p = tmp / name
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, bytes):
                p.write_bytes(data)
            else:
                p.write_text(data, encoding="utf-8")
        dpath = tmp / "deliverable.json"
        dpath.write_text(json.dumps(deliverable), encoding="utf-8")
        cmd = [sys.executable, str(VALIDATOR), str(dpath)]
        if not drop_root:
            cmd += ["--source-root", str(root)]
        if brief is not None:
            bpath = tmp / "output.md"
            bpath.write_text(brief, encoding="utf-8")
            cmd += ["--brief", str(bpath)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        try:
            payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
        except json.JSONDecodeError:
            payload = {"_raw": proc.stdout, "_err": proc.stderr}
        return proc.returncode, payload
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


SOURCES = {
    "C1.md": "## Clause 3.1\nCharges become due when the payment condition is satisfied.\n",  # noqa: E501
    "C4.md": "## Clause 2.1\nThe Acceptance condition is treated as satisfied for payment purposes\nduring the Waiver Period, notwithstanding clause 2.3 of the MSA.\n",  # noqa: E501
}


def base_deliverable(**over):
    d = {
        "method_version": "lq.pressuretest.method.v2.8",
        "verdict": "position_holds",
        "positions": [
            {
                "owner": "Aerolith",
                "conclusion": "The Milestone 3 charge was due at close on 1 April 2025.",  # noqa: E501
                "basis": "instructed",
                "depends_on_other_party_breach": False,
            }
        ],
        "mode": "fast",
        "brief": {
            "position_name": "milestone charge",
            "run_date": "2026-09-03",
            "what_this_is": "A pressure test of the instructed position.",
            "meaning": "Every attack was answered.",
            "summary": "Two documents, one attack, answered.",
            "document_key": {"C1": "MSA", "C4": "Side letter"},
            "scope_confirmation": "The scope was confirmed with the lawyer before testing.",  # noqa: E501
            "established": "The side letter deems satisfaction.",
            "follows": "The charge fell due.",
        },
        "strongest_route": {
            "summary": "C1 3.1 due-on-satisfaction; C4 2.1 deems satisfaction in-period.",  # noqa: E501
            "anchors": [
                {
                    "source": "C1.md",
                    "quote": "Charges become due when the payment condition is satisfied.",  # noqa: E501
                },
                {
                    "source": "C4.md",
                    "quote": "treated as satisfied for payment purposes",
                },
            ],
        },
        "coverage": {
            "selected": ["C1.md", "C4.md"],
            "reviewed": ["C1.md", "C4.md"],
            "parked": [],
            "excluded": [],
            "unreadable": [],
        },
        "checkpoint": {
            "map_read": ["C1.md", "C4.md"],
            "map_changed_after_full_read": False,
        },  # noqa: E501
        "routes": {"tested": ["R1"], "parked": [], "indeterminate": []},
        "tests": {"applied": ["precedence", "temporal-scope"], "parked": []},
        "findings": [
            {
                "id": "A1",
                "title": "Ordinary precedence demotes the side letter",
                "classification": "defeated",
                "position_owner": "Aerolith",
                "statement": "Ordinary precedence would demote the side letter.",
                "anchors": [
                    {
                        "source": "C4.md",
                        "quote": "notwithstanding clause 2.3 of the MSA",
                    }
                ],
                "dispositive_anchor_note": "Express override in C4 2.1.",
            }
        ],
    }
    d.update(over)
    return d


def breaker():
    return {
        "id": "A2",
        "title": "The waiver expired before the assessment date",
        "classification": "breaks_position",
        "position_owner": "Aerolith",
        "against_position": "Aerolith",
        "hits": "Aerolith, entitlement limb",
        "statement": "The waiver expired before the assessment date.",
        "anchors": [{"source": "C4.md", "quote": "during the Waiver Period"}],
        "flip_statement": "If accepted, the charge was not due on 1 April 2025.",
        "survives": "The quantum and the delivery account survive.",
        "test_applied": "Temporal scope.",
        "next_step": "Take instructions on the expiry date.",
    }


HOLDS_VERDICT_LINE = "Verdict: the position holds on the supplied documents."
PP_BREAKS_VERDICT_LINE = (
    "Verdict: the position does not hold as stated — pressure points found."
)
PP_INTERNAL_VERDICT_LINE = (
    "Verdict: the conclusion survives on the supplied documents, but the "
    "position as drafted contradicts itself — pressure points found."
)

HOLDS_TABLE = (
    "| # | Attack tested | Outcome | Answered by |\n"
    "|---|---|---|---|\n"
    "| A1 | Ordinary precedence demotes the side letter "
    "| Answered by an express override | C4 2.1 |\n"
)


def pp_table(ids, severity="Breaks the position"):
    rows = "".join(
        f"| {i} | The waiver expired before the assessment date "
        f"| Aerolith | {severity} | C4 |\n"
        for i in ids
    )
    return (
        "| # | Finding | Whose case it hits | How serious | Where |\n"
        "|---|---|---|---|---|\n" + rows
    )


CLOSING_SENTENCE = (
    "This review can only test the routes it identified — anything it did "
    "not identify remains untested. It does not verify cited authorities "
    "or certify the position."
)


def brief_doc(verdict_line, table, body=""):
    """A minimal brief that satisfies the v2.8 document-shape checks."""
    return (
        "# Pressure test: milestone charge\n\n"
        "## What this document is\n\n"
        "A pressure test of the instructed position against the selected "
        "sources, produced for lawyer review.\n\n"
        "## The answer\n\n"
        f"{verdict_line}\n\n"
        f"{table}\n"
        f"{body}"
        "\n## How this review was done\n\n"
        "| Documents reviewed | 2 |\n|---|---|\n\n"
        "The scope was confirmed with the lawyer before testing.\n\n"
        f"{CLOSING_SENTENCE}\n"
    )


def holds_brief(body=""):
    return brief_doc(HOLDS_VERDICT_LINE, HOLDS_TABLE, body)


class TestVerdictDerivation(unittest.TestCase):
    def test_clean_position_holds_passes(self):
        code, out = run_validator(base_deliverable(), SOURCES)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["derived_verdict"], "position_holds")

    def test_breaks_position_forces_pressure_points(self):
        d = base_deliverable()
        d["findings"].append(breaker())
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 1)
        self.assertIn("verdict_mismatch", [f["code"] for f in out["faults"]])
        d["verdict"] = "pressure_points"
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 0, out)

    def test_parked_docs_force_incomplete(self):
        d = base_deliverable()
        d["coverage"]["reviewed"] = ["C1.md"]
        d["coverage"]["parked"] = ["C4.md"]
        d["findings"][0]["anchors"] = [
            {"source": "C1.md", "quote": "Charges become due"}
        ]
        d["strongest_route"]["anchors"] = [d["strongest_route"]["anchors"][0]]
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 1)
        d["verdict"] = "incomplete"
        d["incomplete_reason"] = "C4.md parked."
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 0, out)

    def test_honest_unreadable_does_not_block_position_holds(self):
        d = base_deliverable()
        d["coverage"]["selected"] = ["C1.md", "C4.md", "scan.pdf"]
        d["coverage"]["unreadable"] = ["scan.pdf"]
        code, out = run_validator(
            d, SOURCES, extra_files={"input/scan.pdf": b"%PDF-1.4 \xff\xfe garbage"}
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(out["derived_verdict"], "position_holds")

    def test_empty_register_cannot_hold(self):
        d = base_deliverable()
        d["findings"] = []
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 1)
        self.assertIn("verdict_mismatch", [f["code"] for f in out["faults"]])


class TestContractChecks(unittest.TestCase):
    def test_breaks_position_requires_flip_survives_and_target(self):
        d = base_deliverable(verdict="pressure_points")
        f = breaker()
        del f["flip_statement"]
        del f["survives"]
        del f["against_position"]
        d["findings"] = [f]
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 1)
        codes = [x["code"] for x in out["faults"]]
        for expected in (
            "missing_flip_statement",
            "missing_survives",
            "bad_against_position",
        ):
            self.assertIn(expected, codes)

    def test_against_position_must_name_tested_position(self):
        d = base_deliverable(verdict="pressure_points")
        f = breaker()
        f["against_position"] = "Beacon"
        d["findings"] = [f]
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 1)
        self.assertIn("bad_against_position", [x["code"] for x in out["faults"]])

    def test_defeated_requires_dispositive_note(self):
        d = base_deliverable()
        del d["findings"][0]["dispositive_anchor_note"]
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 1)
        self.assertIn(
            "missing_dispositive_anchor_note", [x["code"] for x in out["faults"]]
        )

    def test_anchor_quote_must_exist_verbatim(self):
        d = base_deliverable()
        d["findings"][0]["anchors"][0]["quote"] = "this text is nowhere in the file"
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 1)
        self.assertIn("anchor_not_found", [x["code"] for x in out["faults"]])

    def test_anchor_source_escape_rejected(self):
        d = base_deliverable()
        d["coverage"]["selected"].append("../evil.md")
        d["coverage"]["reviewed"].append("../evil.md")
        d["findings"][0]["anchors"][0] = {
            "source": "../evil.md",
            "quote": "planted corroboration",
        }
        code, out = run_validator(
            d, SOURCES, extra_files={"evil.md": "planted corroboration here"}
        )
        self.assertEqual(code, 1)
        codes = [x["code"] for x in out["faults"]]
        self.assertTrue(
            "anchor_source_escapes_root" in codes or "selected_escapes_root" in codes,
            out,
        )

    def test_selected_files_must_exist(self):
        d = base_deliverable()
        d["coverage"]["selected"].append("ghost.md")
        d["coverage"]["reviewed"].append("ghost.md")
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 1)
        self.assertIn("selected_not_found", [x["code"] for x in out["faults"]])

    def test_impact_vocabulary_banned_in_any_prose_field(self):
        d = base_deliverable()
        d["findings"][0]["commentary"] = "Frankly this is fatal and dispositive."
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 1)
        self.assertIn("impact_vocabulary", [x["code"] for x in out["faults"]])

    def test_quoted_defined_terms_pass(self):
        d = base_deliverable()
        d["findings"][0]["statement"] = (
            'The clause 7 "material defect" carve-out does not bite.'
        )
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 0, out)

    def test_docx_anchor_verification(self):
        import io
        import zipfile as zf

        buf = io.BytesIO()
        xml = (
            '<?xml version="1.0"?><w:document><w:body><w:p><w:r><w:t>'
            "The special condition is satisfied on delivery."
            "</w:t></w:r></w:p></w:body></w:document>"
        )
        with zf.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", xml)
        d = base_deliverable()
        d["coverage"]["selected"].append("side.docx")
        d["coverage"]["reviewed"].append("side.docx")
        d["findings"][0]["anchors"].append(
            {
                "source": "side.docx",
                "quote": "special condition is satisfied on delivery",
            }
        )
        code, out = run_validator(
            d, SOURCES, extra_files={"input/side.docx": buf.getvalue()}
        )
        self.assertEqual(code, 0, out)


class TestBriefBinding(unittest.TestCase):
    def test_brief_verdict_line_required(self):
        code, out = run_validator(
            base_deliverable(), SOURCES, brief="# Resilience Brief\n\nAll good.\n"
        )
        self.assertEqual(code, 1)
        self.assertIn("brief_verdict_line", [x["code"] for x in out["faults"]])

    def test_brief_binding_passes_when_consistent(self):
        code, out = run_validator(
            base_deliverable(),
            SOURCES,
            brief=holds_brief("The route holds.\n"),
        )
        self.assertEqual(code, 0, out)

    def test_brief_missing_intro_section_faults(self):
        brief = holds_brief().replace("## What this document is", "## Preamble")
        code, out = run_validator(base_deliverable(), SOURCES, brief=brief)
        self.assertEqual(code, 1)
        self.assertIn("brief_missing_intro_section", [x["code"] for x in out["faults"]])

    def test_brief_missing_receipt_section_faults(self):
        brief = holds_brief().replace("## How this review was done", "## Wrap-up")
        code, out = run_validator(base_deliverable(), SOURCES, brief=brief)
        self.assertEqual(code, 1)
        self.assertIn(
            "brief_missing_receipt_section", [x["code"] for x in out["faults"]]
        )

    def test_brief_missing_closing_sentence_faults(self):
        brief = holds_brief().replace(CLOSING_SENTENCE, "")
        code, out = run_validator(base_deliverable(), SOURCES, brief=brief)
        self.assertEqual(code, 1)
        self.assertIn(
            "brief_missing_closing_sentence", [x["code"] for x in out["faults"]]
        )

    def test_brief_process_telemetry_faults(self):
        for leak in (
            "The interactive checkpoint was answered 'go'.",
            "Active mode | Fast",
            "Routes the map failed to identify are not counted.",
        ):
            brief = holds_brief(leak + "\n")
            code, out = run_validator(base_deliverable(), SOURCES, brief=brief)
            self.assertEqual(code, 1, leak)
            self.assertIn(
                "brief_process_telemetry",
                [x["code"] for x in out["faults"]],
                leak,
            )

    def test_brief_missing_summary_table_faults(self):
        # position_holds brief carrying the pressure-points header instead
        brief = brief_doc(HOLDS_VERDICT_LINE, pp_table(["A1"]))
        code, out = run_validator(base_deliverable(), SOURCES, brief=brief)
        self.assertEqual(code, 1)
        self.assertIn("brief_missing_summary_table", [x["code"] for x in out["faults"]])

    def test_position_holds_brief_bans_impact_vocabulary(self):
        brief = "Verdict: the position holds on the supplied documents.\n\nThere is a fatal defect in the indemnity chain.\n"  # noqa: E501
        code, out = run_validator(base_deliverable(), SOURCES, brief=brief)
        self.assertEqual(code, 1)
        self.assertIn("brief_impact_vocabulary", [x["code"] for x in out["faults"]])

    def test_pressure_points_brief_must_name_ids(self):
        d = base_deliverable(verdict="pressure_points")
        d["findings"] = [breaker()]
        brief = "Verdict: the position does not hold as stated — pressure points found.\n\nOne issue found but not named.\n"  # noqa: E501
        code, out = run_validator(d, SOURCES, brief=brief)
        self.assertEqual(code, 1)
        self.assertIn(
            "brief_missing_pressure_point", [x["code"] for x in out["faults"]]
        )
        brief = brief_doc(
            PP_BREAKS_VERDICT_LINE, pp_table(["A2"]), "## A2 — waiver expiry\n"
        )
        code, out = run_validator(d, SOURCES, brief=brief)
        self.assertEqual(code, 0, out)

    def test_brief_rejects_machine_verdict_token(self):
        code, out = run_validator(
            base_deliverable(),
            SOURCES,
            brief="Verdict: position_holds\n\nThe route holds.\n",
        )
        self.assertEqual(code, 1)
        codes = [x["code"] for x in out["faults"]]
        self.assertIn("brief_verdict_line", codes)
        self.assertIn("brief_machine_tokens", codes)

    def test_brief_rejects_machine_classification_tokens(self):
        brief = (
            "Verdict: the position holds on the supplied documents.\n\n"
            "A1 was adjudicated weakens_route.\n"
        )
        code, out = run_validator(base_deliverable(), SOURCES, brief=brief)
        self.assertEqual(code, 1)
        self.assertIn("brief_machine_tokens", [x["code"] for x in out["faults"]])

    def test_brief_allows_tokens_inside_fenced_blocks(self):
        brief = holds_brief(
            "The structured companion records the verdict as\n"
            '```json\n{"verdict": "position_holds"}\n```\n'
        )
        code, out = run_validator(base_deliverable(), SOURCES, brief=brief)
        self.assertEqual(code, 0, out)

    def test_brief_inline_code_does_not_exempt_tokens(self):
        brief = (
            "Verdict: the position holds on the supplied documents.\n\n"
            "The register keys findings by class (`weakens_route`).\n"
        )
        code, out = run_validator(base_deliverable(), SOURCES, brief=brief)
        self.assertEqual(code, 1)
        self.assertIn("brief_machine_tokens", [x["code"] for x in out["faults"]])

    def test_brief_machine_tokens_case_insensitive(self):
        brief = (
            "Verdict: the position holds on the supplied documents.\n\n"
            "The register recorded one Weakens_Route entry.\n"
        )
        code, out = run_validator(base_deliverable(), SOURCES, brief=brief)
        self.assertEqual(code, 1)
        self.assertIn("brief_machine_tokens", [x["code"] for x in out["faults"]])

    def test_brief_verdict_line_tolerates_markdown_emphasis(self):
        brief = brief_doc(
            "**Verdict: the position holds on the *supplied documents*.**",
            HOLDS_TABLE,
            "The route holds.\n",
        )
        code, out = run_validator(base_deliverable(), SOURCES, brief=brief)
        self.assertEqual(code, 0, out)

    def test_internal_defect_only_run_uses_contradiction_verdict_line(self):
        d = base_deliverable(verdict="pressure_points")
        d["findings"] = [
            {
                "id": "D1",
                "title": "Interval description contradicts the pleaded dates",
                "classification": "internal_defect",
                "position_owner": "Aerolith",
                "against_position": "Aerolith",
                "hits": "Aerolith, as drafted",
                "test_applied": "Date arithmetic.",
                "next_step": "Correct the interval.",
                "statement": "The interval description contradicts the pleaded dates.",  # noqa: E501
                "anchors": [
                    {
                        "source": "C1.md",
                        "quote": "Charges become due when the payment condition is satisfied.",  # noqa: E501
                    },
                    {"source": "C4.md", "quote": "during the Waiver Period"},
                ],
                "defect_statement": "As drafted, the two passages cannot both be accurate.",  # noqa: E501
                "survives": "The operative pleaded dates survive.",
            }
        ]
        good = brief_doc(
            PP_INTERNAL_VERDICT_LINE,
            pp_table(["D1"], severity="Contradiction as drafted"),
            "## D1 — interval description\n",
        )
        code, out = run_validator(d, SOURCES, brief=good)
        self.assertEqual(code, 0, out)
        wrong_line = (
            "Verdict: the position does not hold as stated — pressure points "
            "found.\n\n## D1 — interval description\n"
        )
        code, out = run_validator(d, SOURCES, brief=wrong_line)
        self.assertEqual(code, 1)
        self.assertIn("brief_verdict_line", [x["code"] for x in out["faults"]])


class TestInternalDefect(unittest.TestCase):
    def make(self):
        d = base_deliverable(verdict="pressure_points")
        d["findings"] = [
            {
                "id": "D1",
                "title": "Interval description contradicts the pleaded dates",
                "classification": "internal_defect",
                "position_owner": "Aerolith",
                "against_position": "Aerolith",
                "hits": "Aerolith, as drafted",
                "test_applied": "Date arithmetic.",
                "next_step": "Correct the interval.",
                "statement": "The interval description contradicts the pleaded dates.",
                "anchors": [
                    {
                        "source": "C1.md",
                        "quote": "Charges become due when the payment condition is satisfied.",  # noqa: E501
                    },
                    {"source": "C4.md", "quote": "during the Waiver Period"},
                ],
                "defect_statement": "As drafted, the two passages cannot both be accurate.",  # noqa: E501
                "survives": "The operative pleaded dates survive.",
            }
        ]
        return d

    def test_internal_defect_counts_as_pressure_point(self):
        code, out = run_validator(self.make(), SOURCES)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["derived_verdict"], "pressure_points")

    def test_internal_defect_requires_two_anchors(self):
        d = self.make()
        d["findings"][0]["anchors"] = d["findings"][0]["anchors"][:1]
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 1)
        self.assertIn(
            "internal_defect_needs_two_anchors", [x["code"] for x in out["faults"]]
        )


def causation_attack(classification="defeated"):
    f = {
        "id": "A9",
        "title": "Aerolith withheld the sign-off itself",
        "classification": classification,
        "test_family": "causation",
        "position_owner": "Aerolith",
        "statement": "Aerolith withheld the acceptance sign-off itself.",
        "anchors": [{"source": "C1.md", "quote": "payment condition is satisfied"}],
    }
    if classification == "defeated":
        f["dispositive_anchor_note"] = "Nothing in the bundle shows contribution."
    return f


class TestV27Rules(unittest.TestCase):
    def test_breach_dependency_flag_required(self):
        d = base_deliverable()
        del d["positions"][0]["depends_on_other_party_breach"]
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 1)
        self.assertIn(
            "missing_breach_dependency_flag", [x["code"] for x in out["faults"]]
        )

    def test_breach_dependent_position_needs_causation_attack(self):
        d = base_deliverable()
        d["positions"][0]["depends_on_other_party_breach"] = True
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 1)
        self.assertIn("causation_attack_missing", [x["code"] for x in out["faults"]])

    def test_causation_attack_satisfies_the_gate(self):
        d = base_deliverable()
        d["positions"][0]["depends_on_other_party_breach"] = True
        d["findings"].append(causation_attack())
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["derived_verdict"], "position_holds")

    def test_causation_gate_not_required_when_flag_false(self):
        code, out = run_validator(base_deliverable(), SOURCES)
        self.assertEqual(code, 0, out)

    def test_unknown_test_family_faults(self):
        d = base_deliverable()
        d["findings"][0]["test_family"] = "vibes"
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 1)
        self.assertIn("bad_test_family", [x["code"] for x in out["faults"]])

    def test_duplicate_flip_statements_fault(self):
        d = base_deliverable(verdict="pressure_points")
        first = breaker()
        second = breaker()
        second["id"] = "A3"
        second["statement"] = "The waiver lapsed before the charge date."
        second["flip_statement"] = (
            "  If accepted, the charge was NOT due on 1 April 2025. "
        )
        d["findings"] = [first, second]
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 1)
        self.assertIn("duplicate_flip_statement", [x["code"] for x in out["faults"]])

    def test_distinct_flip_statements_pass(self):
        d = base_deliverable(verdict="pressure_points")
        first = breaker()
        second = breaker()
        second["id"] = "A3"
        second["flip_statement"] = "If accepted, the reliance-loss limb fails."
        d["findings"] = [first, second]
        code, out = run_validator(d, SOURCES)
        self.assertEqual(code, 0, out)


class TestOperationalFaults(unittest.TestCase):
    def test_missing_source_root_is_operational(self):
        code, out = run_validator(base_deliverable(), SOURCES, drop_root=True)
        self.assertEqual(code, 2)

    def test_unverifiable_binary_anchor_is_operational_with_counts(self):
        d = base_deliverable()
        d["coverage"]["selected"].append("scan.pdf")
        d["coverage"]["reviewed"].append("scan.pdf")
        d["findings"][0]["anchors"].append(
            {"source": "scan.pdf", "quote": "something in the pdf"}
        )
        code, out = run_validator(
            d, SOURCES, extra_files={"input/scan.pdf": b"%PDF-1.4 \xff\xfe garbage"}
        )
        self.assertEqual(code, 2)
        self.assertEqual(out["counts"]["anchors_unverified"], 1)
        self.assertGreater(out["counts"]["anchors_verified"], 0)


class TestDocketChecks(unittest.TestCase):
    def run_with_docket(self, docket_text):
        tmp = Path(tempfile.mkdtemp(prefix="ptv24d_"))
        try:
            root = tmp / "input"
            root.mkdir()
            for name, text in SOURCES.items():
                (root / name).write_text(text, encoding="utf-8")
            dpath = tmp / "deliverable.json"
            dpath.write_text(json.dumps(base_deliverable()), encoding="utf-8")
            kpath = tmp / "docket.md"
            kpath.write_text(docket_text, encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    str(dpath),
                    "--source-root",
                    str(root),
                    "--docket",
                    str(kpath),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return proc.returncode, json.loads(proc.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_clean_docket_passes(self):
        code, out = self.run_with_docket(
            "# Untested docket — attack questions, not findings\n"
            "Read so far: C1.md, C4.md\n"
            "- Does the pleaded reliance date precede the assurance? D2 19 v D4 12 — testing.\n"  # noqa: E501
        )
        self.assertEqual(code, 0, out)

    def test_docket_impact_vocabulary_faults(self):
        code, out = self.run_with_docket(
            "Read so far: C1.md\nThis looks like a fatal defect in the chain.\n"
        )
        self.assertEqual(code, 1)
        self.assertIn("docket_impact_vocabulary", [f["code"] for f in out["faults"]])

    def test_docket_verdict_faults(self):
        code, out = self.run_with_docket(
            "Read so far: C1.md\nVerdict: position_holds (probably).\n"
        )
        self.assertEqual(code, 1)
        self.assertIn("docket_contains_verdict", [f["code"] for f in out["faults"]])

    def test_docket_asserted_finding_faults(self):
        code, out = self.run_with_docket(
            "Read so far: C1.md\nA1 is breaks_position against Aerolith.\n"
        )
        self.assertEqual(code, 1)
        self.assertIn("docket_asserts_findings", [f["code"] for f in out["faults"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
