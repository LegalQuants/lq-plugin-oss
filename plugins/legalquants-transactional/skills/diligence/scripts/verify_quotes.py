#!/usr/bin/env python3
"""Public Diligence entrypoint for shared quote verification."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SHARED_DIR = Path(__file__).with_name("shared")
sys.path.insert(0, str(SHARED_DIR))
_SPEC = importlib.util.spec_from_file_location(
    "diligence_shared_verify_quotes", SHARED_DIR / "verify_quotes.py"
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load shared quote verifier")
_SHARED = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SHARED)

normalize = _SHARED.normalize_quote
extract_text = _SHARED.extract_document_text
main = _SHARED.main


if __name__ == "__main__":
    main()
