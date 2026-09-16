"""Grouped v4 overviews preserve typed navigation and one semantic reading order."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest
from public_contract import validate_json_schema

ROOT = Path(__file__).resolve().parents[4]
SKILL = ROOT / "skills/core/legaldesign"
FIXTURE_MODULE = importlib.util.spec_from_file_location(
    "legaldesign_grouped_fixture",
    ROOT / "packages/skill-tests/tests/legaldesign/test_scaffold_single_output.py",
)
assert FIXTURE_MODULE is not None and FIXTURE_MODULE.loader is not None
fixtures = importlib.util.module_from_spec(FIXTURE_MODULE)
FIXTURE_MODULE.loader.exec_module(fixtures)
scaffold = fixtures.scaffold


def grouped_spec(topic_count: int = 3) -> dict:
    spec = fixtures.single_spec("slide-brief")
    first = spec["composition"]["sections"][0]
    topic = next(unit for unit in spec["units"] if unit["id"] == "consent-topic")
    detail = next(unit for unit in spec["units"] if unit["id"] == "consent-detail")
    for index in range(1, topic_count):
        topic_id, detail_id, section_id = (
            f"topic-{index}",
            f"detail-{index}",
            f"section-{index}",
        )
        extra_topic, extra_detail = copy.deepcopy(topic), copy.deepcopy(detail)
        extra_topic["id"], extra_detail["id"] = topic_id, detail_id
        spec["units"].extend([extra_topic, extra_detail])
        first["unitIds"].append(topic_id)
        first["layout"]["placements"].append(
            {"unitId": topic_id, "row": index + 5, "column": 1, "span": 12}
        )
        section = copy.deepcopy(spec["composition"]["sections"][1])
        section.update(id=section_id, unitIds=[detail_id])
        section["layout"]["placements"][0]["unitId"] = detail_id
        spec["composition"]["sections"].append(section)
        spec["overview"]["topics"].append(
            {"unitId": topic_id, "targetSectionId": section_id}
        )
    topic_ids = [topic["unitId"] for topic in spec["overview"]["topics"]]
    spec["overview"]["groups"] = [
        {"label": "Permissions and scope", "topicUnitIds": topic_ids[:2]},
        {"label": 'Delivery <and> "support"', "topicUnitIds": topic_ids[2:]},
    ]
    return spec


def move_overview_unit(spec: dict, unit_id: str, index: int) -> None:
    ids = spec["composition"]["sections"][0]["unitIds"]
    ids.remove(unit_id)
    ids.insert(index, unit_id)


def assert_schema_result(spec: dict, state: dict, *, valid: bool) -> None:
    script = """
import Ajv from './packages/pluginctl/node_modules/ajv/dist/2020.js';
import {readFileSync} from 'node:fs';
const values = JSON.parse(readFileSync(0, 'utf8'));
const results = ['build-spec', 'state'].map((name, index) => {
  const schema = JSON.parse(readFileSync(
    `skills/core/legaldesign/schemas/${name}.schema.json`, 'utf8'));
  const validate = new Ajv({strict: false}).compile(schema);
  const valid = validate(values[index]);
  return {valid, errors: validate.errors};
});
process.stdout.write(JSON.stringify(results));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        input=json.dumps([spec, state]),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for name, value, report in zip(
        ["build-spec", "state"], [spec, state], json.loads(result.stdout), strict=True
    ):
        assert report["valid"] == valid, report["errors"]
        schema = json.loads(
            (SKILL / f"schemas/{name}.schema.json").read_text(encoding="utf-8")
        )
        errors = validate_json_schema(value, schema, schema)
        assert (not errors) == valid, errors


class GroupDOM(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, str | None]] = []
        self.groups: list[dict[str, str | None]] = []
        self.wrappers: list[dict[str, str | None]] = []
        self.units: list[tuple[dict, dict]] = []
        self.labels: list[str] = []
        self.counts: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()
        if "ld-overview-group" in classes:
            self.groups.append(attributes)
        if "ld-overview-groups" in classes:
            assert self.stack[-1].get("class") == "ld-composed-grid"
            self.wrappers.append(attributes)
        if "data-unit" in attributes:
            self.units.append((attributes, self.stack[-1]))
        if tag not in {"br", "hr", "img", "input", "meta", "link"}:
            self.stack.append(attributes)

    def handle_endtag(self, tag) -> None:
        self.stack.pop()

    def handle_data(self, data) -> None:
        if not self.stack:
            return
        if "data-overview-group-label" in self.stack[-1]:
            self.labels.append(data)
        if self.stack[-1].get("class") == "ld-overview-group-count":
            self.counts.append(data)


