from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "skills" / "core" / "legaldesign" / "scripts" / "scaffold.py"
SPEC = importlib.util.spec_from_file_location("legaldesign_template_check", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
scaffold = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scaffold
SPEC.loader.exec_module(scaffold)

TEMPLATES = [
    {
        "source_asset": f"{name}.html",
        "path": f"skills/core/legaldesign/assets/templates/{name}.template.html",
    }
    for name in (
        "stacked-explainer",
        "slide-brief",
        "diligence-report",
        "method-map",
        "card-hub",
    )
]


@pytest.mark.parametrize("entry", TEMPLATES, ids=lambda entry: entry["source_asset"])
def test_shipped_template_passes_template_check(entry: dict[str, str]) -> None:
    args = SimpleNamespace(path=ROOT / entry["path"], asset=entry["source_asset"])
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = scaffold._command_template_check(args)
    assert result == 0, stdout.getvalue() + stderr.getvalue()


@pytest.mark.parametrize("entry", TEMPLATES, ids=lambda entry: entry["source_asset"])
def test_template_blueprint_is_current_and_has_one_overview_led_composition(entry):
    name = Path(entry["source_asset"]).stem
    blueprint = ROOT / "packages/legaldesign/templates" / f"{name}.plan.json"
    plan = json.loads(blueprint.read_text(encoding="utf-8"))
    assert plan["schemaVersion"] == "legaldesign.build.v4"
    assert scaffold.validate_spec(plan) == []
    assert "approaches" not in plan
    minimum_pages = {"slide-brief": 3, "diligence-report": 4}.get(name, 1)
    sections = plan["composition"]["sections"]
    assert len(sections) >= minimum_pages
    assert plan["overview"]["sectionId"] == sections[0]["id"]
    assert len(plan["overview"]["topics"]) == len(sections) - 1
    if plan["brief"]["form"] == "one-page":
        assert len(sections) == 1
    assert all(set(unit["variants"]) == {"a"} for unit in plan["units"])
    if name == "diligence-report":
        assert any(unit.get("role") == "finding" for unit in plan["units"])
    if name == "method-map":
        figures = {
            unit["variants"]["a"].get("component")
            for unit in plan["units"]
            if unit["kind"] == "figure"
        }
        assert figures == {"flow"}


@pytest.mark.parametrize("entry", TEMPLATES, ids=lambda entry: entry["source_asset"])
def test_shipped_template_retains_single_composition_and_shared_runtime(entry):
    html = (ROOT / entry["path"]).read_text(encoding="utf-8")
    match = re.search(
        r'<script[^>]*id="legaldesign-state"[^>]*>(.*?)</script>', html, re.S
    )
    assert match is not None
    state = json.loads(match.group(1))
    assert state["sourceSchemaVersion"] == "legaldesign.build.v4"
    assert "approaches" not in state
    assert "approach" not in state["review"]
    assert state["composition"]["sections"]
    assert state["overview"]["sectionId"] == state["composition"]["sections"][0]["id"]
    assert all(set(unit["variants"]) == {"a"} for unit in state["units"].values())
    for script_id in ("ld-runtime", "ld-client-runtime", "ld-components", "ld-tokens"):
        assert f'id="{script_id}"' in html
    payload = re.search(
        r'<script id="ld-client-runtime" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    assert payload is not None
    reader = json.loads(payload.group(1))
    assert isinstance(reader, str)
    assert not re.search(
        r"showSaveFilePicker|createWritable|persistHTML|\.download\s*=", reader
    )
    surface = re.sub(
        r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>", "", html, flags=re.S
    )
    assert 'id="ld-page-approach"' not in surface
    assert 'data-approach="b"' not in surface
    for topic in state["overview"]["topics"]:
        assert f'data-section-target="{topic["targetSectionId"]}"' in surface
    assert not re.search(r'class="[^"]*(?:eyebrow|kicker)[^"]*"', surface)
    assert not re.search(r'data-select-variant="b"', surface)
    headings = re.findall(r"<h[1-4]\b[^>]*>(.*?)</h[1-4]>", surface, re.S)
    assert headings
    assert all("The open item in five words" not in text for text in headings)
    assert not re.search(r'<a\b[^>]*href="https?://', surface)
    assert "PRIVATE_TEMPLATE_PROBE_836104" not in html
    assert any("[" in unit["placeholder"] for unit in state["units"].values())
    for evidence in state["evidence"].values():
        assert evidence["popup"]["title"]
        assert evidence["popup"]["sections"]


@pytest.mark.parametrize("entry", TEMPLATES, ids=lambda entry: entry["source_asset"])
def test_explicit_import_uses_current_template_not_filled_reference(entry, tmp_path):
    name = Path(entry["source_asset"]).stem
    form = {"slide-brief": "slide-brief", "diligence-report": "slide-brief"}.get(
        name, "one-page"
    )
    args = SimpleNamespace(
        template=name,
        form=form,
        output=tmp_path / "import.html",
        spec_output=tmp_path / "import.spec.json",
    )
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        assert scaffold._command_init(args) == 0
    receipt = json.loads(stdout.getvalue())
    spec = json.loads(args.spec_output.read_text(encoding="utf-8"))
    assert spec["schemaVersion"] == "legaldesign.build.v4"
    assert spec["brief"]["form"] == form
    assert "approaches" not in spec and "overview" in spec
    assert spec["composition"]["templateRef"] == name
    assert "both approaches" not in receipt["warning"]
    current = ROOT / entry["path"]
    assert Path(receipt["sourceAsset"]) == current
    assert args.output.read_bytes() == current.read_bytes()
    assert (
        args.output.read_bytes()
        != (
            ROOT / "skills/core/legaldesign/assets" / entry["source_asset"]
        ).read_bytes()
    )


@pytest.mark.parametrize(
    "template,legacy_form",
    [("slide-brief", "walkthrough"), ("diligence-report", "report")],
)
def test_explicit_template_legacy_form_alias_produces_current_spec(
    template, legacy_form, tmp_path
):
    args = SimpleNamespace(
        template=template,
        form=legacy_form,
        output=tmp_path / "import.html",
        spec_output=tmp_path / "import.spec.json",
    )
    with contextlib.redirect_stdout(io.StringIO()):
        assert scaffold._command_init(args) == 0
    spec = json.loads(args.spec_output.read_text(encoding="utf-8"))
    assert spec["schemaVersion"] == "legaldesign.build.v4"
    assert spec["brief"]["form"] == "slide-brief"
    assert "approaches" not in spec
