"""Shared records and stable identifiers for the definition-check pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any

SCHEMA_VERSION = "0.14.0"
ENGINE_VERSION = "0.14.0"
RUN_STATUSES = frozenset(
    {
        "completed",
        "completed_reduced_assurance",
        "not_run_missing_capability",
        "not_run_policy_restricted",
        "not_run_unsupported_input",
        "partial_input",
        "insufficient_evidence",
        "failed",
    }
)
CAPABILITY_PROFILES = frozenset(
    {
        "C0_INSTRUCTION_ONLY",
        "C1_HOST_TEXT",
        "C2_LOCAL_COMMAND_NO_PYTHON",
        "C3_PYTHON_STDLIB",
        "C4_FULL_LOCAL",
        "C5_APPROVED_INTEGRATIONS",
    }
)
FINDING_KINDS = frozenset({"deterministic", "semantic"})
SEVERITIES = frozenset({"info", "low", "medium", "high"})
REVIEW_STATES = frozenset(
    {
        "open",
        "accepted",
        "rejected",
        "deferred",
        "needs_review",
        "insufficient_evidence",
    }
)
EVIDENCE_STANCES = frozenset({"supports", "contradicts", "context"})
CANDIDATE_STATES = frozenset(
    {"candidate", "not_a_candidate", "needs_context", "abstain"}
)
CONTEXT_REQUEST_TYPES = frozenset(
    {
        "expand_location",
        "search_term",
        "retrieve_definitions_section",
        "retrieve_reference",
        "retrieve_occurrences",
        "escalate_review",
    }
)
CONTEXT_REQUEST_STATUSES = frozenset(
    {"requested", "fulfilled", "failed", "denied", "budget_exhausted"}
)
TRACE_ACTIONS = frozenset({"include", "exclude", "merge", "escalate", "abstain"})
TRACE_VISIBILITIES = frozenset({"internal", "authorized_reviewer"})
SEMANTIC_DECISIONS = frozenset(
    {
        "confirmed_defined",
        "confirmed_alias",
        "confirmed_undefined",
        "confirmed_external_reference",
        "rejected_not_a_term",
        "rejected_proper_name",
        "needs_review",
        "insufficient_evidence",
    }
)
SCOPE_QUALIFICATIONS = frozenset({"none", "possible_inherited_definition"})
REVIEW_REASONS = frozenset(
    {
        "missing_external_evidence",
        "ambiguous_term_identity",
        "uncertain_occurrence_identity",
        "incomplete_source_context",
        "ambiguous_reference",
    }
)
SEMANTIC_REVIEW_STATUSES = frozenset({"not_run", "complete", "incomplete"})
OCCURRENCE_DECISIONS = frozenset(
    {
        "defined_term_use",
        "ordinary_language",
        "proper_name_component",
        "inconsistent_capitalization",
        "shadowed_by_overlapping_term",
        "needs_review",
        "insufficient_evidence",
    }
)
REFERENCE_DECISIONS = frozenset(
    {
        "resolved",
        "broken",
        "out_of_scope",
        "needs_review",
        "insufficient_evidence",
    }
)


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    digest = sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


@dataclass(frozen=True)
class Location:
    part: str
    block_id: str
    block_order: int
    char_start: int
    char_end: int

    def __post_init__(self) -> None:
        if (
            self.block_order < 0
            or self.char_start < 0
            or self.char_end < self.char_start
        ):
            raise ValueError("location offsets must be ordered non-negative integers")


def _validate_review_reason(
    decision: str, review_reason: str | None, *, owner: str
) -> None:
    unresolved = decision in {"needs_review", "insufficient_evidence"}
    if unresolved and review_reason not in REVIEW_REASONS:
        raise ValueError(f"{owner} unresolved decision requires a review reason")
    if not unresolved and review_reason is not None:
        raise ValueError(f"{owner} resolved decision must not carry a review reason")


def _validate_scope_qualification(
    qualification: str,
    target: str | None,
    evidence: tuple[Location, ...],
    *,
    owner: str,
) -> None:
    if qualification not in SCOPE_QUALIFICATIONS:
        raise ValueError(f"unsupported {owner} scope qualification: {qualification}")
    if qualification == "none":
        if target is not None or evidence:
            raise ValueError(f"{owner} unqualified record must not carry scope data")
        return
    if target is None or not target.strip() or not evidence:
        raise ValueError(f"{owner} scope qualification requires target and evidence")


@dataclass(frozen=True)
class Block:
    id: str
    part: str
    kind: str
    order: int
    text: str
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    cell_index: int | None = None

    def location(self, start: int = 0, end: int | None = None) -> Location:
        return Location(
            part=self.part,
            block_id=self.id,
            block_order=self.order,
            char_start=start,
            char_end=len(self.text) if end is None else end,
        )


@dataclass
class SourceDocument:
    document_id: str
    name: str
    sha256: str | None
    blocks: list[Block]
    coverage: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_source_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "name": self.name,
            "sha256": self.sha256,
            "coverage": self.coverage,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class DefinitionSpan:
    """One source-validated span expressing a term's assigned meaning."""

    definition_text: str
    location: Location

    def __post_init__(self) -> None:
        if not self.definition_text.strip():
            raise ValueError("definition span text must not be empty")


