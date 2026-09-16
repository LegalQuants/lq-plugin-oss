"""Scoped, source-grounded review of definition-reference targets."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from .models import (
    Definition,
    Location,
    ReferenceAdjudication,
    ReferenceCandidate,
    ReferenceReviewSummary,
    SourceDocument,
    stable_id,
)
from .term_identity import term_key

REFERENCE_DECISIONS = (
    "resolved",
    "broken",
    "out_of_scope",
    "needs_review",
    "insufficient_evidence",
)
MAX_REFERENCE_CONTEXTS = 12
MAX_REFERENCE_EVIDENCE = 8
_NON_REFERENTIAL_TARGETS = frozenset({"a", "an", "the"})

_REFERENCE_PATTERNS = (
    re.compile(
        r"\b(?:meaning|definition)\s+"
        r"(?:(?:set\s+(?:forth|out)|given|assigned|ascribed|specified|attributed|"
        r"provided(?:\s+for)?)(?:\s+(?:to\s+it|thereto))?\s+)?"
        r"(?:in|under|from)\s+"
        r"(?P<target>[^;,:]+?)(?=\.(?:\s|$)|[;,:]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:set\s+forth|provided|defined|contained|described|incorporated)\s+"
        r"(?:in|under|from|by)\s+(?P<target>[^;,:]+?)(?=\.(?:\s|$)|[;,:]|$)",
        re.IGNORECASE,
    ),
)


def _is_referential_target(value: str) -> bool:
    """Reject fragments that cannot identify a definition-reference target."""

    target = value.strip()
    alphanumeric = [character for character in target if character.isalnum()]
    return bool(
        alphanumeric
        and target.casefold() not in _NON_REFERENTIAL_TARGETS
        and not (len(alphanumeric) == 1 and alphanumeric[0].isalpha())
    )


def _find_phrase(text: str, phrase: str, start: int = 0) -> int:
    """Find a case-insensitive phrase without matching inside a larger token."""

    pattern = re.compile(re.escape(phrase), re.IGNORECASE)
    for match in pattern.finditer(text, start):
        before = text[match.start() - 1] if match.start() else ""
        after = text[match.end()] if match.end() < len(text) else ""
        if phrase[0].isalnum() and before.isalnum():
            continue
        if phrase[-1].isalnum() and after.isalnum():
            continue
        return match.start()
    return -1


class ReferenceReviewError(ValueError):
    """Raised when scoped reference evidence cannot be reconciled safely."""


@dataclass(frozen=True)
class ReferenceSubmission:
    """Worker-compatible response before supervisor IDs and locations are restored."""

    review_id: str
    decision: str
    evidence_indexes: tuple[int, ...]
    rationale_summary: str
    reason_codes: tuple[str, ...] = ()
    confidence: float | None = None
    agent_role: str = "reference_reviewer"
    model_id: str | None = None
    prompt_version: str | None = None
    review_reason: str | None = None


def extract_reference_target(text: str) -> tuple[str, int, int] | None:
    """Extract only the target phrase; resolution remains an agentic decision."""

    for pattern in _REFERENCE_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        raw_value = match.group("target")
        raw = raw_value.strip(" \t\r\n\"'")
        if raw and _is_referential_target(raw):
            start = (
                match.start("target")
                + len(raw_value)
                - len(raw_value.lstrip(" \t\r\n\"'"))
            )
            end = start + len(raw)
            return raw, start, end
    return None


def _find_target_location(
    source: SourceDocument, definition: Definition
) -> tuple[str, Location] | None:
    blocks = {block.id: block for block in source.blocks}
    block = blocks.get(definition.location.block_id)
    if block is None or not definition.reference_target:
        return None
    target = definition.reference_target.strip()
    if not _is_referential_target(target):
        return None
    start = _find_phrase(block.text, target, definition.location.char_end)
    if start < 0:
        start = _find_phrase(block.text, target)
    if start < 0:
        return None
    return target, block.location(start, start + len(target))


def build_reference_candidates(
    source: SourceDocument, definitions: Iterable[Definition]
) -> tuple[ReferenceCandidate, ...]:
    """Create a complete queue and require an exact target source span."""

    candidates = []
    for definition in definitions:
        if not definition.reference_target:
            continue
        if not _is_referential_target(definition.reference_target):
            raise ReferenceReviewError(
                f"reference target for {definition.id} is not a substantive phrase"
            )
        target_location = definition.reference_location
        if target_location is None:
            inferred = _find_target_location(source, definition)
            if inferred is None:
                raise ReferenceReviewError(
                    f"reference target for {definition.id} has no exact source span"
                )
            target, target_location = inferred
        else:
            target = definition.reference_target.strip()
        candidates.append(
            ReferenceCandidate(
                review_id=stable_id(
                    "reference_review",
                    source.document_id,
                    definition.id,
                    target,
                    target_location.block_id,
                    target_location.char_start,
                    target_location.char_end,
                ),
                definition_id=definition.id,
                term=definition.term,
                normalized_term=definition.normalized_term,
                reference_target=target,
                location=definition.location,
                reference_location=target_location,
                scope="document",
            )
        )
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.location.block_order,
                item.location.char_start,
                item.review_id,
            ),
        )
    )


def build_reference_envelopes(
    source: SourceDocument,
    candidates: Iterable[ReferenceCandidate],
    *,
    max_context_chars: int = 3000,
    max_contexts: int = MAX_REFERENCE_CONTEXTS,
) -> list[dict[str, Any]]:
    """Expose bounded source context and explicit scope rules to the reviewer."""

    if max_contexts < 1:
        raise ValueError("reference max_contexts must be positive")

    blocks = {block.id: block for block in source.blocks}
    envelopes = []
    for candidate in candidates:
        block = blocks[candidate.reference_location.block_id]
        if len(block.text) <= max_context_chars:
            start, end = 0, len(block.text)
        else:
            half = max_context_chars // 2
            start = max(0, candidate.reference_location.char_start - half)
            end = min(len(block.text), start + max_context_chars)
            start = max(0, end - max_context_chars)
        contexts = [
            {
                "text": block.text[start:end],
                "match_start": candidate.reference_location.char_start - start,
                "match_end": candidate.reference_location.char_end - start,
                "location": asdict(block.location(start, end)),
            }
        ]
        target_blocks = []
        for target_block in source.blocks:
            if target_block.id == block.id:
                continue
            match_start = _find_phrase(target_block.text, candidate.reference_target)
            if match_start < 0:
                continue
            target_blocks.append((target_block, match_start))
        target_blocks.sort(
            key=lambda item: (
                term_key(item[0].text) != term_key(candidate.reference_target),
                abs(item[0].order - block.order),
                item[0].order,
                item[0].id,
            )
        )
        for target_block, match_start in target_blocks[: max_contexts - 1]:
            if len(target_block.text) <= max_context_chars:
                target_start, target_end = 0, len(target_block.text)
            else:
                half = max_context_chars // 2
                target_start = max(0, match_start - half)
                target_end = min(
                    len(target_block.text), target_start + max_context_chars
                )
                target_start = max(0, target_end - max_context_chars)
            contexts.append(
                {
                    "text": target_block.text[target_start:target_end],
                    "match_start": match_start - target_start,
                    "match_end": match_start
                    - target_start
                    + len(candidate.reference_target),
                    "location": asdict(target_block.location(target_start, target_end)),
                }
            )
        envelopes.append(
            {
                "review_id": candidate.review_id,
                "definition_id": candidate.definition_id,
                "term": candidate.term,
                "reference_target": candidate.reference_target,
                "definition_location": asdict(candidate.location),
                "scope": candidate.scope,
                "contexts": contexts,
                "available_scope": {
                    "source_document": source.name,
                    "companion_documents": "omitted unless explicitly supplied",
                },
                "allowed_decisions": list(REFERENCE_DECISIONS),
                "decision_contract": {
                    "resolved": "The supplied source scope resolves the target.",
                    "broken": "The target is intended to be internal to the supplied scope but cannot be resolved there.",
                    "out_of_scope": "The target is external or belongs to an omitted companion document; do not call that broken.",
                    "needs_review": "The supplied evidence is ambiguous.",
                    "insufficient_evidence": "The supplied evidence cannot support a disposition.",
                },
            }
        )
    return envelopes


def reconcile_reference_adjudications(
    candidates: Iterable[ReferenceCandidate],
    envelopes: Iterable[dict[str, Any]],
    submissions: Iterable[ReferenceSubmission],
) -> tuple[tuple[ReferenceAdjudication, ...], ReferenceReviewSummary]:
    """Require exact queue coverage and map worker evidence back to source spans."""

    candidate_list = tuple(candidates)
    candidate_by_review = {item.review_id: item for item in candidate_list}
    envelope_by_review = {item["review_id"]: item for item in envelopes}
    submitted = tuple(submissions)
    ids = [item.review_id for item in submitted]
    if len(ids) != len(set(ids)):
        raise ReferenceReviewError(
            "reference bundle contains duplicate review_id decisions"
        )
    expected = set(candidate_by_review)
    if set(ids) != expected:
        raise ReferenceReviewError(
            "reference review queue is incomplete or mismatched; "
            f"missing={sorted(expected - set(ids))}, extra={sorted(set(ids) - expected)}"
        )
    decisions = []
    for submission in submitted:
        if submission.decision not in REFERENCE_DECISIONS:
            raise ReferenceReviewError(
                f"unsupported reference decision: {submission.decision}"
            )
        envelope = envelope_by_review.get(submission.review_id)
        if envelope is None:
            raise ReferenceReviewError("reference envelope coverage is incomplete")
        contexts = envelope.get("contexts") or []
        if not submission.evidence_indexes:
            raise ReferenceReviewError(
                f"reference decision {submission.review_id} must cite evidence"
            )
        if len(submission.evidence_indexes) > MAX_REFERENCE_EVIDENCE:
            raise ReferenceReviewError(
                f"reference decision {submission.review_id} cites too many evidence contexts"
            )
        if any(
            index < 0 or index >= len(contexts) for index in submission.evidence_indexes
        ):
            raise ReferenceReviewError(
                f"reference decision {submission.review_id} has an invalid evidence index"
            )
        evidence = tuple(
            Location(**contexts[index]["location"])
            for index in submission.evidence_indexes
        )
        candidate = candidate_by_review[submission.review_id]
        decisions.append(
            ReferenceAdjudication(
                id=stable_id(
                    "reference_adjudication", submission.review_id, submission.decision
                ),
                review_id=submission.review_id,
                definition_id=candidate.definition_id,
                decision=submission.decision,
                evidence=evidence,
                rationale_summary=submission.rationale_summary,
                reason_codes=submission.reason_codes,
                confidence=submission.confidence,
                agent_role=submission.agent_role,
                model_id=submission.model_id,
                prompt_version=submission.prompt_version,
                review_reason=submission.review_reason,
            )
        )
    ordered = tuple(sorted(decisions, key=lambda item: item.review_id))
    unresolved = sum(
        item.decision in {"needs_review", "insufficient_evidence"} for item in ordered
    )
    return ordered, ReferenceReviewSummary(
        "complete",
        len(candidate_list),
        len(ordered),
        unresolved,
    )
