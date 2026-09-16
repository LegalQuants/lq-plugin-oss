"""Shared v2.8 companion fixtures for the renderer and round-trip tests."""

import re

MACHINE = re.compile(
    r"\b(pressure_points|position_holds|breaks_position|internal_defect"
    r"|weakens_route|proof_gap|machine_proposed)\b"
)
DUE = "Charges become due when the payment condition is satisfied."
SOURCES = {
    "C1.md": f"## Clause 3.1\n{DUE}\n",
    "C4.md": (
        "## Clause 2.1\nThe Acceptance condition is treated as satisfied for "
        "payment purposes\nduring the Waiver Period, notwithstanding clause 2.3 "
        "of the MSA.\n"
    ),
}


def base(**over):
    d = {
        "method_version": "lq.pressuretest.method.v2.8",
        "verdict": "position_holds",
        "mode": "fast",
        "positions": [
            {
                "owner": "Aerolith",
                "conclusion": "The Milestone 3 charge was due on 1 April 2025.",
                "basis": "instructed",
                "depends_on_other_party_breach": False,
            }
        ],
        "brief": {
            "position_name": "Milestone 3 charge",
            "run_date": "2026-09-03",
            "what_this_is": (
                "You asked whether the charge fell due. This document tests that "
                "against two documents. Read the answer first, then the detail."
            ),
            "meaning": "Every attack I ran was answered by the documents.",
            "summary": (
                "The position was tested over two documents with two attacks. "
                "Both were answered. Next step: confirm the waiver dates."
            ),
            "document_key": {
                "C1": "Master Services Agreement, 3 Jan 2024",
                "C4": "Acceptance & Waiver Side Letter, 12 Dec 2024",
            },
            "scope_confirmation": (
                "The scope was confirmed with the lawyer before testing."
            ),
            "established": "The side letter deems the acceptance condition met.",
            "follows": "The charge therefore fell due on 1 April 2025.",
        },
        "strongest_route": {
            "summary": "C1 3.1 due-on-satisfaction; C4 2.1 deems satisfaction.",
            "anchors": [
                {"source": "C1.md", "quote": DUE, "locator": "C1 §3.1"},
                {
                    "source": "C4.md",
                    "quote": "treated as satisfied for payment purposes",
                    "locator": "C4 §2.1",
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
        },
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
                        "locator": "C4 §2.1",
                    }
                ],
                "dispositive_anchor_note": "Express override in C4 2.1.",
            }
        ],
    }
    d.update(over)
    return d


def breaker(fid="A2", flip="If accepted, the charge was not due on 1 April 2025."):
    return {
        "id": fid,
        "title": "The waiver expired before the assessment date",
        "classification": "breaks_position",
        "position_owner": "Aerolith",
        "against_position": "Aerolith",
        "hits": "Aerolith, the entitlement limb",
        "statement": "The waiver expired before the assessment date.",
        "anchors": [
            {
                "source": "C4.md",
                "quote": "during the Waiver Period",
                "locator": "C4 §2.1",
            }
        ],
        "flip_statement": flip,
        "survives": "The quantum and the delivery account survive.",
        "test_applied": "Temporal scope of the deeming provision.",
        "next_step": "Take instructions on the waiver expiry date.",
    }


def internal(fid="D1"):
    return {
        "id": fid,
        "title": "The interval description contradicts the pleaded dates",
        "classification": "internal_defect",
        "position_owner": "Aerolith",
        "against_position": "Aerolith",
        "hits": "Aerolith, as drafted",
        "statement": "The interval description contradicts the pleaded dates.",
        "anchors": [
            {"source": "C1.md", "quote": DUE, "locator": "C1 §3.1"},
            {
                "source": "C4.md",
                "quote": "during the Waiver Period",
                "locator": "C4 §2.1",
            },
        ],
        "defect_statement": "As drafted, the two passages cannot both be accurate.",
        "survives": "The operative pleaded dates survive.",
        "test_applied": "Date arithmetic.",
        "next_step": "Correct the interval before service.",
    }