@dataclass(frozen=True)
class Definition:
    id: str
    term: str
    normalized_term: str
    definition_text: str
    location: Location
    pattern: str
    aliases: tuple[str, ...] = ()
    scope: str | None = None
    reference_target: str | None = None
    reference_location: Location | None = None


@dataclass(frozen=True)
class Usage:
    id: str
    term: str
    normalized_term: str
    observed_form: str
    location: Location
    is_definition_occurrence: bool = False
    variant_id: str | None = None


@dataclass(frozen=True)
class TermVariant:
    """A non-canonical source form and its instance-level mapping outcomes."""

    id: str
    term: str
    normalized_term: str
    observed_form: str
    variant_type: str
    mapping_status: str
    usage_ids: tuple[str, ...]
    mapped_usage_ids: tuple[str, ...] = ()
    rejected_usage_ids: tuple[str, ...] = ()
    shadowed_usage_ids: tuple[str, ...] = ()
    unresolved_usage_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.variant_type not in {
            "alias",
            "plural",
            "singular",
            "possessive",
            "capitalization",
            "spacing",
            "composite",
        }:
            raise ValueError(f"unsupported variant type: {self.variant_type}")
        if self.mapping_status not in {
            "mapped",
            "mixed",
            "rejected",
            "shadowed",
            "unresolved",
        }:
            raise ValueError(
                f"unsupported variant mapping status: {self.mapping_status}"
            )
        if not self.usage_ids:
            raise ValueError("term variant must reference at least one usage")
        classified_items = (
            *self.mapped_usage_ids,
            *self.rejected_usage_ids,
            *self.shadowed_usage_ids,
            *self.unresolved_usage_ids,
        )
        if len(classified_items) != len(set(classified_items)) or set(
            classified_items
        ) != set(self.usage_ids):
            raise ValueError("term variant instance outcomes must cover every usage")


@dataclass(frozen=True)
class Finding:
    id: str
    rule_id: str
    kind: str
    severity: str
    message: str
    normalized_term: str | None
    evidence: tuple[Location, ...]
    confidence: float | None = None
    review_state: str = "open"
    scope_qualification: str = "none"
    scope_target: str | None = None
    scope_evidence: tuple[Location, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in FINDING_KINDS:
            raise ValueError(f"unsupported finding kind: {self.kind}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"unsupported severity: {self.severity}")
        if self.review_state not in REVIEW_STATES:
            raise ValueError(f"unsupported review state: {self.review_state}")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        _validate_scope_qualification(
            self.scope_qualification,
            self.scope_target,
            self.scope_evidence,
            owner="finding",
        )


@dataclass(frozen=True)
class EvidenceItem:
    id: str
    location: Location
    excerpt: str
    stance: str
    method: str

    def __post_init__(self) -> None:
        if self.stance not in EVIDENCE_STANCES:
            raise ValueError(f"unsupported evidence stance: {self.stance}")
        if not self.excerpt.strip():
            raise ValueError("evidence excerpt must not be empty")
        if len(self.excerpt) > 4000:
            raise ValueError("evidence excerpt exceeds the 4000 character bound")
        if not self.method.strip():
            raise ValueError("evidence method must not be empty")


@dataclass(frozen=True)
class ContextRequest:
    id: str
    candidate_id: str
    request_type: str
    query: str
    reason: str
    requested_by: str
    status: str = "requested"
    hop: int = 1
    max_results: int = 20
    result_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.request_type not in CONTEXT_REQUEST_TYPES:
            raise ValueError(f"unsupported context request type: {self.request_type}")
        if self.status not in CONTEXT_REQUEST_STATUSES:
            raise ValueError(f"unsupported context request status: {self.status}")
        if (
            not self.query.strip()
            or not self.reason.strip()
            or not self.requested_by.strip()
        ):
            raise ValueError(
                "context request query, reason, and requested_by are required"
            )
        if self.hop < 1:
            raise ValueError("context request hop must be at least 1")
        if not 1 <= self.max_results <= 100:
            raise ValueError("context request max_results must be between 1 and 100")


@dataclass(frozen=True)
class LexicalCandidateObservation:
    """Deterministic source observation with no semantic judgment fields."""

    id: str
    term: str
    normalized_term: str
    location: Location
    detector: str
    detector_version: str
    observation_type: str

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.id,
                self.term,
                self.normalized_term,
                self.detector,
                self.detector_version,
                self.observation_type,
            )
        ):
            raise ValueError("lexical observation fields are required")


