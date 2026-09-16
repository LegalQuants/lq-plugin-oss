"""Load and validate bounded agent-review records without mutating a ledger."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import (
    CandidateProposal,
    ContextRequest,
    EvidenceItem,
    Finding,
    Location,
    ReviewTrace,
)
from .occurrence_review import OccurrenceSubmission
from .reference_review import ReferenceSubmission
from .semantic_review import AdjudicationSubmission

_MAX_BUNDLE_BYTES = 10 * 1024 * 1024
AGENT_BUNDLE_SCHEMA_VERSION = "agent-bundle-v1"
_ALLOWED_KEYS = frozenset(
    {
        "schema_version",
        "evidence",
        "context_requests",
        "candidate_proposals",
        "review_traces",
        "semantic_findings",
        "semantic_adjudications",
        "occurrence_adjudications",
        "reference_adjudications",
        "discovery_review",
    }
)
_RECORD_FIELDS = {
    "evidence": {
        "id",
        "location",
        "excerpt",
        "stance",
        "method",
    },
    "context_requests": {
        "id",
        "candidate_id",
        "request_type",
        "query",
        "reason",
        "requested_by",
        "status",
        "hop",
        "max_results",
        "result_evidence_ids",
    },
    "candidate_proposals": {
        "id",
        "candidate_id",
        "term",
        "normalized_term",
        "location",
        "state",
        "agent_role",
        "revision",
        "rationale_summary",
        "confidence",
        "definition_text",
        "evidence_for",
        "evidence_against",
        "context_request_ids",
        "reason_codes",
        "supersedes",
        "model_id",
        "prompt_version",
    },
    "review_traces": {
        "id",
        "subject_type",
        "subject_id",
        "action",
        "agent_role",
        "rationale_summary",
        "evidence_for",
        "evidence_against",
        "context_request_ids",
        "reason_codes",
        "confidence",
        "uncertainty",
        "model_id",
        "prompt_version",
        "visibility",
    },
    "semantic_findings": {
        "id",
        "rule_id",
        "kind",
        "severity",
        "message",
        "normalized_term",
        "evidence",
        "confidence",
        "review_state",
    },
    "semantic_adjudications": {
        "review_id",
        "decision",
        "evidence_indexes",
        "rationale_summary",
        "reason_codes",
        "confidence",
        "agent_role",
        "definition_text",
        "definition_context_index",
        "definition_start",
        "definition_end",
        "canonical_term",
        "model_id",
        "prompt_version",
        "definition_spans",
        "review_reason",
    },
    "occurrence_adjudications": {
        "review_id",
        "decision",
        "rationale_summary",
        "reason_codes",
        "confidence",
        "agent_role",
        "model_id",
        "prompt_version",
        "review_reason",
    },
    "reference_adjudications": {
        "review_id",
        "decision",
        "evidence_indexes",
        "rationale_summary",
        "reason_codes",
        "confidence",
        "agent_role",
        "model_id",
        "prompt_version",
        "review_reason",
    },
}
_REQUIRED_RECORD_FIELDS = {
    "evidence": {"id", "location", "excerpt", "stance", "method"},
    "context_requests": {
        "id",
        "candidate_id",
        "request_type",
        "query",
        "reason",
        "requested_by",
    },
    "candidate_proposals": {
        "id",
        "candidate_id",
        "term",
        "normalized_term",
        "location",
        "state",
        "agent_role",
        "revision",
        "rationale_summary",
    },
    "review_traces": {
        "id",
        "subject_type",
        "subject_id",
        "action",
        "agent_role",
        "rationale_summary",
    },
    "semantic_findings": {"id", "rule_id", "kind", "severity", "message"},
    "semantic_adjudications": {"review_id", "decision", "rationale_summary"},
    "occurrence_adjudications": {"review_id", "decision", "rationale_summary"},
    "reference_adjudications": {"review_id", "decision", "rationale_summary"},
}


class AgentBundleError(ValueError):
    """Raised when an agent bundle cannot be trusted as structured input."""


@dataclass(frozen=True)
class AgentBundle:
    evidence: tuple[EvidenceItem, ...]
    context_requests: tuple[ContextRequest, ...]
    candidate_proposals: tuple[CandidateProposal, ...]
    review_traces: tuple[ReviewTrace, ...]
    semantic_findings: tuple[Finding, ...]
    semantic_adjudications: tuple[AdjudicationSubmission, ...]
    occurrence_adjudications: tuple[OccurrenceSubmission, ...]
    reference_adjudications: tuple[ReferenceSubmission, ...]
    discovery_review: dict[str, Any] | None = None


def _discovery_review(value: object) -> dict[str, Any]:
    """Read a source-bound record of completed discovery packet responses."""

    fields = {"source_sha256", "prompt_sha256", "queue_sha256", "responses"}
    if not isinstance(value, dict) or set(value) != fields:
        raise AgentBundleError("discovery_review has invalid fields")
    for field in fields - {"responses"}:
        if not isinstance(value[field], str) or not re.fullmatch(
            r"[0-9a-f]{64}", value[field]
        ):
            raise AgentBundleError(f"discovery_review {field} must be a SHA-256 hash")
    responses = value["responses"]
    if not isinstance(responses, list):
        raise AgentBundleError("discovery_review responses must be an array")
    seen = set()
    for response in responses:
        if not isinstance(response, dict) or set(response) != {"packet", "rows"}:
            raise AgentBundleError("discovery_review response fields are invalid")
        packet = response["packet"]
        if (
            isinstance(packet, bool)
            or not isinstance(packet, int)
            or packet < 1
            or packet in seen
        ):
            raise AgentBundleError(
                "discovery_review packet ordinals must be unique positive integers"
            )
        if not isinstance(response["rows"], list):
            raise AgentBundleError("discovery_review rows must be an array")
        seen.add(packet)
    # Exact source spans and exhaustive packet coverage are checked against the
    # freshly rebuilt discovery manifest by the pipeline, not inferred here.
    return value


def _location(value: Any) -> Location:
    if not isinstance(value, dict):
        raise AgentBundleError("location must be an object")
    try:
        return Location(
            part=str(value["part"]),
            block_id=str(value["block_id"]),
            block_order=int(value["block_order"]),
            char_start=int(value["char_start"]),
            char_end=int(value["char_end"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AgentBundleError("location is invalid") from exc


def _tuple_strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise AgentBundleError(f"{field} must be an array of strings")
    if len(value) != len(set(value)):
        raise AgentBundleError(f"{field} must not contain duplicates")
    return tuple(value)


def _definition_spans(value: Any) -> tuple[tuple[int, int, int], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise AgentBundleError("definition_spans must be an array")
    spans = []
    for span in value:
        if (
            not isinstance(span, list)
            or len(span) != 3
            or any(isinstance(item, bool) or not isinstance(item, int) for item in span)
        ):
            raise AgentBundleError("definition_spans must contain three-integer arrays")
        spans.append((span[0], span[1], span[2]))
    if len(spans) != len(set(spans)):
        raise AgentBundleError("definition_spans must be unique")
    return tuple(spans)


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AgentBundleError(f"{field} must be a string or null")
    return value


def _optional_confidence(value: Any, field: str = "confidence") -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AgentBundleError(f"{field} must be a number between 0 and 1 or null")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise AgentBundleError(f"{field} must be a number between 0 and 1 or null")
    return number


def _records(payload: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = payload.get(field, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise AgentBundleError(f"{field} must be an array of objects")
    allowed = _RECORD_FIELDS[field]
    required = _REQUIRED_RECORD_FIELDS[field]
    for item in value:
        extra = set(item) - allowed
        missing = required - set(item)
        if extra:
            raise AgentBundleError(
                f"{field} record contains unsupported fields: {sorted(extra)}"
            )
        if missing:
            raise AgentBundleError(
                f"{field} record is missing required fields: {sorted(missing)}"
            )
    return value


def load_agent_bundle(path: str | Path) -> AgentBundle:
    source = Path(path)
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise AgentBundleError(f"unable to access agent bundle {source!s}") from exc
    if size > _MAX_BUNDLE_BYTES:
        raise AgentBundleError("agent bundle exceeds the 10 MiB limit")
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AgentBundleError("agent bundle is not readable UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise AgentBundleError("agent bundle root must be an object")
    extra = set(payload) - _ALLOWED_KEYS
    if extra:
        raise AgentBundleError(
            f"agent bundle contains unsupported fields: {sorted(extra)}"
        )
    if payload.get("schema_version") != AGENT_BUNDLE_SCHEMA_VERSION:
        raise AgentBundleError("agent bundle has an unsupported schema_version")

    discovery_review = (
        _discovery_review(payload["discovery_review"])
        if "discovery_review" in payload
        else None
    )

    try:
        evidence = tuple(
            EvidenceItem(
                id=str(item["id"]),
                location=_location(item["location"]),
                excerpt=str(item["excerpt"]),
                stance=str(item["stance"]),
                method=str(item["method"]),
            )
            for item in _records(payload, "evidence")
        )

        requests = tuple(
            ContextRequest(
                id=str(item["id"]),
                candidate_id=str(item["candidate_id"]),
                request_type=str(item["request_type"]),
                query=str(item["query"]),
                reason=str(item["reason"]),
                requested_by=str(item["requested_by"]),
                status=str(item.get("status", "requested")),
                hop=int(item.get("hop", 1)),
                max_results=int(item.get("max_results", 20)),
                result_evidence_ids=_tuple_strings(
                    item.get("result_evidence_ids", []), "result_evidence_ids"
                ),
            )
            for item in _records(payload, "context_requests")
        )

        proposals = tuple(
            CandidateProposal(
                id=str(item["id"]),
                candidate_id=str(item["candidate_id"]),
                term=str(item["term"]),
                normalized_term=str(item["normalized_term"]),
                location=_location(item["location"]),
                state=str(item["state"]),
                agent_role=str(item["agent_role"]),
                revision=int(item["revision"]),
                rationale_summary=str(item["rationale_summary"]),
                confidence=_optional_confidence(item.get("confidence")),
                definition_text=_optional_string(
                    item.get("definition_text"), "definition_text"
                ),
                evidence_for=_tuple_strings(
                    item.get("evidence_for", []), "evidence_for"
                ),
                evidence_against=_tuple_strings(
                    item.get("evidence_against", []), "evidence_against"
                ),
                context_request_ids=_tuple_strings(
                    item.get("context_request_ids", []), "context_request_ids"
                ),
                reason_codes=_tuple_strings(
                    item.get("reason_codes", []), "reason_codes"
                ),
                supersedes=_optional_string(item.get("supersedes"), "supersedes"),
                model_id=_optional_string(item.get("model_id"), "model_id"),
                prompt_version=_optional_string(
                    item.get("prompt_version"), "prompt_version"
                ),
            )
            for item in _records(payload, "candidate_proposals")
        )

        traces = tuple(
            ReviewTrace(
                id=str(item["id"]),
                subject_type=str(item["subject_type"]),
                subject_id=str(item["subject_id"]),
                action=str(item["action"]),
                agent_role=str(item["agent_role"]),
                rationale_summary=str(item["rationale_summary"]),
                evidence_for=_tuple_strings(
                    item.get("evidence_for", []), "evidence_for"
                ),
                evidence_against=_tuple_strings(
                    item.get("evidence_against", []), "evidence_against"
                ),
                context_request_ids=_tuple_strings(
                    item.get("context_request_ids", []), "context_request_ids"
                ),
                reason_codes=_tuple_strings(
                    item.get("reason_codes", []), "reason_codes"
                ),
                confidence=_optional_confidence(item.get("confidence")),
                uncertainty=_optional_string(item.get("uncertainty"), "uncertainty"),
                model_id=_optional_string(item.get("model_id"), "model_id"),
                prompt_version=_optional_string(
                    item.get("prompt_version"), "prompt_version"
                ),
                visibility=str(item.get("visibility", "internal")),
            )
            for item in _records(payload, "review_traces")
        )

        findings = tuple(
            Finding(
                id=str(item["id"]),
                rule_id=str(item["rule_id"]),
                kind=str(item["kind"]),
                severity=str(item["severity"]),
                message=str(item["message"]),
                normalized_term=_optional_string(
                    item.get("normalized_term"), "normalized_term"
                ),
                evidence=tuple(
                    _location(location) for location in item.get("evidence", [])
                ),
                confidence=_optional_confidence(item.get("confidence")),
                review_state=str(item.get("review_state", "open")),
            )
            for item in _records(payload, "semantic_findings")
        )

        adjudications = tuple(
            AdjudicationSubmission(
                review_id=str(item["review_id"]),
                decision=str(item["decision"]),
                evidence_indexes=tuple(
                    int(index) for index in item.get("evidence_indexes", [])
                ),
                rationale_summary=str(item["rationale_summary"]),
                reason_codes=_tuple_strings(
                    item.get("reason_codes", []), "reason_codes"
                ),
                confidence=_optional_confidence(item.get("confidence")),
                agent_role=str(item.get("agent_role", "semantic_reviewer")),
                definition_text=_optional_string(
                    item.get("definition_text"), "definition_text"
                ),
                definition_context_index=(
                    int(item["definition_context_index"])
                    if item.get("definition_context_index") is not None
                    else None
                ),
                definition_start=(
                    int(item["definition_start"])
                    if item.get("definition_start") is not None
                    else None
                ),
                definition_end=(
                    int(item["definition_end"])
                    if item.get("definition_end") is not None
                    else None
                ),
                canonical_term=_optional_string(
                    item.get("canonical_term"), "canonical_term"
                ),
                model_id=_optional_string(item.get("model_id"), "model_id"),
                prompt_version=_optional_string(
                    item.get("prompt_version"), "prompt_version"
                ),
                definition_spans=_definition_spans(item.get("definition_spans")),
                review_reason=_optional_string(
                    item.get("review_reason"), "review_reason"
                ),
            )
            for item in _records(payload, "semantic_adjudications")
        )

        occurrence_adjudications = tuple(
            OccurrenceSubmission(
                review_id=str(item["review_id"]),
                decision=str(item["decision"]),
                rationale_summary=str(item["rationale_summary"]),
                reason_codes=_tuple_strings(
                    item.get("reason_codes", []), "reason_codes"
                ),
                confidence=_optional_confidence(item.get("confidence")),
                agent_role=str(item.get("agent_role", "occurrence_reviewer")),
                model_id=_optional_string(item.get("model_id"), "model_id"),
                prompt_version=_optional_string(
                    item.get("prompt_version"), "prompt_version"
                ),
                review_reason=_optional_string(
                    item.get("review_reason"), "review_reason"
                ),
            )
            for item in _records(payload, "occurrence_adjudications")
        )

        reference_adjudications = tuple(
            ReferenceSubmission(
                review_id=str(item["review_id"]),
                decision=str(item["decision"]),
                evidence_indexes=tuple(
                    int(index) for index in item.get("evidence_indexes", [])
                ),
                rationale_summary=str(item["rationale_summary"]),
                reason_codes=_tuple_strings(
                    item.get("reason_codes", []), "reason_codes"
                ),
                confidence=_optional_confidence(item.get("confidence")),
                agent_role=str(item.get("agent_role", "reference_reviewer")),
                model_id=_optional_string(item.get("model_id"), "model_id"),
                prompt_version=_optional_string(
                    item.get("prompt_version"), "prompt_version"
                ),
                review_reason=_optional_string(
                    item.get("review_reason"), "review_reason"
                ),
            )
            for item in _records(payload, "reference_adjudications")
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, AgentBundleError):
            raise
        raise AgentBundleError(f"agent bundle record is invalid: {exc}") from exc

    if any(item.kind != "semantic" for item in findings):
        raise AgentBundleError("semantic_findings may contain only semantic findings")
    if any(
        item.status == "requested" and item.request_type != "escalate_review"
        for item in requests
    ):
        raise AgentBundleError(
            "non-escalation context requests must be resolved before finalization"
        )
    if not any(
        (
            evidence,
            requests,
            proposals,
            traces,
            findings,
            adjudications,
            occurrence_adjudications,
            reference_adjudications,
            discovery_review,
        )
    ):
        raise AgentBundleError("agent bundle must contain at least one review record")
    return AgentBundle(
        evidence,
        requests,
        proposals,
        traces,
        findings,
        adjudications,
        occurrence_adjudications,
        reference_adjudications,
        discovery_review,
    )
