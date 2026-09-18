#!/usr/bin/env python3
"""Copy a LegalDesign shell and validate portable design contracts."""

from __future__ import annotations

import argparse
import base64
import binascii
import copy
import hashlib
import json
import re
import shutil
import sys
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, TypeGuard
from urllib.parse import urlsplit

SKILL_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_ROOT.parents[2]
ASSET_ROOT = SKILL_ROOT / "assets"
COMPONENT_CONTRACT = SKILL_ROOT / "references" / "components.json"
DESIGN_SCHEMA = SKILL_ROOT / "schemas" / "design-authority.schema.json"
# Optional maintainer fixture: installed skills retain the generic template checks
# below without depending on a repository evaluation corpus.
MATTER_TERMS = REPO_ROOT / "packages" / "legaldesign" / "fixtures" / "matter-terms.json"
SPEC_VERSION_V2 = "legaldesign.build.v2"
SPEC_VERSION = "legaldesign.build.v3"
SPEC_VERSION_V4 = "legaldesign.build.v4"
COMPONENT_VERSION = "legaldesign.components.v2"
FORMS = {"one-page", "slide-brief", "walkthrough", "report", "custom"}
V4_FORMS = {"one-page", "slide-brief"}
TEMPLATES = {
    "stacked-explainer": ("one-page", "stacked-explainer.html"),
    "slide-brief": ("slide-brief", "slide-brief.html"),
    "diligence-report": ("slide-brief", "diligence-report.html"),
    "method-map": ("one-page", "method-map.html"),
    "card-hub": ("one-page", "card-hub.html"),
}
RELATIONSHIPS = {
    "sequence",
    "time",
    "hierarchy",
    "containment",
    "comparison",
    "convergence",
    "feedback",
    "priority",
    "progression",
    "interaction",
    "part-of-whole",
    "distribution",
    "correlation",
    "change",
    "quantity",
}
PURPOSES = {"decide", "understand", "choose", "status", "other"}
SITUATIONS = {"laptop", "phone", "meeting", "print"}
FORM_VALUES = {"one-page", "walkthrough", "report", "custom"}
COMPOSITION_STRATEGIES = {"composed", "template-import"}
CLAIM_KINDS = {"material", "context"}
CLAIM_PLACEMENTS = {"surface", "detail", "omitted"}
ORIGINAL_AVAILABILITY = {"linked", "unavailable"}
SELECTION_MODES = {"single", "multiple"}
KINDS = {"text", "card", "figure", "table", "evidence", "decision"}
ROLES = {
    "title",
    "answer",
    "summary",
    "action",
    "scope",
    "finding",
    "expected",
    "matter",
}
SINGLE_TEXT_ROLES = {"scope", "matter", "expected"}
AXES = {"form", "framing", "granularity", "emphasis", "layout", "register"}
STYLE_SOURCES = {"loxoto", "design-md", "template", "playbook"}
SOURCE_STATUSES = {
    "supplied",
    "supplied-unverified",
    "verified",
    "retrieved",
    "unavailable",
}
POPUP_TYPES = {"source", "explainer", "detail"}
FORBIDDEN_SURFACE_CLASS_MARKERS = ("eyebrow", "kicker", "evidence")
GENERIC_POPUP_TITLES = {"evidence", "view evidence", "more detail", "source"}
TEMPLATE_BANS = (
    "{{text_",
    "[Editable content]",
    "Visualization template",
    "data:image",
)
PALETTE_TOKENS = (
    "--bg",
    "--card",
    "--card-strong",
    "--ink",
    "--muted",
    "--faint",
    "--line",
    "--line-strong",
    "--red",
    "--red-strong",
    "--red-wash",
    "--tint",
)
# A DESIGN.md is a palette authority, not a second component system. Interaction,
# depth, and geometry tokens stay in the packaged runtime and are deliberately
# absent from the author-controlled contract.
LIGHT_TOKENS = PALETTE_TOKENS
DARK_TOKENS = PALETTE_TOKENS
COMPOSED_SHELL = ASSET_ROOT / "composed-shell.html"
COMPOSED_CONTENT_MARKER = "<!-- legaldesign:composed-content -->"
ALLOWED_FRAGMENT_TAGS = {
    "a",
    "b",
    "blockquote",
    "br",
    "caption",
    "dd",
    "div",
    "dl",
    "dt",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "hr",
    "i",
    "li",
    "ol",
    "p",
    "small",
    "span",
    "strong",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}
VOID_FRAGMENT_TAGS = {"br", "hr"}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid JSON in {path}: line {exc.lineno}, column {exc.colno}"
        ) from exc


