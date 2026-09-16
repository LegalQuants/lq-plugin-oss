# Agentic Mapping Protocol

Read this reference only when subagents or equivalent model workers are available for the mapping stage. It is `/conform`'s equivalent of `/definition-check`'s [agentic-review-protocol.md](../../definition-check/references/agentic-review-protocol.md); read that file for background on the shared discipline (bounded provenance-neutral packets, prefill-and-validate worker responses, supervisor-owned canonical state).

## Roles

- **Supervisor** owns the private mapping between opaque review IDs and deterministic provenance from both ledgers, the canonical mapping record, and the escalation decision. Workers never mutate shared facts concurrently.
- **Mapping workers** independently adjudicate every queued source concept (conform-selected-text mode) or every queued core-document usage (precedent-leakage mode) from a neutral, provenance-blind packet and submit one `decision` row per queued item.
- **Retriever** executes only the bounded context-request actions permitted by the current capability profile, mirroring `/definition-check`'s `context_query.py` pattern.

If subagents are unavailable, one model may perform the same roles sequentially. Record that execution shape in the run's `methods_run`/`methods_not_run`-equivalent limitations; do not claim independent review.

## Stage barrier

There is exactly one model stage: `mapping`. Unlike `/definition-check`'s discovery-then-semantic-then-occurrence-then-reference pipeline, `/conform` does not run its own discovery pass over free text — the queue is built from the deterministic normalization artifact (`definition-normalization-1.0.0`), which is itself built from each document's already-reconciled `/definition-check` ledger (`definitions`, `term_variants`, `usages`). Discovery work belongs to `/definition-check`, and mechanical term-to-variable resolution belongs to the normalization pass; a stale or incomplete discovery pass is exactly what the ledger preflight hard-stops on, and ledger/document drift is what normalization fails closed on.

1. Build the complete-queue for the current mode (see below) from the two validated ledgers.
2. Freeze that queue and its count before dispatching any mapping worker.
3. Review the frozen queue in parallel batches or one complete pass, using all currently available parallel-worker capacity: dispatch one worker per ready packet up to the host's available worker limit, then refill freed slots until the queue is empty.
4. Reconcile responses into canonical mapping records.
5. Run every mapping record through `scripts/conform/escalation.py` to fix its escalation requirement and reason.
6. Finalize `conform.json`, `conform.html`, and the clean text once.

A candidate found after the freeze invalidates that queue and requires one deliberate rebuild, exactly as `/definition-check` requires for its semantic queue. Dependency misses should be rare: the normalization lookup table's `depends_on` lists deterministically expose every concept a queued definition itself invokes, so the frozen queue should already contain the full dependency closure.

## Complete-queue construction

**Conform-selected-text mode:** the queue is every source-document concept the selected text actually invokes — every variable appearing in the *normalized* selected text, plus the transitive `depends_on` closure of those variables from the lookup table, plus every `skipped_usages` entry whose location falls within the selected span (an unmapped variant or duplicate-defined term the normalization deliberately did not resolve). Do not sample; a clause that invokes five source concepts produces a five-item queue, not a queue limited to the concepts a first pass happened to notice.

**Precedent-leakage mode:** the queue is every core-document usage whose term or context plausibly originates in the named source document's vocabulary. Build it from the normalization artifact: the cross-document report's same-name definitions and variant-form collisions are deterministic candidates, supplemented by the core document's `skipped_usages`, cross-referenced against the source ledger's `definitions`. A core-document usage that is fully covered by the core document's own current definitions is not queued; `/conform` is checking for leakage, not re-litigating `/definition-check`'s findings for the core document alone.

## Compact mapping packet

Each queued item gets an opaque review ID, kept private, with a deterministic run-local numeric ordinal. The worker receives only:

1. the numeric item ordinal;
2. the source concept's term, definition text, and bounded surrounding context (conform-selected-text mode), or the core-document usage's term and bounded surrounding context (precedent-leakage mode);
3. a numbered `context_pool` of candidate destination-document (or, in leakage mode, source-document) definitions and usages, each tagged only with its `document_role` (`source` or `core`) and a numeric ordinal — never the raw ledger, file path, or other provenance;
4. any additional bounded context retrieved for an ambiguous item; and
5. the compact stage instruction and the ten-value `mapping_type` decision legend.

Do **not** pass ledger-internal IDs, `stable_id` values, detector or reviewer provenance from the originating `/definition-check` run, confidence, severity, or a statement that a deterministic layer already reached a conclusion. Do not give a worker unrestricted access to the other document's full ledger; the `context_pool` is the only cross-document evidence a worker sees unless it makes a bounded context request that the supervisor fulfills, mirroring `/definition-check`'s `context_query.py` retrieval boundary. Workers isolated to one document's packet may request the other document's evidence only through that bounded path — never by receiving the second ledger wholesale.

## Response contract

A worker response conforms to `../references/conform-response-schema.json`: one row per queued item, `[item_ordinal, decision, evidence, reviewer_note]`. `decision` is exactly one of the `mapping_type` enum values from `conform-mapping-schema.json`. `evidence` cites only `context_pool` ordinals already supplied to that worker (or ordinals returned by a fulfilled context request); a worker may not invent an ordinal or cite raw text outside its packet. Use `needs_review` when more context might resolve the mapping and `insufficient_evidence` when the retrieval budget is exhausted or the ledgers simply do not contain enough evidence.

## Escalation-decision rules (restated)

Every mapping record — regardless of who or what proposed it — passes through `scripts/conform/escalation.py` before it reaches `conform.json`:

- `false_friend`, `one_to_many`, `many_to_one`, `no_mapping`, `needs_review`, `insufficient_evidence`, `narrower_scope`, `broader_scope`, and `leakage_flag` always require escalation.
- `equivalent` requires escalation only when supporting evidence is incomplete; a fully evidenced `equivalent` mapping does not.

This is a pure function over `(mapping_type, evidence_complete)`; it never depends on worker-reported confidence, and no worker or supervisor step may bypass it. "Safe to propose" never means silent application — an unescalated `equivalent` mapping is still only a proposal in the redline, never an applied edit.

## Worker isolation

Workers never see the other document's raw ledger. Everything a worker can cite comes from:

1. its own packet's bounded excerpt of the concept under review, and
2. its packet's `context_pool`, populated by the supervisor from both ledgers' already-reconciled `definitions`/`term_variants`/`usages`, and
3. any bounded context request fulfilled through the retriever, conforming to `/definition-check`'s `context-request-schema.json`/`context-result-schema.json` request/result shape, scoped to `/conform`'s two-document case (a request must name which document, `source` or `core`, it targets).

The supervisor retains deterministic provenance, ledger-internal IDs, and location data outside the worker prompt and reconnects them only after receiving the structured decision.

## Finalization

The supervisor must:

1. Resolve or explicitly defer every item in the complete queue; a complete run has exactly one decision per queued item.
2. Materialize one `conform-mapping-1.0.0` record per queued item (or, for `one_to_many`, one record with multiple `destination_terms`; for `many_to_one`, one record per source concept that shares a destination term, cross-referenced in each record's `reviewer_note`).
3. Run every materialized record through `escalation.py` and populate `escalation.required`/`escalation.reason`.
4. Build the top-level `escalations` array as the denormalized list of every mapping whose `escalation.required` is true.
5. Render `conform.html` and the clean text only after every queued item has a decision and every mapping has passed through escalation.
6. Delete the marked temporary workspace after successful finalization unless the lawyer explicitly asked for retained debugging artifacts.

Treat the packaged validator as the validation authority, never a worker's own claim that its JSON is valid.
