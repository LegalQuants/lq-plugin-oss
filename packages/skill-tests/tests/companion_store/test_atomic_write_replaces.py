"""Store and marker writes must succeed when the target already exists.

Path.rename refuses an existing target on Windows, so the second write of
profile.json or onboarding.json failed there (found by James Cockburn running
the suite on Windows, 6 Sep 2026). os.replace overwrites on every platform.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = {
    "onboarding": ROOT / "skills/companion/legalquants/scripts/onboarding.py",
    "profile_store": ROOT / "skills/companion/lq-reflect/scripts/profile_store.py",
    "session_reader": ROOT / "skills/companion/lq-reflect/scripts/session_reader.py",
}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS[name])
    assert spec is not None and spec.loader is not None, name
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["onboarding", "profile_store"])
def test_atomic_write_overwrites_an_existing_file(tmp_path: Path, name: str) -> None:
    module = _load(name)
    target = tmp_path / "state.json"
    module.atomic_write(target, "first\n")
    module.atomic_write(target, "second\n")
    assert target.read_text() == "second\n"
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_atomic_json_overwrites_an_existing_manifest(tmp_path: Path) -> None:
    module = _load("session_reader")
    target = tmp_path / "manifest.json"
    module.atomic_json(target, {"n": 1})
    module.atomic_json(target, {"n": 2})
    assert json.loads(target.read_text()) == {"n": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["manifest.json"]


def test_no_rename_onto_existing_targets_remains() -> None:
    for name, path in SCRIPTS.items():
        assert "tmp.rename(path)" not in path.read_text(encoding="utf-8"), name
