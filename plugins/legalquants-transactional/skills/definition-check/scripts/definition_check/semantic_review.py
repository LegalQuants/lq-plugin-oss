"""Build provenance-blind review envelopes and reconcile complete adjudications."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from typing import Any

from .analyze import _plural_form, is_likely_heading
from .models import (
    CandidateProposal,
    Definition,
    DefinitionSpan,
    Finding,
    LexicalCandidateObservation,
    Location,
    SemanticAdjudication,
    SemanticReviewSummary,
    SourceDocument,
    TermCandidate,
    stable_id,
)
from .reference_review import extract_reference_target
from .term_identity import term_key, term_pattern


class SemanticReviewError(ValueError):
    """Raised when semantic results do not match the supervisor-owned queue."""


_ASSIGNMENT_AFTER = re.compile(
    r"^\s*[\"'\u2019\u201d\u00bb)]*\s*(?:shall\s+)?(?:mean|means|refer(?:s)?\s+to|is\s+defined\s+as)\b",
    re.IGNORECASE,
)
_ASSIGNMENT_BEFORE = re.compile(
    r"(?:referred\s+to\s+as|known\s+as|called|designated\s+as)\s*[\"'\u2018\u201c\u00ab(]*\s*$",
    re.IGNORECASE,
)


def _span_splits_word(text: str, start: int, end: int) -> bool:
    """Return whether either span boundary falls inside an alphanumeric token."""

    splits_start = (
        0 < start < len(text) and text[start - 1].isalnum() and text[start].isalnum()
    )
    splits_end = 0 < end < len(text) and text[end - 1].isalnum() and text[end].isalnum()
    return splits_start or splits_end


def _review_term_pattern(value: str) -> re.Pattern[str]:
    return term_pattern(value, allow_possessive=True)


def _singular_form(value: str) -> str | None:
    """Return one conservative singular spelling for review-context retrieval."""

    words = value.split()
    if not words:
        return None
    final = words[-1]
    folded = final.casefold()
    if folded.endswith("ies") and len(final) > 3:
        singular = final[:-3] + ("Y" if final.isupper() else "y")
    elif folded.endswith(("sses", "shes", "ches", "xes", "zes")):
        singular = final[:-2]
    elif folded.endswith("s") and not folded.endswith("ss"):
        singular = final[:-1]
    else:
        return None
    words[-1] = singular
    return " ".join(words)


def _proposal_occurrence_locations(
    source: SourceDocument, proposal: CandidateProposal
) -> tuple[Location, ...]:
    """Expand one discovered label to source occurrences before adjudication."""

    spellings = {proposal.term}
    if plural := _plural_form(proposal.term):
        spellings.add(plural)
    if singular := _singular_form(proposal.term):
        spellings.add(singular)

    # Discovery offsets are suggestions, not authoritative occurrences. Rescan
    # the source so a substring inside a word cannot enter the review inventory.
    locations: set[Location] = set()
    for block in source.blocks:
        for spelling in spellings:
            locations.update(
                block.location(match.start(), match.end())
                for match in _review_term_pattern(spelling).finditer(block.text)
            )
    return tuple(
        sorted(
            locations,
            key=lambda location: (
                location.block_order,
                location.char_start,
                location.char_end,
                location.block_id,
            ),
        )
    )


def _table_row_key(block: Any) -> tuple[str, int, int] | None:
    if block.table_index is None or block.row_index is None:
        return None
    return (block.part, block.table_index, block.row_index)


def _table_rows(blocks: Iterable[Any]) -> dict[tuple[str, int, int], tuple[Any, ...]]:
    grouped: dict[tuple[str, int, int], list[Any]] = {}
    for block in blocks:
        if (row_key := _table_row_key(block)) is not None:
            grouped.setdefault(row_key, []).append(block)
    return {
        row_key: tuple(
            sorted(
                row,
                key=lambda block: (
                    block.cell_index if block.cell_index is not None else -1,
                    block.paragraph_index if block.paragraph_index is not None else -1,
                    block.order,
                ),
            )
        )
        for row_key, row in grouped.items()
    }


def _is_standalone_table_label(
    block: Any,
    candidate_term: str,
    row_blocks: tuple[Any, ...],
) -> bool:
    """Return whether a short cell is a label paired with another populated cell."""

    return bool(
        _table_row_key(block) is not None
        and block.text.strip().casefold() == candidate_term.strip().casefold()
        and any(
            other.id != block.id
            and other.cell_index != block.cell_index
            and other.text.strip()
            for other in row_blocks
        )
    )


def _definition_context_priority(
    block: Any,
    location: Location,
    candidate_term: str,
    row_blocks: tuple[Any, ...],
) -> int:
    """Rank source occurrences for context inclusion without deciding meaning."""

    if _is_standalone_table_label(block, candidate_term, row_blocks):
        return 0
    before = block.text[max(0, location.char_start - 120) : location.char_start]
    after = block.text[location.char_end : location.char_end + 120]
    return (
        1 if _ASSIGNMENT_AFTER.search(after) or _ASSIGNMENT_BEFORE.search(before) else 2
    )


def _context_for_block(
    block: Any,
    location: Location | None,
    *,
    max_context_chars: int,
) -> dict[str, Any]:
    if location is None:
        start, end = 0, min(len(block.text), max_context_chars)
        match_start = match_end = 0
        base_location = block.location(start, start)
    elif len(block.text) <= max_context_chars:
        start, end = 0, len(block.text)
        match_start = location.char_start
        match_end = location.char_end
        base_location = location
    else:
        half = max_context_chars // 2
        start = max(0, location.char_start - half)
        end = min(len(block.text), start + max_context_chars)
        start = max(0, end - max_context_chars)
        match_start = location.char_start - start
        match_end = location.char_end - start
        base_location = location
    context = {
        "text": block.text[start:end],
        "match_start": match_start,
        "match_end": match_end,
        "location": asdict(base_location),
    }
    row_key = _table_row_key(block)
    if row_key is not None:
        context["source_structure"] = {
            "kind": "table_cell",
            "table_index": block.table_index,
            "row_index": block.row_index,
            "cell_index": block.cell_index,
        }
    return context


@dataclass(frozen=True)
class AdjudicationSubmission:
    review_id: str
    decision: str
    evidence_indexes: tuple[int, ...]
    rationale_summary: str
    reason_codes: tuple[str, ...]
    confidence: float | None
    agent_role: str
    definition_text: str | None = None
    definition_context_index: int | None = None
    definition_start: int | None = None
    definition_end: int | None = None
    canonical_term: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    definition_spans: tuple[tuple[int, int, int], ...] = ()
    review_reason: str | None = None


def build_term_candidates(
    source: SourceDocument,
    definitions: Iterable[Definition],
    findings: Iterable[Finding],
    observations: Iterable[LexicalCandidateObservation] = (),
    proposals: Iterable[CandidateProposal] = (),
) -> tuple[TermCandidate, ...]:
    """Return the exact-normalized union of all currently detected term sources."""

    blocks = {block.id: block for block in source.blocks}
    groups: dict[str, dict[str, Any]] = {}

    def add(
        normalized: str,
        term: str,
        location: Location,
        origin: str,
        record_id: str,
        collection: str,
    ) -> None:
        item = groups.setdefault(
            normalized,
            {
                "term": term,
                "locations": [],
                "origins": set(),
                "definition_ids": [],
                "finding_ids": [],
                "observation_ids": [],
                "proposal_ids": [],
            },
        )
        item["locations"].append(location)
        item["origins"].add(origin)
        item[collection].append(record_id)

    for definition in definitions:
        add(
            definition.normalized_term,
            definition.term,
            definition.location,
            "deterministic_definition",
            definition.id,
            "definition_ids",
        )
    for finding in findings:
        if (
            finding.rule_id != "DEF-001"
            or not finding.normalized_term
            or not finding.evidence
        ):
            continue
        first = finding.evidence[0]
        block = blocks.get(first.block_id)
        term = (
            block.text[first.char_start : first.char_end]
            if block
            else finding.normalized_term
        )
        for location in finding.evidence:
            add(
                finding.normalized_term,
                term,
                location,
                "potential_undefined",
                finding.id,
                "finding_ids",
            )
    for observation in observations:
        add(
            observation.normalized_term,
            observation.term,
            observation.location,
            "quoted_text",
            observation.id,
            "observation_ids",
        )
    for proposal in proposals:
        existing = groups.get(proposal.normalized_term)
        block = blocks.get(proposal.location.block_id)
        location = proposal.location
        # Preserve the existing-group fast path only for a source-backed label.
        # Match against the full block: slicing would hide adjacent word chars.
        match = (
            term_pattern(proposal.term).match(block.text, location.char_start)
            if block
            and block.part == location.part
            and block.order == location.block_order
            and 0 <= location.char_start < location.char_end <= len(block.text)
            else None
        )
        locations = (
            ((location,) if match and match.end() == location.char_end else ())
            if existing is not None
            else _proposal_occurrence_locations(source, proposal)
        )
        for location in locations:
            add(
                proposal.normalized_term,
                proposal.term,
                location,
                "agent_discovery",
                proposal.id,
                "proposal_ids",
            )

    records = []
    for normalized, item in sorted(groups.items()):
        unique_locations = tuple(
            sorted(
                set(item["locations"]),
                key=lambda loc: (
                    loc.block_order,
                    loc.char_start,
                    loc.char_end,
                    loc.block_id,
                ),
            )
        )
        likely_heading_count = sum(
            bool(
                (block := blocks.get(location.block_id))
                and is_likely_heading(block.text)
            )
            for location in unique_locations
        )
        if likely_heading_count == len(unique_locations):
            structural_hints = ("likely_heading",)
        elif likely_heading_count:
            structural_hints = ("includes_likely_heading_occurrence",)
        else:
            structural_hints = ()
        records.append(
            TermCandidate(
                review_id=stable_id("review", source.document_id, normalized),
                term=item["term"],
                normalized_term=normalized,
                locations=unique_locations,
                origins=tuple(sorted(item["origins"])),
                definition_ids=tuple(sorted(set(item["definition_ids"]))),
                finding_ids=tuple(sorted(set(item["finding_ids"]))),
                observation_ids=tuple(sorted(set(item["observation_ids"]))),
                proposal_ids=tuple(sorted(set(item["proposal_ids"]))),
                structural_hints=structural_hints,
            )
        )
    return tuple(records)


def build_review_envelopes(
    source: SourceDocument,
    candidates: Iterable[TermCandidate],
    *,
    max_contexts: int = 3,
    max_context_chars: int = 2000,
) -> list[dict[str, Any]]:
    """Serialize neutral term/source context without detector metadata."""

    blocks = {block.id: block for block in source.blocks}
    row_blocks = _table_rows(source.blocks)
    envelopes = []
    for candidate in candidates:
        contexts = []
        ranked_locations = sorted(
            candidate.locations,
            key=lambda location: (
                _definition_context_priority(
                    blocks[location.block_id],
                    location,
                    candidate.term,
                    row_blocks.get(_table_row_key(blocks[location.block_id]), ()),
                ),
                location.block_order,
                location.char_start,
                location.char_end,
                location.block_id,
            ),
        )
        locations_by_block: dict[str, list[Location]] = {}
        for location in ranked_locations:
            locations_by_block.setdefault(location.block_id, []).append(location)
        included_blocks: set[str] = set()
        for location in ranked_locations:
            if len(contexts) >= max_contexts:
                break
            block = blocks[location.block_id]
            if block.id in included_blocks:
                continue
            row = row_blocks.get(_table_row_key(block), ())
            context_blocks = (
                row
                if _is_standalone_table_label(block, candidate.term, row)
                else (block,)
            )
            for context_block in context_blocks:
                if len(contexts) >= max_contexts:
                    break
                if context_block.id in included_blocks:
                    continue
                focus = (
                    location
                    if context_block.id == block.id
                    else next(iter(locations_by_block.get(context_block.id, ())), None)
                )
                contexts.append(
                    _context_for_block(
                        context_block,
                        focus,
                        max_context_chars=max_context_chars,
                    )
                )
                included_blocks.add(context_block.id)
        envelopes.append(
            {
                "review_id": candidate.review_id,
                "term": candidate.term,
                "contexts": contexts,
                "allowed_context_actions": [
                    "expand_location",
                    "search_term",
                    "retrieve_definitions_section",
                    "retrieve_occurrences",
                ],
                "remaining_retrieval_budget": {"requests": 3, "characters": 12000},
                "allowed_decisions": [
                    "confirmed_defined",
                    "confirmed_alias",
                    "confirmed_undefined",
                    "confirmed_external_reference",
                    "rejected_not_a_term",
                    "rejected_proper_name",
                    "needs_review",
                    "insufficient_evidence",
                ],
                "definition_submission_contract": {
                    "confirmed_defined_requires": [
                        "definition_spans",
                    ],
                    "rule": (
                        "Return every exact definition span from the supplied contexts "
                        "as [context, start, end] triples with zero-based offsets."
                    ),
                },
                "alias_submission_contract": {
                    "confirmed_alias_requires": ["canonical_term"],
                    "rule": (
                        "Use confirmed_alias only when this label and the canonical "
                        "label are assigned to the same antecedent. Return the exact "
                        "canonical label spelling from the supplied context."
                    ),
                },
            }
        )
    return envelopes


def reconcile_adjudications(
    candidates: Iterable[TermCandidate],
    envelopes: Iterable[dict[str, Any]],
    submissions: Iterable[AdjudicationSubmission],
) -> tuple[tuple[SemanticAdjudication, ...], SemanticReviewSummary]:
    """Require one reviewer decision for every opaque queue item and map evidence."""

    candidate_list = tuple(candidates)
    envelope_map = {item["review_id"]: item for item in envelopes}
    submitted = tuple(submissions)
    ids = [item.review_id for item in submitted]
    if len(ids) != len(set(ids)):
        raise SemanticReviewError(
            "semantic bundle contains duplicate review_id decisions"
        )
    expected = {item.review_id for item in candidate_list}
    actual = set(ids)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise SemanticReviewError(
            f"semantic review queue is incomplete or mismatched; missing={missing}, extra={extra}"
        )

    candidate_by_review = {item.review_id: item for item in candidate_list}
    candidate_by_source_term = {term_key(item.term): item for item in candidate_list}
    submission_by_review = {item.review_id: item for item in submitted}
    alias_targets: dict[str, TermCandidate] = {}
    for submission in submitted:
        if submission.decision == "confirmed_alias":
            canonical_term = (submission.canonical_term or "").strip()
            target = candidate_by_source_term.get(term_key(canonical_term))
            if target is None:
                raise SemanticReviewError(
                    f"alias decision {submission.review_id} references a missing canonical term"
                )
            if target.review_id == submission.review_id:
                raise SemanticReviewError(
                    f"alias decision {submission.review_id} cannot reference itself"
                )
            target_submission = submission_by_review.get(target.review_id)
            if (
                target_submission is None
                or target_submission.decision != "confirmed_defined"
            ):
                raise SemanticReviewError(
                    f"alias decision {submission.review_id} must reference a confirmed defined term"
                )
            alias_targets[submission.review_id] = target
        elif submission.canonical_term is not None:
            raise SemanticReviewError(
                f"non-alias decision {submission.review_id} must not identify a canonical term"
            )

    decisions = []
    for submission in submitted:
        candidate = candidate_by_review[submission.review_id]
        contexts = envelope_map[submission.review_id]["contexts"]
        if any(
            index < 0 or index >= len(contexts) for index in submission.evidence_indexes
        ):
            raise SemanticReviewError(
                f"semantic decision {submission.review_id} has an invalid evidence index"
            )
        evidence = tuple(
            Location(**contexts[index]["location"])
            for index in submission.evidence_indexes
        )
        definition_text = None
        definition_location = None
        definition_spans: tuple[DefinitionSpan, ...] = ()
        legacy_context_index = submission.definition_context_index
        legacy_start = submission.definition_start
        legacy_end = submission.definition_end
        legacy_definition_fields = (
            submission.definition_text,
            legacy_context_index,
            legacy_start,
            legacy_end,
        )
        if submission.decision == "confirmed_defined":
            if submission.definition_spans:
                if any(value is None for value in legacy_definition_fields) and any(
                    value is not None for value in legacy_definition_fields
                ):
                    raise SemanticReviewError(
                        f"defined decision {submission.review_id} has incomplete legacy definition fields"
                    )
                raw_spans = submission.definition_spans
            else:
                if (
                    legacy_context_index is None
                    or legacy_start is None
                    or legacy_end is None
                ):
                    raise SemanticReviewError(
                        f"confirmed defined decision {submission.review_id} must identify complete definition span fields"
                    )
                raw_spans = ((legacy_context_index, legacy_start, legacy_end),)
            if (
                legacy_context_index is not None
                and legacy_start is not None
                and legacy_end is not None
            ):
                legacy_span = (legacy_context_index, legacy_start, legacy_end)
                if legacy_span != raw_spans[0]:
                    raise SemanticReviewError(
                        f"legacy definition fields for {submission.review_id} must match the first definition span"
                    )
            resolved_spans = []
            seen_locations: set[tuple[str, str, int, int]] = set()
            for raw_span in raw_spans:
                try:
                    context_index, start, end = (int(value) for value in raw_span)
                except (TypeError, ValueError) as exc:
                    raise SemanticReviewError(
                        f"definition span for {submission.review_id} is malformed"
                    ) from exc
                if context_index < 0 or context_index >= len(contexts):
                    raise SemanticReviewError(
                        f"definition span for {submission.review_id} has an invalid context index"
                    )
                context = contexts[context_index]
                context_text = context["text"]
                if start < 0 or end <= start or end > len(context_text):
                    raise SemanticReviewError(
                        f"definition span for {submission.review_id} is out of bounds"
                    )
                if _span_splits_word(context_text, start, end):
                    raise SemanticReviewError(
                        f"definition span for {submission.review_id} splits a word boundary"
                    )
                base = Location(**context["location"])
                context_start = base.char_start - int(context["match_start"])
                location = Location(
                    part=base.part,
                    block_id=base.block_id,
                    block_order=base.block_order,
                    char_start=context_start + start,
                    char_end=context_start + end,
                )
                location_key = (
                    location.block_id,
                    location.part,
                    location.char_start,
                    location.char_end,
                )
                if location_key in seen_locations or any(
                    location.part == seen_part
                    and location.block_id == seen_block
                    and location.char_start < seen_end
                    and seen_start < location.char_end
                    for seen_block, seen_part, seen_start, seen_end in seen_locations
                ):
                    raise SemanticReviewError(
                        f"definition decision {submission.review_id} contains duplicate or overlapping spans"
                    )
                seen_locations.add(location_key)
                source_slice = context_text[start:end]
                if (
                    submission.definition_text is not None
                    and len(raw_spans) == 1
                    and source_slice != submission.definition_text
                ):
                    raise SemanticReviewError(
                        f"definition text for {submission.review_id} does not exactly match the source span"
                    )
                resolved_spans.append(DefinitionSpan(source_slice, location))
            if not resolved_spans:
                raise SemanticReviewError(
                    f"confirmed defined decision {submission.review_id} must identify at least one definition span"
                )
            definition_spans = tuple(resolved_spans)
            definition_text = definition_spans[0].definition_text
            definition_location = definition_spans[0].location
        elif submission.definition_spans or any(
            value is not None for value in legacy_definition_fields
        ):
            raise SemanticReviewError(
                f"non-defined decision {submission.review_id} must not include definition spans"
            )
        canonical_term = None
        canonical_review_id = None
        if submission.decision == "confirmed_alias":
            target = alias_targets[submission.review_id]
            canonical_term = target.term
            canonical_review_id = target.review_id
            if not submission.evidence_indexes:
                raise SemanticReviewError(
                    f"alias decision {submission.review_id} must cite shared source context"
                )
            alias_folded = term_key(candidate.term)
            canonical_folded = term_key(canonical_term)
            if not any(
                alias_folded in term_key(contexts[index]["text"])
                and canonical_folded in term_key(contexts[index]["text"])
                for index in submission.evidence_indexes
            ):
                raise SemanticReviewError(
                    f"alias decision {submission.review_id} lacks shared label context"
                )
        scope_qualification = "none"
        scope_target = None
        scope_evidence: tuple[Location, ...] = ()
        if submission.decision == "confirmed_external_reference":
            if not evidence:
                raise SemanticReviewError(
                    f"external-reference decision {submission.review_id} must cite source evidence"
                )
        decisions.append(
            SemanticAdjudication(
                id=stable_id("adjudication", submission.review_id, submission.decision),
                review_id=submission.review_id,
                decision=submission.decision,
                evidence=evidence,
                rationale_summary=submission.rationale_summary,
                reason_codes=submission.reason_codes,
                confidence=submission.confidence,
                agent_role=submission.agent_role,
                definition_text=definition_text,
                definition_location=definition_location,
                canonical_term=canonical_term,
                canonical_review_id=canonical_review_id,
                model_id=submission.model_id,
                prompt_version=submission.prompt_version,
                definition_spans=definition_spans,
                review_reason=submission.review_reason,
                scope_qualification=scope_qualification,
                scope_target=scope_target,
                scope_evidence=scope_evidence,
            )
        )
    ordered = tuple(sorted(decisions, key=lambda item: item.review_id))
    unresolved = sum(
        item.decision in {"needs_review", "insufficient_evidence"} for item in ordered
    )
    return ordered, SemanticReviewSummary(
        status="complete",
        queue_count=len(candidate_list),
        decided_count=len(ordered),
        unresolved_count=unresolved,
    )


def materialize_definitions(
    source: SourceDocument,
    candidates: Iterable[TermCandidate],
    adjudications: Iterable[SemanticAdjudication],
) -> list[Definition]:
    """Create canonical definitions only from source-validated model decisions."""

    candidate_list = tuple(candidates)
    by_review = {candidate.review_id: candidate for candidate in candidate_list}
    blocks = {block.id: block for block in source.blocks}
    row_blocks = _table_rows(source.blocks)
    definitions = []
    for adjudication in adjudications:
        if adjudication.decision != "confirmed_defined":
            continue
        candidate = by_review.get(adjudication.review_id)
        if candidate is None:
            raise SemanticReviewError(
                f"semantic adjudication references unknown review ID {adjudication.review_id}"
            )
        # Candidate identity is case-insensitive, but its display label may come
        # from an earlier heading. Only existing candidate spans are eligible;
        # the defining block/row below still determines which label is used.
        label_locations = tuple(
            location
            for location in candidate.locations
            if (
                (block := blocks.get(location.block_id)) is not None
                and term_key(block.text[location.char_start : location.char_end])
                == term_key(candidate.term)
            )
        )
        if not adjudication.definition_spans:
            raise SemanticReviewError(
                f"defined term {candidate.review_id} is missing its confirmed definition spans"
            )
        span_keys = [
            (
                span.location.part,
                span.location.block_id,
                span.location.char_start,
                span.location.char_end,
            )
            for span in adjudication.definition_spans
        ]
        if len(span_keys) != len(set(span_keys)):
            raise SemanticReviewError(
                f"defined term {candidate.review_id} contains duplicate definition spans"
            )
        for span in adjudication.definition_spans:
            definition_location = span.location
            definition_block = blocks[definition_location.block_id]
            definition_row_key = _table_row_key(definition_block)
            definition_label_locations = tuple(
                location
                for location in label_locations
                if (
                    location.part == definition_location.part
                    and location.block_id == definition_location.block_id
                )
                or (
                    definition_row_key is not None
                    and (label_block := blocks.get(location.block_id)) is not None
                    and _table_row_key(label_block) == definition_row_key
                )
            )
            if not definition_label_locations:
                raise SemanticReviewError(
                    f"defined term {candidate.review_id} has no label beside its confirmed definition span"
                )

            def distance_from_definition(
                location: Location,
                definition_span: Location = definition_location,
                candidate_term: str = candidate.term,
                table_rows: dict[tuple[str, int, int], tuple[Any, ...]] = row_blocks,
            ) -> tuple[bool, bool, bool, int, int]:
                label_block = blocks[location.block_id]
                standalone_table_label = _is_standalone_table_label(
                    label_block,
                    candidate_term,
                    table_rows.get(_table_row_key(label_block), ()),
                )
                same_block = location.block_id == definition_span.block_id
                contained = (
                    same_block
                    and definition_span.char_start <= location.char_start
                    and location.char_end <= definition_span.char_end
                )
                if not same_block:
                    distance = abs(location.block_order - definition_span.block_order)
                elif location.char_end <= definition_span.char_start:
                    distance = definition_span.char_start - location.char_end
                elif definition_span.char_end <= location.char_start:
                    distance = location.char_start - definition_span.char_end
                else:
                    distance = 0
                return (
                    not standalone_table_label,
                    not same_block,
                    contained,
                    distance,
                    location.char_start,
                )

            term_location = min(
                definition_label_locations,
                key=distance_from_definition,
            )
            term_text = blocks[term_location.block_id].text[
                term_location.char_start : term_location.char_end
            ]
            reference = extract_reference_target(span.definition_text)
            reference_target = None
            reference_location = None
            if reference is not None:
                target, relative_start, relative_end = reference
                reference_target = target
                reference_location = Location(
                    part=definition_location.part,
                    block_id=definition_location.block_id,
                    block_order=definition_location.block_order,
                    char_start=definition_location.char_start + relative_start,
                    char_end=definition_location.char_start + relative_end,
                )
            definitions.append(
                Definition(
                    id=stable_id(
                        "definition",
                        source.document_id,
                        candidate.normalized_term,
                        definition_location.part,
                        definition_location.block_id,
                        definition_location.char_start,
                        definition_location.char_end,
                    ),
                    term=term_text,
                    normalized_term=candidate.normalized_term,
                    definition_text=span.definition_text,
                    location=term_location,
                    pattern="semantic_source_span",
                    reference_target=reference_target,
                    reference_location=reference_location,
                )
            )
    definitions_by_review: dict[str, list[Definition]] = {}
    for definition in definitions:
        candidate = next(
            (
                item
                for item in candidate_list
                if item.normalized_term == definition.normalized_term
            ),
            None,
        )
        if candidate is None:
            raise SemanticReviewError(
                f"materialized definition {definition.id} has no semantic candidate"
            )
        definitions_by_review.setdefault(candidate.review_id, []).append(definition)
    aliases_by_review: dict[str, list[str]] = {}
    candidate_by_review = {item.review_id: item for item in candidate_list}
    for adjudication in adjudications:
        if adjudication.decision != "confirmed_alias":
            continue
        alias_candidate = candidate_by_review[adjudication.review_id]
        aliases_by_review.setdefault(adjudication.canonical_review_id or "", []).append(
            alias_candidate.term
        )
    definitions = [
        replace(
            definition,
            aliases=tuple(
                dict.fromkeys(
                    (*definition.aliases, *aliases_by_review.get(review_id, []))
                )
            ),
        )
        for review_id, definition_group in definitions_by_review.items()
        for definition in definition_group
    ]
    return sorted(
        definitions,
        key=lambda item: (item.location.block_order, item.location.char_start, item.id),
    )
