from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
RUNNER_PATH = ROOT / "skills/litigation/cite-check/scripts/cite_check.py"
SCHEMA_PATH = (
    ROOT / "skills/litigation/cite-check/schemas/cite-check-unit-result.schema.json"
)
SPEC = importlib.util.spec_from_file_location(
    "cite_check_runtime_regressions", RUNNER_PATH
)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)
runtime_module: Any = sys.modules["common.runtime"]


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _task(tmp_path: Path) -> Any:
    return runner.WorkTask(
        "runtime-test-001",
        tmp_path,
        {
            "unitId": "P0001",
            "kind": "paragraph",
            "lineStart": 1,
            "lineEnd": 1,
            "footnoteAnchorUnitId": None,
        },
        [],
        "gpt-5.6-luna",
        "xhigh",
        _schema(),
        "synthetic prompt",
    )


def _result() -> dict[str, Any]:
    return {
        "unitId": "P0001",
        "disposition": "no_citations_found",
        "citations": [],
    }


def test_dead_runtime_selector_is_not_on_the_runtime_module() -> None:
    assert not hasattr(runtime_module, "_select_runtime")
    assert not hasattr(runtime_module, "_runtime_capabilities")
    assert not hasattr(runtime_module.WorkerResponse, "provenance")
    assert not hasattr(runtime_module.WorkTask, "full_document_ref")
    assert not hasattr(runtime_module.WorkTask, "requested_checks")
    assert not hasattr(runtime_module.WorkTask, "prompt_ref")


def test_output_schema_relaxes_only_model_unsupported_keywords() -> None:
    compatible = runtime_module._codex_output_schema(_schema())

    assert "allOf" not in compatible
    assert "anyOf" not in compatible
    assert compatible["additionalProperties"] is False
    assert compatible["required"] == ["unitId", "disposition", "citations"]


def test_cli_extracts_result_from_output_file_and_usage() -> None:
    path = Path("/tmp/cite-check-runtime-result.json")
    path.write_text(json.dumps(_result()), encoding="utf-8")
    try:
        assert runtime_module._extract_cli_json(path, "") == _result()
    finally:
        path.unlink(missing_ok=True)
    metrics = runtime_module._cli_metrics(
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 10,
                    "cached_input_tokens": 2,
                    "cache_write_input_tokens": 1,
                },
            }
        )
    )
    assert metrics == {
        "input_tokens": 10,
        "cached_input_tokens": 2,
        "cache_write_input_tokens": 1,
    }


def test_cli_runtime_reads_json_result_and_requests_read_only_sandbox(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed: list[tuple[list[str], dict[str, Any]]] = []
    inputs: list[bytes | None] = []

    class Process:
        returncode = 0

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            inputs.append(input)
            return (
                json.dumps(
                    {
                        "type": "turn.completed",
                        "actual_model": "gpt-5.6-luna",
                        "actual_effort": "xhigh",
                        "usage": {"input_tokens": 3},
                    }
                ).encode(),
                b"",
            )

    async def create(*command: str, **kwargs: Any) -> Process:
        observed.append((list(command), kwargs))
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text(json.dumps(_result()), encoding="utf-8")
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    runtime = runner.CliRuntime("codex", "gpt-5.6-luna", "xhigh", SCHEMA_PATH, tmp_path)
    response = asyncio.run(runtime.run(_task(tmp_path)))

    assert response.failure is None
    assert response.payload == _result()
    assert response.model == "gpt-5.6-luna"
    assert response.input_tokens == 3
    command, kwargs = observed[0]
    assert "--sandbox" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[-1] == "-"
    assert set(kwargs) == {"cwd", "stdin", "stdout", "stderr"}
    assert inputs == [b"synthetic prompt"]


def test_cli_runtime_does_not_infer_requested_model_when_events_omit_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Process:
        returncode = 0

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            del input
            return b'{"type":"turn.completed","usage":{"input_tokens":3}}', b""

    async def create(*command: str, **kwargs: Any) -> Process:
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text(json.dumps(_result()), encoding="utf-8")
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    response = asyncio.run(
        runner.CliRuntime(
            "codex", "requested-model", "xhigh", SCHEMA_PATH, tmp_path
        ).run(_task(tmp_path))
    )

    assert response.failure is None
    assert response.model == "unknown"
    assert response.effort == "unknown"


def test_cli_schema_request_failure_is_not_authentication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Process:
        returncode = 1

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            del input
            return b'{"type":"error","message":"invalid_json_schema"}', b""

    async def create(*command: str, **kwargs: Any) -> Process:
        del command, kwargs
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    response = asyncio.run(
        runner.CliRuntime("codex", "gpt-5.6-luna", "xhigh", SCHEMA_PATH, tmp_path).run(
            _task(tmp_path)
        )
    )
    assert response.failure is not None
    assert response.failure.code == "schema_request"


def test_cli_timeout_kills_and_reaps_child_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class HangingProcess:
        def __init__(self) -> None:
            self.returncode: int | None = None
            self.killed = False

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            del input
            if self.killed:
                return b"", b""
            await asyncio.sleep(10)
            return b"", b""

    process = HangingProcess()

    async def create(*command: str, **kwargs: Any) -> HangingProcess:
        del command, kwargs
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    runtime = runner.CliRuntime(
        "codex", "gpt-5.6-luna", "xhigh", SCHEMA_PATH, tmp_path, timeout=0.01
    )
    response = asyncio.run(runtime.run(_task(tmp_path)))

    assert response.failure is not None
    assert response.failure.code == "timeout"
    assert process.killed is True


def test_runtime_selection_is_cli_only_and_auto_does_not_use_sdk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runner, "_find_cli", lambda executable: "/usr/bin/codex")
    runtime, capability, exit_code = runner._select_runtime(
        "auto", "gpt-5.6-luna", "xhigh", tmp_path, SCHEMA_PATH, None
    )

    assert exit_code == 0
    assert runtime is not None
    assert runtime.surface == "codex_exec"
    assert capability["selectedRuntime"] == "codex_exec"
    assert "sdk" not in capability


def test_cli_executable_override_must_match_resolved_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    canonical = tmp_path / "codex"
    canonical.write_text("#!/bin/sh\n", encoding="utf-8")
    canonical.chmod(0o755)
    wrapper = tmp_path / "codex-wrapper"
    wrapper.write_text('#!/bin/sh\nexec codex "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    monkeypatch.setattr(runtime_module.shutil, "which", lambda _name: str(canonical))

    assert runtime_module._find_cli() == str(canonical.resolve())
    assert runtime_module._find_cli(str(wrapper)) is None


@pytest.mark.parametrize(
    "error",
    [PermissionError("permission denied"), RuntimeError("EACCES: permission denied")],
)
def test_permission_denials_are_runtime_startup_errors(error: BaseException) -> None:
    assert runner._classify_exception(error).code == "runtime_startup"


@pytest.mark.parametrize(
    "message",
    [
        "failed to initialize in-process app-server client: Operation not permitted",
        (
            "failed to initialize sqlite state runtime: "
            "attempt to write a readonly database"
        ),
    ],
)
def test_outer_sandbox_denials_request_host_approval(message: str) -> None:
    failure = runner._classify_exception(RuntimeError(message))

    assert failure.code == "host_approval_required"
    assert failure.retryable is False


def test_authentication_errors_remain_authentication_errors() -> None:
    assert runner._classify_exception(RuntimeError("401 unauthorized")).code == (
        "authentication"
    )
