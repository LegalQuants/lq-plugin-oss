"""Dependency-free bridge to the published TimeNarratives schemas."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))

validate_schema_subset = importlib.import_module("schema_subset").validate_schema_subset


def published_schema_accepts(schema: Path, instance: object) -> bool:
    contract = json.loads(schema.read_text(encoding="utf-8"))
    return validate_schema_subset(instance, contract) == []


def assert_published_schema_valid(schema: Path, instance: object) -> None:
    assert published_schema_accepts(schema, instance), (
        f"published schema rejected {schema.name}"
    )
