from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
PROBE_PATH = ROOT / "skills/litigation/cite-check/scripts/probe_environment.py"
SPEC = importlib.util.spec_from_file_location(
    "cite_check_environment_probe", PROBE_PATH
)
assert SPEC and SPEC.loader
probe_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe_module)


def _write_probe_script(
    tmp_path: Path,
    relative_path: str,
    *,
    metadata_relative_path: str | None = None,
    metadata: object | None = None,
) -> Path:
    script_path = tmp_path / relative_path
    script_path.parent.mkdir(parents=True)
    script_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    if metadata_relative_path is not None:
        metadata_path = tmp_path / metadata_relative_path
        metadata_path.parent.mkdir(parents=True)
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return script_path


def _runtime(
    *, available: bool = True, missing_flag: str | None = None
) -> dict[str, Any]:
    flags = dict.fromkeys(probe_module.REQUIRED_CODEX_FLAGS, available)
    if missing_flag is not None:
        flags[missing_flag] = False
    return {
        "available": available,
        "help": {
            "status": "pass" if available else "unavailable",
            "flags": flags,
        },
        "canary": {"status": "not_run", "reason": "passive_probe"},
    }


def _local(
    *,
    filesystem: str = "pass",
    subprocess_status: str = "pass",
    fanout: str = "pass",
) -> dict[str, Any]:
    return {
        "filesystem": {"status": filesystem},
        "subprocess": {"status": subprocess_status},
        "processFanout": {"status": fanout, "width": 2},
    }


def _receipt() -> dict[str, Any]:
    return {
        "schemaVersion": probe_module.SCHEMA_VERSION,
        "local": _local(),
        "runtimes": {"codex": _runtime()},
        "probe": {
            "modelCalled": False,
            "matterContentUsed": False,
        },
        "recommendation": {"path": "packaged_codex_runner"},
    }


def test_local_probe_uses_only_synthetic_children(tmp_path: Path) -> None:
    result = probe_module._probe_local(tmp_path, 2_000)

    assert result["filesystem"]["status"] == "pass"
    assert result["subprocess"]["status"] == "pass"
    assert result["processFanout"] == {"status": "pass", "width": 2}
    assert list(tmp_path.iterdir()) == []


def test_source_checkout_recommends_packaged_runner_when_capabilities_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe_module, "__file__", str(PROBE_PATH))
    codex = _runtime()

    recommendation = probe_module._recommendation(codex, _local())

    assert codex["packagedRunnerEligible"] is True
    assert recommendation["path"] == "packaged_codex_runner"


@pytest.mark.parametrize(
    ("relative_path", "metadata_relative_path", "metadata"),
    [
        (
            "renamed-png-plugin/skills/cite-check/scripts/probe_environment.py",
            "renamed-png-plugin/.codex-plugin/plugin.json",
            {
                "name": "legalquants-litigation",
                "version": "0.1.0",
                "interface": {
                    "logo": "./assets/lq-logo.png",
                    "composerIcon": "./assets/lq-logo.png",
                },
            },
        ),
        (
            "legacy-svg-plugin/skills/cite-check/scripts/probe_environment.py",
            "legacy-svg-plugin/.codex-plugin/plugin.json",
            {
                "name": "codex-for-legal",
                "version": "0.1.0",
                "interface": {"logo": "./assets/lq-logo.svg"},
            },
        ),
        (
            "other-provider/skills/cite-check/scripts/probe_environment.py",
            "other-provider/.claude-plugin/plugin.json",
            {"name": "other-provider-plugin", "version": "0.1.0"},
        ),
    ],
)
def test_plugin_identity_and_location_do_not_gate_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    relative_path: str,
    metadata_relative_path: str,
    metadata: object,
) -> None:
    package_script = _write_probe_script(
        tmp_path,
        relative_path,
        metadata_relative_path=metadata_relative_path,
        metadata=metadata,
    )
    monkeypatch.setattr(probe_module, "__file__", str(package_script))
    codex = _runtime()

    recommendation = probe_module._recommendation(codex, _local())

    assert codex["packagedRunnerEligible"] is True
    assert recommendation["path"] == "packaged_codex_runner"
    assert probe_module.validate_receipt(_receipt()) is None


