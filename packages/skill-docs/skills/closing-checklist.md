# Mini-PRD: `/closing-checklist`

**Maintainer:** Bhavya **Status:** Implementation draft — maintainer review

## Description: What is it?

Create and substantively revise a transaction closing checklist in an editable Word document. Start with one principal deal document, usually an SPA, and optional supporting material. Read the document, extract the actions and deliverables, raise relevant possible omissions for the lawyer to consider, and produce a checklist in the lawyer's house format or a generic landscape table.

The initial build and evaluation focus is a private M&A share sale with separate signing and closing. The method also accommodates simultaneous signing and closing. Broader transaction and jurisdiction coverage remains to be validated.

## Problem: What problem is this solving?

Preparing the checklist involves substantial manual extraction and administration. Obligations can be missed, and useful items outside the SPA may not come to mind. As drafts change, obligations and clause numbers move, and the lawyer must reconcile those changes against a separately maintained checklist.

The checklist may be shared with the client and the other side. It must remain useful in Word, preserve the team's edits, and support an external copy without internal notes.

## Why: How do we know this is a real problem and worth solving?

The proposal comes from my own experience preparing checklists, primarily for split signing and closing. The expected benefits are time saved, fewer missed obligations, consideration of reasonably relevant additional items, and more reliable reconciliation after document changes.

Time savings and accuracy improvements remain to be measured against a manual workflow and an ordinary prompt.

## Success: How do we know if we've solved this problem?

- A lawyer receives an editable, usable Word checklist in the approved format.
- In the test corpus, all annotated express in-scope obligations are included or explicitly raised for review; no required item is silently omitted.
- Every item described as coming from an agreement has a supporting passage and accurate reference. Optional practice suggestions are distinguishable and require the lawyer's acceptance.
- Revision identifies the expected additions, amendments, removals and reference changes, then applies only approved changes while preserving unrelated lawyer edits.
- Timing preserves the source's trigger, direction and counting language. Unsupported calendar dates are never supplied.
- An external copy contains no internal notes, including recoverable notes in tracked changes or comments.
- Repeated application of an approved revision does not duplicate items.

## Audience: Who are we building for?

Transactional lawyers responsible for preparing and revising closing checklists at large firms. Start with private M&A share sales; US coverage is a priority alongside UK practice, with each jurisdiction tested separately.

## What: Roughly, what does this look like in the product?

- **Trigger:** Create: "Draft a closing checklist from this SPA." Revise: "Update this checklist for the amended SPA / new document / these instructions."
- **Inputs:** Create: an anchor agreement, user instructions, an optional house template and selected supporting documents. Revise: the latest working checklist, including one the skill did not create, plus changed or additional documents or instructions. Request an earlier source only where necessary to establish a change. The latest supplied checklist takes precedence over any older internal record.
- **Steps:**
  1. Establish readable input coverage and infer the transaction structure from the supplied material. Ask focused questions only where missing facts materially affect the checklist; avoid a lengthy standard intake.
  2. Read the entire supplied anchor document, including available schedules and relevant definitions. Collect actions, conditions, approvals and deliverables across pre-signing, signing, the interim period, closing and post-closing. Retain source references, timing and dependencies. Report missing referenced material and unreadable portions.
  3. Present document-derived items and a concise set of possible additional items separately. Explain the basis for suggestions and the facts needed to assess applicability. Model knowledge can suggest questions; it is not evidence of a current legal requirement. The lawyer accepts, rejects or edits proposed additions.
  4. Preserve relative timing exactly. Calculate a calendar deadline only with adequate trigger dates, applicable definitions and calendar information. Where external filing requirements are researched, use current official sources and record jurisdiction, source and verification date. Unverified requirements remain questions. Changes to timing produce proposed revisions for review.
  5. Settle presentation using the supplied checklist or template. Otherwise use the generic landscape layout: title and source line, a party legend and status key, then a table with number, source reference, item, responsibility, timing, status and notes, with a footer on every page naming the source draft. Use merged section rows for transaction phases and lighter sub-headings within long phases; combine signing and closing where appropriate. The notes column is included unless the lawyer decides to omit it. Follow an existing table's structure, including merged cells, and propose any necessary structural change.
  6. In revision mode, present a summary of proposed additions, amendments and removals with the affected row, proposed wording, source and reason. A missing provision in a new source is not by itself proof that a lawyer-added item should be removed. Preserve unrelated status, responsibility and notes. If an obligation changes in a way that makes an existing status questionable, raise that consequence for review.
  7. Apply approved revisions to a separately named copy. Check the resulting Word document visually and structurally. When requested, produce an external copy excluding internal material and verify the saved file, not just its visible table.

- **Deliverable:** An editable landscape Word checklist, or a revised copy following the supplied checklist's format. Revision includes a proposed-change summary before drafting. A requested external copy excludes the notes column. Unresolved matters and material source gaps accompany the output.
- **Playbook:** Proposed `[closing-checklist]` preferences cover default columns and formatting. Read only confirmed entries; explicit instructions and the supplied checklist govern the run. Write a proposed preference only after showing its exact text and receiving consent. No journey capture or `lqprofile.md` access; no matter facts in either profile file.
- **Out of scope:** Routine status administration; inbox monitoring or chasing; inferring completion, waiver or legal clearance; signature packs and executed-document assembly (`/sigpack`); closing bibles; sending or filing. The checklist does not guarantee transaction completeness beyond the supplied sources and reviewed suggestions.
- **Tool cascade:** Open-source document tooling and available host document capabilities by default; firm-selected licensed tools where required and authorised. Scripts and parallel workers are optional. Preserve the same review method across hosts and disclose when the Word deliverable cannot be produced.

## How: What is the validation plan?

Start with fictional private share-sale agreements and lawyer-reviewed expected checklists. Include a split signing/closing case and a simultaneous case. Test express obligations, optional candidates, timing, ambiguities, missing schedules and irrelevant provisions.

Test revisions against a manually edited checklist with changed numbering, new and removed obligations, changed timing and responsibility, retained statuses and notes, and rejected suggestions. Include merged-cell house templates and an external-copy confidentiality fixture.

Test how source references and item identities survive manual Word edits, without making the lawyer maintain a separate technical record. Measure total lawyer effort, including review and correction, and set numerical targets before scoring held-out cases. Public synthetic fixtures and a rerunnable mechanical test suite accompany the package; private evaluation records and lawyer-scored comparative results remain outside this repository.

## When: When does it ship and what are the milestones?

The skill is shipped in the transactional bundle. Broader transaction and jurisdiction coverage requires additional fixtures and maintainer review.
