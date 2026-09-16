from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import types
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[4]
BUILDER = ROOT / "skills/transactional/playbook-builder"
REVIEWER = ROOT / "skills/transactional/playbook-review"
sys.path.insert(0, str(BUILDER / "scripts"))

from shared.playbook_runtime import (  # noqa: E402
    CLASSIFICATION_LABELS,
    PlaybookError,
    adapt_drafting_to_term_map,
    build_coverage_receipt,
    build_markup_segments,
    build_receipt,
    build_review_receipt,
    build_source_manifest,
    build_term_map_skeleton,
    compile_effective_stance,
    extract_sample_text_from_file,
    find_playbook_registry,
    format_british_date,
    format_display_date,
    format_playbook_picker,
    format_playbook_suggestion,
    get_classification_label,
    list_registered_playbooks,
    match_playbook_candidate,
    populate_issues_markup,
    reconstruct_markup,
    register_playbook,
    render_issues_docx,
    render_issues_html,
    render_playbook_html,
    render_playbook_markdown,
    seal_playbook,
    source_text_index,
    validate_issues_list,
    validate_playbook,
    validate_playbook_registry,
    validate_term_map,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _playbook() -> dict:
    return {
        "artifactType": "contract-playbook",
        "schemaVersion": "1.0",
        "playbookId": "saas-customer",
        "version": "1.0.0",
        "title": "Customer SaaS playbook",
        "status": "approved",
        "perspective": "customer",
        "agreementFamily": "SaaS agreement",
        "governingLaw": "England and Wales",
        "sourceManifestSha256": "a" * 64,
        "issues": [
            {
                "issueId": "liability-cap",
                "topic": "Liability cap",
                "status": "approved",
                "basePosition": {
                    "summary": "Annual fees cap",
                    "preferred": {
                        "summary": "100% annual fees",
                        "text": "Liability is capped at 100% of annual Fees.",
                        "approvalStatus": "approved",
                    },
                    "fallbacks": [
                        {
                            "rank": 1,
                            "condition": "Commercial approval",
                            "wording": {
                                "summary": "150% annual fees",
                                "text": "Liability is capped at 150% of annual Fees.",
                                "approvalStatus": "approved",
                            },
                        }
                    ],
                    "redLine": "No cap below fees paid in the preceding 12 months",
                    "priority": "high",
                },
                "provenance": [
                    {
                        "documentSha256": "b" * 64,
                        "elementId": "el-source",
                        "exactText": "Liability is capped at 100% of annual Fees.",
                        "sourceRole": "approved-template",
                    }
                ],
                "dependencies": [],
            }
        ],
        "matterLenses": [
            {
                "lensId": "regulated-fs",
                "label": "Regulated financial services",
                "description": "Higher data and regulatory protection",
                "status": "approved",
                "adjustments": [
                    {
                        "issueId": "liability-cap",
                        "reason": "Regulatory data exposure",
                        "changes": {
                            "summary": "Annual fees cap with data super-cap",
                            "preferred.summary": "100% fees plus data super-cap",
                        },
                    }
                ],
            },
            {
                "lensId": "high-leverage-customer",
                "label": "High-leverage customer",
                "description": "Stronger customer-side position",
                "status": "approved",
                "adjustments": [
                    {
                        "issueId": "liability-cap",
                        "reason": "Commercial leverage",
                        "changes": {"summary": "Two-times fees cap"},
                    }
                ],
            },
        ],
    }


def _activation(**overrides: object) -> dict:
    activation = {
        "artifactType": "matter-lens-activation",
        "schemaVersion": "1.0",
        "activatedLenses": [],
        "suggestedLenses": [],
        "matterInstructions": [],
        "confirmedByLawyer": True,
        "confirmationNote": "Baseline confirmed",
    }
    activation.update(overrides)
    return activation


def test_shared_runtime_and_contract_are_byte_identical() -> None:
    shared_files = [
        "scripts/shared/__init__.py",
        "scripts/shared/playbook_runtime.py",
        "references/playbook-engine-contract.md",
        "references/pdf-intake.md",
        "schemas/playbook-engine.schema.json",
    ]
    for relative in shared_files:
        assert (BUILDER / relative).read_bytes() == (REVIEWER / relative).read_bytes()
    assert (BUILDER / "schemas/playbook-engine.schema.json").read_bytes() == (
        ROOT / "packages/contracts/schemas/playbook-engine.schema.json"
    ).read_bytes()


def test_manifest_has_stable_source_and_element_ids(tmp_path: Path) -> None:
    source = tmp_path / "template.txt"
    source.write_text("1 Liability\n\nThe cap is annual fees.\n", encoding="utf-8")
    roles = {source.name: "approved-template"}
    first = build_source_manifest([source], tmp_path, roles)
    second = build_source_manifest([source], tmp_path, roles)
    first_document = first["documents"][0]
    second_document = second["documents"][0]
    assert first_document["documentId"] == second_document["documentId"]
    assert [item["elementId"] for item in first_document["elements"]] == [
        item["elementId"] for item in second_document["elements"]
    ]
    assert first["manifestSha256"] == second["manifestSha256"]
    assert first_document["readability"] == "readable"


def test_manifest_indexes_defined_terms_with_source_anchors(tmp_path: Path) -> None:
    source = tmp_path / "template.txt"
    source.write_text(
        '1 Definitions\n\n"Fees" means charges paid or payable under this Agreement.\n',
        encoding="utf-8",
    )
    manifest = build_source_manifest(
        [source], tmp_path, {source.name: "approved-template"}
    )
    document = manifest["documents"][0]
    term = document["definedTerms"][0]
    assert term["term"] == "Fees"
    assert term["normalizedTerm"] == "fees"
    assert term["definitionText"] == (
        '"Fees" means charges paid or payable under this Agreement.'
    )
    assert term["documentSha256"] == document["sha256"]
    assert term["elementId"] == document["elements"][1]["elementId"]


def test_manifest_rejects_sources_outside_boundary(tmp_path: Path) -> None:
    boundary = tmp_path / "inside"
    boundary.mkdir()
    source = tmp_path / "outside.txt"
    source.write_text("Outside", encoding="utf-8")
    with pytest.raises(PlaybookError, match="outside the declared input boundary"):
        build_source_manifest([source], boundary)


def test_playbook_validation_rejects_duplicate_ids_and_bad_ranks() -> None:
    playbook = _playbook()
    duplicate = copy.deepcopy(playbook["issues"][0])
    duplicate["basePosition"]["fallbacks"][0]["rank"] = 2
    playbook["issues"].append(duplicate)
    errors = validate_playbook(playbook)
    assert "duplicate issueId: liability-cap" in errors
    assert "liability-cap: fallback ranks must be consecutive from 1" in errors


def test_suggested_lens_does_not_change_baseline() -> None:
    stance = compile_effective_stance(
        _playbook(),
        _activation(suggestedLenses=["regulated-fs"]),
    )
    assert stance["status"] == "ready"
    assert stance["activatedLenses"] == []
    assert stance["suggestedLenses"] == ["regulated-fs"]
    assert stance["issues"][0]["position"]["summary"] == "Annual fees cap"


def test_explicitly_activated_lens_changes_stance() -> None:
    stance = compile_effective_stance(
        _playbook(),
        _activation(activatedLenses=["regulated-fs"]),
    )
    position = stance["issues"][0]["position"]
    assert stance["status"] == "ready"
    assert position["summary"] == "Annual fees cap with data super-cap"
    assert position["preferred"]["summary"] == "100% fees plus data super-cap"


def test_lens_activation_requires_lawyer_confirmation() -> None:
    with pytest.raises(PlaybookError, match="Gate 1 confirmation is required"):
        compile_effective_stance(
            _playbook(),
            _activation(
                activatedLenses=["regulated-fs"],
                confirmedByLawyer=False,
            ),
        )


def test_lens_activation_rejects_duplicate_lenses() -> None:
    with pytest.raises(PlaybookError, match="must not contain duplicates"):
        compile_effective_stance(
            _playbook(),
            _activation(activatedLenses=["regulated-fs", "regulated-fs"]),
        )


def test_candidate_lens_cannot_be_suggested_or_activated() -> None:
    playbook = _playbook()
    playbook["matterLenses"][0]["status"] = "candidate"
    with pytest.raises(PlaybookError, match="Candidate Matter Lens is non-operative"):
        compile_effective_stance(
            playbook,
            _activation(suggestedLenses=["regulated-fs"]),
        )


def test_incompatible_overlapping_lenses_block_stance() -> None:
    stance = compile_effective_stance(
        _playbook(),
        _activation(activatedLenses=["regulated-fs", "high-leverage-customer"]),
    )
    assert stance["status"] == "blocked"
    assert stance["conflicts"][0]["field"] == "summary"
    assert stance["conflicts"][0]["sources"] == [
        "regulated-fs",
        "high-leverage-customer",
    ]


@pytest.mark.parametrize(
    ("original", "proposed"),
    [
        ("The cap is annual fees.", "The cap is 150% of annual fees."),
        ("Line one\nLine two", "Line one\nNew line two"),
        ("delete everything", "replace everything"),
        ("", "New protection."),
    ],
)
def test_markup_reconstructs_both_exact_texts(original: str, proposed: str) -> None:
    segments = build_markup_segments(original, proposed)
    assert reconstruct_markup(segments) == (original, proposed)


def test_markup_rejects_non_object_segment() -> None:
    with pytest.raises(PlaybookError, match="markup segment must be an object"):
        reconstruct_markup(cast(Any, ["not-an-object"]))


def test_term_map_adapts_equivalent_house_term_to_counterparty_term(
    tmp_path: Path,
) -> None:
    house_source = tmp_path / "house.txt"
    contract_source = tmp_path / "contract.txt"
    house_source.write_text(
        '"Fees" means charges paid or payable under this Agreement.',
        encoding="utf-8",
    )
    contract_source.write_text(
        '"Charges" means charges paid or payable under this Agreement.',
        encoding="utf-8",
    )
    house_manifest = build_source_manifest(
        [house_source], tmp_path, {house_source.name: "approved-template"}
    )
    contract_manifest = build_source_manifest(
        [contract_source], tmp_path, {contract_source.name: "contract-under-review"}
    )
    playbook = _playbook()
    playbook["sourceManifestSha256"] = house_manifest["manifestSha256"]
    term_map = build_term_map_skeleton(
        house_manifest,
        contract_manifest,
        playbook,
        "term-run",
    )
    entry = term_map["entries"][0]
    entry.update(
        {
            "contractDefinition": contract_manifest["documents"][0]["definedTerms"][0],
            "relation": "equivalent",
            "decisionBasis": "model-cited",
            "draftingAction": "use-contract-term",
            "rationale": "Both definitions cover the same payment obligation.",
            "lawyerReview": "pending",
        }
    )
    assert validate_term_map(term_map) == []
    adapted = adapt_drafting_to_term_map(
        "Liability is capped at annual Fees, not FeesAdjustment amounts.",
        term_map,
    )
    assert adapted["status"] == "ready"
    assert adapted["adaptedProposedText"] == (
        "Liability is capped at annual Charges, not FeesAdjustment amounts."
    )
    assert adapted["substitutions"] == [
        {"houseTerm": "Fees", "contractTerm": "Charges"}
    ]


def test_term_map_hard_stops_scope_difference(tmp_path: Path) -> None:
    house_source = tmp_path / "house.txt"
    contract_source = tmp_path / "contract.txt"
    house_source.write_text(
        '"Fees" means all charges paid or payable under this Agreement.',
        encoding="utf-8",
    )
    contract_source.write_text(
        '"Fees" means fixed subscription charges paid in the last month.',
        encoding="utf-8",
    )
    house_manifest = build_source_manifest(
        [house_source], tmp_path, {house_source.name: "approved-template"}
    )
    contract_manifest = build_source_manifest(
        [contract_source], tmp_path, {contract_source.name: "contract-under-review"}
    )
    playbook = _playbook()
    playbook["sourceManifestSha256"] = house_manifest["manifestSha256"]
    term_map = build_term_map_skeleton(
        house_manifest,
        contract_manifest,
        playbook,
        "term-run",
    )
    entry = term_map["entries"][0]
    assert entry["relation"] == "unresolved"
    entry.update(
        {
            "relation": "defined-differently",
            "decisionBasis": "model-cited",
            "draftingAction": "hard-stop",
            "rationale": "The counterparty definition excludes variable charges.",
            "lawyerReview": "pending",
        }
    )
    assert validate_term_map(term_map) == []
    adapted = adapt_drafting_to_term_map("The cap is annual Fees.", term_map)
    assert adapted["status"] == "blocked"
    assert adapted["hardStops"][0]["houseTerm"] == "Fees"


def test_term_map_surfaces_missing_definition_insertion(tmp_path: Path) -> None:
    house_source = tmp_path / "house.txt"
    contract_source = tmp_path / "contract.txt"
    house_source.write_text(
        '"Fees" means charges paid or payable under this Agreement.',
        encoding="utf-8",
    )
    contract_source.write_text("12 Liability", encoding="utf-8")
    house_manifest = build_source_manifest(
        [house_source], tmp_path, {house_source.name: "approved-template"}
    )
    contract_manifest = build_source_manifest(
        [contract_source], tmp_path, {contract_source.name: "contract-under-review"}
    )
    playbook = _playbook()
    playbook["sourceManifestSha256"] = house_manifest["manifestSha256"]
    term_map = build_term_map_skeleton(
        house_manifest,
        contract_manifest,
        playbook,
        "term-run",
    )
    entry = term_map["entries"][0]
    entry.update(
        {
            "relation": "undefined",
            "decisionBasis": "model-cited",
            "draftingAction": "insert-definition",
            "rationale": "No definition or equivalent term appears in the package.",
            "lawyerReview": "pending",
        }
    )
    assert validate_term_map(term_map) == []
    adapted = adapt_drafting_to_term_map("The cap is annual Fees.", term_map)
    assert adapted["status"] == "ready"
    assert adapted["definitionInsertions"][0]["houseTerm"] == "Fees"


def test_issue_validation_checks_source_anchor_and_markup(tmp_path: Path) -> None:
    source = tmp_path / "contract.txt"
    source_text = "12 Liability is capped at annual Fees."
    source.write_text(source_text, encoding="utf-8")
    manifest = build_source_manifest(
        [source],
        tmp_path,
        {source.name: "contract-under-review"},
    )
    document = manifest["documents"][0]
    element = document["elements"][0]
    original = "Liability is capped at annual Fees."
    proposed = "Liability is capped at 150% of annual Fees."
    issues = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "run-1",
        "sourceManifestSha256": manifest["manifestSha256"],
        "playbookId": "saas-customer",
        "playbookVersion": "1.0.0",
        "effectiveStanceSha256": "c" * 64,
        "issues": [
            {
                "issueId": "review-liability-cap",
                "playbookIssueId": "liability-cap",
                "classification": "deviation",
                "materiality": "high",
                "documentSha256": document["sha256"],
                "elementId": element["elementId"],
                "clauseRef": "12",
                "originalText": original,
                "proposedText": proposed,
                "markupSegments": build_markup_segments(original, proposed),
                "draftingProvenance": "approved-playbook",
                "rationale": "The draft is below the approved fallback.",
                "lawyerReview": "pending",
            }
        ],
    }
    assert validate_issues_list(issues, source_text_index(manifest)) == []
    binding_errors = validate_issues_list(
        issues,
        source_text_index(manifest),
        "d" * 64,
    )
    assert "issues list is bound to a different source manifest" in binding_errors
    issues["issues"][0]["originalText"] = "Stale wording"
    errors = validate_issues_list(issues, source_text_index(manifest))
    assert any("does not reconstruct exact originalText" in error for error in errors)
    assert any("not present at the source anchor" in error for error in errors)


