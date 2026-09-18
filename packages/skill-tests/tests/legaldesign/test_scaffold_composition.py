from __future__ import annotations

import copy
import importlib.util
import io
import json
import re
import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from public_contract import validate_json_schema

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "skills" / "core" / "legaldesign" / "scripts" / "scaffold.py"
FIXTURES = ROOT / "packages/skill-tests/tests/legaldesign/fixtures"
NOVEL_PLAN = FIXTURES / "case-06-novel-composition.plan.json"
TEMPLATE_EXPECTED = FIXTURES / "case-07-template-opt-in.expected.json"
LEGACY_V2_SPEC = FIXTURES / "valid-build-spec.json"
SPEC = importlib.util.spec_from_file_location(
    "legaldesign_scaffold_composition", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
scaffold = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scaffold
SPEC.loader.exec_module(scaffold)


type JSONObject = dict[str, Any]
type JSONMutator = Callable[[JSONObject], None]


def json_object(value: object) -> JSONObject:
    assert isinstance(value, dict)
    return cast(JSONObject, value)


def novel_plan() -> JSONObject:
    payload = json_object(json.loads(NOVEL_PLAN.read_text(encoding="utf-8")))
    evidence = payload["evidence"]
    assert isinstance(evidence, list)
    for item in evidence:
        assert isinstance(item, dict)
        original = item.get("original")
        if isinstance(original, dict) and original.get("availability") == "linked":
            original["href"] = "https://example.test/legaldesign/method"
    return payload


def novel_spec() -> JSONObject:
    return json_object({"schemaVersion": "legaldesign.build.v3", **novel_plan()})


def test_new_composition_excludes_legacy_diagrams_without_breaking_renderer() -> None:
    payload = novel_spec()
    unit = next(item for item in payload["units"] if item["id"] == "a-flow")
    unit["relationship"] = "feedback"
    unit["variants"]["a"].update(
        {
            "component": "loop",
            "params": {
                "centre": "Review",
                "steps": [
                    {"title": "Draft", "edge": "Submit"},
                    {"title": "Review", "edge": "Revise"},
                    {"title": "Revise", "edge": "Resubmit"},
                ],
            },
        }
    )
    errors = scaffold.validate_spec(payload)
    assert any("legacy rendering component" in error for error in errors)
    component_errors: list[str] = []
    scaffold._check_component(
        "loop", unit["variants"]["a"]["params"], "feedback", "legacy", component_errors
    )
    assert component_errors == []


def approach_spec() -> JSONObject:
    return novel_spec()


def test_short_detail_anchor_and_contents_label() -> None:
    payload = novel_spec()
    unit = next(u for u in payload["units"] if u["id"] == "a-summary")
    unit["detail"] = "e-input"
    unit["detailAnchor"] = "legal source"
    unit["evidence"].append("e-input")
    payload["approaches"]["a"]["composition"]["sections"][0]["indexLabel"] = "Inputs"
    assert scaffold.validate_spec(payload) == []
    unit["detailAnchor"] = "a phrase not present in the copy"
    assert any("detailAnchor: must match" in e for e in scaffold.validate_spec(payload))
    unit["detailAnchor"] = "one two three four five six seven eight nine"
    assert any(
        "detailAnchor: use a short phrase" in e for e in scaffold.validate_spec(payload)
    )


def remove_component_detail_params(payload: JSONObject) -> None:
    def remove_details(value: object) -> None:
        if isinstance(value, dict):
            for key in list(value):
                if isinstance(key, str) and key.casefold().endswith("detail"):
                    del value[key]
                else:
                    remove_details(value[key])
        elif isinstance(value, list):
            for item in value:
                remove_details(item)

    units = payload["units"]
    assert isinstance(units, list)
    for unit in units:
        assert isinstance(unit, dict)
        variants = unit.get("variants")
        assert isinstance(variants, dict)
        for variant in variants.values():
            assert isinstance(variant, dict)
            if "component" in variant:
                remove_details(variant.get("params"))


def make_decision_unit(unit: JSONObject) -> None:
    unit.update(
        {
            "kind": "decision",
            "question": "Escalate for legal review?",
            "selection_mode": "single",
            "allow_custom": True,
            "allow_note": True,
            "options": [
                {
                    "key": "A",
                    "label": "Escalate now",
                    "consequence": "Legal review begins within the decision window.",
                },
                {
                    "key": "B",
                    "label": "Do not escalate yet",
                    "consequence": "The response team documents the unmet trigger.",
                },
            ],
        }
    )


def mirror_approach_a_into_b(
    payload: JSONObject, *, move_output_only: bool = False
) -> None:
    remap = {
        "a-title": "b-title",
        "a-summary": "b-summary",
        "a-flow": "b-hierarchy",
        "a-output": "b-output",
    }
    units = payload["units"]
    assert isinstance(units, list)
    units_by_id = {unit["id"]: unit for unit in units}
    for source_id, target_id in remap.items():
        replacement = copy.deepcopy(units_by_id[source_id])
        replacement["id"] = target_id
        target_index = next(
            index for index, unit in enumerate(units) if unit["id"] == target_id
        )
        units[target_index] = replacement

    composition = copy.deepcopy(payload["approaches"]["a"]["composition"])
    for index, section in enumerate(composition["sections"]):
        section["id"] = f"b-mirror-{index + 1}"
        section["unitIds"] = [remap[unit_id] for unit_id in section["unitIds"]]
        for placement in section["layout"]["placements"]:
            placement["unitId"] = remap[placement["unitId"]]
            if move_output_only and placement["unitId"] == "b-output":
                placement.update({"column": 2, "span": 11})
    payload["approaches"]["b"]["composition"] = composition


def test_compose_accepts_a_novel_template_free_plan(tmp_path: Path) -> None:
    plan_path = tmp_path / "incident-path.plan.json"
    plan_path.write_text(json.dumps(novel_plan()), encoding="utf-8")
    spec_output = tmp_path / "incident-path.spec.json"
    output = tmp_path / "incident-path.html"
    stdout = io.StringIO()

    with redirect_stdout(stdout):
        result = scaffold._command_compose(
            SimpleNamespace(
                plan=plan_path,
                spec_output=spec_output,
                output=output,
                artifact_id="incident-path",
            )
        )

    payload = json.loads(spec_output.read_text(encoding="utf-8"))
    html = output.read_text(encoding="utf-8")
    receipt = json.loads(stdout.getvalue())
    assert result == 0
    assert scaffold.validate_spec(payload) == []
    assert payload["schemaVersion"] == "legaldesign.build.v3"
    assert set(payload["approaches"]) == {"a", "b"}
    assert all(
        approach["composition"]["strategy"] == "composed"
        and approach["composition"]["templateRef"] is None
        for approach in payload["approaches"].values()
    )
    assert (
        payload["approaches"]["a"]["composition"]["shape"]
        != payload["approaches"]["b"]["composition"]["shape"]
    )
    assert set(receipt["approaches"]) == {"a", "b"}
    material_claims = [
        claim for claim in payload["claims"] if claim["kind"] == "material"
    ]
    assert receipt["materialClaims"] == len(material_claims)
    assert receipt["surfaceClaims"] == sum(
        claim["placement"] == "surface" for claim in material_claims
    )
    assert receipt["artifactId"] == "incident-path"
    assert receipt["specOutput"] == str(spec_output)
    assert receipt["output"] == str(output)
    assert "data-composed-shell" in html
    assert '<div class="ld-diagram" data-editor-preserve-dom' not in html
    assert "stacked-explainer" not in html
    assert html.count('style="--ld-row:1;--ld-column:1;--ld-span:12"') >= 2
    assert html.index('data-unit="a-title"') < html.index('data-unit="a-flow"')
    assert html.index('data-unit="b-title"') < html.index('data-unit="b-hierarchy"')
    assert 'data-detail="e-output"' in html
    assert '<button class="ld-evidence-trigger' not in html
    assert 'data-evidence-ids="' not in html
    assert 'id="e-input"' in html


def test_v3_page_approaches_are_global_structural_and_title_led() -> None:
    payload = approach_spec()

    assert scaffold.validate_spec(payload) == []
    html = scaffold.render_composed_html(payload, "two-approach-artifact")
    state = embedded_state(html)
    markup = re.sub(
        r"<!-- legaldesign:runtime -->.*?<!-- /legaldesign:runtime -->",
        "",
        html,
        flags=re.DOTALL,
    )

    assert state["review"]["approach"] == "a"
    assert state["approaches"] == payload["approaches"]
    markup = re.sub(
        r'<script id="ld-client-runtime"[^>]*>.*?</script>', "", markup, flags=re.DOTALL
    )
    assert markup.count('id="ld-page-approach"') == 1
    surface = re.sub(r"<script\b[^>]*>.*?</script>", "", markup, flags=re.DOTALL)
    assert surface.count("data-select-approach=") == 2
    assert markup.count("data-approach=") == 2
    assert "data-select-variant" not in markup
    assert "ld-why-toggle" not in markup
    assert "ld-kicker" not in markup
    assert "eyebrow" not in markup.lower()
    assert markup.count("<h1") == 2
    assert payload["brief"]["title"] in markup
    title = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    assert title is not None
    assert title.group(1) == payload["brief"]["title"]
    assert "legaldesign:title" not in title.group(0)
    assert state["units"]["a-flow"]["variants"]["a"]["component"] == "flow"
    assert re.search(
        r"<(?=[^>]*data-evidence-field)(?=[^>]*data-editable)[^>]+>",
        markup,
    )


def test_v3_composed_surface_uses_soft_depth_and_popup_only_sources() -> None:
    html = scaffold.render_composed_html(approach_spec(), "visual-contract")
    surface_match = re.search(
        r"<!-- legaldesign:composed-content -->(.*?)"
        r"<!-- /legaldesign:composed-content -->",
        html,
        re.DOTALL,
    )
    popup_match = re.search(
        r"<!-- legaldesign:popups -->(.*?)<!-- /legaldesign:popups -->",
        html,
        re.DOTALL,
    )

    assert surface_match is not None
    assert popup_match is not None
    surface = surface_match.group(1)
    popups = popup_match.group(1)
    assert "--shadow-soft:" in html
    assert re.search(r">\s*Source\s*:", surface, re.IGNORECASE) is None
    assert re.search(r"<a\b[^>]*href=", surface, re.IGNORECASE) is None
    assert re.search(r"<a\b[^>]*href=", popups, re.IGNORECASE) is not None
    assert "Evidence ·" not in popups
    assert "ld-evidence-sequence" not in popups
    assert "data-evidence-step" not in popups
    assert '<section class="ld-popup-section">' in popups
    assert 'data-popup-type="explainer"' in popups


def test_composed_popup_targets_are_semantic_and_unique() -> None:
    html = scaffold.render_composed_html(approach_spec(), "whole-card-contract")
    a_output = re.search(
        r'<section (?=[^>]*data-unit="a-output")'
        r'(?=[^>]*data-detail="e-output")(?=[^>]*role="button")'
        r'(?=[^>]*tabindex="0")(?=[^>]*aria-haspopup="dialog")[^>]*>',
        html,
    )
    assert a_output is not None
    b_output = re.search(r'<section [^>]*data-unit="b-output"[^>]*>', html)
    assert b_output is not None
    assert "data-detail" not in b_output.group(0)
    assert 'role="button"' not in b_output.group(0)

    state = embedded_state(html)
    hierarchy = state["units"]["b-hierarchy"]
    targets = scaffold._unit_popup_targets(hierarchy, unit_id="b-hierarchy")
    assert [detail_id for detail_id, _ in targets] == [
        "e-input",
        "e-judgment",
        "e-output",
    ]
    assert len({detail_id for detail_id, _ in targets}) == 3
    assert ".ld-popup-trigger" in html
    assert "cursor: pointer" in html


def test_grounding_evidence_does_not_create_surface_chrome() -> None:
    html = scaffold.render_composed_html(approach_spec(), "quiet-grounding")
    surface_match = re.search(
        r"<!-- legaldesign:composed-content -->(.*?)"
        r"<!-- /legaldesign:composed-content -->",
        html,
        re.DOTALL,
    )
    assert surface_match is not None
    surface = surface_match.group(1)
    assert "Evidence" not in surface
    assert "ld-evidence" not in surface
    assert "data-evidence" not in surface


@pytest.mark.parametrize(
    ("html", "message"),
    [
        (
            '<p><a href="https://example.test/source">Read source</a></p>',
            "surface HTML must not contain links",
        ),
        ("Evidence", "generic disclosure label 'evidence'"),
        ("<p>Evidence</p>", "generic disclosure label 'evidence'"),
        ("<p>View evidence</p>", "generic disclosure label 'view evidence'"),
        ("<p>More detail</p>", "generic disclosure label 'more detail'"),
        (
            "<p>Source: supplied memorandum</p>",
            "contains a Source: row",
        ),
        ("<p>1 of 3</p>", "generic evidence position counter"),
        (
            "<p>Evidence 1 of 3</p><p>Previous</p><p>Next</p>",
            "generic Previous/Next evidence sequence",
        ),
        ('<p class="eyebrow">Question</p>', "forbidden 'eyebrow' chrome"),
        ('<p class="section-kicker">Question</p>', "forbidden 'kicker' chrome"),
        (
            '<p class="evidence-chrome">Supplied</p>',
            "forbidden 'evidence' chrome",
        ),
    ],
)
def test_v3_composed_surface_rejects_generic_disclosure_chrome(
    html: str, message: str
) -> None:
    payload = novel_spec()
    unit = next(item for item in payload["units"] if item["id"] == "a-output")
    unit["variants"]["a"]["html"] = html

    errors = scaffold.validate_spec(payload)

    assert any(message in error for error in errors), errors


def test_v3_composed_surface_rejects_generic_evidence_unit_kind() -> None:
    payload = novel_spec()
    unit = next(item for item in payload["units"] if item["id"] == "a-output")
    unit["kind"] = "evidence"

    errors = scaffold.validate_spec(payload)

    assert any(
        "generic evidence surface units are not allowed" in error for error in errors
    ), errors


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("stage", "Evidence", "generic disclosure label 'evidence'"),
        ("edge", "Source: memorandum", "contains a Source: row"),
    ],
)
def test_v3_component_copy_rejects_generic_disclosure_chrome(
    field: str, value: str, message: str
) -> None:
    payload = novel_spec()
    flow = next(item for item in payload["units"] if item["id"] == "a-flow")
    params = flow["variants"]["a"]["params"]
    if field == "stage":
        params["stages"][0]["title"] = value
    else:
        params["edges"][0] = value

    errors = scaffold.validate_spec(payload)

    assert any(message in error for error in errors), errors