@pytest.mark.parametrize(
    ("runtime", "local", "expected_reason"),
    [
        (_runtime(available=False), _local(), "codex_cli_not_available"),
        (
            _runtime(missing_flag="outputSchema"),
            _local(),
            "required_codex_cli_flags_not_observed",
        ),
        (
            _runtime(),
            _local(subprocess_status="fail"),
            "local_subprocess_unavailable",
        ),
        (_runtime(), _local(filesystem="fail"), "local_filesystem_unavailable"),
    ],
)
def test_runner_requires_all_capabilities(
    runtime: dict[str, Any],
    local: dict[str, Any],
    expected_reason: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        probe_module,
        "__file__",
        str(
            _write_probe_script(
                tmp_path,
                "arbitrary-plugin/skills/cite-check/scripts/probe_environment.py",
            )
        ),
    )

    recommendation = probe_module._recommendation(runtime, local)

    assert recommendation["path"] == "native_workers_or_sequential"
    assert expected_reason in recommendation["reasonCodes"]


def test_missing_fanout_uses_sequential_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        probe_module,
        "__file__",
        str(
            _write_probe_script(
                tmp_path,
                "arbitrary-plugin/skills/cite-check/scripts/probe_environment.py",
            )
        ),
    )

    recommendation = probe_module._recommendation(_runtime(), _local(fanout="fail"))

    assert recommendation["path"] == "sequential"
    assert "local_process_fanout_unavailable" in recommendation["reasonCodes"]


def test_legacy_package_receipt_fields_are_ignored() -> None:
    receipt = _receipt()
    receipt["package"] = {
        "openaiPackage": False,
        "name": "renamed-plugin",
        "version": "legacy",
    }

    assert probe_module.validate_receipt(receipt) is None


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda receipt: receipt.update({"schemaVersion": "wrong"}),
            "schemaVersion",
        ),
        (
            lambda receipt: receipt["local"]["subprocess"].update({"status": "fail"}),
            "subprocess",
        ),
        (
            lambda receipt: receipt["runtimes"]["codex"]["help"]["flags"].update(
                {"outputSchema": False}
            ),
            "codex exec capabilities",
        ),
        (
            lambda receipt: receipt["probe"].update({"modelCalled": True}),
            "must not call a model",
        ),
        (
            lambda receipt: receipt["probe"].update({"matterContentUsed": True}),
            "must not use matter content",
        ),
        (
            lambda receipt: receipt.update(
                {"recommendation": {"path": "native_workers_or_sequential"}}
            ),
            "does not recommend",
        ),
    ],
)
def test_receipt_validation_rejects_failed_capability(
    mutation: Any,
    message: str,
) -> None:
    receipt = _receipt()
    mutation(receipt)

    reason = probe_module.validate_receipt(receipt)

    assert reason is not None
    assert message in reason


def test_probe_is_passive_and_contains_no_environment_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "synthetic-secret-that-must-not-be-printed"
    monkeypatch.setenv("CODEX_SESSION_ID", secret)
    monkeypatch.setattr(
        probe_module, "_probe_local", lambda *_args, **_kwargs: _local()
    )
    monkeypatch.setattr(
        probe_module, "_inspect_codex", lambda *_args, **_kwargs: _runtime()
    )

    assert probe_module.main(["--run-dir", str(tmp_path), "--json"]) == 0
    stdout = capsys.readouterr().out
    receipt = json.loads(stdout)

    assert secret not in stdout
    assert receipt["schemaVersion"] == "cite-check.environment-capability.v1"
    assert "package" not in receipt
    assert receipt["probe"] == {
        "modelCalled": False,
        "matterContentUsed": False,
    }
    assert receipt["runtimes"]["codex"]["canary"]["status"] == "not_run"
    assert receipt["recommendation"]["path"] == "packaged_codex_runner"


def test_probe_cli_has_no_provider_or_permission_switches() -> None:
    help_text = probe_module._parser().format_help()

    assert "--host-provider" not in help_text
    assert "--authorize" not in help_text
    assert "--run-dir" in help_text


def test_invalid_timeout_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert probe_module.main(["--run-dir", str(tmp_path), "--timeout-ms", "1"]) == 2
    assert "timeout-ms" in capsys.readouterr().err
