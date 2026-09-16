"""Small public contract probes shared by the LegalDesign runtime tests.

The private repository has a larger mechanical evaluator. The public suite
keeps only the standard-library probes needed to exercise the shipped runtime
and schemas; no eval campaigns or historical output are required.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

RUNTIME_START = "<!-- legaldesign:runtime -->"
RUNTIME_END = "<!-- /legaldesign:runtime -->"
CHART_IDS = {
    "rungBars",
    "hairlineLine",
    "hairlineArea",
    "tickDonut",
    "tickRows",
    "pairedRungs",
    "stackedRungs",
    "plumbScatter",
    "rungWaterfall",
    "dotHeat",
    "tickGauge",
    "dumbbell",
    "treemap",
    "rungHistogram",
    "tickBox",
    "streamRibbon",
    "rangeBars",
}


def validate_json_schema(
    value: Any,
    schema: dict[str, Any] | bool,
    root_schema: dict[str, Any],
    path: str = "$",
) -> list[str]:
    """Validate the stdlib-only schema subset used by the build contracts."""

    if isinstance(schema, bool):
        return [] if schema else [f"{path}: disallowed by false schema"]

    def json_equal(left: Any, right: Any) -> bool:
        if isinstance(left, bool) or isinstance(right, bool):
            return type(left) is type(right) and left == right
        if isinstance(left, list) and isinstance(right, list):
            return len(left) == len(right) and all(
                json_equal(a, b) for a, b in zip(left, right, strict=True)
            )
        if isinstance(left, dict) and isinstance(right, dict):
            return left.keys() == right.keys() and all(
                json_equal(left[key], right[key]) for key in left
            )
        return left == right

    errors: list[str] = []
    reference = schema.get("$ref")
    if isinstance(reference, str):
        if not reference.startswith("#/"):
            return [f"{path}: unsupported external schema reference {reference!r}"]
        target: Any = root_schema
        for encoded_part in reference[2:].split("/"):
            part = encoded_part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                return [f"{path}: unresolved schema reference {reference!r}"]
            target = target[part]
        if not isinstance(target, (dict, bool)):
            return [f"{path}: schema reference {reference!r} is not a schema"]
        errors.extend(validate_json_schema(value, target, root_schema, path))

    if "const" in schema and not json_equal(value, schema["const"]):
        errors.append(f"{path}: expected constant {schema['const']!r}")
    enum = schema.get("enum")
    if isinstance(enum, list) and not any(json_equal(value, item) for item in enum):
        errors.append(f"{path}: expected one of {enum!r}, got {value!r}")

    for branch in schema.get("allOf", []):
        errors.extend(validate_json_schema(value, branch, root_schema, path))
    for keyword in ("anyOf", "oneOf"):
        branches = schema.get(keyword)
        if isinstance(branches, list):
            count = sum(
                not validate_json_schema(value, branch, root_schema, path)
                for branch in branches
            )
            if (keyword == "anyOf" and count == 0) or (
                keyword == "oneOf" and count != 1
            ):
                errors.append(f"{path}: {keyword} matched {count} branch(es)")
    forbidden = schema.get("not")
    if isinstance(forbidden, (dict, bool)) and not validate_json_schema(
        value, forbidden, root_schema, path
    ):
        errors.append(f"{path}: disallowed by 'not' schema")
    condition = schema.get("if")
    if isinstance(condition, (dict, bool)):
        branch = schema.get(
            "else"
            if validate_json_schema(value, condition, root_schema, path)
            else "then"
        )
        if isinstance(branch, (dict, bool)):
            errors.extend(validate_json_schema(value, branch, root_schema, path))

    expected = schema.get("type")
    expected_types = expected if isinstance(expected, list) else [expected]

    def matches(kind: object) -> bool:
        return {
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "integer": (isinstance(value, int) and not isinstance(value, bool))
            or (isinstance(value, float) and value.is_integer()),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "null": value is None,
        }.get(kind, True)

    if expected is not None and not any(matches(kind) for kind in expected_types):
        errors.append(f"{path}: expected type {expected!r}, got {type(value).__name__}")
        return errors

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{path}: expected value at least {minimum}")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"{path}: expected value at most {maximum}")

    if isinstance(value, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"{path}: expected at least {minimum} character(s)")
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append(f"{path}: expected at most {maximum} character(s)")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            errors.append(f"{path}: value does not match {pattern!r}")

    if isinstance(value, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"{path}: expected at least {minimum} item(s)")
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append(f"{path}: expected at most {maximum} item(s)")
        if schema.get("uniqueItems") is True:
            for index, item in enumerate(value):
                if any(json_equal(item, previous) for previous in value[:index]):
                    errors.append(f"{path}[{index}]: duplicate item is not allowed")
        item_schema = schema.get("items")
        if isinstance(item_schema, (dict, bool)):
            for index, item in enumerate(value):
                errors.extend(
                    validate_json_schema(
                        item, item_schema, root_schema, f"{path}[{index}]"
                    )
                )

    if isinstance(value, dict):
        minimum = schema.get("minProperties")
        maximum = schema.get("maxProperties")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"{path}: expected at least {minimum} properties")
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append(f"{path}: expected at most {maximum} properties")
        property_names = schema.get("propertyNames")
        if isinstance(property_names, (dict, bool)):
            for key in value:
                errors.extend(
                    validate_json_schema(
                        key, property_names, root_schema, f"{path}[property {key!r}]"
                    )
                )
        properties = schema.get("properties")
        property_map = properties if isinstance(properties, dict) else {}
        required = schema.get("required")
        if isinstance(required, list):
            for key in required:
                if key not in value:
                    errors.append(f"{path}: missing required field {key!r}")
        additional = schema.get("additionalProperties", True)
        for key, child in value.items():
            child_path = f"{path}.{key}"
            child_schema = property_map.get(key)
            if isinstance(child_schema, (dict, bool)):
                errors.extend(
                    validate_json_schema(child, child_schema, root_schema, child_path)
                )
            elif isinstance(additional, dict):
                errors.extend(
                    validate_json_schema(child, additional, root_schema, child_path)
                )
            elif additional is False:
                errors.append(f"{child_path}: unknown field; remove it")
    return errors


class PopupStructureProbe(HTMLParser):
    """Inspect popup ancestry and source-excerpt provenance."""

    def __init__(self) -> None:
        super().__init__()
        self.div_stack: list[tuple[str | None, set[str]]] = []
        self.scrim_depth: int | None = None
        self.popup_count = 0
        self.non_direct_popups = 0
        self.valid_source_exhibits = 0
        self.excerpt_popup_ids: set[str] = set()
        self.provenance_popup_ids: set[str] = set()
        self.source_text_context: tuple[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Any]]) -> None:
        attributes = dict(attrs)
        if tag == "p":
            classes = set((attributes.get("class") or "").split())
            popup_id = next(
                (
                    element_id
                    for element_id, roles in reversed(self.div_stack)
                    if "pop" in roles and element_id
                ),
                None,
            )
            field = (
                "excerpt"
                if "doc-text" in classes
                else ("provenance" if "ld-popup-source" in classes else None)
            )
            self.source_text_context = (popup_id, field) if popup_id and field else None
        if tag == "img":
            classes = set((attributes.get("class") or "").split())
            if "exhibit-shot" in classes:
                inside_popup = any(
                    "pop" in ancestor_classes for _, ancestor_classes in self.div_stack
                )
                src = attributes.get("src") or ""
                alt = attributes.get("alt") or ""
                if inside_popup and src.startswith("data:image/") and alt.strip():
                    self.valid_source_exhibits += 1
            return
        if tag != "div":
            return
        classes: set[str] = set((attributes.get("class") or "").split())
        element_id = attributes.get("id")
        element_id = element_id if isinstance(element_id, str) else None
        if element_id == "popup-scrim":
            self.scrim_depth = len(self.div_stack)
        if "pop" in classes:
            self.popup_count += 1
            if self.scrim_depth is None or len(self.div_stack) != self.scrim_depth + 1:
                self.non_direct_popups += 1
        self.div_stack.append((element_id, classes))

    def handle_endtag(self, tag: str) -> None:
        if tag == "p":
            self.source_text_context = None
        if tag != "div" or not self.div_stack:
            return
        element_id, _ = self.div_stack.pop()
        if element_id == "popup-scrim":
            self.scrim_depth = None

    def handle_data(self, data: str) -> None:
        if self.source_text_context and data.strip():
            popup_id, field = self.source_text_context
            target = (
                self.excerpt_popup_ids
                if field == "excerpt"
                else self.provenance_popup_ids
            )
            target.add(popup_id)


def component_implementation(source: str, component_id: str) -> str | None:
    start = re.search(
        rf"\bC\s*\.\s*{re.escape(component_id)}\s*=\s*"
        r"(?:function\s*\([^)]*\)|\([^)]*\)\s*=>)\s*\{",
        source,
    )
    if start is None:
        return None
    rest = source[start.end() :]
    end = re.search(r"\b(?:C\s*\.\s*[A-Za-z_$][\w$]*|LD\s*\.\s*registry)\s*=", rest)
    return rest if end is None else rest[: end.start()]


def component_parameter_keys(source: str, component_id: str) -> list[str]:
    body = component_implementation(source, component_id)
    if body is None:
        return []
    call = (
        r"chartParams\s*\(\s*params\s*,"
        if component_id in CHART_IDS
        else r"(?:known\s*\(\s*data\s*,\s*['\"]params['\"]\s*,|"
        r"chartParams\s*\(\s*params\s*,)"
    )
    parameters = re.search(rf"\b{call}\s*\[([^]]*)\]", body)
    return re.findall(r"['\"]([^'\"]+)['\"]", parameters.group(1)) if parameters else []


def allows_page_background(selector: str) -> bool:
    selector = re.sub(r"/\*[\s\S]*?\*/", "", selector).strip()
    selector = re.sub(r"\s+", " ", selector)
    selector = re.sub(r"\s*=\s*", "=", selector)
    selector = re.sub(r"(['\"])([\w-]+)\1(?=\s*\])", r"\2", selector)
    selector = re.sub(r"\s*\]", "]", selector)
    if selector in {
        "html",
        "body",
        ".stage",
        "html[data-theme=dark] .ld-composed-unit[data-kind=figure]",
        "html[data-has-slide-index=true] .ld-slide-index",
        "html[data-fixed-pages] .ld-fixed-page",
        ".ld-page-fit-error",
    }:
        return True
    return "-stage" in selector or bool(re.search(r"\[data-fill-token=bg\]", selector))


def runtime_is_in_head(source: str) -> bool:
    head = re.search(r"<head\b[^>]*>", source, re.I)
    close = re.search(r"</head\s*>", source, re.I)
    start = source.find(RUNTIME_START)
    end = source.find(RUNTIME_END, max(0, start))
    return bool(
        head
        and close
        and head.end() <= start <= end
        and end + len(RUNTIME_END) <= close.start()
    )
