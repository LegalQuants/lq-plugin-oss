"""Validator token emission and stable redacted CLI input faults."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_timenarratives_contracts import make_map, make_packet

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
VALIDATOR = SCRIPTS / "validate_map.py"
RENDERER = SCRIPTS / "render_deliverable.py"
sys.path.insert(0, str(SCRIPTS))
canonical_sha256 = importlib.import_module("canonical_json").canonical_sha256


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    packet = make_packet()
    mapping = make_map(packet)
    packet_path = tmp_path / "packet.json"
    map_path = tmp_path / "map.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    map_path.write_text(json.dumps(mapping), encoding="utf-8")
    return packet_path, map_path


def test_validator_emits_exact_current_confirmation_token_only_on_pass(
    tmp_path: Path,
) -> None:
    packet_path, map_path = _write_inputs(tmp_path)
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    expected_digest = canonical_sha256(mapping)
    output = tmp_path / "validation.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--packet",
            str(packet_path),
            "--map",
            str(map_path),
            "--out",
            str(output),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    stdout = json.loads(proc.stdout)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert stdout["mapDigest"] == expected_digest
    assert stdout["confirmationToken"] == f"TN-{expected_digest[:16]}"
    assert json.loads(output.read_text(encoding="utf-8")) == stdout


def test_validator_fault_has_no_confirmation_token_or_output_artifact(
    tmp_path: Path,
) -> None:
    packet_path, map_path = _write_inputs(tmp_path)
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    mapping["events"][0]["performedByActorId"] = "OTHER_ACTOR"
    map_path.write_text(json.dumps(mapping), encoding="utf-8")
    output = tmp_path / "validation.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--packet",
            str(packet_path),
            "--map",
            str(map_path),
            "--out",
            str(output),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    stdout = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert "confirmationToken" not in stdout
    assert not output.exists()


def _bad_packet(tmp_path: Path, fault: str) -> tuple[Path, str]:
    path = tmp_path / "PRIVATE-MATTER-packet.json"
    expected = {
        "missing": "input_unreadable",
        "syntax": "input_invalid_json",
        "nan": "input_invalid_json",
        "infinity": "input_invalid_json",
        "overflow": "input_invalid_json",
        "negative_overflow": "input_invalid_json",
        "duplicate": "input_duplicate_key",
        "nonobject": "input_not_object",
    }[fault]
    if fault == "syntax":
        path.write_text('{"client":"PRIVATE CLIENT",', encoding="utf-8")
    elif fault == "nan":
        path.write_text('{"client":NaN}', encoding="utf-8")
    elif fault == "infinity":
        path.write_text('{"client":Infinity}', encoding="utf-8")
    elif fault == "overflow":
        path.write_text('{"client":1e9999}', encoding="utf-8")
    elif fault == "negative_overflow":
        path.write_text('{"client":-1e9999}', encoding="utf-8")
    elif fault == "duplicate":
        path.write_text(
            '{"PRIVATE_ARBITRARY_KEY":1,"PRIVATE_ARBITRARY_KEY":2}',
            encoding="utf-8",
        )
    elif fault == "nonobject":
        path.write_text('"PRIVATE CLIENT MATTER"', encoding="utf-8")
    return path, expected


@pytest.mark.parametrize("tool", ["validate", "render"])
@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "syntax",
        "nan",
        "infinity",
        "overflow",
        "negative_overflow",
        "duplicate",
        "nonobject",
    ],
)
def test_runtime_cli_input_faults_are_categorical_and_redacted(
    tmp_path: Path, tool: str, fault: str
) -> None:
    bad_packet, expected = _bad_packet(tmp_path, fault)
    _, map_path = _write_inputs(tmp_path)
    command = [
        sys.executable,
        str(VALIDATOR if tool == "validate" else RENDERER),
        "--packet",
        str(bad_packet),
        "--map",
        str(map_path),
    ]
    output_dir = tmp_path / "PRIVATE-output"
    outputs = [output_dir / "artifacts" / "deliverable.json"]
    if tool == "render":
        request = tmp_path / "request.json"
        request.write_text("{}", encoding="utf-8")
        command.extend(
            [
                "--request",
                str(request),
                "--source-root",
                str(tmp_path),
                "--confirmation",
                str(tmp_path / "PRIVATE-confirmation.json"),
                "--out-dir",
                str(output_dir),
            ]
        )
    proc = subprocess.run(command, capture_output=True, check=False, text=True)
    assert proc.returncode == 2
    assert json.loads(proc.stdout) == {
        "status": "operational_fault",
        "error": expected,
    }
    assert "PRIVATE" not in proc.stdout + proc.stderr
    assert not any(path.exists() for path in outputs)
