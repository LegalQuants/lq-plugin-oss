"""DOM-level checks for lawyer-facing labels and composing filters."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT_DIR = ROOT / "skills/litigation/cite-check/scripts"
DOM_RUNNER = ROOT / "packages/skill-tests/tests/cite-check/js/report_dom.mjs"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common.report_core import (  # noqa: E402
    build_report,
)
from common.report_render import (  # noqa: E402
    render_html,
)


def _citation(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "citation_as_written_in_unit": "Example v. Smith, 1 F.4th 2",
        "matched_citation": "Example v. Smith, 1 F.4th 2",
        "proposition": "The rule applies.",
        "matched_source_id": "A0001",
        "source_excerpt": "The rule applies.",
        "source_locator": "p. 4",
        "citation_kind": "case",
        "source_resolution": "matched_supplied_source",
        "fabrication_indicators": [],
        "accuracy_of_source_characterization": (
            "confirmed_fair_characterization_of_source"
        ),
        "pincite_accuracy": "pincite_confirmed_accurate",
        "accuracy_of_direct_quotation": "NA_no_direct_quotation_for_this_citation",
        "recommended_changes": None,
    }
    value.update(overrides)
    return value


def _manifest(authorities: list[dict[str, Any]], *unit_ids: str) -> dict[str, Any]:
    return {
        "schemaVersion": "cite-check.manifest.v2",
        "runId": "dom-run",
        "target": {
            "path": "input/brief.md",
            "fullDocumentRef": "input/brief.md",
            "displayName": "Synthetic brief",
        },
        "authorities": authorities,
        "units": [
            {
                "unitId": unit_id,
                "kind": "paragraph",
                "path": "input/brief.md",
                "lineStart": index,
                "lineEnd": index,
                "footnoteAnchorUnitId": None,
            }
            for index, unit_id in enumerate(unit_ids, start=1)
        ],
        "limitations": [],
    }


def _collision_authorities() -> list[dict[str, Any]]:
    return [
        {
            "sourceId": "A_STULL",
            "path": "authorities/a-stull.md",
            "filename": "a-stull.md",
            "readability": "readable",
            "contentIdentity": {
                "caseName": "Stull v. Combustion Engineering, Inc.",
                "reporterCitation": "72 Ohio App.3d 553",
            },
        },
        {
            "sourceId": "A_EDDY",
            "path": "authorities/a-eddy.md",
            "filename": "a-eddy.md",
            "readability": "readable",
            "contentIdentity": {
                "caseName": "State v. Eddy",
                "reporterCitation": "2022-Ohio-3965",
            },
        },
    ]


def _run_dom(html: str, tmp_path: Path) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the report DOM check")
    path = tmp_path / "report.html"
    path.write_text(html, encoding="utf-8")
    completed = subprocess.run(
        [node, str(DOM_RUNNER), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    value = json.loads(completed.stdout)
    assert isinstance(value, dict)
    return value


def _fixture_data() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    unmatched = {
        "matched_source_id": None,
        "source_excerpt": None,
        "source_locator": None,
        "source_resolution": "not_supplied_search_unavailable",
        "accuracy_of_source_characterization": (
            "source_not_found_unable_to_characterize"
        ),
        "pincite_accuracy": "NA_no_pincite_for_this_citation",
        "accuracy_of_direct_quotation": "NA_no_direct_quotation_for_this_citation",
    }
    results = [
        {
            "unitId": "P0016",
            "disposition": "citations_found",
            "citations": [
                _citation(
                    citation_as_written_in_unit="State v. Carter, 72 Ohio App.3d 553",
                    matched_citation="State v. Carter, 72 Ohio App.3d 553",
                    **unmatched,
                )
            ],
        },
        {
            "unitId": "P0017",
            "disposition": "citations_found",
            "citations": [
                _citation(
                    citation_as_written_in_unit="State v. Milam, 2022-Ohio-3965",
                    matched_citation="State v. Milam, 2022-Ohio-3965",
                    **unmatched,
                )
            ],
        },
    ]
    return _manifest(_collision_authorities(), "P0016", "P0017"), results


def test_report_dom_has_no_enum_leaks_and_filters_compose(tmp_path: Path) -> None:
    manifest, results = _fixture_data()
    report = build_report(manifest, results)
    report["receipts"] = {
        "capability": {
            "requestedModel": "gpt-5.6-luna",
            "requestedReasoningEffort": "xhigh",
            "observedModel": "unknown",
            "observedReasoningEffort": "unknown",
            "selectedRuntime": "local_cli",
        }
    }
    html = render_html(report)
    observed = _run_dom(html, tmp_path)

    assert observed["leaks"] == []
    assert "Run " in observed["runstrip"]
    assert "Target " in observed["runstrip"]
    assert "Surface" not in observed["runstrip"]
    assert "worker" not in observed["runstrip"].lower()
    assert "unknown" not in observed["runstrip"].lower()
    assert "worker" not in observed["reportRecord"].lower()
    assert "model" not in observed["reportRecord"].lower()
    assert "State v. Carter" in observed["gate"]
    assert "State v. Milam" in observed["gate"]
    assert "Complete" not in observed["gate"]
    assert observed["none"]["empty"] == "No citations match"
    assert observed["milam"]["count"].startswith("1/")
    red_count = int(str(observed["red"]["count"]).split("/", 1)[0])
    case_count = int(str(observed["caseKind"]["count"]).split("/", 1)[0])
    assert red_count >= 2
    assert case_count >= 2


def test_report_dom_omits_unknown_masthead_metadata(tmp_path: Path) -> None:
    manifest, results = _fixture_data()
    observed = _run_dom(render_html(build_report(manifest, results)), tmp_path)

    assert "Surface" not in observed["runstrip"]
    assert "Worker" not in observed["runstrip"]
    assert "unknown" not in observed["runstrip"].lower()
    assert "worker" not in observed["reportRecord"].lower()


def test_report_dom_counts_failed_units_as_not_reviewed(tmp_path: Path) -> None:
    manifest = _manifest(_collision_authorities(), "P0001", "P0002")
    valid = {
        "unitId": "P0001",
        "disposition": "citations_found",
        "citations": [_citation()],
    }
    failed = {
        "unitId": "P0002",
        "disposition": "citations_found",
        "citations": [],
    }

    report = build_report(manifest, [valid, failed])
    observed = _run_dom(render_html(report), tmp_path)

    stages = {stage[0]: stage[1] for stage in observed["lineageStages"]}
    assert stages["Selected passages"] == "2"
    assert stages["Reviewed"] == "1"
    assert stages["Not reviewed"] == "1"
