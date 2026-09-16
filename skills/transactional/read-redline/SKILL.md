---
name: read-redline
description: >-
  Use when a counterparty sends a redline, blackline, or compare PDF, or a
  Word file with tracked changes, and you need every change, what matters,
  and a marked-up copy to hand back. Extract PDF changes with the bundled
  calibrated parser (`pdfplumber`) or Word changes from their tracked-change
  tags (standard library), render PDF pages with
  Poppler and look to confirm nothing was missed, rate each change with the
  significance rubric, and create a separately named annotated copy (`pypdf`) with
  tier-coloured highlights and plain-English comments without modifying the source. Trigger on "what changed
  in the new version" or "mark up this compare" even without the word redline.
---

# Read Redline

## When to use
- Review a pre-made redline, blackline, or compare PDF (strikethrough = deleted; underline or colour = inserted), or a Word file with tracked changes (the usual internal form; every change is a tag with an author and a date).
- Rate every change High/Medium/Low and explain the consequence, not the diff.
- Hand back the same PDF, annotated, so the reader triages the document itself. For a Word file the issues list is the deliverable; an annotated copy is written only when asked. Comparing two clean documents is out of scope.

## Before you start
- Read `references/significance_rubric.md` in full. It is short.
- Read your `[redline]` lines in `lqplaybook.md` if the file exists (comment voice, tier overrides) and apply them over the rubric. Read nothing else from the playbook and nothing from `lqprofile.md`; neither shapes the work product beyond those lines. Write to neither; the scribe owns both. One exception: when the user overrides a tier or rejects a comment voice in-session, propose the exact `[redline]` line and write it only on an explicit yes.
- Client-identifying facts belong only in the work product: the annotated copy, the issues list, and the three JSON files that build them. Never put them in a proposed `[redline]` line or anywhere else.

## Workflow

1. **Inspect the file.** A `.docx` takes the Word path below; the PDF steps 2, 4 and 5 do not apply to it. For a PDF, run `pdfinfo`: page count, producer, title. If the last page is a compare-tool summary (Litera and others print totals: insertions, deletions, moves, table changes), keep those numbers for step 5 and pass `--body-end-page <index of last body page>` so the summary is not read as body text (`--body-start-page` likewise skips cover pages).

2. **Calibrate before extracting. Always.**
   ```
   python3 scripts/parse_redline_pdf.py <redline.pdf> --calibrate-only
   ```
   Show the user the colour-to-role table (which colour means deleted, which inserted, what was excluded as headers, watermarks or numbering) and confirm it matches what they see. A wrong role silently inverts every change. Two things to look for in the report:
   - `REVISION -> MIXED` means one colour carries both strikethrough and underline. This is handled: the parser assigns role below word level by decoration, splitting per character where deleted and inserted text touch. Confirm the MIXED reading and move on.
   - A colour showing **both** strikes and underlines while the del and ins colours each show one is usually *moved* text. Confirm with the user, then re-run with `--moved-color <int>` (the integer in the report) so the passage is reported as a move, not a change at both ends.
   - `COLOURED, NO MARKS -> not counted` is text in a colour that is never struck or underlined anywhere in the document: coloured headings, a house style, a cover note. Colour alone is never a change, so the parser does not count it. Tell the user in one line what it was and that it was left out. Only if they say the compare tool marks block insertions or deletions by colour alone, re-run with `--insert-color <int>` or `--delete-color <int>`.

   **Record the gate.** A confirmed calibration is an artifact, not a memory: after extraction (step 3), write `calibration.confirmed.json` beside `extract.json` (command in step 3). It carries the calibration block, a status, and the extract.json content hash it confirms. A bare 'continue' is not approval — write `confirmed` only after the user has actually confirmed the table. In a scripted, non-interactive run there is no one to confirm; the sanctioned path is `declared-default` with an explicit `--reason` saying why, and the reason is required. Both annotators and the issues list refuse to build without a valid artifact that matches the current extract, and their receipts record the gate state.

