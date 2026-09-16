"""Contextual review of every potential use of an accepted defined term."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from .analyze import FinalizedTerm
from .models import (
    Definition,
    OccurrenceAdjudication,
    OccurrenceCandidate,
    OccurrenceCollision,
    SemanticReviewSummary,
    SourceDocument,
    Usage,
    stable_id,
)
from .semantic_review import SemanticReviewError
from .term_identity import same_term


@dataclass(frozen=True)
class OccurrenceSubmission:
    review_id: str
    decision: str
    rationale_summary: str
    reason_codes: tuple[str, ...]
    confidence: float | None
    agent_role: str
    model_id: str | None = None
    prompt_version: str | None = None
    review_reason: str | None = None


def _is_all_caps_label(value: str) -> bool:
    letters = [character for character in value if character.isalpha()]
    return bool(letters) and all(character.isupper() for character in letters)


def _is_permitted_presentation_capitalization(
    canonical_term: str, observed_form: str
) -> bool:
    """Allow all-caps labels to follow surrounding document typography."""

    return same_term(canonical_term, observed_form) and (
        _is_all_caps_label(canonical_term) or _is_all_caps_label(observed_form)
    )


def build_occurrence_collisions(
    usages: Iterable[Usage],
    adjudications: Iterable[OccurrenceAdjudication] = (),
) -> tuple[OccurrenceCollision, ...]:
    """Return connected overlap groups without choosing a winning term."""

    usage_list = tuple(usages)
    decision_by_usage = {item.usage_id: item.decision for item in adjudications}
    by_block: dict[str, list[Usage]] = {}
    for usage in usage_list:
        by_block.setdefault(usage.location.block_id, []).append(usage)
    collisions = []
    for block_usages in by_block.values():
        ordered = sorted(
            block_usages,
            key=lambda item: (
                item.location.char_start,
                item.location.char_end,
                item.normalized_term,
                item.id,
            ),
        )
        remaining = set(range(len(ordered)))
        while remaining:
            first_index = min(remaining)
            remaining.remove(first_index)
            component = {first_index}
            changed = True
            while changed:
                changed = False
                for index in tuple(remaining):
                    candidate = ordered[index]
                    if any(
                        candidate.location.char_start
                        < ordered[member].location.char_end
                        and ordered[member].location.char_start
                        < candidate.location.char_end
                        for member in component
                    ):
                        component.add(index)
                        remaining.remove(index)
                        changed = True
            members = [ordered[index] for index in sorted(component)]
            normalized_terms = tuple(
                dict.fromkeys(item.normalized_term for item in members)
            )
            if len(normalized_terms) < 2:
                continue
            start = min(item.location.char_start for item in members)
            end = max(item.location.char_end for item in members)
            first = members[0].location
            collision_id = stable_id(
                "occurrence_collision",
                first.block_id,
                start,
                end,
                *sorted(normalized_terms),
            )
            mapped = []
            rejected = []
            shadowed = []
            unresolved = []
            for usage in members:
                decision = decision_by_usage.get(usage.id)
                if usage.is_definition_occurrence or decision in {
                    "defined_term_use",
                    "inconsistent_capitalization",
                }:
                    mapped.append(usage.id)
                elif decision in {"ordinary_language", "proper_name_component"}:
                    rejected.append(usage.id)
                elif decision == "shadowed_by_overlapping_term":
                    shadowed.append(usage.id)
                else:
                    unresolved.append(usage.id)
            collisions.append(
                OccurrenceCollision(
                    id=collision_id,
                    location=type(first)(
                        part=first.part,
                        block_id=first.block_id,
                        block_order=first.block_order,
                        char_start=start,
                        char_end=end,
                    ),
                    usage_ids=tuple(item.id for item in members),
                    normalized_terms=normalized_terms,
                    mapped_usage_ids=tuple(mapped),
                    rejected_usage_ids=tuple(rejected),
                    shadowed_usage_ids=tuple(shadowed),
                    unresolved_usage_ids=tuple(unresolved),
                )
            )
    return tuple(
        sorted(
            collisions,
            key=lambda item: (
                item.location.block_order,
                item.location.char_start,
                item.location.char_end,
                item.id,
            ),
        )
    )


def build_occurrence_candidates(
    source: SourceDocument,
    definitions: Iterable[Definition],
    usages: Iterable[Usage],
    *,
    finalized_terms: Iterable[FinalizedTerm] | None = None,
) -> tuple[OccurrenceCandidate, ...]:
    """Queue every non-definition occurrence for semantic adjudication.

    Deterministic matching establishes only that source text may invoke an
    accepted defined term. Exact canonical spelling and an allowed alias are
    not semantic decisions, so they receive the same occurrence review as
    case, number, spacing, possessive, and composite variants.
    """

    # Stable usage IDs already bind candidates to the source and accepted term
    # set. Keep the parameters for the public API and envelope-building flow;
    # none of them may be used to suppress an occurrence from semantic review.
    del source, definitions, finalized_terms
    usage_list = tuple(usages)
    collisions = build_occurrence_collisions(usage_list)
    collision_by_usage = {
        usage_id: collision
        for collision in collisions
        for usage_id in collision.usage_ids
    }
    usage_by_id = {item.id: item for item in usage_list}
    records = []
    for usage in usage_list:
        if usage.is_definition_occurrence:
            continue
        collision = collision_by_usage.get(usage.id)
        competitors = (
            [
                usage_by_id[usage_id]
                for usage_id in collision.usage_ids
                if collision is not None and usage_id != usage.id
            ]
            if collision is not None
            else []
        )
        records.append(
            OccurrenceCandidate(
                review_id=stable_id("occurrence_review", usage.id),
                usage_id=usage.id,
                term=usage.term,
                observed_form=usage.observed_form,
                location=usage.location,
                variant_id=usage.variant_id,
                collision_id=collision.id if collision else None,
                competing_usage_ids=tuple(item.id for item in competitors),
                competing_terms=tuple(item.term for item in competitors),
                competing_locations=tuple(item.location for item in competitors),
            )
        )
    return tuple(
        sorted(
            records,
            key=lambda item: (
                item.location.block_order,
                item.location.char_start,
                item.review_id,
            ),
        )
    )


def build_occurrence_envelopes(
    source: SourceDocument,
    definitions: Iterable[Definition],
    candidates: Iterable[OccurrenceCandidate],
    *,
    finalized_terms: Iterable[FinalizedTerm] | None = None,
    max_context_chars: int = 3000,
) -> list[dict[str, Any]]:
    """Give reviewers the definition and occurrence context, without detector cues."""

    blocks = {block.id: block for block in source.blocks}
    definitions_by_term = {}
    for definition in definitions:
        definitions_by_term.setdefault(definition.term, definition)
    finalized_by_term = {
        finalized.term: finalized for finalized in finalized_terms or ()
    }
    envelopes = []
    for candidate in candidates:
        block = blocks[candidate.location.block_id]
        if len(block.text) <= max_context_chars:
            start, end = 0, len(block.text)
        else:
            half = max_context_chars // 2
            start = max(0, candidate.location.char_start - half)
            end = min(len(block.text), start + max_context_chars)
            start = max(0, end - max_context_chars)
        definition = definitions_by_term.get(candidate.term)
        finalized = finalized_by_term.get(candidate.term)
        aliases = (
            definition.aliases if definition else finalized.aliases if finalized else ()
        )
        envelopes.append(
            {
                "review_id": candidate.review_id,
                "usage_id": candidate.usage_id,
                "term": candidate.term,
                "term_status": "defined",
                "definition_text": (
                    definition.definition_text
                    if definition
                    else finalized.definition_text
                    if finalized
                    else None
                ),
                "aliases": list(aliases),
                "observed_form": candidate.observed_form,
                "variant_id": candidate.variant_id,
                "collision_id": candidate.collision_id,
                "collision": (
                    {
                        "surface_start": min(
                            candidate.location.char_start,
                            *(
                                item.char_start
                                for item in candidate.competing_locations
                            ),
                        )
                        - start,
                        "surface_end": max(
                            candidate.location.char_end,
                            *(item.char_end for item in candidate.competing_locations),
                        )
                        - start,
                        "matches": [
                            {
                                "term": term,
                                "match_start": location.char_start - start,
                                "match_end": location.char_end - start,
                            }
                            for term, location in (
                                (candidate.term, candidate.location),
                                *zip(
                                    candidate.competing_terms,
                                    candidate.competing_locations,
                                    strict=True,
                                ),
                            )
                        ],
                    }
                    if candidate.collision_id
                    else None
                ),
                "context": {
                    "text": block.text[start:end],
                    "match_start": candidate.location.char_start - start,
                    "match_end": candidate.location.char_end - start,
                    "location": asdict(candidate.location),
                },
                "allowed_decisions": [
                    "defined_term_use",
                    "ordinary_language",
                    "proper_name_component",
                    "inconsistent_capitalization",
                    "shadowed_by_overlapping_term",
                    "needs_review",
                    "insufficient_evidence",
                ],
            }
        )
    return envelopes


def reconcile_occurrences(
    candidates: Iterable[OccurrenceCandidate],
    submissions: Iterable[OccurrenceSubmission],
) -> tuple[tuple[OccurrenceAdjudication, ...], SemanticReviewSummary]:
    """Require one semantic disposition for every ambiguous occurrence."""

    candidate_list = tuple(candidates)
    candidate_map = {item.review_id: item for item in candidate_list}
    submitted = tuple(submissions)
    ids = [item.review_id for item in submitted]
    if len(ids) != len(set(ids)):
        raise SemanticReviewError(
            "occurrence bundle contains duplicate review_id decisions"
        )
    expected = set(candidate_map)
    actual = set(ids)
    if actual != expected:
        raise SemanticReviewError(
            "occurrence review queue is incomplete or mismatched; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )
    decisions = []
    submission_by_usage = {
        candidate_map[item.review_id].usage_id: item for item in submitted
    }
    for submission in submitted:
        candidate = candidate_map[submission.review_id]
        decision = submission.decision
        rationale_summary = submission.rationale_summary
        reason_codes = submission.reason_codes
        if decision == "inconsistent_capitalization" and (
            _is_permitted_presentation_capitalization(
                candidate.term, candidate.observed_form
            )
        ):
            decision = "defined_term_use"
            rationale_summary = (
                "The occurrence invokes the defined concept; all-caps and ordinary "
                "capitalization are permitted presentation variants."
            )
            reason_codes = tuple(
                dict.fromkeys((*reason_codes, "allowed_presentation_capitalization"))
            )
        if decision == "shadowed_by_overlapping_term":
            if candidate.collision_id is None:
                raise SemanticReviewError(
                    f"shadowed occurrence {submission.review_id} is not in a collision"
                )
            competing_submissions = [
                submission_by_usage[usage_id]
                for usage_id in candidate.competing_usage_ids
                if usage_id in submission_by_usage
            ]
            if len(competing_submissions) == len(
                candidate.competing_usage_ids
            ) and not any(
                item.decision in {"defined_term_use", "inconsistent_capitalization"}
                for item in competing_submissions
            ):
                raise SemanticReviewError(
                    f"shadowed occurrence {submission.review_id} lacks a mapped overlapping term"
                )
        decisions.append(
            OccurrenceAdjudication(
                id=stable_id("occurrence_adjudication", submission.review_id, decision),
                review_id=submission.review_id,
                usage_id=candidate.usage_id,
                decision=decision,
                rationale_summary=rationale_summary,
                reason_codes=reason_codes,
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
    return ordered, SemanticReviewSummary(
        "complete",
        len(candidate_list),
        len(ordered),
        unresolved,
        review_execution="external_bundle",
        review_id_namespace="opaque-occurrence-v1",
    )
