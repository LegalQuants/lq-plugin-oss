"""Bounded, deterministic context retrieval for agentic definition discovery.

This module deliberately returns evidence, not a document dump.  Runtime
orchestration owns agent calls and may decide how to handle ``escalate_review``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from .models import (
    Block,
    ContextRequest,
    EvidenceItem,
    Location,
    SourceDocument,
    stable_id,
)


@dataclass(frozen=True)
class RetrievalBudget:
    """Per-investigation limits; callers may share one instance's mutable state."""

    max_requests: int = 8
    max_hops: int = 3
    max_results: int = 20
    max_characters: int = 12_000


@dataclass
class RetrievalState:
    budget: RetrievalBudget = RetrievalBudget()
    requests_used: int = 0
    characters_used: int = 0


@dataclass(frozen=True)
class RetrievalResult:
    request: ContextRequest
    evidence: tuple[EvidenceItem, ...]
    note: str | None = None


def _normalise(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _is_heading(block: Block) -> bool:
    text = block.text.strip()
    if block.kind == "heading":
        return True
    if re.match(r"^(?:article|section)\s+(?:[ivxlcdm]+|\d+(?:\.\d+)*)\b", text, re.I):
        return True
    if re.match(r"^\d+(?:\.\d+)*[.)]?\s+\S", text):
        return True
    letters = "".join(char for char in text if char.isalpha())
    return bool(
        letters
        and len(text) <= 90
        and len(text.split()) <= 12
        and letters == letters.upper()
    )


def _budgeted_request(
    request: ContextRequest, state: RetrievalState
) -> ContextRequest | None:
    if (
        request.hop > state.budget.max_hops
        or state.requests_used >= state.budget.max_requests
    ):
        return replace(request, status="budget_exhausted", result_evidence_ids=())
    state.requests_used += 1
    return None


def _complete(
    request: ContextRequest, evidence: Iterable[EvidenceItem], note: str | None = None
) -> RetrievalResult:
    items = tuple(evidence)
    status = "fulfilled" if items else "failed"
    return RetrievalResult(
        replace(
            request, status=status, result_evidence_ids=tuple(item.id for item in items)
        ),
        items,
        note,
    )


def _evidence(
    source: SourceDocument,
    block: Block,
    start: int,
    end: int,
    excerpt: str,
    method: str,
    *,
    location_start: int | None = None,
    location_end: int | None = None,
) -> EvidenceItem:
    """Create stable evidence; location may identify narrower material than its excerpt."""
    location = block.location(
        start if location_start is None else location_start,
        end if location_end is None else location_end,
    )
    return EvidenceItem(
        id=stable_id(
            "evidence",
            source.document_id,
            method,
            location.part,
            location.block_id,
            location.char_start,
            location.char_end,
            excerpt,
        ),
        location=location,
        excerpt=excerpt,
        stance="context",
        method=method,
    )


def _trim(text: str, start: int, end: int, limit: int) -> tuple[int, int, str]:
    if end - start <= limit:
        return start, end, text[start:end]
    # Keep a balanced window around the material location.
    left = max(start, ((start + end - limit) // 2))
    right = left + limit
    return left, right, text[left:right]


def _accept(
    request: ContextRequest, state: RetrievalState, candidates: list[EvidenceItem]
) -> RetrievalResult:
    limit = min(request.max_results, state.budget.max_results)
    chosen: list[EvidenceItem] = []
    for item in candidates[:limit]:
        if state.characters_used + len(item.excerpt) > state.budget.max_characters:
            return RetrievalResult(
                replace(
                    request,
                    status="budget_exhausted",
                    result_evidence_ids=tuple(x.id for x in chosen),
                ),
                tuple(chosen),
                "character budget exhausted",
            )
        chosen.append(item)
        state.characters_used += len(item.excerpt)
    return _complete(
        request,
        chosen,
        "results narrowed to retrieval budget" if len(candidates) > limit else None,
    )


def expand_location(
    source: SourceDocument,
    request: ContextRequest,
    location: Location,
    state: RetrievalState,
    *,
    adjacent_blocks: int = 1,
    excerpt_limit: int = 1_200,
) -> RetrievalResult:
    exhausted = _budgeted_request(request, state)
    if exhausted:
        return RetrievalResult(exhausted, (), "request or hop budget exhausted")
    blocks = sorted(source.blocks, key=lambda block: block.order)
    index = next(
        (i for i, block in enumerate(blocks) if block.id == location.block_id), None
    )
    if index is None:
        return _complete(request, (), "location block is not in source")
    candidates = []
    for block in blocks[max(0, index - adjacent_blocks) : index + adjacent_blocks + 1]:
        start, end, excerpt = _trim(block.text, 0, len(block.text), excerpt_limit)
        candidates.append(
            _evidence(source, block, start, end, excerpt, "context.expand_location")
        )
    return _accept(request, state, candidates)


def search_term(
    source: SourceDocument,
    request: ContextRequest,
    state: RetrievalState,
    *,
    excerpt_limit: int = 1_200,
) -> RetrievalResult:
    exhausted = _budgeted_request(request, state)
    if exhausted:
        return RetrievalResult(exhausted, (), "request or hop budget exhausted")
    needle = _normalise(request.query)
    if not needle:
        return _complete(request, (), "empty search query")
    pattern = _term_pattern(needle)
    candidates: list[EvidenceItem] = []
    for block in sorted(source.blocks, key=lambda item: item.order):
        match = pattern.search(block.text)
        if not match:
            continue
        start = max(
            0, match.start() - (excerpt_limit - (match.end() - match.start())) // 2
        )
        end = min(len(block.text), start + excerpt_limit)
        start = max(0, end - excerpt_limit)
        candidates.append(
            _evidence(
                source, block, start, end, block.text[start:end], "context.search_term"
            )
        )
    return _accept(request, state, candidates)


def _term_pattern(normalised_query: str) -> re.Pattern[str]:
    """Match normalized query words across whitespace and punctuation in source."""
    tokens = normalised_query.split()
    return re.compile(
        r"(?<![A-Za-z0-9])"
        + r"[^A-Za-z0-9]+".join(map(re.escape, tokens))
        + r"(?![A-Za-z0-9])",
        re.I,
    )


def retrieve_occurrences(
    source: SourceDocument, request: ContextRequest, state: RetrievalState
) -> RetrievalResult:
    """Return every bounded match, including multiple matches within one block."""
    exhausted = _budgeted_request(request, state)
    if exhausted:
        return RetrievalResult(exhausted, (), "request or hop budget exhausted")
    needle = _normalise(request.query)
    if not needle:
        return _complete(request, (), "empty search query")
    candidates: list[EvidenceItem] = []
    pattern = _term_pattern(needle)
    for block in sorted(source.blocks, key=lambda item: item.order):
        for match in pattern.finditer(block.text):
            start = max(0, match.start() - 400)
            end = min(len(block.text), max(match.end() + 400, start + 1))
            candidates.append(
                _evidence(
                    source,
                    block,
                    start,
                    end,
                    block.text[start:end],
                    "context.retrieve_occurrences",
                    location_start=match.start(),
                    location_end=match.end(),
                )
            )
    return _accept(request, state, candidates)


def retrieve_definitions_section(
    source: SourceDocument,
    request: ContextRequest,
    state: RetrievalState,
    *,
    max_blocks: int = 12,
) -> RetrievalResult:
    exhausted = _budgeted_request(request, state)
    if exhausted:
        return RetrievalResult(exhausted, (), "request or hop budget exhausted")
    blocks = sorted(source.blocks, key=lambda block: block.order)
    start = next(
        (
            i
            for i, block in enumerate(blocks)
            if _is_heading(block) and "definition" in _normalise(block.text)
        ),
        None,
    )
    if start is None:
        return _complete(request, (), "definitions section was not found")
    selected = []
    for block in blocks[start : start + max_blocks]:
        if block is not blocks[start] and _is_heading(block):
            break
        text_start, text_end, excerpt = _trim(block.text, 0, len(block.text), 1_200)
        selected.append(
            _evidence(
                source,
                block,
                text_start,
                text_end,
                excerpt,
                "context.retrieve_definitions_section",
            )
        )
    return _accept(request, state, selected)


def retrieve_reference(
    source: SourceDocument,
    request: ContextRequest,
    state: RetrievalState,
    *,
    following_blocks: int = 2,
) -> RetrievalResult:
    exhausted = _budgeted_request(request, state)
    if exhausted:
        return RetrievalResult(exhausted, (), "request or hop budget exhausted")
    target = _normalise(request.query)
    target_forms = [target]
    stripped_target = re.sub(r"^(?:section|article)\s+", "", target)
    if stripped_target != target:
        target_forms.append(stripped_target)
    blocks = sorted(source.blocks, key=lambda block: block.order)
    index = next(
        (
            i
            for i, block in enumerate(blocks)
            if _is_heading(block)
            and any(_normalise(block.text).startswith(form) for form in target_forms)
        ),
        None,
    )
    if index is None:
        return _complete(request, (), "reference heading was not found")
    selected = []
    for block in blocks[index : index + following_blocks + 1]:
        if block is not blocks[index] and _is_heading(block):
            break
        start, end, excerpt = _trim(block.text, 0, len(block.text), 1_200)
        selected.append(
            _evidence(source, block, start, end, excerpt, "context.retrieve_reference")
        )
    return _accept(request, state, selected)


def retrieve(
    source: SourceDocument,
    request: ContextRequest,
    state: RetrievalState,
    *,
    location: Location | None = None,
) -> RetrievalResult:
    """Dispatch a bounded request.  Escalation is intentionally left pending."""
    if request.request_type == "escalate_review":
        return RetrievalResult(
            request, (), "runtime orchestration must assign the review worker"
        )
    if request.request_type == "expand_location":
        if location is None:
            return _complete(request, (), "expand_location requires a source location")
        return expand_location(source, request, location, state)
    if request.request_type == "search_term":
        return search_term(source, request, state)
    if request.request_type == "retrieve_occurrences":
        return retrieve_occurrences(source, request, state)
    if request.request_type == "retrieve_definitions_section":
        return retrieve_definitions_section(source, request, state)
    if request.request_type == "retrieve_reference":
        return retrieve_reference(source, request, state)
    return _complete(request, (), "unsupported retrieval request")