def test_html_renderer_escapes_contract_text() -> None:
    original = "Supplier may <script>alert(1)</script>."
    proposed = "Supplier must comply."
    issues = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "run-html",
        "sourceManifestSha256": "a" * 64,
        "playbookId": "saas-customer",
        "playbookVersion": "1.0.0",
        "effectiveStanceSha256": "b" * 64,
        "issues": [
            {
                "issueId": "review-security",
                "playbookIssueId": "security",
                "classification": "deviation",
                "materiality": "high",
                "documentSha256": "c" * 64,
                "elementId": "el-security",
                "clauseRef": "4",
                "originalText": original,
                "proposedText": proposed,
                "markupSegments": build_markup_segments(original, proposed),
                "draftingProvenance": "candidate-drafting",
                "rationale": "The clause is permissive.",
                "lawyerReview": "pending",
            }
        ],
    }
    rendered = render_issues_html(issues)
    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered


def test_malformed_issue_is_rejected_before_rendering() -> None:
    issues = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "run-malformed",
        "sourceManifestSha256": "a" * 64,
        "playbookId": "saas-customer",
        "playbookVersion": "1.0.0",
        "effectiveStanceSha256": "b" * 64,
        "issues": [{"markupSegments": []}],
    }
    errors = validate_issues_list(issues)
    assert "issues[0]: issueId must be a non-empty string" in errors
    with pytest.raises(PlaybookError, match="issueId must be a non-empty string"):
        render_issues_html(issues)


def test_coverage_receipt_requires_all_three_reconciliations() -> None:
    payload = {
        "runId": "run-1",
        "documents": {"expected": 2, "completed": 1, "parked": 1, "unreadable": 0},
        "elements": {"expected": 8, "completed": 7, "parked": 1, "unreadable": 0},
        "rules": {"expected": 4, "evaluated": 3, "notApplicable": 1, "blocked": 0},
    }
    assert build_coverage_receipt(payload)["reconciled"] is True
    payload["rules"]["evaluated"] = 2
    receipt = build_coverage_receipt(payload)
    assert receipt["reconciled"] is False
    assert receipt["errors"] == ["rules: expected 4 does not equal accounted 3"]


def test_coverage_receipt_rejects_boolean_counts() -> None:
    payload = {
        "runId": "run-1",
        "documents": {"expected": True, "completed": 1, "parked": 0, "unreadable": 0},
        "elements": {"expected": 0, "completed": 0, "parked": 0, "unreadable": 0},
        "rules": {"expected": 0, "evaluated": 0, "notApplicable": 0, "blocked": 0},
    }
    receipt = build_coverage_receipt(payload)
    assert receipt["reconciled"] is False
    assert receipt["errors"][0] == "documents: counts must be integers"


def test_coverage_receipt_rejects_non_object_counts() -> None:
    payload = {
        "runId": "run-1",
        "documents": [],
        "elements": {"expected": 0, "completed": 0, "parked": 0, "unreadable": 0},
        "rules": {"expected": 0, "evaluated": 0, "notApplicable": 0, "blocked": 0},
    }
    receipt = build_coverage_receipt(payload)
    assert receipt["reconciled"] is False
    assert receipt["errors"][0] == "documents: counts must be an object"


def test_build_receipt_rejects_stale_or_mismatched_manifest(tmp_path: Path) -> None:
    source = tmp_path / "template.txt"
    source.write_text("Approved wording.", encoding="utf-8")
    manifest = build_source_manifest(
        [source], tmp_path, {source.name: "approved-template"}
    )
    playbook = _playbook()

    mismatched = build_receipt(playbook, manifest)
    assert (
        "playbook is bound to a different source manifest"
        in mismatched["validationErrors"]
    )

    playbook["sourceManifestSha256"] = manifest["manifestSha256"]
    manifest["documents"][0]["readability"] = "partial"
    stale = build_receipt(playbook, manifest)
    assert (
        "manifestSha256 does not match the manifest contents"
        in stale["validationErrors"]
    )


