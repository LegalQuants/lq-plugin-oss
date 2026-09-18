from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
definition = importlib.util.spec_from_file_location(
    "card_hub_scaffold", ROOT / "skills/core/legaldesign/scripts/scaffold.py"
)
assert definition and definition.loader
scaffold = importlib.util.module_from_spec(definition)
definition.loader.exec_module(scaffold)


def plan():
    return json.loads(
        (ROOT / "packages/legaldesign/templates/card-hub.plan.json").read_text()
    )


def test_card_hub_has_one_copy_of_every_unit_and_one_framing_card():
    spec = plan()
    assert scaffold.validate_spec(spec) == []
    html = scaffold.render_composed_html(spec, "hub-test")
    assert html.count('class="ld-hub-intro"') == 1
    for unit in spec["units"]:
        assert html.count(f'data-unit="{unit["id"]}"') == 1
    state = scaffold.state_from_spec(spec, "hub-test")
    assert state["composition"]["sections"][0]["presentation"] == "card-hub"


@pytest.mark.parametrize(
    "case",
    ["wrong-form", "wrong-count", "intro-row", "foreign-row", "order", "bad-layout"],
)
def test_card_hub_rejects_incompatible_geometry(case):
    spec = plan()
    section = spec["composition"]["sections"][0]
    if case == "wrong-form":
        spec["brief"]["form"] = "slide-brief"
    elif case == "wrong-count":
        next(unit for unit in spec["units"] if unit["id"] == "point-1")["kind"] = "text"
    elif case == "intro-row":
        section["layout"]["placements"][1]["row"] = 6
    elif case == "foreign-row":
        section["layout"]["placements"][-1]["row"] = 2
    elif case == "order":
        section["unitIds"][1:3] = reversed(section["unitIds"][1:3])
    else:
        section["layout"] = None
    assert scaffold.validate_spec(spec)
