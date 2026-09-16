"""Delivery invariants and the size gate for newly maintained source boundaries."""

import io
import json
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills/litigation/pressuretest/scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).parent))

import render_brief  # noqa: E402
from result_contract import presentation_faults  # noqa: E402
from test_chat_delivery import chat_fixture  # noqa: E402


def test_new_source_boundaries_stay_within_300_logical_lines():
    for name in ("chat_result.py", "result_contract.py", "render_brief.py"):
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        lines = sum(
            t.type == tokenize.NEWLINE
            for t in tokenize.generate_tokens(io.StringIO(text).readline)
        )
        assert lines <= 300, (name, lines)


def test_batch_status_cannot_be_overridden_by_authored_confirmation():
    data = chat_fixture()
    data["checkpoint"]["status"] = "non_interactive"
    data["brief"]["scope_confirmation"] = "The lawyer confirmed everything."
    text = render_brief.render(data)
    assert "no live lawyer confirmation was obtained" in text
    assert "The lawyer confirmed everything" not in text


def test_malformed_checkpoint_is_a_contract_fault():
    data = chat_fixture()
    data["checkpoint"] = ["bad"]
    assert any(f["code"] == "missing_checkpoint" for f in presentation_faults(data))


def test_malformed_checkpoint_cli_returns_structured_faults():
    for checkpoint in (["bad"], {"status": ["bad"]}):
        data = chat_fixture()
        data["checkpoint"] = checkpoint
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_deliverable.py"), str(path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            assert result.returncode == 1, result.stderr
            assert json.loads(result.stdout)["status"] == "contract_fault"
