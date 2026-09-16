Render the lawyer-facing escalation reason for one already-decided mapping. This step never re-decides `mapping_type`; it turns a fixed, already-computed escalation requirement into a plain-language sentence a lawyer can act on. Write only the JSON object described by response_schema. Start from response_template, preserve its packet number, row order, item ordinals, and row count, and replace every null reason. Do not add keys or prose outside the reason field. A row is `[item, reason]`.

Whether escalation is required is never decided here and never by a worker: `scripts/conform/escalation.py` is the sole authority, applied deterministically after every mapping decision. This step only phrases the `reason` string for a mapping the escalation function has already marked `required: true`.

Escalation-decision rules (for context, not for you to apply):

- `false_friend`, `one_to_many`, `many_to_one`, `no_mapping`, `needs_review`, `insufficient_evidence`, `narrower_scope`, `broader_scope`, and `leakage_flag` always require escalation.
- `equivalent` requires escalation only when its supporting evidence is incomplete.

Write one concrete sentence naming what the lawyer needs to decide, not the internal mapping_type label. For example, prefer "The core document splits this source concept into two defined terms — confirm both are needed here" over "one_to_many mapping requires escalation." Never write a reason that could be read as clearance to proceed without lawyer review; every escalated mapping stays a proposal until the lawyer accepts, edits, or rejects it in the redline.
