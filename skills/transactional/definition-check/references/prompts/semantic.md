Fill `response_template`; return matching JSON only. Preserve packet order. Contexts: `[local_context, source_key, match_start, match_end]`; equal table/row indexes mark sibling cells.

- `confirmed_defined`: source assigns a label: means, refers to, collective wording, a quoted parenthetical short form, or equivalent.
- `confirmed_alias`: source expressly links this and a confirmed canonical label to one antecedent. Similarity or spelling variants are not aliases.
- `confirmed_undefined`: contractual label without a local meaning, even if used once inside another definition or list. Independent reuse is not required. Also use when a word appears lowercase elsewhere but is capitalized mid-sentence without grammatical reason. Exclude sentence/list starts, headings, titles, and proper names. An outside-document definitions clause does not erase the local gap.
- `confirmed_external_reference`: operative incorporation language identifies a specifically named incorporated document not supplied. Informational.
- `rejected_not_a_term`: ordinary or descriptive language, generic phrase, fragment, unquoted explanatory parenthetical, or section or article title. Assess contractual function; location inside another definition or lack of repetition never justifies rejection.
- `rejected_proper_name`: expression identifies a person, organization, product, place, or other named entity. If assigned as a contractual label, use `confirmed_defined` or `confirmed_alias`.
- `needs_review`: more context may resolve. `insufficient_evidence`: source cannot support reliability.

Lack of a definition alone does not make ordinary wording undefined, except under the capitalization rule above.

Parenthetical short forms are definitions, not aliases merely because they abbreviate a name. In `Acme, LLC ("Acme")`, classify `Acme` as `confirmed_defined`, with `Acme, LLC` as its exact meaning span. The referent need not itself be a defined term. Its proper-name status does not invalidate the assigned label.

Reserve `confirmed_alias` for multiple contractual labels expressly assigned to the same antecedent. In `the supplying entity ("Supplier" or "Vendor")`, classify `Supplier` as `confirmed_defined` with meaning `the supplying entity`, and `Vendor` as `confirmed_alias` pointing to `Supplier`. Prefer a substantive label over a pronoun; otherwise use source order for co-equal labels. `term_index` lists candidates, not confirmed definitions. An alias must identify another item that is confirmed as a definition; an unclassified candidate or rejected proper name is not a confirmed anchor. If the anchor is in this response, its decision must be `confirmed_defined`; anchors in other packets must pass stage-wide validation. If an alias anchor fails, reassess the source for a direct definition before rejecting the label. If the supplied evidence cannot resolve its identity, use an unresolved decision with the appropriate review reason.

For `confirmed_defined`, `definition_spans` MUST contain each supplied exact meaning span as zero-based `[context, start, end]` triples. Include qualifications/exclusions; exclude label, quotes, and linking words. Use whole words; exclude unrelated language. Other decisions MUST use null. `canonical_item` is only for `confirmed_alias` and MUST identify a confirmed_defined term_index ordinal; otherwise null.

Rows are `[item, decision, evidence_contexts, definition_spans, note, canonical_item, review_reason]`. `review_reason` MUST be 0 unless unresolved: 1 missing_external_evidence, 2 ambiguous_term_identity, 3 uncertain_occurrence_identity, 4 incomplete_source_context, 5 ambiguous_reference. Note briefly. Prefer operative evidence over headings/titles/proper-name fragments.