@dataclass(frozen=True)
class CandidateProposal:
    id: str
    candidate_id: str
    term: str
    normalized_term: str
    location: Location
    state: str
    agent_role: str
    revision: int
    rationale_summary: str
    confidence: float | None = None
    definition_text: str | None = None
    evidence_for: tuple[str, ...] = ()
    evidence_against: tuple[str, ...] = ()
    context_request_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    supersedes: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None

    def __post_init__(self) -> None:
        if self.state not in CANDIDATE_STATES:
            raise ValueError(f"unsupported candidate state: {self.state}")
        if (
            not self.term.strip()
            or not self.normalized_term.strip()
            or not self.agent_role.strip()
        ):
            raise ValueError(
                "candidate term, normalized term, and agent_role are required"
            )
        if self.revision < 1:
            raise ValueError("candidate revision must be at least 1")
        if not self.rationale_summary.strip() or len(self.rationale_summary) > 2000:
            raise ValueError(
                "candidate rationale_summary must contain 1 to 2000 characters"
            )
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class ReviewTrace:
    id: str
    subject_type: str
    subject_id: str
    action: str
    agent_role: str
    rationale_summary: str
    evidence_for: tuple[str, ...] = ()
    evidence_against: tuple[str, ...] = ()
    context_request_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    confidence: float | None = None
    uncertainty: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    visibility: str = "internal"

    def __post_init__(self) -> None:
        if self.action not in TRACE_ACTIONS:
            raise ValueError(f"unsupported trace action: {self.action}")
        if self.visibility not in TRACE_VISIBILITIES:
            raise ValueError(f"unsupported trace visibility: {self.visibility}")
        if (
            not self.subject_type.strip()
            or not self.subject_id.strip()
            or not self.agent_role.strip()
        ):
            raise ValueError(
                "trace subject_type, subject_id, and agent_role are required"
            )
        if not self.rationale_summary.strip() or len(self.rationale_summary) > 2000:
            raise ValueError(
                "trace rationale_summary must contain 1 to 2000 characters"
            )
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class TermCandidate:
    """Supervisor-side queue record; raw provenance is never sent to a reviewer."""

    review_id: str
    term: str
    normalized_term: str
    locations: tuple[Location, ...]
    origins: tuple[str, ...]
    definition_ids: tuple[str, ...] = ()
    finding_ids: tuple[str, ...] = ()
    observation_ids: tuple[str, ...] = ()
    proposal_ids: tuple[str, ...] = ()
    structural_hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not self.review_id.strip()
            or not self.term.strip()
            or not self.normalized_term.strip()
        ):
            raise ValueError(
                "term candidate review_id, term, and normalized_term are required"
            )
        if not self.locations or not self.origins:
            raise ValueError("term candidate locations and origins are required")


@dataclass(frozen=True)
class SemanticAdjudication:
    """Authoritative reviewer-produced disposition for one opaque queue item."""

    id: str
    review_id: str
    decision: str
    evidence: tuple[Location, ...]
    rationale_summary: str
    reason_codes: tuple[str, ...]
    confidence: float | None
    agent_role: str
    definition_text: str | None = None
    definition_location: Location | None = None
    canonical_term: str | None = None
    canonical_review_id: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    definition_spans: tuple[DefinitionSpan, ...] = ()
    review_reason: str | None = None
    scope_qualification: str = "none"
    scope_target: str | None = None
    scope_evidence: tuple[Location, ...] = ()

    def __post_init__(self) -> None:
        if self.decision not in SEMANTIC_DECISIONS:
            raise ValueError(f"unsupported semantic decision: {self.decision}")
        if (
            not self.id.strip()
            or not self.review_id.strip()
            or not self.agent_role.strip()
        ):
            raise ValueError(
                "semantic adjudication id, review_id, and agent_role are required"
            )
        if not self.rationale_summary.strip() or len(self.rationale_summary) > 2000:
            raise ValueError(
                "semantic rationale_summary must contain 1 to 2000 characters"
            )
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        _validate_review_reason(self.decision, self.review_reason, owner="semantic")
        _validate_scope_qualification(
            self.scope_qualification,
            self.scope_target,
            self.scope_evidence,
            owner="semantic adjudication",
        )
        if (
            self.scope_qualification == "possible_inherited_definition"
            and self.decision != "confirmed_undefined"
        ):
            raise ValueError(
                "only confirmed undefined adjudications may carry an inherited-definition qualifier"
            )
        if self.decision == "confirmed_defined":
            spans = self.definition_spans
            if spans:
                first = spans[0]
                if self.definition_text is None and self.definition_location is None:
                    object.__setattr__(self, "definition_text", first.definition_text)
                    object.__setattr__(self, "definition_location", first.location)
                elif (self.definition_text, self.definition_location) != (
                    first.definition_text,
                    first.location,
                ):
                    raise ValueError(
                        "legacy definition fields must match the first definition span"
                    )
            elif self.definition_text and self.definition_location is not None:
                object.__setattr__(
                    self,
                    "definition_spans",
                    (DefinitionSpan(self.definition_text, self.definition_location),),
                )
            else:
                raise ValueError(
                    "confirmed defined adjudications require source-validated definition spans"
                )
        elif (
            self.definition_spans
            or self.definition_text is not None
            or self.definition_location is not None
        ):
            raise ValueError(
                "only confirmed defined adjudications may include definition spans"
            )
        if self.decision == "confirmed_alias":
            if not self.canonical_term or not self.canonical_review_id:
                raise ValueError(
                    "confirmed alias adjudications require a canonical term and review ID"
                )
        elif self.canonical_term is not None or self.canonical_review_id is not None:
            raise ValueError(
                "only confirmed alias adjudications may identify a canonical term"
            )