@pytest.mark.parametrize("form", ["one-page", "slide-brief"])
def test_flat_overviews_are_unchanged(form: str) -> None:
    spec = fixtures.single_spec(form)
    assert scaffold.validate_spec(spec) == []
    state = scaffold.state_from_spec(spec, "flat-overview")
    assert "groups" not in state["overview"]
    assert_schema_result(spec, state, valid=True)
    rendered = scaffold._render_approaches(spec)
    assert "ld-overview-group" not in rendered
    if form == "slide-brief":
        assert 'data-section-target="consent"' in rendered


def test_grouped_overview_preserves_state_and_nested_navigation_order() -> None:
    spec = grouped_spec()
    assert scaffold.validate_spec(spec) == []
    state = scaffold.state_from_spec(spec, "grouped-overview")
    assert state["overview"] == spec["overview"]
    assert state["overview"]["groups"] is not spec["overview"]["groups"]
    assert_schema_result(spec, state, valid=True)
    rendered = scaffold._render_approaches(spec)
    dom = GroupDOM()
    dom.feed(rendered)
    assert len(dom.wrappers) == 1
    assert dom.wrappers[0]["style"] == "--ld-row:5;--ld-column:1;--ld-span:12"
    assert [group["data-overview-group"] for group in dom.groups] == ["0", "1"]
    assert ["open" in group for group in dom.groups] == [True, False]
    assert dom.labels == [group["label"] for group in spec["overview"]["groups"]]
    assert dom.counts == ["2 topics", "1 topic"]
    assert "Delivery &lt;and&gt; &quot;support&quot;" in rendered
    assert "Delivery <and>" not in rendered
    targets = {
        topic["unitId"]: topic["targetSectionId"]
        for topic in spec["overview"]["topics"]
    }
    grouped = [
        attributes
        for attributes, parent in dom.units
        if parent.get("class") == "ld-overview-topic-grid"
    ]
    assert [unit["data-unit"] for unit in grouped] == list(targets)
    assert all(
        unit["data-section-target"] == targets[unit["data-unit"]] for unit in grouped
    )
    assert all(unit["role"] == "button" and unit["tabindex"] == "0" for unit in grouped)
    assert len(dom.units) == len(spec["units"])
    assert all(
        attributes["data-unit"] not in targets
        for attributes, parent in dom.units
        if parent.get("class") == "ld-composed-grid"
    )


def test_late_authored_topic_rows_do_not_create_outer_grid_tracks() -> None:
    spec = grouped_spec()
    first = spec["composition"]["sections"][0]
    first["layout"]["placements"][-1].update(row=999, column=2, span=5)
    assert scaffold.validate_spec(spec) == []
    dom = GroupDOM()
    dom.feed(scaffold._render_approaches(spec))
    assert dom.wrappers[0]["style"] == "--ld-row:5;--ld-column:1;--ld-span:12"
    assert not any(
        "--ld-row:999" in attributes.get("style", "")
        for attributes, parent in dom.units
        if parent.get("class") == "ld-composed-grid"
    )
    nested = next(
        attributes
        for attributes, _ in dom.units
        if attributes["data-unit"] == "topic-2"
    )
    assert "--ld-row:999" in nested["style"]


def test_full_html_build_round_trips_grouped_navigation_without_extra_units() -> None:
    spec = grouped_spec()
    html = scaffold.render_composed_html(spec, "grouped-full-build")
    match = re.search(
        r'<script[^>]*id="legaldesign-state"[^>]*>(.*?)</script>', html, re.S
    )
    assert match is not None
    state = json.loads(match.group(1))
    assert state["overview"] == spec["overview"]
    assert set(state["units"]) == {unit["id"] for unit in spec["units"]}
    assert 'class="ld-overview-groups"' in html
    assert 'data-overview-group="0" open' in html
    assert_schema_result(spec, state, valid=True)


