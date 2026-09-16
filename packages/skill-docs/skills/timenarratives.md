# Mini-PRD: `/timenarratives`

**Maintainer:** James Cockburn

**Status:** Current public design note for the shipped workflow.

## Description

`/timenarratives` turns expressly selected conversation or document material into an unposted draft narrative for lawyer review. It preserves source identity, attribution, order, and coverage gaps while separating documentary support from the lawyer's own attestation.

The skill does not calculate time, reconstruct an entire day, post billing data, or claim that the selected material is a complete workday.

## Supported inputs

Supported inputs include inline notes, TXT, Markdown, EML with MIME-leaf reconciliation, DOCX with attributed tracked-change extraction, and an expressly selected host conversation snapshot when the host provides one.

MSG, PST/OST/MBOX/TNEF, encrypted inputs, and visual PDF redlines fail closed unless a later adapter explicitly supports them.

## Product contract

- No mailbox, Teams, prompt, chat, drive, or filesystem crawling; no connector discovery or background capture.
- Filters apply only to files or conversation material the user expressly selected and never imply complete workday coverage.
- `user_attested` evidence remains distinct from `documentary_supported` evidence and is never silently promoted.
- One primary workstream is assigned per included event; source author, asserted-by, performed-by, named timekeeper, and clause owner remain separate.
- A map confirmation is required before final rendering. It is bound to the reviewed digest and recorded honestly as session approval, not a cryptographic signature.
- Generated maps, narratives, and receipts contain no duration, rates, fees, amounts, billing codes, billability, or posting data.
- Output is an unposted draft for lawyer review, with one concise narrative per workstream and a receipt that separates selected-packet reconciliation from `workday_completeness: not_assessed`.

## Workflow

The deterministic core is `selected source or attestation -> source unit -> evidence atom -> activity event -> workstream -> narrative clause`. It validates IDs, edges, attribution, support inheritance, prohibited fields, selected-source partition, exact hashes, and receipt arithmetic.

Conversation snapshots preserve source speaker, ID, order, timestamp, and coverage gaps. Assistant, tool, quoted, unknown-role, and summary content is context only; requests and automated outputs do not prove lawyer review or completed work.

The user receives an in-memory draft first. Machine-readable publication occurs only after ordinary-language review, validation, freshness checks, and confirmation of the displayed map. A missing or changed digest prevents publication.

## Non-goals

The skill does not post to a billing system, infer completion, discover connectors, create a persistence service or graph database, infer visual redline authorship, or claim jurisdiction-universal suitability.

## Validation

Public tests should use synthetic multi-turn conversations and public documents with quoted mail, nested messages, attachments, duplicate threads, other actors or matters, tracked changes, malformed files, unsupported types, stale confirmations, and source removal. Private controller ledgers, full evaluation campaigns, and comparative results remain outside this repository.
