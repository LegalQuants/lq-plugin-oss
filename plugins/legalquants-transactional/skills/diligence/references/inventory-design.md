# Inventory design: the dual manifest, deterministically

Design note for `/diligence` step 1 and the Gate 1 surface. This is the build-against spec for the file manifest and the relationship manifest. The governing principle: deterministic scripts do all the work they can, models fill only the gaps, and downstream stages trust a model output only after it is schema-validated, quote-verified, or human-confirmed.

## The shared ingestion module

Stage 1 is use-case-agnostic: inventory, hashing, readability, version tracking. That is the bare-bones core a `/docreview` sibling (or any process-a-document-dump skill) reuses unchanged. Stage 2 is the fork point: `/diligence` models relationships as contract families; a disputes sibling swaps in clustering by custodian, sender and recipient, communication channel, and event references, keeping Stages 1 and 3 as they are.

## Stage 1: File manifest (script work, one narrow model pass)

A script builds the manifest; no model touches steps 1–4.

1. **Walk.** For every file: path, size, extension, content hash, page count. The content hash is the stable doc ID. Same file, same ID. This makes re-runs idempotent and caching safe.
2. **Readability probe.** Attempt text extraction and record the per-page yield. Classify: native text / scanned / encrypted / corrupt. A script measures "unreadable"; no model asserts it. This keeps the coverage receipt honest.
3. **VDR index reconciliation.** Most data-room exports ship an index (an index spreadsheet, or numbered folders like `3.2.1 Amendment No 2 …`). Parse it with a script and diff it against the walk. Index says 214 documents and the folder has 209 → five gap-report entries before any model has run.
4. **Count assertion.** The script fails loudly if any file lacks a manifest row. The script enforces "zero unreconciled manifest items" as an invariant.
5. **Metadata extraction (the one model pass).** One small-model worker per document, fresh context, reading only the opening pages plus the signature block. Fixed JSON schema: `{doc_type, title, parties[], dated, references[]}`. Controls: regex-first for what regex can do (dates, "AMENDMENT NO. _ TO", "STATEMENT OF WORK", filename and index-number parsing); schema validation on receipt; capped retries; failures parked as `metadata-incomplete` but still counted; and each extracted field carries a verbatim quote (see quote verification below).

## Stage 2: Relationship manifest

1. **Blocking (script).** Normalize party names (casefold; strip punctuation and entity suffixes like Inc./LLC/Ltd.). Form candidate groups by normalized-party overlap, shared title tokens, filename or index-number prefix, and explicit cross-references. Candidate pairs form only within blocks. This keeps the cost linear-ish: 500 documents across 30 counterparties is ~30 small clusters rather than 125,000 pairs.
2. **Edge resolution (rules first, model for residue).** Legal drafting conventions are close to machine-readable: "Amendment No. 2 to the Master Services Agreement dated January 5, 2023 between X and Y" names its parent's title, date, and parties. A script matches reference strings against the manifest; a match within tolerance is a **rule-based edge**, with no model involved. Only the ambiguous residue goes to a model, which receives the two metadata records (without the full documents) and returns `{relation: amends | SOW-under | schedule-of | guarantees | supersedes | none, evidence: "<verbatim quote>"}`.
3. **Quote verification (script).** Each model-asserted edge and each extracted field must carry a verbatim quote, and a script confirms the quote exists in the source document. No match, no edge; the skill parks the claim. This one mechanism converts "the model said so" into "the document says so." The finding pin cites use the same machinery at scale, and `/cite-check` points it the other way.
4. **Family assembly (script).** Union-find over the accepted edges. The family ID is the base agreement; amendments sort by date and number; orphans remain single-document families. Pure graph code, deterministic given the edges.

## Stage 3: The gate launders remaining nondeterminism

Each edge on the Gate 1 family map carries its provenance: `rule` (reference-string match) or `model` (with its quote shown). Rule edges render as grouped; model edges render as **proposed**. The lawyer confirms or regroups, and the skill freezes the confirmed map to JSON. Downstream stages read only the frozen file. Even where a model call could vary between runs, the artifact the run depends on is a human-confirmed, versioned document, and nondeterminism stops at the gate.

## Why this shape pays twice

- **Evals are cheap.** A fixture data room in `evals/` with an expected `manifest.json` and `families.json` is a deterministic diff: the re-runnable input/output pair CONTRIBUTING demands.
- **Incremental re-run falls out free.** Results cache by content hash. When the target uploads 40 new documents, a manifest diff identifies them, only new hashes get processed, and blocking re-runs at low cost. That is the first slice of v1.1 response handling, already half-built.

## Honest limit

Metadata extraction from scanned or badly drafted documents stays probabilistic. The design routes that uncertainty into proposed edges and the parked lane, where the lawyer sees it, instead of letting it corrupt the family map unnoticed.
