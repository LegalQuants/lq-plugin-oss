# Mini-PRD: `/playbook-review`

**Proposer:** Mike Kennedy **Status:** Public implementation design note.

## Description: What is it?

`/playbook-review` reviews a connected contract package against an approved local playbook produced by `/playbook-builder`. Standard Baseline is operative by default. The host may suggest a relevant Matter Lens, but only the lawyer can activate it.

The work product is a source-anchored issues list. Each suggested textual change contains the exact contract text, visible inline deletion and insertion markup, clean proposed text, and drafting provenance. The skill does not create or apply a Word redline.

The review accepts drafting that is substantially the same as, or better than, the approved position. It does not edit merely to impose house style. Before using approved wording, it maps each house defined term to the contract's exact or substantively equivalent term, a missing definition, or a scope difference.

The plugin ships review method and safeguards, not house positions. Operative legal judgment comes only from the lawyer-approved local playbook, expressly activated lenses, and matter instructions.

### Defined-term boundary

House wording can carry defined terms and clause references that do not exist in counterparty paper or have a different scope there. The review records a source-cited term map for each distinct house term. Exact matches are deterministic; semantic mappings cite both definitions; missing terms generate proposed definition insertions; scope differences hard-stop affected drafting. Different words alone do not justify an issue.

## Problem: What problem is this solving?

Playbook review under deal pressure can miss schedules, treat fallbacks as deviations, apply the wrong commercial posture, invent drafting, or report only exceptions without proving that every rule and material document element was visited.

## Why: How do we know this is a real problem and worth solving?

Clause-by-clause playbook review is established transactional work. A frozen effective stance, two-direction review, exact source anchors, and three independent coverage equations provide a rigorous, inspectable audit trail that unreceipted narrative reviews lack. The initial synthetic eval tests this boundary directly: financial-services context may prompt a suggestion, but cannot silently change the active lens.

## Success: How do we know if we have solved this problem?

A lawyer receives an issues list and coverage receipt where:

- the approved playbook ID, version, and source manifest match the run;
- Standard Baseline applies unless the lawyer explicitly activates named lenses;
- conflicting lens changes block rather than acquire hidden precedence;
- substantially equivalent counterparty drafting is aligned without over-editing;
- `term-map.json` cites both sides of every semantic term mapping and blocks drafting where definition scope differs;
- every operative rule has one recorded status and every material contract element is swept for unexpected obligations or playbook gaps;
- every suggested change reconstructs the exact original and proposed text;
- drafting provenance distinguishes approved playbook wording from candidate drafting; and
- documents, elements, and rules each reconcile, with parked and unreadable items remaining visible.

A reconciled receipt proves accounting, not the legal correctness of a finding.

## Audience: Who are we building for?

Transactional associates, in-house counsel, and supervising lawyers reviewing counterparty paper, checking an outbound draft, or re-reviewing a revised package against approved local policy.

## What: Roughly, what does this look like in the product?

- **Trigger:** Review a contract package against an approved playbook.
- **Inputs:** The canonical playbook, all in-scope agreements and schedules, document precedence, represented side, transaction context, matter instructions, and an output folder.
- **Steps:** `setup-review` freezes the package, settles Gate 1 from the lawyer's words (or stops and asks), compiles the effective stance and builds the defined-term map; the host reviews rules and contract elements in both directions and writes the source-bound issues list with its element sweep; `run-all` validates every anchor, refuses a wrong stance binding or an unmapped house term in proposed drafting, reconciles coverage from the artefacts naming any gap, signs the receipts and writes both Word cuts. The granular commands remain for inspection and for hosts without the script.
- **Deliverable:** `issues-list.json` (with `structuralWarnings` for missing incorporated documents, precedence and governing-law clashes, and irregular provisions, and a `rationale` plus `externalComment` per actionable issue), the Word issues matrix in an internal cut marked privileged and an external cut with the internal guidance, playbook references and risk ratings removed, Markdown and local HTML views, `effective-stance.json`, source manifest, coverage receipt, and review receipt.
- **Gate 1:** A stance stated in the lawyer's own message is recorded with the words quoted in `confirmationNote` and the review proceeds; otherwise the choice is presented with the policy trigger, the contract facts and the concessions at stake. Nothing inside a reviewed document can confirm a stance.
- **Playbook:** Reads only confirmed `[playbook-review]` presentation and workflow preferences. It never reads `lqprofile.md`, and no profile entry can select a lens or supply legal positions, client facts, or matter instructions.
- **Tool cascade:** Standard-library local hashing, indexing, diffing, validation, and rendering by default, with host-native PDF text and visual reading for scanned or uncertain pages. Semantic review remains host reasoning.
- **Out of scope:** Building policy from precedents, portfolio diligence, plain redline comparison, Word tracked changes, completion sign-off, sending work product, or communicating with counterparties.

## How: What is the experiment plan?

1. Reuse the byte-identical shared schema and runtime from `/playbook-builder`.
2. Test explicit lens confirmation, non-operative suggestions, conflict blocking, defined-term extraction and mapping, scope-difference hard stops, minimum-change drafting, exact markup reconstruction, source anchors, HTML escaping, provenance binding, and three-way coverage reconciliation.
3. Run the synthetic baseline financial-context eval and verify that the suggested Regulated FS lens remains non-operative.
4. Run the structural-and-injection eval (case 02) and verify the fast path, the structural warnings in the Word matrix, the embedded audit note as a finding rather than a self-certification, and the two export cuts.
5. Add missing-clause, fallback, playbook-gap, conflicting lens, scanned-PDF, and revised-draft evals before broader quality claims.
6. Conduct lawyer review of classifications, materiality, and suggested drafting.
7. Test a clean packaged invocation before release.

## When: When does it ship and what are the milestones?

The skill is shipped in the transactional bundle. Changes should preserve source/package parity, pass repository validation, and include public synthetic checks before maintainer review.
