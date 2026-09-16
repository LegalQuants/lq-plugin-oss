#!/usr/bin/env python3
"""Build provider upload ZIPs from the validated pluginctl output."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN = {"AGENTS.md", "CLAUDE.md", "PRD.md", "__pycache__", "evals", "tests"}


def build_archive(name: str, provider: str, output: Path) -> Path:
    """Archive runtime files with stable timestamps and executable permissions."""
    source = ROOT / "dist" / provider / name
    manifest = ".codex-plugin" if provider == "openai" else ".claude-plugin"
    if not (source / manifest / "plugin.json").is_file():
        raise ValueError(f"Missing {provider} package for {name}; run pnpm plugin-pack")
    allowed = {manifest, "skills", "assets", "hooks", "LICENSE"}
    files = sorted(path for path in source.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(source)
        if (
            relative.parts[0] not in allowed
            or FORBIDDEN.intersection(relative.parts)
            or path.suffix in {".pyc", ".pyo"}
        ):
            raise ValueError(f"Unexpected non-runtime file: {relative}")
    archive = output / f"{name}-{provider}.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
        for path in files:
            info = ZipInfo(path.relative_to(source).as_posix(), (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
            info.compress_type = ZIP_DEFLATED
            bundle.writestr(info, path.read_bytes())
    with archive.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8"
    )
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write six provider ZIPs and SHA256 files under dist/releases.",
        epilog=(
            "Run pnpm release:archives to build the plugins first. "
            "Requires uv; no zip executable is needed."
        ),
    )
    parser.parse_args()
    marketplace = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
    output = ROOT / "dist/releases"
    output.mkdir(parents=True, exist_ok=True)
    for plugin in marketplace["plugins"]:
        for provider in ("claude-code", "openai"):
            print(build_archive(plugin["name"], provider, output).name)


if __name__ == "__main__":
    main()
