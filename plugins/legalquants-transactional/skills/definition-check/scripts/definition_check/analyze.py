"""Deterministic usage indexing and initial definition-check rules."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace

from .models import (
    Definition,
    Finding,
    Location,
    OccurrenceAdjudication,
    ReferenceAdjudication,
    ReferenceCandidate,
    SemanticAdjudication,
    SourceDocument,
    TermCandidate,
    TermVariant,
    Usage,
    stable_id,
)
from .term_identity import term_key, term_pattern

# These are deliberately narrow.  Callers can add their own document-specific
# noise controls through ``common_terms`` without changing the analysis.
DEFAULT_COMMON_TERMS = frozenset(
    {
        "section",
        "schedule",
        "exhibit",
        "article",
    }
)

_DEFINITION_SCOPE_IMPORT = re.compile(
    r"\bcapitali[sz]ed\s+terms?\b.{0,180}?\bnot\s+defined\b.{0,180}?"
    r"\b(?:meaning|meanings)\b.{0,80}?\b(?:given|set\s+out|ascribed)\b"
    r".{0,40}?\b(?:in|under)\s+(?:the\s+)?"
    r"(?P<target>[A-Z][A-Za-z0-9&'\u2019 -]{1,100}?)(?=[.;,]|$)",
    re.IGNORECASE,
)


class AnalysisError(ValueError):
    """Raised when finalized analysis inputs violate queue invariants."""


def _candidate_for_review(
    candidates_by_review: dict[str, TermCandidate], review_id: str
) -> TermCandidate:
    candidate = candidates_by_review.get(review_id)
    if candidate is None:
        raise AnalysisError(
            f"semantic adjudication references unknown review ID {review_id}"
        )
    return candidate


def apply_definition_scope_qualifications(
    source: SourceDocument,
    candidates: Iterable[TermCandidate],
    adjudications: Iterable[SemanticAdjudication],
) -> tuple[SemanticAdjudication, ...]:
    """Attach an exact source-backed inherited-definition qualifier when stated."""

    notice: tuple[str, Location] | None = None
    for block in sorted(source.blocks, key=lambda item: (item.order, item.id)):
        match = _DEFINITION_SCOPE_IMPORT.search(block.text)
        if match is None:
            continue
        target = match.group("target").strip()
        target_start = (
            match.start("target")
            + len(match.group("target"))
            - len(match.group("target").lstrip())
        )
        notice = (
            target,
            block.location(target_start, target_start + len(target)),
        )
        break
    candidate_by_review = {item.review_id: item for item in candidates}
    qualified = []
    for adjudication in adjudications:
        if adjudication.decision != "confirmed_undefined" or notice is None:
            qualified.append(adjudication)
            continue
        candidate = _candidate_for_review(candidate_by_review, adjudication.review_id)
        if not candidate.term[:1].isupper():
            qualified.append(adjudication)
            continue
        target, location = notice
        qualified.append(
            replace(
                adjudication,
                scope_qualification="possible_inherited_definition",
                scope_target=target,
                scope_evidence=(location,),
            )
        )
    return tuple(sorted(qualified, key=lambda item: item.review_id))


def _normalise(value: str) -> str:
    return term_key(value)


def _common_terms(common_terms: Iterable[str] | None) -> set[str]:
    terms = set(DEFAULT_COMMON_TERMS)
    if common_terms:
        terms.update(_normalise(term) for term in common_terms)
    return terms


def _term_pattern(value: str) -> re.Pattern[str]:
    # A term may contain ordinary spaces; accept only a spacing *variant* for
    # indexing so DEF-004 can report it. Capture a singular possessive suffix
    # as part of the occurrence rather than leaving it outside the source span.
    return term_pattern(value, allow_possessive=True)


def _maximal_spelling_matches[MatchOwner](
    text: str,
    spellings: Iterable[tuple[str, MatchOwner]],
) -> list[tuple[MatchOwner, re.Match[str]]]:
    """Return lexical matches that are not contained in a longer accepted label."""

    matches = [
        (owner, match)
        for spelling, owner in spellings
        for match in _term_pattern(spelling).finditer(text)
    ]
    return [
        (owner, match)
        for owner, match in matches
        if not any(
            other.start() <= match.start()
            and match.end() <= other.end()
            and (other.end() - other.start()) > (match.end() - match.start())
            for _, other in matches
        )
    ]


def _plural_form(value: str) -> str | None:
    words = value.split()
    if not words:
        return None
    final = words[-1]
    folded = final.casefold()
    if folded.endswith("ies") or folded.endswith("ses") or folded.endswith("ss"):
        return None
    if folded.endswith("y") and len(final) > 1 and final[-2].casefold() not in "aeiou":
        plural = final[:-1] + ("IES" if final.isupper() else "ies")
    elif folded.endswith(("s", "x", "z", "ch", "sh")):
        plural = final + ("ES" if final.isupper() else "es")
    else:
        plural = final + ("S" if final.isupper() else "s")
    words[-1] = plural
    return " ".join(words)


def _variant_type(
    observed_form: str,
    canonical_term: str,
    allowed_forms: Iterable[str],
) -> str | None:
    """Classify a non-canonical form without deciding semantic identity."""

    if observed_form == canonical_term:
        return None
    allowed = tuple(allowed_forms)
    if observed_form in allowed:
        return "alias"
    observed_folded = observed_form.casefold()
    if any(
        observed_folded == (_plural_form(form) or "").casefold() for form in allowed
    ):
        return "plural"
    if any(
        (_plural_form(observed_form) or "").casefold() == form.casefold()
        for form in allowed
    ):
        return "singular"
    if any(
        observed_folded in {f"{form.casefold()}'s", f"{form.casefold()}\u2019s"}
        for form in allowed
    ):
        return "possessive"
    if any(observed_folded == form.casefold() for form in allowed):
        return "capitalization"
    if any(_normalise(observed_form) == _normalise(form) for form in allowed):
        return "spacing"
    return "composite"


def _variant_id(
    normalized_term: str, observed_form: str, variant_type: str | None
) -> str | None:
    if variant_type is None:
        return None
    return stable_id("term_variant", normalized_term, observed_form, variant_type)


def build_term_variants(
    usages: Iterable[Usage],
    definitions: Iterable[Definition],
    occurrence_adjudications: Iterable[OccurrenceAdjudication] = (),
    *,
    occurrence_review_complete: bool = False,
    finalized_terms: Iterable[FinalizedTerm] | None = None,
) -> list[TermVariant]:
    """Materialize variant forms and preserve the outcome of every instance."""

    forms: dict[str, tuple[str, ...]] = {}
    canonical: dict[str, str] = {}
    if finalized_terms is not None:
        for item in finalized_terms:
            forms[item.normalized_term] = item.allowed_forms
            canonical[item.normalized_term] = item.term
    else:
        for item in definitions:
            forms[item.normalized_term] = (item.term, *item.aliases)
            canonical[item.normalized_term] = item.term

    decision_by_usage = {
        str(item.usage_id): str(item.decision) for item in occurrence_adjudications
    }
    grouped: dict[str, list[Usage]] = defaultdict(list)
    metadata: dict[str, tuple[str, str, str, str]] = {}
    for usage in usages:
        allowed = forms.get(usage.normalized_term, (usage.term,))
        kind = _variant_type(
            usage.observed_form,
            canonical.get(usage.normalized_term, usage.term),
            allowed,
        )
        variant_id = _variant_id(usage.normalized_term, usage.observed_form, kind)
        if variant_id is None:
            continue
        grouped[variant_id].append(usage)
        metadata[variant_id] = (
            usage.term,
            usage.normalized_term,
            usage.observed_form,
            str(kind),
        )

    variants = []
    for variant_id, instances in grouped.items():
        mapped = []
        rejected = []
        shadowed = []
        unresolved = []
        for usage in instances:
            decision = decision_by_usage.get(usage.id)
            if decision in {"defined_term_use", "inconsistent_capitalization"}:
                mapped.append(usage.id)
            elif decision in {"ordinary_language", "proper_name_component"}:
                rejected.append(usage.id)
            elif decision == "shadowed_by_overlapping_term":
                shadowed.append(usage.id)
            elif decision in {"needs_review", "insufficient_evidence"}:
                unresolved.append(usage.id)
            elif decision is None and usage.is_definition_occurrence:
                mapped.append(usage.id)
            elif decision is None and occurrence_review_complete:
                mapped.append(usage.id)
            else:
                unresolved.append(usage.id)
        outcome_kinds = sum(
            bool(items) for items in (mapped, rejected, shadowed, unresolved)
        )
        if outcome_kinds > 1:
            status = "mixed"
        elif rejected and not mapped and not unresolved:
            status = "rejected"
        elif shadowed and not mapped and not rejected and not unresolved:
            status = "shadowed"
        elif mapped and not unresolved:
            status = "mapped"
        else:
            status = "unresolved"
        term, normalized_term, observed_form, kind = metadata[variant_id]
        variants.append(
            TermVariant(
                id=variant_id,
                term=term,
                normalized_term=normalized_term,
                observed_form=observed_form,
                variant_type=kind,
                mapping_status=status,
                usage_ids=tuple(item.id for item in instances),
                mapped_usage_ids=tuple(mapped),
                rejected_usage_ids=tuple(rejected),
                shadowed_usage_ids=tuple(shadowed),
                unresolved_usage_ids=tuple(unresolved),
            )
        )
    return sorted(
        variants, key=lambda item: (item.normalized_term, item.observed_form, item.id)
    )


def is_likely_heading(text: str) -> bool:
    """Return a non-authoritative structural hint; never use it to drop text."""
    stripped = text.strip()
    if not stripped or len(stripped) > 180 or len(stripped.split()) > 20:
        return False
    letters = "".join(char for char in stripped if char.isalpha())
    if letters and letters == letters.upper():
        return True
    return bool(
        re.match(
            r"^(?:(?:article|section)\s+)?(?:[ivxlcdm]+|\d+(?:\.\d+)*)[.)]?\s+\S",
            stripped,
            re.IGNORECASE,
        )
    )


def _in_definition(location: Location, definition: Definition, block_text: str) -> bool:
    # Only the introducing label is excluded. Self-references in the meaning
    # body still need contextual occurrence review, even in the same paragraph.
    return (
        location.part == definition.location.part
        and location.block_id == definition.location.block_id
        and definition.location.char_start <= location.char_start
        and location.char_end <= definition.location.char_end
    )


@dataclass(frozen=True)
class FinalizedTerm:
    """Semantically accepted term specification for the final usage scan."""

    term: str
    normalized_term: str
    aliases: tuple[str, ...]
    definitions: tuple[Definition, ...]
    semantic_definition_locations: tuple[Location, ...]
    definition_text: str | None
    inflections: tuple[str, ...] = ()

    @property
    def allowed_forms(self) -> tuple[str, ...]:
        return (self.term, *self.aliases)

    @property
    def indexed_forms(self) -> tuple[str, ...]:
        return (*self.allowed_forms, *self.inflections)


def build_finalized_terms(
    source: SourceDocument,
    definitions: Iterable[Definition],
    candidates: Iterable[TermCandidate],
    adjudications: Iterable[SemanticAdjudication],
) -> tuple[FinalizedTerm, ...]:
    """Return every semantically confirmed defined term and its source evidence."""

    definitions_by_normalized: dict[str, list[Definition]] = defaultdict(list)
    for definition in definitions:
        definitions_by_normalized[definition.normalized_term].append(definition)
    candidate_list = tuple(candidates)
    adjudication_list = tuple(adjudications)
    candidates_by_review = {
        candidate.review_id: candidate for candidate in candidate_list
    }
    confirmed_defined_reviews = {
        adjudication.review_id
        for adjudication in adjudication_list
        if adjudication.decision == "confirmed_defined"
    }
    blocks = {block.id: block for block in source.blocks}
    finalized = []
    for adjudication in adjudication_list:
        if adjudication.decision != "confirmed_defined":
            continue
        candidate = _candidate_for_review(candidates_by_review, adjudication.review_id)
        matched_definitions = tuple(
            sorted(
                definitions_by_normalized.get(candidate.normalized_term, []),
                key=lambda item: (
                    item.location.block_order,
                    item.location.char_start,
                    item.id,
                ),
            )
        )
        aliases = tuple(
            dict.fromkeys(
                alias
                for definition in matched_definitions
                for alias in definition.aliases
                if alias.strip()
            )
        )
        canonical_term = (
            matched_definitions[0].term if matched_definitions else candidate.term
        )
        canonical_forms = {term_key(form) for form in (canonical_term, *aliases)}
        inflections = tuple(
            dict.fromkeys(
                related.term
                for related in candidate_list
                if related.review_id not in confirmed_defined_reviews
                and related.normalized_term != candidate.normalized_term
                and term_key(_plural_form(related.term) or "") in canonical_forms
            )
        )
        semantic_locations = tuple(adjudication.evidence) or candidate.locations[:1]
        if matched_definitions:
            definition_text = matched_definitions[0].definition_text
        elif semantic_locations and (
            block := blocks.get(semantic_locations[0].block_id)
        ):
            definition_text = block.text
        else:
            definition_text = None
        semantic_label_locations = tuple(
            definition.location for definition in matched_definitions
        )
        if not semantic_label_locations:
            semantic_label_locations = tuple(
                location
                for location in candidate.locations
                if adjudication.definition_location is not None
                and location.part == adjudication.definition_location.part
                and location.block_id == adjudication.definition_location.block_id
                and adjudication.definition_location.char_start <= location.char_start
                and location.char_end <= adjudication.definition_location.char_end
            )
        if not semantic_label_locations:
            semantic_label_locations = candidate.locations[:1]
        finalized.append(
            FinalizedTerm(
                term=canonical_term,
                normalized_term=candidate.normalized_term,
                aliases=aliases,
                inflections=inflections,
                definitions=matched_definitions,
                semantic_definition_locations=semantic_label_locations,
                definition_text=definition_text,
            )
        )
    return tuple(sorted(finalized, key=lambda item: (item.normalized_term, item.term)))


def _is_finalized_definition_occurrence(
    location: Location,
    finalized: FinalizedTerm,
    block_text: str,
) -> bool:
    if any(
        _in_definition(location, definition, block_text)
        for definition in finalized.definitions
    ):
        return True
    return any(
        location.part == evidence.part
        and location.block_id == evidence.block_id
        and evidence.char_start <= location.char_start
        and location.char_end <= evidence.char_end
        for evidence in finalized.semantic_definition_locations
    )


def build_finalized_usages(
    source: SourceDocument,
    finalized_terms: Iterable[FinalizedTerm],
    *,
    candidates: Iterable[TermCandidate] = (),
    adjudications: Iterable[SemanticAdjudication] = (),
) -> list[Usage]:
    """Re-scan accepted terms and suppress matches inside longer retained labels."""

    spellings: list[tuple[str, FinalizedTerm]] = []
    for finalized in finalized_terms:
        for spelling in finalized.indexed_forms:
            if not spelling.strip():
                continue
            spellings.append((spelling, finalized))
            plural = _plural_form(spelling)
            if plural and term_key(plural) not in {
                term_key(form) for form in finalized.allowed_forms
            }:
                spellings.append((plural, finalized))
    spellings.sort(key=lambda item: (-len(item[0]), item[0].casefold(), item[1].term))

    usages: list[Usage] = []
    for block in sorted(source.blocks, key=lambda item: (item.order, item.id)):
        seen: set[tuple[str, int, int]] = set()
        for finalized, match in _maximal_spelling_matches(block.text, spellings):
            span = (match.start(), match.end())
            key = (finalized.normalized_term, *span)
            if key in seen:
                continue
            seen.add(key)
            location = block.location(*span)
            observed_form = match.group(0)
            variant_type = _variant_type(
                observed_form,
                finalized.term,
                finalized.allowed_forms,
            )
            usages.append(
                Usage(
                    id=stable_id(
                        "use",
                        source.document_id,
                        finalized.normalized_term,
                        location.block_id,
                        location.char_start,
                        location.char_end,
                    ),
                    term=finalized.term,
                    normalized_term=finalized.normalized_term,
                    observed_form=observed_form,
                    location=location,
                    is_definition_occurrence=_is_finalized_definition_occurrence(
                        location, finalized, block.text
                    ),
                    variant_id=_variant_id(
                        finalized.normalized_term,
                        observed_form,
                        variant_type,
                    ),
                )
            )
    retained_candidate_locations = _retained_candidate_locations(
        source,
        candidates,
        adjudications,
    )
    usages = [
        usage
        for usage in usages
        if not any(
            other.part == usage.location.part
            and other.block_id == usage.location.block_id
            and other.char_start <= usage.location.char_start
            and usage.location.char_end <= other.char_end
            and (other.char_end - other.char_start)
            > (usage.location.char_end - usage.location.char_start)
            for other in retained_candidate_locations
        )
    ]
    return sorted(
        usages,
        key=lambda item: (
            item.location.block_order,
            item.location.char_start,
            item.location.char_end,
            item.normalized_term,
            item.id,
        ),
    )


def _retained_candidate_locations(
    source: SourceDocument,
    candidates: Iterable[TermCandidate],
    adjudications: Iterable[SemanticAdjudication],
) -> tuple[Location, ...]:
    """Return exact-spelled locations for every semantically retained label."""

    candidates_by_review = {candidate.review_id: candidate for candidate in candidates}
    adjudications_by_review = {
        adjudication.review_id: adjudication for adjudication in adjudications
    }
    blocks_by_id = {block.id: block for block in source.blocks}
    return tuple(
        location
        for review_id, candidate in candidates_by_review.items()
        if adjudications_by_review.get(review_id) is not None
        and adjudications_by_review[review_id].decision
        in {"confirmed_defined", "confirmed_undefined", "confirmed_alias"}
        for location in candidate.locations
        if blocks_by_id[location.block_id].text[location.char_start : location.char_end]
        == candidate.term
    )


def _is_grammatical_capitalization(text: str, start: int) -> bool:
    """Return whether capitalization is explained by a sentence or list start."""

    prefix = text[:start]
    return bool(
        re.search(
            r"(?:^|[.!?:]\s+)[\"'\u2018\u201c\[(]*\s*(?:[-\u2013\u2014\u2022*]\s+|"
            r"[\[(]?(?:\d+|[A-Za-z])[\]).]\s+)?$",
            prefix,
        )
    )


def rebuild_finalized_findings(
    source: SourceDocument,
    initial_findings: Iterable[Finding],
    definitions: list[Definition],
    finalized_terms: Iterable[FinalizedTerm],
    usages: list[Usage],
    candidates: Iterable[TermCandidate],
    adjudications: Iterable[SemanticAdjudication],
    common_terms: Iterable[str] | None = None,
    reference_candidates: Iterable[ReferenceCandidate] = (),
    reference_adjudications: Iterable[ReferenceAdjudication] = (),
    reference_review_complete: bool = False,
) -> list[Finding]:
    """Refresh usage-sensitive rules against the authoritative final index."""

    finalized = tuple(finalized_terms)
    preserved = [
        finding
        for finding in initial_findings
        if finding.rule_id
        not in {
            "DEF-001",
            "DEF-002",
            "DEF-003",
            "DEF-004",
            "DEF-005",
            "DEF-006",
            "DEF-007",
        }
    ]
    refreshed = [
        finding
        for finding in run_rules(
            source,
            definitions,
            usages,
            common_terms=common_terms,
        )
        if finding.rule_id in {"DEF-002", "DEF-003", "DEF-004", "DEF-005"}
    ]

    candidates = tuple(candidates)
    adjudications = tuple(adjudications)
    candidates_by_review = {candidate.review_id: candidate for candidate in candidates}
    retained_candidate_locations = _retained_candidate_locations(
        source,
        candidates,
        adjudications,
    )
    retained_usage_locations = tuple(usage.location for usage in usages)
    blocks_by_id = {block.id: block for block in source.blocks}
    for adjudication in adjudications:
        if adjudication.decision == "confirmed_external_reference":
            candidate = _candidate_for_review(
                candidates_by_review, adjudication.review_id
            )
            evidence = adjudication.evidence or candidate.locations
            if evidence:
                refreshed.append(
                    _finding(
                        source,
                        "DEF-007",
                        "info",
                        f"'{candidate.term}' identifies a referenced document that was not checked.",
                        candidate.normalized_term,
                        tuple(evidence),
                        kind="semantic",
                    )
                )
            continue
        # Explicit semantic rejections are authoritative, including capitalized
        # headings and fragments. Only accepted undefined labels reach projection.
        if adjudication.decision != "confirmed_undefined":
            continue
        candidate = _candidate_for_review(candidates_by_review, adjudication.review_id)
        evidence = tuple(
            location
            for location in candidate.locations
            if blocks_by_id[location.block_id].text[
                location.char_start : location.char_end
            ]
            == candidate.term
            and not any(
                other.part == location.part
                and other.block_id == location.block_id
                and other.char_start <= location.char_start
                and location.char_end <= other.char_end
                and (other.char_end - other.char_start)
                > (location.char_end - location.char_start)
                for other in (
                    *retained_candidate_locations,
                    *retained_usage_locations,
                )
            )
        )
        if not evidence:
            continue
        refreshed.append(
            _finding(
                source,
                "DEF-001",
                "medium",
                f"'{candidate.term}' is used but not defined.",
                candidate.normalized_term,
                evidence,
                scope_qualification=adjudication.scope_qualification,
                scope_target=adjudication.scope_target,
                scope_evidence=adjudication.scope_evidence,
            )
        )

    deterministic_normalized = {
        definition.normalized_term for definition in definitions
    }
    for term in finalized:
        if term.normalized_term in deterministic_normalized:
            continue
        variants = [
            usage
            for usage in usages
            if usage.normalized_term == term.normalized_term
            and usage.observed_form not in set(term.allowed_forms)
        ]
        if not variants:
            continue
        matching_candidate = next(
            (
                candidate
                for candidate in candidates_by_review.values()
                if candidate.normalized_term == term.normalized_term
            ),
            None,
        )
        if matching_candidate is None:
            raise AnalysisError(
                f"finalized term {term.normalized_term} has no semantic candidate"
            )
        anchor = matching_candidate.locations[0]
        refreshed.append(
            _finding(
                source,
                "DEF-004",
                "low",
                f"'{term.term}' is used as '{variants[0].observed_form}', which is not an allowed alias.",
                term.normalized_term,
                (anchor, *(variant.location for variant in variants)),
            )
        )

    reference_candidates = tuple(reference_candidates)
    reference_adjudications = tuple(reference_adjudications)
    if reference_review_complete:
        reference_by_review = {
            candidate.review_id: candidate for candidate in reference_candidates
        }
        if len(reference_by_review) != len(reference_candidates):
            raise AnalysisError("reference queue contains duplicate review IDs")
        adjudication_by_review = {
            adjudication.review_id: adjudication
            for adjudication in reference_adjudications
        }
        if set(adjudication_by_review) != set(reference_by_review):
            raise AnalysisError(
                "complete reference review must cover every queued reference"
            )
        for adjudication in adjudication_by_review.values():
            if adjudication.decision != "broken":
                continue
            candidate = reference_by_review[adjudication.review_id]
            evidence = tuple(
                dict.fromkeys(
                    (
                        candidate.location,
                        candidate.reference_location,
                        *adjudication.evidence,
                    )
                )
            )
            refreshed.append(
                _finding(
                    source,
                    "DEF-006",
                    "medium",
                    f"'{candidate.term}' references unresolved '{candidate.reference_target}' within the supplied review scope.",
                    candidate.normalized_term,
                    evidence,
                    kind="semantic",
                )
            )

    return sorted(
        [*preserved, *refreshed],
        key=lambda item: (
            item.rule_id,
            item.normalized_term or "",
            item.evidence[0].block_order,
            item.evidence[0].char_start,
            item.id,
        ),
    )


def apply_occurrence_review_to_findings(
    findings: Iterable[Finding],
    usages: Iterable[Usage],
    adjudications: Iterable[OccurrenceAdjudication],
    *,
    occurrence_review_complete: bool = False,
    source: SourceDocument | None = None,
    definitions: Iterable[Definition] | None = None,
) -> list[Finding]:
    """Apply completed occurrence decisions to the canonical finding inventory."""

    findings = list(findings)
    if not occurrence_review_complete:
        return findings
    if (source is None) != (definitions is None):
        raise AnalysisError(
            "occurrence finding refresh requires source and definitions"
        )

    usages = list(usages)
    decision_by_usage = {
        adjudication.usage_id: adjudication.decision for adjudication in adjudications
    }
    usage_by_location = {usage.location: usage for usage in usages}
    decision_by_location = {
        usage.location: decision_by_usage[usage.id]
        for usage in usage_by_location.values()
        if usage.id in decision_by_usage
    }

    reviewed: list[Finding] = []
    if source is not None and definitions is not None:
        # These rules depend on the entire retained inventory, not just the
        # lexical occurrence previously chosen as a finding's evidence.
        findings = [
            item for item in findings if item.rule_id not in {"DEF-002", "DEF-005"}
        ]
        definitions_by_term: dict[str, list[Definition]] = defaultdict(list)
        usages_by_term: dict[str, list[Usage]] = defaultdict(list)
        rejected = {
            "ordinary_language",
            "proper_name_component",
            "shadowed_by_overlapping_term",
        }
        operative = {"defined_term_use", "inconsistent_capitalization"}
        for definition in definitions:
            definitions_by_term[definition.normalized_term].append(definition)
        for usage in usages:
            if (
                not usage.is_definition_occurrence
                and decision_by_usage.get(usage.id) not in rejected
            ):
                usages_by_term[usage.normalized_term].append(usage)
        for normalized, group in sorted(definitions_by_term.items()):
            first = min(
                group,
                key=lambda item: (
                    item.location.block_order,
                    item.location.char_start,
                    item.id,
                ),
            )
            retained = usages_by_term[normalized]
            if not retained:
                reviewed.append(
                    _finding(
                        source,
                        "DEF-002",
                        "low",
                        f"'{first.term}' is defined but not used outside its defining span.",
                        normalized,
                        (first.location,),
                    )
                )
            before = [
                usage
                for usage in retained
                if (usage.location.block_order, usage.location.char_start)
                < (first.location.block_order, first.location.char_start)
            ]
            # Unresolved mentions prevent a non-use conclusion but cannot
            # establish early use. Their adjudications remain pending in the
            # occurrence inventory and lawyer-facing unresolved review cards.
            confirmed = [
                usage
                for usage in before
                if decision_by_usage.get(usage.id) in operative
            ]
            if confirmed:
                earliest = min(
                    confirmed,
                    key=lambda item: (
                        item.location.block_order,
                        item.location.char_start,
                        item.id,
                    ),
                )
                reviewed.append(
                    _finding(
                        source,
                        "DEF-005",
                        "low",
                        f"'{first.term}' is used before its first definition.",
                        normalized,
                        (earliest.location, first.location),
                    )
                )
    for finding in findings:
        if finding.rule_id == "DEF-001":
            evidence = tuple(
                location
                for location in finding.evidence
                if decision_by_location.get(location)
                not in {
                    "defined_term_use",
                    "inconsistent_capitalization",
                    "ordinary_language",
                    "proper_name_component",
                    "shadowed_by_overlapping_term",
                }
            )
            if evidence:
                reviewed.append(replace(finding, evidence=evidence))
            continue

        if finding.rule_id not in {"DEF-004", "DEF-005"}:
            reviewed.append(finding)
            continue

        if finding.rule_id == "DEF-004" and len(finding.evidence) >= 2:
            prefix = finding.evidence[:1]
            candidate_evidence = finding.evidence[1:]
            suffix: tuple[Location, ...] = ()
        elif finding.rule_id == "DEF-005" and len(finding.evidence) >= 2:
            prefix = ()
            candidate_evidence = finding.evidence[:-1]
            suffix = finding.evidence[-1:]
        else:
            prefix = ()
            candidate_evidence = finding.evidence
            suffix = ()

        projected_evidence = tuple(
            location
            for location in candidate_evidence
            if decision_by_location.get(location)
            not in (
                {
                    "ordinary_language",
                    "proper_name_component",
                    "shadowed_by_overlapping_term",
                }
                | ({"defined_term_use"} if finding.rule_id == "DEF-004" else set())
            )
        )
        if candidate_evidence and not projected_evidence:
            continue

        message = finding.message
        if finding.rule_id == "DEF-004" and projected_evidence:
            first_variant = usage_by_location.get(projected_evidence[0])
            if first_variant is not None:
                message = (
                    f"'{first_variant.term}' is used as "
                    f"'{first_variant.observed_form}', which is not an allowed alias."
                )
        reviewed.append(
            replace(
                finding,
                evidence=(*prefix, *projected_evidence, *suffix),
                message=message,
            )
        )
    return reviewed


def build_usages(
    source: SourceDocument,
    definitions: list[Definition],
    common_terms: Iterable[str] | None = None,
) -> list[Usage]:
    """Index exact term/alias occurrences, including case and spacing variants.

    Each occurrence belongs to one canonical definition term. A match contained
    in a longer accepted label is suppressed; non-containing overlaps remain for
    semantic collision review.
    """
    del common_terms  # reserved for the candidate-discovery portion of analysis
    spellings: list[tuple[str, Definition]] = []
    for definition in definitions:
        for spelling in (definition.term, *definition.aliases):
            if spelling.strip():
                spellings.append((spelling, definition))
                plural = _plural_form(spelling)
                if plural and term_key(plural) not in {
                    term_key(definition.term),
                    *(term_key(alias) for alias in definition.aliases),
                }:
                    spellings.append((plural, definition))
    spellings.sort(key=lambda item: (-len(item[0]), item[0].casefold(), item[1].id))

    usages: list[Usage] = []
    for block in sorted(source.blocks, key=lambda item: (item.order, item.id)):
        seen: set[tuple[str, int, int]] = set()
        for definition, match in _maximal_spelling_matches(block.text, spellings):
            span = (match.start(), match.end())
            key = (definition.normalized_term, *span)
            if key in seen:
                continue
            seen.add(key)
            location = block.location(*span)
            observed_form = match.group(0)
            allowed_forms = (definition.term, *definition.aliases)
            variant_type = _variant_type(
                observed_form,
                definition.term,
                allowed_forms,
            )
            usages.append(
                Usage(
                    id=stable_id(
                        "use",
                        source.document_id,
                        definition.normalized_term,
                        location.block_id,
                        location.char_start,
                        location.char_end,
                    ),
                    term=definition.term,
                    normalized_term=definition.normalized_term,
                    observed_form=observed_form,
                    location=location,
                    is_definition_occurrence=_in_definition(
                        location, definition, block.text
                    ),
                    variant_id=_variant_id(
                        definition.normalized_term,
                        observed_form,
                        variant_type,
                    ),
                )
            )
    return sorted(
        usages,
        key=lambda item: (
            item.location.block_order,
            item.location.char_start,
            item.location.char_end,
            item.normalized_term,
            item.id,
        ),
    )


def _candidate_usages(
    source: SourceDocument, definitions: list[Definition], common: set[str]
) -> list[Usage]:
    known_spans = {
        (u.location.block_id, u.location.char_start, u.location.char_end)
        for u in build_usages(source, definitions)
    }
    # Two or more Title Case words or an all-caps multiword label.  Single title
    # case words create too much sentence-start/entity noise for DEF-001.
    pattern = re.compile(
        r"(?<!\w)(?:[A-Z][A-Za-z0-9'-]*\s+){1,}[A-Z][A-Za-z0-9'-]*(?!\w)|(?<!\w)(?:[A-Z]{2,}\s+)+[A-Z]{2,}(?!\w)"
    )
    candidates: list[Usage] = []
    for block in sorted(source.blocks, key=lambda item: (item.order, item.id)):
        for match in pattern.finditer(block.text):
            observed = match.group(0)
            normalized = _normalise(observed)
            span_key = (block.id, match.start(), match.end())
            location = block.location(match.start(), match.end())
            first_word = normalized.split()[0]
            sentence_noise = {
                "a",
                "an",
                "the",
                "this",
                "that",
                "these",
                "those",
                "each",
                "any",
                "no",
                "if",
                "when",
                "upon",
                "subject",
                "for",
                "notwithstanding",
            }
            inside_definition = any(
                _in_definition(location, definition, block.text)
                for definition in definitions
            )
            is_reference_target = any(
                definition.location.block_id == block.id
                and definition.reference_target
                and normalized == _normalise(definition.reference_target).rstrip(".,;:")
                for definition in definitions
            )
            if (
                normalized in common
                or span_key in known_spans
                or first_word in sentence_noise
                or inside_definition
                or is_reference_target
            ):
                continue
            candidates.append(
                Usage(
                    id=stable_id(
                        "candidate",
                        source.document_id,
                        normalized,
                        block.id,
                        match.start(),
                        match.end(),
                    ),
                    term=observed,
                    normalized_term=normalized,
                    observed_form=observed,
                    location=location,
                )
            )
    return candidates


def _finding(
    source: SourceDocument,
    rule_id: str,
    severity: str,
    message: str,
    normalized_term: str | None,
    evidence: tuple[Location, ...],
    kind: str = "deterministic",
    scope_qualification: str = "none",
    scope_target: str | None = None,
    scope_evidence: tuple[Location, ...] = (),
) -> Finding:
    primary = evidence[0]
    return Finding(
        id=stable_id(
            "finding",
            rule_id,
            source.document_id,
            normalized_term or "",
            primary.part,
            primary.block_id,
            primary.char_start,
            primary.char_end,
        ),
        rule_id=rule_id,
        kind=kind,
        severity=severity,
        message=message,
        normalized_term=normalized_term,
        evidence=evidence,
        scope_qualification=scope_qualification,
        scope_target=scope_target,
        scope_evidence=scope_evidence,
    )


def _reference_resolved(
    source: SourceDocument, definition: Definition, by_term: dict[str, list[Definition]]
) -> bool:
    if not definition.reference_target:
        return True
    target = _normalise(definition.reference_target)
    if target in by_term:
        return True

    anchors = [definition.reference_target]
    structured = re.match(
        r"^(?:section|article)\s+(.+)$", definition.reference_target, re.IGNORECASE
    )
    if structured:
        anchors.append(structured.group(1))

    def is_heading(text: str) -> bool:
        for anchor in anchors:
            words = [re.escape(word) for word in anchor.split()]
            match = re.match(
                r"^\s*"
                + r"\s+".join(words)
                + r"(?:\s*[:\-–—]\s*|\s+)(?P<title>.*?)\s*$",
                text,
                re.IGNORECASE,
            )
            if not match:
                if _normalise(text) == _normalise(anchor):
                    return True
                continue
            title = match.group("title").split(".", 1)[0].rstrip()
            if not title or re.search(r"[.!?;]", title):
                continue
            title_words = re.findall(r"[A-Za-z][A-Za-z0-9'-]*", title)
            if 1 <= len(title_words) <= 12 and all(
                word[0].isupper()
                or word.isupper()
                or word.casefold() in {"and", "or", "of", "the", "to", "for", "in"}
                for word in title_words
            ):
                return True
        return False

    for block in source.blocks:
        if block.id != definition.location.block_id and is_heading(block.text):
            return True
    return False


def run_rules(
    source: SourceDocument,
    definitions: list[Definition],
    usages: list[Usage],
    common_terms: Iterable[str] | None = None,
) -> list[Finding]:
    """Return one stable finding for each deterministic DEF-001 through DEF-005 fact."""
    common = _common_terms(common_terms)
    by_term: dict[str, list[Definition]] = defaultdict(list)
    for definition in definitions:
        by_term[definition.normalized_term].append(definition)
    findings: list[Finding] = []

    # DEF-001: collapse repeated candidate appearances into one lawyer-facing
    # fact, but retain every occurrence as evidence. The first source spelling
    # remains the stable display spelling and primary location.
    undefined: dict[str, list[Usage]] = defaultdict(list)
    for candidate in _candidate_usages(source, definitions, common):
        if candidate.normalized_term not in by_term:
            undefined[candidate.normalized_term].append(candidate)
    for normalized, candidates in undefined.items():
        first_candidate = candidates[0]
        findings.append(
            _finding(
                source,
                "DEF-001",
                "medium",
                f"'{first_candidate.observed_form}' is used but not defined.",
                normalized,
                tuple(candidate.location for candidate in candidates),
            )
        )

    for normalized, group in sorted(by_term.items()):
        ordered = sorted(
            group,
            key=lambda item: (
                item.location.block_order,
                item.location.char_start,
                item.id,
            ),
        )
        external = [
            usage
            for usage in usages
            if usage.normalized_term == normalized
            and not usage.is_definition_occurrence
        ]
        first = ordered[0]
        if not external:
            findings.append(
                _finding(
                    source,
                    "DEF-002",
                    "low",
                    f"'{first.term}' is defined but not used outside its defining span.",
                    normalized,
                    (first.location,),
                )
            )
        if len(ordered) > 1:
            findings.append(
                _finding(
                    source,
                    "DEF-003",
                    "medium",
                    f"'{first.term}' has multiple definitions.",
                    normalized,
                    tuple(item.location for item in ordered),
                )
            )
        # Aliases are allowed spellings, not case-insensitive equivalence
        # classes: ``service fee`` is a reportable variant of ``Service Fee``.
        allowed_forms = {first.term, *first.aliases}
        variants = [
            usage for usage in external if usage.observed_form not in allowed_forms
        ]
        if variants:
            findings.append(
                _finding(
                    source,
                    "DEF-004",
                    "low",
                    f"'{first.term}' is used as '{variants[0].observed_form}', which is not an allowed alias.",
                    normalized,
                    (first.location, *(variant.location for variant in variants)),
                )
            )
        before = [
            usage
            for usage in external
            if (usage.location.block_order, usage.location.char_start)
            < (first.location.block_order, first.location.char_start)
        ]
        if before:
            findings.append(
                _finding(
                    source,
                    "DEF-005",
                    "low",
                    f"'{first.term}' is used before its first definition.",
                    normalized,
                    (before[0].location, first.location),
                )
            )
    return sorted(
        findings,
        key=lambda item: (
            item.rule_id,
            item.normalized_term or "",
            item.evidence[0].block_order,
            item.evidence[0].char_start,
            item.id,
        ),
    )