@dataclass(frozen=True)
class SemanticReviewSummary:
    status: str
    queue_count: int
    decided_count: int
    unresolved_count: int
    review_execution: str = "external_bundle"
    review_id_namespace: str = "opaque-v1"

    def __post_init__(self) -> None:
        if self.status not in SEMANTIC_REVIEW_STATUSES:
            raise ValueError(f"unsupported semantic review status: {self.status}")
        if min(self.queue_count, self.decided_count, self.unresolved_count) < 0:
            raise ValueError("semantic review counts must be non-negative")
        if self.decided_count > self.queue_count:
            raise ValueError("semantic review decided_count exceeds queue_count")


@dataclass(frozen=True)
class ReferenceReviewSummary(SemanticReviewSummary):
    """Completion accounting for the scoped definition-reference queue."""

    review_id_namespace: str = "opaque-reference-v1"


@dataclass(frozen=True)
class ReferenceCandidate:
    """One definition reference requiring an explicit scoped disposition."""

    review_id: str
    definition_id: str
    term: str
    normalized_term: str
    reference_target: str
    location: Location
    reference_location: Location
    scope: str = "document"

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.review_id,
                self.definition_id,
                self.term,
                self.normalized_term,
                self.reference_target,
                self.scope,
            )
        ):
            raise ValueError("reference candidate identity and target are required")


@dataclass(frozen=True)
class ReferenceAdjudication:
    """Supervisor-owned disposition of one scoped definition reference."""

    id: str
    review_id: str
    definition_id: str
    decision: str
    evidence: tuple[Location, ...]
    rationale_summary: str
    reason_codes: tuple[str, ...]
    confidence: float | None
    agent_role: str
    model_id: str | None = None
    prompt_version: str | None = None
    review_reason: str | None = None

    def __post_init__(self) -> None:
        if self.decision not in REFERENCE_DECISIONS:
            raise ValueError(f"unsupported reference decision: {self.decision}")
        if not all(
            value.strip()
            for value in (self.id, self.review_id, self.definition_id, self.agent_role)
        ):
            raise ValueError(
                "reference adjudication identity and agent_role are required"
            )
        if not self.evidence:
            raise ValueError("reference adjudication must cite source evidence")
        if not self.rationale_summary.strip() or len(self.rationale_summary) > 2000:
            raise ValueError(
                "reference rationale_summary must contain 1 to 2000 characters"
            )
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        _validate_review_reason(self.decision, self.review_reason, owner="reference")


@dataclass(frozen=True)
class OccurrenceCandidate:
    """Supervisor mapping for a context-sensitive lexical usage candidate."""

    review_id: str
    usage_id: str
    term: str
    observed_form: str
    location: Location
    variant_id: str | None = None
    collision_id: str | None = None
    competing_usage_ids: tuple[str, ...] = ()
    competing_terms: tuple[str, ...] = ()
    competing_locations: tuple[Location, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.review_id,
                self.usage_id,
                self.term,
                self.observed_form,
            )
        ):
            raise ValueError(
                "occurrence candidate identity and term fields are required"
            )
        if bool(self.collision_id) != bool(self.competing_usage_ids):
            raise ValueError(
                "occurrence collision ID and competing usage IDs must be supplied together"
            )
        if self.competing_usage_ids and not (
            len(self.competing_usage_ids)
            == len(self.competing_terms)
            == len(self.competing_locations)
        ):
            raise ValueError(
                "occurrence competing usage IDs, terms, and locations must have equal length"
            )


