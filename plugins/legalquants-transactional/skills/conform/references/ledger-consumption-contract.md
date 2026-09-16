# Ledger Consumption Contract

`/conform` is a read-only consumer of two `/definition-check` ledgers, schema `0.14.0`. It never writes to a `definition-check.json` file. The full ledger contract, its record invariants, and its schema-version history are canonical at [../../definition-check/references/ledger-contract.md](../../definition-check/references/ledger-contract.md); this file states only which fields `/conform` reads and the hard-stop rule that gates reading them at all.

## Hard-stop rule

Per `ledger-contract.md`: "`/conform` may consume only a supported schema version whose source hash is current." `/conform` never reads past that gate. `scripts/conform_preflight.py` enforces it deterministically before any mapping work begins, for both the source ledger and the core ledger independently. See `SKILL.md`, "Ledger preflight — hard stop," for the lawyer-facing explanation of each `stop_reason`.

## Fields `/conform` reads

Once preflight succeeds for a ledger, `/conform` reads:

- `schema_version` — re-checked defensively even after preflight; any consumer that reads past preflight still fails closed on an unsupported value.
- `source` — `document_id`, `name`, `sha256`, `coverage`, `warnings`. `sha256` is the same content hash preflight already validated; `coverage` and `warnings` inform the boundary statement given to the lawyer (for example, if the source ledger's coverage excludes tables, a table-only clause cannot be conformed from it).
- `run_status` — must be a completed state (`completed` or `completed_reduced_assurance`); a reduced-assurance run is usable but its `methods_not_run` entries are surfaced to the lawyer as a coverage limitation on the mapping evidence.
- `methods_run` / `methods_not_run` — read to state which review methods actually ran, so a mapping's evidence is never presented as more complete than the underlying ledger supports.
- `definitions` — the canonical accepted definitions for each document, including `term`, `normalized_term`, `definition_text`, `location`, `aliases`, `scope`, and `reference_target`. This is the primary evidence for whether two differently named terms cover the same conceptual scope.
- `term_variants` — first-class non-canonical forms mapped toward a canonical term, with mapped/rejected/shadowed/unresolved instance IDs retained separately. Consumed deterministically through the normalization artifact (below), which replaces each mapped variant with its variable and carries the rest as `skipped_usages`.
- `usages` — individual term instances and their locations, consumed deterministically through the normalization artifact, which rewrites every accepted usage into its placeholder variable and validates every span against the current document text.

## The normalization artifact

After preflight, `/conform` also consumes the `definition-normalization-1.0.0` artifact produced by `/definition-check`'s `normalize_terms.py` (run over both documents together; see `SKILL.md`, "Deterministic term normalization — always run"). From it `/conform` reads:

- `documents[].variables` — the variable lookup table: `variable`, `term`, `normalized_term`, `definition_id`, `definition_text`, `normalized_definition_text`, `meaning_source`, `depends_on`, `aliases`, `location`, and `replaced_usage_ids`. This is the queue's source of invoked concepts and their dependency closure.
- `documents[].blocks` — per-block `text` and `normalized_text`; the normalized selected text is read from here.
- `documents[].skipped_usages` — usages normalization deliberately left untouched (`variant_*` statuses, `multiple_definitions`); each becomes a mapping-queue item rather than being silently dropped.
- `cross_document` — `same_name_definitions` and `cross_doc_variant_collisions`: deterministic flags that feed the queue (especially in precedent-leakage mode). Equivalence decisions about them remain agentic.
- `findings` — deterministic and semantic findings, read for any existing DEF-series issue that bears on whether a term is reliably defined before it is used as mapping evidence.
- `semantic_review` / `occurrence_review` / `reference_review` — each summary's `status`, `queue_count`, `decided_count`, and `unresolved_count`. Preflight requires `status == "complete"` for all three before `/conform` runs; `/conform` also reads `unresolved_count` afterward so any residual `needs_review`/`insufficient_evidence` items from the underlying `/definition-check` run are carried into `/conform`'s own escalation record rather than silently treated as resolved.

## Fields `/conform` does not read

`/conform` does not read `lexical_observations`, `candidate_proposals`, `context_requests`, `review_traces`, `term_candidates`, `semantic_adjudications`, `occurrence_candidates`, `occurrence_collisions`, `occurrence_adjudications`, `reference_candidates`, or `reference_adjudications`. Those are `/definition-check`'s internal provenance and adjudication trail; `/conform` trusts the reconciled `definitions`/`term_variants`/`usages`/`findings` output of a complete review rather than re-adjudicating raw candidates itself. An authorized developer audit of `/conform`'s own mapping provenance is a separate, explicitly authorized path (see `conform.md`), not an implicit read of `/definition-check`'s internal records.

## Matter snapshots

Migration note (2026-09-06): the pin moved from `0.13.0` to `0.14.0` with the proper-name review changes; every field `/conform` reads (`definitions`, `term_variants`, `usages`) is unchanged in `0.14.0`. Ledgers emitted before the bump fail `stale_schema_version` and must be regenerated.

`/conform` v1 consumes single-document `0.14.0` ledgers only. It does not read a `matter.definition-check` snapshot. Multi-document normalization likewise consumes several single-document `0.14.0` ledgers as paired inputs; multi-version matter integration is out of scope for this pass. See `SKILL.md` boundaries.
