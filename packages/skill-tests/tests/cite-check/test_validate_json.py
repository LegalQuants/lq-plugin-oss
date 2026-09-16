from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[4]
    / "skills/litigation/cite-check/scripts/common/validate_json.py"
)


def test_validate_json_accepts_object(tmp_path: Path) -> None:
    path = tmp_path / "ok.json"
    path.write_text(json.dumps({"unitId": "1", "status": "ok"}), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0


def test_validate_json_rejects_garbage(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert "invalid json" in completed.stderr


def test_validate_json_rejects_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "not-utf8.json"
    path.write_bytes(b'{"text":"\xff"}')
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert "invalid utf-8" in completed.stderr


def test_validate_json_reports_missing_path(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert "missing:" in completed.stderr


def test_validate_json_reports_unreadable_directory(tmp_path: Path) -> None:
    path = tmp_path / "directory.json"
    path.mkdir()
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert "unreadable:" in completed.stderr


def test_validate_json_usage_when_args_wrong() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "usage:" in completed.stderr
