from __future__ import annotations

import copy
import importlib.util
import io
import json
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "skills/core/legaldesign/scripts/scaffold.py"
MODULE = importlib.util.spec_from_file_location("legaldesign_single_output", SCRIPT)
assert MODULE is not None and MODULE.loader is not None
scaffold = importlib.util.module_from_spec(MODULE)
MODULE.loader.exec_module(scaffold)


def single_spec(form: str = "one-page") -> dict:
    def unit(
        unit_id: str,
        text: str,
        claim: str,
        *,
        role: str = "summary",
        kind: str = "text",
    ) -> dict:
        value = {
            "id": unit_id,
            "kind": kind,
            "role": role,
            "claim": text,
            "claimRefs": [claim],
            "relationship": "containment",
            "candidates": ["text", "card"],
            "placeholder": "[Question or finding.]",
            "variants": {
                "a": {
                    "html": f"<h1>{text}</h1>" if role == "title" else f"<p>{text}</p>",
                    "axis": "framing",
                    "encoding": "Reading order separates facts, question and answer.",
                    "why": "A short statement communicates this proposition.",
                }
            },
        }
        if claim == "answer-claim":
            value.update(evidence=["consent-record"], detail="consent-record")
        return value

    def section(section_id: str, ids: list[str]) -> dict:
        return {
            "id": section_id,
            "purpose": "Explain the consent requirement.",
            "indexLabel": "Consent review"
            if section_id == "overview"
            else "Required consent",
            "unitIds": ids,
            "layout": {
                "columns": 12,
                "placements": [
                    {"unitId": value, "row": index + 1, "column": 1, "span": 12}
                    for index, value in enumerate(ids)
                ],
            },
        }

    units = [
        unit("title", "Consent review", "context-claim", role="title"),
        unit(
            "facts",
            "The supplied agreement requires written consent before assignment.",
            "context-claim",
        ),
        unit(
            "question", "Can the assignment proceed before consent?", "question-claim"
        ),
        unit(
            "answer",
            "Obtain written consent before the proposed assignment.",
            "answer-claim",
            role="answer",
        ),
    ]
    sections = [section("overview", [value["id"] for value in units])]
    overview = {
        "sectionId": "overview",
        "contextUnitIds": ["facts"],
        "questionUnitId": "question",
        "answerUnitId": "answer",
        "topics": [],
    }
    if form == "slide-brief":
        units += [
            unit(
                "consent-topic",
                "Examine the required consent",
                "question-claim",
                kind="card",
            ),
            unit(
                "consent-detail",
                "The agreement states the required written consent.",
                "answer-claim",
            ),
        ]
        sections[0] = section(
            "overview", ["title", "facts", "question", "answer", "consent-topic"]
        )
        sections.append(section("consent", ["consent-detail"]))
        overview["topics"] = [{"unitId": "consent-topic", "targetSectionId": "consent"}]
    return {
        "schemaVersion": "legaldesign.build.v4",
        "brief": {
            "title": "Consent review",
            "reader": "Deal lead",
            "action": "Obtain consent",
            "purpose": "understand",
            "message": "Consent is required before assignment.",
            "spine": "containment",
            "situation": "laptop",
            "form": form,
            "sources": [
                {"id": "agreement", "label": "Supplied agreement", "status": "supplied"}
            ],
            "assumptions": [],
            "gaps": [],
        },
        "style": {"source": "loxoto", "ref": None},
        "composition": {
            "strategy": "composed",
            "shape": "Overview and supporting topics",
            "rationale": "Establish the question before its supporting detail.",
            "sections": sections,
            "templateRef": None,
        },
        "overview": overview,
        "claims": [
            {
                "id": claim,
                "text": text,
                "kind": "material" if claim == "answer-claim" else "context",
                "sourceIds": ["agreement"],
                "placement": "surface",
                "evidenceIds": ["consent-record"] if claim == "answer-claim" else [],
            }
            for claim, text in [
                ("context-claim", "The supplied agreement governs assignment."),
                ("question-claim", "The deal lead asks whether consent is needed."),
                ("answer-claim", "Consent is required before assignment."),
            ]
        ],
        "units": units,
        "evidence": [
            {
                "id": "consent-record",
                "sourceId": "agreement",
                "claimRefs": ["answer-claim"],
                "cite": "Supplied agreement",
                "locator": "Assignment clause",
                "status": "supplied",
                "detail": "Written consent is required before assignment.",
                "popup": {
                    "type": "source",
                    "title": "What consent does the agreement require?",
                    "sections": [
                        {
                            "heading": "Assignment restriction",
                            "body": "Written consent is required before assignment.",
                        }
                    ],
                },
                "original": {
                    "availability": "unavailable",
                    "label": "Supplied agreement file",
                },
            }
        ],
    }


