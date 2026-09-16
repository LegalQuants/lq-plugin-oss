"""Deterministic escalation-decision rule for conform mapping records.

Implements the rule stated in `SKILL.md`, "Escalation decision rules", and
restated in `references/agentic-mapping-protocol.md`:

- `false_friend`, `one_to_many`, `many_to_one`, `no_mapping`, `needs_review`,
  `insufficient_evidence`, `narrower_scope`, `broader_scope`, and
  `leakage_flag` always require escalation.
- `equivalent` requires escalation only when supporting evidence is
  incomplete; a fully evidenced `equivalent` mapping does not.

This is a pure function. It never depends on worker-reported confidence, and
no worker or supervisor step may bypass it. "Safe to propose" never means
silent application: even an unescalated `equivalent` mapping is only a
proposal in the redline, never an applied edit.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import MAPPING_TYPES, Escalation

_ALWAYS_ESCALATE_REASONS: dict[str, str] = {
    "narrower_scope": (
        "the destination term covers a narrower conceptual scope than the "
        "source clause; escalate for lawyer review before scope is lost"
    ),
    "broader_scope": (
        "the destination term covers a broader conceptual scope than the "
        "source clause; escalate for lawyer review before extra scope is "
        "silently swept in"
    ),
    "false_friend": (
        "a destination term shares a name or surface similarity with the "
        "source concept but denotes a different concept; escalate to prevent "
        "a false-friend substitution"
    ),
    "one_to_many": (
        "the source concept divides into multiple destination concepts; "
        "escalate so the lawyer confirms every destination term is required"
    ),
    "many_to_one": (
        "multiple source concepts collapse into one destination term; "
        "escalate so the lawyer confirms no scope is lost"
    ),
    "no_mapping": (
        "no destination concept was found for the source clause; escalate "
        "for lawyer drafting"
    ),
    "leakage_flag": (
        "core document language appears to carry over a source-document "
        "concept unadapted; escalate the possible precedent leakage"
    ),
    "needs_review": ("mapping evidence was ambiguous; escalate for lawyer review"),
    "insufficient_evidence": (
        "mapping evidence does not support a reliable decision; escalate "
        "for lawyer review"
    ),
}

_EQUIVALENT_INCOMPLETE_EVIDENCE_REASON = (
    "the equivalent mapping lacks complete supporting evidence; escalate before use"
)


@dataclass(frozen=True)
class EscalationDecision:
    """Result of applying the escalation rule to one mapping_type."""

    required: bool
    reason: str

    def to_escalation(self) -> Escalation:
        return Escalation(required=self.required, reason=self.reason)


def decide_escalation(
    mapping_type: str, *, evidence_complete: bool
) -> EscalationDecision:
    """Return whether `mapping_type` requires escalation, and why.

    `evidence_complete` is meaningful only for `equivalent`: every other
    mapping_type always escalates regardless of its evidence completeness,
    because the mapping itself already signals ambiguity, scope drift, or a
    substantive deal choice that belongs to the lawyer.
    """

    if mapping_type not in MAPPING_TYPES:
        raise ValueError(f"unsupported mapping_type: {mapping_type}")

    if mapping_type == "equivalent":
        if evidence_complete:
            return EscalationDecision(required=False, reason="")
        return EscalationDecision(
            required=True, reason=_EQUIVALENT_INCOMPLETE_EVIDENCE_REASON
        )

    return EscalationDecision(
        required=True, reason=_ALWAYS_ESCALATE_REASONS[mapping_type]
    )
