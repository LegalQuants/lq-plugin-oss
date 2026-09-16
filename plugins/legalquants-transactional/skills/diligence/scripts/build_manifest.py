#!/usr/bin/env python3
"""Public Diligence entrypoint for the shared deterministic manifest builder."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

SHARED_DIR = Path(__file__).with_name("shared")


def main() -> None:
    sys.path.insert(0, str(SHARED_DIR))
    runpy.run_path(str(SHARED_DIR / "build_manifest.py"), run_name="__main__")


if __name__ == "__main__":
    main()