def json_for_script(payload: Any) -> str:
    """Serialize JSON for an inert script block without a closing-tag token."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )


def _component_payload() -> dict[str, Any]:
    payload = _load_json(COMPONENT_CONTRACT)
    if not isinstance(payload, dict):
        raise ValueError("component registry must be a JSON object")
    if payload.get("schemaVersion") != COMPONENT_VERSION:
        raise ValueError("unsupported component registry")
    if not isinstance(payload.get("components"), dict):
        raise ValueError("component registry has no components object")
    return payload


def _component_contracts() -> dict[str, dict[str, Any]]:
    return _component_payload()["components"]


def _nonempty(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


def _check_keys(
    value: dict[str, Any],
    *,
    allowed: set[str],
    required: set[str],
    path: str,
    errors: list[str],
) -> None:
    for name in sorted(required - set(value)):
        errors.append(f"{path}: missing required field {name!r}")
    for name in sorted(set(value) - allowed):
        errors.append(f"{path}: unknown field {name!r}")


def _check_enum(value: Any, choices: set[str], path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or value not in choices:
        errors.append(f"{path}: expected one of {sorted(choices)!r}")


def _check_string(value: Any, path: str, errors: list[str]) -> None:
    if not _nonempty(value):
        errors.append(f"{path}: expected a non-empty string")


def _check_string_list(
    value: Any, path: str, errors: list[str], *, minimum: int = 0
) -> None:
    if not isinstance(value, list):
        errors.append(f"{path}: expected an array")
        return
    if len(value) < minimum:
        errors.append(f"{path}: expected at least {minimum} item")
    for index, item in enumerate(value):
        _check_string(item, f"{path}[{index}]", errors)


def _check_brief(value: Any, errors: list[str], *, spec_version: str) -> None:
    path = "$.brief"
    if not isinstance(value, dict):
        errors.append(f"{path}: expected an object")
        return
    fields = {
        "reader",
        "action",
        "purpose",
        "message",
        "spine",
        "situation",
        "form",
        "sources",
        "assumptions",
        "gaps",
    }
    if spec_version in {SPEC_VERSION, SPEC_VERSION_V4}:
        fields.add("title")
    _check_keys(value, allowed=fields, required=fields, path=path, errors=errors)
    for name in (
        ("title", "reader", "action", "message")
        if spec_version in {SPEC_VERSION, SPEC_VERSION_V4}
        else ("reader", "action", "message")
    ):
        _check_string(value.get(name), f"{path}.{name}", errors)
    _check_enum(value.get("purpose"), PURPOSES, f"{path}.purpose", errors)
    _check_enum(value.get("spine"), RELATIONSHIPS, f"{path}.spine", errors)
    _check_enum(value.get("situation"), SITUATIONS, f"{path}.situation", errors)
    _check_enum(
        value.get("form"),
        V4_FORMS if spec_version == SPEC_VERSION_V4 else FORM_VALUES,
        f"{path}.form",
        errors,
    )
    sources = value.get("sources")
    if not isinstance(sources, list):
        errors.append(f"{path}.sources: expected an array")
    else:
        if not sources:
            errors.append(f"{path}.sources: expected at least 1 item")
        for index, source in enumerate(sources):
            source_path = f"{path}.sources[{index}]"
            if not isinstance(source, dict):
                errors.append(f"{source_path}: expected an object")
                continue
            _check_keys(
                source,
                allowed={"id", "label", "status"},
                required={"id", "label", "status"},
                path=source_path,
                errors=errors,
            )
            _check_string(source.get("id"), f"{source_path}.id", errors)
            _check_string(source.get("label"), f"{source_path}.label", errors)
            _check_enum(
                source.get("status"),
                SOURCE_STATUSES,
                f"{source_path}.status",
                errors,
            )
    _check_string_list(value.get("assumptions"), f"{path}.assumptions", errors)
    _check_string_list(value.get("gaps"), f"{path}.gaps", errors)


def _check_style(value: Any, errors: list[str]) -> None:
    path = "$.style"
    if not isinstance(value, dict):
        errors.append(f"{path}: expected an object")
        return
    _check_keys(
        value,
        allowed={"source", "ref"},
        required={"source", "ref"},
        path=path,
        errors=errors,
    )
    _check_enum(value.get("source"), STYLE_SOURCES, f"{path}.source", errors)
    reference = value.get("ref")
    if reference is not None:
        _check_string(reference, f"{path}.ref", errors)


def _check_section_layout(
    value: Any,
    *,
    unit_ids: Any,
    path: str,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected an object")
        return
    _check_keys(
        value,
        allowed={"columns", "placements"},
        required={"columns", "placements"},
        path=path,
        errors=errors,
    )
    columns = value.get("columns")
    if isinstance(columns, bool) or columns != 12:
        errors.append(f"{path}.columns: expected the integer 12")
    placements = value.get("placements")
    if not isinstance(placements, list):
        errors.append(f"{path}.placements: expected an array")
        return
    if not placements:
        errors.append(f"{path}.placements: expected at least 1 item")
    placed: list[str] = []
    occupied: dict[tuple[int, int], str] = {}
    for index, placement in enumerate(placements):
        item_path = f"{path}.placements[{index}]"
        if not isinstance(placement, dict):
            errors.append(f"{item_path}: expected an object")
            continue
        _check_keys(
            placement,
            allowed={"unitId", "row", "column", "span", "rowSpan"},
            required={"unitId", "row", "column", "span"},
            path=item_path,
            errors=errors,
        )
        unit_id = placement.get("unitId")
        _check_string(unit_id, f"{item_path}.unitId", errors)
        if isinstance(unit_id, str):
            if unit_id in placed:
                errors.append(
                    f"{item_path}.unitId: duplicate placement for {unit_id!r}"
                )
            placed.append(unit_id)
        coordinates: dict[str, int] = {}
        for name in ("row", "column", "span", "rowSpan"):
            coordinate = (
                placement.get(name, 1) if name == "rowSpan" else placement.get(name)
            )
            if isinstance(coordinate, bool) or not isinstance(coordinate, int):
                errors.append(f"{item_path}.{name}: expected an integer")
                continue
            coordinates[name] = coordinate
        row = coordinates.get("row")
        column = coordinates.get("column")
        span = coordinates.get("span")
        row_span = coordinates.get("rowSpan")
        if row is not None and row < 1:
            errors.append(f"{item_path}.row: expected an integer at least 1")
        if column is not None and not 1 <= column <= 12:
            errors.append(f"{item_path}.column: expected an integer from 1 to 12")
        if span is not None and not 1 <= span <= 12:
            errors.append(f"{item_path}.span: expected an integer from 1 to 12")
        if row_span is not None and not 1 <= row_span <= 12:
            errors.append(f"{item_path}.rowSpan: expected an integer from 1 to 12")
        if (
            row is None
            or column is None
            or span is None
            or row_span is None
            or row < 1
            or not 1 <= column <= 12
            or not 1 <= span <= 12
            or not 1 <= row_span <= 12
        ):
            continue
        last_column = column + span - 1
        if last_column > 12:
            errors.append(
                f"{item_path}: column {column} plus span {span} exceeds 12 columns"
            )
            continue
        for cell_row in range(row, row + row_span):
            for cell_column in range(column, last_column + 1):
                cell = (cell_row, cell_column)
                if cell in occupied:
                    errors.append(
                        f"{item_path}: overlaps {occupied[cell]!r} at row {cell_row}, "
                        f"column {cell_column}"
                    )
                elif isinstance(unit_id, str):
                    occupied[cell] = unit_id

    if isinstance(unit_ids, list):
        expected = [item for item in unit_ids if isinstance(item, str)]
        if len(expected) != len(set(expected)):
            errors.append(f"{path}: unitIds must be unique")
        if set(expected) != set(placed) or len(expected) != len(placed):
            errors.append(
                f"{path}.placements: unit IDs must exactly match the section's unitIds"
            )


def _derive_issue_layout(section: dict[str, Any]) -> dict[str, Any] | None:
    recipe = section.get("issueLayout")
    ids = section.get("unitIds")
    if not isinstance(recipe, dict) or not isinstance(ids, list) or not ids:
        return None
    analysis = [
        recipe.get(key)
        for key in ("findingUnitId", "implicationUnitId", "actionUnitId")
    ]
    support = recipe.get("supportUnitIds")
    if not isinstance(support, list) or not 1 <= len(support) <= 2:
        return None
    if not all(isinstance(item, str) for item in [*ids, *analysis, *support]):
        return None
    positions = {
        unit_id: {"unitId": unit_id, "row": 2 + index, "column": 1, "span": 6}
        for index, unit_id in enumerate(analysis)
    }
    for index, unit_id in enumerate(support):
        positions[unit_id] = {
            "unitId": unit_id,
            "row": 2 + index,
            "column": 7,
            "span": 6,
            "rowSpan": 3 if len(support) == 1 else (1 if index == 0 else 2),
        }
    for index, unit_id in enumerate(item for item in ids if item not in positions):
        positions[unit_id] = {
            "unitId": unit_id,
            "row": 1 if index == 0 else 4 + index,
            "column": 1,
            "span": 12,
        }
    return {"columns": 12, "placements": [positions[item] for item in ids]}


def _normalize_issue_layouts(payload: dict[str, Any]) -> dict[str, Any]:
    """Derive recipe coordinates on a copy; validation never mutates caller data."""
    result = copy.deepcopy(payload)
    if result.get("schemaVersion") != SPEC_VERSION_V4:
        return result
    composition = result.get("composition")
    sections = composition.get("sections") if isinstance(composition, dict) else None
    for section in sections if isinstance(sections, list) else []:
        if (
            isinstance(section, dict)
            and "issueLayout" in section
            and "layout" not in section
        ):
            derived = _derive_issue_layout(section)
            if derived is not None:
                section["layout"] = derived
    return result


def _check_composition(
    value: Any,
    errors: list[str],
    *,
    path: str = "$.composition",
    allow_issue: bool = False,
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected an object")
        return
    fields = {"strategy", "shape", "rationale", "sections", "templateRef"}
    _check_keys(value, allowed=fields, required=fields, path=path, errors=errors)
    strategy = value.get("strategy")
    _check_enum(strategy, COMPOSITION_STRATEGIES, f"{path}.strategy", errors)
    for name in ("shape", "rationale"):
        _check_string(value.get(name), f"{path}.{name}", errors)
    template_ref = value.get("templateRef")
    if strategy == "composed":
        if template_ref is not None:
            errors.append(f"{path}.templateRef: composed work must not name a template")
    elif strategy == "template-import":
        _check_string(template_ref, f"{path}.templateRef", errors)

    sections = value.get("sections")
    if not isinstance(sections, list):
        errors.append(f"{path}.sections: expected an array")
        return
    if not sections:
        errors.append(f"{path}.sections: expected at least 1 item")
    section_ids: set[str] = set()
    for index, section in enumerate(sections):
        section_path = f"{path}.sections[{index}]"
        if not isinstance(section, dict):
            errors.append(f"{section_path}: expected an object")
            continue
        _check_keys(
            section,
            allowed={"id", "purpose", "indexLabel", "unitIds", "layout"}
            | ({"issueLayout", "presentation"} if allow_issue else set()),
            required={"id", "purpose", "unitIds", "layout"},
            path=section_path,
            errors=errors,
        )
        section_id = section.get("id")
        if "presentation" in section:
            _check_enum(
                section["presentation"],
                {"card-hub"},
                f"{section_path}.presentation",
                errors,
            )
        _check_string(section_id, f"{section_path}.id", errors)
        if isinstance(section_id, str):
            if section_id in section_ids:
                errors.append(f"{section_path}.id: duplicate section ID {section_id!r}")
            section_ids.add(section_id)
        _check_string(section.get("purpose"), f"{section_path}.purpose", errors)
        if "indexLabel" in section:
            _check_string(section["indexLabel"], f"{section_path}.indexLabel", errors)
            if (
                isinstance(section["indexLabel"], str)
                and len(section["indexLabel"]) > 48
            ):
                errors.append(
                    f"{section_path}.indexLabel: use a concise label "
                    "(48 characters maximum)"
                )
        _check_string_list(
            section.get("unitIds"),
            f"{section_path}.unitIds",
            errors,
            minimum=1,
        )
        _check_section_layout(
            section.get("layout"),
            unit_ids=section.get("unitIds"),
            path=f"{section_path}.layout",
            errors=errors,
        )


def _check_approaches(value: Any, errors: list[str]) -> None:
    path = "$.approaches"
    if not isinstance(value, dict):
        errors.append(f"{path}: expected an object")
        return
    _check_keys(
        value,
        allowed={"a", "b"},
        required={"a", "b"},
        path=path,
        errors=errors,
    )
    for key in ("a", "b"):
        item = value.get(key)
        item_path = f"{path}.{key}"
        if not isinstance(item, dict):
            errors.append(f"{item_path}: expected an object")
            continue
        _check_keys(
            item,
            allowed={"label", "rationale", "composition"},
            required={"label", "rationale", "composition"},
            path=item_path,
            errors=errors,
        )
        _check_string(item.get("label"), f"{item_path}.label", errors)
        _check_string(item.get("rationale"), f"{item_path}.rationale", errors)
        _check_composition(
            item.get("composition"),
            errors,
            path=f"{item_path}.composition",
        )


def _spec_approaches(payload: dict[str, Any]) -> dict[str, Any]:
    """One internal traversal slot for v4, without duplicating authored data."""
    if payload.get("schemaVersion") == SPEC_VERSION_V4:
        return {"a": {"composition": payload.get("composition")}}
    value = payload.get("approaches")
    return value if isinstance(value, dict) else {}


def _check_overview(payload: dict[str, Any], errors: list[str]) -> None:
    overview = payload.get("overview")
    path = "$.overview"
    if not isinstance(overview, dict):
        errors.append(f"{path}: expected an object")
        return
    fields = {"sectionId", "contextUnitIds", "questionUnitId", "answerUnitId", "topics"}
    _check_keys(
        overview, allowed=fields | {"groups"}, required=fields, path=path, errors=errors
    )
    for key in ("sectionId", "questionUnitId", "answerUnitId"):
        _check_string(overview.get(key), f"{path}.{key}", errors)
    _check_string_list(
        overview.get("contextUnitIds"), f"{path}.contextUnitIds", errors, minimum=1
    )
    composition = payload.get("composition")
    sections = composition.get("sections", []) if isinstance(composition, dict) else []
    if (
        not isinstance(sections, list)
        or not sections
        or not isinstance(sections[0], dict)
    ):
        errors.append(
            f"{path}.sectionId: an overview must be the first composition section"
        )
        return
    first = sections[0]
    if overview.get("sectionId") != first.get("id"):
        errors.append(
            f"{path}.sectionId: overview must identify the first composition section"
        )
    units = (
        {
            unit["id"]: unit
            for unit in payload.get("units", [])
            if isinstance(unit, dict) and isinstance(unit.get("id"), str)
        }
        if isinstance(payload.get("units"), list)
        else {}
    )
    first_ids = first.get("unitIds", [])
    first_ids = first_ids if isinstance(first_ids, list) else []
    context = overview.get("contextUnitIds", [])
    context = context if isinstance(context, list) else []
    anchors = [*context, overview.get("questionUnitId"), overview.get("answerUnitId")]
    meaningful_ids = [item for item in anchors if isinstance(item, str)]
    if len(meaningful_ids) != len(set(meaningful_ids)):
        errors.append(f"{path}: context, question and answer must use distinct units")
    for unit_id in meaningful_ids:
        unit = units.get(unit_id)
        if unit_id not in first_ids or not unit:
            errors.append(
                f"{path}: required unit {unit_id!r} must be placed in the overview"
            )
            continue
        variant = (
            unit.get("variants", {}).get("a", {})
            if isinstance(unit.get("variants"), dict)
            else {}
        )
        html = variant.get("html") if isinstance(variant, dict) else None
        parser = _SurfaceGrammarParser()
        if isinstance(html, str):
            parser.feed(html)
        if (
            unit.get("kind") not in {"text", "card"}
            or not " ".join(parser.text_chunks).strip()
        ):
            errors.append(
                f"{path}: required unit {unit_id!r} needs visible "
                "context/question/answer text"
            )
    topics = overview.get("topics")
    if not isinstance(topics, list):
        errors.append(f"{path}.topics: expected an array")
        return
    later_ids = {
        item.get("id")
        for item in sections[1:]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    targets: list[str] = []
    topic_units: list[str] = []
    for index, topic in enumerate(topics):
        topic_path = f"{path}.topics[{index}]"
        if not isinstance(topic, dict):
            errors.append(f"{topic_path}: expected an object")
            continue
        _check_keys(
            topic,
            allowed={"unitId", "targetSectionId"},
            required={"unitId", "targetSectionId"},
            path=topic_path,
            errors=errors,
        )
        for key in ("unitId", "targetSectionId"):
            _check_string(topic.get(key), f"{topic_path}.{key}", errors)
        target = topic.get("targetSectionId")
        if isinstance(target, str):
            targets.append(target)
            if target not in later_ids:
                errors.append(
                    f"{topic_path}.targetSectionId: must target a subsequent "
                    f"section, not {target!r}"
                )
        unit_id = topic.get("unitId")
        if not isinstance(unit_id, str):
            continue
        topic_units.append(unit_id)
        unit = units.get(unit_id)
        if (
            unit_id not in first_ids
            or not unit
            or unit.get("kind") not in {"text", "card"}
        ):
            errors.append(
                f"{topic_path}.unitId: must identify an overview text/card unit"
            )
        elif unit.get("detail") or unit.get("detailAnchor"):
            errors.append(
                f"{topic_path}.unitId: navigation and popup actions "
                "must not share one unit"
            )
        else:
            variants = unit.get("variants")
            variant = variants.get("a") if isinstance(variants, dict) else None
            html = variant.get("html") if isinstance(variant, dict) else None
            parser = _SurfaceGrammarParser()
            if isinstance(html, str):
                parser.feed(html)
            if not " ".join(parser.text_chunks).strip():
                errors.append(f"{topic_path}.unitId: topic needs visible link text")
    if len(topic_units) != len(set(topic_units)):
        errors.append(f"{path}.topics: each topic unit must have one destination")
    if len(targets) != len(set(targets)):
        errors.append(f"{path}.topics: link each subsequent section exactly once")
    brief = payload.get("brief")
    form = brief.get("form") if isinstance(brief, dict) else None
    if "groups" in overview:
        _check_overview_groups(
            overview["groups"],
            form=form,
            first=first,
            topic_units=topic_units,
            anchors=meaningful_ids,
            errors=errors,
        )
    if form == "one-page" and (len(sections) != 1 or topics):
        errors.append(
            "$.composition: one-page requires one overview section "
            "and no topic navigation"
        )
    if form == "slide-brief":
        if len(sections) < 2:
            errors.append(
                "$.composition: slide-brief requires an overview "
                "and at least one subsequent section"
            )
        if set(targets) != later_ids:
            errors.append(
                f"{path}.topics: must link every subsequent section; "
                f"missing {sorted(later_ids - set(targets))!r}"
            )


def _check_overview_groups(
    groups: Any,
    *,
    form: Any,
    first: dict[str, Any],
    topic_units: list[str],
    anchors: list[str],
    errors: list[str],
) -> None:
    path = "$.overview.groups"
    if form != "slide-brief":
        errors.append(f"{path}: grouped topic navigation requires slide-brief")
    if not isinstance(groups, list):
        errors.append(f"{path}: expected an array")
        return
    if not 1 <= len(groups) <= 12:
        errors.append(f"{path}: expected 1 to 12 groups")
    grouped_ids: list[str] = []
    for index, group in enumerate(groups):
        group_path = f"{path}[{index}]"
        if not isinstance(group, dict):
            errors.append(f"{group_path}: expected an object")
            continue
        _check_keys(
            group,
            allowed={"label", "topicUnitIds"},
            required={"label", "topicUnitIds"},
            path=group_path,
            errors=errors,
        )
        label = group.get("label")
        _check_string(label, f"{group_path}.label", errors)
        if isinstance(label, str) and len(label) > 48:
            errors.append(f"{group_path}.label: expected at most 48 characters")
        ids = group.get("topicUnitIds")
        _check_string_list(ids, f"{group_path}.topicUnitIds", errors, minimum=1)
        if isinstance(ids, list):
            grouped_ids.extend(unit_id for unit_id in ids if isinstance(unit_id, str))
    if len(grouped_ids) != len(set(grouped_ids)):
        errors.append(f"{path}: each topic must be assigned to exactly one group")
    topic_set = set(topic_units)
    unknown = set(grouped_ids) - topic_set
    missing = topic_set - set(grouped_ids)
    if unknown:
        errors.append(f"{path}: non-topic unit references {sorted(unknown)!r}")
    if missing:
        errors.append(
            f"{path}: every topic must be grouped; missing {sorted(missing)!r}"
        )
    first_ids = first.get("unitIds")
    if not isinstance(first_ids, list):
        return
    first_topic_index = next(
        (
            index
            for index, unit_id in enumerate(first_ids)
            if isinstance(unit_id, str) and unit_id in topic_set
        ),
        None,
    )
    if first_topic_index is None:
        errors.append(f"{path}: the overview must contain its grouped topics")
        return
    if first_ids[first_topic_index:] != grouped_ids:
        errors.append(
            f"{path}: flattened topicUnitIds must exactly match the trailing "
            "contiguous topic block in overview unitIds"
        )
    if any(anchor not in first_ids[:first_topic_index] for anchor in anchors):
        errors.append(
            f"{path}: context, question and answer must precede grouped topics"
        )
    layout = first.get("layout")
    placements = layout.get("placements") if isinstance(layout, dict) else None
    placement = (
        next(
            (
                item
                for item in placements
                if isinstance(item, dict)
                and item.get("unitId") == first_ids[first_topic_index]
            ),
            None,
        )
        if isinstance(placements, list)
        else None
    )
    if not isinstance(placement, dict) or (
        placement.get("column") != 1 or placement.get("span") != 12
    ):
        errors.append(f"{path}: the first grouped topic must reserve column 1, span 12")


def _check_claims(value: Any, errors: list[str]) -> None:
    path = "$.claims"
    if not isinstance(value, list):
        errors.append(f"{path}: expected an array")
        return
    if not value:
        errors.append(f"{path}: expected at least 1 item")
    for index, claim in enumerate(value):
        claim_path = f"{path}[{index}]"
        if not isinstance(claim, dict):
            errors.append(f"{claim_path}: expected an object")
            continue
        fields = {
            "id",
            "text",
            "kind",
            "sourceIds",
            "placement",
            "evidenceIds",
            "omissionReason",
        }
        required = fields - {"omissionReason"}
        _check_keys(
            claim,
            allowed=fields,
            required=required,
            path=claim_path,
            errors=errors,
        )
        for name in ("id", "text"):
            _check_string(claim.get(name), f"{claim_path}.{name}", errors)
        _check_enum(claim.get("kind"), CLAIM_KINDS, f"{claim_path}.kind", errors)
        _check_enum(
            claim.get("placement"),
            CLAIM_PLACEMENTS,
            f"{claim_path}.placement",
            errors,
        )
        _check_string_list(
            claim.get("sourceIds"),
            f"{claim_path}.sourceIds",
            errors,
            minimum=1,
        )
        _check_string_list(
            claim.get("evidenceIds"),
            f"{claim_path}.evidenceIds",
            errors,
        )
        if claim.get("placement") == "omitted":
            _check_string(
                claim.get("omissionReason"),
                f"{claim_path}.omissionReason",
                errors,
            )
        elif "omissionReason" in claim:
            errors.append(
                f"{claim_path}.omissionReason: allowed only when placement is omitted"
            )
        if (
            claim.get("kind") == "material"
            and claim.get("placement") != "omitted"
            and not claim.get("evidenceIds")
        ):
            errors.append(
                f"{claim_path}.evidenceIds: a presented material claim needs "
                "popup detail and an original-source state"
            )


def _check_item(
    value: Any,
    *,
    contract: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected an object")
        return
    fields = set(contract.get("itemFields", []))
    required = set(contract.get("itemRequired", []))
    _check_keys(value, allowed=fields, required=required, path=path, errors=errors)
    choices = contract.get("itemChoices", {})
    for name, item in value.items():
        item_path = f"{path}.{name}"
        if name == "open":
            if not isinstance(item, bool):
                errors.append(f"{item_path}: expected a boolean")
        elif name == "leaves":
            if not isinstance(item, list):
                errors.append(f"{item_path}: expected an array")
                continue
            if not 1 <= len(item) <= 2:
                errors.append(f"{item_path}: expected 1 to 2 items, got {len(item)}")
            for leaf_index, leaf in enumerate(item):
                leaf_path = f"{item_path}[{leaf_index}]"
                if not isinstance(leaf, dict):
                    errors.append(f"{leaf_path}: expected an object")
                    continue
                _check_keys(
                    leaf,
                    allowed={"title", "detail"},
                    required={"title"},
                    path=leaf_path,
                    errors=errors,
                )
                _check_string(leaf.get("title"), f"{leaf_path}.title", errors)
                if "detail" in leaf:
                    _check_string(leaf["detail"], f"{leaf_path}.detail", errors)
        elif name in choices:
            if item not in choices[name]:
                errors.append(f"{item_path}: expected one of {choices[name]!r}")
        elif item is not None:
            _check_string(item, item_path, errors)


def _check_parameter(
    value: Any,
    *,
    contract: dict[str, Any],
    params: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    kind = contract.get("type")
    if kind == "text":
        _check_string(value, path, errors)
        return
    if kind == "choice":
        if value not in contract.get("choices", []):
            errors.append(f"{path}: expected one of {contract.get('choices', [])!r}")
        return
    if kind == "index":
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"{path}: expected an integer index")
            return
        minimum = int(contract.get("minValue", 0))
        maximum = contract.get("maxValue")
        max_from = contract.get("maxFrom")
        if isinstance(max_from, str) and isinstance(params.get(max_from), list):
            maximum = len(params[max_from]) - 1
        if value < minimum or maximum is None or value > int(maximum):
            errors.append(f"{path}: index {value} is outside the available items")
        return
    if kind not in {"strings", "list"}:
        errors.append(f"{path}: unsupported contract type {kind!r}")
        return
    if not isinstance(value, list):
        errors.append(f"{path}: expected an array")
        return
    minimum = int(contract.get("minItems", 0))
    maximum = int(contract.get("maxItems", len(value)))
    if len(value) < minimum or len(value) > maximum:
        errors.append(
            f"{path}: expected {minimum} to {maximum} items, got {len(value)}"
        )
    if kind == "strings":
        _check_string_list(value, path, errors)
    else:
        for index, item in enumerate(value):
            _check_item(
                item,
                contract=contract,
                path=f"{path}[{index}]",
                errors=errors,
            )
    count_from = contract.get("countFrom")
    if isinstance(count_from, dict):
        source = params.get(count_from.get("parameter"))
        if isinstance(source, list):
            wanted = len(source) + int(count_from.get("offset", 0))
            if len(value) != wanted:
                errors.append(f"{path}: expected exactly {wanted} items")


def _check_component(
    component_id: Any,
    params: Any,
    relationship: Any,
    path: str,
    errors: list[str],
) -> None:
    if not _nonempty(component_id):
        errors.append(f"{path}.component: expected a non-empty string")
        return
    contracts = _component_contracts()
    component = contracts.get(component_id)
    if not isinstance(component, dict):
        errors.append(f"{path}.component: unknown component ID {component_id!r}")
        return
    declared = component.get("relationships")
    if not isinstance(declared, list) or relationship not in declared:
        errors.append(
            f"{path}.component: {component_id!r} does not declare "
            f"relationship {relationship!r}"
        )
    if not isinstance(params, dict):
        errors.append(f"{path}.params: expected an object")
        return
    parameter_contracts = component.get("parameters")
    if not isinstance(parameter_contracts, dict):
        errors.append(f"{path}: packaged component contract is invalid")
        return
    for name in sorted(set(params) - set(parameter_contracts)):
        errors.append(f"{path}.params: unknown field {name!r}")
    for name, parameter in parameter_contracts.items():
        if not isinstance(parameter, dict):
            errors.append(f"{path}.params.{name}: packaged contract is invalid")
            continue
        if parameter.get("required") and name not in params:
            errors.append(f"{path}.params: missing required field {name!r}")
        elif name in params:
            _check_parameter(
                params[name],
                contract=parameter,
                params=params,
                path=f"{path}.params.{name}",
                errors=errors,
            )
    if component.get("kind") == "chart":
        labels = component.get("labels", {})
        if labels.get("axisTitle") == "required" and not params.get("axisTitles"):
            errors.append(f"{path}.params: chart requires axis titles")
        if labels.get("unit") == "required" and not params.get("units"):
            errors.append(f"{path}.params: chart requires units")


def _variant_content(value: dict[str, Any]) -> str:
    payload = {key: value.get(key) for key in ("html", "component", "params")}
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _check_variant(
    value: Any,
    *,
    unit_kind: Any,
    relationship: Any,
    spec_version: str,
    path: str,
    errors: list[str],
    source_preview: bool = False,
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected an object")
        return
    fields = {"html", "component", "params", "axis", "why"}
    required = {"axis", "why"}
    if spec_version == SPEC_VERSION:
        fields.add("encoding")
        required.add("encoding")
    _check_keys(
        value,
        allowed=fields,
        required=required,
        path=path,
        errors=errors,
    )
    _check_enum(value.get("axis"), AXES, f"{path}.axis", errors)
    _check_string(value.get("why"), f"{path}.why", errors)
    if spec_version == SPEC_VERSION:
        _check_string(value.get("encoding"), f"{path}.encoding", errors)
    if source_preview:
        if {"html", "component", "params"} & set(value):
            errors.append(
                f"{path}: sourcePreview content is derived from its source record; "
                "do not provide html, component or params"
            )
        return
    has_html = "html" in value
    has_component = "component" in value
    if has_html == has_component:
        errors.append(f"{path}: expected exactly one of 'html' or 'component'")
        return
    if has_html:
        _check_string(value.get("html"), f"{path}.html", errors)
        if "params" in value:
            errors.append(f"{path}.params: unknown field for an HTML variant")
        if unit_kind == "figure":
            errors.append(f"{path}: a figure variant requires a component")
    else:
        if unit_kind != "figure":
            errors.append(f"{path}: only a figure variant may name a component")
        _check_component(
            value.get("component"),
            value.get("params"),
            relationship,
            path,
            errors,
        )


def _check_decision_fields(
    value: dict[str, Any], *, path: str, errors: list[str]
) -> None:
    decision_fields = {
        "question",
        "selection_mode",
        "allow_custom",
        "allow_note",
        "options",
    }
    if value.get("kind") != "decision":
        for name in sorted(decision_fields & set(value)):
            errors.append(f"{path}.{name}: allowed only for a decision unit")
        return
    if "detail" in value:
        errors.append(
            f"{path}.detail: a decision unit must not use a unit-level popup target"
        )
    for name in sorted(decision_fields - set(value)):
        errors.append(f"{path}: missing required decision field {name!r}")
    _check_string(value.get("question"), f"{path}.question", errors)
    _check_enum(
        value.get("selection_mode"),
        SELECTION_MODES,
        f"{path}.selection_mode",
        errors,
    )
    for name in ("allow_custom", "allow_note"):
        if not isinstance(value.get(name), bool):
            errors.append(f"{path}.{name}: expected a boolean")
    options = value.get("options")
    if not isinstance(options, list):
        errors.append(f"{path}.options: expected an array")
        return
    if len(options) < 2:
        errors.append(f"{path}.options: expected at least 2 items")
    keys: set[str] = set()
    for index, option in enumerate(options):
        option_path = f"{path}.options[{index}]"
        if not isinstance(option, dict):
            errors.append(f"{option_path}: expected an object")
            continue
        _check_keys(
            option,
            allowed={"key", "label", "consequence"},
            required={"key", "label", "consequence"},
            path=option_path,
            errors=errors,
        )
        for name in ("key", "label", "consequence"):
            _check_string(option.get(name), f"{option_path}.{name}", errors)
        key = option.get("key")
        if isinstance(key, str):
            if key in keys:
                errors.append(f"{option_path}.key: duplicate option key {key!r}")
            keys.add(key)


def _check_unit(
    value: Any, index: int, errors: list[str], *, spec_version: str
) -> None:
    path = f"$.units[{index}]"
    if not isinstance(value, dict):
        errors.append(f"{path}: expected an object")
        return
    fields = {
        "id",
        "kind",
        "role",
        "claim",
        "relationship",
        "candidates",
        "variants",
        "placeholder",
        "evidence",
        "detail",
        "detailAnchor",
        "single",
        "sourcePreview",
    }
    required = {
        "id",
        "kind",
        "claim",
        "relationship",
        "candidates",
        "variants",
        "placeholder",
    }
    if spec_version == SPEC_VERSION:
        fields |= {
            "claimRefs",
            "question",
            "selection_mode",
            "allow_custom",
            "allow_note",
            "options",
        }
        required.add("claimRefs")
    _check_keys(value, allowed=fields, required=required, path=path, errors=errors)
    _check_string(value.get("id"), f"{path}.id", errors)
    _check_enum(value.get("kind"), KINDS, f"{path}.kind", errors)
    if "role" in value:
        _check_enum(value.get("role"), ROLES, f"{path}.role", errors)
    _check_string(value.get("claim"), f"{path}.claim", errors)
    _check_enum(
        value.get("relationship"), RELATIONSHIPS, f"{path}.relationship", errors
    )
    _check_string_list(value.get("candidates"), f"{path}.candidates", errors, minimum=1)
    _check_string(value.get("placeholder"), f"{path}.placeholder", errors)
    if "evidence" in value:
        _check_string_list(value.get("evidence"), f"{path}.evidence", errors)
    if "detail" in value:
        _check_string(value.get("detail"), f"{path}.detail", errors)
    if "sourcePreview" in value:
        if (
            value["sourcePreview"] is not True
            or value.get("kind") != "evidence"
            or not _nonempty(value.get("detail"))
        ):
            errors.append(
                f"{path}.sourcePreview: requires true on an evidence unit with detail"
            )
    if "detailAnchor" in value:
        anchor = value["detailAnchor"]
        _check_string(anchor, f"{path}.detailAnchor", errors)
        if value.get("kind") != "text" or not _nonempty(value.get("detail")):
            errors.append(f"{path}.detailAnchor: requires a text unit with detail")
        if isinstance(anchor, str):
            if len(anchor) > 64 or len(anchor.split()) > 8:
                errors.append(
                    f"{path}.detailAnchor: use a short phrase "
                    "(at most eight words / 64 characters)"
                )
            variants_for_anchor = value.get("variants")
            for variant in (
                variants_for_anchor.values()
                if isinstance(variants_for_anchor, dict)
                else []
            ):
                if not isinstance(variant, dict) or not isinstance(
                    variant.get("html"), str
                ):
                    continue
                parser = _SurfaceGrammarParser()
                parser.feed(variant.get("html", ""))
                if sum(chunk.count(anchor) for chunk in parser.text_chunks) != 1:
                    errors.append(
                        f"{path}.detailAnchor: must match exactly one "
                        "unbroken phrase in each variant"
                    )
    if "claimRefs" in value:
        _check_string_list(
            value.get("claimRefs"), f"{path}.claimRefs", errors, minimum=1
        )
    if spec_version == SPEC_VERSION:
        _check_decision_fields(value, path=path, errors=errors)
    single = value.get("single", False)
    if not isinstance(single, bool):
        errors.append(f"{path}.single: expected a boolean")
        single = False
    if single and not (
        value.get("kind") in {"evidence", "decision"}
        or (value.get("kind") == "text" and value.get("role") in SINGLE_TEXT_ROLES)
    ):
        errors.append(
            f"{path}.single: allowed only for evidence, decision, or text "
            "with role scope, matter, or expected"
        )
    variants = value.get("variants")
    if not isinstance(variants, dict):
        errors.append(f"{path}.variants: expected an object")
        return
    global_approach_unit = spec_version == SPEC_VERSION
    _check_keys(
        variants,
        allowed={"a"} if global_approach_unit else {"a", "b"},
        required={"a"} if global_approach_unit or single else {"a", "b"},
        path=f"{path}.variants",
        errors=errors,
    )
    wanted = 1 if global_approach_unit or single else 2
    if len(variants) != wanted:
        errors.append(
            f"{path}.variants: expected exactly {wanted} variant"
            f"{'' if wanted == 1 else 's'}, got {len(variants)}"
        )
    for name, variant in variants.items():
        _check_variant(
            variant,
            unit_kind=value.get("kind"),
            relationship=value.get("relationship"),
            spec_version=spec_version,
            path=f"{path}.variants.{name}",
            errors=errors,
            source_preview=value.get("sourcePreview") is True,
        )
    a = variants.get("a")
    b = variants.get("b")
    if isinstance(a, dict) and isinstance(b, dict):
        if a.get("axis") == b.get("axis") and _variant_content(a) == _variant_content(
            b
        ):
            errors.append(
                f"{path}.variants: variants sharing axis {a.get('axis')!r} "
                "have identical content"
            )


def _check_exhibit(value: Any, path: str, errors: list[str]) -> None:
    """Validate inert supplied PNG/JPEG bytes, not the truth of their provenance."""
    if not isinstance(value, dict):
        errors.append(f"{path}: expected an object")
        return
    fields = {
        "data",
        "sha256",
        "sourceSha256",
        "locator",
        "captureMethod",
        "capturedAt",
        "alt",
    }
    _check_keys(value, allowed=fields, required=fields, path=path, errors=errors)
    for field in fields:
        _check_string(value.get(field), f"{path}.{field}", errors)
    for field in ("sha256", "sourceSha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(value.get(field, ""))):
            errors.append(f"{path}.{field}: expected a lowercase SHA-256 digest")
    data = value.get("data")
    if not isinstance(data, str) or len(data) > 5_600_000:
        errors.append(f"{path}.data: expected an embedded PNG/JPEG under 4 MiB")
        return
    match = re.fullmatch(r"data:image/(png|jpeg);base64,([A-Za-z0-9+/]+={0,2})", data)
    if not match:
        errors.append(f"{path}.data: only base64 PNG/JPEG images are allowed")
        return
    try:
        raw = base64.b64decode(match[2], validate=True)
    except (binascii.Error, ValueError):
        errors.append(f"{path}.data: invalid base64")
        return
    valid_signature = (
        raw.startswith(b"\x89PNG\r\n\x1a\n") and raw.endswith(b"IEND\xaeB`\x82")
        if match[1] == "png"
        else raw.startswith(b"\xff\xd8\xff") and raw.endswith(b"\xff\xd9")
    )
    if not valid_signature or len(raw) > 4 * 1024 * 1024:
        errors.append(f"{path}.data: invalid image signature or image exceeds 4 MiB")
    if hashlib.sha256(raw).hexdigest() != value.get("sha256"):
        errors.append(f"{path}.sha256: digest does not match the supplied image bytes")


def _check_evidence(value: Any, errors: list[str], *, spec_version: str) -> None:
    path = "$.evidence"
    if not isinstance(value, list):
        errors.append(f"{path}: expected an array")
        return
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_path}: expected an object")
            continue
        v2_fields = {"id", "cite", "locator", "status"}
        v3_fields = v2_fields | {
            "sourceId",
            "claimRefs",
            "detail",
            "original",
            "popup",
        }
        fields = v3_fields if spec_version == SPEC_VERSION else v2_fields
        _check_keys(
            item,
            allowed=fields
            | ({"excerpt", "exhibit"} if spec_version == SPEC_VERSION else set()),
            required=fields,
            path=item_path,
            errors=errors,
        )
        for name in ("id", "cite", "locator"):
            _check_string(item.get(name), f"{item_path}.{name}", errors)
        _check_enum(
            item.get("status"),
            SOURCE_STATUSES,
            f"{item_path}.status",
            errors,
        )
        if spec_version != SPEC_VERSION:
            continue
        if "excerpt" in item:
            _check_string(item["excerpt"], f"{item_path}.excerpt", errors)
        if "exhibit" in item:
            _check_exhibit(item["exhibit"], f"{item_path}.exhibit", errors)
        _check_string(item.get("sourceId"), f"{item_path}.sourceId", errors)
        _check_string_list(
            item.get("claimRefs"),
            f"{item_path}.claimRefs",
            errors,
            minimum=1,
        )
        _check_string(item.get("detail"), f"{item_path}.detail", errors)
        popup = item.get("popup")
        if not isinstance(popup, dict):
            errors.append(f"{item_path}.popup: expected an object")
        else:
            _check_keys(
                popup,
                allowed={"type", "title", "lede", "sections"},
                required={"type", "title", "sections"},
                path=f"{item_path}.popup",
                errors=errors,
            )
            _check_enum(
                popup.get("type"),
                POPUP_TYPES,
                f"{item_path}.popup.type",
                errors,
            )
            _check_string(popup.get("title"), f"{item_path}.popup.title", errors)
            if "lede" in popup:
                _check_string(popup.get("lede"), f"{item_path}.popup.lede", errors)
            sections = popup.get("sections")
            if not isinstance(sections, list):
                errors.append(f"{item_path}.popup.sections: expected an array")
            elif not sections:
                errors.append(f"{item_path}.popup.sections: expected at least 1 item")
            else:
                for section_index, section in enumerate(sections):
                    section_path = f"{item_path}.popup.sections[{section_index}]"
                    if not isinstance(section, dict):
                        errors.append(f"{section_path}: expected an object")
                        continue
                    _check_keys(
                        section,
                        allowed={"heading", "body"},
                        required={"heading", "body"},
                        path=section_path,
                        errors=errors,
                    )
                    _check_string(
                        section.get("heading"), f"{section_path}.heading", errors
                    )
                    _check_string(section.get("body"), f"{section_path}.body", errors)
        original = item.get("original")
        if not isinstance(original, dict):
            errors.append(f"{item_path}.original: expected an object")
            continue
        _check_keys(
            original,
            allowed={"availability", "href", "label"},
            required={"availability", "label"},
            path=f"{item_path}.original",
            errors=errors,
        )
        availability = original.get("availability")
        _check_enum(
            availability,
            ORIGINAL_AVAILABILITY,
            f"{item_path}.original.availability",
            errors,
        )
        _check_string(original.get("label"), f"{item_path}.original.label", errors)
        if availability == "linked":
            href = original.get("href")
            _check_string(href, f"{item_path}.original.href", errors)
            if _safe_http_link(href) is None:
                errors.append(
                    f"{item_path}.original.href: expected an absolute HTTP(S) URL"
                )
        elif "href" in original:
            errors.append(
                f"{item_path}.original.href: unavailable sources must not carry a link"
            )


def _id_map(value: Any, path: str, errors: list[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(value, list):
        return result
    for index, item in enumerate(value):
        if not isinstance(item, dict) or not _nonempty(item.get("id")):
            continue
        item_id = item["id"]
        if item_id in result:
            errors.append(f"{path}[{index}].id: duplicate ID {item_id!r}")
        else:
            result[item_id] = item
    return result


def _component_minimum_span(
    unit: dict[str, Any], *, spec_version: str = SPEC_VERSION
) -> int:
    """Return the desktop grid footprint needed to keep a figure legible.

    Wide components are deliberately rejected in narrow desktop placements. A
    responsive phone layout may still choose the component's narrow renderer;
    the guard prevents an accidental eight-column desktop placement from
    silently becoming a page-height mobile diagram.

    V4's fixed-type layout supports a seven-column figure beside five-column
    prose for modest flows and hierarchies using their narrow renderer. Dense
    stage/branch counts retain a full-width requirement; this is not a general
    reduction of every figure's physical footprint. Browser fit and label-size
    checks still determine whether an authored page actually fits.
    """

    required = 1
    modest_flow_span = 7 if spec_version == SPEC_VERSION_V4 else 8
    variants = unit.get("variants")
    if not isinstance(variants, dict):
        return required
    for variant in variants.values():
        if not isinstance(variant, dict):
            continue
        component = variant.get("component")
        params = variant.get("params")
        params = params if isinstance(params, dict) else {}
        if component == "flow":
            count = (
                len(params.get("stages", []))
                if isinstance(params.get("stages"), list)
                else 0
            )
            required = max(required, 12 if count >= 5 else modest_flow_span)
        elif component == "hierarchy":
            count = (
                len(params.get("branches", []))
                if isinstance(params.get("branches"), list)
                else 0
            )
            required = max(required, 12 if count >= 3 else modest_flow_span)
        elif component == "timeline":
            count = (
                len(params.get("marks", []))
                if isinstance(params.get("marks"), list)
                else 0
            )
            required = max(
                required,
                5
                if params.get("orientation") == "vertical"
                else 10
                if count >= 4
                else 8,
            )
        elif component in {"zones", "beforeAfter", "compareTwo", "figurePath"}:
            required = max(required, 10)
        elif component:
            required = max(required, 6)
    return required


def _check_v3_links(payload: dict[str, Any], errors: list[str]) -> None:
    units = _id_map(payload.get("units"), "$.units", errors)
    claims = _id_map(payload.get("claims"), "$.claims", errors)
    evidence = _id_map(payload.get("evidence"), "$.evidence", errors)
    brief = payload.get("brief")
    sources = _id_map(
        brief.get("sources") if isinstance(brief, dict) else None,
        "$.brief.sources",
        errors,
    )

    unit_claims: dict[str, set[str]] = {}
    unit_evidence: dict[str, set[str]] = {}
    overview = payload.get("overview")
    topic_ids = (
        {
            item.get("unitId")
            for item in overview.get("topics", [])
            if isinstance(item, dict) and isinstance(item.get("unitId"), str)
        }
        if isinstance(overview, dict) and isinstance(overview.get("topics"), list)
        else set()
    )
    for unit_id, unit in units.items():
        refs = (
            set(unit.get("claimRefs", []))
            if isinstance(unit.get("claimRefs"), list)
            else set()
        )
        unit_claims[unit_id] = refs
        evidence_refs = (
            set(unit.get("evidence", []))
            if isinstance(unit.get("evidence"), list)
            else set()
        )
        unit_evidence[unit_id] = evidence_refs
        for claim_id in sorted(refs - set(claims)):
            errors.append(
                f"$.units[{unit_id!r}].claimRefs: unknown claim ID {claim_id!r}"
            )
        for claim_id in sorted(refs & set(claims)):
            claim = claims[claim_id]
            if claim.get("kind") == "material" and claim.get("placement") != "surface":
                errors.append(
                    f"$.units[{unit_id!r}].claimRefs: material claim {claim_id!r} "
                    "is not placed on the surface"
                )
        for evidence_id in evidence_refs:
            if evidence_id not in evidence:
                errors.append(
                    f"$.units[{unit_id!r}].evidence: unknown evidence ID "
                    f"{evidence_id!r}"
                )
        detail_id = unit.get("detail")
        if detail_id is not None and detail_id not in evidence:
            errors.append(
                f"$.units[{unit_id!r}].detail: unknown popup/evidence ID {detail_id!r}"
            )
        if (
            unit.get("kind") == "card"
            and evidence_refs
            and not _nonempty(detail_id)
            and unit_id not in topic_ids
        ):
            errors.append(
                f"$.units[{unit_id!r}].detail: an evidence-grounded card must "
                "open one purpose-specific popup from the whole card"
            )
    reachable_evidence = (
        set().union(*unit_evidence.values()) if unit_evidence else set()
    )

    for claim_id, claim in claims.items():
        source_ids = set(claim.get("sourceIds", []))
        for source_id in sorted(source_ids - set(sources)):
            errors.append(
                f"$.claims[{claim_id!r}].sourceIds: unknown source ID {source_id!r}"
            )
        evidence_ids = set(claim.get("evidenceIds", []))
        for evidence_id in sorted(evidence_ids - set(evidence)):
            errors.append(
                f"$.claims[{claim_id!r}].evidenceIds: unknown evidence ID "
                f"{evidence_id!r}"
            )
        for evidence_id in sorted(evidence_ids & set(evidence)):
            evidence_claims = evidence[evidence_id].get("claimRefs", [])
            if claim_id not in evidence_claims:
                errors.append(
                    f"$.claims[{claim_id!r}].evidenceIds: evidence "
                    f"{evidence_id!r} does not point back to this claim"
                )
        if claim.get("placement") == "surface":
            carriers = [
                unit_id for unit_id, refs in unit_claims.items() if claim_id in refs
            ]
            if not carriers:
                errors.append(
                    f"$.claims[{claim_id!r}]: surface claim is not carried by any unit"
                )
            for unit_id in carriers:
                missing = evidence_ids - unit_evidence.get(unit_id, set())
                if missing:
                    errors.append(
                        f"$.units[{unit_id!r}].evidence: surface claim "
                        f"{claim_id!r} requires reachable evidence IDs "
                        f"{sorted(missing)!r}"
                    )
        if claim.get("kind") == "material" and claim.get("placement") != "omitted":
            evidence_backlinks = {
                evidence_id
                for evidence_id, item in evidence.items()
                if isinstance(item.get("claimRefs"), list)
                and claim_id in item["claimRefs"]
            }
            if not reachable_evidence & (evidence_ids | evidence_backlinks):
                errors.append(
                    f"$.claims[{claim_id!r}]: presented material claim has no "
                    "evidence path reachable from a surface unit"
                )

    for evidence_id, item in evidence.items():
        source_id = item.get("sourceId")
        if source_id not in sources:
            errors.append(
                f"$.evidence[{evidence_id!r}].sourceId: unknown source ID {source_id!r}"
            )
        refs = set(item.get("claimRefs", []))
        for claim_id in sorted(refs - set(claims)):
            errors.append(
                f"$.evidence[{evidence_id!r}].claimRefs: unknown claim ID {claim_id!r}"
            )

    approaches = _spec_approaches(payload)
    seen: set[str] = set()
    structure_dimensions: dict[str, dict[str, Any]] = {}
    approach_keys = (
        ("a",) if payload.get("schemaVersion") == SPEC_VERSION_V4 else ("a", "b")
    )
    approach_units: dict[str, set[str]] = {key: set() for key in approach_keys}
    if isinstance(approaches, dict):
        for approach_key in approach_keys:
            approach = approaches.get(approach_key)
            composition = (
                approach.get("composition") if isinstance(approach, dict) else None
            )
            sections = (
                composition.get("sections") if isinstance(composition, dict) else None
            )
            if not isinstance(sections, list):
                continue
            section_grouping: list[int] = []
            semantic_sequence: list[tuple[Any, Any]] = []
            figure_architecture: list[Any] = []
            placement_topology: list[tuple[Any, ...]] = []
            title_placements: list[dict[str, Any]] = []
            for section in sections:
                if not isinstance(section, dict):
                    continue
                placements = (
                    section.get("layout", {}).get("placements", [])
                    if isinstance(section.get("layout"), dict)
                    else []
                )
                signature_placements: list[Any] = []
                for placement in placements:
                    if not isinstance(placement, dict):
                        continue
                    unit_id = placement.get("unitId")
                    if not isinstance(unit_id, str):
                        continue
                    path = f"$.approaches.{approach_key}.composition.sections"
                    if unit_id not in units:
                        errors.append(f"{path}: unknown unit ID {unit_id!r}")
                        continue
                    if unit_id in seen:
                        errors.append(
                            f"{path}: unit ID {unit_id!r} appears in more than one "
                            "page approach"
                        )
                    seen.add(unit_id)
                    approach_units[approach_key].add(unit_id)
                    unit = units[unit_id]
                    minimum_span = _component_minimum_span(
                        unit, spec_version=payload.get("schemaVersion", SPEC_VERSION)
                    )
                    recipe = section.get("issueLayout")
                    if (
                        payload.get("schemaVersion") == SPEC_VERSION_V4
                        and isinstance(recipe, dict)
                        and isinstance(recipe.get("supportUnitIds"), list)
                        and unit_id in recipe.get("supportUnitIds", [])
                    ):
                        # The issue recipe intentionally owns a half-width
                        # support frame; registered narrow renderers retain all
                        # source facts. Browser page-fit still gates export.
                        minimum_span = min(minimum_span, 6)
                    span = placement.get("span")
                    if (
                        unit.get("kind") == "figure"
                        and isinstance(span, int)
                        and span < minimum_span
                    ):
                        errors.append(
                            f"{path}: figure unit {unit_id!r} requires span "
                            f"{minimum_span} for its selected component footprint; "
                            f"received {span}"
                        )
                    if unit.get("role") == "title":
                        title_placements.append(placement)
                    variants = unit.get("variants")
                    variant = variants.get("a") if isinstance(variants, dict) else None
                    component = (
                        variant.get("component") if isinstance(variant, dict) else None
                    )
                    row = placement.get("row")
                    column = placement.get("column")
                    signature_placements.append(
                        (
                            row if isinstance(row, int) else 10**9,
                            column if isinstance(column, int) else 10**9,
                            unit_id,
                            (
                                row,
                                column,
                                placement.get("span"),
                                placement.get("rowSpan", 1),
                            ),
                            (unit.get("relationship"), unit.get("role")),
                            component if unit.get("kind") == "figure" else None,
                        )
                    )
                signature_placements.sort(key=lambda item: item[:3])
                section_grouping.append(len(signature_placements))
                placement_topology.append(
                    tuple(item[3] for item in signature_placements)
                )
                semantic_sequence.extend(item[4] for item in signature_placements)
                figure_architecture.extend(
                    item[5] for item in signature_placements if item[5] is not None
                )
            if len(title_placements) != 1:
                errors.append(
                    f"$.approaches.{approach_key}: expected exactly one title unit"
                )
            elif not (
                title_placements[0].get("row") == 1
                and title_placements[0].get("column") == 1
                and title_placements[0].get("span") == 12
            ):
                errors.append(
                    f"$.approaches.{approach_key}: title must occupy row 1, "
                    "column 1, span 12"
                )
            structure_dimensions[approach_key] = {
                "section_grouping": tuple(section_grouping),
                "semantic_sequence": tuple(semantic_sequence),
                "figure_architecture": tuple(figure_architecture),
                "placement_topology": tuple(placement_topology),
            }
    dimension_labels = {
        "section_grouping": "section grouping",
        "semantic_sequence": "semantic relationship/role sequence",
        "figure_architecture": "dominant figure/component architecture",
        "placement_topology": "placement topology",
    }
    if "a" in structure_dimensions and "b" in structure_dimensions:
        differing_dimensions = [
            label
            for key, label in dimension_labels.items()
            if structure_dimensions["a"].get(key) != structure_dimensions["b"].get(key)
        ]
        if len(differing_dimensions) < 2:
            observed = ", ".join(differing_dimensions) or "none"
            errors.append(
                "$.approaches: A and B must use materially different information "
                "structures across at least two independent structural dimensions; "
                f"differences found: {observed}"
            )
    for unit_id in sorted(set(units) - seen):
        errors.append(f"$.approaches: unit ID {unit_id!r} is not placed")

    material = [claim for claim in claims.values() if claim.get("kind") == "material"]
    surface_ids = {
        claim["id"] for claim in material if claim.get("placement") == "surface"
    }
    for approach_key, placed_ids in approach_units.items():
        popup_targets = {
            detail_id
            for unit_id in placed_ids
            for detail_id, _ in _unit_popup_targets(units[unit_id], unit_id=unit_id)
            if detail_id in evidence
        }
        for claim_id, claim in sorted(claims.items()):
            if claim.get("kind") != "material" or claim.get("placement") == "omitted":
                continue
            claim_evidence = set(claim.get("evidenceIds", []))
            claim_evidence.update(
                evidence_id
                for evidence_id, item in evidence.items()
                if isinstance(item.get("claimRefs"), list)
                and claim_id in item["claimRefs"]
            )
            if not popup_targets & claim_evidence:
                errors.append(
                    f"$.approaches.{approach_key}: presented material claim "
                    f"{claim_id!r} has no actual popup target for its evidence "
                    "within this approach"
                )
        for claim_id in sorted(surface_ids):
            if not any(
                claim_id in unit_claims.get(unit_id, set()) for unit_id in placed_ids
            ):
                errors.append(
                    f"$.approaches.{approach_key}: surface claim {claim_id!r} "
                    "is not carried on this page"
                )
    if len(material) >= 3:
        substantive_units = {
            unit_id for unit_id, refs in unit_claims.items() if refs & surface_ids
        }
        if len(surface_ids) < 2 or len(substantive_units) < 2:
            errors.append(
                "$.claims: materially richer records need at least two distinct "
                "surface claims in two units; a one-sentence treatment is too thin"
            )

    purpose = brief.get("purpose") if isinstance(brief, dict) else None
    if purpose in {"decide", "choose"}:
        for approach_key, placed_ids in approach_units.items():
            actionable = any(
                units[unit_id].get("role") == "action"
                and bool(unit_claims.get(unit_id, set()) & surface_ids)
                for unit_id in placed_ids
            )
            if not actionable:
                errors.append(
                    f"$.approaches.{approach_key}: purpose {purpose!r} requires "
                    "an action unit tied to a surface material claim"
                )
    elif purpose == "understand":
        for approach_key, placed_ids in approach_units.items():
            summarized = any(
                units[unit_id].get("role") in {"summary", "answer"}
                and bool(unit_claims.get(unit_id, set()) & surface_ids)
                for unit_id in placed_ids
            )
            if not summarized:
                errors.append(
                    f"$.approaches.{approach_key}: purpose 'understand' requires "
                    "a summary or answer unit tied to a surface material claim"
                )


def _iter_parameter_detail_targets(value: Any, *, path: str) -> list[tuple[str, str]]:
    """Return popup targets declared inside one component parameter tree."""
    targets: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key.casefold().endswith("detail") and _nonempty(child):
                targets.append((child.strip(), child_path))
            elif isinstance(child, (dict, list)):
                targets.extend(_iter_parameter_detail_targets(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, (dict, list)):
                targets.extend(
                    _iter_parameter_detail_targets(child, path=f"{path}[{index}]")
                )
    return targets


def _unit_popup_targets(unit: dict[str, Any], *, unit_id: str) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    detail = unit.get("detail")
    if _nonempty(detail):
        targets.append((detail.strip(), f"$.units[{unit_id!r}].detail"))
    variants = unit.get("variants")
    if not isinstance(variants, dict):
        return targets
    for variant_key, variant in variants.items():
        if not isinstance(variant, dict) or "component" not in variant:
            continue
        params = variant.get("params")
        targets.extend(
            _iter_parameter_detail_targets(
                params,
                path=f"$.units[{unit_id!r}].variants.{variant_key}.params",
            )
        )
    return targets


def _normalise_chrome_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _is_generic_popup_title(value: Any) -> bool:
    if not _nonempty(value):
        return False
    normalized = re.sub(r"[\s:·|—–_-]+", " ", value.strip().casefold()).strip()
    if normalized in GENERIC_POPUP_TITLES:
        return True
    return bool(
        re.fullmatch(
            r"evidence(?: (?:supplied|verified|retrieved|unavailable))?",
            normalized,
        )
    )


def _generic_surface_text_violations(values: list[str]) -> list[str]:
    violations: list[str] = []
    visible_strings = {
        _normalise_chrome_text(text) for text in values if _normalise_chrome_text(text)
    }
    for text in sorted(visible_strings):
        if text in {"evidence", "view evidence", "more detail"} or re.fullmatch(
            r"evidence\s*[·|:—–-]\s*[a-z][a-z -]*", text
        ):
            violations.append(
                f"surface copy contains generic disclosure label {text!r}"
            )
        if re.match(r"^source\s*:", text):
            violations.append(
                "surface copy contains a Source: row; source identity belongs "
                "in the purpose-specific popup"
            )
        if re.fullmatch(
            r"(?:evidence\s*[·|:—–-]?\s*)?\d+\s*(?:of|/)\s*(?:\d+|n)",
            text,
        ):
            violations.append(
                "surface copy contains a generic evidence position counter"
            )

    joined = " ".join(_normalise_chrome_text(text) for text in values)
    has_sequence_controls = bool(
        re.search(r"\bprevious(?: evidence)?\b", joined)
        and re.search(r"\bnext(?: evidence)?\b", joined)
    )
    has_sequence_context = bool(
        re.search(r"\bevidence\b", joined)
        or re.search(r"\b\d+\s*(?:of|/)\s*(?:\d+|n)\b", joined)
    )
    if has_sequence_controls and has_sequence_context:
        violations.append(
            "surface copy contains a generic Previous/Next evidence sequence"
        )
    return list(dict.fromkeys(violations))


def _surface_policy_violations(value: str) -> list[str]:
    parser = _SurfaceGrammarParser()
    parser.feed(value)
    parser.close()
    violations: list[str] = []
    if parser.has_anchor:
        violations.append(
            "surface HTML must not contain links; put source links in the "
            "purpose-specific popup"
        )
    for token in parser.class_tokens:
        lowered = token.casefold()
        marker = next(
            (
                candidate
                for candidate in FORBIDDEN_SURFACE_CLASS_MARKERS
                if candidate in lowered
            ),
            None,
        )
        if marker is not None:
            violations.append(
                f"surface class {token!r} uses forbidden {marker!r} chrome"
            )
    violations.extend(
        _generic_surface_text_violations([*parser.visible_strings, *parser.text_chunks])
    )
    return list(dict.fromkeys(violations))


def _iter_component_surface_text(value: Any, *, field: str = "") -> list[str]:
    """Return component strings that render as copy rather than popup IDs."""
    if field.casefold().endswith("detail"):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [
            text
            for key, child in value.items()
            for text in _iter_component_surface_text(child, field=key)
        ]
    if isinstance(value, list):
        return [
            text
            for child in value
            for text in _iter_component_surface_text(child, field=field)
        ]
    return []


def _check_v3_composition_grammar(payload: dict[str, Any], errors: list[str]) -> None:
    """Reject known generic-design regressions in new composed v3 pages."""
    approaches = _spec_approaches(payload)
    if not isinstance(approaches, dict):
        return
    composed: dict[str, dict[str, Any]] = {}
    for approach_key, approach in approaches.items():
        composition = (
            approach.get("composition") if isinstance(approach, dict) else None
        )
        if isinstance(composition, dict) and composition.get("strategy") == "composed":
            composed[approach_key] = composition
    if not composed:
        return

    unit_list = payload.get("units")
    units = (
        {
            item["id"]: item
            for item in unit_list
            if isinstance(item, dict) and _nonempty(item.get("id"))
        }
        if isinstance(unit_list, list)
        else {}
    )

    composed_unit_ids: set[str] = set()
    for composition in composed.values():
        sections = composition.get("sections")
        if not isinstance(sections, list):
            continue
        for section in sections:
            if not isinstance(section, dict):
                continue
            unit_ids = section.get("unitIds")
            if isinstance(unit_ids, list):
                composed_unit_ids.update(
                    unit_id for unit_id in unit_ids if isinstance(unit_id, str)
                )

    contracts = _component_contracts()
    for unit_id in sorted(composed_unit_ids):
        unit = units.get(unit_id)
        if not isinstance(unit, dict):
            continue
        if unit.get("kind") == "evidence" and not (
            payload.get("schemaVersion") == SPEC_VERSION_V4
            and unit.get("sourcePreview") is True
        ):
            errors.append(
                f"$.units[{unit_id!r}].kind: generic evidence surface units are "
                "not allowed in v3 composed plans; attach the source record to "
                "a semantic card or node and a purpose-specific popup"
            )
        variants = unit.get("variants")
        if not isinstance(variants, dict):
            continue
        for variant_key, variant in variants.items():
            if not isinstance(variant, dict):
                continue
            path = f"$.units[{unit_id!r}].variants.{variant_key}.html"
            if _nonempty(variant.get("html")):
                for violation in _surface_policy_violations(variant["html"]):
                    errors.append(f"{path}: {violation}")
            elif "component" in variant:
                component_id = variant["component"]
                if (
                    isinstance(component_id, str)
                    and contracts.get(component_id, {}).get("recommended") is False
                ):
                    errors.append(
                        f"$.units[{unit_id!r}].variants.{variant_key}.component: "
                        f"{component_id!r} is a legacy rendering component, "
                        "not a new-design choice; choose a recommended "
                        "relationship form or plain text/table unit"
                    )
                params_path = f"$.units[{unit_id!r}].variants.{variant_key}.params"
                for violation in _generic_surface_text_violations(
                    _iter_component_surface_text(variant.get("params"))
                ):
                    errors.append(f"{params_path}: {violation}")

    evidence_list = payload.get("evidence")
    if isinstance(evidence_list, list):
        for index, item in enumerate(evidence_list):
            popup = item.get("popup") if isinstance(item, dict) else None
            if isinstance(popup, dict) and _is_generic_popup_title(popup.get("title")):
                errors.append(
                    f"$.evidence[{index}].popup.title: expected a "
                    "purpose-specific title, not generic disclosure chrome"
                )


def _check_card_hub(payload: dict[str, Any], errors: list[str]) -> None:
    composition = payload.get("composition")
    if not isinstance(composition, dict):
        return
    sections = composition.get("sections", [])
    if not isinstance(sections, list):
        return
    overview = payload.get("overview", {})
    raw_units = payload.get("units", [])
    units = (
        {
            unit["id"]: unit
            for unit in raw_units
            if isinstance(unit, dict) and isinstance(unit.get("id"), str)
        }
        if isinstance(raw_units, list)
        else {}
    )
    for section in sections:
        if not isinstance(section, dict) or section.get("presentation") != "card-hub":
            continue
        path = "$.composition.sections: card-hub"
        if (
            not isinstance(payload.get("brief"), dict)
            or payload["brief"].get("form") != "one-page"
            or len(sections) != 1
            or "issueLayout" in section
            or not isinstance(overview, dict)
            or section.get("id") != overview.get("sectionId")
        ):
            errors.append(f"{path}: requires the sole one-page overview section")
            continue
        intro = overview.get("contextUnitIds", [])
        if not isinstance(intro, list):
            continue
        intro = intro + [overview.get("questionUnitId"), overview.get("answerUnitId")]
        ids = section.get("unitIds", [])
        if not isinstance(ids, list) or not all(isinstance(uid, str) for uid in ids):
            continue
        cards = [
            units.get(uid, {})
            for uid in ids
            if units.get(uid, {}).get("kind") == "card"
        ]
        if len(cards) != 5 or cards[-1].get("role") != "action":
            errors.append(
                f"{path}: requires four peer cards followed by one action card"
            )
        else:
            ordered = [ids[0], *intro, *(card["id"] for card in cards)]
            scope = [uid for uid in ids if units.get(uid, {}).get("role") == "scope"]
            if ids != ordered + scope or len(scope) > 1:
                errors.append(
                    f"{path}: order title, intro, peer cards, action, optional scope"
                )
        layout = section.get("layout")
        placements = layout.get("placements", []) if isinstance(layout, dict) else []
        if isinstance(placements, list):
            for placement in placements:
                if (
                    isinstance(placement, dict)
                    and placement.get("unitId") in intro
                    and placement.get("row") != 2
                ):
                    errors.append(f"{path}: intro units must share row 2")
                if (
                    isinstance(placement, dict)
                    and placement.get("unitId") not in intro
                    and placement.get("row") == 2
                ):
                    errors.append(f"{path}: row 2 is reserved for the framing card")


def _check_issue_features(payload: dict[str, Any], errors: list[str]) -> None:
    units = (
        {
            item["id"]: item
            for item in payload.get("units", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if isinstance(payload.get("units"), list)
        else {}
    )
    evidence = (
        {
            item["id"]: item
            for item in payload.get("evidence", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if isinstance(payload.get("evidence"), list)
        else {}
    )
    for unit_id, unit in units.items():
        if "sourcePreview" not in unit:
            continue
        path = f"$.units[{unit_id!r}].sourcePreview"
        if payload.get("schemaVersion") != SPEC_VERSION_V4:
            errors.append(f"{path}: available only in v4")
        detail = unit.get("detail")
        source = evidence.get(detail) if isinstance(detail, str) else None
        if not isinstance(source, dict):
            errors.append(
                f"{path}: detail must reference an existing source evidence record"
            )
            continue
        popup = source.get("popup")
        if not isinstance(popup, dict) or popup.get("type") != "source":
            errors.append(f"{path}: the referenced popup must have type source")
        if not source.get("exhibit") and not _nonempty(source.get("excerpt")):
            errors.append(
                f"{path}: requires an explicit exact excerpt or authenticated "
                "exhibit; detail prose is not a source quotation"
            )

    composition = payload.get("composition")
    sections = composition.get("sections") if isinstance(composition, dict) else None
    for index, section in enumerate(sections if isinstance(sections, list) else []):
        if not isinstance(section, dict) or "issueLayout" not in section:
            continue
        path = f"$.composition.sections[{index}].issueLayout"
        recipe = section["issueLayout"]
        if not isinstance(recipe, dict):
            errors.append(f"{path}: expected an object")
            continue
        fields = {
            "findingUnitId",
            "implicationUnitId",
            "actionUnitId",
            "supportUnitIds",
        }
        _check_keys(recipe, allowed=fields, required=fields, path=path, errors=errors)
        analysis = [
            recipe.get(key)
            for key in ("findingUnitId", "implicationUnitId", "actionUnitId")
        ]
        for key, unit_id in zip(
            ("findingUnitId", "implicationUnitId", "actionUnitId"),
            analysis,
            strict=True,
        ):
            _check_string(unit_id, f"{path}.{key}", errors)
        support = recipe.get("supportUnitIds")
        _check_string_list(support, f"{path}.supportUnitIds", errors, minimum=1)
        if not isinstance(support, list) or not all(
            isinstance(item, str) for item in [*analysis, *support]
        ):
            continue
        if len(support) > 2:
            errors.append(f"{path}.supportUnitIds: expected one or two support units")
        body = [*analysis, *support]
        if len(body) != len(set(body)):
            errors.append(f"{path}: analysis and support IDs must all be distinct")
        ids = section.get("unitIds")
        if (
            not isinstance(ids, list)
            or not ids
            or not all(isinstance(item, str) for item in ids)
        ):
            continue
        if any(item not in ids or item not in units for item in body):
            errors.append(f"{path}: all referenced units must belong to this section")
        for unit_id in analysis:
            if units.get(unit_id, {}).get("kind") != "card":
                errors.append(f"{path}: analysis unit {unit_id!r} must be a card")
        if units.get(analysis[2], {}).get("role") != "action":
            errors.append(
                f"{path}.actionUnitId: the recommendation/next-check card "
                "must have role action"
            )
        for unit_id in support:
            unit = units.get(unit_id, {})
            if unit.get("kind") not in {"figure", "evidence"}:
                errors.append(
                    f"{path}: support unit {unit_id!r} must be figure or evidence"
                )
            if unit.get("kind") == "evidence" and unit.get("sourcePreview") is not True:
                errors.append(
                    f"{path}: evidence support {unit_id!r} must use sourcePreview"
                )
        if units.get(ids[0], {}).get("kind") != "text" or ids[0] in body:
            errors.append(
                f"{path}: the first section unit must be a separate text title/header"
            )
        expected = [ids[0], *body]
        remaining = [item for item in ids if item not in expected]
        if len(remaining) > 1 or any(
            units.get(item, {}).get("kind") != "text"
            or units.get(item, {}).get("role") != "scope"
            for item in remaining
        ):
            errors.append(
                f"{path}: only one optional scope-text footer may follow the recipe"
            )
        if ids != [*expected, *remaining]:
            errors.append(
                f"{path}: unitIds order must be header, finding, implication, "
                "action, supports, optional scope footer"
            )
        if section.get("layout") != _derive_issue_layout(section):
            errors.append(
                f"{path}: layout must match deterministic issue placements; "
                "omit layout to derive it"
            )
        brief_value = payload.get("brief")
        brief = brief_value if isinstance(brief_value, dict) else {}
        overview_value = payload.get("overview")
        overview = overview_value if isinstance(overview_value, dict) else {}
        if brief.get("form") != "slide-brief" or section.get("id") == overview.get(
            "sectionId"
        ):
            errors.append(
                f"{path}: issueLayout is for slide-brief detail pages "
                "after the overview"
            )


def validate_spec(payload: Any) -> list[str]:
    """Return path-qualified errors for one supported LegalDesign build spec."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["$: expected a JSON object"]
    payload = _normalize_issue_layouts(payload)
    version = payload.get("schemaVersion")
    version_text = version if isinstance(version, str) else ""
    is_v3 = version == SPEC_VERSION
    is_v4 = version == SPEC_VERSION_V4
    modern = is_v3 or is_v4
    validation_version = SPEC_VERSION if is_v4 else version_text
    fields = {"schemaVersion", "brief", "style", "units", "evidence"}
    if is_v3:
        fields |= {"approaches", "claims"}
    if is_v4:
        fields |= {"composition", "overview", "claims"}
    _check_keys(payload, allowed=fields, required=fields, path="$", errors=errors)
    if version not in {SPEC_VERSION_V2, SPEC_VERSION, SPEC_VERSION_V4}:
        errors.append(
            "$.schemaVersion: expected one of "
            f"{[SPEC_VERSION_V2, SPEC_VERSION, SPEC_VERSION_V4]!r}"
        )
    _check_brief(payload.get("brief"), errors, spec_version=version_text)
    _check_style(payload.get("style"), errors)
    if modern:
        if is_v4:
            _check_composition(payload.get("composition"), errors, allow_issue=True)
            _check_overview(payload, errors)
        else:
            _check_approaches(payload.get("approaches"), errors)
        _check_claims(payload.get("claims"), errors)
        style = payload.get("style")
        if isinstance(style, dict):
            source = style.get("source")
            reference = style.get("ref")
            if source == "loxoto" and reference is not None:
                errors.append("$.style.ref: Loxoto style must use null")
            if source in {"design-md", "template", "playbook"} and not _nonempty(
                reference
            ):
                errors.append(f"$.style.ref: style source {source!r} requires a path")
            approach_compositions = []
            approaches = _spec_approaches(payload)
            if isinstance(approaches, dict):
                approach_compositions = [
                    item.get("composition")
                    for item in approaches.values()
                    if isinstance(item, dict)
                ]
            if any(
                isinstance(composition, dict)
                and composition.get("strategy") == "composed"
                for composition in approach_compositions
            ) and source in {"template", "playbook"}:
                errors.append(
                    "$.style.source: composed strategy supports only 'loxoto' "
                    "or 'design-md'"
                )
    units = payload.get("units")
    if not isinstance(units, list):
        errors.append("$.units: expected an array")
    else:
        if not units:
            errors.append("$.units: expected at least 1 item")
        for index, unit in enumerate(units):
            _check_unit(unit, index, errors, spec_version=validation_version)
    _check_evidence(payload.get("evidence"), errors, spec_version=validation_version)
    _check_issue_features(payload, errors)
    _check_card_hub(payload, errors)
    if modern:
        _check_v3_links(payload, errors)
        _check_v3_composition_grammar(payload, errors)
    if is_v4:
        errors = [
            error.replace("$.approaches.a.composition", "$.composition")
            .replace("$.approaches.a", "$.composition")
            .replace("$.approaches", "$.composition")
            for error in errors
        ]
    return errors


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _skeleton(form: str, *, template: str | None = None) -> dict[str, Any]:
    strategy = "template-import" if template else "composed"
    if form not in V4_FORMS:
        raise ValueError(
            "new outputs use form one-page or slide-brief; "
            "older forms are template-import compatibility only"
        )
    result = {
        "schemaVersion": SPEC_VERSION_V4,
        "brief": {
            "title": "",
            "reader": "",
            "action": "",
            "purpose": "other",
            "message": "",
            "spine": "containment",
            "situation": "laptop",
            "form": form,
            "sources": [],
            "assumptions": [],
            "gaps": [],
        },
        "style": {"source": "loxoto", "ref": None},
        "composition": {
            "strategy": strategy,
            "shape": "",
            "rationale": "",
            "sections": [],
            "templateRef": template,
        },
        "overview": {
            "sectionId": "",
            "contextUnitIds": [],
            "questionUnitId": "",
            "answerUnitId": "",
            "topics": [],
        },
        "claims": [],
        "units": [],
        "evidence": [],
    }
    return result


