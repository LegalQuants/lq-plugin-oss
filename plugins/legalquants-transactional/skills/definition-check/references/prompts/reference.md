# Definition-reference review

Review every supplied reference item using only the source context in this packet. Write only the JSON object described by response_schema. Start from response_template, preserve its packet number, row order, item ordinals, and row count, and replace every null decision. Do not add keys or prose. Each row is `[item, decision, evidence_contexts, note, review_reason]`; use only the evidence contexts allowed by item_constraints.

Decision codes:

1. `resolved`: the supplied document scope resolves the target to source language that can carry the referenced meaning.
2. `broken`: the target is intended to be internal to the supplied document scope, but the supplied scope cannot resolve it.
3. `out_of_scope`: the target is external or belongs to an omitted companion document, schedule, exhibit, or other material outside the supplied scope. External or omitted material is not a broken internal reference.
4. `needs_review`: the supplied evidence is ambiguous.
5. `insufficient_evidence`: the supplied evidence cannot support a disposition.

Use the smallest sufficient set of context ordinals exactly as shown in the packet in `evidence_contexts`. Do not cite incidental matches or every available context. Do not infer that an incidental prose mention resolves a heading, section, schedule, exhibit, or incorporated definition. The supervisor validates the original source spans and restores opaque IDs; do not return IDs, locations, hashes, confidence, or hidden reasoning.

review_reason MUST be 0 for resolved, broken, and out_of_scope decisions. For unresolved decisions use 1 missing_external_evidence, 4 incomplete_source_context, or 5 ambiguous_reference. Prefer operative evidence over unexplained headings, titles, or proper-name fragments.
