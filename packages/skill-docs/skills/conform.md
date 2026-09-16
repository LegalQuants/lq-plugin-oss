# Mini-PRD: `/conform`

**Maintainer:** Josh

## Description: What is it?

`/conform` uses current `/definition-check` ledgers to adapt precedent language to a core document.

It maps conceptual scope and dependencies, not merely term names, and returns a copy-pasteable clean version, an HTML redline, supporting mapping evidence, and explicit escalations.

## Problem: What problem is this solving?

A copied clause can remain syntactically valid while importing the wrong entities, definitions, rights, obligations, or economic mechanics.

Identically named terms may have materially different meanings. Differently named terms may represent the same concept. Literal replacement cannot reliably preserve the source clause's operation.

## Why: How do we know this is a real problem and worth solving?

The proposed advance is semantic portability: lawyers can reuse the best source clause rather than only a precedent whose terminology happens to match.

The open ledger standard and proven eval corpus become shared foundations for additional workflow-specific agentic systems. This is not a claim that defined-term checking, cross-document review, or precedent assistance are new categories.

## Success: How do we know if we've solved this problem?

A successful run:

- Verifies the identity and current version of every relevant document and ledger.
- Stops when a required ledger is missing, stale, mismatched, or unreliable.
- Preserves the source clause's evidenced conceptual scope using destination-document vocabulary.
- Recognizes that identical names do not prove equivalent meanings.
- Supports one-to-many, many-to-one, and nonliteral mappings where evidenced.
- Escalates ambiguity or substantive deal choices.
- Produces an accurate HTML redline, clean copy, and mapping explanation.
- Never silently edits the source or core document.

The directional goal is 100% precision and recall, but performance must be established through evaluation rather than represented as a universal semantic-accuracy figure.

Actual evals use human-verified contracts from EDGAR or another traceable corpus. Deterministic scoring, versioned iterative LLM judges, development cases, a frozen holdout, abstention reporting, and expert-disagreement reporting are used. No common Eval Pack is currently accepted; if the repository later accepts one, this skill should integrate with it.

## Audience: Who are we building for?

Transactional lawyers copying or adapting precedent language into a core document.

## What: Roughly, what does this look like in the product?

- **Trigger:** Two supported invocation modes:
  1. **Conform selected text:** the lawyer (or agent) selects precedent text and identifies the core document.
  2. **Check for precedent leakage:** the lawyer asks `/conform` to inspect the core document against relevant source-document ledgers.
- **Inputs:** The selected source text when using conform-selected-text mode; the core document and at least one source or precedent document; current `/definition-check` ledgers (schema `0.13.0`) matching the relevant document versions.
- **Steps:**
  1. Confirm which document is the core document.
  2. Verify document IDs, versions, hashes, ledger freshness, and extraction integrity. Hard-stop on a missing ledger, a `schema_version` below `0.13.0`, a source-hash mismatch, or an incomplete semantic/occurrence/reference review — never proceed on stale or partial evidence.
  3. If a ledger is absent or stale, stop and prompt the lawyer to run `/definition-check`.
  4. Run deterministic term normalization over both documents, rewriting every accepted defined-term usage into a document-qualified placeholder variable and producing the lookup table and cross-document flags (`definition-normalization-1.0.0`).
  5. Compare the relevant ledger entries, definitions, usages, relationships, and dependencies — starting from the normalized text and lookup table rather than raw term strings.
  6. Infer mappings from the current documents; do not rely on a reusable semantic-mapping library.
  7. Detect same-name semantic conflicts, false friends, missing dependencies, one-to-many mappings, and precedent leakage.
  8. Decide dynamically which mappings require escalation and record the evidence and reasoning.
  9. Generate the clean conformed text, HTML redline, mapping evidence, and escalation notes.
  10. Leave application of the proposed language to the lawyer or a separately authorized agent.
- **Deliverable:** Copy-pasteable clean text; HTML redline; evidence-backed mapping record (`conform.json`); explicit escalations; and, in leakage-check mode, a report identifying suspicious source-document concepts remaining in the core document.
- **Playbook:** V1 reads no `lqplaybook.md` namespace and proposes no playbook line. Mapping, escalation, and presentation remain objective. The skill never reads or writes `lqprofile.md`; generic journey capture belongs to the scribe.
- **Out of scope:** Silent document modification; unreviewed substantive deal decisions; a reusable library of semantic mappings; operating without current ledgers; PDFs; scanned documents; OCR; general drafting automation; `/section-check`; profile or playbook writes; multi-version matter-snapshot integration (v2).

Missing evidence, stale state, version mismatch, extraction failure, or unresolved core-document identity are deterministic hard stops.

Agentic escalation considers competing mappings, semantic distance, missing dependencies, conflicting evidence, and possible changes to operative scope. "Safe to propose" never means silent application.

## How: What is the experiment plan?

1. Stabilize the shared ledger contract — done, schema `0.13.0`.
2. Implement document and ledger preflight.
3. Implement deterministic term normalization over one or more ledgers — done, `definition-normalization-1.0.0` (`normalize_terms.py` in `/definition-check`).
4. Implement conceptual-scope and dependency comparison.
5. Implement evidence-backed mapping and escalation.
6. Generate clean text and HTML redlines.
7. Add precedent-leakage detection.
8. Use the synthetic financing fixture as the first demo specification:
- Same-name `Material Adverse Effect` conflict.
- One-to-many `Default` mapping.
- `Authorized Officer` semantic false friend.
9. Build actual evals from human-verified public contracts.
10. Add deterministic and versioned LLM-judge scoring.
11. Iterate on the development set while preserving a frozen holdout.
12. Preserve compatibility with any future accepted common Eval Pack.

The synthetic fixture demonstrates intended behavior but is not performance evidence.

## When: When does it ship and what are the milestones?

Milestones are dependency-based:

1. Stable shared ledger contract — done.
2. Version and freshness preflight.
3. Selected-text conformance.
4. Semantic mapping and escalation.
5. HTML redline and clean output.
6. Precedent-leakage mode.
7. Public-contract development evals.
8. Frozen holdout and measured results.
9. Eval Pack integration decision.
10. Stable `/conform` release candidate.
