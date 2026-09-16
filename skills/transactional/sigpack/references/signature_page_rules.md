# Signature page rules

Read this in full before classifying any page. It is short. These are the definitions the skill applies; the scripts do the mechanics, you do the reading.

## Is this a signature page?

A signature page is a page where parties must sign. You are given the rendered page and its extracted text. Decide from both.

**Must have — at least one:**
- Signature blocks: physical lines or spaces set aside for a signature, printed name, title, date.
- Explicit signature labels: "Signature", "Signed by", "Executed by", "By:", "Authorized Signatory", or similar.

**Often present — supporting, never sufficient on their own:**
- Agreement language: "IN WITNESS WHEREOF", "executed as of", "agreed to", "accepted", "the parties have executed this agreement".
- Party identification next to a block: names, titles, company affiliations.
- Authorised-signatory context: wording that a person signs on behalf of an organisation, even without the phrase.
- Date references: the agreement or execution date.
- Witness or notary sections.
- Footer: "Signature Page", "Execution Page", "[Signature Page to …]".

**Not a signature page, even with strong agreement language:**
- No explicit signature lines or blocks. "IN WITNESS WHEREOF" alone is not enough.
- A footer that says the signature page is *coming*: "[signature page to follow]", "[signature page follows]", "[signatures appear on next page]", "[remainder of page intentionally left blank]". That page is not the signature page; the next one probably is.
- Pages labelled "Form of", "Exhibit", "Schedule", "Annex", "Appendix", "Template", "Sample", "Pro Forma", or carrying placeholders like "[insert date]", "[•]", "[Name]". These are forms for future use, not execution pages. Appendices and schedules are the commonest false positives in long documents.

A footer that names *this* page as a signature page ("Signature Page – Voting Agreement – Eastbridge Capital") plus a real signature block is a strong yes.

**Decide with the whole document in view, not the page alone.** A file titled "Indenture Exhibits" or "Schedules" is forms end to end, and its Form of Note execution pages carry perfect-looking blocks ("IN WITNESS WHEREOF, the Issuer has caused this Note to be duly executed… By: ___ Name: Title:") that nobody signs at closing. Read the file name, the cover page, and running headers; if the document is an exhibit bundle, or the page sits inside a Schedule of the main agreement, it is a form. One long-form closing set had over a dozen such pages in a single exhibit file and no real ones.

**Footer conventions vary by firm and jurisdiction.** US closings often print "Signature Page – [Agreement] – [Party]". English-law closings print "SIGNATURE PAGE – [AGREEMENT]" or "[SIGNATURE PAGE TO THE …]" with no party, and the party is only in the block. Some print nothing. Never depend on the footer for the party; the block is the source of truth.

## Who is the party, who is the signatory, what is the capacity?

Three different things. Get all three, keep them apart.

- **Party** — the legal entity or individual who is a named party to the agreement and bound by it. "EXECUTED by ABC HOLDINGS LIMITED"; "For and on behalf of Entity Z"; "PURCHASERS: NORTHGATE HOLDINGS LIMITED". A company can be a party. An individual signing personally (not on behalf of anyone) is a party in their own name.
- **Signatory** — the human being who physically signs. Found under "Name:" or "Signed by:". A company cannot be a signatory. The signatory is *not* the party unless they are signing personally as an individual party.
- **Capacity** — the role or authority the signatory signs in. Found under "Title:" ("Director", "Chief Executive Officer", "Authorised Signatory", "General Partner"). Where an entity signs through another entity ("Northgate Holdings Limited, By: Northgate GP Limited, its General Partner, By: [name], Authorized Signatory"), the party is the top entity, the signatory is the human, and the capacity records the chain.

Rules:
- One page may hold several blocks. Read every block; return one record per block.
- Blank fields ("Name: ________") are `Unknown`, and the page is flagged for manual review, never guessed.
- Party names in any language count. Return them exactly as written, in block letters when producing the packs.
- The same human signing in two capacities (as CEO for the company, and personally as a key holder) is two blocks, two records, and under signatory grouping both land in that person's pack.

Worked examples:

| Text on page | Party | Signatory | Capacity |
|---|---|---|---|
| `By: [name] / Name: J. Smith / Title: Director, Company A` | COMPANY A | J. Smith | Director |
| `_______ / Party A` | PARTY A | Unknown | Unknown |
| `Company B / By: [name] / [name], as authorized signatory` | COMPANY B | [name] | Authorized Signatory |
| `Signed, ____ For Organization X / ____ For Entity Y` | ORGANIZATION X; ENTITY Y (two records) | Unknown; Unknown | Unknown |
| `_______ / Individual 1` | INDIVIDUAL 1 | Individual 1 | Personal |
| `_______ / For and on behalf of Entity Z` | ENTITY Z | Unknown | Unknown |

## Grouping and duplication

