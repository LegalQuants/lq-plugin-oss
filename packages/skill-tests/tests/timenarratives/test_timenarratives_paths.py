from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def paths_module():
    path = SCRIPTS / "source_paths.py"
    assert path.is_file(), "source_paths.py has not been implemented"
    return importlib.import_module("source_paths")


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/absolute.txt",
        "//server/share.txt",
        "C:/secret.txt",
        "../escape.txt",
        "folder/../escape.txt",
        "folder\\file.txt",
        "folder//file.txt",
        "report.txt:stream",
        "CON.txt",
        "folder/NUL",
    ],
)
def test_unsafe_relative_source_paths_are_rejected(value: str) -> None:
    paths = paths_module()

    with pytest.raises(paths.SourcePathError):
        paths.validate_relative_path(value)


def test_bounded_read_returns_exact_bytes_and_full_hash(tmp_path: Path) -> None:
    paths = paths_module()
    source = tmp_path / "evidence.txt"
    source.write_bytes("café\r\n".encode())

    result = paths.read_bounded_file(tmp_path, "evidence.txt", max_bytes=32)

    assert result.data == b"caf\xc3\xa9\r\n"
    assert result.byte_length == 7
    assert result.sha256 == (
        "7f2adbdb77890209f13a322e75d8aa13b9169722e702a2e367250125d33e8832"
    )
    assert result.display_name == "evidence.txt"


def test_bounded_read_rejects_oversize_without_truncation(tmp_path: Path) -> None:
    paths = paths_module()
    (tmp_path / "large.txt").write_bytes(b"abcdef")

    with pytest.raises(paths.SourceReadError, match="exceeds"):
        paths.read_bounded_file(tmp_path, "large.txt", max_bytes=5)


def test_selected_symlink_is_rejected(tmp_path: Path) -> None:
    paths = paths_module()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this host")

    with pytest.raises(paths.SourcePathError, match="symlink|reparse"):
        paths.read_bounded_file(tmp_path, "link.txt", max_bytes=32)


def test_atomic_json_write_replaces_file_inside_owned_root(tmp_path: Path) -> None:
    paths = paths_module()
    output = tmp_path / "run"
    output.mkdir()
    target = output / "packet.json"

    paths.atomic_write_json(target, {"runId": "R1"}, output_root=output)
    paths.atomic_write_json(target, {"runId": "R2"}, output_root=output)

    assert json.loads(target.read_text(encoding="utf-8")) == {"runId": "R2"}
    assert target.read_bytes().endswith(b"\n")
