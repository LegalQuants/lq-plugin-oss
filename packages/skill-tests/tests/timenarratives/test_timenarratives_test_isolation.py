"""Keep the Python compatibility jobs independent of pnpm installation state."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_python_contract_checks_do_not_load_pluginctl_dependencies() -> None:
    this_file = Path(__file__).resolve()
    paths = [
        path
        for path in sorted(
            (ROOT / "packages/skill-tests/tests/timenarratives").glob("test_*.py")
        )
        if path.resolve() != this_file
    ]
    assert paths
    forbidden = ("node_modules/ajv", "node_modules\\ajv", "pnpm dependencies")
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path
