"""Typed dataclasses for the conform mapping record.

These mirror the shape of `../../references/conform-mapping-schema.json` and
`../../references/conform-run-schema.json`. They are intentionally small and
dependency-free: `/conform` does not vendor a JSON Schema validator, so these
dataclasses carry the invariants a schema would otherwise enforce, and
`to_dict()` on each produces the exact schema-conforming shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

MAPPING_TYPES = frozenset(
    {
        "equivalent",
        "narrower_scope",
        "broader_scope",
        "false_friend",
        "one_to_many",
        "many_to_one",
        "no_mapping",
        "leakage_flag",
        "needs_review",
        "insufficient_evidence",
    }
)

EVIDENCE_STANCES = frozenset({"supports", "contradicts", "context"})
DOCUMENT_ROLES = frozenset({"source", "core"})

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

MODES = frozenset({"conform_selected_text", "precedent_leakage_check"})


def stable_id(prefix: str, *parts: object) -> str:
    """Deterministic identifier, matching definition-check's stable_id shape."""

    payload = "\x1f".join(str(part) for part in parts)
    digest = sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


@dataclass(frozen=True)
class SourceSpan:
    """A document-qualified location, resolvable in either the source or core document."""

    document_role: str
    document_id: str
    part: str
    block_id: str
    block_order: int
    char_start: int
    char_end: int

    def __post_init__(self) -> None:
        if self.document_role not in DOCUMENT_ROLES:
            raise ValueError(f"unsupported document_role: {self.document_role}")
        if (
            self.block_order < 0
            or self.char_start < 0
            or self.char_end < self.char_start
        ):
            raise ValueError(
                "source span offsets must be ordered non-negative integers"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_role": self.document_role,
            "document_id": self.document_id,
            "part": self.part,
            "block_id": self.block_id,
            "block_order": self.block_order,
            "char_start": self.char_start,
            "char_end": self.char_end,
        }


@dataclass(frozen=True)
class EvidenceItem:
    """One bounded excerpt cited in support of, or against, a mapping decision."""

    location: SourceSpan
    excerpt: str
    stance: str

    def __post_init__(self) -> None:
        if self.stance not in EVIDENCE_STANCES:
            raise ValueError(f"unsupported evidence stance: {self.stance}")
        if not self.excerpt.strip():
            raise ValueError("evidence excerpt must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "location": self.location.to_dict(),
            "excerpt": self.excerpt,
            "stance": self.stance,
        }


@dataclass(frozen=True)
class DestinationTerm:
    """One core-document expression proposed to carry a source concept."""

    term: str
    location: SourceSpan

    def __post_init__(self) -> None:
        if not self.term.strip():
            raise ValueError("destination term must not be empty")
        if self.location.document_role != "core":
            raise ValueError("destination term location must be in the core document")

    def to_dict(self) -> dict[str, Any]:
        return {"term": self.term, "location": self.location.to_dict()}


@dataclass(frozen=True)
class Escalation:
    """Whether a mapping requires lawyer escalation, and why."""

    required: bool
    reason: str = ""

    def __post_init__(self) -> None:
        if self.required and not self.reason.strip():
            raise ValueError("an escalation marked required must carry a reason")
        if not self.required and self.reason.strip():
            raise ValueError("an escalation not required must not carry a reason")

    def to_dict(self) -> dict[str, Any]:
        return {"required": self.required, "reason": self.reason}


@dataclass(frozen=True)
class MappingRecord:
    """One evidence-backed mapping between a source concept and a core-document expression."""

    mapping_id: str
    source_span: SourceSpan
    destination_terms: tuple[DestinationTerm, ...]
    mapping_type: str
    evidence: tuple[EvidenceItem, ...]
    escalation: Escalation
    adjudication_id: str | None = None
    reviewer_note: str = ""

    def __post_init__(self) -> None:
        if self.mapping_type not in MAPPING_TYPES:
            raise ValueError(f"unsupported mapping_type: {self.mapping_type}")
        if self.source_span.document_role != "source":
            raise ValueError("mapping source_span must be in the source document")
        if self.mapping_type == "no_mapping" and self.destination_terms:
            raise ValueError("no_mapping must not carry destination terms")
        if (
            self.mapping_type != "no_mapping"
            and not self.destination_terms
            and self.mapping_type
            not in (
                "needs_review",
                "insufficient_evidence",
            )
        ):
            raise ValueError(
                f"{self.mapping_type} mappings require at least one destination term"
            )
        if self.mapping_type == "one_to_many" and len(self.destination_terms) < 2:
            raise ValueError(
                "one_to_many mappings require two or more destination terms"
            )
        if len(self.reviewer_note) > 2000:
            raise ValueError("reviewer_note must be 2000 characters or fewer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_id": self.mapping_id,
            "source_span": self.source_span.to_dict(),
            "destination_terms": [item.to_dict() for item in self.destination_terms],
            "mapping_type": self.mapping_type,
            "evidence": [item.to_dict() for item in self.evidence],
            "escalation": self.escalation.to_dict(),
            "adjudication_id": self.adjudication_id,
            "reviewer_note": self.reviewer_note,
        }


@dataclass(frozen=True)
class DocumentRef:
    """Identity of one document and the ledger schema version /conform read it under."""

    document_id: str
    name: str
    sha256: str | None
    ledger_schema_version: str = "0.14.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "name": self.name,
            "sha256": self.sha256,
            "ledger_schema_version": self.ledger_schema_version,
        }


@dataclass
class ConformRun:
    """Top-level canonical output of one /conform run (conform.json)."""

    run_status: str
    mode: str
    source_document: DocumentRef
    core_document: DocumentRef
    mappings: list[MappingRecord] = field(default_factory=list)
    redline: dict[str, str] | None = None
    clean_text: dict[str, str] | None = None
    limitations: list[str] = field(default_factory=list)
    schema_version: str = "1.0.0"
    engine_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if self.run_status not in RUN_STATUSES:
            raise ValueError(f"unsupported run_status: {self.run_status}")
        if self.mode not in MODES:
            raise ValueError(f"unsupported mode: {self.mode}")

    def escalations(self) -> list[dict[str, Any]]:
        return [
            {"mapping_id": mapping.mapping_id, "reason": mapping.escalation.reason}
            for mapping in self.mappings
            if mapping.escalation.required
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
            "run_status": self.run_status,
            "mode": self.mode,
            "source_document": self.source_document.to_dict(),
            "core_document": self.core_document.to_dict(),
            "mappings": [mapping.to_dict() for mapping in self.mappings],
            "escalations": self.escalations(),
            "redline": self.redline,
            "clean_text": self.clean_text,
            "limitations": list(self.limitations),
        }
