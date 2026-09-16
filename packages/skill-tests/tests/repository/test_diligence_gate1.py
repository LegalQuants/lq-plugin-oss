"""Integration regressions for the shipped Diligence Gate 1 inputs."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills/transactional/diligence/scripts"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_script(script: str, *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *(str(arg) for arg in args)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_gate1_carries_framework_identity_and_verified_metadata(tmp_path: Path) -> None:
    room = tmp_path / "room"
    room.mkdir()
    source = room / "agreement.txt"
    source.write_text(
        "Example Services Agreement effective January 2, 2024.\n",
        encoding="utf-8",
    )
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    doc_id = "sha256:" + source_digest[:12]
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
                "bytes": source.stat().st_size,
                "ext": "txt",
                "id": doc_id,
                "pages": None,
                "path": source.name,
                "readability": "native",
                "review_role": "substantive",
                "text_yield": 1.0,
            }
        ],
        "root_label": "room",
    }
    framework = {
        "approved": False,
        "framework_version": 7,
        "lenses": [
            {
                "items": [
                    {
                        "answer_shape": {
                            "characterization_max_words": 30,
                            "statuses": ["present", "absent", "unresolved"],
                            "template": "State the agreement date.",
                        },
                        "disposition": "report",
                        "evidence": {
                            "required": "verbatim quote plus section reference",
                            "unresolved_when": (
                                "The supplied text does not state a date."
                            ),
                        },
                        "exclusions": [],
                        "hit_rule": "Language stating an agreement or effective date.",
                        "issue_id": "agreement-date",
                        "overlap_owner": None,
                        "question": "What date does the agreement state?",
                    }
                ],
                "lens_id": "identity",
                "name": "Agreement identity",
            }
        ],
        "source_inputs": [{"kind": "checklist", "label": "instructions.txt"}],
    }
    paths = {
        "manifest": tmp_path / "manifest.json",
        "framework": tmp_path / "framework.json",
        "readback": tmp_path / "framework-readback.json",
        "families": tmp_path / "families.json",
        "gaps": tmp_path / "gaps.json",
        "sample": tmp_path / "sample.json",
        "metadata": tmp_path / "metadata",
        "review_copies": tmp_path / "review-copies.json",
        "output": tmp_path / "review-setup.html",
    }
    write_json(paths["manifest"], manifest)
    write_json(paths["framework"], framework)
    write_json(paths["families"], {"families": [], "orphans": [doc_id]})
    write_json(paths["gaps"], {"entries": []})
    write_json(
        paths["sample"],
        {
            "framework_version": 7,
            "proposed_units": [
                {
                    "doc_id": doc_id,
                    "label": "Example Services Agreement",
                    "reason": "The only substantive agreement is reviewed in full.",
                }
            ],
            "sample_size": 1,
            "selection_basis": "The only substantive agreement is in scope.",
        },
    )
    write_json(
        paths["metadata"] / f"{doc_id}.json",
        {
            "dated": "2024-01-02",
            "doc_type": "services agreement",
            "id": doc_id,
            "parties": ["Example Customer", "Example Provider"],
            "references": [],
            "status": "complete",
            "title": "Example Services Agreement",
        },
    )

    readback = run_script(
        "render_readback.py",
        "--framework",
        paths["framework"],
        "--out",
        paths["readback"],
    )
    assert readback.returncode == 0, readback.stderr or readback.stdout
    readback_data = json.loads(paths["readback"].read_text(encoding="utf-8"))
    assert readback_data["framework_version"] == 7
    assert readback_data["approved"] is False

    copies = run_script(
        "review_copies.py",
        "build",
        "--manifest",
        paths["manifest"],
        "--source-root",
        room,
        "--sidecar",
        paths["review_copies"],
        "--bundle-root",
        "review-copies",
        "--mode",
        "text",
    )
    assert copies.returncode == 0, copies.stderr or copies.stdout

    rendered = run_script(
        "render_gate1.py",
        "--manifest",
        paths["manifest"],
        "--metadata",
        paths["metadata"],
        "--families",
        paths["families"],
        "--gaps",
        paths["gaps"],
        "--readback",
        paths["readback"],
        "--sample",
        paths["sample"],
        "--source-prefix",
        "sources",
        "--review-copies",
        paths["review_copies"],
        "--document-root",
        room,
        "--out",
        paths["output"],
    )
    assert rendered.returncode == 0, rendered.stderr or rendered.stdout
    page = paths["output"].read_text(encoding="utf-8")
    assert "Example Services Agreement" in page
    assert "2024-01-02" in page
    assert "framework version <code>7</code>" in page
    assert "framework version <code>not recorded</code>" not in page
    assert "Date not stated in inventory" not in page