3. **Extract.**
   ```
   python3 scripts/parse_redline_pdf.py <redline.pdf> extract.json
   ```
   Then record the calibration gate the user confirmed in step 2:
   ```
   python3 scripts/calibration_gate.py extract.json --status confirmed
   ```
   or, in a scripted non-interactive run only, `--status declared-default --reason "<why no human confirmed>"`.
   `pairs` are the `{old_text, new_text}` changes with a `pair_id` and geometry. `quarantined` lists paragraphs the parser could not reconstruct reliably; they are excluded from `pairs`. Tell the user which pages they are on. Never present the extraction as complete when the quarantine list is non-empty. Moved passages (from `--moved-color` or a compare tool's "Moved from" / "Moved to" labels) are listed under `move_annotations`; they are not changes.

4. **Render and look.** Prefer visual review. Run `pdftoppm -png -r 110` on every page that has changed pairs plus a sample of the rest; render every page when calibration was MIXED, when anything was quarantined, or when the extraction found no changes at all. Open each PNG and compare what you see against that page's pairs in `extract.json`. Every visible mark (strikethrough, underline, coloured text that is struck or underlined, margin balloon, moved-text marker) that has no matching pair becomes a manual-review item. Coloured text with no strike and no underline is not a mark; it was reported at calibration and is not a change unless the user said so. Never explain a mark away. Append each one to `extract.json` under `quarantined`:
   ```json
   {"page": 3, "reason": "visible-mark-not-extracted", "raw_text_preview": "what the mark shows, in your words", "page_bbox": [x0, top, x1, bottom]}
   ```
   Approximate `page_bbox` from the render is fine (0-indexed page, top-down PDF points, 110 dpi means divide pixel coordinates by 110/72). The annotator stamps these as manual-review sticky notes in step 8. Appending to `extract.json` changes its hash, so afterwards re-run the step-3 `calibration_gate.py` command with the same status to re-stamp the gate.

5. **Reconcile counts.** State the number of changed pairs beside the summary-page totals from step 1, if any, and explain the gap in one sentence (one pair can cover several summary changes; a table change may be one summary line and no pair). A large unexplained gap means render every page and look again.

6. **Rate and write the rows.** Group pairs that edit one provision into one row. For each row write `{provision, source_pair_ids, comment, materiality}`: a short label, the `pair_id`s it covers, a one-to-two sentence comment on what changed and why it matters in the rubric's voice, and High, Medium or Low per the rubric. Add an optional `direction` — `favours-us`, `favours-them`, `neutral` or `unknown` — per the rubric's direction heuristic; it is orthogonal to the tier and omitted rows render exactly as before. When unsure, a Low row rather than no row. Save as `rows.json` (a JSON list). The keys `provision` and `materiality` are what the skill calls the change's label and significance; use them exactly.

7. **Group into themes.** Rows answer "what changed in this clause"; the reader's question is "what is the other side doing." Two passes over `rows.json` (never re-analyse; rows stay the grounded unit):
   - *Housekeeping bucket.* A row is housekeeping if its change is ONLY renumbering, cross-reference updates caused by renumbering, TOC/pagination shifts, draft-date mechanics, or defined-term tidy-ups with no change in legal effect. When in doubt, not housekeeping.
   - *Themes.* Cluster the rest into 5–15 themes. Each theme: a 2–6 word label and a 1–2 sentence summary that states DIRECTION — what the party proposing the changes is doing ("tightening the merger covenant"), never a generic label ("various definition changes"). Merge across provisions when the same intent appears in scattered clauses; that merging is the point. A row may appear in up to two themes. No single-row themes unless the row is genuinely standalone; more than two of those means under-merging. Rows that fit no theme go in `unclustered` with a one-line reason — never force a fit.
   Save as `themes.json`:
   ```json
   {"themes": [{"label": "", "summary": "", "row_refs": [0]}],
    "housekeeping": {"count": 0, "row_refs": []},
    "unclustered": [{"row_ref": 0, "why": ""}],
    "coverage": {"rows_total": 0, "rows_themed": 0, "rows_housekeeping": 0, "rows_unclustered": 0}}
   ```
   `row_refs` are 0-based indexes into `rows.json`. The receipt is hard: every row appears exactly once across themes (counting multi-theme rows once), housekeeping, and unclustered, and the three coverage counts sum to `rows_total`. Count before writing.

8. **Annotate the same PDF.**
   ```
   python3 scripts/annotate_pdf.py <redline.pdf> --pairs extract.json --rows rows.json --out "<name> - Annotated.pdf"
   ```
   The script highlights each row in its tier colour, attaches the comment as a PDF annotation readable in the Comments pane, stamps every quarantine entry as a distinct manual-review sticky, then re-opens the file and fails loudly if the page count changed or any annotation did not survive. Report any rows it lists as **unplaceable**; those are analysed but not marked, and the user must know.

9. **Present.** Lead with the themes: label plus one-line direction each, then the housekeeping line ("N housekeeping provisions — renumbering and pagination, nothing to negotiate"), then any standalone rows. Then the receipt line: pages rendered and looked at, marks seen, marks matched to pairs, manual-review items, summary-page total if any, theme coverage (themed + housekeeping + standalone = total rows). Deliver two artifacts: the annotated PDF (the full record — every mark in place) and, when the user wants a take-away, the issues list:
   ```
   python3 scripts/make_issues_list.py extract.json rows.json themes.json "<name> - Issues List.docx"
   ```
   a Word table grouped by theme: provision and tier (with the row's direction beside it when present), the redline itself (struck deletions, underlined insertions), and the comment. Each row also carries its first pair's location — page for a PDF run, paragraph for a Word run; the list stays grouped by theme, and the annotated PDF remains the document-order view. The closing receipt records the calibration gate state (confirmed, or declared default with its reason). It is the briefing document, deliberately summary-level; the annotated PDF stays the complete record. The source PDF is never modified.

## The Word path (tracked changes)

Word records every change as a tag with an author and a date, so nothing is inferred from colour and there is no calibration.

1. **Report before extracting.**
   ```
   python3 scripts/parse_redline_docx.py <redline.docx> --calibrate-only
   ```
   Show the user the counts by kind and by author, the moved passages, and the formatting-only count. Confirm the authors are who they expect. If the report says **no tracked changes found**, stop: the changes were accepted before saving or the file is a clean draft, and there is nothing to review. Say so; do not compare it against anything.
2. **Extract.**
   ```
   python3 scripts/parse_redline_docx.py <redline.docx> extract.json
   ```
   Same `pairs` shape as the PDF path, with `paragraph` in place of page geometry, each pair's `revisions` (kind, author, date, text), and the document's existing `comments` anchored to their paragraphs. Moved passages are `move_annotations`, not changes. A formatting-only change is not a change. Then record the calibration gate exactly as in PDF step 3 — the step-1 report the user confirmed is the calibration the artifact carries:
   ```
   python3 scripts/calibration_gate.py extract.json --status confirmed
   ```
3. **Read and look.** There are no pages to render. Read every changed pair and the existing comments; a counterparty's own comment often says why a change was made and belongs in the row's comment.
4. **Rate, group, present** exactly as steps 6, 7 and 9 above. The issues list gains nothing by colour; it already shows old and new text. Where the author matters ("the other side's counsel deleted", "our associate inserted"), say so in the comment, since the extraction records it.
5. **Annotated copy, on request only.** The Word file is the lawyer's working document, so the default is to leave it alone and hand over the issues list. If they ask for the marks in the document:
   ```
   python3 scripts/annotate_docx.py <redline.docx> --pairs extract.json --rows rows.json --out "<name> - Annotated.docx"
   ```
   One Word comment per row, anchored on the row's first paragraph, authored **LegalQuants**, reading `[Tier] Provision — comment` (prefixed with the direction when the row carries one: `[favours-them · Tier] Provision — comment`). No shading, no colour, the lawyer's tracked changes and comments untouched. Tell them the whole layer filters or deletes by reviewer in one action. The source file is never written.

## Output conventions
- `extract.json`, `calibration.confirmed.json`, `rows.json` and `themes.json` are the intermediates. Keep them under `tmp/redline/` and delete them after step 9 has written the deliverables.
- The annotated copy and the issues list go beside the input as `<name> - Annotated.pdf` (or `.docx`) / `<name> - Issues List.docx`.
- Keep the `rows.json` and `themes.json` schemas exact.

## Validating across many PDFs
`python3 scripts/batch_review.py <folder>` runs calibrate → extract → smoke-annotate over every PDF in a folder, warns on zero changes, quarantines and likely moved colours, and writes `report.json`. It checks geometry, not judgment.

## Capability fallback

The bundled scripts require `pdfplumber`, `pypdf`, `python-docx`, and Poppler. Probe those capabilities before reading the client document. Do not assume they are installed, and do not ask to install packages inside a hosted task.

If the scripts cannot run, use host-native PDF reading, rendering, and annotation capabilities to preserve the same calibration, extraction, visual reconciliation, quarantine, rating, and coverage rules. If the host cannot render pages, say plainly that visual reconciliation did not run and the completeness receipt is unavailable. If it cannot write PDF annotations, deliver the grounded issues list and state that the annotated-PDF artifact could not be produced; do not silently claim the normal output contract was completed.

## Final checks
- PDF path: calibration was shown to the user and confirmed before extraction.
- `calibration.confirmed.json` exists beside `extract.json`, matches the current extract, and carries `confirmed` or `declared-default` with its reason — the annotators and issues list refuse to run without it.
- PDF path: every rendered page was looked at, not just generated.
- Word path: the tracked-change report (counts by kind and by author) was shown to the user and the authors confirmed.
- Word path: every changed pair and every existing comment was read.
- The manual-review list is shown to the user even when empty.
- No change was dropped because it was hard to classify.
- Theme coverage adds up: themed + housekeeping + standalone = total rows.
- PDF path: the annotated PDF opened with the same page count and its comments appear in the Comments pane.

## Scripts
- `scripts/parse_redline_pdf.py` — calibrate and extract. Flags: `--calibrate-only`, `--body-start-page N`, `--body-end-page N`, `--note-pattern REGEX`, `--moved-color INT`, `--insert-color INT`, `--delete-color INT` (all repeatable). Runs on `pdfplumber`.
- `scripts/calibration_gate.py` — record the calibration gate: writes `calibration.confirmed.json` beside extract.json. Flags: `--status confirmed|declared-default`, `--reason` (required for declared-default). Standard library only.
- `scripts/parse_redline_docx.py` — the Word path: report (`--calibrate-only`) and extract from tracked-change tags. Standard library only.
- `scripts/annotate_docx.py` — on request: the review as Word comments by LegalQuants in a separately named copy. Standard library only.
- `scripts/annotate_pdf.py` — highlight, comment, stamp quarantines, verify. Flags: `--pairs`, `--rows`, `--out`, `--dry-run`, `--check-contract`. Runs on `pypdf`.
- `scripts/make_issues_list.py` — build the theme-grouped Word issues list from extract.json + rows.json + themes.json. Runs on `python-docx`.
- `scripts/batch_review.py` — fleet check over a folder.
