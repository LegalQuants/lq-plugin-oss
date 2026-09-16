from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

SCHEMA_DIR = (
    Path(__file__).resolve().parents[4] / "skills/litigation/cite-check/schemas"
)
REPO_ROOT = SCHEMA_DIR.parents[3]
AJV_ENTRY = REPO_ROOT / "packages/pluginctl/node_modules/ajv/dist/2020.js"
SUPERSEDED_SCHEMA_NAMES = {
    "cite-check-work-unit-result.schema.json",
    "work-unit-result.schema.json",
    "sol-review.schema.json",
    "report.schema.json",
}


def load_schema(name: str) -> dict[str, Any]:
    value = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def schema_names() -> set[str]:
    return {path.name for path in SCHEMA_DIR.glob("*.schema.json")}


def ajv_validate(cases: list[tuple[str, str, Any]]) -> dict[str, bool]:
    if not AJV_ENTRY.exists():
        pytest.skip(
            "AJV is not installed in this Python-only environment; "
            "CI's Pack job installs JavaScript dependencies and runs this suite"
        )

    payload = [
        {"caseId": case_id, "schema": schema_name, "instance": instance}
        for case_id, schema_name, instance in cases
    ]
    script = r"""
const fs = require("fs");
const path = require("path");
const Ajv2020 = require(
  path.join(process.cwd(), "packages/pluginctl/node_modules/ajv/dist/2020"),
);
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const schemaDir = path.join(process.cwd(), "skills/litigation/cite-check/schemas");
const names = [
  "manifest.schema.json",
  "cite-check-unit-result.schema.json",
  "coverage.schema.json",
];
const ajv = new Ajv2020({ allErrors: true, strict: true });
for (const name of names) {
  ajv.addSchema(JSON.parse(fs.readFileSync(path.join(schemaDir, name), "utf8")));
}
const results = {};
for (const item of payload) {
  const validator = ajv.getSchema(
    `https://legalquants.com/schemas/${item.schema}`,
  );
  if (!validator) throw new Error(`schema not found: ${item.schema}`);
  results[item.caseId] = validator(item.instance);
}
process.stdout.write(JSON.stringify(results));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=REPO_ROOT,
        input=json.dumps(payload),
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert isinstance(result, dict)
    return result


CITATION_KIND_VALUES = (
    "case",
    "statute",
    "rule",
    "regulation",
    "record",
    "other",
)
SOURCE_RESOLUTION_VALUES = (
    "matched_supplied_source",
    "not_supplied_confirmed_exists_elsewhere",
    "not_supplied_not_found_potential_hallucination",
    "not_supplied_search_unavailable",
)
FABRICATION_INDICATOR_VALUES = (
    "reporter_coordinates_belong_to_different_supplied_case",
    "not_found_in_external_search",
    "citation_malformed_or_impossible",
)
REQUIRED_CITATION_FIELDS = {
    "citation_as_written_in_unit",
    "matched_citation",
    "proposition",
    "matched_source_id",
    "source_excerpt",
    "source_locator",
    "citation_kind",
    "source_resolution",
    "fabrication_indicators",
    "accuracy_of_source_characterization",
    "pincite_accuracy",
    "accuracy_of_direct_quotation",
    "recommended_changes",
}
OPTIONAL_CITATION_FIELDS = {
    "colliding_source_id",
    "existence_check_notes",
}


def citation(
    *,
    source_id: str | None = "A0001",
    excerpt: str | None = "The court held that the rule applies.",
    locator: str | None = "p. 4",
    proposition: str | None = None,
    citation_kind: str = "case",
    source_resolution: str | None = None,
    fabrication_indicators: list[str] | None = None,
    colliding_source_id: str | None = None,
    existence_check_notes: str | None = None,
    include_optional: bool = False,
) -> dict[str, Any]:
    if source_resolution is None:
        source_resolution = (
            "matched_supplied_source"
            if source_id is not None
            else "not_supplied_search_unavailable"
        )
    row: dict[str, Any] = {
        "citation_as_written_in_unit": "Smith v. Jones, 1 F.4th 2, 4 (2d Cir. 2020)",
        "matched_citation": "Smith v. Jones, 1 F.4th 2, 4 (2d Cir. 2020)",
        "proposition": proposition,
        "matched_source_id": source_id,
        "source_excerpt": excerpt,
        "source_locator": locator,
        "citation_kind": citation_kind,
        "source_resolution": source_resolution,
        "fabrication_indicators": (
            [] if fabrication_indicators is None else fabrication_indicators
        ),
        "accuracy_of_source_characterization": (
            "confirmed_fair_characterization_of_source"
        ),
        "pincite_accuracy": "pincite_confirmed_accurate",
        "accuracy_of_direct_quotation": "NA_no_direct_quotation_for_this_citation",
        "recommended_changes": None,
    }
    if include_optional:
        row["colliding_source_id"] = colliding_source_id
        row["existence_check_notes"] = existence_check_notes
    return row


def test_only_current_contract_schemas_are_present() -> None:
    assert schema_names() == {
        "manifest.schema.json",
        "cite-check-unit-result.schema.json",
        "coverage.schema.json",
    }
    assert SUPERSEDED_SCHEMA_NAMES.isdisjoint(schema_names())


def test_current_schemas_are_strict_draft_2020_contracts() -> None:
    for name in schema_names():
        schema = load_schema(name)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"].endswith(f"/{name}")
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False


def test_unit_result_is_a_citation_level_contract() -> None:
    schema = load_schema("cite-check-unit-result.schema.json")
    assert set(schema["properties"]) == {"unitId", "disposition", "citations"}
    assert schema["required"] == ["unitId", "disposition", "citations"]
    properties = schema["$defs"]["citation"]["properties"]
    assert set(properties) == REQUIRED_CITATION_FIELDS | OPTIONAL_CITATION_FIELDS
    # Required keys are always emitted. Companion collision/existence notes
    # stay optional so a matched row need not invent nulls.
    assert set(schema["$defs"]["citation"]["required"]) == REQUIRED_CITATION_FIELDS
    assert properties["citation_kind"]["enum"] == list(CITATION_KIND_VALUES)
    assert properties["source_resolution"]["enum"] == list(SOURCE_RESOLUTION_VALUES)
    assert properties["fabrication_indicators"]["type"] == "array"
    assert properties["fabrication_indicators"]["items"]["enum"] == list(
        FABRICATION_INDICATOR_VALUES
    )
    assert properties["colliding_source_id"]["$ref"] == "#/$defs/nullableString"
    assert properties["existence_check_notes"]["$ref"] == "#/$defs/nullableString"
    assert schema["$defs"]["citation"]["properties"]["proposition"]["$ref"] == (
        "#/$defs/nullableString"
    )
    serialized = json.dumps(schema)
    for retired in (
        "targetLocation",
        "exclusionReceipt",
        "authoritySourceIds",
        "findings",
        "assertionType",
        "currentness",
        "ethics",
        "posture",
    ):
        assert retired not in serialized


def test_no_citations_found_is_a_valid_terminal_receipt() -> None:
    result = ajv_validate(
        [
            (
                "no-citations",
                "cite-check-unit-result.schema.json",
                {
                    "unitId": "P0001",
                    "disposition": "no_citations_found",
                    "citations": [],
                },
            )
        ]
    )
    assert result == {"no-citations": True}


def test_mixed_citations_found_unit_is_valid() -> None:
    instance = {
        "unitId": "P0002",
        "disposition": "citations_found",
        "citations": [citation(), citation(source_id=None, excerpt=None, locator=None)],
    }
    result = ajv_validate([("mixed", "cite-check-unit-result.schema.json", instance)])
    assert result == {"mixed": True}


def test_same_written_citation_can_have_two_proposition_rows() -> None:
    first = citation(proposition="The statute supplies the governing standard.")
    second = citation(proposition="The court applied that standard to this claim.")
    assert first["citation_as_written_in_unit"] == second["citation_as_written_in_unit"]
    assert first["proposition"] != second["proposition"]
    result = ajv_validate(
        [
            (
                "two-propositions",
                "cite-check-unit-result.schema.json",
                {
                    "unitId": "P0003",
                    "disposition": "citations_found",
                    "citations": [first, second],
                },
            )
        ]
    )
    assert result == {"two-propositions": True}


def test_citation_row_missing_the_proposition_key_is_rejected() -> None:
    row = citation()
    del row["proposition"]
    result = ajv_validate(
        [
            (
                "missing-proposition",
                "cite-check-unit-result.schema.json",
                {
                    "unitId": "P0005",
                    "disposition": "citations_found",
                    "citations": [row],
                },
            )
        ]
    )
    assert result == {"missing-proposition": False}


def test_source_found_without_excerpt_is_valid_for_citation_level_demotion() -> None:
    row = citation(excerpt=None, locator=None)
    result = ajv_validate(
        [
            (
                "missing-evidence",
                "cite-check-unit-result.schema.json",
                {
                    "unitId": "P0004",
                    "disposition": "citations_found",
                    "citations": [row],
                },
            )
        ]
    )
    assert result == {"missing-evidence": True}
    assert (
        "validation_flags"
        not in load_schema("cite-check-unit-result.schema.json")["$defs"]["citation"][
            "properties"
        ]
    )


def test_citation_row_missing_new_required_keys_is_rejected() -> None:
    cases: list[tuple[str, str]] = [
        ("missing-kind", "citation_kind"),
        ("missing-resolution", "source_resolution"),
        ("missing-indicators", "fabrication_indicators"),
    ]
    payload: list[tuple[str, str, Any]] = []
    for case_id, field in cases:
        row = citation()
        del row[field]
        payload.append(
            (
                case_id,
                "cite-check-unit-result.schema.json",
                {
                    "unitId": "P0006",
                    "disposition": "citations_found",
                    "citations": [row],
                },
            )
        )
    result = ajv_validate(payload)
    assert result == {case_id: False for case_id, _field in cases}


def test_unmatched_case_with_empty_indicators_and_optional_notes_is_valid() -> None:
    row = citation(
        source_id=None,
        excerpt=None,
        locator=None,
        source_resolution="not_supplied_not_found_potential_hallucination",
        fabrication_indicators=["not_found_in_external_search"],
        colliding_source_id=None,
        existence_check_notes="CourtListener and web search returned no match.",
        include_optional=True,
    )
    row["accuracy_of_source_characterization"] = (
        "source_not_found_unable_to_characterize"
    )
    row["pincite_accuracy"] = "source_not_found_unable_to_check_pincite"
    row["accuracy_of_direct_quotation"] = "source_not_found_unable_to_check_quotation"
    result = ajv_validate(
        [
            (
                "potential-hallucination",
                "cite-check-unit-result.schema.json",
                {
                    "unitId": "P0007",
                    "disposition": "citations_found",
                    "citations": [row],
                },
            )
        ]
    )
    assert result == {"potential-hallucination": True}


def test_duplicate_fabrication_indicators_are_rejected() -> None:
    row = citation(
        source_id=None,
        excerpt=None,
        locator=None,
        source_resolution="not_supplied_not_found_potential_hallucination",
        fabrication_indicators=[
            "not_found_in_external_search",
            "not_found_in_external_search",
        ],
    )
    result = ajv_validate(
        [
            (
                "duplicate-indicators",
                "cite-check-unit-result.schema.json",
                {
                    "unitId": "P0008",
                    "disposition": "citations_found",
                    "citations": [row],
                },
            )
        ]
    )
    assert result == {"duplicate-indicators": False}


def test_worker_prompt_example_validates_against_the_unit_result_schema() -> None:
    prompt = (
        Path(__file__).resolve().parents[4]
        / "skills/litigation/cite-check/references/unit-review-prompt.md"
    ).read_text(encoding="utf-8")
    match = re.search(r"```json\n(\{.*?\n\})\n```", prompt, flags=re.S)
    assert match is not None
    example = json.loads(match.group(1))
    result = ajv_validate(
        [("prompt-example", "cite-check-unit-result.schema.json", example)]
    )
    assert result == {"prompt-example": True}


def test_manifest_is_a_slim_parent_owned_preparation_inventory() -> None:
    schema = load_schema("manifest.schema.json")
    assert set(schema["properties"]) == {
        "schemaVersion",
        "runId",
        "target",
        "authorities",
        "units",
        "limitations",
    }
    unit = schema["$defs"]["unit"]
    assert set(unit["properties"]) == {
        "unitId",
        "kind",
        "path",
        "lineStart",
        "lineEnd",
        "footnoteAnchorUnitId",
    }
    serialized = json.dumps(schema)
    for retired in (
        "expectedUnitIds",
        "selection",
        "exclusionReceipt",
        "authoritySourceIds",
    ):
        assert retired not in serialized


def test_manifest_rejects_unsafe_paths_and_accepts_footnote_anchor() -> None:
    schema = load_schema("manifest.schema.json")
    path_pattern = schema["$defs"]["relativePath"]["pattern"]
    path_re = re.compile(path_pattern)
    for path in ("/tmp/brief.md", "../brief.md", "a/../../brief.md", "C:/brief.md"):
        assert path_re.search(path) is None
    for path in ("input/brief.md", "authorities/Smith v Jones.pdf"):
        assert path_re.search(path) is not None

    manifest = {
        "schemaVersion": "cite-check.manifest.v2",
        "runId": "run-001",
        "target": {
            "path": "input/brief.md",
            "fullDocumentRef": "input/brief.md",
            "displayName": "Brief",
        },
        "authorities": [
            {
                "sourceId": "A0001",
                "path": "authorities/Smith v Jones.pdf",
                "filename": "Smith v Jones.pdf",
                "readability": "readable",
                "contentIdentity": {"caseName": "Smith v. Jones"},
            }
        ],
        "units": [
            {
                "unitId": "P0001",
                "kind": "paragraph",
                "path": "input/brief.md",
                "lineStart": 1,
                "lineEnd": 1,
                "footnoteAnchorUnitId": None,
            },
            {
                "unitId": "F0001",
                "kind": "footnote",
                "path": "input/brief.md",
                "lineStart": 2,
                "lineEnd": 2,
                "footnoteAnchorUnitId": "P0001",
            },
        ],
        "limitations": [],
    }
    result = ajv_validate([("manifest", "manifest.schema.json", manifest)])
    assert result == {"manifest": True}


def test_coverage_uses_terminal_unit_states() -> None:
    schema = load_schema("coverage.schema.json")
    assert set(schema["$defs"]["unitState"]["properties"]) == {
        "unitId",
        "state",
    }
    assert schema["$defs"]["unitState"]["properties"]["state"]["enum"] == [
        "no_citations_found",
        "complete",
        "failed",
        "still_missing",
    ]
    serialized = json.dumps(schema)
    for retired in ("excludedUnitIds", "exclusionReceipts", "expectedReviewUnitIds"):
        assert retired not in serialized

    coverage = {
        "schemaVersion": "cite-check.coverage.v2",
        "runId": "run-001",
        "phase": "final",
        "unitStates": [
            {"unitId": "P0001", "state": "complete"},
            {"unitId": "P0002", "state": "no_citations_found"},
            {"unitId": "P0003", "state": "failed"},
            {"unitId": "P0004", "state": "still_missing"},
        ],
        "retriedUnitIds": ["P0003"],
        "status": "incomplete",
        "isComplete": False,
    }
    result = ajv_validate([("coverage", "coverage.schema.json", coverage)])
    assert result == {"coverage": True}


def test_complete_coverage_requires_no_unresolved_state() -> None:
    coverage = {
        "schemaVersion": "cite-check.coverage.v2",
        "runId": "run-002",
        "phase": "final",
        "unitStates": [
            {"unitId": "P0001", "state": "complete"},
            {"unitId": "P0002", "state": "no_citations_found"},
        ],
        "retriedUnitIds": [],
        "status": "complete",
        "isComplete": True,
    }
    result = ajv_validate([("complete", "coverage.schema.json", coverage)])
    assert result == {"complete": True}