@pytest.mark.parametrize(
    "groups",
    [
        None,
        {},
        [],
        [None],
        [{"label": "X", "topicUnitIds": ["consent-topic"]}] * 13,
        [{"topicUnitIds": ["consent-topic"]}],
        [{"label": "", "topicUnitIds": ["consent-topic"]}],
        [{"label": "   ", "topicUnitIds": ["consent-topic"]}],
        [{"label": "X" * 49, "topicUnitIds": ["consent-topic"]}],
        [{"label": 1, "topicUnitIds": ["consent-topic"]}],
        [{"label": "X"}],
        [{"label": "X", "topicUnitIds": []}],
        [{"label": "X", "topicUnitIds": "consent-topic"}],
        [{"label": "X", "topicUnitIds": [""]}],
        [{"label": "X", "topicUnitIds": [1]}],
        [{"label": "X", "topicUnitIds": ["consent-topic", "consent-topic"]}],
        [{"label": "X", "topicUnitIds": ["consent-topic"], "html": "<script>"}],
    ],
)
def test_group_shape_is_checked_by_scaffold_and_both_schemas(groups) -> None:
    spec = grouped_spec()
    state = scaffold.state_from_spec(spec, "grouped-shape")
    spec["overview"]["groups"] = copy.deepcopy(groups)
    state["overview"]["groups"] = copy.deepcopy(groups)
    assert scaffold.validate_spec(spec)
    assert_schema_result(spec, state, valid=False)


def test_groups_require_slide_brief_even_with_one_page_topology() -> None:
    spec = fixtures.single_spec("one-page")
    state = scaffold.state_from_spec(spec, "grouped-one-page")
    groups = [{"label": "Not permitted", "topicUnitIds": ["title"]}]
    spec["overview"]["groups"] = copy.deepcopy(groups)
    state["overview"]["groups"] = copy.deepcopy(groups)
    assert any(
        "requires slide-brief" in error for error in scaffold.validate_spec(spec)
    )
    assert_schema_result(spec, state, valid=False)


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda spec: spec["overview"]["groups"].pop(), "every topic must be grouped"),
        (
            lambda spec: spec["overview"]["groups"][1]["topicUnitIds"].append(
                "consent-topic"
            ),
            "exactly one group",
        ),
        (
            lambda spec: spec["overview"]["groups"][1].update(topicUnitIds=["facts"]),
            "non-topic unit",
        ),
        (
            lambda spec: spec["overview"]["groups"][1].update(topicUnitIds=["missing"]),
            "non-topic unit",
        ),
        (
            lambda spec: spec["overview"]["groups"].reverse(),
            "exactly match the trailing",
        ),
        (
            lambda spec: spec["overview"]["groups"][0]["topicUnitIds"].reverse(),
            "exactly match the trailing",
        ),
        (
            lambda spec: move_overview_unit(spec, "title", 999),
            "exactly match the trailing",
        ),
        (
            lambda spec: move_overview_unit(spec, "facts", 5),
            "must precede grouped topics",
        ),
        (
            lambda spec: spec["composition"]["sections"][0]["layout"]["placements"][
                4
            ].update(span=6),
            "column 1, span 12",
        ),
        (
            lambda spec: spec["composition"]["sections"][0]["layout"]["placements"][
                4
            ].update(column=2, span=11),
            "column 1, span 12",
        ),
        (
            lambda spec: spec["composition"]["sections"][0]["layout"][
                "placements"
            ].pop(),
            "unit IDs must exactly match",
        ),
        (
            lambda spec: spec["composition"]["sections"][0]["layout"]["placements"][
                -1
            ].update(row=5),
            "overlaps",
        ),
    ],
)
def test_group_membership_order_and_layout_fail_closed(mutate, expected: str) -> None:
    spec = grouped_spec()
    mutate(spec)
    errors = scaffold.validate_spec(spec)
    assert any(expected in error for error in errors), errors


def test_twelve_nonempty_groups_are_supported() -> None:
    spec = grouped_spec(12)
    spec["overview"]["groups"] = [
        {"label": f"Group {index + 1}", "topicUnitIds": [topic["unitId"]]}
        for index, topic in enumerate(spec["overview"]["topics"])
    ]
    assert scaffold.validate_spec(spec) == []
    state = scaffold.state_from_spec(spec, "twelve-groups")
    assert_schema_result(spec, state, valid=True)
    dom = GroupDOM()
    dom.feed(scaffold._render_approaches(spec))
    assert len(dom.groups) == 12 and sum("open" in group for group in dom.groups) == 1
