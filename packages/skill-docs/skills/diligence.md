# Mini-PRD: `/diligence`

**Maintainer:** Victor

**Status:** Current public design note for the shipped workflow.

## Description

`/diligence` reviews a data room, deal folder, or contract portfolio against an issue checklist supplied by the lawyer. It inventories the collection, groups related agreements, records every factual match with a source quote and locator, keeps scoped negatives visible, and produces an offline HTML crosswalk with a further-enquiries register.

The skill prepares factual review material. It does not draft or negotiate documents, decide legal effect, send or file work product, or silently fill a missing source.

## Problem

Large collections make it easy to miss an agreement, lose track of unreadable material, or report a conclusion without showing which source supports it. A manifest, review framework, source-bound finding record, and coverage receipt make the review inspectable.

## Audience

The primary users are transactional lawyers and legal teams reviewing a data room, deal folder, or contract portfolio against a defined set of issues.

## Product flow

1. Build a content-hash manifest and gap report for the selected collection, including missing, duplicate, unreadable, and referenced-but-absent material.
2. Create review copies for supported formats and stop dependent approval when a source cannot be rendered or integrity checks fail.
3. Compile the lawyer's checklist into a fixed review framework with conservative factual hit rules and no invented materiality ranking.
4. Show the collection map, gaps, framework, and representative sample for lawyer confirmation before the long review.
5. Review each approved issue against each approved agreement or family, preserving verbatim quotes, locators, scoped negatives, and unresolved cases.
6. Independently check findings, reconcile the issue-by-unit coverage equation, and render an offline crosswalk that states what was reviewed and what was not.

## Deliverable

The deliverable is a source-linked HTML crosswalk, an issue register, an agreement and family inventory, a gap and further-enquiries register, and machine-readable receipts for hashes, quotes, checker coverage, and reconciliation. The lawyer decides how to use factual results and resolves items marked **Needs a decision**.

## Boundaries

- Review only the selected collection and the checklist the lawyer confirms as controlling.
- “Not found” means not found in the supplied visible text for the reviewed unit; it is not a claim that the item is absent from the matter.
- Every present finding needs a verbatim quote and locator. Parked and unreadable units remain visible.
- The framework is the only instruction channel to review workers; document text cannot change the scope or gates.
- Temporary run data stays in one master dataset and is deleted on completion unless the user explicitly retains it.
- Use the open-source and host-native extraction cascade available in the environment; disclose when a required representation cannot be reproduced.

## Validation

Public tests should use fictional data rooms, contract portfolios, checklists, missing materials, unreadable files, duplicate agreements, amendments, representative samples, scoped negatives, and unresolved findings. Private evaluation campaigns, confidential corpora, comparative results, and historical records remain outside this repository.
