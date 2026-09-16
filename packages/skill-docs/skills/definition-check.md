# Mini-PRD: `/definition-check`

**Maintainer:** Josh **Status:** Draft prototype for review; not release-ready

## Description: What is it?

`/definition-check` analyzes defined terms in a `.docx` contract.

It combines deterministic document processing with independent agent review to create an evidence-backed JSON ledger of candidate terms, definitions, usages, relationships, and potential problems. It identifies undefined terms, unused definitions, inconsistent usage or capitalization, duplicate or conflicting definitions, and other suspicious terms.

The JSON ledger is the canonical artifact. Conformance is deferred as an optional future mode within this skill, following progressive disclosure, once the single-document ledger is stable and independently validated.

## Problem: What problem is this solving?

Transactional lawyers routinely assemble contracts from multiple precedents. Each precedent carries its own defined terms, entities, and drafting conventions.

Manual review can miss:

- Terms imported without their definitions.
- Definitions left behind but never used.
- Incorrect entity names.
- Inconsistent capitalization or usage.
- Familiar-looking terms whose meanings differ materially.

The most dangerous errors can remain linguistically plausible while changing the transaction's operation.

## Why: How do we know this is a real problem and worth solving?

Transactional lawyers draft and revise contracts from precedent language every day. Defined-term checking is commonly performed through manual searches, Word tools, proofreading, and reviewer memory.

Existing tools establish that the problem is real, but the proposed contribution aims to produce an open, evidence-backed, versioned ledger standard that downstream agentic workflows can reuse and evaluate reproducibly.

## Success: How do we know if we have solved the problem?

The directional goal is 100% precision and recall; that is an aspiration, not a current performance claim or release threshold. Current public-corpus runs are diagnostic and remain guardrail-blocked.

V1 prioritizes avoiding false negatives. Uncertain or unreadable cases must never be represented as cleared.

Evaluation will measure precision and recall separately across:

- Undefined terms.
- Unused definitions.
- Inconsistent capitalization and usage.
- Duplicate or conflicting definitions.
- Suspicious imported terms or entities.
- Semantically inconsistent uses.

Actual evals will use traceable contracts from EDGAR or another established corpus, with human-verified expected findings. Seeded defects may be added to create controlled cases.

Scoring will combine deterministic checks with versioned LLM-as-judge evaluation where semantic judgment is necessary. Precision, recall, abstention, defect class, and expert disagreement remain separate. Development cases and a frozen holdout remain separate.

## Audience: Who are we building for?

Transactional lawyers who draft, revise, or review contracts using precedent language.

## What: Roughly, what does this look like in the product?

- **Trigger:** A lawyer runs `/definition-check` against a `.docx` contract.
- **Inputs:** One `.docx` document.
- **Steps:**
  1. Extract text while retaining reliable document locations.
  2. Run a deterministic scan for likely defined terms and definition structures.
  3. Run an independent agentic scan for candidates missed by deterministic detection.
  4. Reconcile the candidate lists, using deterministic normalization for exact duplicates and agents for semantic overlap.
  5. Locate each candidate's definition and usages.
  6. Build the canonical JSON ledger.
  7. Run a supervising analysis over the complete ledger.
  8. Identify undefined, unused, inconsistent, conflicting, suspicious, and uncertain terms.
  9. Generate the findings report and persist the ledger.
- **Deliverable:** A lawyer-facing interactive HTML glossary, canonical JSON ledger, and deterministic Markdown report. A companion CLI (`normalize_terms.py`) additionally emits a versioned `definition-normalization-1.0.0` artifact — per-block text with every accepted defined-term usage rewritten to a placeholder variable, a variable-to-definition lookup table, and (for multi-document runs) deterministic cross-document flags — for downstream consumers such as `/conform`.
- **Playbook:** V1 reads no `lqplaybook.md` namespace and proposes no playbook line. Analysis, thresholds, classifications, and presentation remain objective. The skill never reads or writes `lqprofile.md`; generic journey capture belongs to the scribe.
- **Out of scope:** Cross-document conformance in this draft; direct source-document editing; PDFs; scanned documents; OCR; `/section-check`; silent clearance of uncertain cases; profile or playbook writes.

Each ledger records:

- Stable document ID and document version.
- Parent or prior version when known.
- Source locator and content hash.
- Definition and usage locations.
- Exact and normalized term forms.
- Supporting evidence and inclusion rationale.
- Semantic relationships and dependencies.
- Findings, confidence, and uncertainty.
- Ledger-schema, extraction-engine, model, prompt, judge, and run versions.

The current CLI writes each run to an explicit user-selected output directory. Persistent hidden-ledger lifecycle and stale-version routing remain future work.

**Tool cascade:** use open-source local `.docx`/OOXML processing by default. Exact implementations will be selected during the build.

## How: What is the experiment plan?

Build the thinnest complete `.docx` flow:

1. Define and validate the ledger schema.
2. Implement deterministic extraction and location tracking.
3. Implement deterministic candidate detection.
4. Add agentic detection and reconciliation.
5. Add definition, usage, relationship, and issue analysis.
6. Generate findings and proposed corrections.
7. Implement deterministic Markdown and interactive HTML renderers.
8. Assemble a human-verified public-contract development corpus.
9. Add deterministic and versioned LLM-judge scoring.
10. Freeze a holdout before iterative engine refinement.
11. Investigate every missed seeded defect, emphasizing false negatives.
12. Stabilize the ledger contract before building `/conform`.

No common Eval Pack is currently accepted. If the repository later accepts one, this skill should integrate with it rather than create a competing evaluation framework.

## When: When does it ship and what are the milestones?

Milestones are dependency-based:

1. Ledger schema and version contract.
2. `.docx` extraction.
3. Deterministic candidate detection.
4. Agentic detection and reconciliation.
5. Definition and usage analysis.
6. Findings and corrections.
7. Markdown and Word rendering.
8. Development corpus and scoring.
9. Frozen holdout and measured results.
10. Stable ledger contract for the optional future conform mode.
