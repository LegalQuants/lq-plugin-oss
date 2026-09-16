from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


def load(name, path):
    definition = importlib.util.spec_from_file_location(name, path)
    assert definition is not None and definition.loader is not None
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    return module


scaffold = load("issue_scaffold", ROOT / "skills/core/legaldesign/scripts/scaffold.py")
fixtures = load(
    "issue_fixture", Path(__file__).with_name("test_scaffold_single_output.py")
)
PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lE"
    "QVR42mP8/x8AAwMCAO+jXioAAAAASUVORK5CYII="
)


def issue_spec(support="both"):
    spec = fixtures.single_spec("slide-brief")
    prototype = spec["units"].pop()
    header = copy.deepcopy(spec["units"][1])
    header.update(id="issue-title", role="summary")
    header["variants"]["a"]["html"] = "<h1>Assignment consent</h1>"
    added = [header]
    for unit_id, role, heading in [
        ("finding", "finding", "What the agreement says"),
        ("implication", "summary", "Why consent matters"),
        ("action", "action", "Next check"),
    ]:
        unit = copy.deepcopy(prototype)
        unit.update(id=unit_id, kind="card", role=role)
        unit["variants"]["a"]["html"] = (
            f"<h2>{heading}</h2><p>Obtain written consent before assignment.</p>"
        )
        added.append(unit)
    support_ids = []
    if support in {"figure", "both"}:
        unit = copy.deepcopy(prototype)
        unit.update(id="support-figure", kind="figure")
        unit.pop("detail", None)
        unit["relationship"] = "sequence"
        unit["candidates"] = ["flow"]
        variant = unit["variants"]["a"]
        variant.pop("html")
        variant.update(
            component="flow",
            params={
                "stages": [
                    {"title": "Written consent", "sub": "Obtain consent"},
                    {"title": "Assignment", "sub": "Check conditions"},
                ],
                "edges": ["permits"],
            },
        )
        added.append(unit)
        support_ids.append(unit["id"])
    if support in {"source", "both"}:
        unit = copy.deepcopy(prototype)
        unit.update(id="support-source", kind="evidence", sourcePreview=True)
        unit["variants"]["a"].pop("html")
        added.append(unit)
        support_ids.append(unit["id"])
        spec["evidence"][0]["excerpt"] = (
            "Exact supplied clause: consent <must> precede assignment."
        )
    footer = copy.deepcopy(header)
    footer.update(id="issue-scope", role="scope")
    footer["variants"]["a"]["html"] = "<p>Scope: supplied assignment clause only.</p>"
    added.append(footer)
    spec["units"].extend(added)
    section = spec["composition"]["sections"][1]
    section["unitIds"] = [unit["id"] for unit in added]
    section.pop("layout")
    section["issueLayout"] = {
        "findingUnitId": "finding",
        "implicationUnitId": "implication",
        "actionUnitId": "action",
        "supportUnitIds": support_ids,
    }
    return spec