def test_command_line_workflow_end_to_end(tmp_path: Path) -> None:
    builder_cli = BUILDER / "scripts/playbook_builder.py"
    reviewer_cli = REVIEWER / "scripts/playbook_review.py"

    def run_cli(script: Path, *arguments: object) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(script), *(str(argument) for argument in arguments)],
            capture_output=True,
            check=False,
            encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr or result.stdout
        return result

    source = tmp_path / "supplier-draft.txt"
    source.write_text(
        '"Fees" means charges paid or payable under this Agreement.\n\n'
        "12 Liability is capped at annual Fees.\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "source-manifest.json"
    run_cli(
        builder_cli,
        "manifest",
        source,
        "--boundary",
        tmp_path,
        "--role",
        f"{source.name}=approved-template",
        "--out",
        manifest_path,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    document = manifest["documents"][0]
    assert document["sourceRole"] == "approved-template"
    assert document["readability"] == "readable"

    playbook = _playbook()
    playbook["sourceManifestSha256"] = manifest["manifestSha256"]
    playbook["issues"][0]["provenance"][0]["documentSha256"] = document["sha256"]
    playbook["issues"][0]["provenance"][0]["elementId"] = document["elements"][1][
        "elementId"
    ]
    playbook["issues"][0]["provenance"][0]["exactText"] = (
        "12 Liability is capped at annual Fees."
    )
    playbook_path = tmp_path / "playbook.json"
    playbook_path.write_text(json.dumps(playbook), encoding="utf-8")
    run_cli(builder_cli, "validate", playbook_path)

    build_receipt_path = tmp_path / "build-receipt.json"
    run_cli(
        builder_cli,
        "receipt",
        manifest_path,
        playbook_path,
        "--out",
        build_receipt_path,
    )
    build_receipt = json.loads(build_receipt_path.read_text(encoding="utf-8"))
    assert build_receipt["validationErrors"] == []
    assert build_receipt["approvedIssueCount"] == 1

    playbook_html_path = tmp_path / "playbook.html"
    run_cli(builder_cli, "render", playbook_path, "--out", playbook_html_path)
    assert "Customer SaaS playbook" in playbook_html_path.read_text(encoding="utf-8")

    activation = _activation(suggestedLenses=["regulated-fs"])
    activation_path = tmp_path / "activation.json"
    activation_path.write_text(json.dumps(activation), encoding="utf-8")
    stance_path = tmp_path / "effective-stance.json"
    run_cli(
        reviewer_cli,
        "compile-stance",
        playbook_path,
        activation_path,
        "--out",
        stance_path,
    )
    stance = json.loads(stance_path.read_text(encoding="utf-8"))
    assert stance["activatedLenses"] == []
    assert stance["suggestedLenses"] == ["regulated-fs"]
    assert stance["issues"][0]["position"]["summary"] == "Annual fees cap"

    term_map_path = tmp_path / "term-map.json"
    run_cli(
        reviewer_cli,
        "term-map",
        manifest_path,
        manifest_path,
        playbook_path,
        "--run-id",
        "cli-run",
        "--out",
        term_map_path,
    )
    run_cli(reviewer_cli, "validate-term-map", term_map_path)
    term_map = json.loads(term_map_path.read_text(encoding="utf-8"))
    assert term_map["entries"][0]["relation"] == "exact"

    original = "Liability is capped at annual Fees."
    proposed = "Liability is capped at 150% of Fees."
    original_path = tmp_path / "original.txt"
    proposed_path = tmp_path / "proposed.txt"
    original_path.write_text(original, encoding="utf-8")
    proposed_path.write_text(proposed, encoding="utf-8")
    adapted_path = tmp_path / "adapted-drafting.json"
    run_cli(
        reviewer_cli,
        "adapt-drafting",
        proposed_path,
        term_map_path,
        "--out",
        adapted_path,
    )
    adapted = json.loads(adapted_path.read_text(encoding="utf-8"))
    assert adapted["adaptedProposedText"] == proposed
    markup_path = tmp_path / "markup.json"
    run_cli(
        reviewer_cli,
        "markup",
        original_path,
        proposed_path,
        "--out",
        markup_path,
    )
    markup = json.loads(markup_path.read_text(encoding="utf-8"))["markupSegments"]

    issues = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "cli-run",
        "sourceManifestSha256": manifest["manifestSha256"],
        "playbookId": playbook["playbookId"],
        "playbookVersion": playbook["version"],
        "effectiveStanceSha256": stance["stanceSha256"],
        "issues": [
            {
                "issueId": "review-liability-cap",
                "playbookIssueId": "liability-cap",
                "classification": "deviation",
                "materiality": "high",
                "documentSha256": document["sha256"],
                "elementId": document["elements"][1]["elementId"],
                "clauseRef": "12",
                "originalText": original,
                "proposedText": proposed,
                "markupSegments": markup,
                "draftingProvenance": "approved-playbook",
                "rationale": "The draft is below the approved fallback.",
                "lawyerReview": "pending",
            }
        ],
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(issues), encoding="utf-8")
    run_cli(
        reviewer_cli,
        "validate-issues",
        issues_path,
        "--manifest",
        manifest_path,
    )

    html_path = tmp_path / "issues.html"
    run_cli(reviewer_cli, "render-issues", issues_path, "--out", html_path)
    rendered = html_path.read_text(encoding="utf-8")
    assert "Suggested markup" in rendered
    assert "<del>" in rendered
    assert "<ins>" in rendered

    counts = {
        "runId": "cli-run",
        "documents": {
            "expected": 1,
            "completed": 1,
            "parked": 0,
            "unreadable": 0,
        },
        "elements": {
            "expected": 1,
            "completed": 1,
            "parked": 0,
            "unreadable": 0,
        },
        "rules": {
            "expected": 1,
            "evaluated": 1,
            "notApplicable": 0,
            "blocked": 0,
        },
    }
    counts_path = tmp_path / "counts.json"
    counts_path.write_text(json.dumps(counts), encoding="utf-8")
    coverage_path = tmp_path / "coverage.json"
    run_cli(
        reviewer_cli,
        "coverage",
        counts_path,
        "--out",
        coverage_path,
    )
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    assert coverage["reconciled"] is True

    # CLI markup-issues
    issues_no_markup = copy.deepcopy(issues)
    cast(dict[str, Any], issues_no_markup["issues"][0]).pop("markupSegments", None)
    no_markup_path = tmp_path / "issues-no-markup.json"
    no_markup_path.write_text(json.dumps(issues_no_markup), encoding="utf-8")
    run_cli(reviewer_cli, "markup-issues", no_markup_path)
    reloaded = json.loads(no_markup_path.read_text(encoding="utf-8"))
    assert reloaded["issues"][0]["markupSegments"] == markup

    # CLI review-receipt
    review_receipt_path = tmp_path / "review-receipt.json"
    run_cli(
        reviewer_cli,
        "review-receipt",
        issues_path,
        "--coverage",
        coverage_path,
        "--out",
        review_receipt_path,
    )
    review_receipt = json.loads(review_receipt_path.read_text(encoding="utf-8"))
    assert review_receipt["artifactType"] == "review-receipt"
    assert review_receipt["issuesCount"] == 1
    assert review_receipt["classificationCounts"]["deviation"] == 1
    assert review_receipt["reconciled"] is True


def test_defined_term_extraction_markdown_bullets(tmp_path: Path) -> None:
    content = """# Section 1: Definitions

1.1 In this Agreement, unless the context otherwise requires:
- **"Authorized Users"**: means employees and contractors of Customer authorised to use the Cloud Service.
* **"Confidential Information"** shall mean all non-public, proprietary information disclosed by one party to the other.
- "Effective Date" has the meaning given in the Order Form.
- "Third-Party Services" means any products or services provided by third parties.
"""
    doc_path = tmp_path / "definitions.md"
    doc_path.write_text(content, encoding="utf-8")
    manifest = build_source_manifest(
        [doc_path], tmp_path, {doc_path.name: "approved-template"}
    )
    terms = {
        t["term"]: t["definitionText"] for t in manifest["documents"][0]["definedTerms"]
    }
    assert "Authorized Users" in terms
    assert "Confidential Information" in terms
    assert "Effective Date" in terms
    assert "Third-Party Services" in terms
    assert "employees and contractors" in terms["Authorized Users"]


def test_defined_term_extraction_docx_table(tmp_path: Path) -> None:
    docx_path = tmp_path / "definitions_table.docx"
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        "<w:tbl>"
        "<w:tr>"
        "<w:tc><w:p><w:r><w:t>Affiliate</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>means any entity that directly or indirectly controls, is controlled by, or is under common control with the subject entity.</w:t></w:r></w:p></w:tc>"
        "</w:tr>"
        "<w:tr>"
        "<w:tc><w:p><w:r><w:t>Fees</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>means all fees and charges payable by Customer under this Agreement.</w:t></w:r></w:p></w:tc>"
        "</w:tr>"
        "</w:tbl>"
        "</w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(docx_path, "w") as zf:
        zf.writestr("word/document.xml", doc_xml.encode("utf-8"))

    manifest = build_source_manifest(
        [docx_path], tmp_path, {docx_path.name: "approved-template"}
    )
    terms = {
        t["term"]: t["definitionText"] for t in manifest["documents"][0]["definedTerms"]
    }
    assert "Affiliate" in terms
    assert "Fees" in terms
    assert "directly or indirectly controls" in terms["Affiliate"]


def test_validate_issues_list_clause_deletion() -> None:
    issues_list = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "del-run",
        "sourceManifestSha256": "a" * 64,
        "playbookId": "saas-customer",
        "playbookVersion": "1.0.0",
        "effectiveStanceSha256": "b" * 64,
        "issues": [
            {
                "issueId": "del-issue-1",
                "playbookIssueId": "unwanted-clause",
                "classification": "deviation",
                "materiality": "medium",
                "documentSha256": "c" * 64,
                "elementId": "el-1",
                "clauseRef": "5.2",
                "originalText": "This clause is deleted entirely.",
                "proposedText": "",
                "markupSegments": [
                    {"op": "delete", "text": "This clause is deleted entirely."}
                ],
                "draftingProvenance": "approved-playbook",
                "rationale": "Delete obsolete clause.",
                "lawyerReview": "pending",
            }
        ],
    }
    errors = validate_issues_list(issues_list)
    assert errors == []


