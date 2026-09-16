"""Deterministic reconciliation of append-only agent candidate proposals.

This module intentionally does not decide whether a term is semantically a
defined term.  It validates proposal history and records the mechanically
determined consequence of the latest submitted state for each candidate.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .models import CandidateProposal, ReviewTrace, stable_id


class ProposalValidationError(ValueError):
    """Raised when an append-only candidate revision history is invalid."""


@dataclass(frozen=True)
class CandidateDecision:
    """The supervisor's deterministic disposition of a current proposal."""

    candidate_id: str
    proposal_id: str
    term: str
    normalized_term: str
    disposition: str
    merged_into_candidate_id: str | None = None


@dataclass(frozen=True)
class ProposalReviewResult:
    """New review artifacts; callers retain ownership of their ledger facts."""

    latest_proposals: tuple[CandidateProposal, ...]
    decisions: tuple[CandidateDecision, ...]
    review_traces: tuple[ReviewTrace, ...]


def reconcile_proposals(proposals: Iterable[CandidateProposal]) -> ProposalReviewResult:
    """Validate, select, and mechanically reconcile append-only proposals.

    Exact ``normalized_term`` equality is the sole merge criterion.  In
    particular, visually similar terms are deliberately kept separate.  The
    function is pure: it neither changes proposals nor touches deterministic
    definitions, usages, or findings held by a caller's ledger.
    """

    records = tuple(proposals)
    _validate_proposals(records)
    latest = _latest_proposals(records)
    merge_leaders = _merge_leaders(latest)

    decisions: list[CandidateDecision] = []
    traces: list[ReviewTrace] = []
    for proposal in latest:
        leader = merge_leaders.get(proposal.candidate_id)
        if proposal.state == "candidate":
            if leader and leader.candidate_id != proposal.candidate_id:
                disposition = "merge"
                merged_into = leader.candidate_id
            else:
                disposition = "include"
                merged_into = None
        elif proposal.state == "not_a_candidate":
            disposition = "exclude"
            merged_into = None
        elif proposal.state == "needs_context":
            disposition = "escalate"
            merged_into = None
        else:  # CandidateProposal validates the only remaining state is abstain.
            disposition = "abstain"
            merged_into = None

        decisions.append(
            CandidateDecision(
                candidate_id=proposal.candidate_id,
                proposal_id=proposal.id,
                term=proposal.term,
                normalized_term=proposal.normalized_term,
                disposition=disposition,
                merged_into_candidate_id=merged_into,
            )
        )
        traces.append(_trace_for(proposal, disposition, merged_into))

    return ProposalReviewResult(
        latest_proposals=latest,
        decisions=tuple(decisions),
        review_traces=tuple(traces),
    )


def _validate_proposals(records: tuple[CandidateProposal, ...]) -> None:
    by_id = {proposal.id: proposal for proposal in records}
    if len(by_id) != len(records):
        raise ProposalValidationError("candidate proposal IDs must be unique")

    by_candidate: dict[str, list[CandidateProposal]] = {}
    for proposal in records:
        by_candidate.setdefault(proposal.candidate_id, []).append(proposal)

    for candidate_id, history in by_candidate.items():
        ordered = sorted(history, key=lambda proposal: (proposal.revision, proposal.id))
        revisions = [proposal.revision for proposal in ordered]
        expected = list(range(1, len(ordered) + 1))
        if revisions != expected:
            raise ProposalValidationError(
                f"candidate {candidate_id} revisions must be consecutive from 1"
            )
        for index, proposal in enumerate(ordered):
            if index == 0:
                if proposal.supersedes is not None:
                    raise ProposalValidationError(
                        f"candidate {candidate_id} revision 1 must not supersede another proposal"
                    )
                continue
            predecessor = ordered[index - 1]
            if proposal.supersedes != predecessor.id:
                raise ProposalValidationError(
                    f"candidate {candidate_id} revision {proposal.revision} must supersede "
                    f"its immediately preceding revision"
                )
            if by_id[proposal.supersedes].candidate_id != candidate_id:
                raise ProposalValidationError(
                    "proposal supersedes a different candidate"
                )


def _latest_proposals(
    records: tuple[CandidateProposal, ...],
) -> tuple[CandidateProposal, ...]:
    latest: dict[str, CandidateProposal] = {}
    for proposal in records:
        current = latest.get(proposal.candidate_id)
        if current is None or proposal.revision > current.revision:
            latest[proposal.candidate_id] = proposal
    return tuple(
        sorted(
            latest.values(),
            key=lambda proposal: (
                proposal.normalized_term,
                proposal.candidate_id,
                proposal.id,
            ),
        )
    )


def _merge_leaders(
    latest: tuple[CandidateProposal, ...],
) -> dict[str, CandidateProposal]:
    groups: dict[str, list[CandidateProposal]] = {}
    for proposal in latest:
        if proposal.state == "candidate":
            groups.setdefault(proposal.normalized_term, []).append(proposal)
    leaders: dict[str, CandidateProposal] = {}
    for group in groups.values():
        leader = min(group, key=lambda proposal: (proposal.candidate_id, proposal.id))
        for proposal in group:
            leaders[proposal.candidate_id] = leader
    return leaders


def _trace_for(
    proposal: CandidateProposal,
    disposition: str,
    merged_into: str | None,
) -> ReviewTrace:
    rationale = {
        "include": "Latest proposal retained without a deterministic exact duplicate.",
        "exclude": "Latest proposal explicitly reports not_a_candidate; no semantic judgment was added.",
        "escalate": "Latest proposal requests additional context; supervisor escalated without deciding it.",
        "abstain": "Latest proposal abstains; supervisor preserved the abstention without deciding it.",
        "merge": "Latest proposal is an exact normalized-term duplicate of the deterministically selected leader.",
    }[disposition]
    if merged_into:
        rationale = f"{rationale} Leader candidate: {merged_into}."
    return ReviewTrace(
        id=stable_id(
            "trace",
            "proposal_reducer",
            proposal.candidate_id,
            proposal.id,
            disposition,
            merged_into or "",
        ),
        subject_type="candidate_proposal",
        subject_id=proposal.id,
        action=disposition,
        agent_role="supervisor_reducer",
        rationale_summary=rationale,
        evidence_for=tuple(sorted(set(proposal.evidence_for))),
        evidence_against=tuple(sorted(set(proposal.evidence_against))),
        context_request_ids=tuple(sorted(set(proposal.context_request_ids))),
        reason_codes=(),
        confidence=proposal.confidence,
        uncertainty=(
            "Additional context requested by discovery worker."
            if disposition == "escalate"
            else "Discovery worker abstained from a decision."
            if disposition == "abstain"
            else None
        ),
        model_id=proposal.model_id,
        prompt_version=proposal.prompt_version,
    )
