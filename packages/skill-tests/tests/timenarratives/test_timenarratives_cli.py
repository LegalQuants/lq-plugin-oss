"""Published packet CLI contract and redacted failure codes."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
sys.path.insert(0, str(SCRIPTS))
build_packet = importlib.import_module("build_packet")
packet_io = importlib.import_module("packet_io")
safe_output = importlib.import_module("safe_output")


def _request() -> dict:
    return {
        "schemaVersion": "timenarratives.request.v1",
        "runId": "Cli_Run",
        "actor": {"id": "cli-actor", "name": "Private Actor", "aliases": []},
        "matter": {
            "id": "PRIVATE-MATTER",
            "client": "Private Client",
            "aliases": [],
        },
        "selections": [{"kind": "user_note", "text": "Private rough note"}],
        "filters": {
            "sourceTypes": ["user_note"],
            "since": None,
            "until": None,
            "asOf": "2026-08-21T12:00:00+01:00",
        },
    }


def _invoke(request_path: Path, source_root: Path, output: Path) -> int:
    return build_packet.main(
        [
            "--source-root",
            str(source_root),
            "--request",
            str(request_path),
            "--out",
            str(output),
        ]
    )


def _refusal(code: str) -> str:
    return f"packet build failed: operational_failure:{code}\n"


def _source_root(tmp_path: Path) -> Path:
    root = tmp_path / "selected"
    root.mkdir()
    return root


@pytest.mark.parametrize(
    "constant", ["NaN", "Infinity", "-Infinity", "1e9999", "-1e9999"]
)
def test_request_reader_rejects_non_json_numeric_constants(
    tmp_path: Path, constant: str
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(f'{{"value":{constant}}}', encoding="utf-8")

    with pytest.raises(packet_io.RequestFormatError):
        packet_io._read_request(request_path)


def test_cli_accepts_published_out_as_new_atomic_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request()), encoding="utf-8")
    output = tmp_path / "packet.json"

    code = _invoke(request_path, _source_root(tmp_path), output)

    captured = capsys.readouterr()
    packet = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert packet["runId"] == "Cli_Run"
    assert json.loads(captured.out) == {
        "status": "requires_confirmation",
        "runId": "Cli_Run",
    }
    assert captured.err == ""


@pytest.mark.parametrize(
    ("since", "until"),
    [
        ("2026-08-21T09:00:00+01:00", None),
        (None, "2026-08-21T11:00:00+01:00"),
        ("2026-08-21T09:00:00+01:00", "2026-08-21T11:00:00+01:00"),
    ],
)
def test_cli_refuses_user_note_with_time_filter_without_writing_packet(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    since: str | None,
    until: str | None,
) -> None:
    value = _request()
    value["filters"].update(since=since, until=until)
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "packet.json"

    code = _invoke(request_path, _source_root(tmp_path), output)

    captured = capsys.readouterr()
    assert code == 1
    assert not output.exists()
    assert captured.out == ""
    assert captured.err == "packet build failed: invalid_request\n"


def test_cli_refuses_preexisting_output_without_changing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request()), encoding="utf-8")
    output = tmp_path / "packet.json"
    output.write_text("old artifact", encoding="utf-8")

    code = _invoke(request_path, _source_root(tmp_path), output)

    captured = capsys.readouterr()
    assert code == 2
    assert output.read_text(encoding="utf-8") == "old artifact"
    assert captured.err == _refusal("output_already_exists")


@pytest.mark.parametrize(
    "fault", ["syntax", "duplicate", "nan", "infinity", "structure"]
)
def test_cli_contract_fault_is_exit_1_without_artifact_or_sensitive_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fault: str,
) -> None:
    request_path = tmp_path / "request.json"
    value = _request()
    if fault == "syntax":
        request_path.write_text("{PRIVATE-BROKEN", encoding="utf-8")
    elif fault == "duplicate":
        raw = '{"runId":"PRIVATE-DUPLICATE",' + json.dumps(value)[1:]
        request_path.write_text(raw, encoding="utf-8")
    elif fault in {"nan", "infinity"}:
        value["filters"]["since"] = float(fault)
        request_path.write_text(json.dumps(value), encoding="utf-8")
    else:
        value["filters"]["sourceTypes"] = ["not-a-source-type"]
        request_path.write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "packet.json"

    code = _invoke(request_path, _source_root(tmp_path), output)

    captured = capsys.readouterr()
    assert code == 1
    assert not output.exists()
    assert captured.out == ""
    assert captured.err == "packet build failed: invalid_request\n"
    assert "PRIVATE" not in captured.err


def test_cli_operational_fault_is_exit_2_and_redacted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = tmp_path / "PRIVATE-missing-request.json"
    output = tmp_path / "packet.json"

    code = _invoke(request_path, _source_root(tmp_path), output)

    captured = capsys.readouterr()
    assert code == 2
    assert not output.exists()
    assert captured.out == ""
    assert captured.err == "packet build failed: operational_failure\n"
    assert "PRIVATE" not in captured.err


def test_cli_missing_source_root_is_invocation_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request()), encoding="utf-8")
    output = tmp_path / "packet.json"

    code = _invoke(request_path, tmp_path / "missing-root", output)

    captured = capsys.readouterr()
    assert code == 2
    assert not output.exists()
    assert captured.out == ""
    assert captured.err == "packet build failed: operational_failure\n"


def test_cli_missing_selected_file_writes_incomplete_packet_with_exit_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    value = _request()
    value["selections"] = [{"kind": "file", "path": "missing.txt"}]
    value["filters"]["sourceTypes"] = ["text"]
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "packet.json"

    code = _invoke(request_path, _source_root(tmp_path), output)

    captured = capsys.readouterr()
    packet = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert packet["status"] == "incomplete"
    assert packet["roots"][0]["disposition"] == "unreadable"
    assert json.loads(captured.out)["status"] == "incomplete"
    assert captured.err == ""


def test_cli_write_failure_is_exit_2_without_touching_other_artifacts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request()), encoding="utf-8")
    existing = tmp_path / "existing.json"
    existing.write_text("preserve", encoding="utf-8")
    output = tmp_path / "missing-parent" / "packet.json"

    code = _invoke(request_path, _source_root(tmp_path), output)

    captured = capsys.readouterr()
    assert code == 2
    assert not output.exists()
    assert existing.read_text(encoding="utf-8") == "preserve"
    assert captured.err == _refusal("output_parent_unavailable")


def test_cli_refuses_output_inside_selected_source_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request()), encoding="utf-8")
    source_root = _source_root(tmp_path)
    output = source_root / "packet.json"

    assert _invoke(request_path, source_root, output) == 2
    assert not output.exists()
    assert capsys.readouterr().err == _refusal("output_inside_input_root")


def test_cli_refuses_hardlink_alias_to_request_without_changing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request()), encoding="utf-8")
    before = request_path.read_bytes()
    output = tmp_path / "packet.json"
    try:
        os.link(request_path, output)
    except OSError:
        pytest.skip("hard links are unavailable on this filesystem")

    assert _invoke(request_path, _source_root(tmp_path), output) == 2
    assert output.read_bytes() == request_path.read_bytes() == before
    assert capsys.readouterr().err == _refusal("output_already_exists")


def test_cli_unexpected_compile_fault_is_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request()), encoding="utf-8")

    def fail_compile(request: dict, source_root: Path) -> dict:
        raise RuntimeError("PRIVATE workspace path")

    monkeypatch.setattr(build_packet, "compile_packet", fail_compile)
    output = tmp_path / "packet.json"
    assert _invoke(request_path, _source_root(tmp_path), output) == 2
    captured = capsys.readouterr()
    assert captured.err == "packet build failed: operational_failure\n"
    assert "PRIVATE" not in captured.out + captured.err
    assert not output.exists()


def test_cli_publication_interrupt_is_redacted_and_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request()), encoding="utf-8")

    def interrupt(source: Path, destination: Path) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(safe_output.os, "link", interrupt)
    output = tmp_path / "packet.json"
    assert _invoke(request_path, _source_root(tmp_path), output) == 2
    assert capsys.readouterr().err == "packet build failed: operational_failure\n"
    assert not output.exists()
    assert not list(tmp_path.glob(".packet.json.stage-*"))