def test_multiline_anchor_whitespace_tolerance() -> None:
    doc_sha = "c" * 64
    source_index = {
        (
            doc_sha,
            "el-1",
        ): "Clause 10. Liability is capped\n    at 100% of annual fees paid."
    }
    issues_list = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "whitespace-run",
        "sourceManifestSha256": "a" * 64,
        "playbookId": "saas-customer",
        "playbookVersion": "1.0.0",
        "effectiveStanceSha256": "b" * 64,
        "issues": [
            {
                "issueId": "anchor-issue-1",
                "playbookIssueId": "liability-cap",
                "classification": "deviation",
                "materiality": "high",
                "documentSha256": doc_sha,
                "elementId": "el-1",
                "clauseRef": "10",
                "originalText": "Liability is capped\n  at 100% of annual fees paid.",
                "proposedText": "Liability is capped\n  at 150% of annual fees paid.",
                "markupSegments": [
                    {"op": "equal", "text": "Liability is capped\n  at "},
                    {"op": "delete", "text": "100%"},
                    {"op": "insert", "text": "150%"},
                    {"op": "equal", "text": " of annual fees paid."},
                ],
                "draftingProvenance": "approved-playbook",
                "rationale": "Commercial cap adjustment",
                "lawyerReview": "pending",
            }
        ],
    }
    errors = validate_issues_list(issues_list, source_index=source_index)
    assert errors == []


def test_adapt_drafting_hard_stop_rollback() -> None:
    term_map = {
        "artifactType": "term-map",
        "schemaVersion": "1.0",
        "runId": "run-1",
        "playbookId": "pb-1",
        "playbookVersion": "1.0",
        "playbookSourceManifestSha256": "a" * 64,
        "contractSourceManifestSha256": "b" * 64,
        "entries": [
            {
                "entryId": "entry-1",
                "houseDefinition": {
                    "termId": "t1",
                    "term": "Data Controller",
                    "normalizedTerm": "data controller",
                    "definitionText": "means data controller under GDPR",
                    "documentSha256": "a" * 64,
                    "elementId": "el-1",
                    "clauseRef": "1",
                },
                "contractDefinition": {
                    "termId": "c1",
                    "term": "Business",
                    "normalizedTerm": "business",
                    "definitionText": "means business entity under CCPA",
                    "documentSha256": "b" * 64,
                    "elementId": "el-2",
                    "clauseRef": "2",
                },
                "relation": "defined-differently",
                "decisionBasis": "model-cited",
                "draftingAction": "hard-stop",
                "rationale": "GDPR versus CCPA scope mismatch",
                "lawyerReview": "pending",
            }
        ],
    }
    orig_text = "The Data Controller shall notify Customer without undue delay."
    result = adapt_drafting_to_term_map(orig_text, term_map)
    assert result["status"] == "blocked"
    assert len(result["hardStops"]) == 1
    assert result["adaptedProposedText"] == orig_text
    assert result["substitutions"] == []


def test_render_playbook_html() -> None:
    pb = _playbook()
    html_out = render_playbook_html(pb)
    assert "<!doctype html>" in html_out
    assert "Customer SaaS playbook" in html_out
    assert "liability-cap" in html_out
    assert "Matter Lenses" in html_out
    assert "Regulated financial services" in html_out


def test_build_review_receipt_and_populate_markup() -> None:
    issues_list = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "run-test",
        "playbookId": "pb-test",
        "playbookVersion": "1.0",
        "sourceManifestSha256": "a" * 64,
        "effectiveStanceSha256": "b" * 64,
        "issues": [
            {
                "issueId": "iss-1",
                "playbookIssueId": "pb-iss-1",
                "classification": "deviation",
                "materiality": "high",
                "documentSha256": "c" * 64,
                "elementId": "el-1",
                "clauseRef": "1.1",
                "originalText": "Supplier liability is capped at £100.",
                "proposedText": "Supplier liability is capped at £1,000.",
                "markupSegments": [],
                "draftingProvenance": "approved-playbook",
                "rationale": "Increase cap",
                "lawyerReview": "pending",
            }
        ],
    }
    populated = populate_issues_markup(issues_list)
    assert len(populated["issues"][0]["markupSegments"]) > 0
    assert any(s["op"] == "delete" for s in populated["issues"][0]["markupSegments"])
    assert any(s["op"] == "insert" for s in populated["issues"][0]["markupSegments"])

    receipt = build_review_receipt(populated)
    assert receipt["artifactType"] == "review-receipt"
    assert receipt["issuesCount"] == 1
    assert receipt["classificationCounts"]["deviation"] == 1
    assert receipt["reconciled"] is False

    receipt_with_cov = build_review_receipt(populated, {"reconciled": True})
    assert receipt_with_cov["reconciled"] is True


def test_validate_playbook_allows_alphanumeric_and_uppercase_ids() -> None:
    pb = _playbook()
    pb["playbookId"] = "PB-SUBSTRATE-CLOUD-2026"
    pb["issues"][0]["issueId"] = "LIAB-001"
    pb["matterLenses"][0]["lensId"] = "LENS_FS"
    pb["matterLenses"][0]["adjustments"][0]["issueId"] = "LIAB-001"
    pb["matterLenses"][1]["adjustments"][0]["issueId"] = "LIAB-001"
    errors = validate_playbook(pb)
    assert errors == []


def test_digital_fast_path_docx_intake(tmp_path: Path) -> None:
    docx_path = tmp_path / "contract.docx"
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        "<w:body>\n"
        "<w:p><w:r><w:t>1. Liability. Supplier liability is capped at annual fees.</w:t></w:r></w:p>\n"
        "</w:body>\n"
        "</w:document>"
    )
    with zipfile.ZipFile(docx_path, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)

    manifest = build_source_manifest(
        [docx_path], tmp_path, {docx_path.name: "contract-under-review"}
    )
    doc = manifest["documents"][0]
    assert doc["readability"] == "readable"
    assert doc["pages"] == []
    assert len(doc["elements"]) == 1
    assert "Supplier liability is capped" in doc["elements"][0]["sourceText"]


def test_playbook_registry_lifecycle_and_picker(tmp_path: Path) -> None:
    pb = _playbook()
    pkg_dir = tmp_path / "outputs" / "playbook-package"
    pkg_dir.mkdir(parents=True)
    registry_file = tmp_path / "playbook-registry.json"

    reg = register_playbook(pb, pkg_dir, registry_file)
    assert reg["artifactType"] == "playbook-registry"
    assert len(reg["playbooks"]) == 1
    entry = reg["playbooks"][0]
    assert entry["playbookId"] == pb["playbookId"]
    assert entry["issueCount"] == 1
    assert validate_playbook_registry(reg) == []

    # Updating same playbook updates entry in place
    pb["issues"].append(copy.deepcopy(pb["issues"][0]))
    pb["issues"][1]["issueId"] = "second-issue"
    reg2 = register_playbook(pb, pkg_dir, registry_file)
    assert len(reg2["playbooks"]) == 1
    assert reg2["playbooks"][0]["issueCount"] == 2

    # Discover and picker
    discovered = list_registered_playbooks(registry_file)
    assert len(discovered) == 1
    picker = format_playbook_picker(discovered)
    assert "Available Approved Playbooks:" in picker
    assert pb["playbookId"] in picker
    assert "2 issues" in picker

    # Find registry by searching upward
    found = find_playbook_registry(pkg_dir)
    assert found == registry_file


def test_render_issues_docx_landscape_openxml(tmp_path: Path) -> None:
    issues = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "run-docx",
        "sourceManifestSha256": "a" * 64,
        "playbookId": "saas-customer",
        "playbookVersion": "1.0.0",
        "effectiveStanceSha256": "b" * 64,
        "issues": [
            {
                "issueId": "review-liability-cap",
                "playbookIssueId": "liability-cap",
                "classification": "deviation",
                "materiality": "high",
                "documentSha256": "c" * 64,
                "elementId": "el-liability",
                "clauseRef": "12.1",
                "originalText": "Liability is capped at 50% of annual fees.",
                "proposedText": "Liability is capped at 100% of annual fees.",
                "markupSegments": build_markup_segments(
                    "Liability is capped at 50% of annual fees.",
                    "Liability is capped at 100% of annual fees.",
                ),
                "draftingProvenance": "approved-playbook",
                "rationale": "Cap must reflect annual fees baseline.",
                "lawyerReview": "pending",
            }
        ],
    }
    out_docx = tmp_path / "issues-matrix.docx"
    render_issues_docx(issues, out_docx, playbook=_playbook())
    assert out_docx.is_file()

    with zipfile.ZipFile(out_docx) as zf:
        namelist = zf.namelist()
        assert "[Content_Types].xml" in namelist
        assert "word/document.xml" in namelist
        assert "_rels/.rels" in namelist
        assert "word/_rels/document.xml.rels" in namelist

        doc_xml = zf.read("word/document.xml").decode("utf-8")
        assert 'w:orient="landscape"' in doc_xml
        assert 'w:type="pct"' in doc_xml
        assert "<w:tblHeader/>" in doc_xml
        assert "<w:cantSplit/>" in doc_xml
        assert 'w:fill="1B365D"' in doc_xml
        assert 'w:fill="FADBD8"' in doc_xml
        assert "<w:strike/>" in doc_xml
        assert '<w:u w:val="single"/>' in doc_xml
        assert "review-liability-cap" in doc_xml
        assert "Clause 12.1" in doc_xml
        assert "Cap must reflect annual fees baseline." in doc_xml

        # ElementTree parses with zero XML errors
        from xml.etree import ElementTree as ET

        root = ET.fromstring(doc_xml)
        assert root is not None


