#!/usr/bin/env python3
"""Run the dependency-free definition-check deterministic pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from dataclasses import asdict

from typing import Optional

from _runtime_gate import require_supported_python

require_supported_python()

from definition_check.analyze import (
    apply_definition_scope_qualifications,
    apply_occurrence_review_to_findings,
    build_finalized_terms,
    build_finalized_usages,
    build_term_variants,
    build_usages,
    rebuild_finalized_findings,
    run_rules,
)
from definition_check.bundle import AgentBundleError, load_agent_bundle
from definition_check.mention_coverage import audit_mentions
from definition_check.extract import extract_quoted_observations
from definition_check.models import (
    Ledger,
    ReferenceReviewSummary,
    SemanticReviewSummary,
)
from definition_check.occurrence_review import (
    build_occurrence_candidates,
    build_occurrence_collisions,
    build_occurrence_envelopes,
    reconcile_occurrences,
)
from definition_check.ooxml import IntakeError, extract_docx
from definition_check.reference_review import (
    ReferenceReviewError,
    build_reference_candidates,
    build_reference_envelopes,
    reconcile_reference_adjudications,
)
from definition_check.render import write_outputs, write_review_artifacts
from definition_check.review import ProposalValidationError, reconcile_proposals
from definition_check.review_packets import (
    build_discovery_packets,
    build_occurrence_packets,
    build_reference_packets,
    build_semantic_packets,
    expand_discovery_responses,
    write_packet_builds,
)
from definition_check.seeds import generate_discovery_seeds
from definition_check.semantic_review import (
    SemanticReviewError,
    build_review_envelopes,
    build_term_candidates,
    materialize_definitions,
    reconcile_adjudications,
)
from definition_check.telemetry import DebugTelemetry, write_debug_telemetry
from definition_check.workspace import (
    WorkspaceError,
    create_workspace,
    ensure_workspace,
    require_disjoint_paths,
    require_within_workspace,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check defined-term hygiene in one DOCX without modifying the source."
    )
    parser.add_argument("input", type=Path, help="Path to the source DOCX")
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Explicit directory for Definition Check artifacts",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        help=(
            "Internal run workspace for packets, manifests, responses, and review "
            "envelopes; defaults to a new cleanup-eligible OS-temporary workspace. "
            "An explicit path is caller-managed and retained."
        ),
    )
    parser.add_argument(
        "--common-term",
        action="append",
        default=[],
        help="Capitalized term to suppress from undefined-term candidates; repeat as needed",
    )
    parser.add_argument(
        "--agent-bundle",
        type=Path,
        help="Optional validated JSON bundle containing agent records and per-term semantic adjudications",
    )
    parser.add_argument(
        "--include-internal-traces",
        action="store_true",
        help="Compatibility option for developer artifacts; the lawyer dashboard never shows internal traces",
    )
    parser.add_argument(
        "--qa-annotated-document",
        action="store_true",
        help="Write an opt-in full-document HTML view with reviewed term annotations",
    )
    parser.add_argument(
        "--debug-telemetry",
        action="store_true",
        help="Write local phase timings and labelled review-payload token estimates",
    )
    parser.add_argument("--prepare-only", action="store_true", help=argparse.SUPPRESS)
    return parser


def run(
    input_path: Path,
    output_dir: Path,
    common_terms: Optional[set[str]] = None,
    agent_bundle_path: Optional[Path] = None,
    include_internal_traces: bool = False,
    include_qa_annotated_document: bool = False,
    debug_telemetry: Optional[DebugTelemetry] = None,
    work_dir: Optional[Path] = None,
    emit_outputs: bool = True,
) -> Ledger:
    telemetry = debug_telemetry or DebugTelemetry()
    if work_dir is not None:
        require_disjoint_paths(output_dir, work_dir)
        workspace_dir = ensure_workspace(work_dir)[0]
    else:
        workspace_dir = create_workspace()[0]
        require_disjoint_paths(output_dir, workspace_dir)
    if agent_bundle_path is not None:
        require_within_workspace(
            agent_bundle_path,
            workspace_dir,
            label="--agent-bundle",
        )
    with telemetry.phase("agent_bundle_load"):
        agent_bundle = (
            load_agent_bundle(agent_bundle_path) if agent_bundle_path else None
        )
    if agent_bundle:
        telemetry.record_payload(
            "agent_candidate_proposals", agent_bundle.candidate_proposals
        )
        telemetry.record_payload(
            "semantic_adjudication_responses",
            agent_bundle.semantic_adjudications,
        )
        telemetry.record_payload(
            "occurrence_adjudication_responses",
            agent_bundle.occurrence_adjudications,
        )
        telemetry.record_payload(
            "reference_adjudication_responses",
            agent_bundle.reference_adjudications,
        )
    with telemetry.phase("ooxml_intake"):
        source = extract_docx(input_path)
    ensure_workspace(workspace_dir, source_sha256=source.sha256)
    with telemetry.phase("quoted_candidate_discovery"):
        lexical_observations = extract_quoted_observations(source)
        definitions = []
    with telemetry.phase("initial_usage_index_and_rules"):
        usages = build_usages(source, definitions, common_terms=common_terms)
        findings = run_rules(source, definitions, usages, common_terms=common_terms)

    limitations = list(source.warnings)
    run_status = "completed_reduced_assurance" if limitations else "completed"
    methods_run = [
        "ooxml_intake",
        "quoted_candidate_discovery",
        "deterministic_candidate_closure",
        "deterministic_usage_index",
        "deterministic_definition_rules",
    ]
    methods_not_run: list[dict[str, str]] = []
    evidence = []
    context_requests = []
    candidate_proposals = []
    review_traces = []
    semantic_findings = []
    semantic_adjudications = []
    occurrence_adjudications = []
    reference_adjudications = []
    capability_profile = "C3_PYTHON_STDLIB"

    if agent_bundle:
        with telemetry.phase("agent_proposal_reconciliation"):
            review = reconcile_proposals(agent_bundle.candidate_proposals)
            evidence = list(agent_bundle.evidence)
            context_requests = list(agent_bundle.context_requests)
            candidate_proposals.extend(agent_bundle.candidate_proposals)
            review_traces = [*review.review_traces, *agent_bundle.review_traces]
            semantic_findings = list(agent_bundle.semantic_findings)
        methods_run.append("supervisor_reconciliation")
        if candidate_proposals:
            methods_run.append("agentic_candidate_discovery")
        if context_requests:
            methods_run.append("bounded_context_retrieval")
        capability_profile = "C4_FULL_LOCAL"

    with telemetry.phase("semantic_queue_build"):
        term_candidates = build_term_candidates(
            source,
            definitions,
            findings,
            lexical_observations,
            candidate_proposals,
        )
        review_envelopes = build_review_envelopes(
            source,
            term_candidates,
        )
    with telemetry.phase("review_packet_build"):
        discovery_seeds = generate_discovery_seeds(source)
        discovery_packet_build = build_discovery_packets(
            discovery_seeds,
            source_sha256=source.sha256,
        )
        semantic_packet_build = build_semantic_packets(
            review_envelopes,
            source_sha256=source.sha256,
        )
    discovery_complete = False
    if agent_bundle and agent_bundle.discovery_review is not None:
        receipt = agent_bundle.discovery_review
        manifest = discovery_packet_build.manifest
        if any(
            receipt[field] != manifest[field]
            for field in ("source_sha256", "prompt_sha256", "queue_sha256")
        ):
            raise AgentBundleError(
                "discovery_review does not match the current source, prompt, or queue"
            )
        discovered = expand_discovery_responses(
            manifest,
            {response["packet"]: response for response in receipt["responses"]},
            expected_source_sha256=source.sha256,
        )
        supplied = {
            (proposal.id, proposal.term, proposal.location)
            for proposal in candidate_proposals
        }
        if any(
            (proposal.id, proposal.term, proposal.location) not in supplied
            for proposal in discovered
        ):
            raise AgentBundleError(
                "discovery_review proposals are missing from the bundle"
            )
        discovery_complete = True
        if "agentic_candidate_discovery" not in methods_run:
            methods_run.append("agentic_candidate_discovery")
        methods_run.append("discovery_queue_finalization")
    telemetry.record_count("semantic_queue", len(term_candidates))
    telemetry.record_count(
        "discovery_review_packets", len(discovery_packet_build.packets)
    )
    telemetry.record_count(
        "semantic_review_packets", len(semantic_packet_build.packets)
    )
    telemetry.record_payload("semantic_review_envelopes", review_envelopes)
    telemetry.record_payload("discovery_review_packets", discovery_packet_build.packets)
    telemetry.record_payload("semantic_review_packets", semantic_packet_build.packets)
    semantic_review = SemanticReviewSummary(
        "not_run", len(term_candidates), 0, len(term_candidates)
    )
    if agent_bundle and (
        agent_bundle.semantic_adjudications
        or (discovery_complete and not term_candidates)
    ):
        with telemetry.phase("semantic_reconciliation"):
            semantic_adjudications, semantic_review = reconcile_adjudications(
                term_candidates,
                review_envelopes,
                agent_bundle.semantic_adjudications,
            )
            semantic_adjudications = list(
                apply_definition_scope_qualifications(
                    source, term_candidates, semantic_adjudications
                )
            )
            definitions = materialize_definitions(
                source,
                term_candidates,
                semantic_adjudications,
            )
        if term_candidates:
            methods_run.append("agentic_semantic_review")
        methods_run.append("semantic_queue_finalization")
    else:
        methods_not_run.append(
            {
                "method": "agentic_semantic_review",
                "reason": "not_run_missing_capability",
            }
        )
    reference_candidates = ()
    reference_review_envelopes: list[dict[str, object]] = []
    reference_review = ReferenceReviewSummary("not_run", 0, 0, 0)
    with telemetry.phase("reference_queue_build"):
        if semantic_review.status == "complete":
            reference_candidates = build_reference_candidates(source, definitions)
            reference_review_envelopes = build_reference_envelopes(
                source, reference_candidates
            )
        reference_packet_build = build_reference_packets(
            reference_review_envelopes,
            source_sha256=source.sha256,
        )
    telemetry.record_count("reference_queue", len(reference_candidates))
    telemetry.record_payload("reference_review_envelopes", reference_review_envelopes)
    telemetry.record_payload("reference_review_packets", reference_packet_build.packets)
    if semantic_review.status == "complete":
        if not reference_candidates:
            reference_adjudications, reference_review = (
                reconcile_reference_adjudications(
                    reference_candidates,
                    reference_review_envelopes,
                    agent_bundle.reference_adjudications if agent_bundle else (),
                )
            )
            reference_adjudications = list(reference_adjudications)
        elif agent_bundle and agent_bundle.reference_adjudications:
            with telemetry.phase("reference_reconciliation"):
                reference_adjudications, reference_review = (
                    reconcile_reference_adjudications(
                        reference_candidates,
                        reference_review_envelopes,
                        agent_bundle.reference_adjudications,
                    )
                )
                reference_adjudications = list(reference_adjudications)
            methods_run.append("agentic_reference_review")
        else:
            reference_review = ReferenceReviewSummary(
                "incomplete",
                len(reference_candidates),
                0,
                len(reference_candidates),
            )
            methods_not_run.append(
                {
                    "method": "agentic_reference_review",
                    "reason": "not_run_missing_capability",
                }
            )
    elif agent_bundle and agent_bundle.reference_adjudications:
        raise ReferenceReviewError(
            "reference adjudications cannot be applied before semantic review completes"
        )

    finalized_terms = None
    if semantic_review.status == "complete":
        with telemetry.phase("post_finalization_usage_reindex"):
            finalized_terms = build_finalized_terms(
                source,
                definitions,
                term_candidates,
                semantic_adjudications,
            )
            usages = build_finalized_usages(
                source,
                finalized_terms,
                candidates=term_candidates,
                adjudications=semantic_adjudications,
            )
            findings = rebuild_finalized_findings(
                source,
                findings,
                definitions,
                finalized_terms,
                usages,
                term_candidates,
                semantic_adjudications,
                common_terms=common_terms,
                reference_candidates=reference_candidates,
                reference_adjudications=reference_adjudications,
                reference_review_complete=reference_review.status == "complete",
            )
        methods_run.append("post_finalization_usage_reindex")
    telemetry.record_count("finalized_terms", len(finalized_terms or ()))
    telemetry.record_count("indexed_usages", len(usages))

    with telemetry.phase("occurrence_queue_build"):
        occurrence_candidates = build_occurrence_candidates(
            source,
            definitions,
            usages,
            finalized_terms=finalized_terms,
        )
        occurrence_review_envelopes = build_occurrence_envelopes(
            source,
            definitions,
            occurrence_candidates,
            finalized_terms=finalized_terms,
        )
    telemetry.record_count("occurrence_queue", len(occurrence_candidates))
    telemetry.record_payload("occurrence_review_envelopes", occurrence_review_envelopes)
    with telemetry.phase("occurrence_review_packet_build"):
        occurrence_packet_build = build_occurrence_packets(
            occurrence_review_envelopes,
            source_sha256=source.sha256,
        )
    telemetry.record_count(
        "occurrence_review_packets", len(occurrence_packet_build.packets)
    )
    telemetry.record_payload(
        "occurrence_review_packets", occurrence_packet_build.packets
    )
    occurrence_review = SemanticReviewSummary(
        "not_run",
        len(occurrence_candidates),
        0,
        len(occurrence_candidates),
        review_id_namespace="opaque-occurrence-v1",
    )
    if semantic_review.status == "complete" and not occurrence_candidates:
        occurrence_adjudications, occurrence_review = reconcile_occurrences(
            occurrence_candidates,
            agent_bundle.occurrence_adjudications if agent_bundle else (),
        )
        occurrence_adjudications = list(occurrence_adjudications)
        methods_run.append("occurrence_queue_finalization")
    elif agent_bundle and agent_bundle.occurrence_adjudications:
        with telemetry.phase("occurrence_reconciliation"):
            occurrence_adjudications, occurrence_review = reconcile_occurrences(
                occurrence_candidates,
                agent_bundle.occurrence_adjudications,
            )
            occurrence_adjudications = list(occurrence_adjudications)
        methods_run.append("agentic_occurrence_review")
    else:
        methods_not_run.append(
            {
                "method": "agentic_occurrence_review",
                "reason": "not_run_missing_capability",
            }
        )

    with telemetry.phase("occurrence_collision_registry_build"):
        occurrence_collisions = build_occurrence_collisions(
            usages,
            occurrence_adjudications,
        )
    telemetry.record_count("occurrence_collisions", len(occurrence_collisions))
    methods_run.append("occurrence_collision_registry_build")

    with telemetry.phase("variant_registry_build"):
        term_variants = build_term_variants(
            usages,
            definitions,
            occurrence_adjudications,
            occurrence_review_complete=occurrence_review.status == "complete",
            finalized_terms=finalized_terms,
        )
    telemetry.record_count("term_variants", len(term_variants))
    methods_run.append("variant_registry_build")

    canonical_findings = apply_occurrence_review_to_findings(
        [*findings, *semantic_findings],
        usages,
        occurrence_adjudications,
        occurrence_review_complete=occurrence_review.status == "complete",
        source=source,
        definitions=definitions,
    )

    with telemetry.phase("ledger_assembly"):
        ledger = Ledger(
            source=source,
            capability_profile=capability_profile,
            run_status=run_status,
            methods_run=methods_run,
            methods_not_run=methods_not_run,
            definitions=definitions,
            term_variants=term_variants,
            usages=usages,
            findings=canonical_findings,
            evidence=evidence,
            lexical_observations=lexical_observations,
            candidate_proposals=candidate_proposals,
            context_requests=context_requests,
            review_traces=review_traces,
            term_candidates=list(term_candidates),
            semantic_adjudications=semantic_adjudications,
            semantic_review=semantic_review,
            occurrence_candidates=list(occurrence_candidates),
            occurrence_collisions=list(occurrence_collisions),
            occurrence_adjudications=occurrence_adjudications,
            occurrence_review=occurrence_review,
            reference_candidates=list(reference_candidates),
            reference_adjudications=reference_adjudications,
            reference_review=reference_review,
            limitations=limitations,
        )
    with telemetry.phase("mention_coverage_audit"):
        mention_audit = audit_mentions(
            ledger.to_dict(), [asdict(block) for block in source.blocks]
        )
        (Path(workspace_dir) / "mention-coverage.json").write_text(
            json.dumps(mention_audit, indent=2), encoding="utf-8"
        )
        if (
            semantic_review.status == "complete"
            and occurrence_review.status == "complete"
        ):
            if (
                mention_audit["gap_count"]
                or mention_audit["contradiction_count"]
                or mention_audit["counts"].get("unreviewed_occurrence", 0)
            ):
                raise ValueError("mention coverage audit failed; lawyer HTML withheld")
    with telemetry.phase("artifact_rendering"):
        if emit_outputs:
            write_outputs(
                ledger,
                output_dir,
                include_internal_traces=include_internal_traces,
                include_qa_annotated_document=include_qa_annotated_document,
            )
        write_review_artifacts(
            workspace_dir,
            review_envelopes=review_envelopes,
            occurrence_review_envelopes=occurrence_review_envelopes,
            reference_review_envelopes=reference_review_envelopes,
        )
        write_packet_builds(
            workspace_dir,
            (
                discovery_packet_build,
                semantic_packet_build,
                occurrence_packet_build,
                reference_packet_build,
            ),
        )
    return ledger


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    work_dir = args.work_dir.resolve() if args.work_dir else None
    workspace_created = work_dir is None
    telemetry = DebugTelemetry() if args.debug_telemetry else None

    try:
        if work_dir is not None:
            require_disjoint_paths(output_dir, work_dir)
        work_dir = (
            ensure_workspace(work_dir)[0]
            if work_dir is not None
            else create_workspace()[0]
        )
        require_disjoint_paths(output_dir, work_dir)
        if args.agent_bundle:
            require_within_workspace(
                args.agent_bundle,
                work_dir,
                label="--agent-bundle",
            )
        ledger = run(
            input_path,
            output_dir,
            common_terms=set(args.common_term),
            agent_bundle_path=args.agent_bundle.resolve()
            if args.agent_bundle
            else None,
            include_internal_traces=args.include_internal_traces,
            include_qa_annotated_document=args.qa_annotated_document,
            debug_telemetry=telemetry,
            work_dir=work_dir,
            emit_outputs=not args.prepare_only,
        )
    except (
        AgentBundleError,
        ProposalValidationError,
        SemanticReviewError,
        IntakeError,
        OSError,
        WorkspaceError,
        ValueError,
    ) as exc:
        if isinstance(exc, IntakeError):
            run_status = exc.run_status
        elif isinstance(exc, PermissionError):
            run_status = "not_run_policy_restricted"
        else:
            run_status = "failed"
        error = {
            "run_status": run_status,
            "capability_profile": "C3_PYTHON_STDLIB",
            "input": str(input_path),
            "work_dir": str(work_dir) if work_dir is not None else None,
            "workspace_created": workspace_created,
            "methods_run": [],
            "methods_not_run": [
                {
                    "method": "deterministic_docx_pipeline",
                    "reason": type(exc).__name__,
                }
            ],
            "error": str(exc),
        }
        print(json.dumps(error, ensure_ascii=True, sort_keys=True), file=sys.stderr)
        return 2

    if telemetry is not None:
        telemetry_path = output_dir / "definition-check-debug.json"
        try:
            write_debug_telemetry(
                telemetry_path,
                telemetry.to_dict(source_sha256=ledger.source.sha256),
            )
        except OSError as exc:
            print(
                json.dumps(
                    {
                        "run_status": "failed",
                        "error": str(exc),
                        "output_dir": str(output_dir),
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2

    html_path = output_dir / "definition-check.html"
    dashboard_available = html_path.is_file()
    summary = {
        "run_status": ledger.run_status,
        "result_available": dashboard_available,
        "message": (
            "Definition Check results are ready."
            if dashboard_available
            else "The Definition Check did not produce a complete result."
        ),
        "definitions": len(ledger.definitions),
        "usages": len(ledger.usages),
        "findings": len(ledger.findings),
        "semantic_review": ledger.semantic_review.status,
        "semantic_queue": ledger.semantic_review.queue_count,
        "occurrence_review": ledger.occurrence_review.status,
        "occurrence_queue": ledger.occurrence_review.queue_count,
        "reference_review": ledger.reference_review.status,
        "reference_queue": ledger.reference_review.queue_count,
        "output_dir": str(output_dir),
        "work_dir": str(work_dir),
        "workspace_created": workspace_created,
        "workspace_retention": (
            "temporary_delete_after_handoff"
            if workspace_created
            else "caller_managed_retained"
        ),
        "artifacts": {
            "markdown": {
                "path": str(output_dir / "definition-check.md"),
                "purpose": "developer_diagnostic_fallback",
            },
            "json": {
                "path": str(output_dir / "definition-check.json"),
                "purpose": "canonical_machine_ledger",
            },
            "semantic_review_envelopes": {
                "path": str(work_dir / "semantic-review-envelopes.json"),
                "purpose": "internal_workflow",
            },
            "occurrence_review_envelopes": {
                "path": str(work_dir / "occurrence-review-envelopes.json"),
                "purpose": "internal_workflow",
            },
            "reference_review_envelopes": {
                "path": str(work_dir / "reference-review-envelopes.json"),
                "purpose": "internal_workflow",
            },
            "review_packets": {
                "path": str(work_dir / "packets"),
                "purpose": "bounded_worker_inputs_and_private_supervisor_manifests",
            },
            "private_manifests": {
                "path": str(work_dir / "private"),
                "purpose": "supervisor_only_review_mapping",
            },
            "worker_responses": {
                "path": str(work_dir / "responses"),
                "purpose": "temporary_compact_worker_responses",
            },
        },
    }
    if dashboard_available:
        summary["primary_artifact"] = str(html_path)
        summary["artifacts"]["html"] = {
            "path": str(html_path),
            "purpose": "primary_lawyer_review",
        }
    if args.qa_annotated_document:
        summary["artifacts"]["annotated_document"] = {
            "path": str(output_dir / "annotated-document.html"),
            "purpose": "qa_source_order_review",
        }
    if telemetry is not None:
        summary["artifacts"]["debug_telemetry"] = {
            "path": str(output_dir / "definition-check-debug.json"),
            "purpose": "local_phase_timing_and_review_payload_token_estimates",
        }
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
