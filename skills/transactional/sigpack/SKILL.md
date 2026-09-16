---
name: sigpack
description: >-
  Use for wet-ink and mixed closings on a folder of execution PDFs: find every
  signature page, read who signs (party, signatory, capacity), open the matter
  ledger, build the signature packs by agreement, counterparty or signatory with
  the instructions table and cover note; then, as signed pages come back over
  days as scans, native PDFs or e-signature envelopes, look at each one, place
  only the signed ones back where their unsigned page was, and keep the receipt
  that says what is signed, blank, missing or unmatched until the closing is
  complete. Trigger on "signature packs", "sig pages", "signing bundle",
  "compile the executed versions", "insert the signed pages back", "what's
  still outstanding".
argument-hint: "draft | extract [by agreement|party|signatory] | compile"
---

# Sigpack

## When to use
- Prepare signature packs from a closing set: the pages each party or person has to sign, sorted the way the deal needs, with the signing instructions and cover note.
- Take signed pages back as they arrive, in batches, and keep the executed set and the receipt current without redoing anything.
- Date the executed pages on instruction at closing.
- Not for running the e-signature process itself, drafting or checking signature blocks, or deciding who has authority to sign. It checks that a block is signed and by the printed name; it never vouches for a signature.
- Know the cost before you start: every returned page is looked at as a rendered image before anything is compiled. That is what makes the executed PDF honest, and it takes attention proportional to the number of pages. Where the host offers parallel workers, the pages are farmed out in batches and it takes minutes; without them it is sequential. A user who wants "just merge them" is asking for a different, less safe tool; say so once, then do it properly.

## Modes
The skill takes arguments: `/sigpack [mode] [flags]`. Three modes, one ledger. Never force a user upstream of where they are.

