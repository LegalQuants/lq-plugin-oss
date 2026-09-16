Review every numbered core-document usage and decide whether it is a genuine core-document concept or an unadapted carryover from the named source document's vocabulary, using only the context supplied in this packet's `context_pool`. Write only the JSON object described by response_schema. Start from response_template, preserve its packet number, row order, item ordinals, and row count, and replace every null decision. Do not add keys or prose. A row is `[item, decision, evidence, reviewer_note]`.

This is precedent-leakage mode: the queued item is a core-document usage, not a source-document concept. The question is whether the core document's own current definitions already cover it, or whether its wording and context instead trace back to the named source document.

Decision values:

- `equivalent`: the core document's own current definitions fully cover this usage; it is not leakage. Use this to clear a usage, not to describe a source-to-core mapping.
- `leakage_flag`: this usage's wording, scope, or context plausibly originates in the named source document's vocabulary and is not covered by anything the core document itself currently defines. This is the primary finding of this mode.
- `false_friend`: the usage's label coincides with a source-document term, but on inspection the core document is using it as its own distinct, self-contained concept. Do not flag a usage as leakage merely because a similarly spelled term also happens to appear in the source document; that coincidence alone is not evidence of leakage.
- `narrower_scope` / `broader_scope`: the usage tracks the source concept but the core document's own surrounding language has already narrowed or broadened it from the source scope, which is itself worth flagging to the lawyer rather than silently accepted or silently flagged as clean.
- `needs_review`: more context, which this packet does not contain, might resolve whether this is leakage.
- `insufficient_evidence`: the supplied ledgers do not contain enough evidence to support a reliable decision at all.

`one_to_many`, `many_to_one`, and `no_mapping` are not valid decisions in this mode; do not use them.

`evidence` cites `context_pool` ordinals exactly as shown in the packet. A `leakage_flag` decision requires at least one `supports` citation from the `source` document showing the concept it plausibly carried over from, and, where available, a `context` citation showing the core document's own definitions do not cover it. Give a short, concrete reviewer_note naming the specific source concept a flagged usage appears to carry.

The supervisor validates every citation and reconciles opaque IDs; do not return ledger IDs, file paths, confidence, severity, or hidden reasoning.
