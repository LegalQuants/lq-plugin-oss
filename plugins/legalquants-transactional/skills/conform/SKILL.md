---
name: conform
description: Adapt a selected clause from a source or precedent document into a core document's own vocabulary, or check a core document for leftover source-document vocabulary, using current /definition-check ledgers for both documents. Use when a lawyer wants to reuse precedent language across documents with different defined-term vocabularies, or wants to check whether precedent language leaked into a core document unchanged.
compatibility: Requires local command execution and Python 3.12 or newer. Uses only the Python standard library and requires no network access.
metadata:
  legalquants.python-requires: ">=3.12"
  legalquants.python-dependencies: "stdlib-only"
---

# Conform

Adapt a source clause's evidenced conceptual scope into a core document's own vocabulary. Same names do not prove the same meaning; different names can be the same concept. `/conform` reads two current `/definition-check` ledgers, infers mappings from the current documents, and never silently applies anything.

## Speak to the lawyer, not the process

Assume the user is a non-technical lawyer unless they ask for implementation details. In chat, explain the legal comparison and its practical result, not the software machinery used to produce it.

- Keep progress updates brief, calm, and useful. Appropriate examples include: "I'm comparing how each concept is used in both documents," "I've confirmed both ledgers are current and am mapping the selected clause into the core document's terms," and "The mapping is complete. Here is what needs your decision." Use a progress statement only when it is true.
- Progress updates should ordinarily contain no numbers. Do not report running totals, counts of candidates, mappings, packets, workers, stages, retries, or remaining items; do not expose numbered internal labels, IDs, versions, timings, percentages, or provisional counts before the run is complete. Say "I'm working through the remaining concepts" rather than a processing count.
- Use numbers only when they help the lawyer understand or act on the legal result. Clause references, defined-term counts material to a decision, and a concise final escalation count may be useful; internal processing metrics are not.
- Do not narrate tool discovery, command execution, file paths, deterministic or agentic stages, workers or subagents, queues, packets, manifests, models, concurrency, schemas, or similar implementation details.
- Describe what is being compared by its legal purpose. For example, say "I'm checking whether the core document already has a concept that covers this" rather than naming an internal review stage.
- Surface process information only when the user needs it to make a decision, take an action, understand a material coverage limit, or assess confidentiality, cost, or risk. State the practical effect first and give the next step in plain language.
- If the run cannot be completed, say what was not completed, why that matters, and what the user can do next. Do not show raw errors or technical diagnostics unless the user asks for them.
- Legal findings may use precise transactional-law terminology. Avoid software terminology in ordinary updates and handoffs.

## State the boundary before running

Before execution and in the completion handoff, state in plain language which documents are in scope: "I compared the selected clause against the core document using each document's current defined-term review. Only the document body and tables were checked; notes, footnotes, headers, comments, and tracked changes were excluded, matching the scope of each `/definition-check` review." Do not replace it with technical parser language.

## Confirm the core document

Before doing anything else, confirm in plain language which document is the core document (the one being drafted or finalized) and which is the source or precedent document (the one contributing language). `/conform` never infers this from file order, naming, or which document the lawyer pasted first. If the lawyer's selection is ambiguous, ask.

In conform-selected-text mode, also confirm the exact selected source text. In precedent-leakage mode, confirm which source or precedent document's vocabulary the core document should be checked against; a leakage check requires at least one named source document, never an unbounded search across every document the lawyer has ever touched.

## Ledger preflight — hard stop

`/conform` never runs against a missing, stale, mismatched, or incomplete `/definition-check` ledger. Run the packaged preflight before any mapping work:

```text
python <skill-dir>/scripts/conform_preflight.py --source-docx <source.docx> --source-ledger <source-definition-check.json> --core-docx <core.docx> --core-ledger <core-definition-check.json>
```

The preflight fails closed on any of the following, and each has a distinct `stop_reason`:

- **`missing_ledger`** — a ledger file is absent, unreadable, or not valid JSON. Tell the lawyer: "I don't have a current definition check for [document]. Please run `/definition-check` on it first."
- **`stale_schema_version`** — a ledger's `schema_version` is not exactly `0.14.0`. Tell the lawyer the review is out of date and needs to be regenerated with the current `/definition-check`.
- **`hash_mismatch`** — the document's current content hash does not match the hash recorded in its ledger, meaning the document changed since the last review. Tell the lawyer the document has changed since it was last checked and ask them to re-run `/definition-check` before conforming.
- **`incomplete_run`** — the ledger's `run_status` is not a completed state. Tell the lawyer the earlier review did not finish and needs to be re-run.
- **`incomplete_review`** — the ledger's semantic, occurrence, or reference review is not complete. Tell the lawyer the earlier review is only partly done and `/conform` cannot rely on it yet.