def test_semantic_accent_roles_replace_visual_tint_flags() -> None:
    payload = novel_spec()
    flow = next(item for item in payload["units"] if item["id"] == "a-flow")
    stage = flow["variants"]["a"]["params"]["stages"][0]
    stage["tint"] = True

    errors = scaffold.validate_spec(payload)

    assert any("unknown field 'tint'" in error for error in errors), errors


def test_semantic_accent_role_fails_closed_to_the_named_meanings() -> None:
    payload = novel_spec()
    hierarchy = next(item for item in payload["units"] if item["id"] == "b-hierarchy")
    hierarchy["variants"]["a"]["params"]["branches"][1]["accentRole"] = "outcome"

    errors = scaffold.validate_spec(payload)

    assert any(
        "accentRole" in error and "expected one of" in error for error in errors
    ), errors


@pytest.mark.parametrize(
    "role",
    [
        "open",
        "incomplete",
        "uncovered",
        "recommendation",
        "action",
        "decision",
        "active",
    ],
)
def test_semantic_accent_role_accepts_only_documented_meanings(role: str) -> None:
    payload = novel_spec()
    hierarchy = next(item for item in payload["units"] if item["id"] == "b-hierarchy")
    hierarchy["variants"]["a"]["params"]["branches"][1]["accentRole"] = role

    assert scaffold.validate_spec(payload) == []


