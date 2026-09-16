"""Regression tests for compact, ID-safe DocReview worker admission."""

# ruff: noqa: E501

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SHARED = ROOT / "skills/litigation/docreview/scripts/shared"
ADMITTER = SHARED / "admit_finding_result.py"
RUNNER = SHARED / "run_review_jobs.py"
CODEX_WORKER = SHARED / "run_codex_finding_worker.py"
SCHEMA = (
    ROOT / "skills/litigation/docreview/references/shared/finding-worker.schema.json"
)


def test_diligence_shares_the_same_mapping_runtime_and_guidance() -> None:
    shared_pairs = (
        "scripts/shared/run_codex_finding_worker.py",
        "scripts/shared/run_review_jobs.py",
        "references/openai-codex-runtime.md",
        "references/shared/execution-modes.md",
        "references/shared/finding-worker-prompt.md",
    )
    for relative in shared_pairs:
        assert (ROOT / "skills/litigation/docreview" / relative).read_bytes() == (
            ROOT / "skills/transactional/diligence" / relative
        ).read_bytes()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def assignment(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "lease.txt"
    source.write_text("The monthly rent is $2,400.\n", encoding="utf-8")
    import hashlib

    doc_id = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    path = tmp_path / "assignment.json"
    write_json(
        path,
        {
            "documents": [
                {
                    "id": doc_id,
                    "pages": None,
                    "path": source.name,
                    "readability": "native",
                    "title": "Lease",
                }
            ],
            "framework_version": 1,
            "issue_items": [
                {
                    "answer_shape": {"characterization_max_words": 30},
                    "issue_id": "rent-payment",
                }
            ],
            "job_id": "0012068f5f3fb4a6",
            "lens_id": "rent",
            "member_ids": [doc_id],
            "requires_current_position": False,
            "review_plan_id": "20ac3e44da66f908",
            "unit_id": doc_id,
        },
    )
    return path, doc_id


def run_admitter(
    tmp_path: Path, assignment_path: Path, raw: object
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    raw_path = tmp_path / "raw.json"
    result_path = tmp_path / "maker-result.json"
    receipt_path = tmp_path / "receipt.json"
    write_json(raw_path, raw)
    completed = subprocess.run(
        [
            sys.executable,
            str(ADMITTER),
            "--assignment",
            str(assignment_path),
            "--raw",
            str(raw_path),
            "--room-root",
            str(tmp_path),
            "--out",
            str(result_path),
            "--receipt",
            str(receipt_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed, result_path, receipt_path


def test_compact_absent_is_expanded_without_model_copying_hashes(
    tmp_path: Path,
) -> None:
    assignment_path, doc_id = assignment(tmp_path)
    raw = {
        "contract": "finding-worker/2",
        "determinations": [{"issue_id": "rent-payment", "n": 1, "status": "absent"}],
        "job_id": "0012068f5f3fb4a6",
        "privilege_candidates": [],
        "review_plan_id": "20ac3e44da66f908",
    }

    completed, result_path, receipt_path = run_admitter(tmp_path, assignment_path, raw)

    assert completed.returncode == 0, completed.stderr or completed.stdout
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["unit_id"] == doc_id
    assert result["findings"] == [
        {
            "band": None,
            "band_basis": None,
            "characterization": "No responsive evidence found in the reviewed unit.",
            "current_position": False,
            "doc_id": doc_id,
            "finding_id": f"rent-payment/{doc_id}",
            "issue_id": "rent-payment",
            "page": None,
            "quote": None,
            "receipt_mode": None,
            "section": None,
            "status": "absent",
        }
    ]
    first_result = result_path.read_bytes()
    first_receipt = receipt_path.read_bytes()
    completed, _, _ = run_admitter(tmp_path, assignment_path, raw)
    assert completed.returncode == 0
    assert result_path.read_bytes() == first_result
    assert receipt_path.read_bytes() == first_receipt


def test_worker_schema_is_compact_and_response_format_safe() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["properties"]["contract"]["const"] == "finding-worker/2"
    determination = schema["properties"]["determinations"]["items"]
    variants = determination["anyOf"]
    assert len(variants) == 4
    assert {variant["properties"]["status"]["const"] for variant in variants} == {
        "absent",
        "present",
        "unresolved",
    }
    for variant in variants:
        assert set(variant["required"]) == set(variant["properties"])
        assert variant["additionalProperties"] is False
        assert "finding_id" not in variant["properties"]
        assert "doc_id" not in variant["properties"]
    assert "uniqueItems" not in json.dumps(schema)


def test_worker_schema_all_objects_are_openai_strict() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    def visit(value: object) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if value.get("type") == "object" and isinstance(properties, dict):
                assert value.get("additionalProperties") is False
                assert set(value.get("required", [])) == set(properties)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)


def test_codex_worker_attaches_hash_verified_review_pages(tmp_path: Path) -> None:
    assignment_path, doc_id = assignment(tmp_path)
    value = json.loads(assignment_path.read_text(encoding="utf-8"))
    value["documents"][0]["readability"] = "scanned"
    write_json(assignment_path, value)
    bundle = tmp_path / "review-copies/objects/aa"
    bundle.mkdir(parents=True)
    image = bundle / "page.png"
    image.write_bytes(b"verified page bytes")
    import hashlib

    digest = "sha256:" + hashlib.sha256(image.read_bytes()).hexdigest()
    sidecar = tmp_path / "review-copies.json"
    write_json(
        sidecar,
        {
            "bundle_root": "review-copies",
            "documents": [
                {
                    "derivatives": [
                        {
                            "media_type": "image/png",
                            "page": 2,
                            "path": "objects/aa/page.png",
                            "sha256": digest,
                        }
                    ],
                    "doc_id": doc_id,
                    "status": "ready",
                }
            ],
        },
    )
    argv_path = tmp_path / "argv.json"
    stdin_path = tmp_path / "stdin.txt"
    fake = tmp_path / "fake-codex.py"
    fake.write_text(
        """#!/usr/bin/env python3
import json, os, pathlib, sys
pathlib.Path(os.environ['FAKE_ARGV']).write_text(json.dumps(sys.argv[1:]))
pathlib.Path(os.environ['FAKE_STDIN']).write_text(sys.stdin.read())
out = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])
out.write_text(json.dumps({'contract':'finding-worker/2','review_plan_id':'20ac3e44da66f908','job_id':'0012068f5f3fb4a6','determinations':[{'n':1,'issue_id':'rent-payment','status':'absent'}],'privilege_candidates':[]}))
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    output = tmp_path / "raw.json"
    env = {**os.environ, "FAKE_ARGV": str(argv_path), "FAKE_STDIN": str(stdin_path)}
    completed = subprocess.run(
        [
            sys.executable,
            str(CODEX_WORKER),
            "--assignment",
            str(assignment_path),
            "--output",
            str(output),
            "--schema",
            str(SCHEMA),
            "--room-root",
            str(tmp_path),
            "--review-copies",
            str(sidecar),
            "--model",
            "gpt-test",
            "--effort",
            "medium",
            "--codex",
            str(fake),
        ],
        input="worker prompt",
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    argv = json.loads(argv_path.read_text(encoding="utf-8"))
    assert argv[0] == "exec"
    assert "--ignore-user-config" in argv
    assert "--ignore-rules" in argv
    assert argv[argv.index("--image") + 1] == str(image)
    assert "Attachment 1: Document 1, page 2" in stdin_path.read_text(encoding="utf-8")
    assert output.exists()


def test_codex_worker_persists_jsonl_token_usage(tmp_path: Path) -> None:
    assignment_path, doc_id = assignment(tmp_path)
    sidecar = tmp_path / "review-copies.json"
    write_json(
        sidecar,
        {
            "bundle_root": "review-copies",
            "documents": [{"derivatives": [], "doc_id": doc_id, "status": "ready"}],
        },
    )
    fake = tmp_path / "fake-codex.py"
    fake.write_text(
        """#!/usr/bin/env python3
import json, pathlib, sys
out = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])
out.write_text(json.dumps({'contract':'finding-worker/2','review_plan_id':'20ac3e44da66f908','job_id':'0012068f5f3fb4a6','determinations':[{'n':1,'issue_id':'rent-payment','status':'absent'}],'privilege_candidates':[]}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':120,'cached_input_tokens':40,'output_tokens':15,'reasoning_output_tokens':5}}))
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    output = tmp_path / "raw.json"
    usage_path = tmp_path / "usage.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(CODEX_WORKER),
            "--assignment",
            str(assignment_path),
            "--output",
            str(output),
            "--usage-out",
            str(usage_path),
            "--require-usage",
            "--schema",
            str(SCHEMA),
            "--room-root",
            str(tmp_path),
            "--review-copies",
            str(sidecar),
            "--model",
            "gpt-test",
            "--effort",
            "medium",
            "--codex",
            str(fake),
        ],
        input="worker prompt",
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    usage = json.loads(usage_path.read_text(encoding="utf-8"))
    assert usage == {
        "cached_input_tokens": 40,
        "contract": "codex-usage/1",
        "effort": "medium",
        "input_tokens": 120,
        "job_id": "0012068f5f3fb4a6",
        "model": "gpt-test",
        "model_calls": 1,
        "output_tokens": 15,
        "reasoning_output_tokens": 5,
        "total_tokens": 135,
    }


def test_codex_worker_refuses_low_effort_without_explicit_override(
    tmp_path: Path,
) -> None:
    assignment_path, doc_id = assignment(tmp_path)
    sidecar = tmp_path / "review-copies.json"
    write_json(
        sidecar,
        {
            "bundle_root": "review-copies",
            "documents": [{"derivatives": [], "doc_id": doc_id, "status": "ready"}],
        },
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(CODEX_WORKER),
            "--assignment",
            str(assignment_path),
            "--output",
            str(tmp_path / "raw.json"),
            "--schema",
            str(SCHEMA),
            "--room-root",
            str(tmp_path),
            "--review-copies",
            str(sidecar),
            "--model",
            "gpt-test",
            "--effort",
            "low",
            "--codex",
            str(tmp_path / "does-not-exist"),
        ],
        input="worker prompt",
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "requires at least medium reasoning effort" in completed.stderr


def test_codex_worker_batches_requests_and_restores_full_order(
    tmp_path: Path,
) -> None:
    assignment_path, doc_id = assignment(tmp_path)
    value = json.loads(assignment_path.read_text(encoding="utf-8"))
    value["issue_items"] = [
        {"answer_shape": {"characterization_max_words": 30}, "issue_id": f"issue-{n}"}
        for n in range(1, 6)
    ]
    write_json(assignment_path, value)
    sidecar = tmp_path / "review-copies.json"
    write_json(
        sidecar,
        {
            "bundle_root": "review-copies",
            "documents": [{"derivatives": [], "doc_id": doc_id, "status": "ready"}],
        },
    )
    count_path = tmp_path / "count.txt"
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    fake = tmp_path / "fake-codex.py"
    fake.write_text(
        """#!/usr/bin/env python3
import json, os, pathlib, re, sys
count_path = pathlib.Path(os.environ['FAKE_COUNT'])
count = int(count_path.read_text()) + 1 if count_path.exists() else 1
count_path.write_text(str(count))
prompt = sys.stdin.read()
pathlib.Path(os.environ['FAKE_PROMPTS'], f'{count}.txt').write_text(prompt)
issue_ids = re.findall(r'\"issue_id\": \"(issue-[0-9]+)\"', prompt)
out = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])
out.write_text(json.dumps({'contract':'finding-worker/2','review_plan_id':'20ac3e44da66f908','job_id':'0012068f5f3fb4a6','determinations':[{'n':n,'issue_id':issue_id,'status':'absent'} for n, issue_id in enumerate(issue_ids, 1)],'privilege_candidates':[]}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':10,'output_tokens':20,'reasoning_output_tokens':5}}))
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    output = tmp_path / "raw.json"
    usage_path = tmp_path / "usage.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(CODEX_WORKER),
            "--assignment",
            str(assignment_path),
            "--output",
            str(output),
            "--usage-out",
            str(usage_path),
            "--require-usage",
            "--schema",
            str(SCHEMA),
            "--room-root",
            str(tmp_path),
            "--review-copies",
            str(sidecar),
            "--model",
            "gpt-test",
            "--effort",
            "medium",
            "--issue-batch-size",
            "2",
            "--codex",
            str(fake),
        ],
        input="worker prompt",
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "FAKE_COUNT": str(count_path),
            "FAKE_PROMPTS": str(prompts_dir),
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert count_path.read_text(encoding="utf-8") == "3"
    result = json.loads(output.read_text(encoding="utf-8"))
    assert [row["issue_id"] for row in result["determinations"]] == [
        f"issue-{n}" for n in range(1, 6)
    ]
    assert [row["n"] for row in result["determinations"]] == [1, 2, 3, 4, 5]
    assert json.loads(usage_path.read_text(encoding="utf-8"))["model_calls"] == 3
    assert all(
        len(re.findall(r"\"issue_id\": \"issue-[0-9]+\"", path.read_text())) <= 2
        for path in prompts_dir.iterdir()
    )


def test_runner_defaults_to_five_and_persists_admission(tmp_path: Path) -> None:
    assignment_path, doc_id = assignment(tmp_path)
    template = json.loads(assignment_path.read_text(encoding="utf-8"))
    run_dir = tmp_path / "run"
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    for index in range(10):
        item = dict(template)
        item["job_id"] = f"{index + 1:016x}"
        write_json(inputs / f"{item['job_id']}.json", item)
    events = tmp_path / "events.jsonl"
    stub = tmp_path / "worker.py"
    stub.write_text(
        """\
import argparse, json, time
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--assignment'); p.add_argument('--output'); p.add_argument('--events'); a=p.parse_args()
j=json.loads(Path(a.assignment).read_text())
with Path(a.events).open('a') as h: h.write(json.dumps({'event':'start','job':j['job_id'],'at':time.time()})+'\\n')
time.sleep(0.08)
raw={'contract':'finding-worker/2','review_plan_id':j['review_plan_id'],'job_id':j['job_id'],'determinations':[{'n':1,'issue_id':'rent-payment','status':'absent'}],'privilege_candidates':[]}
Path(a.output).write_text(json.dumps(raw))
with Path(a.events).open('a') as h: h.write(json.dumps({'event':'end','job':j['job_id'],'at':time.time()})+'\\n')
""",
        encoding="utf-8",
    )
    command = (
        f"{sys.executable} {stub} --assignment {{assignment}} "
        f"--output {{output}} --events {events}"
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "run",
            "--run-dir",
            str(run_dir),
            "--room-root",
            str(tmp_path),
            "--worker-cmd",
            command,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    journal = [
        json.loads(line)
        for line in (run_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert journal[0]["event"] == "run-started"
    assert journal[0]["workers"] == 5
    assert "tunable" in journal[0]["disclosure"]
    assert len(list((run_dir / "maker-results").glob("*.json"))) == 10
    assert len(list((run_dir / "receipts").glob("*.json"))) == 10

    # Concurrency is proven from the workers' own start/end events below (peak
    # overlap between 2 and 5), not from wall-clock time: ten interpreter
    # spawns on a shared CI runner routinely exceeded a fixed bound while the
    # runner was doing exactly what this test asserts.
    intervals: dict[str, dict[str, float]] = {}
    for line in events.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        intervals.setdefault(event["job"], {})[event["event"]] = event["at"]
    moments = sorted(
        (value, 1 if kind == "start" else -1)
        for interval in intervals.values()
        for kind, value in interval.items()
    )
    active = peak = 0
    for _, delta in moments:
        active += delta
        peak = max(peak, active)
    assert 2 <= peak <= 5
    progress = json.loads((run_dir / "progress.json").read_text(encoding="utf-8"))
    assert progress["admitted"] == 10
    assert progress["total"] == 10
    assert doc_id in template["member_ids"]


def test_runner_includes_validator_codes_in_retry_prompt(tmp_path: Path) -> None:
    assignment_path, _ = assignment(tmp_path)
    run_dir = tmp_path / "run"
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "0012068f5f3fb4a6.json").write_bytes(assignment_path.read_bytes())
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    stub = tmp_path / "retry_worker.py"
    stub.write_text(
        """\
import argparse, json, sys
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--assignment'); p.add_argument('--output'); p.add_argument('--prompts'); a=p.parse_args()
j=json.loads(Path(a.assignment).read_text()); attempt=Path(a.output).stem
(Path(a.prompts) / f'{attempt}.txt').write_text(sys.stdin.read())
issue = 'wrong-issue' if attempt == 'attempt-1' else 'rent-payment'
Path(a.output).write_text(json.dumps({'contract':'finding-worker/2','review_plan_id':j['review_plan_id'],'job_id':j['job_id'],'determinations':[{'n':1,'issue_id':issue,'status':'absent'}],'privilege_candidates':[]}))
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "run",
            "--run-dir",
            str(run_dir),
            "--room-root",
            str(tmp_path),
            "--worker-cmd",
            f"{sys.executable} {stub} --assignment {{assignment}} --output {{output}} --prompts {prompts}",
            "--workers",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert (run_dir / "maker-results/0012068f5f3fb4a6.json").exists()
    assert "issue-echo-mismatch" in (prompts / "attempt-2.txt").read_text(
        encoding="utf-8"
    )


def test_runner_aggregates_usage_across_judgment_retries(tmp_path: Path) -> None:
    assignment_path, _ = assignment(tmp_path)
    run_dir = tmp_path / "run"
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "0012068f5f3fb4a6.json").write_bytes(assignment_path.read_bytes())
    stub = tmp_path / "usage_worker.py"
    stub.write_text(
        """\
import argparse, json
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--assignment'); p.add_argument('--output'); p.add_argument('--usage'); a=p.parse_args()
j=json.loads(Path(a.assignment).read_text()); attempt=int(Path(a.output).stem.split('-')[1])
issue = 'wrong-issue' if attempt == 1 else 'rent-payment'
Path(a.output).write_text(json.dumps({'contract':'finding-worker/2','review_plan_id':j['review_plan_id'],'job_id':j['job_id'],'determinations':[{'n':1,'issue_id':issue,'status':'absent'}],'privilege_candidates':[]}))
Path(a.usage).write_text(json.dumps({'contract':'codex-usage/1','job_id':j['job_id'],'input_tokens':100 * attempt,'cached_input_tokens':10 * attempt,'output_tokens':20 * attempt,'reasoning_output_tokens':5 * attempt,'total_tokens':120 * attempt}))
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "run",
            "--run-dir",
            str(run_dir),
            "--room-root",
            str(tmp_path),
            "--worker-cmd",
            f"{sys.executable} {stub} --assignment {{assignment}} --output {{output}} --usage {{usage}}",
            "--workers",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    usage = json.loads((run_dir / "usage.json").read_text(encoding="utf-8"))
    assert usage == {
        "calls_recorded": 2,
        "contract": "review-usage/1",
        "jobs_with_usage": 1,
        "totals": {
            "cached_input_tokens": 30,
            "input_tokens": 300,
            "output_tokens": 60,
            "reasoning_output_tokens": 15,
            "total_tokens": 360,
        },
    }


def test_status_does_not_clobber_live_progress(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    for index in range(10):
        (inputs / f"{index:016x}.json").write_text("{}", encoding="utf-8")
    progress_path = run_dir / "progress.json"
    write_json(
        progress_path,
        {"admitted": 1, "in_flight": 4, "parked": 0, "pending": 5, "total": 10},
    )
    before = progress_path.read_bytes()

    completed = subprocess.run(
        [sys.executable, str(RUNNER), "status", "--run-dir", str(run_dir)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["in_flight"] == 4
    assert progress_path.read_bytes() == before


def test_admitter_rejects_quote_not_in_bound_document(tmp_path: Path) -> None:
    assignment_path, _ = assignment(tmp_path)
    raw = {
        "contract": "finding-worker/2",
        "determinations": [
            {
                "characterization": "The lease states a monthly rent amount.",
                "current_position": False,
                "doc": 1,
                "issue_id": "rent-payment",
                "n": 1,
                "page": None,
                "quote": "The monthly rent is $9,999.",
                "receipt_mode": "text",
                "section": "Rent",
                "status": "present",
            }
        ],
        "job_id": "0012068f5f3fb4a6",
        "privilege_candidates": [],
        "review_plan_id": "20ac3e44da66f908",
    }
    completed, result_path, receipt_path = run_admitter(tmp_path, assignment_path, raw)
    assert completed.returncode == 1
    assert json.loads(completed.stdout)["codes"] == ["quote-not-in-source"]
    assert not result_path.exists()
    assert not receipt_path.exists()


def test_runner_parks_after_three_judgment_rejections(tmp_path: Path) -> None:
    assignment_path, _ = assignment(tmp_path)
    run_dir = tmp_path / "run"
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    target = inputs / "0012068f5f3fb4a6.json"
    target.write_bytes(assignment_path.read_bytes())
    stub = tmp_path / "invalid_worker.py"
    stub.write_text(
        """\
import argparse, json
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--output'); a=p.parse_args()
Path(a.output).write_text(json.dumps({'contract':'finding-worker/2'}))
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "run",
            "--run-dir",
            str(run_dir),
            "--room-root",
            str(tmp_path),
            "--worker-cmd",
            f"{sys.executable} {stub} --output {{output}}",
            "--workers",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    metas = list((run_dir / "attempts/0012068f5f3fb4a6").glob("*.meta.json"))
    assert len(metas) == 3
    parked = json.loads((run_dir / "parked.json").read_text(encoding="utf-8"))
    assert parked["jobs"] == [
        {"job_id": "0012068f5f3fb4a6", "reason": "retry-cap-exhausted"}
    ]
    assert not (run_dir / "maker-results/0012068f5f3fb4a6.json").exists()


def test_detached_runner_survives_launcher_and_completes(tmp_path: Path) -> None:
    assignment_path, _ = assignment(tmp_path)
    run_dir = tmp_path / "run"
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "0012068f5f3fb4a6.json").write_bytes(assignment_path.read_bytes())
    stub = tmp_path / "detached_worker.py"
    stub.write_text(
        """\
import argparse, json, time
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--assignment'); p.add_argument('--output'); a=p.parse_args()
j=json.loads(Path(a.assignment).read_text()); time.sleep(.1)
Path(a.output).write_text(json.dumps({'contract':'finding-worker/2','review_plan_id':j['review_plan_id'],'job_id':j['job_id'],'determinations':[{'n':1,'issue_id':'rent-payment','status':'absent'}],'privilege_candidates':[]}))
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "run",
            "--run-dir",
            str(run_dir),
            "--room-root",
            str(tmp_path),
            "--worker-cmd",
            f"{sys.executable} {stub} --assignment {{assignment}} --output {{output}}",
            "--detach",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert "Detached review runner" in completed.stdout
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        checkpoint = run_dir / "maker-results/0012068f5f3fb4a6.json"
        lease_path = run_dir / "runner.lease.json"
        if checkpoint.exists() and lease_path.exists():
            lease = json.loads(lease_path.read_text(encoding="utf-8"))
            if lease.get("status") == "stopped":
                break
        time.sleep(0.05)
    else:
        raise AssertionError((run_dir / "runner.log").read_text(encoding="utf-8"))
    assert (run_dir / "receipts/0012068f5f3fb4a6.json").exists()