@pytest.mark.parametrize("form", ["one-page", "slide-brief"])
def test_v4_single_output_state_and_dom(form: str) -> None:
    spec = single_spec(form)
    assert scaffold.validate_spec(spec) == []
    state = scaffold.state_from_spec(spec, "single-output")
    assert "approaches" not in state and "approach" not in state["review"]
    assert state["sourceSchemaVersion"] == "legaldesign.build.v4"
    assert state["brief"]["form"] == form
    assert state["composition"] == spec["composition"]
    assert state["overview"] == spec["overview"]
    assert all(set(unit["variants"]) == {"a"} for unit in state["units"].values())
    html = scaffold._render_approaches(spec)
    assert html.count('data-approach="a"') == 1
    assert 'data-approach="b"' not in html and "data-select-approach" not in html
    assert html.count('data-unit="facts"') == 1
    if form == "slide-brief":
        assert 'data-section-target="consent"' in html
        assert 'role="button" tabindex="0"' in html
        assert html.count("data-composition-section=") == 2


@pytest.mark.parametrize(
    "field", ["sectionId", "contextUnitIds", "questionUnitId", "answerUnitId", "topics"]
)
def test_v4_overview_requires_all_orientation_fields(field: str) -> None:
    spec = single_spec()
    del spec["overview"][field]
    assert any(field in error for error in scaffold.validate_spec(spec))


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda spec: spec.pop("overview"), "overview"),
        (
            lambda spec: spec["overview"].update(sectionId="consent"),
            "first composition section",
        ),
        (lambda spec: spec["overview"].update(contextUnitIds=[]), "at least 1"),
        (
            lambda spec: spec["overview"].update(questionUnitId="facts"),
            "distinct units",
        ),
        (
            lambda spec: spec["overview"].update(answerUnitId="consent-detail"),
            "placed in the overview",
        ),
        (lambda spec: spec["overview"].update(topics=[]), "every subsequent section"),
        (
            lambda spec: spec["overview"]["topics"][0].update(
                targetSectionId="missing"
            ),
            "subsequent section",
        ),
        (
            lambda spec: spec["overview"]["topics"][0].update(
                targetSectionId="overview"
            ),
            "subsequent section",
        ),
        (
            lambda spec: spec["overview"]["topics"][0].update(unitId="consent-detail"),
            "overview text/card",
        ),
        (
            lambda spec: spec["overview"]["topics"].append(
                copy.deepcopy(spec["overview"]["topics"][0])
            ),
            "one destination",
        ),
        (lambda spec: spec.update(approaches={"b": {}}), "unknown field 'approaches'"),
        (lambda spec: spec["brief"].update(form="report"), "slide-brief"),
        (lambda spec: spec["brief"].update(form="walkthrough"), "slide-brief"),
        (
            lambda spec: spec["units"][1]["variants"]["a"].update(html="<p></p>"),
            "visible context/question/answer",
        ),
        (
            lambda spec: spec["units"][4].update(detail="consent-record"),
            "navigation and popup",
        ),
        (lambda spec: spec["units"][4].update(kind="decision"), "overview text/card"),
        (lambda spec: spec["units"][4].update(kind="figure"), "overview text/card"),
        (
            lambda spec: spec["units"][0]["variants"].update(
                b=copy.deepcopy(spec["units"][0]["variants"]["a"])
            ),
            "exactly 1 variant",
        ),
    ],
)
def test_v4_overview_rejects_broken_invariants(mutate, expected: str) -> None:
    spec = single_spec("slide-brief")
    mutate(spec)
    assert any(expected in error for error in scaffold.validate_spec(spec))


def test_v4_forms_enforce_page_count_and_topics() -> None:
    spec = single_spec("slide-brief")
    spec["brief"]["form"] = "one-page"
    assert any(
        "one overview section" in error for error in scaffold.validate_spec(spec)
    )
    spec = single_spec()
    spec["brief"]["form"] = "slide-brief"
    assert any(
        "at least one subsequent section" in error
        for error in scaffold.validate_spec(spec)
    )