@pytest.mark.parametrize(
    "title", ["Evidence", "View evidence", "More detail", "Source"]
)
def test_v3_composed_popups_require_purpose_specific_titles(title: str) -> None:
    payload = novel_spec()
    payload["evidence"][0]["popup"]["title"] = title

    errors = scaffold.validate_spec(payload)

    assert any("expected a purpose-specific title" in error for error in errors), errors


def test_v3_composed_popup_can_be_shared_by_separate_semantic_targets() -> None:
    payload = novel_spec()
    unit = next(item for item in payload["units"] if item["id"] == "a-output")
    unit["detail"] = "e-ask"
    unit["evidence"].append("e-ask")

    assert scaffold.validate_spec(payload) == []


def test_composition_grammar_does_not_change_legacy_v2_contract() -> None:
    payload = json_object(json.loads(LEGACY_V2_SPEC.read_text(encoding="utf-8")))
    payload["units"][0]["variants"]["a"]["html"] = (
        '<p class="eyebrow">Evidence</p>'
        '<a href="https://example.test/source">Source</a>'
    )

    assert scaffold.validate_spec(payload) == []


def test_page_approaches_reject_identical_structural_dimensions() -> None:
    payload = approach_spec()
    mirror_approach_a_into_b(payload)

    errors = scaffold.validate_spec(payload)

    assert errors
    assert any(
        "must use materially different information structures" in error
        for error in errors
    )