def _ensure_new_file(path: Path, label: str) -> None:
    if path.exists():
        raise ValueError(f"{label} already exists; refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)


def _copy_new(source: Path, destination: Path) -> None:
    created = False
    try:
        with source.open("rb") as source_handle:
            with destination.open("xb") as output_handle:
                created = True
                shutil.copyfileobj(source_handle, output_handle)
    except OSError:
        if created:
            destination.unlink(missing_ok=True)
        raise


def _write_json_new(path: Path, payload: dict[str, Any]) -> None:
    created = False
    try:
        with path.open("x", encoding="utf-8") as handle:
            created = True
            handle.write(json.dumps(payload, indent=2) + "\n")
    except OSError:
        if created:
            path.unlink(missing_ok=True)
        raise


def _write_text_new(path: Path, value: str) -> None:
    created = False
    try:
        with path.open("x", encoding="utf-8") as handle:
            created = True
            handle.write(value)
    except OSError:
        if created:
            path.unlink(missing_ok=True)
        raise


def _safe_http_link(value: Any) -> str | None:
    if not _nonempty(value):
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


class _SurfaceGrammarParser(HTMLParser):
    """Collect authored surface semantics without changing the HTML allowlist."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.has_anchor = False
        self.class_tokens: list[str] = []
        self.text_chunks: list[str] = []
        self.visible_strings: list[str] = []
        self._text_frames: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag == "a":
            self.has_anchor = True
        for raw_name, raw_value in attrs:
            if raw_name.casefold() == "class" and raw_value:
                self.class_tokens.extend(raw_value.split())
        if tag not in VOID_FRAGMENT_TAGS:
            self._text_frames.append([])

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag == "a":
            self.has_anchor = True
        for raw_name, raw_value in attrs:
            if raw_name.casefold() == "class" and raw_value:
                self.class_tokens.extend(raw_value.split())

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in VOID_FRAGMENT_TAGS or not self._text_frames:
            return
        self.visible_strings.append("".join(self._text_frames.pop()))

    def handle_data(self, data: str) -> None:
        self.text_chunks.append(data)
        for frame in self._text_frames:
            frame.append(data)


class _InertFragmentParser(HTMLParser):
    """Fail-closed allowlist serialiser for authored visible copy."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.stack: list[str] = []

    def _attributes(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        result: list[str] = []
        seen: set[str] = set()
        href: str | None = None
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            if name in seen:
                raise ValueError(f"HTML fragment: duplicate attribute {name!r}")
            seen.add(name)
            value = raw_value or ""
            if name == "class":
                if not all(
                    re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", token)
                    for token in value.split()
                ):
                    raise ValueError("HTML fragment: invalid class token")
                result.append(f' class="{escape(value, quote=True)}"')
            elif name in {
                "aria-label",
                "data-card-title",
                "data-placeholder",
                "title",
            }:
                result.append(f' {name}="{escape(value, quote=True)}"')
            elif name == "data-editable":
                result.append(" data-editable")
            elif name == "href" and tag == "a":
                href = _safe_http_link(value)
                if href is None:
                    raise ValueError(
                        "HTML fragment: links must use an absolute HTTP(S) URL"
                    )
            elif name == "scope" and tag == "th":
                if value not in {"row", "col", "rowgroup", "colgroup"}:
                    raise ValueError("HTML fragment: invalid table-header scope")
                result.append(f' scope="{value}"')
            elif name in {"colspan", "rowspan"} and tag in {"td", "th"}:
                if not value.isdigit() or not 1 <= int(value) <= 20:
                    raise ValueError(f"HTML fragment: invalid {name}")
                result.append(f' {name}="{value}"')
            else:
                raise ValueError(
                    f"HTML fragment: attribute {name!r} is not allowed on <{tag}>"
                )
        if tag == "a":
            if href is None:
                raise ValueError("HTML fragment: <a> requires an HTTP(S) href")
            result.append(f' href="{escape(href, quote=True)}"')
            result.append(' target="_blank" rel="noopener noreferrer"')
        return "".join(result)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in ALLOWED_FRAGMENT_TAGS:
            raise ValueError(f"HTML fragment: tag <{tag}> is not allowed")
        rendered = self._attributes(tag, attrs)
        self.output.append(f"<{tag}{rendered}>")
        if tag not in VOID_FRAGMENT_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in VOID_FRAGMENT_TAGS:
            raise ValueError(
                f"HTML fragment: only void tags may self-close, got <{tag}>"
            )
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in VOID_FRAGMENT_TAGS:
            raise ValueError(f"HTML fragment: void tag </{tag}> must not close")
        if not self.stack or self.stack[-1] != tag:
            raise ValueError(f"HTML fragment: unmatched closing tag </{tag}>")
        self.stack.pop()
        self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.output.append(escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        raise ValueError("HTML fragment: comments are not allowed")

    def handle_decl(self, decl: str) -> None:
        raise ValueError("HTML fragment: declarations are not allowed")

    def unknown_decl(self, data: str) -> None:
        raise ValueError("HTML fragment: declarations are not allowed")

    def handle_pi(self, data: str) -> None:
        raise ValueError("HTML fragment: processing instructions are not allowed")

    def result(self) -> str:
        if self.stack:
            raise ValueError(f"HTML fragment: unclosed tag <{self.stack[-1]}>")
        return "".join(self.output)


def sanitize_html_fragment(value: str) -> str:
    parser = _InertFragmentParser()
    parser.feed(value)
    parser.close()
    return parser.result()


def state_from_spec(spec: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    """Project a valid v3/v4 build spec into deterministic portable state."""
    if not _nonempty(artifact_id) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]*", artifact_id
    ):
        raise ValueError(
            "artifact ID must start with a letter or number and use only "
            "letters, numbers, dot, underscore, or hyphen"
        )
    spec = _normalize_issue_layouts(spec)
    errors = validate_spec(spec)
    if spec.get("schemaVersion") not in {SPEC_VERSION, SPEC_VERSION_V4} or errors:
        detail = "; ".join(errors) if errors else "expected a v3 or v4 build spec"
        raise ValueError(f"cannot build portable state: {detail}")

    units: dict[str, Any] = {}
    source_records = {item["id"]: item for item in spec["evidence"]}
    for source in spec["units"]:
        unit = copy.deepcopy(source)
        unit_id = unit.pop("id")
        unit["selected"] = "a"
        unit["edits"] = {key: None for key in unit["variants"]}
        if unit.get("sourcePreview") is True:
            unit["variants"]["a"]["html"] = _render_source_preview(
                source, source_records[source["detail"]]
            )
        units[unit_id] = unit

    evidence: dict[str, Any] = {}
    for source in spec["evidence"]:
        item = copy.deepcopy(source)
        evidence_id = item.pop("id")
        original = item.get("original", {})
        href = (
            original.get("href") if original.get("availability") == "linked" else None
        )
        item["excerpt"] = item.get("excerpt", item["detail"])
        item["link"] = _safe_http_link(href)
        exhibit = item.pop("exhibit", None)
        item["image"] = (
            {"status": "supplied-unverified", **exhibit}
            if exhibit
            else {"status": "unavailable"}
        )
        item["provenance"] = f"{item['sourceId']} · {item['locator']}"
        evidence[evidence_id] = item

    result = {
        "schema": "legaldesign.state.v1",
        "sourceSchemaVersion": spec["schemaVersion"],
        "artifactId": artifact_id,
        "savedAt": None,
        "brief": copy.deepcopy(spec["brief"]),
        "style": copy.deepcopy(spec["style"]),
        "claims": copy.deepcopy(spec["claims"]),
        "units": units,
        "evidence": evidence,
        "review": {
            "approach": "a",
            "decisions": {},
            "theme": "light",
            "location": None,
        },
        "history": [],
    }
    if spec["schemaVersion"] == SPEC_VERSION_V4:
        result["composition"] = copy.deepcopy(spec["composition"])
        result["overview"] = copy.deepcopy(spec["overview"])
        result["review"].pop("approach")
    else:
        result["approaches"] = copy.deepcopy(spec["approaches"])
    return result


def _render_source_preview(unit: dict[str, Any], source: dict[str, Any]) -> str:
    """Only typed, validated source bytes/text enter this surface panel."""
    exhibit = source.get("exhibit")
    content = (
        '<img class="exhibit-shot" contenteditable="false" '
        f'src="{escape(exhibit["data"], quote=True)}" '
        f'alt="{escape(exhibit["alt"], quote=True)}">'
        if exhibit
        else '<blockquote class="doc-text" contenteditable="false">'
        f"{escape(source['excerpt'])}</blockquote>"
    )
    return (
        '<figure class="ld-source-preview">'
        f"<h2 data-editable>{escape(unit['claim'])}</h2>{content}"
        '<figcaption class="ld-source-preview-locator" contenteditable="false">'
        f"{escape(source['cite'])} · {escape(source['locator'])} · "
        f"{escape(source['status'])}"
        "</figcaption></figure>"
    )


def _render_variant(
    key: str, variant: dict[str, Any], *, source_html: str | None = None
) -> str:
    hidden = " hidden" if key != "a" else ""
    if source_html is not None:
        body = source_html
    elif "component" in variant:
        body = '<div class="ld-diagram"></div>'
    else:
        body = sanitize_html_fragment(variant["html"])
    return (
        f'<div class="ld-variant" data-variant="{key}"{hidden}>'
        f"<div data-variant-body data-editable>{body}</div>"
        "</div>"
    )


def _render_decision(unit: dict[str, Any]) -> str:
    if unit.get("kind") != "decision":
        return ""
    options = []
    for option in unit["options"]:
        options.append(
            '<button type="button" class="ld-decision-option" '
            f'data-decision-option value="{escape(option["key"], quote=True)}" '
            'aria-pressed="false">'
            f"<strong>{escape(option['key'])}</strong>"
            f"<span>{escape(option['label'])}</span>"
            f"<small>{escape(option['consequence'])}</small>"
            "</button>"
        )
    custom = (
        '<label class="ld-decision-input">Other'
        '<input type="text" data-decision-custom autocomplete="off"></label>'
        if unit["allow_custom"]
        else ""
    )
    note = (
        '<label class="ld-decision-input">Decision note (optional)'
        '<textarea data-decision-note rows="3"></textarea></label>'
        if unit["allow_note"]
        else ""
    )
    return (
        '<div class="ld-decision">'
        f"<h3 data-editable>{escape(unit['question'])}</h3>"
        f'<div class="ld-decision-options">{"".join(options)}</div>'
        f'<div class="ld-decision-inputs">{custom}{note}</div>'
        "</div>"
    )


def _render_unit(
    unit: dict[str, Any],
    *,
    row: int,
    column: int,
    span: int,
    row_span: int = 1,
    section_target: str | None = None,
    source_record: dict[str, Any] | None = None,
) -> str:
    unit_id = unit["id"]
    variants = unit["variants"]
    detail_id = unit.get("detail")
    classes = "ld-unit ld-composed-unit"
    if _nonempty(detail_id):
        classes += " ld-popup-trigger"
    role = unit.get("role")
    placement_style = f"--ld-row:{row};--ld-column:{column};--ld-span:{span}"
    if row_span != 1:
        placement_style += f";--ld-row-span:{row_span}"
    attributes = [
        f'class="{classes}"',
        f'data-unit="{escape(unit_id, quote=True)}"',
        f'data-kind="{escape(unit["kind"], quote=True)}"',
        f'aria-label="{escape(unit["claim"], quote=True)}"',
        f'style="{placement_style}"',
    ]
    if role:
        attributes.append(f'data-role="{escape(role, quote=True)}"')
    if section_target:
        attributes.extend(
            [
                f'data-section-target="{escape(section_target, quote=True)}"',
                'role="button"',
                'tabindex="0"',
            ]
        )
    if _nonempty(detail_id):
        escaped_detail = escape(detail_id, quote=True)
        attributes.extend(
            [
                f'data-detail="{escaped_detail}"',
                'role="button"',
                'tabindex="0"',
                'aria-haspopup="dialog"',
                f'aria-controls="{escaped_detail}"',
            ]
        )
    if unit.get("selection_mode") == "multiple":
        attributes.append("data-multi")
    figure_heading = (
        f'<h2 class="ld-figure-title" data-editable>{escape(unit["claim"])}</h2>'
        if unit.get("kind") == "figure"
        else ""
    )
    rendered_variants = "".join(
        _render_variant(
            key,
            variant,
            source_html=_render_source_preview(unit, source_record)
            if unit.get("sourcePreview") is True and source_record is not None
            else None,
        )
        for key, variant in variants.items()
    )
    return (
        f"<section {' '.join(attributes)}>"
        f"{figure_heading}{rendered_variants}{_render_decision(unit)}"
        "</section>"
    )


def _render_composition(
    spec: dict[str, Any], composition: dict[str, Any], approach_key: str
) -> str:
    units = {unit["id"]: unit for unit in spec["units"]}
    source_records = {item["id"]: item for item in spec.get("evidence", [])}
    overview = spec.get("overview", {})
    topic_targets = {
        item["unitId"]: item["targetSectionId"] for item in overview.get("topics", [])
    }

    def render_placed_unit(unit_id: str, placements: dict[str, Any]) -> str:
        placement = placements[unit_id]
        return _render_unit(
            units[unit_id],
            row=placement["row"],
            column=placement["column"],
            span=placement["span"],
            row_span=placement.get("rowSpan", 1),
            section_target=topic_targets.get(unit_id),
            source_record=source_records.get(units[unit_id].get("detail")),
        )

    sections: list[str] = []
    for section in composition["sections"]:
        placements = {item["unitId"]: item for item in section["layout"]["placements"]}
        groups = (
            overview.get("groups", [])
            if section["id"] == overview.get("sectionId")
            else []
        )
        grouped_ids = [unit_id for group in groups for unit_id in group["topicUnitIds"]]
        grouped_set = set(grouped_ids)
        recipe = section.get("issueLayout")
        analysis_ids = (
            [
                recipe[key]
                for key in ("findingUnitId", "implicationUnitId", "actionUnitId")
            ]
            if recipe
            else []
        )
        support_ids = recipe["supportUnitIds"] if recipe else []
        issue_ids = set(analysis_ids + support_ids)
        hub = section.get("presentation") == "card-hub"
        intro_ids = (
            overview["contextUnitIds"]
            + [overview["questionUnitId"], overview["answerUnitId"]]
            if hub
            else []
        )
        rendered_units = []
        for unit_id in section["unitIds"]:
            if unit_id in intro_ids:
                if unit_id == intro_ids[0]:
                    rendered_units.append(
                        '<div class="ld-hub-intro" '
                        'style="--ld-row:2;--ld-column:1;--ld-span:12">'
                        + "".join(
                            render_placed_unit(item, placements) for item in intro_ids
                        )
                        + "</div>"
                    )
                continue
            if unit_id in issue_ids:
                if unit_id == analysis_ids[0]:
                    rendered_units.append(
                        '<div class="ld-issue-body" '
                        'style="--ld-row:2;--ld-column:1;--ld-span:12">'
                        '<div class="ld-issue-analysis">'
                        + "".join(
                            render_placed_unit(item, placements)
                            for item in analysis_ids
                        )
                        + '</div><div class="ld-issue-support">'
                        + "".join(
                            render_placed_unit(item, placements) for item in support_ids
                        )
                        + "</div></div>"
                    )
                continue
            if unit_id not in grouped_set:
                rendered_units.append(render_placed_unit(unit_id, placements))
                continue
            if unit_id != grouped_ids[0]:
                continue
            rendered_groups = []
            for group_index, group in enumerate(groups):
                topic_html = "".join(
                    render_placed_unit(topic_id, placements)
                    for topic_id in group["topicUnitIds"]
                )
                count = len(group["topicUnitIds"])
                count_label = "topic" if count == 1 else "topics"
                open_attribute = " open" if group_index == 0 else ""
                rendered_groups.append(
                    '<details class="ld-overview-group" '
                    f'data-overview-group="{group_index}"{open_attribute}>'
                    '<summary><span class="ld-overview-group-label" '
                    f'data-overview-group-label="{group_index}">'
                    f"{escape(group['label'])}</span>"
                    '<span class="ld-overview-group-count">'
                    f"{count} {count_label}</span></summary>"
                    f'<div class="ld-overview-topic-grid">{topic_html}</div>'
                    "</details>"
                )
            # Only this wrapper participates in the outer grid. Topic rows stay
            # in portable state but must not create empty outer-grid tracks.
            group_row = placements[unit_id]["row"]
            rendered_units.append(
                '<div class="ld-overview-groups" '
                f'style="--ld-row:{group_row};--ld-column:1;--ld-span:12">'
                f"{''.join(rendered_groups)}</div>"
            )
        page_class = " ld-fixed-page" if spec["brief"]["form"] != "one-page" else ""
        if hub:
            page_class += " ld-card-hub"
        index_label = (
            f' data-index-label="{escape(section["indexLabel"], quote=True)}"'
            if section.get("indexLabel")
            else ""
        )
        sections.append(
            f'<section class="ld-composed-section{page_class}" '
            f'data-composition-section="{escape(section["id"], quote=True)}" '
            f'aria-label="{escape(section["purpose"], quote=True)}"{index_label}>'
            f'<div class="ld-composed-grid">{"".join(rendered_units)}</div>'
            "</section>"
        )
    hidden = "" if approach_key == "a" else " hidden"
    page_class = " ld-fixed-page" if spec["brief"]["form"] == "one-page" else ""
    return (
        f'<div class="ld-page-approach{page_class}" '
        f'data-approach="{approach_key}"{hidden}>'
        f"{''.join(sections)}</div>"
    )


def _render_approaches(spec: dict[str, Any]) -> str:
    if spec.get("schemaVersion") == SPEC_VERSION_V4:
        return _render_composition(spec, spec["composition"], "a")
    controls = []
    pages = []
    for key in ("a", "b"):
        approach = spec["approaches"][key]
        controls.append(
            '<button type="button" '
            f'data-select-approach="{key}" '
            f'aria-pressed="{"true" if key == "a" else "false"}">'
            f"<span>{key.upper()}</span>{escape(approach['label'])}</button>"
        )
        pages.append(_render_composition(spec, approach["composition"], key))
    return (
        '<nav id="ld-page-approach" data-export-chrome '
        'aria-label="Page design">'
        '<span class="ld-approach-label">Page design</span>'
        f"{''.join(controls)}</nav>{''.join(pages)}"
    )


def _render_popups(spec: dict[str, Any]) -> str:
    popups: list[str] = []
    for item in spec["evidence"]:
        original = item["original"]
        href = (
            _safe_http_link(original.get("href"))
            if original.get("availability") == "linked"
            else None
        )
        if href is None:
            source = (
                '<p class="out ld-source-unavailable">'
                f"{escape(original['label'])} — original source unavailable in "
                "this file.</p>"
            )
        else:
            source = (
                '<p class="out"><a target="_blank" rel="noopener noreferrer" '
                f'href="{escape(href, quote=True)}">'
                f"{escape(original['label'])}</a></p>"
            )
        popup = item["popup"]
        lede = (
            '<p class="ld-popup-lede" data-evidence-field="popup.lede" '
            f"data-editable>{escape(popup['lede'])}</p>"
            if popup.get("lede")
            else ""
        )
        sections = []
        for index, section in enumerate(popup["sections"]):
            sections.append(
                '<section class="ld-popup-section">'
                f'<h3 data-evidence-field="popup.sections.{index}.heading" '
                f"data-editable>{escape(section['heading'])}</h3>"
                f'<p data-evidence-field="popup.sections.{index}.body" '
                f"data-editable>{escape(section['body'])}</p>"
                "</section>"
            )
        exhibit = item.get("exhibit")
        source_excerpt = ""
        if exhibit or item.get("excerpt"):
            quote = (
                f'<blockquote class="doc-text">{escape(item["excerpt"])}</blockquote>'
                if item.get("excerpt")
                else ""
            )
            clip = (
                '<img class="exhibit-shot" '
                f'src="{escape(exhibit["data"], quote=True)}" '
                f'alt="{escape(exhibit["alt"], quote=True)}">'
                if exhibit
                else ""
            )
            provenance = (
                f"{exhibit['captureMethod']} · {exhibit['capturedAt']} · "
                f"image SHA-256 {exhibit['sha256']} · "
                f"source SHA-256 {exhibit['sourceSha256']}"
                if exhibit
                else "Exact supplied excerpt; source rendering unavailable."
            )
            source_excerpt = (
                f'<figure class="doc">{clip}{quote}'
                f'<figcaption class="doc-cl">{escape(item["cite"])} · '
                f"{escape(item['locator'])} · {escape(item['status'])}</figcaption>"
                f'<details class="doc-foot"><summary>Capture record</summary>'
                f"<p>{escape(provenance)}</p></details></figure>"
            )
            if not exhibit and len(item.get("excerpt", "")) > 800:
                source_excerpt = (
                    '<details class="ld-source-excerpt">'
                    "<summary>Read the exact supplied passage</summary>"
                    f"{source_excerpt}</details>"
                )
        popups.append(
            f'<div class="pop" id="{escape(item["id"], quote=True)}" '
            f'data-evidence-id="{escape(item["id"], quote=True)}" hidden '
            f'data-popup-type="{escape(popup["type"], quote=True)}" '
            'role="dialog" aria-modal="true" '
            f'aria-labelledby="{escape(item["id"], quote=True)}-title">'
            '<button class="ld-popup-close" type="button" '
            'aria-label="Close detail">×</button>'
            f'<h2 data-evidence-field="popup.title" data-editable '
            f'id="{escape(item["id"], quote=True)}-title">'
            f"{escape(popup['title'])}</h2>{lede}{''.join(sections)}{source_excerpt}"
            f'<footer class="ld-popup-source">{source}</footer></div>'
        )
    return "".join(popups)


def _replace_block(source: str, name: str, value: str) -> str:
    pattern = re.compile(
        rf"<!-- legaldesign:{re.escape(name)} -->.*?"
        rf"<!-- /legaldesign:{re.escape(name)} -->",
        re.DOTALL,
    )
    replacement = f"<!-- legaldesign:{name} -->{value}<!-- /legaldesign:{name} -->"
    result, count = pattern.subn(lambda _: replacement, source)
    if count != 1:
        raise ValueError(f"composed shell must contain exactly one {name!r} block")
    return result


def _safe_design_token(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"(?:#[0-9A-Fa-f]{3,8}|rgba?\([0-9.,%\s-]+\))", value):
        raise ValueError(f"DESIGN.md contains an unsafe color token {value!r}")
    return value


def _design_authority_css(spec: dict[str, Any], plan_path: Path) -> str:
    style = spec["style"]
    source = style["source"]
    if source == "loxoto":
        return ""
    if source != "design-md":
        raise ValueError(
            "composed output can apply only Loxoto or DESIGN.md directly; "
            "template and playbook styles require an explicit template import"
        )
    reference = style.get("ref")
    if not _nonempty(reference):
        raise ValueError("style.source 'design-md' requires style.ref")
    raw_path = Path(reference).expanduser()
    candidates = (
        [raw_path]
        if raw_path.is_absolute()
        else [plan_path.parent / raw_path, Path.cwd() / raw_path]
    )
    authority = next(
        (candidate.resolve() for candidate in candidates if candidate.is_file()), None
    )
    if authority is None:
        raise ValueError(f"DESIGN.md not found for style.ref {reference!r}")
    text = authority.read_text(encoding="utf-8")
    front = _parse_front_matter(text)
    if front.get("legaldesign") != "design-authority":
        raise ValueError("style.ref is not a LegalDesign design authority")
    if front.get("status") != "configured":
        raise ValueError("style.ref DESIGN.md must have status: configured")
    if front.get("system") != "Loxoto":
        raise ValueError("style.ref DESIGN.md must preserve system: Loxoto")
    if front.get("scope") != "palette-only":
        raise ValueError("style.ref DESIGN.md must declare scope: palette-only")
    if not _nonempty(front.get("palette_name")):
        raise ValueError("style.ref DESIGN.md must name its palette_name")
    light = _token_values(text, "Light")
    dark = _token_values(text, "Dark")
    missing = [f"Light.{token}" for token in LIGHT_TOKENS if token not in light] + [
        f"Dark.{token}" for token in DARK_TOKENS if token not in dark
    ]
    if missing:
        raise ValueError("DESIGN.md is missing required tokens: " + ", ".join(missing))
    if dark["--bg"].strip().lower() != "#000000":
        raise ValueError("DESIGN.md Dark.--bg must be pure black (#000000)")
    permitted = set(LIGHT_TOKENS)
    unexpected = sorted((set(light) | set(dark)) - permitted)
    if unexpected:
        raise ValueError(
            "DESIGN.md contains unsupported non-palette tokens: "
            + ", ".join(unexpected)
        )
    for theme, tokens in (("Light", light), ("Dark", dark)):
        for surface in ("--bg", "--card", "--card-strong", "--tint"):
            for foreground in (
                "--ink",
                "--muted",
                "--faint",
                "--red",
                "--red-strong",
            ):
                try:
                    ratio = _contrast(tokens[foreground], tokens[surface])
                except ValueError as exc:
                    raise ValueError(f"DESIGN.md {theme}: {exc}") from exc
                if ratio < 4.5:
                    raise ValueError(
                        f"DESIGN.md {theme} {foreground} on {surface} contrast "
                        f"{ratio:.2f}:1 is below 4.5:1"
                    )

    def rule(selector: str, tokens: dict[str, str], required: tuple[str, ...]) -> str:
        declarations = "".join(
            f"{name}:{_safe_design_token(tokens[name])};" for name in required
        )
        return f"{selector}{{{declarations}}}"

    return rule('html:root,html[data-theme="light"]', light, PALETTE_TOKENS) + rule(
        'html[data-theme="dark"]', dark, PALETTE_TOKENS
    )


def _validate_fixed_page_surface(spec: dict[str, Any]) -> None:
    """Reject plainly overfull plans before HTML generation.

    This is a generous *ceiling*, not a substitute for browser geometry QA.
    Runtime checks actual bounds and refuses export if editing or rich content
    exceeds the available window. No text is truncated, dropped, or reduced to fit.
    """
    units = {unit["id"]: unit for unit in spec["units"]}
    for key, approach in _spec_approaches(spec).items():
        sections = approach["composition"]["sections"]
        pages = (
            [sections]
            if spec["brief"]["form"] == "one-page"
            else [[section] for section in sections]
        )
        for index, page in enumerate(pages):
            surface_characters = 0
            for section in page:
                for unit_id in section["unitIds"]:
                    unit = units[unit_id]
                    variant_lengths = []
                    for variant in unit["variants"].values():
                        if unit.get("sourcePreview") is True:
                            record = next(
                                item
                                for item in spec["evidence"]
                                if item["id"] == unit["detail"]
                            )
                            text = " ".join(
                                str(value)
                                for value in (
                                    unit["claim"],
                                    record["cite"],
                                    record["locator"],
                                    record["status"],
                                    record.get("excerpt", "")
                                    if not record.get("exhibit")
                                    else "",
                                )
                            )
                        elif "html" in variant:
                            text = re.sub(r"<[^>]*>", " ", variant["html"])
                        else:
                            text = " ".join(
                                _iter_component_surface_text(variant.get("params", {}))
                            )
                        variant_lengths.append(len(re.sub(r"\s+", " ", text).strip()))
                    surface_characters += max(variant_lengths, default=0)
            if surface_characters > 4200:
                raise ValueError(
                    f"approach {key.upper()} page {index + 1} "
                    "exceeds the single-page overview budget "
                    f"({surface_characters} characters; "
                    "maximum 4200 before geometry checks). "
                    "Keep the overview on the page; "
                    "move supporting detail into a popup "
                    "or split the content into another page. Never shrink or clip it."
                )


def render_composed_html(
    spec: dict[str, Any],
    artifact_id: str,
    *,
    shell: Path = COMPOSED_SHELL,
    design_css: str = "",
) -> str:
    spec = _normalize_issue_layouts(spec)
    state = state_from_spec(spec, artifact_id)
    _validate_fixed_page_surface(spec)
    source = shell.read_text(encoding="utf-8")
    source = source.replace(
        "data-composed-shell>", 'data-composed-shell data-fixed-pages="4:3">', 1
    )
    title_pattern = re.compile(r"<title>.*?</title>", re.DOTALL | re.IGNORECASE)
    source, title_count = title_pattern.subn(
        f"<title>{escape(spec['brief']['title'])}</title>", source, count=1
    )
    if title_count != 1:
        raise ValueError("composed shell must contain exactly one title element")
    source = _replace_block(source, "matter", escape(spec["brief"]["title"]))
    source = _replace_block(source, "design-authority", design_css)
    source = source.replace("<!-- legaldesign:design-authority -->", "").replace(
        "<!-- /legaldesign:design-authority -->", ""
    )
    source = _replace_block(source, "composed-content", _render_approaches(spec))
    source = _replace_block(source, "popups", _render_popups(spec))
    state_pattern = re.compile(
        r'(<script\s+id="legaldesign-state"\s+type="application/json">)'
        r".*?(</script>)",
        re.DOTALL,
    )
    source, count = state_pattern.subn(
        lambda match: match.group(1) + json_for_script(state) + match.group(2),
        source,
    )
    if count != 1:
        raise ValueError("composed shell must contain one legaldesign-state block")
    return source


def _command_init(args: argparse.Namespace) -> int:
    spec_path = args.spec_output.expanduser().resolve()
    output = args.output.expanduser().resolve() if args.output else None
    template = args.template
    form = args.form
    source: Path | None = None
    if template is None and output is not None:
        raise ValueError(
            "--output copies HTML only with explicit --template; composition "
            "starts from the claim-led specification"
        )
    if template is not None:
        expected_form, asset_name = TEMPLATES[template]
        legacy_form = {"slide-brief": "walkthrough", "diligence-report": "report"}.get(
            template
        )
        if form == legacy_form:
            form = expected_form
        if form != expected_form:
            raise ValueError(f"template {template!r} requires --form {expected_form!r}")
        if output is None:
            raise ValueError("--template requires --output")
        source = (
            ASSET_ROOT / "templates" / asset_name.replace(".html", ".template.html")
        )
        if spec_path == output:
            raise ValueError("output and spec output must be different files")
        _ensure_new_file(output, "output")
    _ensure_new_file(spec_path, "spec output")
    if source is not None and output is not None:
        _copy_new(source, output)
    try:
        _write_json_new(spec_path, _skeleton(form, template=template))
    except OSError:
        if output is not None:
            output.unlink(missing_ok=True)
        raise
    print(
        json.dumps(
            {
                "form": form,
                "strategy": "template-import" if template else "composed",
                "template": template,
                "output": str(output) if output else None,
                "sourceAsset": str(source) if source else None,
                "sourceSha256": _sha256(source) if source else None,
                "outputSha256": _sha256(output) if output else None,
                "specOutput": str(spec_path),
                "warning": (
                    "Reusable template copied: complete the overview and composition; "
                    "replace every descriptive placeholder before client delivery."
                    if template
                    else "No example or template was selected. Complete the claim "
                    "ledger and composition plan before considering examples."
                ),
            },
            indent=2,
        )
    )
    return 0


def _command_compose(args: argparse.Namespace) -> int:
    """Validate a current single-output plan or legacy v3 composition."""
    plan_path = args.plan.expanduser().resolve()
    spec_output = args.spec_output.expanduser().resolve()
    html_output = args.output.expanduser().resolve()
    if spec_output == html_output:
        raise ValueError("output and spec output must be different files")
    plan = _load_json(plan_path)
    if not isinstance(plan, dict):
        raise ValueError("composition plan must be a JSON object")
    payload: dict[str, Any]
    if "schemaVersion" in plan:
        plan_version = plan["schemaVersion"]
        if plan_version not in {SPEC_VERSION, SPEC_VERSION_V4}:
            raise ValueError(
                f"unsupported composition plan schemaVersion {plan_version!r}; "
                f"expected {SPEC_VERSION!r} or {SPEC_VERSION_V4!r}"
            )
        payload = dict(plan)
    else:
        payload = {
            "schemaVersion": SPEC_VERSION if "approaches" in plan else SPEC_VERSION_V4,
            **plan,
        }
    payload = _normalize_issue_layouts(payload)
    errors = validate_spec(payload)
    if errors:
        raise ValueError("composition plan is invalid:\n- " + "\n- ".join(errors))
    if any(
        approach["composition"]["strategy"] != "composed"
        for approach in _spec_approaches(payload).values()
    ):
        raise ValueError(
            "compose renders freely composed Loxoto pages only; "
            "use init --template for an explicit template import"
        )
    design_css = _design_authority_css(payload, plan_path)
    rendered = render_composed_html(payload, args.artifact_id, design_css=design_css)
    _ensure_new_file(spec_output, "spec output")
    _ensure_new_file(html_output, "output")
    created_spec = False
    created_html = False
    try:
        _write_json_new(spec_output, payload)
        created_spec = True
        _write_text_new(html_output, rendered)
        created_html = True
    except OSError:
        if created_html:
            html_output.unlink(missing_ok=True)
        if created_spec:
            spec_output.unlink(missing_ok=True)
        raise
    material = [
        claim
        for claim in payload["claims"]
        if isinstance(claim, dict) and claim.get("kind") == "material"
    ]
    print(
        json.dumps(
            {
                "schemaVersion": payload["schemaVersion"],
                **(
                    {
                        "composition": {
                            key: payload["composition"][key]
                            for key in ("strategy", "shape", "templateRef")
                        }
                    }
                    if payload["schemaVersion"] == SPEC_VERSION_V4
                    else {
                        "approaches": {
                            key: {
                                "label": payload["approaches"][key]["label"],
                                "strategy": payload["approaches"][key]["composition"][
                                    "strategy"
                                ],
                                "shape": payload["approaches"][key]["composition"][
                                    "shape"
                                ],
                                "templateRef": payload["approaches"][key][
                                    "composition"
                                ]["templateRef"],
                            }
                            for key in ("a", "b")
                        }
                    }
                ),
                "styleSource": payload["style"]["source"],
                "styleApplication": (
                    "design-md-palette-roles"
                    if payload["style"]["source"] == "design-md"
                    else "loxoto"
                ),
                "styleRef": payload["style"]["ref"],
                "materialClaims": len(material),
                "surfaceClaims": sum(
                    claim.get("placement") == "surface" for claim in material
                ),
                "units": len(payload["units"]),
                "artifactId": args.artifact_id,
                "specOutput": str(spec_output),
                "specSha256": _sha256(spec_output),
                "output": str(html_output),
                "outputSha256": _sha256(html_output),
            },
            indent=2,
        )
    )
    return 0


def _command_validate(args: argparse.Namespace) -> int:
    payload = _load_json(args.spec.expanduser().resolve())
    errors = validate_spec(payload)
    if args.json:
        print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    elif errors:
        for error in errors:
            print(error, file=sys.stderr)
    return 1 if errors else 0


def _parameter_summary(name: str, contract: dict[str, Any]) -> str:
    kind = contract.get("type", "")
    required = "required" if contract.get("required") else "optional"
    if kind in {"list", "strings"}:
        bounds = f"{contract.get('minItems')}–{contract.get('maxItems')}"
        fields = contract.get("itemFields")
        suffix = f"; fields {', '.join(fields)}" if fields else ""
        return f"`{name}` {bounds} {kind}{suffix}"
    if kind == "choice":
        choices = " \\| ".join(contract.get("choices", []))
        return f"`{name}` {required}: {choices}"
    if kind == "index":
        return f"`{name}` {required} index"
    return f"`{name}` {required} {kind}"


def components_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Component registry",
        "",
        "Generated by `scripts/scaffold.py components --markdown` from "
        "[`components.json`](components.json). Do not edit this table by hand.",
        "",
        "## Recommended for new designs",
        "",
        "Choose the relationship first. These components are the curated starting "
        "set, not a requirement to draw a diagram.",
        "",
        "| Runtime ID | Relationships | Capacity | Parameters | Detail |",
        "|---|---|---|---|---|",
    ]
    legacy = []
    for component_id, contract in payload["components"].items():
        if contract.get("recommended") is False:
            legacy.append(f"`{component_id}`")
            continue
        parameters = "; ".join(
            _parameter_summary(name, parameter)
            for name, parameter in contract.get("parameters", {}).items()
        )
        relationships = ", ".join(contract.get("relationships", []))
        detail = "yes" if contract.get("detail") else "no"
        lines.append(
            f"| `{component_id}` | {relationships} | "
            f"{contract.get('capacity', '')} | {parameters} | {detail} |"
        )
    lines.extend(
        [
            "",
            "## Saved-file compatibility",
            "",
            "The following renderers remain available to open existing artifacts "
            "and explicit template imports, but are not offered for new "
            "compositions. Full parameter contracts remain in `components.json`.",
            "",
            ", ".join(legacy) + ".",
            "",
            "The runtime carries no third-party code and copies nothing from "
            "Lieflat Charts (PolyForm Noncommercial).",
            "",
            "Unknown component IDs, undocumented fields, and over-capacity "
            "lists fail validation.",
        ]
    )
    return "\n".join(lines) + "\n"


def _command_components(args: argparse.Namespace) -> int:
    payload = _component_payload()
    if args.markdown:
        print(components_markdown(payload), end="")
    else:
        print(json.dumps(payload, indent=2))
    return 0


def _parse_front_matter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        raise ValueError("DESIGN.md must begin with front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("DESIGN.md front matter is not closed")

    def scalar(value: str) -> Any:
        if value == "null":
            return None
        if value == "[]":
            return []
        if re.fullmatch(r"\d+", value):
            return int(value)
        return value.strip('"')

    result: dict[str, Any] = {}
    source: dict[str, Any] | None = None
    source_list: str | None = None
    for line_number, line in enumerate(text[4:end].splitlines(), start=2):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0:
            source = None
            source_list = None
            if ":" not in line:
                raise ValueError(f"DESIGN.md:{line_number}: invalid front matter")
            key, raw = line.split(":", 1)
            value = raw.strip()
            result[key.strip()] = (
                [] if key.strip() == "sources" and not value else scalar(value)
            )
            continue
        if indent == 2 and stripped.startswith("- "):
            if not isinstance(result.get("sources"), list):
                raise ValueError(f"DESIGN.md:{line_number}: source outside sources")
            source = {}
            result["sources"].append(source)
            source_list = None
            remainder = stripped[2:].strip()
            if remainder:
                if ":" not in remainder:
                    raise ValueError(f"DESIGN.md:{line_number}: invalid source entry")
                key, raw = remainder.split(":", 1)
                source[key.strip()] = scalar(raw.strip())
            continue
        if indent == 4 and source is not None and ":" in stripped:
            key, raw = stripped.split(":", 1)
            value = raw.strip()
            if not value:
                source[key.strip()] = []
                source_list = key.strip()
            else:
                source[key.strip()] = scalar(value)
                source_list = None
            continue
        if (
            indent == 6
            and stripped.startswith("- ")
            and source is not None
            and source_list
        ):
            source[source_list].append(scalar(stripped[2:].strip()))
            continue
        if ":" not in line:
            raise ValueError(f"DESIGN.md:{line_number}: invalid front matter")
        raise ValueError(f"DESIGN.md:{line_number}: unsupported indentation")
    return result


def _token_values(text: str, theme: str) -> dict[str, str]:
    match = re.search(rf"^{theme}:\s*(.+)$", text, re.MULTILINE)
    if match is None:
        return {}
    return {
        name: value.strip().strip("`").strip()
        for name, value in re.findall(r"(--[a-z-]+)\s+([^·]+)", match.group(1))
    }


def _rgb(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"#([0-9a-fA-F]{6})", value.strip())
    if match is None:
        raise ValueError(f"contrast color must be six-digit hex, got {value!r}")
    packed = match.group(1)
    return (
        int(packed[0:2], 16),
        int(packed[2:4], 16),
        int(packed[4:6], 16),
    )


def _contrast(foreground: str, background: str) -> float:
    def luminance(color: str) -> float:
        channels = []
        for channel in _rgb(color):
            value = channel / 255
            channels.append(
                value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
            )
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    first, second = luminance(foreground), luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _command_design_check(args: argparse.Namespace) -> int:
    path = args.path.expanduser().resolve()
    text = path.read_text(encoding="utf-8")
    front = _parse_front_matter(text)
    schema = _load_json(DESIGN_SCHEMA)
    properties = set(schema.get("properties", {}))
    required = set(schema.get("required", []))
    errors: list[str] = []
    _check_keys(front, allowed=properties, required=required, path="$", errors=errors)
    if front.get("legaldesign") != "design-authority":
        errors.append("$.legaldesign: expected 'design-authority'")
    if not isinstance(front.get("version"), int) or front["version"] < 1:
        errors.append("$.version: expected a positive integer")
    if front.get("status") not in {"unconfigured", "configured"}:
        errors.append("$.status: expected 'unconfigured' or 'configured'")
    if front.get("system") != "Loxoto":
        errors.append("$.system: expected 'Loxoto'")
    if front.get("scope") != "palette-only":
        errors.append("$.scope: expected 'palette-only'")
    _check_string(front.get("palette_name"), "$.palette_name", errors)
    if front.get("set_up") is not None:
        _check_string(front["set_up"], "$.set_up", errors)
    sources = front.get("sources")
    if not isinstance(sources, list):
        errors.append("$.sources: expected an array")
    else:
        source_schema = schema.get("properties", {}).get("sources", {}).get("items", {})
        source_fields = set(source_schema.get("properties", {}))
        source_required = set(source_schema.get("required", []))
        for index, source in enumerate(sources):
            source_path = f"$.sources[{index}]"
            if not isinstance(source, dict):
                errors.append(f"{source_path}: expected an object")
                continue
            _check_keys(
                source,
                allowed=source_fields,
                required=source_required,
                path=source_path,
                errors=errors,
            )
            for name in ("kind", "ref", "date"):
                if name in source:
                    _check_string(source[name], f"{source_path}.{name}", errors)
            for name in ("observed", "inferred"):
                if name in source:
                    _check_string_list(source[name], f"{source_path}.{name}", errors)

    themes = {
        "Light": (_token_values(text, "Light"), LIGHT_TOKENS),
        "Dark": (_token_values(text, "Dark"), DARK_TOKENS),
    }
    for theme, (tokens, required_tokens) in themes.items():
        unexpected = sorted(set(tokens) - set(required_tokens))
        for token in unexpected:
            errors.append(f"{theme}.{token}: unsupported token")
        for token in required_tokens:
            if token not in tokens:
                errors.append(f"{theme}.{token}: missing token")
            else:
                print(f"{theme}.{token}: present ({tokens[token]})")
        if theme == "Dark" and tokens.get("--bg", "").strip().lower() != "#000000":
            errors.append("Dark.--bg: expected pure black (#000000)")
        for foreground in (
            "--ink",
            "--muted",
            "--faint",
            "--red",
            "--red-strong",
        ):
            for surface in ("--bg", "--card", "--card-strong", "--tint"):
                if foreground not in tokens or surface not in tokens:
                    continue
                try:
                    ratio = _contrast(tokens[foreground], tokens[surface])
                except ValueError as exc:
                    errors.append(f"{theme} {foreground} on {surface}: {exc}")
                    continue
                print(f"{theme} {foreground} on {surface}: {ratio:.2f}:1")
                if ratio < 4.5:
                    errors.append(
                        f"{theme} {foreground} on {surface}: contrast "
                        f"{ratio:.2f}:1 is below 4.5:1"
                    )
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


class _TemplateParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.stack: list[tuple[str, str | None]] = []
        self.unit_text: dict[str, list[str]] = {}
        self.visible: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in {"script", "style"}:
            self.skip += 1
        current = self.stack[-1][1] if self.stack else None
        unit = attributes.get("data-unit") or current
        if unit is not None:
            self.unit_text.setdefault(unit, [])
            self.unit_text[unit].extend(value or "" for _, value in attrs)
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append((tag, unit))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        current = self.stack[-1][1] if self.stack else None
        unit = attributes.get("data-unit") or current
        if unit is not None:
            self.unit_text.setdefault(unit, [])
            self.unit_text[unit].extend(value or "" for _, value in attrs)

    def handle_endtag(self, tag: str) -> None:
        while self.stack:
            open_tag, _ = self.stack.pop()
            if open_tag == tag:
                break
        if tag in {"script", "style"} and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        self.visible.append(data)
        unit = self.stack[-1][1] if self.stack else None
        if unit is not None:
            self.unit_text.setdefault(unit, []).append(data)


def _command_template_check(args: argparse.Namespace) -> int:
    path = args.path.expanduser().resolve()
    source = path.read_text(encoding="utf-8")
    parser = _TemplateParser()
    parser.feed(source)
    visible = " ".join(parser.visible)
    scan_source = re.sub(
        re.escape("<!-- legaldesign:runtime -->")
        + r"[\s\S]*?"
        + re.escape("<!-- /legaldesign:runtime -->"),
        "",
        source,
    )
    scan_source = re.sub(
        r"<script\b[^>]*\bid=[\"']ld-(?:client-)?runtime[\"'][^>]*>[\s\S]*?</script\s*>",
        "",
        scan_source,
        flags=re.IGNORECASE,
    )
    findings: list[str] = []
    for banned in TEMPLATE_BANS:
        if banned.casefold() in scan_source.casefold():
            findings.append(f"{path}: banned string {banned!r}")
    if re.search(r"https?://", scan_source, re.IGNORECASE):
        findings.append(f"{path}: banned http(s) URL")
    if args.asset and MATTER_TERMS.exists():
        terms = _load_json(MATTER_TERMS)
        values = terms.get(args.asset, []) if isinstance(terms, dict) else []
        if not isinstance(values, list):
            raise ValueError(f"matter terms for {args.asset!r} must be an array")
        for term in values:
            if isinstance(term, str) and term.casefold() in scan_source.casefold():
                findings.append(f"{path}: matter term {term!r}")
    for unit, parts in sorted(parser.unit_text.items()):
        count = len(re.findall(r"\[[^\]\n]+\]", " ".join(parts)))
        print(f"{unit}: {count} bracketed placeholder(s)")
    unscoped = len(re.findall(r"\[[^\]\n]+\]", visible))
    print(f"unscoped-visible: {unscoped} bracketed placeholder(s)")
    for finding in findings:
        print(finding, file=sys.stderr)
    return 1 if findings else 0


def _command_script_json(args: argparse.Namespace) -> int:
    payload = _load_json(args.input.expanduser().resolve())
    print(json_for_script(payload))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compose and validate LegalDesign specifications; copy a tested HTML "
            "template only when explicitly selected. The tool never writes "
            "substantive copy or performs legal QA."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser(
        "init", help="start a claim-led spec; copy HTML only with --template"
    )
    init.add_argument("--form", required=True, choices=sorted(FORMS))
    init.add_argument("--spec-output", required=True, type=Path)
    init.add_argument("--template", choices=sorted(TEMPLATES))
    init.add_argument("--output", type=Path)
    init.set_defaults(handler=_command_init)

    compose = subparsers.add_parser(
        "compose",
        help="write a canonical single-output v4 spec (or legacy v3) and finished HTML",
    )
    compose.add_argument("--plan", required=True, type=Path)
    compose.add_argument("--spec-output", required=True, type=Path)
    compose.add_argument("--output", required=True, type=Path)
    compose.add_argument("--artifact-id", required=True)
    compose.set_defaults(handler=_command_compose)

    validate = subparsers.add_parser(
        "validate", help="validate a v2, v3 or v4 build spec"
    )
    validate.add_argument("--spec", required=True, type=Path)
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(handler=_command_validate)

    components = subparsers.add_parser("components", help="print component registry")
    components.add_argument("--markdown", action="store_true")
    components.set_defaults(handler=_command_components)

    script_json = subparsers.add_parser(
        "script-json", help="serialize JSON for the inert state block"
    )
    script_json.add_argument("--input", required=True, type=Path)
    script_json.set_defaults(handler=_command_script_json)

    design_check = subparsers.add_parser(
        "design-check", help="check DESIGN.md front matter, tokens, and contrast"
    )
    design_check.add_argument("path", type=Path)
    design_check.set_defaults(handler=_command_design_check)

    template_check = subparsers.add_parser(
        "template-check", help="scan a reusable template and report placeholders"
    )
    template_check.add_argument("path", type=Path)
    template_check.add_argument("--asset")
    template_check.set_defaults(handler=_command_template_check)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        return int(args.handler(args))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
