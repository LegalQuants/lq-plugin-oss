"""Tests for the setup-review and run-all orchestration.

The orchestrator exists so the review sequence is enforced in code. These
tests hold it to the governance rules: nothing confirms Gate 1 except the
lawyer, coverage is never counted as complete by default, and run-all refuses
to export a run that is bound to the wrong stance or drafts with unmapped
house terms.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
REVIEWER = ROOT / "skills/transactional/playbook-review"
sys.path.insert(0, str(REVIEWER / "scripts"))

from shared.playbook_runtime import (  # noqa: E402
    PlaybookError,
    build_source_manifest,
    compile_effective_stance,
    describe_coverage_gaps,
    reconcile_coverage_from_artifacts,
    run_review_pipeline,
    setup_review_pipeline,
    validate_element_sweep,
    validate_issues_list,
)

CONTRACT_TEXT = (
    "Supplier aggregate liability is capped at 50% of annual fees.\n\n"
    "Either party may terminate on 90 days written notice.\n\n"
    "This Agreement is governed by the laws of England and Wales.\n"
)


def _sample_playbook(
    manifest_sha: str = "0" * 64, doc_sha: str = "1" * 64
) -> dict[str, Any]:
    return {
        "artifactType": "contract-playbook",
        "schemaVersion": "1.0",
        "playbookId": "saas-supplier",
        "version": "1.0.0",
        "title": "Supplier SaaS Playbook",
        "status": "approved",
        "perspective": "supplier",
        "agreementFamily": "SaaS agreement",
        "governingLaw": "England and Wales",
        "dateStyle": "uk",
        "sourceManifestSha256": manifest_sha,
        "issues": [
            {
                "issueId": "liability-cap",
                "topic": "Liability cap",
                "status": "approved",
                "basePosition": {
                    "summary": "Annual fees cap",
                    "preferred": {
                        "summary": "100% annual fees",
                        "text": "The Supplier aggregate liability is capped at 100% of annual fees.",
                        "approvalStatus": "approved",
                    },
                    "fallbacks": [],
                    "redLine": "No unlimited liability",
                    "priority": "high",
                },
                "provenance": [
                    {
                        "documentSha256": doc_sha,
                        "elementId": "el-prov-1",
                        "exactText": "The Supplier aggregate liability is capped at 100% of annual fees.",
                        "sourceRole": "km-guidance",
                    }
                ],
                "dependencies": [],
            },
            {
                "issueId": "term-notice",
                "topic": "Termination notice",
                "status": "approved",
                "basePosition": {
                    "summary": "30 days notice",
                    "preferred": {
                        "summary": "30 days notice",
                        "text": "Either party may terminate on 30 days written notice.",
                        "approvalStatus": "approved",
                    },
                    "fallbacks": [],
                    "redLine": "Notice under 14 days",
                    "priority": "medium",
                },
                "provenance": [
                    {
                        "documentSha256": doc_sha,
                        "elementId": "el-prov-2",
                        "exactText": "Either party may terminate on 30 days written notice.",
                        "sourceRole": "km-guidance",
                    }
                ],
                "dependencies": [],
            },
        ],
        "matterLenses": [
            {
                "lensId": "regulated-fs",
                "label": "Regulated financial services",
                "description": "Higher caps and regulator audit rights for FS customers.",
                "status": "approved",
                "adjustments": [
                    {
                        "issueId": "liability-cap",
                        "reason": "FS customers require a higher cap",
                        "changes": {"summary": "150% annual fees"},
                    }
                ],
            }
        ],
    }


def _confirmed_activation(lenses: list[str] | None = None) -> dict[str, Any]:
    return {
        "artifactType": "matter-lens-activation",
        "schemaVersion": "1.0",
        "activatedLenses": lenses or [],
        "suggestedLenses": [],
        "matterInstructions": [],
        "confirmedByLawyer": True,
        "confirmationNote": "Lawyer's message: 'confirm Standard Baseline only'",
    }


def _run_cli(*arguments: object) -> subprocess.CompletedProcess[str]:
    script = REVIEWER / "scripts/playbook_review.py"
    return subprocess.run(
        [sys.executable, str(script), *(str(arg) for arg in arguments)],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )


def _write(path: Path, payload: Any) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _contract_and_playbook(tmp_path: Path) -> tuple[Path, Path]:
    contract = tmp_path / "Acme_Agreement.md"
    contract.write_text(CONTRACT_TEXT, encoding="utf-8")
    playbook = _write(tmp_path / "playbook.json", _sample_playbook())
    return contract, playbook


def _issue(
    doc_sha: str, element: dict[str, Any], rule: str, **overrides: Any
) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "issueId": f"rev-{rule}",
        "playbookIssueId": rule,
        "classification": "aligned-preferred",
        "materiality": "none",
        "documentSha256": doc_sha,
        "elementId": element["elementId"],
        "clauseRef": None,
        "originalText": element["sourceText"],
        "proposedText": element["sourceText"],
        "draftingProvenance": "none",
        "rationale": "Aligned.",
        "lawyerReview": "not-required",
    }
    issue.update(overrides)
    return issue


def _prepared_run(tmp_path: Path) -> dict[str, Any]:
    """Manifest, stance and playbook for a run, ready for an issues list."""
    contract, playbook_file = _contract_and_playbook(tmp_path)
    manifest = build_source_manifest(
        [contract], tmp_path, {contract.name: "contract-under-review"}
    )
    manifest_file = _write(tmp_path / "source-manifest.json", manifest)
    playbook = json.loads(playbook_file.read_text(encoding="utf-8"))
    stance = compile_effective_stance(playbook, _confirmed_activation())
    stance_file = _write(tmp_path / "effective-stance.json", stance)
    doc = manifest["documents"][0]
    return {
        "manifest": manifest,
        "manifest_file": manifest_file,
        "stance": stance,
        "stance_file": stance_file,
        "playbook": playbook,
        "playbook_file": playbook_file,
        "doc": doc,
        "elements": doc["elements"],
    }


def _issues_list(run: dict[str, Any], issues: list[dict[str, Any]], **extra: Any):
    payload: dict[str, Any] = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "review-run",
        "sourceManifestSha256": run["manifest"]["manifestSha256"],
        "playbookId": run["playbook"]["playbookId"],
        "playbookVersion": run["playbook"]["version"],
        "effectiveStanceSha256": run["stance"]["stanceSha256"],
        "contractName": "Acme Agreement",
        "issues": issues,
    }
    payload.update(extra)
    return payload


def _full_issues(run: dict[str, Any]) -> list[dict[str, Any]]:
    doc_sha = run["doc"]["sha256"]
    cap, notice, _law = run["elements"][:3]
    proposed = "Supplier aggregate liability is capped at 100% of annual fees."
    return [
        _issue(
            doc_sha,
            cap,
            "liability-cap",
            classification="deviation",
            materiality="high",
            proposedText=proposed,
            draftingProvenance="approved-playbook",
            rationale="Below the house floor.",
            externalComment="We propose a cap of 100% of annual fees.",
            lawyerReview="pending",
        ),
        _issue(
            doc_sha,
            notice,
            "term-notice",
            classification="aligned-fallback",
            materiality="low",
            rationale="90 days is within the approved range.",
        ),
    ]


# --- Gate 1 ------------------------------------------------------------------


def test_setup_review_without_confirmation_stops_at_gate_1(tmp_path: Path) -> None:
    contract, playbook_file = _contract_and_playbook(tmp_path)
    run_dir = tmp_path / "run"
    result = setup_review_pipeline(
        sources=[contract],
        boundary=tmp_path,
        playbook_path=playbook_file,
        out_dir=run_dir,
    )
    assert result["status"] == "awaiting-gate-1"
    assert (run_dir / "source-manifest.json").is_file()
    assert not (run_dir / "matter-lens-activation.json").exists()
    assert not (run_dir / "effective-stance.json").exists()
    assert result["stancePath"] is None
    assert result["gate1"]["defaultStance"] == "standard-baseline"
    assert result["gate1"]["approvedLenses"][0]["lensId"] == "regulated-fs"
    assert result["documentsCount"] == 1
    assert result["elementsCount"] == 3


def test_setup_review_quotes_the_lawyers_words(tmp_path: Path) -> None:
    contract, playbook_file = _contract_and_playbook(tmp_path)
    run_dir = tmp_path / "run"
    result = setup_review_pipeline(
        sources=[contract],
        boundary=tmp_path,
        playbook_path=playbook_file,
        confirmation="confirm Standard Baseline only, no lenses",
        out_dir=run_dir,
        contract_name="Acme Enterprise Agreement",
    )
    assert result["status"] == "ready"
    assert result["operativeRulesCount"] == 2
    assert result["activatedLenses"] == []
    assert result["contractName"] == "Acme Enterprise Agreement"
    activation = json.loads(
        (run_dir / "matter-lens-activation.json").read_text(encoding="utf-8")
    )
    assert activation["confirmedByLawyer"] is True
    assert "confirm Standard Baseline only, no lenses" in activation["confirmationNote"]
    assert activation["confirmationNote"].startswith("Lawyer's message:")
    assert set(activation) == {
        "artifactType",
        "schemaVersion",
        "activatedLenses",
        "suggestedLenses",
        "matterInstructions",
        "confirmedByLawyer",
        "confirmationNote",
    }
    stance = json.loads((run_dir / "effective-stance.json").read_text(encoding="utf-8"))
    assert stance["status"] == "ready"


def test_setup_review_activates_a_lens_only_with_confirmation(tmp_path: Path) -> None:
    contract, playbook_file = _contract_and_playbook(tmp_path)
    with pytest.raises(PlaybookError, match="lawyer's confirmation"):
        setup_review_pipeline(
            sources=[contract],
            boundary=tmp_path,
            playbook_path=playbook_file,
            selected_lenses=["regulated-fs"],
            out_dir=tmp_path / "run-a",
        )
    result = setup_review_pipeline(
        sources=[contract],
        boundary=tmp_path,
        playbook_path=playbook_file,
        confirmation="please apply the regulated FS lens",
        selected_lenses=["regulated-fs"],
        out_dir=tmp_path / "run-b",
    )
    assert result["status"] == "ready"
    assert result["activatedLenses"] == ["regulated-fs"]


def test_setup_review_rejects_unconfirmed_activation_file(tmp_path: Path) -> None:
    contract, playbook_file = _contract_and_playbook(tmp_path)
    activation = _confirmed_activation()
    activation["confirmedByLawyer"] = False
    activation_file = _write(tmp_path / "activation.json", activation)
    with pytest.raises(PlaybookError, match="not confirmed by the lawyer"):
        setup_review_pipeline(
            sources=[contract],
            boundary=tmp_path,
            playbook_path=playbook_file,
            activation_path=activation_file,
            out_dir=tmp_path / "run",
        )


def test_setup_review_rejects_draft_playbook(tmp_path: Path) -> None:
    contract, _ = _contract_and_playbook(tmp_path)
    draft = _sample_playbook()
    draft["status"] = "draft"
    draft_file = _write(tmp_path / "draft.json", draft)
    with pytest.raises(PlaybookError, match="not usable for an operative review"):
        setup_review_pipeline(
            sources=[contract],
            boundary=tmp_path,
            playbook_path=draft_file,
            confirmation="confirm Standard Baseline only",
            out_dir=tmp_path / "run",
        )


def test_setup_review_cli_exit_codes(tmp_path: Path) -> None:
    contract, playbook_file = _contract_and_playbook(tmp_path)
    run_dir = tmp_path / "cli-run"
    waiting = _run_cli(
        "setup-review",
        contract,
        "--boundary",
        tmp_path,
        "--playbook",
        playbook_file,
        "--out-dir",
        run_dir,
    )
    assert waiting.returncode == 2, waiting.stderr
    assert json.loads(waiting.stdout)["status"] == "awaiting-gate-1"

    ready = _run_cli(
        "setup-review",
        contract,
        "--boundary",
        tmp_path,
        "--playbook",
        playbook_file,
        "--out-dir",
        run_dir,
        "--confirm",
        "confirm Standard Baseline only",
    )
    assert ready.returncode == 0, ready.stderr
    data = json.loads(ready.stdout)
    assert data["status"] == "ready"
    assert data["operativeRulesCount"] == 2
    assert "SHA" not in ready.stdout.upper().replace("SHA256", "")


# --- Coverage ----------------------------------------------------------------


def test_coverage_is_not_completed_by_default(tmp_path: Path) -> None:
    run = _prepared_run(tmp_path)
    doc_sha = run["doc"]["sha256"]
    cap = run["elements"][0]
    # One rule evaluated, one rule with no status, two elements never swept.
    issues = _issues_list(
        run,
        [
            _issue(
                doc_sha,
                cap,
                "liability-cap",
                classification="deviation",
                materiality="high",
                proposedText="x",
                markupSegments=[
                    {"op": "delete", "text": cap["sourceText"]},
                    {"op": "insert", "text": "x"},
                ],
                draftingProvenance="candidate-drafting",
                lawyerReview="pending",
            )
        ],
    )
    receipt = reconcile_coverage_from_artifacts(run["manifest"], run["stance"], issues)
    assert receipt["reconciled"] is False
    assert receipt["rules"] == {
        "expected": 2,
        "evaluated": 1,
        "notApplicable": 0,
        "blocked": 0,
    }
    assert receipt["elements"]["expected"] == 3
    assert receipt["elements"]["completed"] == 1
    assert receipt["documents"] == {
        "expected": 1,
        "completed": 0,
        "parked": 1,
        "unreadable": 0,
    }
    gaps = describe_coverage_gaps(run["manifest"], run["stance"], issues)
    assert gaps["missingRules"] == ["term-notice"]
    assert len(gaps["unsweptElements"]) == 2


def test_coverage_reconciles_with_explicit_sweep(tmp_path: Path) -> None:
    run = _prepared_run(tmp_path)
    law_element = run["elements"][2]
    issues = _issues_list(
        run,
        _full_issues(run),
        elementSweep={"completed": [law_element["elementId"]]},
    )
    receipt = reconcile_coverage_from_artifacts(run["manifest"], run["stance"], issues)
    assert receipt["reconciled"] is True
    assert receipt["elements"] == {
        "expected": 3,
        "completed": 3,
        "parked": 0,
        "unreadable": 0,
    }
    assert receipt["rules"] == {
        "expected": 2,
        "evaluated": 2,
        "notApplicable": 0,
        "blocked": 0,
    }
    assert receipt["documents"]["completed"] == 1

    remaining = _issues_list(
        run, _full_issues(run), elementSweep={"completed": "all-remaining"}
    )
    assert reconcile_coverage_from_artifacts(run["manifest"], run["stance"], remaining)[
        "reconciled"
    ]

    parked = _issues_list(
        run, _full_issues(run), elementSweep={"parked": [law_element["elementId"]]}
    )
    parked_receipt = reconcile_coverage_from_artifacts(
        run["manifest"], run["stance"], parked
    )
    assert parked_receipt["reconciled"] is True
    assert parked_receipt["elements"]["parked"] == 1
    assert parked_receipt["documents"]["parked"] == 1


def test_coverage_rule_status_precedence_and_outside_stance(tmp_path: Path) -> None:
    run = _prepared_run(tmp_path)
    doc_sha = run["doc"]["sha256"]
    cap, notice, law = run["elements"]
    issues = _issues_list(
        run,
        [
            _issue(
                doc_sha,
                cap,
                "liability-cap",
                classification="deviation",
                materiality="high",
                proposedText="y",
                markupSegments=[
                    {"op": "delete", "text": cap["sourceText"]},
                    {"op": "insert", "text": "y"},
                ],
                draftingProvenance="candidate-drafting",
                lawyerReview="pending",
            ),
            _issue(
                doc_sha,
                notice,
                "liability-cap",
                issueId="rev-cap-na",
                classification="not-applicable",
            ),
            _issue(doc_sha, law, "term-notice", classification="playbook-conflict"),
            _issue(
                doc_sha,
                law,
                "no-such-rule",
                issueId="rev-stray",
                classification="playbook-gap",
            ),
        ],
    )
    receipt = reconcile_coverage_from_artifacts(run["manifest"], run["stance"], issues)
    assert receipt["rules"] == {
        "expected": 2,
        "evaluated": 1,
        "notApplicable": 0,
        "blocked": 1,
    }
    gaps = describe_coverage_gaps(run["manifest"], run["stance"], issues)
    assert gaps["issuesOutsideStance"] == ["no-such-rule"]
    assert gaps["missingRules"] == []


def test_manual_coverage_counts_still_take_precedence(tmp_path: Path) -> None:
    run = _prepared_run(tmp_path)
    counts = {
        "runId": "manual",
        "documents": {"expected": 1, "completed": 1, "parked": 0, "unreadable": 0},
        "elements": {"expected": 3, "completed": 3, "parked": 0, "unreadable": 0},
        "rules": {"expected": 2, "evaluated": 2, "notApplicable": 0, "blocked": 0},
    }
    receipt = reconcile_coverage_from_artifacts(
        run["manifest"], run["stance"], _issues_list(run, []), coverage_counts=counts
    )
    assert receipt["reconciled"] is True
    assert receipt["runId"] == "manual"


def test_element_sweep_is_validated(tmp_path: Path) -> None:
    assert validate_element_sweep(None) == []
    assert validate_element_sweep({"completed": "all-remaining"}) == []
    assert validate_element_sweep("done") == ["elementSweep must be an object"]
    errors = validate_element_sweep(
        {"completed": ["el-1", ""], "unreadable": "el-2"}, known_ids={"el-1"}
    )
    assert any("completed must be a list" in e for e in errors)
    assert any("unreadable must be a list" in e for e in errors)
    overlap = validate_element_sweep({"completed": ["el-1"], "parked": ["el-1"]})
    assert overlap == ["elementSweep: el-1 is listed as both completed and parked"]
    assert validate_element_sweep({"completed": ["ghost"]}, known_ids={"el-1"}) == [
        "elementSweep: unknown element ghost"
    ]
    run = _prepared_run(tmp_path)
    bad = _issues_list(run, [], elementSweep={"completed": ["ghost"]})
    from shared.playbook_runtime import source_text_index

    errors = validate_issues_list(bad, source_text_index(run["manifest"]))
    assert "elementSweep: unknown element ghost" in errors


# --- run-all -----------------------------------------------------------------


def test_run_review_pipeline_reconciled_run(tmp_path: Path) -> None:
    run = _prepared_run(tmp_path)
    issues_file = _write(
        tmp_path / "issues-list.json",
        _issues_list(
            run, _full_issues(run), elementSweep={"completed": "all-remaining"}
        ),
    )
    out_dir = tmp_path / "out"
    result = run_review_pipeline(
        issues_path=issues_file,
        manifest_path=run["manifest_file"],
        stance_path=run["stance_file"],
        playbook_path=run["playbook_file"],
        out_dir=out_dir,
    )
    assert result["status"] == "reconciled"
    assert result["reconciled"] is True
    assert result["coverageGaps"] == {
        "missingRules": [],
        "unsweptElements": [],
        "issuesOutsideStance": [],
    }
    artifacts = result["artifacts"]
    assert set(artifacts) == {
        "issuesList",
        "coverageReceipt",
        "reviewReceipt",
        "docxInternal",
        "docxExternal",
        "html",
    }
    for path in artifacts.values():
        assert Path(path).is_file(), path
    assert Path(artifacts["docxInternal"]).name == "issues-matrix.docx"
    assert Path(artifacts["docxExternal"]).name == "issues-matrix-external.docx"
    assert Path(artifacts["html"]).name == "issues-list.html"
    assert not (out_dir / "issues-matrix-internal.docx").exists()

    saved = json.loads(Path(artifacts["issuesList"]).read_text(encoding="utf-8"))
    assert saved["issues"][0]["markupSegments"]
    assert saved["generatedAt"].endswith("Z")
    review = json.loads(Path(artifacts["reviewReceipt"]).read_text(encoding="utf-8"))
    assert review["reconciled"] is True
    assert review["effectiveStanceSha256"] == run["stance"]["stanceSha256"]


def test_run_review_pipeline_reports_gaps_and_exits_unreconciled(
    tmp_path: Path,
) -> None:
    run = _prepared_run(tmp_path)
    issues_file = _write(
        tmp_path / "issues-list.json", _issues_list(run, _full_issues(run))
    )
    result = run_review_pipeline(
        issues_path=issues_file,
        manifest_path=run["manifest_file"],
        stance_path=run["stance_file"],
        out_dir=tmp_path / "out",
    )
    assert result["status"] == "unreconciled"
    assert result["coverageGaps"]["unsweptElements"] == [
        run["elements"][2]["elementId"]
    ]
    # The exports are still written so the lawyer can see the work so far.
    assert Path(result["artifacts"]["docxInternal"]).is_file()


def test_run_review_pipeline_refuses_wrong_stance_binding(tmp_path: Path) -> None:
    run = _prepared_run(tmp_path)
    wrong = _issues_list(run, _full_issues(run), effectiveStanceSha256="f" * 64)
    issues_file = _write(tmp_path / "issues-list.json", wrong)
    with pytest.raises(PlaybookError, match="different effective stance"):
        run_review_pipeline(
            issues_path=issues_file,
            manifest_path=run["manifest_file"],
            stance_path=run["stance_file"],
        )
    wrong_version = _issues_list(run, _full_issues(run), playbookVersion="9.9.9")
    issues_file = _write(tmp_path / "issues-list.json", wrong_version)
    with pytest.raises(PlaybookError, match="different playbook version"):
        run_review_pipeline(
            issues_path=issues_file,
            manifest_path=run["manifest_file"],
            stance_path=run["stance_file"],
        )


def test_run_review_pipeline_refuses_blocked_stance(tmp_path: Path) -> None:
    run = _prepared_run(tmp_path)
    blocked = dict(run["stance"])
    blocked["status"] = "blocked"
    blocked_file = _write(tmp_path / "blocked-stance.json", blocked)
    issues_file = _write(
        tmp_path / "issues-list.json", _issues_list(run, _full_issues(run))
    )
    with pytest.raises(PlaybookError, match="blocked"):
        run_review_pipeline(
            issues_path=issues_file,
            manifest_path=run["manifest_file"],
            stance_path=blocked_file,
        )


def test_run_review_pipeline_refuses_unmapped_house_terms(tmp_path: Path) -> None:
    run = _prepared_run(tmp_path)
    issues = _full_issues(run)
    issues[0]["proposedText"] = (
        "Supplier aggregate liability is capped at 100% of the Fees."
    )
    issues_file = _write(
        tmp_path / "issues-list.json",
        _issues_list(run, issues, elementSweep={"completed": "all-remaining"}),
    )
    term_map = {
        "entries": [
            {
                "relation": "unresolved",
                "lawyerReview": "pending",
                "houseDefinition": {"term": "Fees"},
            }
        ]
    }
    term_map_file = _write(tmp_path / "term-map.json", term_map)
    with pytest.raises(PlaybookError, match="Fees \\(unresolved\\)"):
        run_review_pipeline(
            issues_path=issues_file,
            manifest_path=run["manifest_file"],
            stance_path=run["stance_file"],
            term_map_path=term_map_file,
        )
    # Accepted by the lawyer: no longer a blocker.
    term_map["entries"][0]["lawyerReview"] = "accepted"
    _write(term_map_file, term_map)
    result = run_review_pipeline(
        issues_path=issues_file,
        manifest_path=run["manifest_file"],
        stance_path=run["stance_file"],
        term_map_path=term_map_file,
    )
    assert result["reconciled"] is True


def test_run_review_pipeline_validation_failure_writes_nothing(tmp_path: Path) -> None:
    run = _prepared_run(tmp_path)
    bad = _full_issues(run)
    bad[0]["originalText"] = "Completely hallucinated text not in element"
    issues_file = _write(tmp_path / "issues-list.json", _issues_list(run, bad))
    out_dir = tmp_path / "out"
    with pytest.raises(PlaybookError, match="Issues list validation failed"):
        run_review_pipeline(
            issues_path=issues_file,
            manifest_path=run["manifest_file"],
            stance_path=run["stance_file"],
            out_dir=out_dir,
        )
    assert not out_dir.exists()


def test_setup_and_run_all_cli_end_to_end(tmp_path: Path) -> None:
    contract, playbook_file = _contract_and_playbook(tmp_path)
    run_dir = tmp_path / "run"
    setup = _run_cli(
        "setup-review",
        contract,
        "--boundary",
        tmp_path,
        "--playbook",
        playbook_file,
        "--out-dir",
        run_dir,
        "--confirm",
        "confirm Standard Baseline only",
        "--contract-name",
        "Acme Agreement",
    )
    assert setup.returncode == 0, setup.stderr
    manifest = json.loads(
        (run_dir / "source-manifest.json").read_text(encoding="utf-8")
    )
    stance = json.loads((run_dir / "effective-stance.json").read_text(encoding="utf-8"))
    playbook = json.loads(playbook_file.read_text(encoding="utf-8"))
    run = {
        "manifest": manifest,
        "stance": stance,
        "playbook": playbook,
        "doc": manifest["documents"][0],
        "elements": manifest["documents"][0]["elements"],
    }

    unswept = _write(run_dir / "issues-list.json", _issues_list(run, _full_issues(run)))
    partial = _run_cli("run-all", unswept, "--playbook", playbook_file)
    assert partial.returncode == 1, partial.stderr
    assert json.loads(partial.stdout)["coverageGaps"]["unsweptElements"]

    complete = _write(
        run_dir / "issues-list.json",
        _issues_list(
            run, _full_issues(run), elementSweep={"completed": "all-remaining"}
        ),
    )
    done = _run_cli("run-all", complete, "--playbook", playbook_file)
    assert done.returncode == 0, done.stderr
    output = json.loads(done.stdout)
    assert output["status"] == "reconciled"
    assert (run_dir / "issues-matrix.docx").is_file()
    assert (run_dir / "issues-matrix-external.docx").is_file()
    assert (run_dir / "issues-list.html").is_file()
    assert (run_dir / "coverage-receipt.json").is_file()
    assert (run_dir / "review-receipt.json").is_file()
