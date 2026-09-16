Review every numbered item and decide how the source concept it identifies maps into the core document, using only the context supplied in this packet's `context_pool`. Write only the JSON object described by response_schema. Start from response_template, preserve its packet number, row order, item ordinals, and row count, and replace every null decision. Do not add keys or prose. A row is `[item, decision, evidence, reviewer_note]`.

Same names do not prove the same meaning. Different names can be the same concept. Decide from the definition text and usage context supplied, never from label similarity alone.

Source concepts reach you as placeholder variables (for example, `«A:T001»`) produced by a deterministic normalization pass over the source document: every exact or mapped-variant usage of a defined term has already been rewritten to its variable. The packet supplies each variable's definition text and bounded context. Treat the variable as an opaque label — decide the mapping from the supplied evidence, never from the variable's numbering or from any same-named term that may exist in the destination document.

Decision values:

- `equivalent`: a core-document expression covers the same conceptual scope as the source concept, with no limb, qualification, or exclusion added or lost.
- `narrower_scope`: the best core-document candidate covers less than the source concept did; some source scope would be silently dropped by a literal substitution.
- `broader_scope`: the best core-document candidate covers more than the source concept did; the substitution would silently sweep in scope the source clause never carried.
- `false_friend`: a core-document term with a similar or identical label denotes a materially different concept. Naming this is exactly the failure this review exists to catch; never resolve a false friend as equivalent because the label looks right.
- `one_to_many`: the source concept is best preserved by two or more core-document terms together. Cite every destination term in `evidence`; a one_to_many decision with only one cited destination is invalid.
- `many_to_one`: this source concept and at least one other queued source concept both belong under the same single core-document term. Say which other item(s) share the destination in `reviewer_note`.
- `no_mapping`: the core document has no expression, defined or undefined, that covers this concept at all.
- `leakage_flag`: (precedent-leakage mode only) this core-document usage appears to be an unadapted carryover of the named source document's vocabulary rather than a term the core document actually defines or means to use.
- `needs_review`: more context, which this packet does not contain, might resolve the mapping.
- `insufficient_evidence`: the supplied ledgers do not contain enough evidence to support a reliable decision at all.

`evidence` cites `context_pool` ordinals exactly as shown in the packet, tagged with the stance each one plays. Do not cite an ordinal that was not supplied. `equivalent`, `narrower_scope`, `broader_scope`, and `false_friend` each require at least one `supports` evidence citation from both `source` and `core`. `no_mapping` may cite `context` evidence explaining what was searched. Give a short, concrete reviewer_note — for example, name the specific limb of the source definition that a `narrower_scope` candidate drops, or the specific reason a `false_friend` candidate's label is misleading.

The supervisor validates every citation and reconciles opaque IDs; do not return ledger IDs, file paths, confidence, severity, or hidden reasoning.