def test_cli_register_and_export_docx_and_discover(tmp_path: Path) -> None:
    builder_cli = BUILDER / "scripts/playbook_builder.py"
    reviewer_cli = REVIEWER / "scripts/playbook_review.py"

    def run_cli(script: Path, *arguments: object) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(script), *(str(arg) for arg in arguments)],
            capture_output=True,
            check=False,
            encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr or result.stdout
        return result

    pb = _playbook()
    pb_file = tmp_path / "playbook.json"
    pb_file.write_text(json.dumps(pb), encoding="utf-8")
    reg_file = tmp_path / "playbook-registry.json"

    # 1. builder register command
    run_cli(builder_cli, "register", pb_file, "--registry", reg_file)
    assert reg_file.is_file()

    # 2. reviewer discover-playbooks command
    res = run_cli(reviewer_cli, "discover-playbooks", "--registry", reg_file)
    assert pb["playbookId"] in res.stdout
    assert "Available Approved Playbooks:" in res.stdout

    # 3. reviewer export-docx command
    issues = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "cli-test-run",
        "sourceManifestSha256": "a" * 64,
        "playbookId": pb["playbookId"],
        "playbookVersion": pb["version"],
        "effectiveStanceSha256": "b" * 64,
        "issues": [
            {
                "issueId": "cli-issue-1",
                "playbookIssueId": "liability-cap",
                "classification": "deviation",
                "materiality": "high",
                "documentSha256": "c" * 64,
                "elementId": "el-1",
                "clauseRef": "5",
                "originalText": "Old cap.",
                "proposedText": "New cap.",
                "markupSegments": [
                    {"op": "delete", "text": "Old "},
                    {"op": "insert", "text": "New "},
                    {"op": "equal", "text": "cap."},
                ],
                "draftingProvenance": "approved-playbook",
                "rationale": "Commercial fallback.",
                "lawyerReview": "pending",
            }
        ],
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(issues), encoding="utf-8")
    docx_out = tmp_path / "output.docx"
    run_cli(
        reviewer_cli,
        "export-docx",
        issues_path,
        "--playbook",
        pb_file,
        "--out",
        docx_out,
    )
    assert docx_out.is_file()
    with zipfile.ZipFile(docx_out) as zf:
        assert "word/document.xml" in zf.namelist()


def _fake_pdfplumber(page_texts: list[str | None]) -> types.SimpleNamespace:
    class _Page:
        def __init__(self, text: str | None) -> None:
            self._text = text

        def extract_text(self) -> str | None:
            if self._text is None:
                raise RuntimeError("mid-document extraction failure")
            return self._text

    class _Pdf:
        def __init__(self) -> None:
            self.pages = [_Page(text) for text in page_texts]

        def __enter__(self) -> _Pdf:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    return types.SimpleNamespace(open=lambda _path: _Pdf())


def test_pdf_extraction_error_is_not_presented_as_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "contract.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setitem(
        sys.modules,
        "pdfplumber",
        _fake_pdfplumber(["Page one text.", None, "Page three text."]),
    )

    manifest = build_source_manifest(
        [pdf_path], tmp_path, {pdf_path.name: "contract-under-review"}
    )
    document = manifest["documents"][0]
    assert document["readability"] == "partial"
    assert document["readability"] != "readable"
    assert any(
        warning.startswith("pdf-extraction-error") for warning in document["warnings"]
    )


def test_pdf_clean_extraction_stays_fast_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "contract.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setitem(
        sys.modules,
        "pdfplumber",
        _fake_pdfplumber(["Page one text.", "Page two text."]),
    )

    manifest = build_source_manifest(
        [pdf_path], tmp_path, {pdf_path.name: "contract-under-review"}
    )
    document = manifest["documents"][0]
    assert document["readability"] == "readable"
    assert all(page["readingMethod"] == "native-text" for page in document["pages"])
    assert not any(
        warning.startswith("pdf-extraction-error") for warning in document["warnings"]
    )


def _severity_issue(issue_id: str, materiality: str, clause: str) -> dict:
    original = f"Original wording for {issue_id}."
    proposed = f"Proposed wording for {issue_id}."
    return {
        "issueId": issue_id,
        "playbookIssueId": issue_id,
        "classification": "deviation",
        "materiality": materiality,
        "documentSha256": "c" * 64,
        "elementId": f"el-{issue_id}",
        "clauseRef": clause,
        "originalText": original,
        "proposedText": proposed,
        "markupSegments": build_markup_segments(original, proposed),
        "draftingProvenance": "approved-playbook",
        "rationale": "Deviation from the approved position.",
        "lawyerReview": "pending",
    }


def test_issues_render_sorted_by_severity(tmp_path: Path) -> None:
    issues = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "run-sort",
        "sourceManifestSha256": "a" * 64,
        "playbookId": "saas-customer",
        "playbookVersion": "1.0.0",
        "effectiveStanceSha256": "b" * 64,
        "issues": [
            _severity_issue("low-issue", "low", "1"),
            _severity_issue("high-issue", "high", "2"),
            _severity_issue("medium-issue", "medium", "3"),
        ],
    }

    rendered = render_issues_html(issues)
    html_order = [rendered.index(f"{name}-issue") for name in ("high", "medium", "low")]
    assert html_order == sorted(html_order)

    out_docx = tmp_path / "issues.docx"
    render_issues_docx(issues, out_docx)
    with zipfile.ZipFile(out_docx) as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
    docx_order = [doc_xml.index(f"{name}-issue") for name in ("high", "medium", "low")]
    assert docx_order == sorted(docx_order)


def test_register_playbook_requires_approved_status(tmp_path: Path) -> None:
    playbook = _playbook()
    playbook["status"] = "draft"
    with pytest.raises(PlaybookError, match="Only approved playbooks"):
        register_playbook(playbook, tmp_path, tmp_path / "registry.json")


def test_registry_listing_and_picker_surface_only_approved(tmp_path: Path) -> None:
    playbook = _playbook()
    registry_file = tmp_path / "playbook-registry.json"
    register_playbook(playbook, tmp_path / "pkg", registry_file)
    registry = json.loads(registry_file.read_text(encoding="utf-8"))
    registry["playbooks"].append(
        {
            "playbookId": "draft-playbook",
            "playbookName": "Draft playbook",
            "version": "0.1.0",
            "status": "draft",
            "sealedAt": "2026-01-01T00:00:00Z",
            "packagePath": "/tmp/draft",
        }
    )
    registry_file.write_text(json.dumps(registry), encoding="utf-8")

    discovered = list_registered_playbooks(registry_file)
    assert [entry["playbookId"] for entry in discovered] == [playbook["playbookId"]]
    picker = format_playbook_picker(discovered)
    assert playbook["playbookId"] in picker
    assert "draft-playbook" not in picker


def test_reregister_never_overwrites_newer_version(tmp_path: Path) -> None:
    playbook = _playbook()
    registry_file = tmp_path / "playbook-registry.json"
    register_playbook(playbook, tmp_path / "pkg", registry_file)

    older = copy.deepcopy(playbook)
    older["version"] = "0.9.0"
    with pytest.raises(PlaybookError, match="refusing to register older"):
        register_playbook(older, tmp_path / "pkg", registry_file)
    current = list_registered_playbooks(registry_file)
    assert current[0]["version"] == "1.0.0"

    newer = copy.deepcopy(playbook)
    newer["version"] = "1.1.0"
    register_playbook(newer, tmp_path / "pkg", registry_file)
    current = list_registered_playbooks(registry_file)
    assert len(current) == 1
    assert current[0]["version"] == "1.1.0"


def test_manifest_requires_explicit_source_role(tmp_path: Path) -> None:
    source = tmp_path / "template.txt"
    source.write_text("Approved wording.", encoding="utf-8")
    with pytest.raises(PlaybookError, match="Source role is required"):
        build_source_manifest([source], tmp_path)
    with pytest.raises(PlaybookError, match="approved-template"):
        build_source_manifest([source], tmp_path)


def test_manifest_enforces_one_to_five_source_bounds(tmp_path: Path) -> None:
    with pytest.raises(PlaybookError, match="At least one source file"):
        build_source_manifest([], tmp_path)

    sources = []
    roles = {}
    for index in range(6):
        source = tmp_path / f"source-{index}.txt"
        source.write_text(f"Source {index}.", encoding="utf-8")
        sources.append(source)
        roles[source.name] = "approved-template"
    with pytest.raises(PlaybookError, match="At most 5 source files"):
        build_source_manifest(sources, tmp_path, roles)


