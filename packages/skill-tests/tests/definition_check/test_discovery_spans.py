"""Synthetic regressions for discovery offsets that split source tokens."""

from dataclasses import asdict, replace

import pytest
from definition_check.analyze import FinalizedTerm, build_finalized_usages
from definition_check.mention_coverage import audit_mentions
from definition_check.models import Block, CandidateProposal, SourceDocument
from definition_check.semantic_review import build_term_candidates


def proposal(block, start):
    return CandidateProposal(
        "p1",
        "c1",
        "ZX",
        "zx",
        block.location(start, start + 2),
        "candidate",
        "discovery_worker",
        1,
        "Possible label.",
    )


@pytest.mark.parametrize("text", ["aZX", "ZXa", "1ZX", "ZX2", "_ZX", "ZX_", "éZX"])
def test_embedded_discovery_span_is_not_a_candidate(text):
    block = Block("b1", "document", "paragraph", 0, text)
    source = SourceDocument("synthetic", "synthetic.txt", None, [block])
    assert not build_term_candidates(
        source, [], [], proposals=[proposal(block, text.index("ZX"))]
    )


def test_rescan_recovers_real_occurrences_and_audit_still_detects_missing_usage():
    text = "Supply aZX format. ZX applies. (ZX) continues."
    block = Block("b1", "document", "paragraph", 0, text)
    source = SourceDocument("synthetic", "synthetic.txt", None, [block])
    bad = proposal(block, text.index("ZX"))
    candidates = build_term_candidates(source, [], [], proposals=[bad])
    assert len(candidates) == 1
    candidate = candidates[0]
    assert [loc.char_start for loc in candidate.locations] == [
        text.index("ZX applies"),
        text.index("ZX)"),
    ]
    usages = build_finalized_usages(
        source, [FinalizedTerm("ZX", "zx", (), (), (), "Synthetic meaning")]
    )
    data = {
        "source": {"sha256": None},
        "term_candidates": [asdict(candidate)],
        "semantic_adjudications": [
            {
                "review_id": candidate.review_id,
                "decision": "confirmed_defined",
            }
        ],
        "occurrence_adjudications": [
            {"usage_id": usage.id, "decision": "defined_term_use"} for usage in usages
        ],
        "definitions": [],
        "findings": [],
        "usages": [asdict(usage) for usage in usages],
    }
    assert audit_mentions(data, [asdict(block)])["gap_count"] == 0
    data["usages"] = data["usages"][:-1]
    assert audit_mentions(data, [asdict(block)])["gap_count"] == 1


def test_invalid_proposal_does_not_contaminate_existing_group():
    text = "ZX applies; aZX does not."
    block = Block("b1", "document", "paragraph", 0, text)
    source = SourceDocument("synthetic", "synthetic.txt", None, [block])
    good = proposal(block, 0)
    bad = replace(proposal(block, text.index("aZX") + 1), id="p2")
    candidates = build_term_candidates(source, [], [], proposals=[good, bad])
    assert candidates[0].locations == (block.location(0, 2),)


def test_valid_proposal_still_merges_into_existing_group():
    block = Block("b1", "document", "paragraph", 0, "ZX applies. (ZX) continues.")
    source = SourceDocument("synthetic", "synthetic.txt", None, [block])
    first = proposal(block, 0)
    second = replace(proposal(block, block.text.rindex("ZX")), id="p2")
    candidate = build_term_candidates(source, [], [], proposals=[first, second])[0]
    assert candidate.proposal_ids == ("p1", "p2")
    assert len(candidate.locations) == 2


def test_rescan_preserves_plural_and_possessive_contexts():
    block = Block("b1", "document", "paragraph", 0, "Fees apply. A Fee's basis.")
    source = SourceDocument("synthetic", "synthetic.txt", None, [block])
    discovered = replace(
        proposal(block, 0),
        term="Fees",
        normalized_term="fees",
        location=block.location(0, 4),
    )
    candidate = build_term_candidates(source, [], [], proposals=[discovered])[0]
    assert [
        block.text[loc.char_start : loc.char_end] for loc in candidate.locations
    ] == [
        "Fees",
        "Fee's",
    ]
