"""Named folder intake stays bounded and composes with chat and attestations."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[4] / "skills/core/timenarratives/scripts"
sys.path.insert(0, str(SCRIPTS))
folders = importlib.import_module("folder_selection")
start = importlib.import_module("start_run")
compiler = importlib.import_module("build_packet")


def put(root: Path, name: str, text: str = "Selected context.") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def request(root: Path, **kwargs):
    return start.build_request(
        lawyer="Alex Hart", matter="Cedar", source_root=root, **kwargs
    )


def test_named_folder_includes_nested_files_without_selecting_sibling(tmp_path):
    put(tmp_path, "Cedar/z.txt")
    put(tmp_path, "Cedar/nested/a.md")
    put(tmp_path, "Other/private.txt")
    assert folders.expand_folders(tmp_path, ["Cedar"], []) == [
        "Cedar/nested/a.md",
        "Cedar/z.txt",
    ]


def test_overlapping_folders_and_explicit_file_have_one_selection(tmp_path):
    put(tmp_path, "Cedar/nested/a.txt")
    assert folders.expand_folders(
        tmp_path, ["Cedar", "Cedar/nested", "Cedar"], ["Cedar/nested/a.txt"]
    ) == ["Cedar/nested/a.txt"]


def test_explicit_root_and_absolute_folder_paths_are_supported(tmp_path):
    put(tmp_path, "a.txt")
    req = request(tmp_path, paths=[], folders=[str(tmp_path)])
    assert req["selections"] == [{"kind": "file", "path": "a.txt"}]


def test_folders_without_source_root_are_rejected():
    with pytest.raises(compiler.PacketBuildError, match="source root"):
        start.build_request(lawyer="Alex", matter="Cedar", paths=[], folders=["Cedar"])


@pytest.mark.parametrize("name", ["../Other", "/outside", "missing", "note.txt"])
def test_invalid_folder_fails_before_any_run_is_created(tmp_path, capsys, name):
    root = tmp_path / "sources"
    root.mkdir()
    put(root, "note.txt")
    code = start.main(
        [
            "--lawyer",
            "Alex",
            "--matter",
            "Cedar",
            "--source-root",
            str(root),
            "--folder",
            name,
        ]
    )
    assert code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "invalid_request"
    assert list(tmp_path.glob(".timenarratives-run-*")) == []


@pytest.mark.parametrize("target_inside", [True, False])
def test_symlink_is_refused_even_when_target_inside_root(tmp_path, target_inside):
    root = tmp_path / "source"
    put(root, "Cedar/a.txt")
    target = root / "target" if target_inside else tmp_path / "outside"
    put(target, "private.txt")
    try:
        (root / "Cedar/link").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit creating a symlink")
    with pytest.raises(folders.SourcePathError, match="link or reparse"):
        folders.expand_folders(root, ["Cedar"], [])


def test_selected_folder_itself_cannot_be_a_link(tmp_path):
    put(tmp_path, "real/a.txt")
    try:
        (tmp_path / "alias").symlink_to(tmp_path / "real", target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit creating a symlink")
    with pytest.raises(folders.SourcePathError, match="link or reparse"):
        folders.expand_folders(tmp_path, ["alias"], [])


@pytest.mark.parametrize("nested", [False, True])
def test_absolute_folder_preserves_link_components_for_refusal(tmp_path, nested):
    put(tmp_path, "real/sub/a.txt")
    try:
        (tmp_path / "alias").symlink_to(tmp_path / "real", target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit creating a symlink")
    selected = tmp_path / "alias/sub" if nested else tmp_path / "alias"
    with pytest.raises(folders.SourcePathError, match="link or reparse"):
        request(tmp_path, paths=[], folders=[str(selected)])


def test_absolute_file_alias_is_not_resolved_away(tmp_path):
    put(tmp_path, "real.txt")
    try:
        (tmp_path / "alias.txt").symlink_to(tmp_path / "real.txt")
    except OSError:
        pytest.skip("host does not permit creating a symlink")
    req = request(tmp_path, paths=[str(tmp_path / "alias.txt")])
    assert req["selections"] == [{"kind": "file", "path": "alias.txt"}]
    packet = compiler.compile_packet(req, tmp_path)
    assert packet["roots"][0]["disposition"] == "unreadable"


def test_hidden_and_unsupported_files_are_accounted_not_silently_dropped(tmp_path):
    put(tmp_path, "Cedar/.note.txt")
    put(tmp_path, "Cedar/scan.pdf", "Unsupported PDF content.")
    packet = compiler.compile_packet(
        request(tmp_path, paths=[], folders=["Cedar"]), tmp_path
    )
    assert len(packet["roots"]) == 2
    assert any(row["reason"] == "unsupported_format" for row in packet["roots"])


def test_too_many_files_refuses_instead_of_using_first_thirty(tmp_path):
    for index in range(31):
        put(tmp_path, f"Cedar/{index}.txt")
    with pytest.raises(compiler.PacketBuildError, match="packet limit"):
        request(tmp_path, paths=[], folders=["Cedar"])


def test_total_limit_includes_notes_with_folder_files(tmp_path):
    for index in range(30):
        put(tmp_path, f"Cedar/{index}.txt")
    with pytest.raises(compiler.PacketBuildError):
        request(
            tmp_path, paths=[], folders=["Cedar"], notes=["I reviewed the agreement."]
        )


def test_empty_directory_enumeration_is_bounded(tmp_path, monkeypatch):
    for index in range(4):
        (tmp_path / f"empty{index}").mkdir()
    monkeypatch.setattr(folders, "MAX_FOLDER_ENTRIES", 3)
    with pytest.raises(compiler.PacketBuildError, match="too large"):
        folders.expand_folders(tmp_path, ["."], [])


def test_depth_is_bounded(tmp_path, monkeypatch):
    put(tmp_path, "a/b/c/note.txt")
    monkeypatch.setattr(folders, "MAX_FOLDER_DEPTH", 1)
    with pytest.raises(compiler.PacketBuildError, match="too deep"):
        folders.expand_folders(tmp_path, ["."], [])


def test_empty_folder_does_not_invent_sources(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(compiler.PacketBuildError):
        request(tmp_path, paths=[], folders=["empty"])


def test_folder_selection_freezes_membership_without_monitoring(tmp_path):
    put(tmp_path, "Cedar/a.txt")
    req = request(tmp_path, paths=[], folders=["Cedar"])
    put(tmp_path, "Cedar/later.txt")
    packet = compiler.compile_packet(req, tmp_path)
    assert len(packet["roots"]) == 1
    assert req["selections"] == [{"kind": "file", "path": "Cedar/a.txt"}]


def test_cli_combines_chat_offline_documents_and_lawyer_account(tmp_path, capsys):
    from test_timenarratives_conversation import message, snapshot

    root = tmp_path / "sources"
    put(
        root,
        "Cedar/call.md",
        "Alex discussed the suspension provision with the client.",
    )
    put(root, "Other/private.txt", "Unselected material.")
    put(
        root, "chat.json", json.dumps(snapshot([message(), message("ai", "assistant")]))
    )
    identity = json.loads((root / "chat.json").read_text())["conversationId"]
    assert (
        start.main(
            [
                "--lawyer",
                "Alex Hart",
                "--matter",
                "Cedar",
                "--source-root",
                str(root),
                "--folder",
                "Cedar",
                "--conversation",
                identity,
                "chat.json",
                "--note",
                "I reviewed Morgan's amendments and discussed the suspension "
                "provision with the client.",
                "--as-of",
                "2026-09-06T20:00:00+01:00",
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    packet = json.loads(Path(summary["packet"]).read_text(encoding="utf-8"))
    req = json.loads(Path(summary["request"]).read_text(encoding="utf-8"))
    assert summary["selected"] == 3
    assert {row["kind"] for row in req["selections"]} == {
        "file",
        "conversation",
        "user_note",
    }
    assert "Unselected material" not in json.dumps(packet)
    assert any(row["sourceClass"] == "user_attested" for row in packet["units"])
    assert any(row["eligibility"] == "context_only" for row in packet["units"])
