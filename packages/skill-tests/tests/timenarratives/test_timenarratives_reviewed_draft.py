"""Ordinary approval cannot approve a different, otherwise-valid displayed map."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_timenarratives_render_cli import _approved_args, _journey, renderer


def test_changed_valid_map_cannot_inherit_ordinary_approval(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _journey(tmp_path)
    args = _approved_args(paths, tmp_path / "result")
    mapping = json.loads(paths["map"].read_text(encoding="utf-8"))
    mapping["unitAssessment"][0].update(
        disposition="needs_confirmation", reason="action_unclear"
    )
    packet = json.loads(paths["packet"].read_text(encoding="utf-8"))
    assert renderer.validate_map(packet, mapping)["faults"] == []
    paths["map"].write_text(json.dumps(mapping), encoding="utf-8")

    assert renderer.main(args) == 1
    assert not (tmp_path / "result").exists()
    assert json.loads(capsys.readouterr().out)["faults"][0]["code"] == (
        "reviewed_map_mismatch"
    )


def test_missing_displayed_digest_does_not_self_approve(tmp_path: Path) -> None:
    paths = _journey(tmp_path)
    args = _approved_args(paths, tmp_path / "result")
    index = args.index("--reviewed-map-digest")
    del args[index : index + 2]
    assert renderer.main(args) == 1
    assert not (tmp_path / "result").exists()
