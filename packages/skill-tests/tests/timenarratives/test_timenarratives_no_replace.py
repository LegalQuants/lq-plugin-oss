"""Native atomic no-replace primitive regressions."""

from __future__ import annotations

import ctypes
import errno
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))
no_replace = importlib.import_module("no_replace")


def test_linux_no_replace_uses_kernel_exclusive_flag() -> None:
    calls: list[tuple[object, ...]] = []

    class ExistingDestination:
        argtypes: object = None
        restype: object = None

        def __call__(self, *args: object) -> int:
            calls.append(args)
            ctypes.set_errno(errno.EEXIST)
            return -1

    with pytest.raises(FileExistsError):
        no_replace._linux_rename_no_replace(
            Path("/private/stage"),
            Path("/private/target"),
            ExistingDestination(),
        )

    assert len(calls) == 1
    assert calls[0][0] == calls[0][2] == -100
    assert isinstance(calls[0][1], bytes) and isinstance(calls[0][3], bytes)
    assert calls[0][4] == 1


def test_macos_no_replace_uses_exclusive_flag() -> None:
    calls: list[tuple[object, ...]] = []

    class ExistingDestination:
        argtypes: object = None
        restype: object = None

        def __call__(self, *args: object) -> int:
            calls.append(args)
            ctypes.set_errno(errno.EEXIST)
            return -1

    with pytest.raises(FileExistsError):
        no_replace._macos_rename_no_replace(
            Path("/private/stage"),
            Path("/private/target"),
            ExistingDestination(),
        )

    assert len(calls) == 1
    assert isinstance(calls[0][0], bytes) and isinstance(calls[0][1], bytes)
    assert calls[0][2] == 4


def test_no_replace_fails_closed_on_unsupported_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(no_replace.sys, "platform", "unsupported")

    with pytest.raises(no_replace.NoReplaceUnavailableError):
        no_replace.rename_no_replace(Path("stage"), Path("target"))


def test_windows_no_replace_refuses_an_existing_empty_directory(
    tmp_path: Path,
) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows primitive check")
    source = tmp_path / "stage"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()

    with pytest.raises(FileExistsError):
        no_replace.rename_no_replace(source, target)

    assert source.is_dir() and target.is_dir()
