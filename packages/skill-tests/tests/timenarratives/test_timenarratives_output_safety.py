"""New-only TimeNarratives output boundary regressions."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_timenarratives_contracts import make_map, make_packet
from test_timenarratives_render_cli import _args, _journey

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))
safe_output = importlib.import_module("safe_output")
build_packet = importlib.import_module("build_packet")
validate_map_cli = importlib.import_module("validate_map")
renderer = importlib.import_module("render_deliverable")


def _note_request() -> dict:
    return {
        "schemaVersion": "timenarratives.request.v1",
        "runId": "OutputSafety",
        "actor": {"id": "ACTOR1", "name": "Synthetic Lawyer", "aliases": []},
        "matter": {"id": "MATTER1", "client": None, "aliases": []},
        "selections": [{"kind": "user_note", "text": "Reviewed authorities"}],
        "filters": {
            "sourceTypes": ["user_note"],
            "since": None,
            "until": None,
            "asOf": "2026-08-21T12:00:00+01:00",
        },
    }


def test_new_file_publication_is_fully_staged_and_never_replaces(
    tmp_path: Path,
) -> None:
    target = tmp_path / "packet.json"
    safe_output.write_new_bytes(target, b"complete\n")
    assert target.read_bytes() == b"complete\n"

    with pytest.raises(safe_output.OutputSafetyError):
        safe_output.write_new_bytes(target, b"replacement\n")
    assert target.read_bytes() == b"complete\n"


def test_new_file_refuses_hardlink_alias_without_changing_input(tmp_path: Path) -> None:
    source = tmp_path / "request.json"
    source.write_bytes(b"authoritative\n")
    alias = tmp_path / "packet.json"
    try:
        os.link(source, alias)
    except OSError:
        pytest.skip("hard links are unavailable on this filesystem")

    with pytest.raises(safe_output.OutputSafetyError):
        safe_output.write_new_bytes(alias, b"replacement\n", protected_paths=(source,))
    assert source.read_bytes() == alias.read_bytes() == b"authoritative\n"


def test_new_output_refuses_symlink_target_and_ancestor(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    target_value = tmp_path / "protected"
    target_value.write_text("preserve", encoding="utf-8")
    linked_target = tmp_path / "linked-target"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        linked_target.symlink_to(target_value)
    except OSError:
        pytest.skip("symlinks are unavailable on this host")

    with pytest.raises(safe_output.OutputSafetyError):
        safe_output.write_new_bytes(linked_parent / "packet.json", b"data")
    with pytest.raises(safe_output.OutputSafetyError):
        safe_output.write_new_bytes(linked_target, b"data")
    assert not (real_parent / "packet.json").exists()
    assert target_value.read_text(encoding="utf-8") == "preserve"


def test_atomic_directory_claim_loses_race_without_deleting_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "result"
    original_validate = safe_output.validate_new_output

    def inject_competing_claim(*args, **kwargs) -> Path:
        checked = original_validate(*args, **kwargs)
        checked.mkdir()
        (checked / "winner").write_text("preserve", encoding="utf-8")
        return checked

    monkeypatch.setattr(safe_output, "validate_new_output", inject_competing_claim)
    with pytest.raises(safe_output.OutputSafetyError):
        safe_output.publish_owned_directory(target, {"deliverable.json": b"{}\n"})
    assert (target / "winner").read_text(encoding="utf-8") == "preserve"


def test_artifact_child_appears_only_as_a_complete_atomic_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "result"
    original_commit = safe_output.rename_no_replace
    observations: list[list[str]] = []

    def inspect_then_commit(source: Path, destination: Path) -> None:
        assert Path(destination) == target
        assert [item.name for item in Path(source).iterdir()] == ["artifacts"]
        observations.append(
            sorted(item.name for item in (Path(source) / "artifacts").iterdir())
        )
        assert not target.exists()
        original_commit(source, destination)

    monkeypatch.setattr(safe_output, "rename_no_replace", inspect_then_commit)
    published = safe_output.publish_owned_directory(
        target,
        {"deliverable.json": b"{}\n", "narratives.md": b"No activity.\n"},
    )

    assert observations == [["deliverable.json", "narratives.md"]]
    assert published == target / "artifacts"
    assert sorted(item.name for item in published.iterdir()) == [
        "deliverable.json",
        "narratives.md",
    ]


def test_file_publication_base_exception_cleans_only_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "packet.json"

    def interrupt(source: Path, destination: Path) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(safe_output.os, "link", interrupt)
    with pytest.raises(KeyboardInterrupt):
        safe_output.write_new_bytes(target, b"complete\n")
    assert not target.exists()
    assert not list(tmp_path.glob(".packet.json.stage-*"))


def test_compile_directory_refuses_existing_or_source_owned_target(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    existing = tmp_path / "existing"
    existing.mkdir()
    marker = existing / "preserve"
    marker.write_text("untouched", encoding="utf-8")

    with pytest.raises(OSError):
        build_packet.compile_packet_to_directory(_note_request(), source_root, existing)
    assert marker.read_text(encoding="utf-8") == "untouched"

    inside_source = source_root / "result"
    with pytest.raises(OSError):
        build_packet.compile_packet_to_directory(
            _note_request(), source_root, inside_source
        )
    assert not inside_source.exists()


def test_compile_directory_refuses_reparse_target(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this host")

    with pytest.raises(OSError):
        build_packet.compile_packet_to_directory(_note_request(), source_root, linked)
    assert list(real.iterdir()) == []


def test_validator_refuses_existing_hardlink_alias_to_packet(tmp_path: Path) -> None:
    packet = make_packet()
    mapping = make_map(packet)
    packet_path = tmp_path / "packet.json"
    map_path = tmp_path / "map.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    map_path.write_text(json.dumps(mapping), encoding="utf-8")
    before = packet_path.read_bytes()
    output = tmp_path / "validation.json"
    try:
        os.link(packet_path, output)
    except OSError:
        pytest.skip("hard links are unavailable on this filesystem")

    code = validate_map_cli.main(
        [
            "--packet",
            str(packet_path),
            "--map",
            str(map_path),
            "--out",
            str(output),
        ]
    )

    assert code == 2
    assert output.read_bytes() == packet_path.read_bytes() == before


def test_publication_failure_leaves_a_swapped_output_identity_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "result"
    original_commit = safe_output.rename_no_replace

    def race_then_commit(source: Path, destination: Path) -> None:
        target.mkdir()
        (target / "winner").write_text("preserve", encoding="utf-8")
        original_commit(source, destination)

    monkeypatch.setattr(safe_output, "rename_no_replace", race_then_commit)
    with pytest.raises(FileExistsError):
        safe_output.publish_owned_directory(
            target,
            {"deliverable.json": b"{}\n", "narratives.md": b"draft\n"},
        )
    assert (target / "winner").read_text(encoding="utf-8") == "preserve"
    assert not (target / "artifacts").exists()
    stages = list(tmp_path.glob(".result.stage-*"))
    assert len(stages) == 1
    assert (stages[0] / "artifacts" / "deliverable.json").is_file()


def test_publication_final_race_refuses_an_empty_target_without_replacing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "result"
    original_commit = safe_output.rename_no_replace

    def race_then_commit(source: Path, destination: Path) -> None:
        target.mkdir()
        original_commit(source, destination)

    monkeypatch.setattr(safe_output, "rename_no_replace", race_then_commit)
    with pytest.raises(FileExistsError):
        safe_output.publish_owned_directory(
            target,
            {"deliverable.json": b"{}\n", "narratives.md": b"draft\n"},
        )

    assert target.is_dir() and list(target.iterdir()) == []
    stages = list(tmp_path.glob(".result.stage-*"))
    assert len(stages) == 1
    assert sorted(item.name for item in (stages[0] / "artifacts").iterdir()) == [
        "deliverable.json",
        "narratives.md",
    ]


def test_failure_path_never_moves_or_deletes_a_replacement(
    tmp_path: Path,
) -> None:
    target = tmp_path / "result"
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    marker = replacement / "preserve"
    marker.write_text("untouched", encoding="utf-8")
    original_replace = safe_output.os.replace

    def replace_then_cancel() -> None:
        original_replace(replacement, target)
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        safe_output.publish_owned_directory(
            target,
            {"deliverable.json": b"{}\n"},
            before_publish=replace_then_cancel,
        )

    assert target.is_dir()
    assert (target / marker.name).read_text(encoding="utf-8") == "untouched"
    assert not (target / "artifacts").exists()
    stages = list(tmp_path.glob(".result.stage-*"))
    assert len(stages) == 1
    assert (stages[0] / "artifacts" / "deliverable.json").is_file()


def test_freshness_recompile_occurs_immediately_before_snapshot_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _journey(tmp_path)
    target = tmp_path / "result"
    original_compile = renderer.compile_packet
    observations: list[str] = []

    def inspect_then_compile(request: dict, source_root: Path) -> dict:
        stages = list(target.parent.glob(f".{target.name}.stage-*"))
        assert len(stages) == 1
        assert [item.name for item in stages[0].iterdir()] == ["artifacts"]
        assert sorted(item.name for item in (stages[0] / "artifacts").iterdir()) == [
            "deliverable.json",
            "narratives.md",
        ]
        assert not target.exists()
        observations.append("before")
        return original_compile(request, source_root)

    monkeypatch.setattr(renderer, "compile_packet", inspect_then_compile)
    assert renderer.main(_args(paths, target)) == 0
    assert observations == ["before"]
    assert (target / "artifacts" / "deliverable.json").is_file()


def test_unexpected_render_validation_fault_is_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _journey(tmp_path)

    def fail_validation(packet: dict, mapping: dict, confirmation: dict) -> dict:
        raise RuntimeError("PRIVATE workspace path")

    monkeypatch.setattr(renderer, "build_rendered", fail_validation)
    target = tmp_path / "result"
    assert renderer.main(_args(paths, target)) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "status": "operational_fault",
        "error": "validation_failed",
    }
    assert "PRIVATE" not in captured.out + captured.err
    assert not target.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL behaviour")
def test_windows_publication_inherits_parent_acl(tmp_path: Path) -> None:
    target = tmp_path / "run"
    safe_output.publish_owned_directory(target, {"deliverable.json": b"{}\n"})
    for path in (target, target / "artifacts"):
        acl = subprocess.run(
            ["icacls", str(path)], capture_output=True, text=True, check=True
        ).stdout
        entries = [
            line[line.rfind(":(") + 1 :]
            for line in acl.splitlines()
            if ":(" in line and not line.startswith("Successfully")
        ]
        assert entries, acl
        assert all(entry.startswith("(I)") for entry in entries), acl