def test_page_approaches_reject_near_clone_with_one_moved_box() -> None:
    payload = approach_spec()
    mirror_approach_a_into_b(payload, move_output_only=True)

    errors = scaffold.validate_spec(payload)

    assert any(
        "at least two independent structural dimensions" in error
        and "differences found: placement topology" in error
        for error in errors
    ), errors


def test_each_page_approach_must_carry_the_material_surface_record() -> None:
    payload = approach_spec()
    section = payload["approaches"]["b"]["composition"]["sections"][0]
    section["unitIds"] = ["b-title"]
    section["layout"]["placements"] = [
        {"unitId": "b-title", "row": 1, "column": 1, "span": 12}
    ]
    payload["units"] = [
        unit
        for unit in payload["units"]
        if not unit["id"].startswith("b-") or unit["id"] == "b-title"
    ]

    errors = scaffold.validate_spec(payload)

    assert errors
    assert any(
        error.startswith("$.approaches.b") and "surface claim" in error
        for error in errors
    )


def test_compose_applies_safe_design_md_color_tokens_and_reports_scope(
    tmp_path: Path,
) -> None:
    authority = (ROOT / "skills/core/legaldesign/DESIGN.md").read_text(encoding="utf-8")
    authority = authority.replace("status: unconfigured", "status: configured")
    authority = authority.replace("--red #c92014", "--red #123456")
    design_path = tmp_path / "DESIGN.md"
    design_path.write_text(authority, encoding="utf-8")
    plan = novel_plan()
    plan["style"] = {"source": "design-md", "ref": str(design_path)}
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    spec_output = tmp_path / "artifact.spec.json"
    output = tmp_path / "artifact.html"
    stdout = io.StringIO()

    with redirect_stdout(stdout):
        result = scaffold._command_compose(
            SimpleNamespace(
                plan=plan_path,
                spec_output=spec_output,
                output=output,
                artifact_id="styled-artifact",
            )
        )

    receipt = json.loads(stdout.getvalue())
    html = output.read_text(encoding="utf-8")
    assert result == 0
    assert "--red:#123456" in html
    assert 'html:root,html[data-theme="light"]' in html
    assert 'html[data-theme="dark"]' in html
    assert receipt["styleSource"] == "design-md"
    assert receipt["styleApplication"] == "design-md-palette-roles"
    assert receipt["styleRef"] == str(design_path)

    authority_block = re.search(
        r'<style id="ld-design-authority">(.*?)</style>', html, re.DOTALL
    )
    assert authority_block is not None
    applied = authority_block.group(1)
    assert "--insert:" not in applied
    assert "--scrim:" not in applied
    assert "--shadow-soft:" not in applied
    assert "--shadow:" not in applied


def test_custom_palette_preserves_composed_dom_and_interactions(tmp_path: Path) -> None:
    payload = novel_spec()
    loxoto = scaffold.render_composed_html(payload, "palette-parity")
    authority = (ROOT / "skills/core/legaldesign/DESIGN.md").read_text(encoding="utf-8")
    authority = authority.replace("status: unconfigured", "status: configured")
    authority = authority.replace("--red #c92014", "--red #123456")
    path = tmp_path / "DESIGN.md"
    path.write_text(authority, encoding="utf-8")
    payload["style"] = {"source": "design-md", "ref": str(path)}
    custom_css = scaffold._design_authority_css(payload, tmp_path / "plan.json")
    custom = scaffold.render_composed_html(
        payload, "palette-parity", design_css=custom_css
    )

    def normalize(html: str) -> str:
        html = re.sub(
            r'<style id="ld-design-authority">.*?</style>',
            '<style id="ld-design-authority"></style>',
            html,
            flags=re.DOTALL,
        )
        html = re.sub(
            r'<script id="legaldesign-state" type="application/json">.*?</script>',
            '<script id="legaldesign-state" type="application/json"></script>',
            html,
            flags=re.DOTALL,
        )
        return html

    assert normalize(custom) == normalize(loxoto)


@pytest.mark.parametrize(
    ("replace_from", "replace_to", "message"),
    [
        ("status: unconfigured", "status: unconfigured", "status: configured"),
        ("system: Loxoto", "system: Other", "system: Loxoto"),
        ("scope: palette-only", "scope: full-system", "scope: palette-only"),
        ("Dark: `--bg #000000", "Dark: `--bg #101010", "pure black"),
        ("--red #c92014", "--red #eeeeee", "contrast"),
        ("--faint #666666", "--faint #b0b0b0", "contrast"),
    ],
)
def test_design_md_palette_contract_fails_closed(
    tmp_path: Path, replace_from: str, replace_to: str, message: str
) -> None:
    authority = (ROOT / "skills/core/legaldesign/DESIGN.md").read_text(encoding="utf-8")
    if replace_from != "status: unconfigured":
        authority = authority.replace("status: unconfigured", "status: configured")
    authority = authority.replace(replace_from, replace_to)
    path = tmp_path / "DESIGN.md"
    path.write_text(authority, encoding="utf-8")
    payload = novel_spec()
    payload["style"] = {"source": "design-md", "ref": str(path)}

    with pytest.raises(ValueError, match=message):
        scaffold._design_authority_css(payload, tmp_path / "plan.json")


