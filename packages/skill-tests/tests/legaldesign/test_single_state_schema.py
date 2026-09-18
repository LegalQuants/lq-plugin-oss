"""Validate portable v4 state with both mechanical and full schema evaluators.

Client fixtures call the runtime's actual state-reduction function with a tiny
rendered-unit DOM stand-in. Browser tests separately cover rendering and exports.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest
from public_contract import validate_json_schema

ROOT = Path(__file__).resolve().parents[4]
SKILL = ROOT / "skills/core/legaldesign"
PLANS = ROOT / "packages/legaldesign/templates"
FIXTURES = ROOT / "packages/skill-tests/tests/legaldesign/fixtures"
NAMES = [
    "stacked-explainer",
    "method-map",
    "slide-brief",
    "diligence-report",
    "card-hub",
]
MODULE = importlib.util.spec_from_file_location(
    "legaldesign_single_state_schema", SKILL / "scripts/scaffold.py"
)
assert MODULE is not None and MODULE.loader is not None
scaffold = importlib.util.module_from_spec(MODULE)
MODULE.loader.exec_module(scaffold)
STATE_SCHEMA = json.loads(
    (SKILL / "schemas/state.schema.json").read_text(encoding="utf-8")
)

VALIDATE_JS = r"""
import Ajv from './packages/pluginctl/node_modules/ajv/dist/2020.js';
import {readFileSync} from 'node:fs';
const schema = JSON.parse(readFileSync(
  'skills/core/legaldesign/schemas/state.schema.json', 'utf8'));
const validate = new Ajv({strict: false, allErrors: true}).compile(schema);
const requests = JSON.parse(readFileSync(0, 'utf8'));
const runtime = readFileSync('packages/legaldesign/runtime/runtime.js', 'utf8');
const start = runtime.indexOf('function reducedClientState(');
const end = runtime.indexOf('function placeholderFor(', start);
if (start < 0 || end < 0) throw new Error('Client state reducer not found');
const reduceClient = new Function('state', 'clone', 'singleComposition',
  'currentApproach', 'all', 'PLACEHOLDERS',
  `return (${runtime.slice(start, end)})({}, 'schema-client-fixture');`);