def test_render_playbook_markdown_formats_bulleted_sources() -> None:
    playbook = _playbook()
    manifest = {
        "artifactType": "source-manifest",
        "schemaVersion": "1.0",
        "manifestId": "test-manifest",
        "createdAt": "2026-09-05T12:00:00Z",
        "inputBoundary": "C:/matter/boundary",
        "manifestSha256": "a" * 64,
        "documents": [
            {
                "documentId": "doc-0",
                "documentSha256": "b" * 64,
                "originalPath": "C:/matter/boundary/precedent.docx",
                "fileName": "precedent.docx",
                "sourceRole": "approved-template",
                "readability": "clean",
                "pageReadingMethod": "native-text",
                "warnings": [],
                "elements": [],
            }
        ],
    }

    markdown = render_playbook_markdown(playbook, manifest)

    assert "# Customer SaaS playbook" in markdown
    assert "### Liability cap (`liability-cap`)" in markdown
    assert "#### Preferred Position" in markdown
    assert "#### Approved Fallbacks" in markdown
    assert "#### Red Line" in markdown
    assert "#### Sources" in markdown
    assert "- `precedent.docx` (`el-source`, role: approved-template)" in markdown

    invalid = copy.deepcopy(playbook)
    invalid["issues"][0]["issueId"] = "INVALID_CAPS"
    with pytest.raises(PlaybookError):
        render_playbook_markdown(invalid, manifest)


def _create_test_docx(
    path: Path,
    body_xml: str,
    footnotes_xml: str | None = None,
    comments_xml: str | None = None,
) -> None:
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="xml" ContentType="application/xml"/>\n'
        '  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>\n'
    )
    if footnotes_xml:
        content_types += '  <Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>\n'
    if comments_xml:
        content_types += '  <Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>\n'
    content_types += "</Types>"

    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>\n'
        "</Relationships>"
    )

    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        f"<w:body>{body_xml}</w:body>\n"
        "</w:document>"
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", doc_xml)
        if footnotes_xml:
            zf.writestr("word/footnotes.xml", footnotes_xml)
        if comments_xml:
            zf.writestr("word/comments.xml", comments_xml)


def test_validate_playbook_rejects_fabricated_provenance_quotation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "template.txt"
    source.write_text("Liability is capped at 100% of annual Fees.\n", encoding="utf-8")
    manifest = build_source_manifest(
        [source], tmp_path, {source.name: "approved-template"}
    )
    doc_sha = manifest["documents"][0]["sha256"]
    element_id = manifest["documents"][0]["elements"][0]["elementId"]

    pb = _playbook()
    pb["sourceManifestSha256"] = manifest["manifestSha256"]
    pb["issues"][0]["provenance"] = [
        {
            "documentSha256": doc_sha,
            "elementId": element_id,
            "exactText": "Liability is capped at 100% of annual Fees.",
            "sourceRole": "approved-template",
        }
    ]
    assert validate_playbook(pb, source_manifest=manifest) == []

    # Fabricated quotation
    pb_fabricated = copy.deepcopy(pb)
    pb_fabricated["issues"][0]["provenance"][0]["exactText"] = (
        "Fabricated wording not in source."
    )
    errors = validate_playbook(pb_fabricated, source_manifest=manifest)
    assert any(
        "provenance quotation does not match source element" in err for err in errors
    )

    # Unknown element ID
    pb_bad_el = copy.deepcopy(pb)
    pb_bad_el["issues"][0]["provenance"][0]["elementId"] = "el-nonexistent"
    errors = validate_playbook(pb_bad_el, source_manifest=manifest)
    assert any("provenance element el-nonexistent not found" in err for err in errors)

    # Unknown document SHA
    pb_bad_doc = copy.deepcopy(pb)
    pb_bad_doc["issues"][0]["provenance"][0]["documentSha256"] = "f" * 64
    errors = validate_playbook(pb_bad_doc, source_manifest=manifest)
    assert any(
        "provenance document " + ("f" * 64) + " not found" in err for err in errors
    )


def test_validate_playbook_enforces_approved_wording_when_status_is_approved() -> None:
    pb = _playbook()
    assert pb["status"] == "approved"
    assert validate_playbook(pb) == []

    # Candidate preferred wording in approved issue
    pb_cand_pref = copy.deepcopy(pb)
    pb_cand_pref["issues"][0]["basePosition"]["preferred"]["approvalStatus"] = (
        "candidate"
    )
    errors = validate_playbook(pb_cand_pref)
    assert any("operative preferred wording is not approved" in err for err in errors)

    # Candidate fallback wording in approved issue
    pb_cand_fb = copy.deepcopy(pb)
    pb_cand_fb["issues"][0]["basePosition"]["fallbacks"][0]["wording"][
        "approvalStatus"
    ] = "candidate"
    errors = validate_playbook(pb_cand_fb)
    assert any("operative fallback wording is not approved" in err for err in errors)

    # Draft playbook allows candidate wording
    pb_cand_fb["status"] = "draft"
    pb_cand_fb["issues"][0]["status"] = "candidate"
    assert validate_playbook(pb_cand_fb) == []


def test_docx_extraction_fidelity_linebreaks_and_no_synthetic_means(
    tmp_path: Path,
) -> None:
    docx_file = tmp_path / "sample.docx"
    body_xml = (
        "<w:p>"
        "<w:r><w:t>First line</w:t><w:br/><w:t>Second line</w:t><w:tab/><w:t>Tabbed part</w:t></w:r>"
        "</w:p>"
        "<w:tbl>"
        "<w:tr>"
        "<w:tc><w:p><w:r><w:t>Notice Period</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>30 days in writing</w:t></w:r></w:p></w:tc>"
        "</w:tr>"
        "</w:tbl>"
    )
    fn_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '<w:footnote w:id="1"><w:p><w:r><w:t>Substantive footnote</w:t></w:r></w:p></w:footnote>\n'
        "</w:footnotes>"
    )
    cm_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '<w:comment w:id="1"><w:p><w:r><w:t>Drafting comment</w:t></w:r></w:p></w:comment>\n'
        "</w:comments>"
    )
    _create_test_docx(docx_file, body_xml, footnotes_xml=fn_xml, comments_xml=cm_xml)

    manifest = build_source_manifest(
        [docx_file], tmp_path, {docx_file.name: "approved-template"}
    )
    doc = manifest["documents"][0]
    assert doc["readability"] == "readable"
    assert "document-contains-footnotes" in doc["warnings"]
    assert "document-contains-comments" in doc["warnings"]

    el_p = doc["elements"][0]
    assert el_p["sourceText"] == "First line Second line Tabbed part"
    assert "lineSecond" not in el_p["sourceText"]

    el_tbl = doc["elements"][1]
    assert el_tbl["sourceText"] == "Notice Period | 30 days in writing"
    assert "means" not in el_tbl["sourceText"]


def test_term_map_only_uses_approved_template_for_house_definitions(
    tmp_path: Path,
) -> None:
    template = tmp_path / "template.txt"
    template.write_text(
        '1 Definitions\n\n"Fees" means charges paid or payable under this Agreement.\n',
        encoding="utf-8",
    )
    precedent = tmp_path / "precedent.txt"
    precedent.write_text(
        '1 Definitions\n\n"Fees" means total revenue invoiced under all Order Forms.\n',
        encoding="utf-8",
    )
    contract = tmp_path / "contract.txt"
    contract.write_text(
        '1 Definitions\n\n"Fees" means charges paid or payable under this Agreement.\n',
        encoding="utf-8",
    )
    roles = {
        template.name: "approved-template",
        precedent.name: "negotiated-final",
    }
    house_manifest = build_source_manifest([template, precedent], tmp_path, roles)
    contract_manifest = build_source_manifest(
        [contract], tmp_path, {contract.name: "contract-under-review"}
    )
    pb = _playbook()
    pb["sourceManifestSha256"] = house_manifest["manifestSha256"]

    term_map = build_term_map_skeleton(
        house_manifest,
        contract_manifest,
        pb,
        "test-run",
    )
    assert len(term_map["entries"]) == 1
    entry = term_map["entries"][0]
    assert entry["houseDefinition"]["term"] == "Fees"
    assert (
        entry["houseDefinition"]["definitionText"]
        == '"Fees" means charges paid or payable under this Agreement.'
    )
    assert (
        entry["houseDefinition"]["documentSha256"]
        == house_manifest["documents"][0]["sha256"]
    )
    assert entry["relation"] == "exact"
    assert entry["draftingAction"] == "use-contract-term"
    assert (
        entry["rationale"]
        != "House sources contain multiple definitions for this term."
    )


