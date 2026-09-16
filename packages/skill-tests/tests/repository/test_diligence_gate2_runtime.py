"""Regression tests for Diligence's Gate 2 factual-review runtime."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills/transactional/diligence/scripts"
SHARED = SCRIPTS / "shared"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_script(path: Path, *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(path), *(str(arg) for arg in args)],
        check=False,
        capture_output=True,
        text=True,
    )


def source_document(room: Path, name: str, text: str, role: str) -> dict[str, object]:
    source = room / name
    source.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return {
        "bytes": source.stat().st_size,
        "ext": "txt",
        "id": "sha256:" + digest[:12],
        "pages": None,
        "path": name,
        "readability": "native",
        "review_role": role,
        "text_yield": 1.0,
    }


def write_docx(path: Path, paragraphs: list[str]) -> None:
    body = "".join(
        "<w:p><w:r><w:t>" + text + "</w:t></w:r></w:p>" for text in paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document_xml)


def factual_item(*, materiality: bool = False) -> dict[str, object]:
    item: dict[str, object] = {
        "answer_shape": {
            "characterization_max_words": 30,
            "statuses": ["present", "absent", "unresolved"],
            "template": "State whether consent is required.",
        },
        "disposition": "report",
        "evidence": {
            "required": "verbatim quote plus section reference",
            "unresolved_when": "The supplied text does not resolve consent.",
        },
        "exclusions": [],
        "hit_rule": "Language requiring consent before assignment.",
        "issue_id": "assignment-consent",
        "overlap_owner": None,
        "question": "Is consent required before assignment?",
    }
    if materiality:
        item["materiality"] = {"bands": [], "default": "medium"}
    return item


def test_compact_worker_accepts_unranked_present_finding(tmp_path: Path) -> None:
    room = tmp_path / "room"
    room.mkdir()
    document = source_document(
        room,
        "agreement.txt",
        "Section 7. Consent is required before assignment.\n",
        "substantive",
    )
    assignment = {
        "documents": [document],
        "framework_version": 1,
        "issue_items": [factual_item()],
        "job_id": "1111111111111111",
        "lens_id": "assignment",
        "member_ids": [document["id"]],
        "requires_current_position": False,
        "review_plan_id": "2222222222222222",
        "unit_id": document["id"],
    }
    raw = {
        "contract": "finding-worker/2",
        "determinations": [
            {
                "characterization": "Consent is required before assignment.",
                "current_position": False,
                "doc": 1,
                "issue_id": "assignment-consent",
                "n": 1,
                "page": None,
                "quote": "Consent is required before assignment.",
                "receipt_mode": "text",
                "section": "7",
                "status": "present",
            }
        ],
        "job_id": assignment["job_id"],
        "privilege_candidates": [],
        "review_plan_id": assignment["review_plan_id"],
    }
    assignment_path = tmp_path / "assignment.json"
    raw_path = tmp_path / "raw.json"
    output = tmp_path / "finding.json"
    receipt = tmp_path / "receipt.json"
    write_json(assignment_path, assignment)
    write_json(raw_path, raw)

    result = run_script(
        SHARED / "admit_finding_result.py",
        "--assignment",
        assignment_path,
        "--raw",
        raw_path,
        "--room-root",
        room,
        "--out",
        output,
        "--receipt",
        receipt,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    finding = json.loads(output.read_text(encoding="utf-8"))["findings"][0]
    assert finding["status"] == "present"
    assert finding["band"] is None
    assert finding["band_basis"] is None


def test_review_plan_excludes_runner_control_from_jobs_and_parking(
    tmp_path: Path,
) -> None:
    room = tmp_path / "room"
    room.mkdir()
    agreement = source_document(
        room,
        "agreement.txt",
        "Section 7. Consent is required before assignment.\n",
        "substantive",
    )
    control = source_document(
        room,
        "instructions.txt",
        "Review every agreement for assignment consent.\n",
        "runner-control",
    )
    manifest = {
        "counts": {"corrupt": 0, "encrypted": 0, "files": 2, "native": 2, "scanned": 0},
        "documents": [agreement, control],
    }
    framework = {
        "approved": True,
        "framework_version": 1,
        "lenses": [
            {"items": [factual_item()], "lens_id": "assignment", "name": "Assignment"}
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    framework_path = tmp_path / "framework.json"
    output = tmp_path / "review-plan.json"
    write_json(manifest_path, manifest)
    write_json(framework_path, framework)

    result = run_script(
        SHARED / "build_review_plan.py",
        "--manifest",
        manifest_path,
        "--framework",
        framework_path,
        "--room-root",
        room,
        "--tier",
        "full",
        "--out",
        output,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    plan = json.loads(output.read_text(encoding="utf-8"))
    assert len(plan["jobs"]) == 1
    assert plan["jobs"][0]["member_ids"] == [agreement["id"]]
    assert plan["parked_units"] == []
    assert str(control["id"]) not in json.dumps(plan, sort_keys=True)


def test_gate2_page_explains_verification_and_supports_search(tmp_path: Path) -> None:
    room = tmp_path / "room"
    room.mkdir()
    document = source_document(
        room,
        "agreement.txt",
        "Section 7. Consent is required before assignment.\n",
        "substantive",
    )
    manifest = {
        "counts": {"corrupt": 0, "encrypted": 0, "files": 1, "native": 1, "scanned": 0},
        "documents": [document],
        "root_label": "room",
    }
    framework = {
        "approved": True,
        "framework_version": 1,
        "lenses": [
            {"items": [factual_item()], "lens_id": "assignment", "name": "Assignment"}
        ],
    }
    findings = {
        "findings": [
            {
                "band": None,
                "band_basis": None,
                "characterization": "Consent is required before assignment.",
                "current_position": True,
                "doc_id": document["id"],
                "finding_id": f"assignment-consent/{document['id']}",
                "issue_id": "assignment-consent",
                "lens_id": "assignment",
                "page": None,
                "quote": "Consent is required before assignment.",
                "quote_verification": {
                    "checker": "human-image-lane",
                    "reason": "image transcription is not script-verifiable",
                    "status": "human-required",
                },
                "receipt_mode": "text",
                "section": "7",
                "status": "present",
                "unit_id": document["id"],
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    framework_path = tmp_path / "framework.json"
    findings_path = tmp_path / "findings.json"
    sidecar = tmp_path / "review-copies.json"
    output = tmp_path / "review-test-results.html"
    write_json(manifest_path, manifest)
    write_json(framework_path, framework)
    write_json(findings_path, findings)

    copies = run_script(
        SCRIPTS / "review_copies.py",
        "build",
        "--manifest",
        manifest_path,
        "--source-root",
        room,
        "--sidecar",
        sidecar,
        "--bundle-root",
        "review-copies",
        "--mode",
        "text",
    )
    assert copies.returncode == 0, copies.stderr or copies.stdout
    rendered = run_script(
        SCRIPTS / "render_sample.py",
        "--framework",
        framework_path,
        "--findings",
        findings_path,
        "--manifest",
        manifest_path,
        "--source-prefix",
        "sources",
        "--review-copies",
        sidecar,
        "--document-root",
        room,
        "--out",
        output,
    )
    assert rendered.returncode == 0, rendered.stderr or rendered.stdout
    page = output.read_text(encoding="utf-8")
    assert 'id="result-search"' in page
    assert "Quote needs human checking" in page
    assert "Independent check pending" in page
    assert '<span class="badge current-position">current position</span>' in page
    assert '<span class="badge band-medium">current position</span>' not in page


def test_public_diligence_entrypoints_extract_and_verify_docx(tmp_path: Path) -> None:
    room = tmp_path / "room"
    room.mkdir()
    source = room / "services-agreement.docx"
    write_docx(
        source,
        [
            "MASTER SERVICES AGREEMENT",
            "This Agreement is effective January 2, 2024.",
            "Section 7. Consent is required before assignment.",
        ],
    )
    manifest_path = tmp_path / "manifest.json"
    gaps_path = tmp_path / "gaps.json"
    built = run_script(
        SCRIPTS / "build_manifest.py",
        "--root",
        room,
        "--out",
        manifest_path,
        "--gaps",
        gaps_path,
        "--extractor",
        "stdlib",
    )
    assert built.returncode == 0, built.stderr or built.stdout
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    document = manifest["documents"][0]
    assert document["readability"] == "native"
    assert document["text_yield"] == 1.0

    metadata_dir = tmp_path / "metadata-run"
    prepared = run_script(
        SCRIPTS / "extract_metadata_prep.py",
        "--manifest",
        manifest_path,
        "--room-root",
        room,
        "--outdir",
        metadata_dir,
        "--extractor",
        "stdlib",
    )
    assert prepared.returncode == 0, prepared.stderr or prepared.stdout
    metadata = json.loads(
        (metadata_dir / "regex-metadata" / f"{document['id']}.json").read_text(
            encoding="utf-8"
        )
    )
    assert metadata["title"] == "MASTER SERVICES AGREEMENT"
    assert not metadata["title"].startswith("PK")

    findings_path = tmp_path / "findings.json"
    checked_path = tmp_path / "findings.checked.json"
    write_json(
        findings_path,
        {
            "findings": [
                {
                    "doc_id": document["id"],
                    "finding_id": f"assignment-consent/{document['id']}",
                    "quote": "Consent is required before assignment.",
                    "status": "present",
                }
            ]
        },
    )
    verified = run_script(
        SCRIPTS / "verify_finding_quotes.py",
        "--findings",
        findings_path,
        "--manifest",
        manifest_path,
        "--room-root",
        room,
        "--extractor",
        "stdlib",
        "--out",
        checked_path,
    )
    assert verified.returncode == 0, verified.stderr or verified.stdout
    finding = json.loads(checked_path.read_text(encoding="utf-8"))["findings"][0]
    assert finding["status"] == "present"
    assert finding["quote_verification"]["status"] == "confirmed"


def test_worker_batch_validation_runs_on_system_python_39() -> None:
    script = SHARED / "run_codex_finding_worker.py"
    program = f"""
import importlib.util
spec = importlib.util.spec_from_file_location('worker', {str(script)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assignment = {{'review_plan_id': 'a' * 16, 'job_id': 'b' * 16,
              'issue_items': [{{'issue_id': 'one'}}]}}
value = {{'contract': 'finding-worker/2', 'review_plan_id': 'a' * 16,
         'job_id': 'b' * 16,
         'determinations': [{{'n': 1, 'issue_id': 'one', 'status': 'absent'}}],
         'privilege_candidates': []}}
rows, candidates = module.validate_batch_result(value, assignment, 0)
assert rows[0]['issue_id'] == 'one' and candidates == []
"""
    result = subprocess.run(
        ["/usr/bin/python3", "-c", program],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
