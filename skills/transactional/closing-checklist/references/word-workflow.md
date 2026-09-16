# Optional local Word workflow

`scripts/closing_checklist.py` uses Python's standard library only. It does not
perform legal extraction or call a model. Use paths relative to this skill's
directory, or resolve its actual installed location. Never require a particular
host command, connector or interpreter installation.

Create temporary JSON inside the user's workspace, with restricted access where
supported. Paths in JSON should be absolute local snapshot paths. Retain one
master source bundle; delete temporary matter data at completion. Helpers create
outputs exclusively: an existing path is an error, not permission to overwrite.

```sh
python3 scripts/closing_checklist.py prepare anchor.docx annex.md --out sources.json
python3 scripts/closing_checklist.py inspect latest-checklist.docx
python3 scripts/closing_checklist.py plan --spec spec.json --sources sources.json --out plan.json
python3 scripts/closing_checklist.py apply --plan plan.json --approval approval.json --out checklist-v2.docx
```

`prepare` supports readable DOCX/TXT/MD. For PDF or connector sources, use host
extraction to stage readable text and record the original document/version/page
mapping in the master dataset. An extraction warning means inspect the actual
document; neither the helper nor a clean extraction certifies source completeness.
Embedded images, tracked changes and missing annexes need explicit coverage review.

## Plan contract

Write a spec after substantive review. Every item/operation requires `id`,
`basis` (`document`, `practice`, `instruction`), `reason`, and `evidence`.
Document-based proposals require at least one exact quote:

```json
{"source_id":"S1","unit_id":"L4","quote":"The Seller shall deliver the share certificates."}
```

Source IDs/locators come from `prepare`, not invented citations. The helper checks
quote presence and source fingerprints, **not** whether a quote supports the
proposal, whether the agreement is legally current, or whether all items were found.

Creation spec (generic default layout):

```json
{
  "mode": "create",
  "title": "Project Example — Closing Checklist",
  "scope": ["Source: Share Purchase Agreement, Draft 3 dated 6 June 2026. Perspective: Buyer."],
  "parties": [
    {"label": "Seller", "name": "Example Holdings Limited", "role": "Seller", "group": "Principals"},
    {"label": "[Seller's counsel]", "name": "Not identified in the source", "role": "Seller's legal adviser", "group": "Advisers and service providers"}
  ],
  "status_key": [{"label": "Not confirmed", "meaning": "No status evidence in the sources"}],
  "footer": "Prepared based on draft Share Purchase Agreement (Draft 3) dated 6 June 2026",
  "headings": ["No.", "Source reference", "Item", "Responsibility", "Timing", "Status", "Notes"],
  "items": [{
    "id": "C1", "basis": "instruction", "reason": "Express lawyer instruction",
    "evidence": [], "phase": "Closing", "group": "Seller deliverables",
    "cells": ["1", "SPA cl. 5.1(a)", "Deliver agreed documents", "Seller", "At Completion", "Not confirmed", ""]
  }]
}
```

`scope`, `parties`, `status_key` and `footer` are optional opening sections and
the every-page footer; `group` is an optional lighter sub-heading within a phase.
The helper writes the title, scope lines, a Parties table (grouped when any
entry has `group`), a Status key table, a "Checklist" heading and the table, in
that order, with page numbers in the footer. It accepts five to eight columns
and sizes them by heading meaning (Item widest, No. narrowest). Template mode
ignores these keys because the template supplies its own opening content.

An explicitly approved reusable template can replace the generic style: add
`template` (path) and `layout` with zero-based `table`, `item_row`, `phase_row`,
`body_start`. The selected table body from `body_start` onwards is replaced;
all other content remains. Inspect the whole template for old matter content
before choosing this mode. Header rows remain; the phase prototype must span
the full grid. Each record must supply every column in the template's order.

Revision spec: `mode: "revise"`, `baseline` path and `operations`. Each operation
also contains zero-based `table`, original `row`, `before` (every original cell's
exact inspected text) and one of:

- `kind: "update"`, `values: {"1": "Approved new item wording"}`. Only named
  cells change; combine all approved changes to one row in one operation.
- `kind: "remove"`. Requires explicit approval of this row's removal.
- `kind: "add_after"`, `prototype_row` (plain item style), `values` (all cells).
  The anchor may be a merged phase row. For several adjacent additions, use a
  host editor or separately reviewed plans; do not reuse the same anchor in a plan.

Indices refer to the original snapshot throughout the plan. New phases or complex
numbering/merges may require host editing; propose the structural changes first.

`plan` binds the spec, source bundle and baseline/template fingerprints to a digest.
After the user approves the displayed proposals, record:

```json
{"plan_sha256":"<printed digest>","approved_ids":["C1"],"user_instruction":"<actual approval from this conversation>"}
```

This record is an agent-maintained audit aid, **not cryptographic proof of human
consent**. Never fabricate it or treat a successful hash check as approval. Changed
sources/checklists require a new review. Applying to a previously amended baseline
fails closed; repeated application to the original creates the same content, not
another layer of changes. Always reconcile against the latest Word file first.

Rejecting a create-mode proposal must not leave the checklist numbered 1, 3. When
the generic layout's first column is headed "No." and every approved item's first
cell is a plain number, the helper re-sequences that column across the approved
items only. A manual scheme such as `1a`, a blank, or a first column that is not
the number is written exactly as supplied. Template mode writes every cell
verbatim because the template's column meanings are not known: number the items
for the approved set, or renumber in the host editor. Check the saved numbering
in the two-way coverage check either way.

## Supported editing and fallbacks

The helper preserves untouched package parts byte-for-byte and untouched document
nodes semantically. Edited text cells retain their cell properties and first
paragraph/run formatting, not arbitrary mixed inline styles. It supports plain
item rows and full-width merged phase and sub-heading rows. In revision mode the
checklist table's zero-based index counts any opening legend tables, so use
`inspect` to find it. It refuses tracked/dynamic content,
extension namespace declarations, digital signatures, protection, nested item
tables and vertical merges. These are disclosed helper limits, not permission to
flatten the document. Use a capable host Word editor, preserving the same approval
and verification contract, or report the specific unmet requirement.

For a helper-created generic checklist only, after confirming the Notes column
is entirely internal and a generic external layout is acceptable (zero-based
column index; 6 for the default seven-column layout, 5 for the earlier
six-column layout):

```sh
python3 scripts/closing_checklist.py external checklist.docx --notes-column 6 --out checklist-external.docx
```

The checklist is the last table; opening legend tables are carried across as
plain text. The helper refuses a column whose heading does not read as notes,
rebuilds a minimal package with the public content and footer, and refuses
ancillary parts and unfamiliar content instead of claiming arbitrary Word
sanitisation. Page-number fields in the footer are the only field codes the
helper writes or edits.
House-style external copies require host editing and package-level inspection.
Even a successful helper check cannot identify all confidential facts in public
cells: review the saved external file and its package before calling it ready
for circulation. Do not send it. Render both internal and external versions and
inspect every page; report any unperformed visual or confidentiality check.
