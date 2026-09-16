"""Point-in-time freshness and digest-bound snapshot publication."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

import pytest
from test_timenarratives_render_cli import _args, _journey

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))
renderer = importlib.import_module("render_deliverable")


def _assert_uncommitted(output: Path) -> None:
    assert not output.exists()
    stages = list(output.parent.glob(f".{output.name}.stage-*"))
    assert len(stages) == 1
    assert [item.name for item in stages[0].iterdir()] == ["artifacts"]
    assert sorted(item.name for item in (stages[0] / "artifacts").iterdir()) == [
        "deliverable.json",
        "narratives.md",
    ]


@pytest.mark.parametrize("mutation", ["source_edit", "source_delete", "request_edit"])
def test_cli_freshness_change_refuses_snapshot_commit(
    tmp_path: Path, mutation: str
) -> None:
    paths = _journey(tmp_path)
    if mutation == "source_edit":
        paths["source"].write_text("Changed after confirmation.\n", encoding="utf-8")
    elif mutation == "source_delete":
        paths["source"].unlink()
    else:
        request = json.loads(paths["request"].read_text(encoding="utf-8"))
        request["matter"]["client"] = "Changed after confirmation"
        paths["request"].write_text(json.dumps(request), encoding="utf-8")
    output = tmp_path / "refused"

    assert renderer.main(_args(paths, output)) == 1
    _assert_uncommitted(output)


def test_unchanged_present_unsupported_source_can_render_partial_receipt(
    tmp_path: Path,
) -> None:
    paths = _journey(tmp_path, with_unsupported=True)
    output = tmp_path / "partial"

    assert renderer.main(_args(paths, output)) == 0
    deliverable = json.loads(
        (output / "artifacts" / "deliverable.json").read_text(encoding="utf-8")
    )
    assert deliverable["status"] == "incomplete"
    assert deliverable["receipt"]["counts"]["packetErrors"] == 1


@pytest.mark.parametrize("mutation", ["edit", "delete"])
def test_unsupported_source_change_after_confirmation_refuses_snapshot_commit(
    tmp_path: Path, mutation: str
) -> None:
    paths = _journey(tmp_path, with_unsupported=True)
    if mutation == "edit":
        paths["unsupported"].write_bytes(b"changed unsupported bytes\n")
    else:
        paths["unsupported"].unlink()
    output = tmp_path / "refused"

    assert renderer.main(_args(paths, output)) == 1
    _assert_uncommitted(output)


def test_source_bytes_are_digest_bound_before_publication(tmp_path: Path) -> None:
    paths = _journey(tmp_path)
    original = paths["source"].read_bytes()
    paths["source"].write_bytes(original + b"changed")
    assert (
        hashlib.sha256(paths["source"].read_bytes()).digest()
        != hashlib.sha256(original).digest()
    )

    output = tmp_path / "result"
    assert renderer.main(_args(paths, output)) == 1
    _assert_uncommitted(output)


def test_source_change_immediately_before_freshness_check_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _journey(tmp_path)
    output = tmp_path / "result"
    original_compile = renderer.compile_packet

    def change_source_then_compile(request: dict, source_root: Path) -> dict:
        paths["source"].write_text(
            "Changed immediately before the freshness check.\n", encoding="utf-8"
        )
        return original_compile(request, source_root)

    monkeypatch.setattr(renderer, "compile_packet", change_source_then_compile)

    assert renderer.main(_args(paths, output)) == 1
    _assert_uncommitted(output)


@pytest.mark.parametrize("mutation", ["valid_change", "duplicate_key"])
def test_request_change_during_cli_before_freshness_check_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    paths = _journey(tmp_path)
    output = tmp_path / "result"
    original_publish = renderer.publish_owned_directory

    def mutate_then_publish(
        path: str | Path,
        files: Mapping[str, bytes],
        *,
        protected_paths: Iterable[str | Path] = (),
        forbidden_roots: Iterable[str | Path] = (),
        before_publish: Callable[[], None] | None = None,
    ) -> Path:
        if mutation == "valid_change":
            request = json.loads(paths["request"].read_text(encoding="utf-8"))
            request["matter"]["client"] = "Changed during render"
            paths["request"].write_text(json.dumps(request), encoding="utf-8")
        else:
            paths["request"].write_text('{"value":1,"value":2}', encoding="utf-8")
        return original_publish(
            path,
            files,
            protected_paths=protected_paths,
            forbidden_roots=forbidden_roots,
            before_publish=before_publish,
        )

    monkeypatch.setattr(renderer, "publish_owned_directory", mutate_then_publish)

    assert renderer.main(_args(paths, output)) == 1
    _assert_uncommitted(output)


def test_source_change_after_snapshot_commit_keeps_the_bound_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _journey(tmp_path)
    output = tmp_path / "result"
    packet = json.loads(paths["packet"].read_text(encoding="utf-8"))
    safe_output = importlib.import_module("safe_output")
    original_commit = safe_output.rename_no_replace

    def publish_then_change_source(source: Path, destination: Path) -> None:
        original_commit(source, destination)
        paths["source"].write_text(
            "Changed after the snapshot commit.\n", encoding="utf-8"
        )

    monkeypatch.setattr(safe_output, "rename_no_replace", publish_then_change_source)

    assert renderer.main(_args(paths, output)) == 0
    deliverable = json.loads(
        (output / "artifacts" / "deliverable.json").read_text(encoding="utf-8")
    )
    assert deliverable["receipt"]["packetDigest"] == packet["packetDigestSha256"]
    assert paths["source"].read_text(encoding="utf-8").startswith("Changed after")
    assert sorted(item.name for item in (output / "artifacts").iterdir()) == [
        "deliverable.json",
        "narratives.md",
    ]


def test_freshness_operational_error_is_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _journey(tmp_path)

    def fail_compile(request: dict, source_root: Path) -> dict:
        raise OSError("PRIVATE selected source path")

    monkeypatch.setattr(renderer, "compile_packet", fail_compile)
    output = tmp_path / "result"
    assert renderer.main(_args(paths, output)) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "status": "operational_fault",
        "error": "freshness_check_failed",
    }
    assert "PRIVATE" not in captured.out + captured.err
    _assert_uncommitted(output)