def test_seal_playbook_end_to_end(tmp_path: Path) -> None:
    source = tmp_path / "template.txt"
    source.write_text("Liability is capped at 100% of annual Fees.\n", encoding="utf-8")
    manifest = build_source_manifest(
        [source], tmp_path, {source.name: "approved-template"}
    )
    doc_sha = manifest["documents"][0]["sha256"]
    element_id = manifest["documents"][0]["elements"][0]["elementId"]

    draft_pb = _playbook()
    draft_pb["status"] = "draft"
    draft_pb["version"] = "0.9.0"
    draft_pb["sourceManifestSha256"] = manifest["manifestSha256"]
    draft_pb["issues"][0]["status"] = "approved"
    draft_pb["issues"][0]["basePosition"]["preferred"]["approvalStatus"] = "candidate"
    draft_pb["issues"][0]["basePosition"]["fallbacks"][0]["wording"][
        "approvalStatus"
    ] = "candidate"
    draft_pb["issues"][0]["provenance"] = [
        {
            "documentSha256": doc_sha,
            "elementId": element_id,
            "exactText": "Liability is capped at 100% of annual Fees.",
            "sourceRole": "approved-template",
        }
    ]

    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    registry_file = tmp_path / "playbook-registry.json"

    res = seal_playbook(
        draft_pb,
        manifest,
        version="1.0.0",
        package_path=pkg_dir,
        registry_path=registry_file,
    )
    assert res["playbook"]["status"] == "approved"
    assert res["playbook"]["version"] == "1.0.0"
    assert (
        res["playbook"]["issues"][0]["basePosition"]["preferred"]["approvalStatus"]
        == "approved"
    )
    assert (
        res["playbook"]["issues"][0]["basePosition"]["fallbacks"][0]["wording"][
            "approvalStatus"
        ]
        == "approved"
    )
    assert res["receipt"]["validationErrors"] == []
    assert "Approved Fallbacks" in res["markdown"]
    assert registry_file.is_file()

    # Test CLI seal command
    pb_path = tmp_path / "draft_pb.json"
    pb_path.write_text(json.dumps(draft_pb), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    sealed_pb_path = tmp_path / "sealed_pb.json"
    receipt_path = tmp_path / "build-receipt.json"
    md_path = tmp_path / "playbook.md"

    builder_cli = BUILDER / "scripts/playbook_builder.py"
    cmd_res = subprocess.run(
        [
            sys.executable,
            str(builder_cli),
            "seal",
            str(pb_path),
            "--manifest",
            str(manifest_path),
            "--version",
            "1.2.0",
            "--registry",
            str(registry_file),
            "--out-playbook",
            str(sealed_pb_path),
            "--out-receipt",
            str(receipt_path),
            "--out-markdown",
            str(md_path),
        ],
        capture_output=True,
        text=True,
    )
    assert cmd_res.returncode == 0, cmd_res.stderr
    assert sealed_pb_path.is_file()
    assert receipt_path.is_file()
    assert md_path.is_file()
    sealed_data = json.loads(sealed_pb_path.read_text(encoding="utf-8"))
    assert sealed_data["version"] == "1.2.0"
    assert sealed_data["status"] == "approved"


def test_register_playbook_protects_corrupt_registry(tmp_path: Path) -> None:
    registry_file = tmp_path / "playbook-registry.json"
    corrupt_content = b"INVALID JSON CONTENT {{"
    registry_file.write_bytes(corrupt_content)

    pb = _playbook()
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()

    with pytest.raises(PlaybookError, match="preserved corrupted file"):
        register_playbook(pb, pkg_dir, registry_file)

    corrupt_backups = list(tmp_path.glob("playbook-registry.corrupt-*.json"))
    assert len(corrupt_backups) == 1
    assert corrupt_backups[0].read_bytes() == corrupt_content

    # Also invalid artifactType
    registry_file.write_text(json.dumps({"artifactType": "wrong"}), encoding="utf-8")
    with pytest.raises(PlaybookError, match="preserved corrupted file"):
        register_playbook(pb, pkg_dir, registry_file)


def test_build_review_receipt_requires_reconciled_coverage_receipt() -> None:
    issues = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "run-receipt",
        "sourceManifestSha256": "a" * 64,
        "playbookId": "saas-customer",
        "playbookVersion": "1.0.0",
        "effectiveStanceSha256": "b" * 64,
        "issues": [],
    }
    # None coverage receipt -> reconciled: False
    r1 = build_review_receipt(issues, None)
    assert r1["reconciled"] is False

    # False coverage receipt -> reconciled: False
    cov_false = {"artifactType": "review-coverage-receipt", "reconciled": False}
    r2 = build_review_receipt(issues, cov_false)
    assert r2["reconciled"] is False

    # True coverage receipt -> reconciled: True
    cov_true = {"artifactType": "review-coverage-receipt", "reconciled": True}
    r3 = build_review_receipt(issues, cov_true)
    assert r3["reconciled"] is True


def test_manifest_supports_custom_max_sources(tmp_path: Path) -> None:
    sources = []
    roles = {}
    for idx in range(10):
        s = tmp_path / f"source_{idx}.txt"
        s.write_text(f"Clause {idx} content", encoding="utf-8")
        sources.append(s)
        roles[s.name] = "approved-template" if idx == 0 else "negotiated-final"

    # Fails with default max_sources=5
    with pytest.raises(PlaybookError, match="At most 5 source files"):
        build_source_manifest(sources, tmp_path, roles)

    # Succeeds when max_sources=15
    manifest = build_source_manifest(sources, tmp_path, roles, max_sources=15)
    assert len(manifest["documents"]) == 10


def test_format_playbook_picker_displays_human_names(tmp_path: Path) -> None:
    playbooks = [
        {
            "playbookId": "msa-supplier",
            "playbookName": "Master Services Agreement (Supplier)",
            "version": "1.0.0",
            "agreementFamily": "MSA",
            "perspective": "supplier",
            "issueCount": 24,
            "status": "approved",
            "sealedAt": "2026-09-01T12:00:00Z",
            "packagePath": "/path/to/pkg",
        },
        {
            "playbookId": "mutual-nda",
            "playbookName": "Standard Mutual NDA",
            "version": "2.1.0",
            "agreementFamily": "NDA",
            "perspective": "mutual",
            "issueCount": 12,
            "status": "approved",
            "sealedAt": "2026-09-02T12:00:00Z",
            "packagePath": "/path/to/pkg2",
        },
    ]
    picker = format_playbook_picker(playbooks)
    assert "Available Approved Playbooks:" in picker
    assert "**Master Services Agreement (Supplier)**" in picker
    assert "(`msa-supplier`)" in picker
    assert "24 issues [Supplier]" in picker
    assert "**Standard Mutual NDA**" in picker
    assert "(`mutual-nda`)" in picker
    assert "12 issues [Mutual]" in picker


def test_suggest_playbook_matches_contract_by_filename(tmp_path: Path) -> None:
    playbooks = [
        {
            "playbookId": "msa-supplier",
            "playbookName": "Master Services Agreement - Supplier",
            "version": "1.0.0",
            "agreementFamily": "MSA",
            "perspective": "supplier",
            "issueCount": 20,
            "status": "approved",
        },
        {
            "playbookId": "nda-standard",
            "playbookName": "Standard Non-Disclosure Agreement",
            "version": "1.2.0",
            "agreementFamily": "NDA",
            "perspective": "mutual",
            "issueCount": 10,
            "status": "approved",
        },
    ]
    # 1. MSA filename match
    msa_file = tmp_path / "Acme_MSA_Draft_2026.docx"
    match = match_playbook_candidate(playbooks, source_names=[msa_file])
    assert match is not None
    assert match["playbook"]["playbookId"] == "msa-supplier"
    assert match["detectedFamily"] == "MSA"
    suggestion_text = format_playbook_suggestion(match)
    assert "This looks like an MSA." in suggestion_text
    assert "Master Services Agreement - Supplier" in suggestion_text

    # 2. NDA filename match
    nda_file = tmp_path / "Mutual_Confidentiality_Agreement.pdf"
    match_nda = match_playbook_candidate(playbooks, source_names=[nda_file])
    assert match_nda is not None
    assert match_nda["playbook"]["playbookId"] == "nda-standard"
    assert match_nda["detectedFamily"] == "NDA"

    # 3. Unrelated filename returns None
    other_file = tmp_path / "Quarterly_Minutes.txt"
    assert match_playbook_candidate(playbooks, source_names=[other_file]) is None


def test_suggest_playbook_matches_contract_by_docx_heading(tmp_path: Path) -> None:
    playbooks = [
        {
            "playbookId": "msa-supplier",
            "playbookName": "Master Services Agreement - Supplier",
            "version": "1.0.0",
            "agreementFamily": "MSA",
            "perspective": "supplier",
            "issueCount": 20,
            "status": "approved",
        }
    ]
    # Create a docx with generic filename but MSA heading inside
    generic_docx = tmp_path / "Contract_Draft_v1.docx"
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>MASTER SERVICES AGREEMENT</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>This Master Agreement is entered into by...</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    with zipfile.ZipFile(generic_docx, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)

    sample = extract_sample_text_from_file(generic_docx)
    assert "MASTER SERVICES AGREEMENT" in sample
    match = match_playbook_candidate(
        playbooks, source_names=[generic_docx], sample_text=sample
    )
    assert match is not None
    assert match["playbook"]["playbookId"] == "msa-supplier"


def test_suggest_playbook_handles_perspective_and_ambiguity(tmp_path: Path) -> None:
    playbooks = [
        {
            "playbookId": "msa-supplier",
            "playbookName": "Master Services Agreement (Supplier)",
            "version": "1.0.0",
            "agreementFamily": "MSA",
            "perspective": "supplier",
            "issueCount": 20,
            "status": "approved",
        },
        {
            "playbookId": "msa-customer",
            "playbookName": "Master Services Agreement (Customer)",
            "version": "1.0.0",
            "agreementFamily": "MSA",
            "perspective": "customer",
            "issueCount": 20,
            "status": "approved",
        },
    ]

    # Distinct perspective in filename
    supplier_file = tmp_path / "Acme_MSA_Supplier_Signed.docx"
    match_sup = match_playbook_candidate(playbooks, source_names=[supplier_file])
    assert match_sup is not None
    assert match_sup["playbook"]["playbookId"] == "msa-supplier"

    customer_file = tmp_path / "Acme_MSA_Customer_Clean.docx"
    match_cust = match_playbook_candidate(playbooks, source_names=[customer_file])
    assert match_cust is not None
    assert match_cust["playbook"]["playbookId"] == "msa-customer"

    # Ambiguous filename with no perspective clue -> returns None to fall back to picker
    neutral_file = tmp_path / "Acme_MSA_v1.docx"
    assert match_playbook_candidate(playbooks, source_names=[neutral_file]) is None