def test_design_md_rejects_runtime_depth_tokens_as_palette_input(
    tmp_path: Path,
) -> None:
    authority = (ROOT / "skills/core/legaldesign/DESIGN.md").read_text(encoding="utf-8")
    authority = authority.replace("status: unconfigured", "status: configured")
    authority = authority.replace(
        "--tint #f3f3f3`",
        "--tint #f3f3f3 · --shadow #111111`",
        1,
    )
    path = tmp_path / "DESIGN.md"
    path.write_text(authority, encoding="utf-8")
    payload = novel_spec()
    payload["style"] = {"source": "design-md", "ref": str(path)}

    with pytest.raises(ValueError, match="unsupported non-palette tokens: --shadow"):
        scaffold._design_authority_css(payload, tmp_path / "plan.json")


def test_composed_strategy_rejects_template_style_metadata() -> None:
    payload = novel_spec()
    payload["style"] = {"source": "template", "ref": "example.html"}

    errors = scaffold.validate_spec(payload)

    assert any("supports only 'loxoto' or 'design-md'" in error for error in errors)


def embedded_state(html: str) -> JSONObject:
    match = re.search(
        r'<script id="legaldesign-state" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    return json_object(json.loads(match.group(1)))


def test_v3_state_bridge_is_deterministic_lossless_and_schema_valid() -> None:
    spec = novel_spec()

    first = scaffold.state_from_spec(spec, "incident-path")
    second = scaffold.state_from_spec(spec, "incident-path")

    assert first == second
    assert first["savedAt"] is None
    assert first["sourceSchemaVersion"] == "legaldesign.build.v3"
    assert first["approaches"] == spec["approaches"]
    assert first["claims"] == spec["claims"]
    assert first["units"]["a-flow"]["claimRefs"] == [
        "c-input",
        "c-judgment",
        "c-output",
    ]
    assert first["units"]["a-flow"]["variants"]["a"]["encoding"]
    assert first["evidence"]["e-input"]["detail"] == spec["evidence"][0]["detail"]
    assert first["evidence"]["e-input"]["original"] == spec["evidence"][0]["original"]
    assert first["evidence"]["e-input"]["link"] == (
        "https://example.test/legaldesign/method"
    )
    assert first["evidence"]["e-input"]["excerpt"] == spec["evidence"][0]["detail"]
    assert first["evidence"]["e-input"]["popup"] == spec["evidence"][0]["popup"]
    state_schema = json.loads(
        (ROOT / "skills/core/legaldesign/schemas/state.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert validate_json_schema(first, state_schema, state_schema) == []


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload["approaches"]["a"]["composition"]["sections"][
                0
            ].pop("layout"),
            "missing required field 'layout'",
        ),
        (
            lambda payload: payload["approaches"]["a"]["composition"]["sections"][0][
                "layout"
            ]["placements"].pop(),
            "unit IDs must exactly match",
        ),
        (
            lambda payload: payload["approaches"]["a"]["composition"]["sections"][0][
                "layout"
            ]["placements"][0].update({"column": 10, "span": 5}),
            "exceeds 12 columns",
        ),
        (
            lambda payload: payload["approaches"]["a"]["composition"]["sections"][0][
                "layout"
            ]["placements"][1].update({"row": 1, "column": 1}),
            "overlaps",
        ),
    ],
)
def test_composition_placement_validation(mutate: JSONMutator, message: str) -> None:
    payload = novel_spec()
    mutate(payload)

    errors = scaffold.validate_spec(payload)

    assert any(message in error for error in errors), errors


def row_span_layout() -> JSONObject:
    return {
        "columns": 12,
        "placements": [
            {"unitId": "title", "row": 1, "column": 1, "span": 12},
            {"unitId": "finding", "row": 2, "column": 1, "span": 4},
            {"unitId": "consequence", "row": 3, "column": 1, "span": 4},
            {"unitId": "recommendation", "row": 4, "column": 1, "span": 4},
            {"unitId": "timeline", "row": 2, "column": 5, "span": 8, "rowSpan": 3},
        ],
    }


def row_span_errors(layout: JSONObject) -> list[str]:
    errors: list[str] = []
    scaffold._check_section_layout(
        layout,
        unit_ids=[item["unitId"] for item in layout["placements"]],
        path="layout",
        errors=errors,
    )
    return errors


def test_row_span_places_tall_figure_beside_three_cards() -> None:
    layout = row_span_layout()
    assert row_span_errors(layout) == []
    layout["placements"].reverse()
    assert row_span_errors(layout) == [], "placement order cannot change occupancy"


@pytest.mark.parametrize("reverse", [False, True])
def test_row_span_checks_overlap_beyond_its_first_row(reverse: bool) -> None:
    layout = row_span_layout()
    layout["placements"][3].update({"column": 4, "span": 2})
    if reverse:
        layout["placements"].reverse()
    errors = row_span_errors(layout)
    assert any("overlaps" in error and "row 4, column 5" in error for error in errors)


@pytest.mark.parametrize("value", [0, -1, 13, 1.5, True, "3", None])
def test_row_span_rejects_invalid_or_unbounded_capacity(value: object) -> None:
    layout = row_span_layout()
    layout["placements"][-1]["rowSpan"] = value
    assert any("rowSpan" in error for error in row_span_errors(layout))