- **By agreement:** one pack per document; every signature page of that document, in page order.
- **By counterparty:** one pack per party; every page on which that party has a block, across all documents, ordered by document then page. Where one page carries blocks for two parties, **each party's pack gets its own copy of that page** (unless the user says no duplicates).
- **By signatory:** one pack per human; every page they sign, in whatever capacity, ordered by document then page.
- Copies: default one per page; a party may need to sign more than one original.
- Filenames: default `Signature Pack – [Group]`. Users often specify their own pattern; follow it exactly, including what to omit (document IDs, version suffixes).

## Returned pages (compile)

- A returned page usually carries a footer naming its agreement, sometimes its party. Read it, native text or OCR. When the footer names only the document, or nothing, read the block: the party name in caps or after "for and on behalf of", the capacity in brackets, the signatory under the line. Normalise dashes (– — - ~), quotes (’ '), and whitespace before matching; OCR mangles all three.
- Match on agreement + party. If the footer is missing or unreadable, read the block itself (party name, signatory name).
- A returned page that matches a target already filled by another returned page is a **duplicate**: place one, report the other.
- A returned page that matches nothing is **unmatched**: never force it; report it with what could be read. On real closings this is usually a page for a document that is not in the execution folder (a side letter, a fee letter) — say so, because the user may have simply not handed that document over.
- A signature page in an execution version with no returned page is **missing**; the gap list is the deliverable as much as the executed PDFs are.
- E-signature envelopes (DocuSign, Adobe Sign): the completed PDF often ends with a completion certificate and may open with an envelope cover; those pages are not signature pages. The file may be locked; unlock or flatten only if permitted, otherwise report it as needing manual handling.

## What "executed" means (compile)

A returned page is not executed because it came back. It is executed because the block is signed. Decide from the render, never from the text layer alone: ink, an e-signature stamp graphic, initials over the line, a struck-through block, a rotated scan are all invisible to text extraction.

Per block, from the render:
- **signed** — every required mark in the block is present (ink or e-signature stamp), and the printed names match the manifest, or the manifest names were unknown. A block can require several marks: two directors, a director and a secretary, a chop and a representative, or — on deeds — a signatory **and a witness**. Count the marks; a deed signed but unwitnessed, or one director of two, is **partial**, not signed. Say "signed", not "valid": the skill checks presence and printed name, never authenticity, authority or the person's actual hand.
- **partial** — this block is unsigned but another block on the same page is signed. Common on shared pages. Not placed unless the user says so; the report names the missing block.
- **blank** — the block is unsigned. Often an unsigned execution page returned by mistake, or the pack copy meant for someone else. Never placed.
- **unclear** — the render cannot be read with confidence: bad scan, cropped, upside down (rotate and look again first). Manual review.
- **wrong-version** — the page matches the document and party but its version marker (`12345678-v9`) differs from the execution version. A signed page from an earlier draft. Never placed.

Other things a returned bundle contains that are not signature pages: initialled body pages (some jurisdictions initial every page), e-signature completion certificates and envelope covers, fax headers, blank separator sheets. Skip them and say so.

**Printed name vs manifest.** If the block was `Name: ___` in the execution version and the returned page shows a handwritten or typed name, record it; that is new information, not a mismatch. If the manifest had a name and the returned page shows a different one, that is a mismatch: quarantine, do not place, report both names.

**Dating.** Pages come back undated by design; escrow means undated. Do not date unless instructed. When instructed, date by visible annotation over the date field, never by editing the scan; leave already-dated pages alone and record what they say.

## Placement convention

**Drafting vs marking — the boundary.** Drafting signature pages from the firm's approved template *before circulation* is ordinary lawyer work, gated by the lawyer twice (matrix confirmed; sample page approved). Adding anything to a page *after* the parties have agreed the version, or after signing, is never done. Same principle, two sides.

**Never mark the instrument.** Pack pages and returned signed pages are never stamped, tagged or annotated — a signed page must be page-identical to the execution version the parties agreed. Matching is done by reading, not by labelling.

Replace, page for page: each signed page sits exactly where its unsigned page was, and schedules and exhibits after the signature block stay where they are. One exception, from how counterparts work: a page shared by two or more parties, where each party returns its own signed sheet, is placed as ALL of those sheets, one after another in block order — a counterpart-executed page genuinely is several sheets, and none of them may be dropped. The executed page count grows by exactly those extra sheets; nothing else moves.

- Only pages whose blocks are all `signed` are placed. Spare originals (a second signed copy where `copies_required` is 1, or a duplicate return) go to `executed/spare-originals/`, never into the executed PDF.
- If a firm wants a separator sheet before e-signed pages in a mixed closing, `esig_separator` on the ledger line adds a labelled sheet; page count then grows by the number of separators, and the report says so.
- The ledger (`references/ledger_schema.md`) is the record: every page, every block, every return, and the receipt. It lives in the matter folder and is the memory across batches of returns.

## The ledger is the memory

Signed pages arrive over days. The pack half writes the ledger; each compile run reads it, places only what is new, updates statuses, recomputes the receipt. Nothing is reclassified, no pack is rebuilt. At any moment `status` says what is signed, what is missing, from whom, and whether the closing is complete.
