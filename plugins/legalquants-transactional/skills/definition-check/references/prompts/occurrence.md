Review every occurrence against its canonical term, definition, aliases, exact context, and overlap set. Fill `response_template`; return only matching JSON. Preserve packet, row order, ordinals, and row count. Rows are `[item, decision, note, review_reason]`; decision MUST be an allowed integer.

Decide contextual identity, not spelling alone:

- `defined_term_use`: context invokes the accepted definition. Singular, plural, possessive, spacing, or case variation may still invoke it.
- `ordinary_language`: generic or descriptive prose does not invoke the definition.
- `proper_name_component`: match appears solely within a person, organization, product, place, or other named entity and does not invoke the definition.
- `inconsistent_capitalization`: context invokes the definition but changes canonical capitalization without an allowed presentation variant or alias. Singular/plural/possessive change alone is not enough. Ordinary capitalization of an all-caps label, all-caps heading/signature typography, and sentence-initial capitalization of a lowercase alias are permitted.
- `shadowed_by_overlapping_term`: a supplied exact-span or partial-overlap competitor is the contextual accepted term. Do not use merely because a longer ordinary phrase contains the match; the competitor must be an accepted term shown in the packet.
- `needs_review`: more context may resolve identity. `insufficient_evidence`: supplied source cannot support a reliable decision.

An exact term inside a longer document/section title or ordinary compound may be ordinary language. Wholly contained accepted-label matches were already removed. Multiple overlapping terms may be defined-term uses only when context invokes both.

Give a short note. `review_reason` MUST be 0 for resolved decisions; for unresolved use 2 ambiguous_term_identity, 3 uncertain_occurrence_identity, or 4 incomplete_source_context. Prefer operative evidence over headings, titles, and proper-name fragments.