def test_row_span_default_and_maximum_preserve_existing_behavior() -> None:
    unit = novel_spec()["units"][0]
    implicit = scaffold._render_unit(unit, row=1, column=1, span=12)
    explicit = scaffold._render_unit(unit, row=1, column=1, span=12, row_span=1)
    assert implicit == explicit
    assert "--ld-row-span" not in implicit
    layout = row_span_layout()
    layout["placements"][-1]["rowSpan"] = 12
    assert row_span_errors(layout) == []


def test_row_span_survives_spec_state_and_composition_rendering() -> None:
    payload = novel_spec()
    section = payload["approaches"]["a"]["composition"]["sections"][1]
    section["layout"]["placements"][0]["rowSpan"] = 3
    section["layout"]["placements"][1]["row"] = 4
    assert scaffold.validate_spec(payload) == []
    schema = json.loads(
        (ROOT / "skills/core/legaldesign/schemas/build-spec.schema.json").read_text()
    )
    assert validate_json_schema(payload, schema, schema) == []
    state = scaffold.state_from_spec(payload, "row-span-example")
    assert state["approaches"] == payload["approaches"]
    markup = scaffold._render_composition(
        payload, payload["approaches"]["a"]["composition"], "a"
    )
    assert 'style="--ld-row:1;--ld-column:1;--ld-span:12;--ld-row-span:3"' in markup
    assert markup.index('data-unit="a-flow"') < markup.index('data-unit="a-output"')


@pytest.mark.parametrize("count", [3, 4, 5])
def test_explicit_vertical_timeline_allows_five_columns_without_weakening_horizontal(
    count: int,
) -> None:
    params = {"marks": [{} for _ in range(count)]}
    unit = {"variants": {"a": {"component": "timeline", "params": params}}}
    expected_horizontal = 10 if count >= 4 else 8
    assert scaffold._component_minimum_span(unit) == expected_horizontal
    params["orientation"] = "horizontal"
    assert scaffold._component_minimum_span(unit) == expected_horizontal
    params["orientation"] = "vertical"
    assert scaffold._component_minimum_span(unit) == 5


def test_composition_section_ids_must_be_unique() -> None:
    payload = novel_spec()
    sections = payload["approaches"]["a"]["composition"]["sections"]
    sections.append(copy.deepcopy(sections[0]))

    errors = scaffold.validate_spec(payload)

    assert any("duplicate section ID 'a-overview'" in error for error in errors)


def test_inert_fragment_allowlist_accepts_copy_and_rejects_execution() -> None:
    assert (
        scaffold.sanitize_html_fragment(
            '<p class="lead"><strong>Answer.</strong> Safe &amp; inert.</p>'
        )
        == '<p class="lead"><strong>Answer.</strong> Safe &amp; inert.</p>'
    )
    with pytest.raises(ValueError, match="tag <script>"):
        scaffold.sanitize_html_fragment("<script>alert(1)</script>")
    with pytest.raises(ValueError, match="attribute 'onerror'"):
        scaffold.sanitize_html_fragment('<span onerror="alert(1)">No</span>')
    with pytest.raises(ValueError, match=r"HTTP\(S\)"):
        scaffold.sanitize_html_fragment('<a href="javascript:alert(1)">No</a>')


def test_v3_decision_unit_renders_and_persists_response_contract() -> None:
    payload = novel_spec()
    decision = next(unit for unit in payload["units"] if unit["id"] == "a-summary")
    make_decision_unit(decision)

    assert scaffold.validate_spec(payload) == []
    html = scaffold.render_composed_html(payload, "incident-decision")
    state = embedded_state(html)
    assert 'data-kind="decision"' in html
    assert 'data-decision-option value="A"' in html
    assert "data-decision-custom" in html
    assert "data-decision-note" in html
    assert state["units"]["a-summary"]["selection_mode"] == "single"
    assert state["units"]["a-summary"]["options"][0]["key"] == "A"
    assert state["review"]["decisions"] == {}


def test_v3_decision_unit_rejects_unit_level_popup_target() -> None:
    payload = novel_spec()
    decision = next(unit for unit in payload["units"] if unit["id"] == "a-summary")
    make_decision_unit(decision)
    decision["detail"] = "e-input"

    errors = scaffold.validate_spec(payload)

    assert any(
        "$.units[1].detail: a decision unit must not use a unit-level popup target"
        in error
        for error in errors
    ), errors


def test_compose_rolls_back_spec_when_html_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_path = tmp_path / "artifact.plan.json"
    plan_path.write_text(json.dumps(novel_plan()), encoding="utf-8")
    spec_output = tmp_path / "artifact.spec.json"
    html_output = tmp_path / "artifact.html"

    def fail_write(path: Path, value: str) -> None:
        raise OSError("simulated HTML write failure")

    monkeypatch.setattr(scaffold, "_write_text_new", fail_write)
    with pytest.raises(OSError, match="simulated"):
        scaffold._command_compose(
            SimpleNamespace(
                plan=plan_path,
                spec_output=spec_output,
                output=html_output,
                artifact_id="artifact",
            )
        )

    assert not spec_output.exists()
    assert not html_output.exists()


def test_compose_does_not_render_an_explicit_template_import(tmp_path: Path) -> None:
    plan = novel_plan()
    plan["approaches"]["a"]["composition"]["strategy"] = "template-import"
    plan["approaches"]["a"]["composition"]["templateRef"] = "stacked-explainer"
    plan_path = tmp_path / "template-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ValueError, match="use init --template"):
        scaffold._command_compose(
            SimpleNamespace(
                plan=plan_path,
                spec_output=tmp_path / "template.spec.json",
                output=tmp_path / "template.html",
                artifact_id="template-import",
            )
        )