@dataclass(frozen=True)
class OccurrenceCollision:
    """Overlapping lexical usages awaiting or recording semantic resolution."""

    id: str
    location: Location
    usage_ids: tuple[str, ...]
    normalized_terms: tuple[str, ...]
    mapped_usage_ids: tuple[str, ...] = ()
    rejected_usage_ids: tuple[str, ...] = ()
    shadowed_usage_ids: tuple[str, ...] = ()
    unresolved_usage_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip() or len(self.usage_ids) < 2:
            raise ValueError(
                "occurrence collision requires an ID and at least two usages"
            )
        if len(set(self.normalized_terms)) < 2:
            raise ValueError(
                "occurrence collision requires at least two canonical terms"
            )
        classified_items = (
            *self.mapped_usage_ids,
            *self.rejected_usage_ids,
            *self.shadowed_usage_ids,
            *self.unresolved_usage_ids,
        )
        if len(classified_items) != len(set(classified_items)) or set(
            classified_items
        ) != set(self.usage_ids):
            raise ValueError("occurrence collision outcomes must cover every usage")


@dataclass(frozen=True)
class OccurrenceAdjudication:
    """Semantic disposition of one potentially ambiguous lexical occurrence."""

    id: str
    review_id: str
    usage_id: str
    decision: str
    rationale_summary: str
    reason_codes: tuple[str, ...]
    confidence: float | None
    agent_role: str
    model_id: str | None = None
    prompt_version: str | None = None
    review_reason: str | None = None

    def __post_init__(self) -> None:
        if self.decision not in OCCURRENCE_DECISIONS:
            raise ValueError(f"unsupported occurrence decision: {self.decision}")
        if not all(
            value.strip()
            for value in (
                self.id,
                self.review_id,
                self.usage_id,
                self.agent_role,
            )
        ):
            raise ValueError(
                "occurrence adjudication identity and agent_role are required"
            )
        if not self.rationale_summary.strip() or len(self.rationale_summary) > 2000:
            raise ValueError(
                "occurrence rationale_summary must contain 1 to 2000 characters"
            )
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        _validate_review_reason(self.decision, self.review_reason, owner="occurrence")


