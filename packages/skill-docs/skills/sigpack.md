# Mini-PRD: `/sigpack`

**Maintainer:** Jamie

## Description: What is it?

Two jobs, one skill, both on the closing set already sitting in a folder.

1. **Pack.** Point it at the execution-version PDFs. It finds every signature page, reads who signs (party, signatory, capacity), and builds the packs three ways: by agreement, by counterparty, or by signatory. Where two parties share one page, each gets its own copy. Each pack ships with a signing-instructions table and a cover note the client can act on.
2. **Compile.** Point it at the folder of returned signed pages. It works out which document and which party's block each page belongs to, whether the page is a wet-ink scan or a completed e-signature PDF, and produces one fully executed PDF per document with each signed page in place of its unsigned block, plus a list of what is still missing.

## Problem: What problem is this solving?

Signing a deal means dozens of documents, each with signature pages for several parties, and a party may sign in more than one capacity: a founder signs as CEO of the company and again personally as a key holder. Someone, usually a junior, scrolls hundreds of pages to find the signature pages, cuts them out, sorts them per party or per signatory, and writes the email saying who signs what and how many copies. Then it all comes back as a mess of scans and DocuSign envelopes, and someone reassembles the executed copies by hand and chases the gaps.

## Why: How do we know this is a real problem and worth solving?

- A closing may contain many documents, several parties, and multiple signing capacities. The workflow keeps party, signatory, and capacity separate, records every page, and sends ambiguous cases to review.
- The pack and compile halves work on the local execution set and returned pages. The signing provider remains responsible for the signing event itself.

## Success: How do we know if we've solved this problem?

Pack: a first-time user drops a closing set and gets correct packs plus a correct instructions table without touching a PDF by hand. Zero signature pages missed, zero pages attributed to the wrong party. Anything ambiguous is flagged for manual review, never guessed.

Compile: every returned page lands in the right document at the right block, scanned or not, and the missing list is exactly right. Withhold one pack and the gap list names exactly those pages.

## Audience: Who are we building for?

Transactional and funds lawyers running closings, and the paralegal or PSL running the closing checklist.

## What: Roughly, what does this look like in the product?

- **Trigger:** "prepare signature packs for this closing" / "compile the signed pages back in".
- **Inputs:** Pack: a folder of execution versions, PDF or Word (Word is converted with the host's bundled LibreOffice first). Compile: the same execution versions plus a folder of returned signed pages: wet-ink scans, photos, native PDFs, and completed e-signature envelopes (often with a completion certificate appended and sometimes locked).
- **Steps — pack:**
  1. Find candidate pages: regex over page text for signature-block markers (`Signature`, `Execution`, `Executed`, `Signed`, `Witness`, `Agreed and Accepted`, `By:`, `Name:`, `Title:`, `Date:`), render each candidate and confirm visually, OCR any page with no text layer.
  2. Read each block: party (the entity bound), signatory (the human under "Name:", never a company), capacity (the role under "Title:"). Several blocks per page allowed. Blank name is Unknown and flagged.
  3. Ask which grouping the user wants (agreement / counterparty / signatory), copies per party (default one), whether shared pages are duplicated (default yes), and the filename convention (default "Signature Pack – [Group]").
  4. Build one PDF per group, pages ordered by document then page number.
  5. Write the instructions table: party, document, sign as (capacity) by (signatory), copies. Write the cover note: packs attached, copies to sign, return-by date, pages held in escrow and released only on instruction when documents reach execution form.
- **Steps — compile:**
  1. Classify each returned page: OCR if scanned; read the "Signature Page – [Agreement] – [Party]" header where present, otherwise read the block. For an e-signature envelope, unlock it if permitted, drop the completion certificate and any envelope cover pages, keep the signed pages, and read the e-signature stamp for signatory and date.
  2. Match to execution version and party block by agreement, party, signatory. Ambiguous goes to a manual-review queue, never guessed.
  3. Assemble: the execution version with each party's signed page replacing its unsigned block page. One executed PDF per document.
  4. Report: placed, unmatched, duplicated, missing, per document and per party.
- **Deliverable:** Pack: the packs, the instructions table, the cover note. Compile: executed PDFs plus the gap list. Either half: a per-matter viewer over the ledger, rendered on demand, where the lawyer checks and corrects what was read.
- **Playbook:** `[sigpack]` namespace: default grouping, default copies, duplicate rule, filename convention, cover-note wording (escrow line included by default, firm can override), executed-file naming. Journey capture belongs to the scribe, not this skill.
- **Out of scope:** running the e-signature process itself (the skill consumes its output); drafting or checking the signature blocks; judging authority to sign; releasing pages from escrow (the lawyer's call; the skill lists what is held). Dating is done only on the lawyer's instruction.

## How: What is the validation plan?

- Public synthetic fixtures should cover multiple agreements, parties, capacities, shared pages, wet-ink scans, native PDFs, and completed e-signature envelopes. Tests should prove page accounting, grouping, duplicate-page rules, matching, and exact missing-page reports. Private closing materials and comparative results remain outside this repository.
- The classification step combines a text pre-filter with visual review of rendered pages when available; unreadable or ambiguous pages remain visible for manual review.

## When: When does it ship and what are the milestones?

The skill is shipped in the transactional bundle. Pack and compile changes should preserve page accounting, ambiguity handling, and the separate validation of each half.