def test_one_page_init_does_not_choose_stacked_explainer(tmp_path: Path) -> None:
    spec_output = tmp_path / "one-page.spec.json"
    stdout = io.StringIO()

    with redirect_stdout(stdout):
        result = scaffold._command_init(
            SimpleNamespace(
                form="one-page",
                spec_output=spec_output,
                template=None,
                output=None,
            )
        )

    payload = json.loads(spec_output.read_text(encoding="utf-8"))
    receipt = json.loads(stdout.getvalue())
    assert result == 0
    assert payload["schemaVersion"] == "legaldesign.build.v4"
    assert "approaches" not in payload
    assert payload["composition"]["strategy"] == "composed"
    assert payload["composition"]["templateRef"] is None
    assert "overview" in payload
    assert receipt["sourceAsset"] is None
    assert receipt["output"] is None


def test_initialized_spec_can_explicitly_import_legacy_v3_plan(tmp_path: Path) -> None:
    plan_path = tmp_path / "initialized-plan.json"
    with redirect_stdout(io.StringIO()):
        result = scaffold._command_init(
            SimpleNamespace(
                form="one-page",
                spec_output=plan_path,
                template=None,
                output=None,
            )
        )

    initialized = json_object(json.loads(plan_path.read_text(encoding="utf-8")))
    assert result == 0
    assert initialized["schemaVersion"] == "legaldesign.build.v4"
    initialized.pop("composition")
    initialized.pop("overview")
    initialized.update(novel_spec())
    plan_path.write_text(json.dumps(initialized), encoding="utf-8")

    spec_output = tmp_path / "composed.spec.json"
    html_output = tmp_path / "composed.html"
    with redirect_stdout(io.StringIO()):
        compose_result = scaffold._command_compose(
            SimpleNamespace(
                plan=plan_path,
                spec_output=spec_output,
                output=html_output,
                artifact_id="initialized-plan",
            )
        )

    assert compose_result == 0
    assert (
        scaffold.validate_spec(json.loads(spec_output.read_text(encoding="utf-8")))
        == []
    )
    assert "data-composed-shell" in html_output.read_text(encoding="utf-8")


def test_compose_rejects_an_unsupported_plan_schema_version(tmp_path: Path) -> None:
    plan = novel_spec()
    plan["schemaVersion"] = "legaldesign.build.v5"
    plan_path = tmp_path / "unsupported-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported composition plan schemaVersion"):
        scaffold._command_compose(
            SimpleNamespace(
                plan=plan_path,
                spec_output=tmp_path / "unsupported.spec.json",
                output=tmp_path / "unsupported.html",
                artifact_id="unsupported",
            )
        )


def test_template_copy_requires_explicit_template_opt_in(tmp_path: Path) -> None:
    expected = json.loads(TEMPLATE_EXPECTED.read_text(encoding="utf-8"))
    spec_output = tmp_path / "import.spec.json"
    html_output = tmp_path / "import.html"
    stdout = io.StringIO()

    with redirect_stdout(stdout):
        result = scaffold._command_init(
            SimpleNamespace(
                form=expected["form"],
                spec_output=spec_output,
                template=expected["template"],
                output=html_output,
            )
        )

    payload = json.loads(spec_output.read_text(encoding="utf-8"))
    receipt = json.loads(stdout.getvalue())
    source = (
        ROOT
        / "skills"
        / "core"
        / "legaldesign"
        / "assets"
        / "templates"
        / expected["sourceAsset"]
    )
    assert result == 0
    assert payload["schemaVersion"] == "legaldesign.build.v4"
    assert "approaches" not in payload
    assert payload["composition"]["strategy"] == expected["strategy"]
    assert payload["composition"]["templateRef"] == expected["template"]
    assert html_output.read_bytes() == source.read_bytes()
    assert Path(receipt["sourceAsset"]).name == expected["sourceAsset"]


def test_html_output_without_template_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit --template"):
        scaffold._command_init(
            SimpleNamespace(
                form="one-page",
                spec_output=tmp_path / "spec.json",
                template=None,
                output=tmp_path / "artifact.html",
            )
        )


def test_materially_rich_record_rejects_one_sentence_surface() -> None:
    payload = novel_spec()
    claims = payload["claims"]
    assert isinstance(claims, list)
    for claim in claims[1:]:
        claim["placement"] = "detail"

    errors = scaffold.validate_spec(payload)

    assert any("one-sentence treatment is too thin" in error for error in errors)


def test_v3_variant_requires_technical_encoding() -> None:
    payload = novel_spec()
    units = payload["units"]
    assert isinstance(units, list)
    del units[0]["variants"]["a"]["encoding"]

    errors = scaffold.validate_spec(payload)

    assert any("missing required field 'encoding'" in error for error in errors)


def test_surface_claim_evidence_must_be_reachable_from_carrying_unit() -> None:
    payload = novel_spec()
    units = payload["units"]
    assert isinstance(units, list)
    next(unit for unit in units if unit["id"] == "a-summary")["evidence"] = [
        "e-judgment",
        "e-output",
    ]

    errors = scaffold.validate_spec(payload)

    assert any(
        "surface claim 'c-input' requires reachable evidence IDs ['e-input']" in error
        for error in errors
    )


def test_detail_material_claim_evidence_must_be_reachable_from_surface() -> None:
    payload = novel_spec()
    next(claim for claim in payload["claims"] if claim["id"] == "c-judgment")[
        "placement"
    ] = "detail"
    units = payload["units"]
    assert isinstance(units, list)
    judgment_evidence = {
        item["id"] for item in payload["evidence"] if "c-judgment" in item["claimRefs"]
    }
    for unit in units:
        unit["evidence"] = [
            evidence_id
            for evidence_id in unit["evidence"]
            if evidence_id not in judgment_evidence
        ]

    errors = scaffold.validate_spec(payload)

    assert any(
        "$.claims['c-judgment']: presented material claim has no evidence path "
        "reachable from a surface unit" in error
        for error in errors
    )