def test_cli_discover_playbooks_with_contract_first_guess(tmp_path: Path) -> None:
    reviewer_cli = REVIEWER / "scripts/playbook_review.py"

    def run_cli(script: Path, *arguments: object) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(script), *(str(arg) for arg in arguments)],
            capture_output=True,
            check=False,
            encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr or result.stdout
        return result

    pb = _playbook()
    pb["playbookId"] = "cloud-saas-customer"
    pb["title"] = "Enterprise SaaS Master Agreement"
    pb["agreementFamily"] = "SaaS agreement"
    reg_file = tmp_path / "playbook-registry.json"
    register_playbook(pb, tmp_path / "pkg", reg_file)

    # 1. First-guess contract match
    contract_file = tmp_path / "Acme_SaaS_Agreement_2026.docx"
    contract_file.write_text("dummy", encoding="utf-8")

    res = run_cli(
        reviewer_cli,
        "discover-playbooks",
        "--registry",
        reg_file,
        "--contract",
        contract_file,
    )
    assert "This looks like a SaaS Agreement." in res.stdout
    assert "Enterprise SaaS Master Agreement" in res.stdout
    assert "Would you like to use this playbook" in res.stdout

    # 2. First-guess JSON output
    res_json = run_cli(
        reviewer_cli,
        "discover-playbooks",
        "--registry",
        reg_file,
        "--contract",
        contract_file,
        "--json",
    )
    data = json.loads(res_json.stdout)
    assert data["suggestion"] is not None
    assert data["suggestion"]["playbook"]["playbookId"] == "cloud-saas-customer"

    # 3. Non-matching contract falls back to picker
    other_file = tmp_path / "Meeting_Agenda.txt"
    other_file.write_text("Agenda", encoding="utf-8")
    res_fallback = run_cli(
        reviewer_cli,
        "discover-playbooks",
        "--registry",
        reg_file,
        "--contract",
        other_file,
    )
    assert "Available Approved Playbooks:" in res_fallback.stdout
    assert "Enterprise SaaS Master Agreement" in res_fallback.stdout


def test_classification_labels_and_british_date_helpers() -> None:
    assert CLASSIFICATION_LABELS["deviation"] == "Redline Required"
    assert get_classification_label("deviation") == "Redline Required"
    assert get_classification_label("missing-protection") == "Missing House Clause"
    assert get_classification_label("extra-obligation") == "Onerous / Non-Standard"
    assert get_classification_label("aligned-fallback") == "Acceptable Fallback"
    assert get_classification_label("aligned-preferred") == "Standard / Aligned"
    assert get_classification_label("playbook-gap") == "Uncovered Issue"
    assert get_classification_label("playbook-conflict") == "Playbook Conflict"
    assert get_classification_label("unclear") == "Ambiguous Drafting"
    assert get_classification_label("not-applicable") == "Not Applicable"

    assert format_british_date("2026-09-06T14:15:22Z") == "6 September 2026"
    assert format_british_date("2026-01-15T09:00:00+00:00") == "15 January 2026"

    # International, US, and ISO date formatting
    assert format_display_date("2026-09-06T14:15:22Z", style="uk") == "6 September 2026"
    assert (
        format_display_date("2026-09-06T14:15:22Z", style="us") == "September 6, 2026"
    )
    assert format_display_date("2026-09-06T14:15:22Z", style="iso") == "2026-09-06"
    # Auto-detection based on governing law
    assert (
        format_display_date("2026-09-06T14:15:22Z", governing_law="State of Delaware")
        == "September 6, 2026"
    )
    assert (
        format_display_date("2026-09-06T14:15:22Z", governing_law="New York Law")
        == "September 6, 2026"
    )
    assert (
        format_display_date("2026-09-06T14:15:22Z", governing_law="England and Wales")
        == "6 September 2026"
    )


def test_render_issues_docx_executive_header_and_negotiation_comment(
    tmp_path: Path,
) -> None:
    issues = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "review-run-exec",
        "sourceManifestSha256": "a" * 64,
        "playbookId": "saas-customer",
        "playbookVersion": "1.0.0",
        "effectiveStanceSha256": "b" * 64,
        "contractName": "Acme Cloud Services Agreement",
        "generatedAt": "2026-09-06T12:00:00Z",
        "issues": [
            {
                "issueId": "review-liab-cap",
                "playbookIssueId": "liability-cap",
                "classification": "deviation",
                "materiality": "high",
                "documentSha256": "c" * 64,
                "elementId": "el-cap",
                "clauseRef": "12.1",
                "originalText": "Liability is capped at 50% fees.",
                "proposedText": "Liability is capped at 100% fees.",
                "markupSegments": build_markup_segments(
                    "Liability is capped at 50% fees.",
                    "Liability is capped at 100% fees.",
                ),
                "draftingProvenance": "approved-playbook",
                "rationale": "High commercial risk; cap must reflect standard 100% annual fees baseline.",
                "externalComment": "Our house standard requires liability to be capped at 100% of annual fees.",
                "lawyerReview": "pending",
            },
            {
                "issueId": "review-audit",
                "playbookIssueId": "audit-rights",
                "classification": "aligned-preferred",
                "materiality": "none",
                "documentSha256": "c" * 64,
                "elementId": "el-audit",
                "clauseRef": "14.2",
                "originalText": "Supplier may audit on 30 days notice.",
                "proposedText": "Supplier may audit on 30 days notice.",
                "markupSegments": [
                    {"op": "equal", "text": "Supplier may audit on 30 days notice."}
                ],
                "draftingProvenance": "none",
                "rationale": "Annual audit on 30 days notice is fully aligned.",
                "lawyerReview": "not-required",
            },
        ],
    }

    out_docx = tmp_path / "exec-issues-matrix.docx"
    render_issues_docx(
        issues,
        out_docx,
        playbook=_playbook(),
        contract_name="Acme Enterprise Agreement",
    )
    assert out_docx.is_file()

    with zipfile.ZipFile(out_docx) as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
        assert "Customer SaaS playbook" in doc_xml
        assert "Acme Enterprise Agreement" in doc_xml
        assert "6 September 2026" in doc_xml
        assert "Governing Law: England and Wales" in doc_xml
        assert "Executive Summary: 2 Total Issues" in doc_xml
        assert "1 High Risk" in doc_xml
        assert "1 Redline Required" in doc_xml
        assert "1 Standard" in doc_xml
        assert "Redline Required" in doc_xml
        assert "(deviation)" not in doc_xml  # slug never leaks into the matrix
        assert "INTERNAL - PRIVILEGED AND CONFIDENTIAL" in doc_xml
        assert "Internal Risk / Guidance:" in doc_xml
        assert (
            "High commercial risk; cap must reflect standard 100% annual fees baseline."
            in doc_xml
        )
        assert "Negotiation Comment (for Word / Counterparty):" in doc_xml
        assert (
            "Our house standard requires liability to be capped at 100% of annual fees."
            in doc_xml
        )

        from xml.etree import ElementTree as ET

        root = ET.fromstring(doc_xml)
        assert root is not None


def test_render_issues_docx_us_governing_law(tmp_path: Path) -> None:
    pb = _playbook()
    pb["governingLaw"] = "State of Delaware"
    issues = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "review-run-us",
        "sourceManifestSha256": "a" * 64,
        "playbookId": "saas-customer",
        "playbookVersion": "1.0.0",
        "effectiveStanceSha256": "b" * 64,
        "generatedAt": "2026-09-06T12:00:00Z",
        "issues": [],
    }
    out_docx = tmp_path / "exec-issues-matrix-us.docx"
    render_issues_docx(issues, out_docx, playbook=pb)
    assert out_docx.is_file()

    with zipfile.ZipFile(out_docx) as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
        assert "September 6, 2026" in doc_xml
        assert "Governing Law: State of Delaware" in doc_xml


def test_validate_issues_list_handles_external_comment() -> None:
    valid_issue: dict[str, Any] = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "run-valid",
        "sourceManifestSha256": "a" * 64,
        "playbookId": "saas-customer",
        "playbookVersion": "1.0.0",
        "effectiveStanceSha256": "b" * 64,
        "issues": [
            {
                "issueId": "iss-1",
                "playbookIssueId": "liab-cap",
                "classification": "deviation",
                "materiality": "high",
                "documentSha256": "c" * 64,
                "elementId": "el-1",
                "clauseRef": "1.1",
                "originalText": "Old",
                "proposedText": "New",
                "markupSegments": [
                    {"op": "delete", "text": "Old"},
                    {"op": "insert", "text": "New"},
                ],
                "draftingProvenance": "approved-playbook",
                "rationale": "Internal note",
                "externalComment": "Ready for Word comments",
                "lawyerReview": "pending",
            }
        ],
    }
    assert validate_issues_list(valid_issue) == []

    # Non-string externalComment fails
    invalid_issue = copy.deepcopy(valid_issue)
    invalid_issue["issues"][0]["externalComment"] = 12345  # type: ignore[typeddict-item]
    errors = validate_issues_list(invalid_issue)
    assert any("externalComment must be a string" in e for e in errors)


def test_cli_export_docx_with_contract_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issues_file = tmp_path / "issues-list.json"
    issues_data = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "run-cli-export",
        "sourceManifestSha256": "a" * 64,
        "playbookId": "saas-customer",
        "playbookVersion": "1.0.0",
        "effectiveStanceSha256": "b" * 64,
        "issues": [],
    }
    issues_file.write_text(json.dumps(issues_data), encoding="utf-8")
    out_docx = tmp_path / "cli-export.docx"

    reviewer_cli = (
        Path(__file__).resolve().parents[4]
        / "skills/transactional/playbook-review/scripts/playbook_review.py"
    )

    def run_cli(script: Path, *arguments: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *(str(a) for a in arguments)],
            check=True,
            capture_output=True,
            text=True,
        )

    res = run_cli(
        reviewer_cli,
        "export-docx",
        issues_file,
        "--contract-name",
        "Halcyon MSA",
        "--out",
        out_docx,
    )
    assert res.returncode == 0
    assert out_docx.is_file()

    with zipfile.ZipFile(out_docx) as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
        assert "Halcyon MSA" in doc_xml