const results = requests.map(({state, client}) => {
  if (client) {
    const sections = Object.entries(state.units).map(([id, unit]) => ({
      getAttribute: name => name === 'data-unit' ? id : null,
      querySelector: () => ({querySelector: () => ({
        innerHTML: unit.variants[unit.selected].html || '<svg></svg>',
      })}),
    }));
    state = reduceClient(state, structuredClone,
      () => state.sourceSchemaVersion === 'legaldesign.build.v4',
      () => state.review.approach || 'a',
      selector => {
        if (selector !== 'section.ld-unit[data-unit]')
          throw new Error(`Unexpected reducer DOM query: ${selector}`);
        return sections;
      }, {cardLine: '[Card.]', figureLabel: '[Figure.]', title: '[Title.]'});
  }
  const valid = validate(state);
  return {state, valid, errors: validate.errors};
});
process.stdout.write(JSON.stringify(results));
"""


def validate_states(states: list[dict], *, client: bool = False) -> list[dict]:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", VALIDATE_JS],
        input=json.dumps([{"state": state, "client": client} for state in states]),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    results = json.loads(result.stdout)
    for item in results:
        mechanical_errors = validate_json_schema(
            item["state"], STATE_SCHEMA, STATE_SCHEMA
        )
        assert item["valid"] == (not mechanical_errors), {
            "mechanical": mechanical_errors,
            "ajv": item["errors"],
            "state": item["state"],
        }
    return results


def working_state(name: str = "stacked-explainer") -> dict:
    plan = json.loads((PLANS / f"{name}.plan.json").read_text(encoding="utf-8"))
    return scaffold.state_from_spec(plan, f"schema-{name}")


def state_from_html(path: Path) -> dict:
    match = re.search(
        r'<script[^>]*id="legaldesign-state"[^>]*>(.*?)</script>',
        path.read_text(encoding="utf-8"),
        re.S,
    )
    assert match is not None
    return json.loads(match.group(1))


@pytest.mark.parametrize("name", NAMES)
def test_fresh_v4_working_and_shipping_template_states(name: str) -> None:
    working = working_state(name)
    template = state_from_html(SKILL / "assets/templates" / f"{name}.template.html")
    for result in validate_states([working, template]):
        assert result["valid"], result["errors"]
        state = result["state"]
        assert state["sourceSchemaVersion"] == "legaldesign.build.v4"
        assert "approaches" not in state and "approach" not in state["review"]
        assert (
            state["overview"]["sectionId"] == state["composition"]["sections"][0]["id"]
        )


@pytest.mark.parametrize("name", NAMES)
def test_actual_client_reducer_keeps_a_valid_minimal_v4_state(name: str) -> None:
    result = validate_states([working_state(name)], client=True)[0]
    assert result["valid"], result["errors"]
    state = result["state"]
    assert "claims" not in state and state["evidence"] == {}
    assert state["brief"]["sources"] == []
    assert set(state["composition"]) == {"strategy", "sections"}
    for section in state["composition"]["sections"]:
        expected = {"id", "unitIds", "layout"}
        if "issueLayout" in section:
            expected.add("issueLayout")
            recipe = section["issueLayout"]
            references = [
                recipe["findingUnitId"],
                recipe["implicationUnitId"],
                recipe["actionUnitId"],
                *recipe["supportUnitIds"],
            ]
            assert len(references) == len(set(references))
            assert all(
                unit_id in section["unitIds"] and unit_id in state["units"]
                for unit_id in references
            )
        if "presentation" in section:
            expected.add("presentation")
            assert section["presentation"] == "card-hub"
        assert set(section) == expected
    assert all(
        "encoding" not in unit["variants"]["a"] for unit in state["units"].values()
    )
    assert all(unit["variants"]["a"]["why"] == "" for unit in state["units"].values())
    assert "approaches" not in state and "approach" not in state["review"]


def test_v4_new_layout_and_detail_fields_remain_typed() -> None:
    state = working_state()
    section = state["composition"]["sections"][0]
    section["indexLabel"] = "Scope and answer"
    section["layout"]["placements"][0]["rowSpan"] = 2
    unit = next(unit for unit in state["units"].values() if unit["kind"] == "text")
    unit["detailAnchor"] = "Read the supplied note"
    result = validate_states([state])[0]
    assert result["valid"], result["errors"]
    invalid = []
    for value in [0, 13, 1.5, "2"]:
        changed = copy.deepcopy(state)
        changed["composition"]["sections"][0]["layout"]["placements"][0]["rowSpan"] = (
            value
        )
        invalid.append(changed)
    for field, value in [("indexLabel", ""), ("indexLabel", "x" * 49)]:
        changed = copy.deepcopy(state)
        changed["composition"]["sections"][0][field] = value
        invalid.append(changed)
    for result in validate_states(invalid):
        assert not result["valid"], result["state"]


def test_v4_rejects_legacy_alternatives_and_missing_single_output_fields() -> None:
    baseline = working_state()
    invalid = []
    for field in ["composition", "overview"]:
        state = copy.deepcopy(baseline)
        del state[field]
        invalid.append(state)
    for field, value in [
        ("approaches", {}),
        ("sourceSchemaVersion", "legaldesign.build.v5"),
    ]:
        state = copy.deepcopy(baseline)
        state[field] = value
        invalid.append(state)
    for form in ["walkthrough", "report", "library", "custom"]:
        state = copy.deepcopy(baseline)
        state["brief"]["form"] = form
        invalid.append(state)
    state = copy.deepcopy(baseline)
    state["review"]["approach"] = "a"
    invalid.append(state)
    for field, value in [
        ("selected", "b"),
        (
            "variants",
            {"a": {"axis": "single", "why": ""}, "b": {"axis": "single", "why": ""}},
        ),
        ("edits", {"a": None, "b": None}),
    ]:
        state = copy.deepcopy(baseline)
        next(iter(state["units"].values()))[field] = value
        invalid.append(state)
    for location in [-1, "overview"]:
        state = copy.deepcopy(baseline)
        state["review"]["location"] = location
        invalid.append(state)
    for result in validate_states(invalid):
        assert not result["valid"], result["state"]


def test_v4_overview_reference_shapes_and_page_counts_are_enforced() -> None:
    baseline = working_state("slide-brief")
    invalid = []
    for field in [
        "sectionId",
        "contextUnitIds",
        "questionUnitId",
        "answerUnitId",
        "topics",
    ]:
        state = copy.deepcopy(baseline)
        del state["overview"][field]
        invalid.append(state)
    for field, value in [
        ("sectionId", ""),
        ("questionUnitId", 3),
        ("answerUnitId", None),
        ("contextUnitIds", []),
        ("contextUnitIds", [""]),
        ("contextUnitIds", ["facts", "facts"]),
        ("topics", []),
        ("topics", [{"unitId": "topic"}]),
        ("topics", [{"unitId": "topic", "targetSectionId": ""}]),
        ("topics", [{"unitId": [], "targetSectionId": "detail"}]),
        ("topics", [{"unitId": "topic", "targetSectionId": "detail", "href": "/"}]),
    ]:
        state = copy.deepcopy(baseline)
        state["overview"][field] = value
        invalid.append(state)
    state = copy.deepcopy(baseline)
    state["overview"]["topics"].append(copy.deepcopy(state["overview"]["topics"][0]))
    invalid.append(state)
    state = copy.deepcopy(baseline)
    state["composition"]["sections"] = state["composition"]["sections"][:1]
    invalid.append(state)
    state = copy.deepcopy(baseline)
    state["brief"]["form"] = "one-page"
    invalid.append(state)
    state = working_state()
    state["overview"]["topics"] = [{"unitId": "topic", "targetSectionId": "detail"}]
    invalid.append(state)
    for result in validate_states(invalid):
        assert not result["valid"], result["state"]


def test_minimal_client_composition_still_requires_real_layout_structure() -> None:
    baseline = validate_states([working_state()], client=True)[0]["state"]
    invalid = []
    for field in ["strategy", "sections"]:
        state = copy.deepcopy(baseline)
        del state["composition"][field]
        invalid.append(state)
    for field in ["id", "unitIds", "layout"]:
        state = copy.deepcopy(baseline)
        del state["composition"]["sections"][0][field]
        invalid.append(state)
    for field, value in [
        ("unitId", ""),
        ("row", 0),
        ("column", 13),
        ("span", 0),
        ("rowSpan", -1),
    ]:
        state = copy.deepcopy(baseline)
        state["composition"]["sections"][0]["layout"]["placements"][0][field] = value
        invalid.append(state)
    state = copy.deepcopy(baseline)
    state["units"] = {}
    invalid.append(state)
    for result in validate_states(invalid):
        assert not result["valid"], result["state"]


def test_legacy_v1_v2_and_v3_states_remain_valid() -> None:
    v1 = state_from_html(SKILL / "assets/library.html")
    assert "sourceSchemaVersion" not in v1
    v2_spec = json.loads(
        (FIXTURES / "valid-build-spec.json").read_text(encoding="utf-8")
    )
    v2 = copy.deepcopy(v1)
    v2.update(
        sourceSchemaVersion="legaldesign.build.v2",
        brief=v2_spec["brief"],
        style=v2_spec["style"],
        units={},
    )
    for source in v2_spec["units"]:
        unit = copy.deepcopy(source)
        unit_id = unit.pop("id")
        unit.update(selected="b", edits={"a": None, "b": "Edited legacy copy"})
        v2["units"][unit_id] = unit
    v2["review"].update(approach="b", location="legacy-page")
    versionless_v2 = copy.deepcopy(v2)
    del versionless_v2["sourceSchemaVersion"]
    v3_plan = json.loads(
        (FIXTURES / "case-06-novel-composition.plan.json").read_text(encoding="utf-8")
    )
    v3 = scaffold.state_from_spec(v3_plan, "schema-legacy-v3")
    assert set(v3["approaches"]) == {"a", "b"}
    for result in validate_states([v1, v2, versionless_v2, v3]):
        assert result["valid"], result["errors"]
    v3_client = validate_states([v3], client=True)[0]
    assert v3_client["valid"], v3_client["errors"]
    assert set(v3_client["state"]["approaches"]) == {"a"}


def test_legacy_v3_still_requires_its_authoring_composition_fields() -> None:
    plan = json.loads(
        (FIXTURES / "case-06-novel-composition.plan.json").read_text(encoding="utf-8")
    )
    baseline = scaffold.state_from_spec(plan, "schema-legacy-v3")
    invalid = []
    for field in ["shape", "rationale", "templateRef"]:
        state = copy.deepcopy(baseline)
        del state["approaches"]["a"]["composition"][field]
        invalid.append(state)
    state = copy.deepcopy(baseline)
    del state["approaches"]["a"]["composition"]["sections"][0]["purpose"]
    invalid.append(state)
    state = copy.deepcopy(baseline)
    del state["approaches"]
    invalid.append(state)
    for result in validate_states(invalid):
        assert not result["valid"], result["state"]


@pytest.mark.parametrize(
    "schema,value,valid",
    [
        ({"allOf": [{"minimum": 1}, {"maximum": 12}]}, 13, False),
        ({"allOf": [{"minimum": 1}, {"maximum": 12}]}, 12, True),
        ({"anyOf": [{"type": "string"}, {"type": "null"}]}, 0, False),
        ({"anyOf": [{"type": "string"}, {"type": "null"}]}, None, True),
        ({"oneOf": [{"type": "number"}, {"minimum": 1}]}, 2, False),
        ({"oneOf": [{"type": "number"}, {"minimum": 1}]}, 0, True),
        (
            {"not": {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]}},
            {"b": 1},
            False,
        ),
        ({"not": {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]}}, {}, True),
        ({"uniqueItems": True}, [{"a": 1, "b": 2}, {"b": 2, "a": 1.0}], False),
        ({"uniqueItems": True}, [{"a": True}, {"a": 1}], True),
        ({"const": 1}, True, False),
        ({"enum": [False]}, 0, False),
        ({"minProperties": 1}, {}, False),
        ({"maxProperties": 1}, {"a": 1, "b": 2}, False),
        ({"propertyNames": {"minLength": 1}}, {"": {}}, False),
        ({"propertyNames": {"pattern": "^[a-z]+$"}}, {"ab": {}}, True),
        ({"propertyNames": {"pattern": "^[a-z]+$"}}, {"A": {}}, False),
        ({"type": "integer", "minimum": 1}, 0, False),
        ({"type": "integer", "maximum": 12}, 13, False),
        ({"type": "integer", "minimum": 1}, True, False),
        ({"type": "integer", "minimum": 1}, 1.0, True),
        ({"type": "integer"}, 1.5, False),
        ({"maxLength": 3}, "abcd", False),
        ({"properties": {"secret": False}}, {"secret": "no"}, False),
        ({"items": False}, [], True),
        ({"items": False}, [1], False),
    ],
)
def test_stdlib_schema_supported_keyword_semantics(schema, value, valid) -> None:
    errors = validate_json_schema(value, schema, schema)
    assert (not errors) == valid, errors


@pytest.mark.parametrize(
    "value,valid",
    [
        ({"version": 4, "composition": {}}, True),
        ({"version": 4}, False),
        ({"version": 3, "approaches": {}}, True),
        ({"version": 3}, False),
        ({"approaches": {}}, True),
    ],
)
def test_stdlib_schema_condition_selects_only_the_matching_branch(value, valid) -> None:
    schema = {
        "if": {"properties": {"version": {"const": 4}}, "required": ["version"]},
        "then": {"required": ["composition"], "not": {"required": ["approaches"]}},
        "else": {"required": ["approaches"], "not": {"required": ["composition"]}},
    }
    errors = validate_json_schema(value, schema, schema)
    assert (not errors) == valid, errors


def test_stdlib_schema_reference_keeps_sibling_constraints() -> None:
    schema = {
        "$defs": {"a/b~c": {"type": "integer", "minimum": 1}},
        "$ref": "#/$defs/a~1b~0c",
        "maximum": 12,
    }
    assert validate_json_schema(1, schema, schema) == []
    assert validate_json_schema(0, schema, schema)
    assert validate_json_schema(13, schema, schema)
    assert validate_json_schema("1", schema, schema)
