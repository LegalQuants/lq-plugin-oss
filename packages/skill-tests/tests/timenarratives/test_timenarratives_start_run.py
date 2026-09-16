"""start_run builds a valid request, sites the run beside the sources, compiles."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))
start_run = importlib.import_module("start_run")
packet_core = importlib.import_module("packet_core")


def _sources(tmp_path: Path) -> Path:
    root = tmp_path / "selected"
    root.mkdir()
    (root / "note.txt").write_text("Reviewed the escrow clause.\n", encoding="utf-8")
    return root


def test_request_is_schema_valid_with_only_lawyer_matter_and_paths() -> None:
    request = start_run.build_request(
        lawyer="Hannah Blake", matter="MTS/DFS/2025/014", paths=["note.txt"]
    )
    packet_core.validate_request(request)  # raises on any fault
    assert request["actor"]["name"] == "Hannah Blake"
    assert request["matter"]["id"] == "MTS/DFS/2025/014"
    assert request["matter"]["client"] is None
    assert request["filters"]["sourceTypes"] == [
        "text",
        "email",
        "docx",
        "user_note",
        "conversation",
    ]
    assert request["filters"]["since"] is None
    assert request["filters"]["until"] is None
    packet_core.parse_time(request["filters"]["asOf"], "asOf", nullable=False)


def test_run_directory_is_a_sibling_of_the_source_root(tmp_path: Path) -> None:
    root = _sources(tmp_path)
    result = start_run.main(
        [
            "--lawyer",
            "Hannah Blake",
            "--matter",
            "MTS/DFS/2025/014",
            "--source-root",
            str(root),
            "note.txt",
        ]
    )
    assert result == 0
    runs = [p for p in tmp_path.iterdir() if p.name.startswith(".timenarratives-run-")]
    assert len(runs) == 1
    assert (runs[0] / "request.json").is_file()
    assert (runs[0] / "artifacts" / "packet.private.json").is_file()
    assert not any(p.name.startswith(".timenarratives-run-") for p in root.iterdir())


def test_summary_is_plain_counts_not_the_packet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _sources(tmp_path)
    (root / "photo.jpg").write_bytes(b"\xff\xd8")
    code = start_run.main(
        [
            "--lawyer",
            "Hannah Blake",
            "--matter",
            "M1",
            "--source-root",
            str(root),
            "note.txt",
            "photo.jpg",
        ]
    )
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "incomplete"
    assert summary["selected"] == 2
    assert summary["readable"] == 1
    assert summary["unreadable"] == [
        {"source": "photo.jpg", "reason": "unsupported_format"}
    ]
    assert "units" not in summary
    assert "escrow" not in json.dumps(summary)


def test_windows_style_selection_paths_are_normalised() -> None:
    request = start_run.build_request(lawyer="H", matter="M", paths=["sub\\a.md"])
    assert request["selections"][0]["path"] == "sub/a.md"


def test_no_sources_is_refused_plainly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _sources(tmp_path)
    code = start_run.main(
        ["--lawyer", "H", "--matter", "M", "--source-root", str(root)]
    )
    assert code == 1
    assert json.loads(capsys.readouterr().out) == {"status": "no_sources_selected"}


def test_inline_note_alone_starts_a_run(tmp_path: Path) -> None:
    root = _sources(tmp_path)
    code = start_run.main(
        ["--lawyer", "H", "--matter", "M", "--source-root", str(root), "--note", "x"]
    )
    assert code == 0


def test_absolute_path_under_the_source_root_is_relativised(tmp_path: Path) -> None:
    root = _sources(tmp_path)
    request = start_run.build_request(
        lawyer="H", matter="M", paths=[str(root / "note.txt")], source_root=root
    )
    assert request["selections"][0]["path"] == "note.txt"


def test_request_file_is_written_new_only_inside_the_run(tmp_path: Path) -> None:
    root = _sources(tmp_path)
    assert (
        start_run.main(
            ["--lawyer", "H", "--matter", "M", "--source-root", str(root), "note.txt"]
        )
        == 0
    )
    run = next(
        p for p in tmp_path.iterdir() if p.name.startswith(".timenarratives-run-")
    )
    request = json.loads((run / "request.json").read_text(encoding="utf-8"))
    packet_core.validate_request(request)
    assert not list(root.glob("request.json"))