@dataclass
class Ledger:
    source: SourceDocument
    capability_profile: str
    run_status: str = "completed"
    methods_run: list[str] = field(default_factory=list)
    methods_not_run: list[dict[str, str]] = field(default_factory=list)
    definitions: list[Definition] = field(default_factory=list)
    term_variants: list[TermVariant] = field(default_factory=list)
    usages: list[Usage] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    lexical_observations: list[LexicalCandidateObservation] = field(
        default_factory=list
    )
    candidate_proposals: list[CandidateProposal] = field(default_factory=list)
    context_requests: list[ContextRequest] = field(default_factory=list)
    review_traces: list[ReviewTrace] = field(default_factory=list)
    term_candidates: list[TermCandidate] = field(default_factory=list)
    semantic_adjudications: list[SemanticAdjudication] = field(default_factory=list)
    semantic_review: SemanticReviewSummary = field(
        default_factory=lambda: SemanticReviewSummary("not_run", 0, 0, 0)
    )
    occurrence_candidates: list[OccurrenceCandidate] = field(default_factory=list)
    occurrence_collisions: list[OccurrenceCollision] = field(default_factory=list)
    occurrence_adjudications: list[OccurrenceAdjudication] = field(default_factory=list)
    occurrence_review: SemanticReviewSummary = field(
        default_factory=lambda: SemanticReviewSummary("not_run", 0, 0, 0)
    )
    reference_candidates: list[ReferenceCandidate] = field(default_factory=list)
    reference_adjudications: list[ReferenceAdjudication] = field(default_factory=list)
    reference_review: ReferenceReviewSummary = field(
        default_factory=lambda: ReferenceReviewSummary("not_run", 0, 0, 0)
    )
    limitations: list[str] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION
    engine_version: str = ENGINE_VERSION

    def __post_init__(self) -> None:
        if self.run_status not in RUN_STATUSES:
            raise ValueError(f"unsupported run status: {self.run_status}")
        if self.capability_profile not in CAPABILITY_PROFILES:
            raise ValueError(
                f"unsupported capability profile: {self.capability_profile}"
            )

    def validate_references(self) -> None:
        collections = {
            "evidence": [item.id for item in self.evidence],
            "lexical_observations": [item.id for item in self.lexical_observations],
            "candidate_proposals": [item.id for item in self.candidate_proposals],
            "context_requests": [item.id for item in self.context_requests],
            "review_traces": [item.id for item in self.review_traces],
            "term_candidates": [item.review_id for item in self.term_candidates],
            "semantic_adjudications": [item.id for item in self.semantic_adjudications],
            "occurrence_candidates": [
                item.review_id for item in self.occurrence_candidates
            ],
            "occurrence_collisions": [item.id for item in self.occurrence_collisions],
            "occurrence_adjudications": [
                item.id for item in self.occurrence_adjudications
            ],
            "reference_candidates": [
                item.review_id for item in self.reference_candidates
            ],
            "reference_adjudications": [
                item.id for item in self.reference_adjudications
            ],
            "term_variants": [item.id for item in self.term_variants],
        }
        for name, identifiers in collections.items():
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"duplicate IDs in {name}")

        evidence_ids = set(collections["evidence"])
        request_ids = set(collections["context_requests"])
        proposal_ids = set(collections["candidate_proposals"])
        observation_ids = set(collections["lexical_observations"])
        review_ids = set(collections["term_candidates"])
        usage_ids = {item.id for item in self.usages}
        variant_ids = set(collections["term_variants"])
        occurrence_review_ids = set(collections["occurrence_candidates"])
        collision_ids = set(collections["occurrence_collisions"])
        reference_review_ids = set(collections["reference_candidates"])
        definition_ids = {item.id for item in self.definitions}

        if self.source.blocks:
            blocks = {item.id: item for item in self.source.blocks}

            def validate_location(location: Location, owner: str) -> None:
                block = blocks.get(location.block_id)
                if block is None:
                    raise ValueError(f"{owner} references a block outside the source")
                if location.part != block.part or location.block_order != block.order:
                    raise ValueError(
                        f"{owner} location metadata disagrees with the source block"
                    )
                if location.char_end > len(block.text):
                    raise ValueError(f"{owner} location exceeds the source block")

            for definition in self.definitions:
                validate_location(definition.location, definition.id)
                if definition.reference_location is not None:
                    validate_location(
                        definition.reference_location,
                        f"{definition.id}.reference_location",
                    )
                    if not definition.reference_target:
                        raise ValueError(
                            f"{definition.id} has a reference location without a target"
                        )
                    block = blocks[definition.reference_location.block_id]
                    source_text = block.text[
                        definition.reference_location.char_start : definition.reference_location.char_end
                    ]
                    if source_text != definition.reference_target:
                        raise ValueError(
                            f"{definition.id} reference target disagrees with its source span"
                        )
            for usage in self.usages:
                validate_location(usage.location, usage.id)
            for finding in self.findings:
                for location in finding.evidence:
                    validate_location(location, finding.id)
            for item in self.evidence:
                validate_location(item.location, item.id)
            for observation in self.lexical_observations:
                validate_location(observation.location, observation.id)
            for proposal in self.candidate_proposals:
                validate_location(proposal.location, proposal.id)
            for candidate in self.term_candidates:
                for location in candidate.locations:
                    validate_location(location, candidate.review_id)
            for adjudication in self.semantic_adjudications:
                for location in adjudication.evidence:
                    validate_location(location, adjudication.id)
                for definition_span in adjudication.definition_spans:
                    validate_location(definition_span.location, adjudication.id)
                    block = blocks[definition_span.location.block_id]
                    source_text = block.text[
                        definition_span.location.char_start : definition_span.location.char_end
                    ]
                    if source_text != definition_span.definition_text:
                        raise ValueError(
                            f"{adjudication.id} definition span text disagrees with its source span"
                        )
            for candidate in self.occurrence_candidates:
                validate_location(candidate.location, candidate.review_id)
                for location in candidate.competing_locations:
                    validate_location(location, candidate.review_id)
            for collision in self.occurrence_collisions:
                validate_location(collision.location, collision.id)
            for candidate in self.reference_candidates:
                validate_location(candidate.location, candidate.review_id)
                validate_location(
                    candidate.reference_location,
                    f"{candidate.review_id}.reference_location",
                )
                block = blocks[candidate.reference_location.block_id]
                source_text = block.text[
                    candidate.reference_location.char_start : candidate.reference_location.char_end
                ]
                if source_text != candidate.reference_target:
                    raise ValueError(
                        f"{candidate.review_id} reference target disagrees with its source span"
                    )
            for adjudication in self.reference_adjudications:
                for location in adjudication.evidence:
                    validate_location(location, adjudication.id)

        for request in self.context_requests:
            missing = set(request.result_evidence_ids) - evidence_ids
            if missing:
                raise ValueError(
                    f"context request {request.id} references missing evidence: {sorted(missing)}"
                )
        for proposal in self.candidate_proposals:
            missing_evidence = (
                set((*proposal.evidence_for, *proposal.evidence_against)) - evidence_ids
            )
            missing_requests = set(proposal.context_request_ids) - request_ids
            if missing_evidence or missing_requests:
                raise ValueError(
                    f"candidate proposal {proposal.id} has unresolved references"
                )
            if proposal.supersedes and proposal.supersedes not in proposal_ids:
                raise ValueError(
                    f"candidate proposal {proposal.id} supersedes a missing proposal"
                )
        for candidate in self.term_candidates:
            missing_observations = set(candidate.observation_ids) - observation_ids
            missing_proposals = set(candidate.proposal_ids) - proposal_ids
            if missing_observations or missing_proposals:
                raise ValueError(
                    f"term candidate {candidate.review_id} has unresolved source records"
                )
        for trace in self.review_traces:
            missing_evidence = (
                set((*trace.evidence_for, *trace.evidence_against)) - evidence_ids
            )
            missing_requests = set(trace.context_request_ids) - request_ids
            if missing_evidence or missing_requests:
                raise ValueError(f"review trace {trace.id} has unresolved references")
        adjudicated_review_ids = [
            item.review_id for item in self.semantic_adjudications
        ]
        if len(adjudicated_review_ids) != len(set(adjudicated_review_ids)):
            raise ValueError(
                "semantic adjudications must contain at most one decision per review_id"
            )
        missing_candidates = set(adjudicated_review_ids) - review_ids
        if missing_candidates:
            raise ValueError(
                f"semantic adjudications reference missing queue items: {sorted(missing_candidates)}"
            )
        semantic_by_review = {
            item.review_id: item for item in self.semantic_adjudications
        }
        for item in self.semantic_adjudications:
            if item.decision != "confirmed_alias":
                continue
            target = semantic_by_review.get(item.canonical_review_id or "")
            if target is None or target.decision != "confirmed_defined":
                raise ValueError(
                    f"semantic alias {item.id} does not reference a confirmed definition"
                )
        if self.semantic_review.queue_count != len(self.term_candidates):
            raise ValueError(
                "semantic review queue_count disagrees with term_candidates"
            )
        if self.semantic_review.decided_count != len(self.semantic_adjudications):
            raise ValueError(
                "semantic review decided_count disagrees with semantic_adjudications"
            )
        if (
            self.semantic_review.status == "complete"
            and set(adjudicated_review_ids) != review_ids
        ):
            raise ValueError(
                "complete semantic review must adjudicate every queue item"
            )
        for candidate in self.occurrence_candidates:
            if candidate.usage_id not in usage_ids:
                raise ValueError(
                    f"occurrence candidate {candidate.review_id} references a missing usage"
                )
            if candidate.collision_id is not None:
                if candidate.collision_id not in collision_ids:
                    raise ValueError(
                        f"occurrence candidate {candidate.review_id} references a missing collision"
                    )
                if set(candidate.competing_usage_ids) - usage_ids:
                    raise ValueError(
                        f"occurrence candidate {candidate.review_id} references missing competing usages"
                    )
        for collision in self.occurrence_collisions:
            if set(collision.usage_ids) - usage_ids:
                raise ValueError(
                    f"occurrence collision {collision.id} references missing usages"
                )
            if set(
                (
                    *collision.mapped_usage_ids,
                    *collision.rejected_usage_ids,
                    *collision.shadowed_usage_ids,
                    *collision.unresolved_usage_ids,
                )
            ) - set(collision.usage_ids):
                raise ValueError(
                    f"occurrence collision {collision.id} outcomes reference non-member usages"
                )
        if self.occurrence_review.status == "complete":
            queued_usage_ids = {item.usage_id for item in self.occurrence_candidates}
            reviewable_usage_ids = {
                item.id for item in self.usages if not item.is_definition_occurrence
            }
            if queued_usage_ids != reviewable_usage_ids:
                raise ValueError(
                    "complete occurrence review must queue every non-definition usage; "
                    f"missing={sorted(reviewable_usage_ids - queued_usage_ids)}, "
                    f"extra={sorted(queued_usage_ids - reviewable_usage_ids)}"
                )
        for usage in self.usages:
            if usage.variant_id is not None and usage.variant_id not in variant_ids:
                raise ValueError(f"usage {usage.id} references a missing term variant")
        for variant in self.term_variants:
            if set(variant.usage_ids) - usage_ids:
                raise ValueError(f"term variant {variant.id} references missing usages")
            for usage_id in variant.usage_ids:
                usage = next(item for item in self.usages if item.id == usage_id)
                if usage.variant_id != variant.id:
                    raise ValueError(
                        f"term variant {variant.id} disagrees with usage {usage_id}"
                    )
        occurrence_adjudicated_ids = [
            item.review_id for item in self.occurrence_adjudications
        ]
        if len(occurrence_adjudicated_ids) != len(set(occurrence_adjudicated_ids)):
            raise ValueError(
                "occurrence adjudications must contain at most one decision per review_id"
            )
        candidate_by_review = {
            item.review_id: item for item in self.occurrence_candidates
        }
        for item in self.occurrence_adjudications:
            candidate = candidate_by_review.get(item.review_id)
            if candidate is None or candidate.usage_id != item.usage_id:
                raise ValueError(
                    f"occurrence adjudication {item.id} has no matching candidate"
                )
        if self.occurrence_review.queue_count != len(self.occurrence_candidates):
            raise ValueError(
                "occurrence review queue_count disagrees with occurrence_candidates"
            )
        if self.occurrence_review.decided_count != len(self.occurrence_adjudications):
            raise ValueError(
                "occurrence review decided_count disagrees with occurrence_adjudications"
            )
        if (
            self.occurrence_review.status == "complete"
            and set(occurrence_adjudicated_ids) != occurrence_review_ids
        ):
            raise ValueError(
                "complete occurrence review must adjudicate every queued occurrence"
            )
        for candidate in self.reference_candidates:
            if candidate.definition_id not in definition_ids:
                raise ValueError(
                    f"reference candidate {candidate.review_id} references a missing definition"
                )
        reference_definition_ids = {
            item.id for item in self.definitions if item.reference_target
        }
        queued_reference_definition_ids = [
            item.definition_id for item in self.reference_candidates
        ]
        if len(queued_reference_definition_ids) != len(
            set(queued_reference_definition_ids)
        ):
            raise ValueError(
                "reference candidates must contain at most one item per definition"
            )
        if set(queued_reference_definition_ids) != reference_definition_ids:
            raise ValueError(
                "reference candidates must cover every definition with a reference target"
            )
        reference_adjudicated_ids = [
            item.review_id for item in self.reference_adjudications
        ]
        if len(reference_adjudicated_ids) != len(set(reference_adjudicated_ids)):
            raise ValueError(
                "reference adjudications must contain at most one decision per review_id"
            )
        reference_by_review = {
            item.review_id: item for item in self.reference_candidates
        }
        for item in self.reference_adjudications:
            candidate = reference_by_review.get(item.review_id)
            if candidate is None or candidate.definition_id != item.definition_id:
                raise ValueError(
                    f"reference adjudication {item.id} has no matching candidate"
                )
        if self.reference_review.queue_count != len(self.reference_candidates):
            raise ValueError(
                "reference review queue_count disagrees with reference_candidates"
            )
        if self.reference_review.decided_count != len(self.reference_adjudications):
            raise ValueError(
                "reference review decided_count disagrees with reference_adjudications"
            )
        if (
            self.reference_review.status == "complete"
            and set(reference_adjudicated_ids) != reference_review_ids
        ):
            raise ValueError(
                "complete reference review must adjudicate every queued reference"
            )

    def to_dict(self) -> dict[str, Any]:
        self.validate_references()
        return {
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
            "run_status": self.run_status,
            "capability_profile": self.capability_profile,
            "source": self.source.to_source_dict(),
            "methods_run": list(self.methods_run),
            "methods_not_run": list(self.methods_not_run),
            "definitions": [asdict(item) for item in self.definitions],
            "term_variants": [asdict(item) for item in self.term_variants],
            "usages": [asdict(item) for item in self.usages],
            "findings": [asdict(item) for item in self.findings],
            "evidence": [asdict(item) for item in self.evidence],
            "lexical_observations": [
                asdict(item) for item in self.lexical_observations
            ],
            "candidate_proposals": [asdict(item) for item in self.candidate_proposals],
            "context_requests": [asdict(item) for item in self.context_requests],
            "review_traces": [asdict(item) for item in self.review_traces],
            "term_candidates": [asdict(item) for item in self.term_candidates],
            "semantic_adjudications": [
                asdict(item) for item in self.semantic_adjudications
            ],
            "semantic_review": asdict(self.semantic_review),
            "occurrence_candidates": [
                asdict(item) for item in self.occurrence_candidates
            ],
            "occurrence_collisions": [
                asdict(item) for item in self.occurrence_collisions
            ],
            "occurrence_adjudications": [
                asdict(item) for item in self.occurrence_adjudications
            ],
            "occurrence_review": asdict(self.occurrence_review),
            "reference_candidates": [
                asdict(item) for item in self.reference_candidates
            ],
            "reference_adjudications": [
                asdict(item) for item in self.reference_adjudications
            ],
            "reference_review": asdict(self.reference_review),
            "limitations": list(self.limitations),
        }