def schema_errors(data, name):
    script = """
import Ajv from './packages/pluginctl/node_modules/ajv/dist/2020.js';
import {readFileSync} from 'node:fs';
const {data,name}=JSON.parse(readFileSync(0,'utf8'));
const schema=JSON.parse(readFileSync(
  'skills/core/legaldesign/schemas/'+name+'.schema.json','utf8'));
const validate=new Ajv({strict:false,allErrors:true}).compile(schema);
validate(data); process.stdout.write(JSON.stringify(validate.errors||[]));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        input=json.dumps({"data": data, "name": name}),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("support", ["figure", "source", "both"])
def test_recipe_derives_layout_and_single_ownership_without_mutating_input(support):
    spec = issue_spec(support)
    original = copy.deepcopy(spec)
    assert scaffold.validate_spec(spec) == []
    assert schema_errors(spec, "build-spec") == []
    state = scaffold.state_from_spec(spec, "recipe-test")
    section = state["composition"]["sections"][1]
    assert section["layout"]["columns"] == 12
    assert section["layout"] == scaffold._derive_issue_layout(section)
    assert schema_errors(json.loads(json.dumps(state)), "state") == []
    html = scaffold.render_composed_html(spec, "recipe-test")
    assert html.count('class="ld-issue-body"') == 1
    assert html.count('class="ld-issue-analysis"') == 1
    assert html.count('class="ld-issue-support"') == 1
    for unit_id in section["unitIds"]:
        assert html.count(f'data-unit="{unit_id}"') == 1
    assert spec == original


@pytest.mark.parametrize(
    "change,expected",
    [
        (
            lambda s: s["composition"]["sections"][1]["issueLayout"].update(
                actionUnitId="finding"
            ),
            "distinct",
        ),
        (
            lambda s: s["composition"]["sections"][1]["issueLayout"].update(
                findingUnitId="facts"
            ),
            "belong to this section",
        ),
        (
            lambda s: next(u for u in s["units"] if u["id"] == "implication").update(
                kind="text"
            ),
            "must be a card",
        ),
        (
            lambda s: next(u for u in s["units"] if u["id"] == "action").update(
                role="summary"
            ),
            "role action",
        ),
        (
            lambda s: s["composition"]["sections"][1]["issueLayout"].update(
                supportUnitIds=[]
            ),
            "at least 1",
        ),
        (
            lambda s: s["composition"]["sections"][1]["issueLayout"].update(
                supportUnitIds=["support-source", "support-figure", "action"]
            ),
            "one or two",
        ),
        (
            lambda s: s["composition"]["sections"][1]["unitIds"].reverse(),
            "unitIds order",
        ),
        (
            lambda s: s["composition"]["sections"][1].update(
                layout={"columns": 12, "placements": []}
            ),
            "deterministic issue placements",
        ),
        (
            lambda s: next(u for u in s["units"] if u["id"] == "issue-scope").update(
                role="summary"
            ),
            "scope-text footer",
        ),
    ],
)
def test_invalid_issue_roles_ownership_order_and_coordinates_fail(change, expected):
    spec = issue_spec()
    change(spec)
    assert any(expected in error for error in scaffold.validate_spec(spec))


@pytest.mark.parametrize("invalid", [None, False, "support-figure", [None], [{}]])
def test_malformed_support_reference_reports_errors_without_crashing(invalid):
    spec = issue_spec()
    section = spec["composition"]["sections"][1]
    section["layout"] = scaffold._derive_issue_layout(section)
    section["issueLayout"]["supportUnitIds"] = invalid
    assert scaffold.validate_spec(spec)


def test_recipe_cannot_replace_the_overview_or_one_page_contract():
    spec = issue_spec()
    spec["brief"]["form"] = "one-page"
    assert any("after the overview" in error for error in scaffold.validate_spec(spec))
    spec["brief"]["form"] = "slide-brief"
    spec["overview"]["sectionId"] = spec["composition"]["sections"][1]["id"]
    assert any("after the overview" in error for error in scaffold.validate_spec(spec))


@pytest.mark.parametrize(
    "change,expected",
    [
        (lambda s: s["evidence"][0].pop("excerpt"), "explicit exact excerpt"),
        (lambda s: s["evidence"][0]["popup"].update(type="explainer"), "type source"),
        (
            lambda s: next(u for u in s["units"] if u["id"] == "support-source").update(
                detail="absent"
            ),
            "existing source",
        ),
        (
            lambda s: next(u for u in s["units"] if u["id"] == "support-source")[
                "variants"
            ]["a"].update(html="<img src='https://example.test/fake.png'>"),
            "do not provide html",
        ),
    ],
)
def test_preview_requires_typed_exact_source_not_authored_html(change, expected):
    spec = issue_spec()
    change(spec)
    assert any(expected in error for error in scaffold.validate_spec(spec))


def test_source_quote_is_escaped_in_editor_body_with_unpromoted_metadata():
    spec = issue_spec("source")
    html = scaffold.render_composed_html(spec, "quote-test")
    expected = "Exact supplied clause: consent &lt;must&gt; precede assignment."
    assert expected in html
    state = scaffold.state_from_spec(spec, "quote-test")
    content = state["units"]["support-source"]["variants"]["a"]["html"]
    assert '<blockquote class="doc-text" contenteditable="false">' in content
    assert expected in content
    assert "Assignment clause · supplied" in content
    assert state["evidence"]["consent-record"]["status"] == "supplied"
    assert 'data-kind="evidence"' in html and 'data-detail="consent-record"' in html
    assert 'data-variant-body data-editable><figure class="ld-source-preview"' in html


def test_authenticated_clip_is_only_image_source_and_remains_protected():
    spec = issue_spec("source")
    source = spec["evidence"][0]
    source["exhibit"] = {
        "data": "data:image/png;base64," + PNG,
        "sha256": hashlib.sha256(base64.b64decode(PNG)).hexdigest(),
        "sourceSha256": "a" * 64,
        "locator": "Assignment clause",
        "captureMethod": "Supplied synthetic test clip",
        "capturedAt": "2026-09-06T00:00:00Z",
        "alt": "Supplied clause image",
    }
    assert scaffold.validate_spec(spec) == []
    state = scaffold.state_from_spec(spec, "clip-test")
    assert schema_errors(state, "state") == []
    assert (
        f'src="data:image/png;base64,{PNG}"'
        in state["units"]["support-source"]["variants"]["a"]["html"]
    )
    source["exhibit"]["data"] = "https://example.test/fabricated.png"
    assert any("base64 PNG/JPEG" in error for error in scaffold.validate_spec(spec))


def test_exact_quote_participates_in_page_budget():
    spec = issue_spec("source")
    spec["evidence"][0]["excerpt"] = "Exact supplied text. " * 300
    with pytest.raises(ValueError, match="overview budget"):
        scaffold.render_composed_html(spec, "long-source")


def test_legacy_and_normal_v4_layouts_unchanged():
    normal = fixtures.single_spec()
    assert scaffold.validate_spec(normal) == []
    assert scaffold._normalize_issue_layouts(normal) == normal
    preview = issue_spec("source")
    preview["schemaVersion"] = "legaldesign.build.v3"
    assert any(
        "available only in v4" in error for error in scaffold.validate_spec(preview)
    )


def test_direct_composition_helper_without_evidence_keeps_legacy_behavior():
    spec = fixtures.single_spec()
    minimal = {"brief": spec["brief"], "units": spec["units"]}
    markup = scaffold._render_composition(minimal, spec["composition"], "a")
    assert 'class="ld-composed-grid"' in markup
    for unit in spec["units"]:
        assert f'data-unit="{unit["id"]}"' in markup
    preview = issue_spec("source")
    preview.pop("evidence")
    assert any("existing source" in error for error in scaffold.validate_spec(preview))
