from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
MODULE = importlib.util.spec_from_file_location(
    "legaldesign_source_clips", ROOT / "skills/core/legaldesign/scripts/scaffold.py"
)
assert MODULE and MODULE.loader
scaffold = importlib.util.module_from_spec(MODULE)
sys.modules[MODULE.name] = scaffold
MODULE.loader.exec_module(scaffold)
PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAwMCAO+jXioAAAAASUVORK5CYII="
)
FIXTURE = (
    ROOT
    / "packages/skill-tests/tests/legaldesign/fixtures/case-07-forward-design.plan.json"
)


def plan_with_clip() -> dict:
    plan = json.loads((FIXTURE).read_text())
    plan["evidence"][0]["excerpt"] = "Exact supplied words <not markup>."
    plan["evidence"][0]["exhibit"] = {
        "data": "data:image/png;base64," + PNG,
        "sha256": hashlib.sha256(base64.b64decode(PNG)).hexdigest(),
        "sourceSha256": "a" * 64,
        "locator": "Supplied fixture, paragraph 1",
        "captureMethod": "Supplied test PNG; not a verified document",
        "capturedAt": "2026-09-05T00:00:00Z",
        "alt": 'Fixture <image> "quoted"',
    }
    return plan


def test_clip_and_exact_excerpt_render_without_upgrading_support() -> None:
    plan = plan_with_clip()
    assert scaffold.validate_spec(plan) == []
    state = scaffold.state_from_spec(plan, "clip-test")
    item = state["evidence"]["gate"]
    assert item["status"] == "supplied-unverified"
    assert item["image"]["status"] == "supplied-unverified"
    assert item["image"]["data"].endswith(PNG)
    assert item["excerpt"] == "Exact supplied words <not markup>."
    assert "exhibit" not in item
    rendered = scaffold._render_popups(plan)
    assert 'class="exhibit-shot"' in rendered
    assert 'class="doc-text"' in rendered
    assert "&lt;not markup&gt;" in rendered
    assert "Capture record" in rendered
    assert "&lt;image&gt; &quot;quoted&quot;" in rendered


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("data", "https://example.test/image.png", "only base64 PNG/JPEG"),
        ("data", "data:image/svg+xml;base64,PHN2Zz4=", "only base64 PNG/JPEG"),
        ("data", "data:image/png;base64,SGVsbG8=", "invalid image signature"),
        ("sha256", "0" * 64, "does not match"),
        ("sourceSha256", "not-a-hash", "SHA-256"),
        ("data", "data:image/png;base64," + "A" * 5_600_000, "under 4 MiB"),
    ],
)
def test_unsafe_or_mismatched_clips_fail_closed(field, value, expected) -> None:
    plan = plan_with_clip()
    plan["evidence"][0]["exhibit"][field] = value
    assert any(expected in error for error in scaffold.validate_spec(plan))


def test_capture_metadata_is_required_and_unknown_fields_are_rejected() -> None:
    plan = plan_with_clip()
    original = copy.deepcopy(plan["evidence"][0]["exhibit"])
    for field in original:
        plan["evidence"][0]["exhibit"] = {
            key: value for key, value in original.items() if key != field
        }
        assert scaffold.validate_spec(plan), field
    plan["evidence"][0]["exhibit"] = {**original, "onload": "alert(1)"}
    assert scaffold.validate_spec(plan)
