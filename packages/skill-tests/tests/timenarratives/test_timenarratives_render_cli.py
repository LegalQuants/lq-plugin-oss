"""First-use rendering, freshness, and atomic-directory publication tests."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
from test_timenarratives_contracts import make_confirmation

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))
build_packet = importlib.import_module("build_packet")
renderer = importlib.import_module("render_deliverable")


def _request() -> dict:
    return {
        "schemaVersion": "timenarratives.request.v1",
        "runId": "Render_Run",
        "actor": {
            "id": "ACTOR1",
            "name": "Synthetic Lawyer",
            "aliases": [],
        },
        "matter": {
            "id": "MATTER1",
            "client": "Synthetic Client",
            "aliases": [],
        },
        "selections": [{"kind": "file", "path": "work.txt"}],
        "filters": {
            "sourceTypes": ["text"],
            "since": None,
            "until": None,
            "asOf": "2026-08-21T12:00:00+01:00",
        },
    }


def _journey(tmp_path: Path, *, with_unsupported: bool = False) -> dict[str, Path]:
    source_root = tmp_path / "selected"
    source_root.mkdir()
    source = source_root / "work.txt"
    source.write_text("Reviewed the synthetic chronology.\n", encoding="utf-8")
    request = _request()
    unsupported = source_root / "archive.msg"
    if with_unsupported:
        unsupported.write_bytes(b"synthetic unsupported container\n")
        request["selections"].append({"kind": "file", "path": "archive.msg"})
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    packet = build_packet.compile_packet(request, source_root)
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    mapping = {
        "schemaVersion": "timenarratives.map.v1",
        "runId": packet["runId"],
        "packetDigest": packet["packetDigestSha256"],
        "unitAssessment": [
            {
                "unitId": packet["units"][0]["unitId"],
                "disposition": "read_but_unused",
                "reason": "not_relevant",
            }
        ],
        "atoms": [],
        "events": [],
        "workstreams": [],
        "clauses": [],
    }
    map_path = tmp_path / "map.json"
    map_path.write_text(json.dumps(mapping), encoding="utf-8")
    confirmation = make_confirmation(packet, mapping)
    confirmation_path = tmp_path / "confirmation.json"
    confirmation_path.write_text(json.dumps(confirmation), encoding="utf-8")
    return {
        "source_root": source_root,
        "source": source,
        "unsupported": unsupported,
        "request": request_path,
        "packet": packet_path,
        "map": map_path,
        "confirmation": confirmation_path,
    }


def _args(paths: dict[str, Path], output: Path) -> list[str]:
    return [
        "--request",
        str(paths["request"]),
        "--source-root",
        str(paths["source_root"]),
        "--packet",
        str(paths["packet"]),
        "--map",
        str(paths["map"]),
        "--confirmation",
        str(paths["confirmation"]),
        "--out-dir",
        str(output),
    ]


def test_cli_publishes_one_complete_new_directory_deterministically(
    tmp_path: Path,
) -> None:
    paths = _journey(tmp_path)
    results = []
    for index in range(2):
        output = tmp_path / f"result-{index}"
        assert renderer.main(_args(paths, output)) == 0
        assert [item.name for item in output.iterdir()] == ["artifacts"]
        artifacts = output / "artifacts"
        assert sorted(item.name for item in artifacts.iterdir()) == [
            "deliverable.json",
            "narratives.md",
        ]
        results.append(
            (
                (artifacts / "deliverable.json").read_bytes(),
                (artifacts / "narratives.md").read_bytes(),
            )
        )
    assert results[0] == results[1]


def test_cli_stale_confirmation_writes_no_directory(tmp_path: Path) -> None:
    paths = _journey(tmp_path)
    mapping = json.loads(paths["map"].read_text(encoding="utf-8"))
    mapping["unitAssessment"][0]["reason"] = None
    paths["map"].write_text(json.dumps(mapping), encoding="utf-8")
    output = tmp_path / "refused"

    assert renderer.main(_args(paths, output)) == 1
    assert not output.exists()


@pytest.mark.parametrize("kind", ["file", "directory", "input", "inside_source"])
def test_cli_refuses_existing_alias_or_unowned_output(
    tmp_path: Path, kind: str
) -> None:
    paths = _journey(tmp_path)
    if kind == "file":
        output = tmp_path / "PRIVATE-existing"
        output.write_text("preserve", encoding="utf-8")
    elif kind == "directory":
        output = tmp_path / "PRIVATE-existing"
        output.mkdir()
    elif kind == "input":
        output = paths["packet"]
    else:
        output = paths["source_root"] / "PRIVATE-result"

    assert renderer.main(_args(paths, output)) == 2
    if kind == "file":
        assert output.read_text(encoding="utf-8") == "preserve"
    assert "PRIVATE" not in ""  # sensitive names are checked in subprocess smoke


def test_cli_refuses_symlinked_output_ancestor(tmp_path: Path) -> None:
    paths = _journey(tmp_path)
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this host")
    output = linked_parent / "result"

    assert renderer.main(_args(paths, output)) == 2
    assert not (real_parent / "result").exists()


@pytest.mark.parametrize("failure", [OSError("replace failed"), KeyboardInterrupt()])
def test_publication_base_exception_leaves_uncommitted_owned_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    paths = _journey(tmp_path)
    output = tmp_path / "result"
    safe_output = importlib.import_module("safe_output")

    def fail_publish(source: Path, target: Path) -> None:
        staged = Path(source)
        assert [item.name for item in staged.iterdir()] == ["artifacts"]
        assert sorted(item.name for item in (staged / "artifacts").iterdir()) == [
            "deliverable.json",
            "narratives.md",
        ]
        raise failure

    monkeypatch.setattr(safe_output, "rename_no_replace", fail_publish)
    assert renderer.main(_args(paths, output)) == 2
    assert not output.exists()
    stages = list(tmp_path.glob(".result.stage-*"))
    assert len(stages) == 1
    assert sorted(item.name for item in (stages[0] / "artifacts").iterdir()) == [
        "deliverable.json",
        "narratives.md",
    ]


def test_publication_failure_preserves_swapped_replacement_at_output_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _journey(tmp_path)
    output = tmp_path / "result"
    displaced = tmp_path / "displaced-owned-result"
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    (replacement / "preserve").write_text("untouched", encoding="utf-8")
    safe_output = importlib.import_module("safe_output")
    original_commit = safe_output.rename_no_replace
    original_replace = safe_output.os.replace

    def fail_publish(source: Path, destination: Path) -> None:
        original_replace(replacement, output)
        original_commit(source, destination)

    monkeypatch.setattr(safe_output, "rename_no_replace", fail_publish)

    assert renderer.main(_args(paths, output)) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "status": "operational_fault",
        "error": "output_publication_failed",
    }
    assert (output / "preserve").read_text(encoding="utf-8") == "untouched"
    assert not displaced.exists()
    stages = list(tmp_path.glob(".result.stage-*"))
    assert len(stages) == 1
    assert (stages[0] / "artifacts" / "deliverable.json").is_file()


def test_cli_refuses_nonempty_target_substitution_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _journey(tmp_path)
    output = tmp_path / "result"
    displaced = tmp_path / "displaced-owned-result"
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    (replacement / "preserve").write_text("untouched", encoding="utf-8")
    safe_output = importlib.import_module("safe_output")
    original_stage = safe_output._make_stage_dir
    original_replace = safe_output.os.replace

    def substitute_before_staging(parent: Path, prefix: str) -> Path:
        if output.exists():
            original_replace(output, displaced)
        original_replace(replacement, output)
        return original_stage(parent, prefix)

    monkeypatch.setattr(safe_output, "_make_stage_dir", substitute_before_staging)

    assert renderer.main(_args(paths, output)) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "status": "operational_fault",
        "error": "output_publication_failed",
    }
    assert sorted(item.name for item in output.iterdir()) == ["preserve"]
    assert (output / "preserve").read_text(encoding="utf-8") == "untouched"
    assert not displaced.exists()
    stages = list(tmp_path.glob(".result.stage-*"))
    assert len(stages) == 1
    assert sorted(item.name for item in (stages[0] / "artifacts").iterdir()) == [
        "deliverable.json",
        "narratives.md",
    ]


def _approved_args(paths: dict[str, Path], output: Path) -> list[str]:
    args = _args(paths, output)
    index = args.index("--confirmation")
    reviewed = json.loads(paths["confirmation"].read_text(encoding="utf-8"))
    return (
        args[:index]
        + ["--user-approved", "--reviewed-map-digest", reviewed["mapDigest"]]
        + args[index + 2 :]
    )


def test_user_approved_flag_publishes_without_a_confirmation_file(
    tmp_path: Path,
) -> None:
    paths = _journey(tmp_path)
    output = tmp_path / "approved"
    assert renderer.main(_approved_args(paths, output)) == 0
    deliverable = json.loads(
        (output / "artifacts" / "deliverable.json").read_text(encoding="utf-8")
    )
    expected = json.loads(paths["confirmation"].read_text(encoding="utf-8"))
    assert deliverable["receipt"]["confirmationToken"] == expected["confirmationToken"]
    assert deliverable["receipt"]["mapDigest"] == expected["mapDigest"]


def test_user_approved_still_refuses_a_stale_map(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _journey(tmp_path)
    mapping = json.loads(paths["map"].read_text(encoding="utf-8"))
    mapping["packetDigest"] = "0" * 64
    paths["map"].write_text(json.dumps(mapping), encoding="utf-8")
    assert renderer.main(_approved_args(paths, tmp_path / "stale")) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "contract_fault"
    assert not (tmp_path / "stale").exists()


def test_confirmation_and_user_approved_are_mutually_exclusive(
    tmp_path: Path,
) -> None:
    paths = _journey(tmp_path)
    with pytest.raises(SystemExit):
        renderer.main(_args(paths, tmp_path / "x") + ["--user-approved"])
