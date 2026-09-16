# Mini-PRD: `/playbook-builder`

**Proposer:** Mike Kennedy **Status:** Public implementation design note.

## Description: What is it?

`/playbook-builder` turns one to five lawyer-selected templates, precedents, negotiated agreements, or KM notes into a versioned contract playbook. It records preferred positions, ranked fallbacks, red lines, approved wording, dependencies, provenance, and optional Matter Lenses.

The plugin ships the method, artifact contract, and deterministic safeguards. It ships no legal position. Every inferred position remains a candidate until a lawyer expressly approves it in the local playbook package. This is the boundary between the repository's portable professional method and firm-specific positional judgment.

## Problem: What problem is this solving?

Contract policy is often dispersed across templates, remembered concessions, negotiated agreements, and informal guidance. Manual consolidation can mistake repeated counterparty wording for house policy, lose the source of a fallback, or create a set of positions that do not work coherently across linked clauses.

## Why: How do we know this is a real problem and worth solving?

Transactional lawyers already build and maintain playbooks, but the source analysis and approval trail are commonly manual. A source-bound candidate workflow reduces that effort while ensuring policy approval remains strictly with the lawyer. The initial synthetic eval tests that boundary directly: an approved template supports a proposal, but does not itself approve it.

## Success: How do we know if we have solved this problem?

A lawyer can take one to five related sources through a guided session and produce a coherent, approved playbook package where:

- every admitted source is hashed, readable or visibly parked, and assigned a confirmed source role;
- every operative position has exact provenance or an explicit lawyer decision;
- approved wording retains defined-term anchors so downstream review can adapt it to the contract rather than importing house vocabulary blindly;
- candidates and conflicting material remain non-operative;
- fallback ranks and dependencies validate;
- Standard Baseline remains the default and Matter Lenses are definitions, not automatic activations; and
- the receipt binds the playbook to the exact source manifest and playbook hash.

## Audience: Who are we building for?

Transactional lawyers, in-house counsel, and legal knowledge teams maintaining contract positions for a defined agreement family and represented side.

## What: Roughly, what does this look like in the product?

- **Trigger:** Build, formalise, or update a contract playbook from selected precedents or KM material.
- **Inputs:** One to five `.docx`, `.pdf`, `.md`, or `.txt` sources; source roles; represented side; agreement family; and an output folder. Or an existing firm playbook table in `.docx`, `.xlsx` or `.csv` for `import-playbook`.
- **Steps:** Freeze the source and defined-term census, align issues by legal function, retain exact provenance, propose candidate ladders and Matter Lenses, obtain explicit approval, test cross-issue coherence, validate, and seal the package. `import-playbook` short-cuts the census for a table the firm already maintains: every row anchors to its manifest element, cells are summaries not approved wording, rows land as candidates, and only the lawyer's confirmation in `--approve-all` approves and seals them.
- **Deliverable:** Canonical JSON plus local Markdown inspection view, a coherence report, and build receipt.
- **Playbook:** Reads only confirmed `[playbook-builder]` workflow and presentation preferences. It never reads `lqprofile.md`, and neither profile file may supply legal positions, precedent text, client facts, or matter instructions.
- **Tool cascade:** Standard-library local hashing and DOCX/text extraction by default, with host-native PDF text and visual reading where required. Legal analysis remains host reasoning over the lawyer-selected local corpus.
- **Out of scope:** Automatic policy approval, unrelated agreement families in one run, negotiation archaeology across redline generations, live contract review, external storage, or skill-initiated network calls.

## How: What is the experiment plan?

1. Freeze a shared JSON Schema and deterministic source-manifest contract.
2. Prove source IDs, hashes, candidate separation, lens compilation, receipts, and malformed-input failure modes with unit and command-line tests.
3. Run the synthetic approved-template eval and score source accounting, provenance, candidate separation, and approval gating.
4. Add synthetic multi-precedent and conflicting-source cases before making broader quality claims.
5. Conduct lawyer review of the resulting ladders and coherence reports.
6. Test a clean packaged invocation before release.

## When: When does it ship and what are the milestones?

The skill is shipped in the transactional bundle. Changes should preserve canonical/package parity, pass repository validation, and include public synthetic checks before maintainer review.