def test_material_claim_evidence_requires_an_actual_target_in_each_approach() -> None:
    payload = novel_spec()
    assert any(unit.get("evidence") for unit in payload["units"])
    remove_component_detail_params(payload)

    errors = scaffold.validate_spec(payload)

    expected = {
        ("a", "c-input"),
        ("a", "c-judgment"),
        ("b", "c-input"),
        ("b", "c-judgment"),
        ("b", "c-output"),
    }
    for approach, claim_id in expected:
        assert any(
            f"$.approaches.{approach}: presented material claim {claim_id!r} "
            "has no actual popup target for its evidence within this approach" in error
            for error in errors
        ), (approach, claim_id, errors)


def test_justified_omission_does_not_require_an_approach_popup_target() -> None:
    payload = novel_spec()
    claim = next(item for item in payload["claims"] if item["id"] == "c-judgment")
    claim["placement"] = "omitted"
    claim["omissionReason"] = "The client-facing page excludes internal method detail."
    omitted_evidence = {
        item["id"] for item in payload["evidence"] if "c-judgment" in item["claimRefs"]
    }

    def remove_omitted_targets(value: object) -> None:
        if isinstance(value, dict):
            for key in list(value):
                child = value[key]
                if (
                    isinstance(key, str)
                    and key.casefold().endswith("detail")
                    and child in omitted_evidence
                ):
                    del value[key]
                else:
                    remove_omitted_targets(child)
        elif isinstance(value, list):
            for item in value:
                remove_omitted_targets(item)

    for unit in payload["units"]:
        unit["claimRefs"] = [
            claim_id for claim_id in unit["claimRefs"] if claim_id != "c-judgment"
        ]
        for variant in unit["variants"].values():
            if "component" in variant:
                remove_omitted_targets(variant.get("params"))

    assert scaffold.validate_spec(payload) == []


@pytest.mark.parametrize("purpose", ["decide", "choose"])
def test_decide_and_choose_require_action_even_for_one_material_claim(
    purpose: str,
) -> None:
    payload = novel_spec()
    brief = payload["brief"]
    claims = payload["claims"]
    units = payload["units"]
    assert isinstance(brief, dict)
    assert isinstance(claims, list)
    assert isinstance(units, list)
    brief["purpose"] = purpose
    for claim in claims:
        if claim["kind"] == "material" and claim["id"] != "c-input":
            claim["kind"] = "context"
    for unit in units:
        if unit["id"] in {"a-summary", "b-summary"}:
            unit["role"] = "action"

    assert scaffold.validate_spec(payload) == []

    for unit in units:
        if unit.get("role") == "action":
            unit["role"] = "answer"
    errors = scaffold.validate_spec(payload)

    assert any(
        f"purpose {purpose!r} requires an action unit" in error for error in errors
    )


@pytest.mark.parametrize("role", ["summary", "answer"])
def test_understand_requires_summary_or_answer_surface(role: str) -> None:
    payload = novel_spec()
    brief = payload["brief"]
    units = payload["units"]
    assert isinstance(brief, dict)
    assert isinstance(units, list)
    brief["purpose"] = "understand"
    for unit in units:
        if unit["id"] in {"a-summary", "b-summary"}:
            unit["role"] = role

    assert scaffold.validate_spec(payload) == []

    for unit in units:
        if unit.get("role") in {"summary", "answer"}:
            unit["role"] = "finding"
    errors = scaffold.validate_spec(payload)

    assert any(
        "purpose 'understand' requires a summary or answer unit" in error
        for error in errors
    )


def test_presented_material_claim_requires_popup_and_original_state() -> None:
    payload = copy.deepcopy(novel_spec())
    evidence = payload["evidence"]
    assert isinstance(evidence, list)
    del evidence[0]["original"]

    errors = scaffold.validate_spec(payload)

    assert any("missing required field 'original'" in error for error in errors)


def test_v3_evidence_requires_purpose_specific_popup_content() -> None:
    payload = novel_spec()
    del payload["evidence"][0]["popup"]

    errors = scaffold.validate_spec(payload)

    assert any("missing required field 'popup'" in error for error in errors)


def test_v3_popup_requires_at_least_one_structured_section() -> None:
    payload = novel_spec()
    payload["evidence"][0]["popup"]["sections"] = []

    errors = scaffold.validate_spec(payload)

    assert any(
        "popup.sections: expected at least 1 item" in error for error in errors
    ), errors


def test_evidence_grounded_card_requires_one_whole_card_detail_target() -> None:
    payload = novel_spec()
    unit = next(item for item in payload["units"] if item["id"] == "a-output")
    del unit["detail"]

    errors = scaffold.validate_spec(payload)

    assert any(
        "an evidence-grounded card must open one purpose-specific popup" in error
        for error in errors
    )


@pytest.mark.parametrize("href", ["javascript:alert(1)", "records/source.pdf"])
def test_linked_original_rejects_unsafe_or_relative_href(href: str) -> None:
    payload = novel_spec()
    payload["evidence"][0]["original"]["href"] = href

    errors = scaffold.validate_spec(payload)

    assert any(
        "$.evidence[0].original.href: expected an absolute HTTP(S) URL" in error
        for error in errors
    )


def test_linked_original_accepts_absolute_https_href() -> None:
    payload = novel_spec()
    payload["evidence"][0]["original"]["href"] = (
        "https://records.example.test/source.pdf"
    )

    assert scaffold.validate_spec(payload) == []