| Invocation | What runs |
|---|---|
| `/sigpack draft` | nothing exists yet: extract the signing matrix from the documents, fill the firm's signature-page template, circulate. The ledger opens *declared*. |
| `/sigpack extract [by agreement\|party\|signatory]` | signature pages already drafted (most users' first touch, and the fastest aha): scan, classify, build packs — the pack workflow below. The ledger opens *discovered*. |
| `/sigpack compile` | signed pages are back and there is no ledger: run scan + classification on the execution versions first, then compile. Same receipt either way. |

Parsing the arguments:
- Mode words: `draft`; `extract` (accept `pack` as a synonym); `compile`. Anything else after the mode is a flag or the folder to work on.
- Grouping flag on `extract`: `by agreement`, `by party` (the ledger's *counterparty* grouping), `by signatory` (accept `by signature`). Other flags in the same style: `copies 2`, `no duplicates`, a quoted filename pattern.
- Precedence: an explicit flag wins over the `[sigpack]` playbook default, which wins over asking. Only ask for what neither states.
- **No arguments is fine.** Route by what is in front of you — unsigned execution versions point at extract, a folder of returned scans at compile, no signature pages anywhere at draft — and confirm the door in one line before starting. Plain words in the request ("packs per counterparty, two copies") count as flags; nobody is made to learn the grammar.

## Before you start
- Read `references/signature_page_rules.md` in full: what a signature page is, why party, signatory and capacity are three things, what "executed" means per block, how returns are matched.
- Read `references/ledger_schema.md`: one `sigpack.ledger.json` per matter, in the closing folder. The pack half opens it, every batch of returns settles into it, and its receipt must balance. It is the memory across sessions.
- Read your `[sigpack]` lines in `lqplaybook.md` if present (default grouping, copies, duplicate rule, filename pattern, cover-note wording, separator, executed-file naming). Read nothing else from the profile; write nothing to it. Propose a `[sigpack]` line when the user states a preference; write it only on an explicit yes.
- Client-identifying facts belong in the packs, the executed PDFs and the matter ledger only. Never in the profile, never in a repository.

## Workflow — draft (declared start)

1. **Extract the signing matrix.** Read each execution version's parties clause and execution language; propose per document, per party: capacity chain, signatory if known, required marks (a deed needs a witness), copies. Write it as `matrix.json` (same shape as `classified.json`, `signatures[]` per block). **Gate: show the lawyer the matrix table and confirm before drafting.**
2. **Load the firm's template** from the `[sigpack]` playbook (`template: <path>`) or ask once — a docx with `{{DOC_TITLE}}`, `{{PARTY}}`, `{{SIGNATORY}}`, `{{TITLE}}` placeholders.
3. **Draft.**
   ```
   python3 scripts/sigpack.py draft --matrix matrix.json --template <sigpage.docx> --out-dir drafted/ --execution <closing-folder>
   ```
   One page per party per document, rendered through the bundled LibreOffice, footer authored by us. **Gate: render a sample and show the lawyer before circulating.** Drafting happens before circulation and is the lawyer's to approve; nothing is ever added to a page after agreement or signing (document-integrity rule).
4. **Open the ledger from the declared classification** (`drafted/declared-classified.json`) with `init`, then continue with the pack workflow at step 4 (grouping) — packs, instructions, cover note, and later compile, all unchanged. Drafted pages match returns reliably because we authored their footers.

## Workflow — pack

0. **Convert Word inputs first, if any.**
   ```
   python3 scripts/sigpack.py convert <folder-with-docx> --out-dir <execution-folder>
   ```
   Uses the host's bundled LibreOffice (`soffice --headless`), the same way the host's own document skill renders Word files: a per-run profile, and success only when a non-empty PDF exists, never on quiet stderr. If `soffice` is missing the command stops and says so; ask for PDFs rather than proceeding as if converted. Execution PDFs are the working set from here on.

1. **Scan for candidates.**
   ```
   python3 scripts/sigpack.py scan <execution-folder> --out tmp/sigpack/candidates.json --ocr
   ```
   Every page with signature-block markers or a signature-page footer is a candidate. It over-includes on purpose; the script never decides.

2. **Read every candidate and decide, with the whole document in view.** Do it in parallel where the host allows it — this is the larger attention bill of the two halves: `scan <folder> --out ... --triage-dir ... --emit-batches 12 --batch-dir tmp/sigpack/scan-batches` groups **whole documents** per worker file (a candidate is judged with its document's name, cover page and exhibit context, so a document is never split); hand one file to each parallel worker with `references/signature_page_rules.md`, collect the filled files, then `assemble --batches <folder> --execution <folder> --out tmp/sigpack/classified.json` — it refuses while any candidate is unanswered. The contact sheets stay with you either way: look at every sheet, zoom the unsure cells. If the host has no parallel workers, work through the candidates yourself: render each (`pdftoppm -png -r 80 -f N -l N`) and look at it beside its text. Is it a signature page? Exhibit bundles and Schedules carry form execution pages that look real and are not; the file name and cover page tell you. If yes: one record per block with party, signatory, capacity, and `copies_required` when a party must sign more than one original. Mark spare blank pages `reserved`, and pages that need a separator sheet before them `esig_separator`. Blank fields are `Unknown` and the page is flagged. Write `tmp/sigpack/classified.json`:
   ```json
   {"signature_pages": [
     {"file": "(Final) Voting_Agreement.pdf", "page": 9, "agreement": "Voting Agreement",
      "blocks": [{"party": "Northgate Holdings Limited", "signatory": "A. Signatory", "capacity": "Authorized Signatory of Northgate GP Limited, its General Partner", "copies_required": 1}]}
   ]}
   ```
   Show the user the table (document, page, party, signatory, capacity, copies) and confirm. Say how many candidates you rejected and why in one line.

3. **Open the ledger.**
   ```
   python3 scripts/sigpack.py init --ledger sigpack.ledger.json --execution <execution-folder> --classified tmp/sigpack/classified.json --matter "<name>"
   ```
   Every signature page gets a stable id (`SLA-p19`); every block starts `required`. If a ledger already exists for this matter, do not init again — go to step 5 or to the compile workflow.

4. **Settle the build options** in precedence order — invocation flags, then `[sigpack]` playbook defaults, then ask for whatever is still open: grouping (agreement / counterparty / signatory), copies (default one, or per block from step 2), whether a page shared by two parties goes into each pack (default yes), the filename pattern (default `Signature Pack – [Group]`; follow the user's exactly, including what to omit).

5. **Build the packs.**
   ```
   python3 scripts/sigpack.py build --ledger sigpack.ledger.json --group counterparty --out-dir packs/ [--copies N] [--no-duplicate] [--name "Signature Pack – {group}"]
   ```
   One PDF per group, pages ordered by document then page, `copies_required` honoured. Pack pages are exact copies of the execution pages — the skill never writes anything onto a page that will be signed. Blocks move to `sent`; `packs_sent` is recorded. `instructions.json` is the table.

6. **Write the instructions and the cover note.** Render `instructions.json` as a table: party, document, sign as (capacity), by (signatory), copies. Then the cover note, from the playbook or the default: the packs attached and the copies to sign; return by [date]; signed pages held in escrow, undated, and released only on the user's instruction once the documents are in execution form; the user will be asked before release. The escrow line ships by default; a firm overrides it in the playbook.

7. **Present.** Headline (N packs by [grouping], M pages, K flagged), the instructions table, the cover note, the packs, and the receipt line from `status`.

## Workflow — compile (repeat for every batch of returns)

1. **Register the batch.**
   ```
   python3 scripts/sigpack.py read --ledger sigpack.ledger.json --returned <returned-folder> --ocr --render-dir tmp/sigpack/renders
   ```
   Every returned page is registered once with its footer (native or OCR), version marker, e-signature flag, and a render. Locked envelopes are reported, not forced. Pages already registered are skipped, so re-running on the same folder is safe.

2. **Look at every returned page. This is the step that makes the executed PDF honest.** Do it in parallel where the host allows it: `read --emit-batches 10 --batch-dir tmp/sigpack/batches` writes worker-ready files, each a list of pages with their render path and the fields to fill; hand one file to each parallel worker with `references/signature_page_rules.md`, collect the filled files, then `merge --verdicts <folder>`. If the host has no parallel workers, work through the batch files yourself, one page at a time, same fields, same rules. Either way, for each page open its render and fill, in the ledger entry:
   - `agreement` and `party` if the footer did not give them (English-law footers name only the document; read the block: party in caps or after "for and on behalf of", capacity, printed name).
   - `execution`: `signed` (every required mark present — count them on multi-signature and deed blocks, a witness line is a required mark; printed names match the manifest or the manifest had none; record `signatures_present` when the block requires more than one), `partial` (this block unsigned while another block on the page is signed), `blank` (unsigned), `unclear` (unreadable, rotated, cropped — rotate and look again first), `not-a-signature-page` (initialled body page, completion certificate, envelope cover, fax header).
   - `printed_name` as it appears; `dated` if the page already carries a date.
   Compile refuses to run while any page is `unknown`. Never guess: a page you cannot place goes through as unmatched and is reported.

3. **Compile.**
   Before the first compile of a batch, run it with `--dry-run`: it writes only `compile-plan.json`, lists which returned sheet would replace which page and how each would be dated, and changes nothing. Show the lawyer that plan; compile once they agree.
   ```
   python3 scripts/sigpack.py compile --ledger sigpack.ledger.json --out-dir executed/ [--date "29 May 2025"] [--separator] [--place-partial]
   ```
   Matches each new return to a signature-page block by agreement and party (signatory fallback), quarantines version mismatches, places `signed` blocks only — replace, page for page; a page executed in counterparts is placed as all its signed sheets in block order, so the count grows by exactly those sheets — files extra signed copies to `executed/spare-originals/`, records every return on its block, recomputes the receipt. Idempotent: run it after every batch; nothing is re-placed. `--date` writes the date as a visible annotation on pages that have a date field and are not already dated. `--separator` inserts a labelled sheet before pages marked `esig_separator`. `--place-partial` places pages where at least one block is signed; off by default.

4. **Look before delivering.** For each executed PDF, render the signature pages and confirm the signed page sits where the unsigned one was and belongs to that document. Any blank, partial, unclear, wrong-version or unmatched return: render it, say what it is and where it came from. Unmatched returns are usually documents that were never handed over — say so.

5. **Present.** If anything moved since the last batch, that line first (`compile` prints it; `status --since` shows it any time, `status --since <batch folder>` since a named batch). Then the receipt line (the same numbers head `closing-checklist.md`, which every compile writes beside the executed PDFs: parties down the side, documents across, one mark per block). If anything is outstanding, run `python3 scripts/sigpack.py chase --ledger sigpack.ledger.json --out-dir chasers/` and hand the lawyer the per-party facts it writes; they choose the words and send from their own mail. The skill never sends anything. The receipt line: *N pages / M blocks required · signed · partial · blank · unclear · wrong-version · missing · unmatched · spare originals · COMPLETE or NOT COMPLETE*. Then the missing list per document and party, then the executed PDFs. `python3 scripts/sigpack.py status --ledger sigpack.ledger.json` prints it any time.

## Output conventions
- Ledger: `sigpack.ledger.json` in the closing folder, next to the execution versions. It stays with the matter.
- Every output stays inside the ledger's folder (or the current folder for `scan`, `convert`, `draft`, `assemble`). The script refuses any `--out-dir`, `--out`, `--render-dir`, `--triage-dir` or `--batch-dir` that resolves elsewhere, symlinks included, unless the user passes `--allow-outside` for that run. Inputs may be read from anywhere; a symlinked PDF pointing outside its folder is skipped and named.
- Intermediate files under `tmp/sigpack/`; delete when done. Renders can go too once every page has been looked at.
- Packs beside the input as `Signature Pack – [Group].pdf` unless the user names them; executed PDFs as `(Executed) <name>.pdf`; spare signed originals under `executed/spare-originals/`.
- `packs.json`, `instructions.json`, and `compile-report.json` stay with the outputs.

## Capability fallback

The bundled script requires `pypdf`. Scanned-page processing and rendering use Poppler and `tesseract` when available; Word conversion uses LibreOffice. Probe those capabilities before reading client material. Do not assume they are installed, and do not ask to install packages inside a hosted task.

If the script cannot run, use host-native PDF and document capabilities while preserving the same ledger, classification, page-by-page visual review, matching, and receipt rules. Without a way to render every candidate and returned page, say plainly that the visual-review gate cannot run and do not compile an executed set. If Word conversion is unavailable, ask for PDFs rather than treating the documents as converted.

## Final checks
- Every candidate page was looked at with the document in view; the rejected count was stated.
- The classification was shown and confirmed before the ledger was opened.
- Every returned page in the batch was looked at; none is `unknown`; none was guessed.
- The receipt was shown, even when complete; the missing list names parties.
- Executed PDFs have the same page count as their execution versions (plus separators, if any); spare originals are filed, not lost.
- The ledger was left in the closing folder.

## Scripts
- `scripts/sigpack.py` — `convert`, `scan` (with `--emit-batches` for parallel classification, whole documents per worker), `assemble`, `init`, `build`, `read` (with `--emit-batches` for parallel workers), `merge`, `compile`, `status`. Runs on `pypdf`; Poppler for text and renders; tesseract for OCR and the bundled LibreOffice for docx when present.
- `references/signature_page_rules.md` — classification, execution, matching, dating rules.
- `references/ledger_schema.md` — the matter ledger.