def test_v4_init_fill_compose_and_schema(tmp_path: Path) -> None:
    plan = scaffold._skeleton("slide-brief")
    assert plan["schemaVersion"] == "legaldesign.build.v4" and "approaches" not in plan
    plan.update(single_spec("slide-brief"))
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    with redirect_stdout(io.StringIO()) as stdout:
        assert (
            scaffold._command_compose(
                SimpleNamespace(
                    plan=path,
                    spec_output=tmp_path / "spec.json",
                    output=tmp_path / "artifact.html",
                    artifact_id="single-output",
                )
            )
            == 0
        )
    receipt = json.loads(stdout.getvalue())
    assert (
        receipt["schemaVersion"] == "legaldesign.build.v4"
        and "approaches" not in receipt
    )
    html = (tmp_path / "artifact.html").read_text(encoding="utf-8")
    assert 'data-section-target="consent"' in html
    script = """
import Ajv from './packages/pluginctl/node_modules/ajv/dist/2020.js';
import {readFileSync} from 'node:fs';
const schemaPath='skills/core/legaldesign/schemas/build-spec.schema.json';
const schema=JSON.parse(readFileSync(schemaPath,'utf8'));
const validate=new Ajv({strict:false}).compile(schema);
const value=JSON.parse(readFileSync(process.argv[1],'utf8'));
if(!validate(value)) throw new Error(JSON.stringify(validate.errors));
for(const mutate of [s=>delete s.overview, s=>s.approaches={a:{},b:{}},
 s=>s.brief.form='report', s=>s.units[0].variants.b=s.units[0].variants.a]) {
 const invalid=structuredClone(value); mutate(invalid);
 if(validate(invalid)) throw new Error('invalid v4 passed JSON schema');
}
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "component,field,modest,dense",
    [
        ("flow", "stages", 4, 5),
        ("hierarchy", "branches", 2, 3),
    ],
)
def test_v4_modest_figures_allow_seven_columns_without_losing_capacity_guard(
    component: str, field: str, modest: int, dense: int
) -> None:
    unit = {
        "variants": {"a": {"component": component, "params": {field: [{}] * modest}}}
    }
    assert scaffold._component_minimum_span(unit) == 8
    assert (
        scaffold._component_minimum_span(unit, spec_version="legaldesign.build.v4") == 7
    )
    unit["variants"]["a"]["params"][field] = [{}] * dense
    assert (
        scaffold._component_minimum_span(unit, spec_version="legaldesign.build.v4")
        == 12
    )


def test_topic_requires_visible_link_text() -> None:
    payload = single_spec("slide-brief")
    topic_id = payload["overview"]["topics"][0]["unitId"]
    topic = next(unit for unit in payload["units"] if unit["id"] == topic_id)
    topic["variants"]["a"]["html"] = "<p> </p>"
    assert any(
        "visible link text" in error for error in scaffold.validate_spec(payload)
    )


@pytest.mark.parametrize(
    "name,form,count",
    [
        ("stacked-explainer", "one-page", 1),
        ("method-map", "one-page", 1),
        ("slide-brief", "slide-brief", 3),
        ("diligence-report", "slide-brief", 4),
    ],
)
def test_maintainer_templates_are_single_output_overview_led_plans(
    name: str, form: str, count: int
) -> None:
    path = ROOT / "packages/legaldesign/templates" / f"{name}.plan.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert scaffold.validate_spec(payload) == []
    assert payload["schemaVersion"] == "legaldesign.build.v4"
    assert payload["brief"]["form"] == form
    assert "approaches" not in payload
    assert len(payload["composition"]["sections"]) == count
    assert len(payload["overview"]["topics"]) == count - 1
    assert all(set(unit["variants"]) == {"a"} for unit in payload["units"])
    assert not any(unit["id"].startswith("b-") for unit in payload["units"])
    overview = payload["overview"]
    units = {unit["id"]: unit for unit in payload["units"]}
    for unit_id in [
        *overview["contextUnitIds"],
        overview["questionUnitId"],
        overview["answerUnitId"],
    ]:
        html = units[unit_id]["variants"]["a"]["html"]
        assert "<p>" in html and len(html.split()) >= 8
    # The retained figures still expose all three meaningful source popups.
    assert {"e-core", "e-detail", "e-action"} <= {
        evidence["id"] for evidence in payload["evidence"]
    }
