"""Regression tests shared by Diligence and DocReview review-copy builders."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
REVIEW_COPY_SCRIPTS = (
    ROOT / "skills/transactional/diligence/scripts/review_copies.py",
    ROOT / "skills/litigation/docreview/scripts/shared/review_copies.py",
)


def load_module(script: Path):
    module_name = (
        f"review_copies_{hashlib.sha256(str(script).encode()).hexdigest()[:12]}"
    )
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("script", REVIEW_COPY_SCRIPTS, ids=("diligence", "docreview"))
def test_eml_surrogate_headers_render_without_changing_source_hash(
    tmp_path: Path, script: Path
) -> None:
    module = load_module(script)
    room = tmp_path / "room"
    room.mkdir()
    source = room / "instructions.eml"
    source_bytes = (
        b"From: lawyer@example.test\r\n"
        b"To: reviewer@example.test\r\n"
        b"Subject: Review \xff request\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Review the assignment provisions.\r\n"
    )
    source.write_bytes(source_bytes)
    source_digest = hashlib.sha256(source_bytes).hexdigest()
    manifest = {
        "counts": {
            "corrupt": 0,
            "encrypted": 0,
            "files": 1,
            "native": 1,
            "scanned": 0,
        },
        "documents": [
            {
                "bytes": len(source_bytes),
                "ext": "eml",
                "id": "sha256:" + source_digest[:12],
                "pages": None,
                "path": source.name,
                "readability": "native",
                "text_yield": 1.0,
            }
        ],
        "root_label": "room",
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    sidecar_path = tmp_path / "run/review-copies.json"

    result = module.build_review_copies(
        manifest_path,
        room,
        sidecar_path,
        bundle_root="review-copies",
        mode="text",
    )

    assert result.validation.ready
    document = result.sidecar["documents"][0]
    assert document["source_sha256"] == "sha256:" + source_digest
    derivative = document["derivatives"][0]
    rendered = (
        sidecar_path.parent / result.sidecar["bundle_root"] / derivative["path"]
    ).read_text(encoding="utf-8")
    assert "Subject: Review \ufffd request" in rendered
    assert source.read_bytes() == source_bytes
