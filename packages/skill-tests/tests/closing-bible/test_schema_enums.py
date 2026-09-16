"""Every references/*.schema.json parses, every $ref resolves, and every enum
the schemas declare is the same set models.py enforces — so a status can be
added in neither place alone."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from cb_support import REFERENCES
from closing_bible import models

SCHEMAS = sorted(REFERENCES.glob("*.schema.json"))
EXPECTED_FILES = {
    "build-plan.schema.json",
    "checklist.schema.json",
    "closing-index.schema.json",
    "closing-receipt.schema.json",
    "execution-overview.schema.json",
    "families.schema.json",
    "inspection.schema.json",
    "selection-plan.schema.json",
    "source-manifest.schema.json",
}


def schema(name: str) -> dict[str, Any]:
    return json.loads((REFERENCES / name).read_text())


def walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def test_all_nine_schemas_present_and_parse() -> None:
    assert {p.name for p in SCHEMAS} == EXPECTED_FILES
    for path in SCHEMAS:
        doc = json.loads(path.read_text())
        assert doc["type"] == "object", path.name
        assert doc["additionalProperties"] is False, path.name


@pytest.mark.parametrize("path", SCHEMAS, ids=lambda p: p.name)
def test_every_ref_resolves_inside_its_file(path: Path) -> None:
    doc = json.loads(path.read_text())
    for node in walk(doc):
        ref = node.get("$ref")
        if ref is None:
            continue
        assert ref.startswith("#/definitions/"), f"{path.name}: external ref {ref}"
        assert ref.split("/")[-1] in doc.get("definitions", {}), f"{path.name}: {ref}"


@pytest.mark.parametrize("path", SCHEMAS, ids=lambda p: p.name)
def test_schema_version_const_matches_models(path: Path) -> None:
    doc = json.loads(path.read_text())
    version = doc["properties"].get("schema_version")
    if version is not None:
        assert version == {"const": models.SCHEMA_VERSION}


def test_inspection_enums_equal_models() -> None:
    doc = schema("inspection.schema.json")
    fam = doc["definitions"]["family_inspection"]["properties"]
    execution = doc["definitions"]["execution_finding"]["properties"]
    ev = doc["definitions"]["evidence"]["properties"]
    assert set(fam["proposed_status"]["enum"]) == models.INSPECTION_STATUSES
    assert set(execution["apparent_status"]["enum"]) == models.APPARENT_STATUSES
    assert set(execution["dated"]["enum"]) == models.DATED
    assert set(ev["claim"]["enum"]) == models.EVIDENCE_CLAIMS
    assert set(ev["source"]["enum"]) == models.EVIDENCE_SOURCES
    assert fam["family_id"]["pattern"] == models.FAMILY_ID.pattern
    assert fam["member_ids"]["items"]["pattern"] == models.DOC_ID.pattern
    assert fam["proposed_pick"]["pattern"] == models.DOC_ID.pattern
    assert (
        execution["signature_pages"]["items"]["properties"]["document_id"]["pattern"]
        == models.DOC_ID.pattern
    )
    assert set(fam) == {
        "family_id",
        "member_ids",
        "proposed_pick",
        "proposed_status",
        "execution_expected",
        "execution",
        "evidence",
        "missing_components",
        "note",
    }


def test_index_enums_equal_models() -> None:
    doc = schema("closing-index.schema.json")
    item = doc["definitions"]["item"]["properties"]
    execution = item["execution"]["properties"]
    assert set(item["status"]["enum"]) == models.ITEM_STATUSES
    assert "unexpected" not in item["status"]["enum"]
    assert set(doc["properties"]["index_source"]["enum"]) == models.INDEX_SOURCES
    assert set(execution["evidence_source"]["enum"]) == models.EXECUTION_SOURCES
    assert set(execution["apparent_status"]["enum"]) == models.APPARENT_STATUSES
    assert set(execution["dated"]["enum"]) == models.DATED
    assert item["item_id"]["pattern"] == models.ITEM_ID.pattern
    assert item["selected_id"]["pattern"] == models.DOC_ID.pattern
    assert item["qualification"]["maxLength"] == 500


def test_receipt_enums_equal_models() -> None:
    doc = schema("closing-receipt.schema.json")
    props = doc["properties"]
    assert set(props["by_status"]["required"]) == set(models.RECEIPT_STATUSES)
    assert set(props["by_status"]["properties"]) == set(models.RECEIPT_STATUSES)
    assert set(props["mode"]["enum"]) == models.MODES
    assert set(props["outcome"]["enum"]) == models.OUTCOMES
    assert set(props["sources"]["required"]) == models.SOURCE_KEYS
    assert set(props["inspection"]["required"]) == models.INSPECTION_KEYS
    assert set(props["sigpack"]["required"]) == models.SIGPACK_KEYS
    assert props["as_of"]["pattern"] == models.DATE.pattern


def test_families_and_plan_enums_equal_models() -> None:
    fam = schema("families.schema.json")["properties"]["families"]["items"][
        "properties"
    ]
    assert set(fam["grouping_basis"]["items"]["enum"]) == models.GROUPING_BASIS
    assert fam["family_id"]["pattern"] == models.FAMILY_ID.pattern
    assert fam["member_ids"]["items"]["pattern"] == models.DOC_ID.pattern

    plan = schema("selection-plan.schema.json")["properties"]["families"]["items"][
        "properties"
    ]
    assert set(plan["grouping_basis"]["items"]["enum"]) == models.GROUPING_BASIS
    assert set(plan["resolved_status"]["enum"]) == models.STATUSES - {"missing"}
    ev = plan["evidence"]["items"]["properties"]
    assert set(ev["claim"]["enum"]) == models.EVIDENCE_CLAIMS
    assert set(ev["source"]["enum"]) == models.EVIDENCE_SOURCES


def test_manifest_and_overview_enums_equal_models() -> None:
    manifest = schema("source-manifest.schema.json")
    document = manifest["definitions"]["document"]["properties"]
    assert set(document["readability"]["enum"]) == models.READABILITY
    assert document["id"]["pattern"] == models.DOC_ID.pattern
    assert set(manifest["properties"]["counts"]["required"]) == {
        "files",
        "distinct",
        *models.READABILITY,
    }

    overview = schema("execution-overview.schema.json")
    doc = overview["properties"]["documents"]["items"]["properties"]
    assert set(doc["evidence_source"]["enum"]) == models.EXECUTION_SOURCES
    assert set(doc["apparent_status"]["enum"]) == models.APPARENT_STATUSES


def test_nine_statuses_and_no_others() -> None:
    """status-taxonomy.md: nine statuses; `unexpected` is a family, not a row."""

    assert models.STATUSES == {
        "ready",
        "unsigned",
        "undated",
        "incomplete",
        "version-conflict",
        "missing",
        "unexpected",
        "unreadable",
        "not-required",
    }
    assert models.ITEM_STATUSES == models.STATUSES - {"unexpected"}
    assert models.SELECTABLE_STATUSES == {"ready", "unsigned", "undated", "incomplete"}
    assert models.NO_PICK_STATUSES == {"version-conflict", "unreadable"}