Never proceed on stale or partial evidence, and never re-derive missing coverage yourself in place of a fresh `/definition-check` run. A hard stop is normal, expected behavior, not a bug to work around. Report the specific stop reason and the specific next step; do not show the raw JSON or exit code unless the lawyer asks for it.

After the preflight succeeds, run deterministic term normalization over both documents before any mapping work (next section). After that, read `definitions`, `findings`, `run_status`, `methods_run`/`methods_not_run`, and the completion blocks from each ledger as needed for evidence and boundary statements. Read [references/ledger-consumption-contract.md](references/ledger-consumption-contract.md) for the exact fields consumed and why.

## Deterministic term normalization — always run

Whenever `/conform` brings text in from a precedent or source document, normalization runs automatically — it is not an optional step. After the preflight succeeds, run `/definition-check`'s normalization script against both documents, writing into the temporary run workspace:

```text
python <definition-check-skill-dir>/scripts/normalize_terms.py --doc <source.docx> --ledger <source-definition-check.json> --doc <core.docx> --ledger <core-definition-check.json> --out <temporary-work-directory>/normalization.json
```

The script is part of the `/definition-check` skill, which ships alongside `/conform` in the same plugin; the ledgers preflight just validated are its output, so it is always present when `/conform` can run. If it is genuinely absent, stop and tell the lawyer the installation is incomplete.

The script rewrites every accepted usage of a defined term into a placeholder variable (`«A:T001»`-style, document-qualified) and emits a versioned `definition-normalization-1.0.0` artifact: per-block normalized text for both documents, a lookup table mapping each variable to its definition, and a cross-document report flagging same-name definitions and variant-form collisions. This is deterministic: it performs no semantic judgment, and it fails closed on any drift between a ledger and its document.

What normalization settles and what it leaves to mapping:

- **Settled deterministically:** every exact or mapped-variant usage of a defined term is now a variable. The mapping queue is built from the *normalized* source text — the variables the selected text invokes — and each variable's `depends_on` list in the lookup table already exposes the concepts its definition depends on, so dependency expansion needs no separate pass.
- **Left to agentic mapping:** which core-document concept, if any, each variable maps to; false friends; narrower/broader scope; one-to-many and many-to-one mappings; every usage in `skipped_usages` (unmapped variants, duplicate-defined terms); and every entry in the cross-document report, where same-name terms are flagged for review, never auto-merged.

The script's distinct exit codes mirror the preflight's hard stops. A schema stop (exit 20) means a ledger is out of date; a source-binding stop (exit 21) means a document changed since its review; a span-integrity stop (exit 22) means the ledger and document disagree. In every case tell the lawyer the affected document needs a fresh `/definition-check` run, in plain language, without showing the raw exit code.

The normalization artifact is intermediate run data: it lives in the temporary run workspace and is deleted on completion with everything else there.

## Full-capability agentic mapping path

When subagents or equivalent model workers are available, read [references/agentic-mapping-protocol.md](references/agentic-mapping-protocol.md) before dispatching any mapping work. Build the complete mapping queue first:

- **Conform-selected-text mode:** every variable the *normalized* selected text invokes, plus every concept those variables depend on (each variable's `depends_on` list in the normalization lookup table), plus every usage the normalization left in `skipped_usages` within the selection.
- **Precedent-leakage mode:** every core-document concept that could plausibly be an unadapted carryover of the named source document's vocabulary — starting from the normalization artifact's cross-document report (same-name definitions, variant-form collisions) and the core document's own skipped usages.

Review the entire queue; do not sample it. Within a stage with multiple ready packets, dispatch one worker per ready packet up to the host's available worker capacity, then refill freed slots until the queue is empty, following the same parallel-dispatch discipline as `/definition-check`'s agentic review.

Create the mapping workspace, build packets, dispatch, and expand responses with the packaged scripts:

```text
python <skill-dir>/scripts/conform_packets.py workspace-create
python <skill-dir>/scripts/conform_packets.py build --stage mapping --work-dir <temporary-work-directory> --source-ledger <source-definition-check.json> --core-ledger <core-definition-check.json> --selected-text <selected-text.json>
python <skill-dir>/scripts/conform_packets.py render-dispatch --stage mapping --work-dir <temporary-work-directory> --packet <packet.json>
python <skill-dir>/scripts/conform_packets.py expand --stage mapping --work-dir <temporary-work-directory> --manifest <private-manifest.json> --output <agent-bundle.json>
```

`render-dispatch` prefills the response with that packet's exact template and embeds a packet-scoped validator. The worker edits the prefilled response, runs the validator, may correct one invalid response once, and must stop with the exact validation error after a second failure. Never redispatch or rebuild a completed stage to repair one invalid packet. Workers are provenance-neutral by default: they see only the bounded source-clause and core-document excerpts supplied in the packet, never the other document's raw ledger, unless a bounded context request is supplied through the same context-query pattern `/definition-check` uses. Read [references/prompts/dispatch.md](references/prompts/dispatch.md), [references/prompts/mapping.md](references/prompts/mapping.md), [references/prompts/leakage-scan.md](references/prompts/leakage-scan.md), and [references/prompts/escalation.md](references/prompts/escalation.md) for the exact instructions given to workers at each stage.

Model choice, reasoning level, concurrency, and agent identity remain supervisor-side. If subagents are unavailable, one model may perform the same roles sequentially; record that execution shape and do not claim independent review.

## Escalation decision rules

`/conform` decides dynamically which mappings require lawyer escalation and records why. The rule is fixed and implemented in `scripts/conform/escalation.py`:

- `false_friend`, `one_to_many`, `many_to_one`, `no_mapping`, `needs_review`, and `insufficient_evidence` always require escalation.
- `narrower_scope` and `broader_scope` always require escalation: the destination term does not cover the same conceptual scope as the source clause, which is itself a substantive drafting choice for the lawyer.
- `leakage_flag` (precedent-leakage mode) always requires escalation.
- `equivalent` requires escalation only when the supporting evidence is incomplete. A fully evidenced `equivalent` mapping does not require escalation.

"Safe to propose" never means silent application. Every mapping — escalated or not — is a proposal in the redline and mapping record for the lawyer to accept, edit, or reject. `/conform` never applies a mapping to the core document itself.

## Precedent-leakage mode

When the lawyer asks `/conform` to check a core document for leakage from a named source document's vocabulary, run the same preflight and ledger-consumption steps against both ledgers, then build the mapping queue from the core document's concepts instead of the source clause. Flag a core-document usage as a leakage candidate only when the current core-document ledger's own definitions do not already cover that usage and the usage's wording and context plausibly originate in the named source document. Never flag a usage merely because a similarly spelled term also appears in the source document; that is exactly the same-name trap this skill exists to avoid. Every leakage candidate is `leakage_flag` and always escalates.

## Outputs

- `conform.html` is the primary lawyer-facing deliverable: the HTML redline of the selected clause (or, in leakage mode, the flagged core-document passages) with proposed conforming language, generated only after mapping and escalation review are complete.
- Clean, copy-pasteable text of the fully conformed clause is provided alongside the redline in chat and as a plain-text section of the handoff, generated independently of the HTML rather than derived by stripping its tags.
- `conform.json` is the canonical machine-readable mapping record, conforming to [references/conform-run-schema.json](references/conform-run-schema.json) and [references/conform-mapping-schema.json](references/conform-mapping-schema.json). An authorized agent may use its structured mappings to answer questions about the run; do not ask an ordinary user to open it.
- `conform.md` is a developer diagnostic fallback, not a lawyer-facing report.
- Keep the successful completion handoff concise: state the boundary note above, summarize the clean text and any escalations in plain language, and end by asking whether the lawyer would like to walk through the mapping evidence.
- If the run does not complete, do not create a partial or failure HTML file. Tell the user in chat what did not complete and why, without describing internal processing stages unless they ask for diagnostics.

**Temporary memory:** intermediate mapping data — including the normalization artifact — is written to one temporary, marked run workspace (mirroring `/definition-check`'s workspace discipline: OS-temporary by default, disjoint from `--output-dir`, exact-cleanup on handoff) and deleted after completion unless the lawyer explicitly asked for retained debugging artifacts. Only `conform.json`, `conform.html`, and the clean text persist.

## Boundaries

- No silent document modification. `/conform` never writes to the source or core document; it only produces the redline, clean text, and mapping record for the lawyer to apply.
- No reusable semantic-mapping library. Every mapping is inferred from the current versioned ledgers of the two documents actually in front of the lawyer, not from a stored table of prior mappings.
- No PDFs, scanned documents, or OCR. V1 supports `.docx` only.
- `/section-check` is a separate skill and out of scope here.
- `/conform` never reads or writes `lqprofile.md` or `lqplaybook.md`. Mapping, escalation, and presentation remain objective; generic journey capture belongs to the scribe.
- Unreviewed substantive deal decisions are never made by this skill. Escalated mappings and no-mapping results are left to the lawyer or a separately authorized agent.
- Operating without current ledgers for both documents is out of scope; the ledger preflight is a hard stop, not a soft warning.
