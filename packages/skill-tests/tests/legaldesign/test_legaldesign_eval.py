"""Run the portable /legaldesign contract as part of the repository test suite."""

from __future__ import annotations

import pytest
from public_contract import (
    PopupStructureProbe,
    allows_page_background,
    component_implementation,
    component_parameter_keys,
    runtime_is_in_head,
)


class _Contract:
    component_implementation = staticmethod(component_implementation)
    component_parameter_keys = staticmethod(component_parameter_keys)
    allows_page_background = staticmethod(allows_page_background)
    runtime_is_in_head = staticmethod(runtime_is_in_head)
    PopupStructureProbe = PopupStructureProbe


EVAL = _Contract()


@pytest.mark.parametrize(
    "declaration",
    [
        "C.flow = function (params, opts) { "
        'known(data, "params", ["stages", "edges"]); };',
        'C.flow=(params,opts)=>{known(data,"params",["stages","edges"]);};',
        """C . flow = (
            params,
            opts,
        ) => {
            known (
                data, 'params', ['stages', 'edges',],
            );
        };""",
    ],
)
def test_component_extraction_ignores_formatter_choices(declaration: str) -> None:
    source = (
        declaration
        + 'C.timeline=(params)=>{known(data,"params",["marks"]);};LD.registry=[];'
    )
    assert EVAL.component_implementation(source, "flow") is not None
    assert EVAL.component_parameter_keys(source, "flow") == ["stages", "edges"]
    assert EVAL.component_parameter_keys(source, "timeline") == ["marks"]
    assert EVAL.component_implementation(source, "missing") is None


def test_component_extraction_preserves_contract_failures() -> None:
    source = (
        'C.flow=(params)=>{};C.timeline=(params)=>{known(data,"params",["marks"]);};'
        "LD.registry=[];"
    )
    assert EVAL.component_parameter_keys(source, "flow") == []
    reordered = (
        'C.flow=(params)=>{known(data,"params",["edges","stages"]);};LD.registry=[];'
    )
    assert EVAL.component_parameter_keys(reordered, "flow") == ["edges", "stages"]
    chart = (
        "C.rungBars = (params,opts) => { const data=chartParams ( params, "
        '["items", "unit"], ); };LD.registry=[];'
    )
    assert EVAL.component_parameter_keys(chart, "rungBars") == ["items", "unit"]
    invalid_chart = chart.replace("chartParams ( params,", 'known ( data, "params",')
    assert EVAL.component_parameter_keys(invalid_chart, "rungBars") == []


@pytest.mark.parametrize(
    "selector",
    [
        'html[data-theme="dark"] .ld-composed-unit[data-kind="figure"]',
        "html[data-theme=dark] .ld-composed-unit[data-kind=figure]",
        "/* index rail */\nhtml[data-has-slide-index='true'] .ld-slide-index",
        'html[data-has-slide-index = "true"] .ld-slide-index',
    ],
)
def test_page_background_accepts_exact_stage_and_index_surfaces(selector: str) -> None:
    assert EVAL.allows_page_background(selector)


@pytest.mark.parametrize(
    "selector",
    [
        ".card",
        'html[data-theme="dark"] .ld-composed-unit[data-kind="text"]',
        'html[data-theme="dark"] .ld-composed-unit[data-kind="figure"] .card',
        'html[data-has-slide-index="true"] .ld-slide-index button',
        ".ld-slide-index .card",
    ],
)
def test_page_background_does_not_allow_cards_inside_new_surfaces(
    selector: str,
) -> None:
    assert not EVAL.allows_page_background(selector)


def test_complete_runtime_block_must_live_inside_head() -> None:
    runtime = (
        "<!-- legaldesign:runtime -->"
        + "<style>body{}</style><script></script>"
        + "<!-- /legaldesign:runtime -->"
    )
    assert EVAL.runtime_is_in_head(
        "<html><head>" + runtime + "</head><body></body></html>"
    )
    assert not EVAL.runtime_is_in_head(
        "<html><head></head><body>" + runtime + "</body></html>"
    )
    assert not EVAL.runtime_is_in_head(
        "<html><head>"
        + "<!-- legaldesign:runtime -->"
        + "</head><body>"
        + "<!-- /legaldesign:runtime -->"
        + "</body></html>"
    )


@pytest.mark.parametrize("same_popup", [True, False])
def test_source_excerpt_requires_provenance_in_its_popup(same_popup: bool) -> None:
    excerpt = '<p class="doc-text">Exact source quotation.</p>'
    provenance = '<p class="ld-popup-source">Supplied method · section 2</p>'
    source = '<div id="popup-scrim"><div class="pop" id="source-one">' + excerpt
    source += (
        provenance
        if same_popup
        else '</div><div class="pop" id="source-two">' + provenance
    )
    source += "</div></div>"
    probe = EVAL.PopupStructureProbe()
    probe.feed(source)
    assert bool(probe.excerpt_popup_ids & probe.provenance_popup_ids) is same_popup


def test_source_excerpt_outside_popup_does_not_count() -> None:
    probe = EVAL.PopupStructureProbe()
    probe.feed('<p class="doc-text">Quotation</p><p class="ld-popup-source">Source</p>')
    assert not probe.excerpt_popup_ids
    assert not probe.provenance_popup_ids
