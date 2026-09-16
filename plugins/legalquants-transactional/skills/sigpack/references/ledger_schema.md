# The matter ledger — `sigpack.ledger.json`

One file per closing, kept in the closing folder beside the execution versions. Every signature page is a line item; the ledger must balance. The pack half opens it, the compile half settles it, and it survives across sessions and batches of returns.

The `signature_pages` array is the **manifest** — the declared list of what must be signed. Everything else is what happened to each item over time. The `receipt` is the balance.

## Shape

```json
{
  "matter": "Project Aurora (fictional)",
  "created": "2026-08-18",
  "closing_date": null,
  "execution_dir": "execution/",
  "returned_dirs": ["returned/2026-08-15/", "returned/2026-08-18/"],
  "signature_pages": [
    {
      "id": "VA-p9",
      "file": "(Final) Voting_Agreement.pdf",
      "page": 19,
      "agreement": "Voting Agreement",
      "footer": "Signature Page – Voting Agreement – Northgate Holdings Limited",
      "version_marker": "(none printed)",
      "reserved": false,
      "esig_separator": false,
      "blocks": [
        {
          "block": 1,
          "party": "NORTHGATE HOLDINGS LIMITED",
          "signatory": "A. Signatory",
          "capacity": "Authorized Signatory of Northgate GP Limited, its General Partner",
          "date_field": true,
          "copies_required": 1,
          "status": "signed",
          "returned": [
            {"pack": "(Signed) Signature Pack - A. Signatory.pdf", "page": 7, "batch": "returned/2026-08-15/",
             "execution": "signed", "printed_name_matches": true, "dated": null,
             "chosen": true, "placed_in": "(Executed) Voting Agreement.pdf#19", "spare": false}
          ]
        }
      ]
    }
  ],
  "packs_sent": [
    {"group_by": "counterparty", "group": "EASTBRIDGE CAPITAL", "file": "Signature Pack – EASTBRIDGE CAPITAL.pdf",
     "sent": "2026-08-12", "pages": ["SPA-p13", "VA-p10", "IRA-p16"], "copies": 1}
  ],
  "unmatched_returns": [
    {"pack": "(Signed) Signature Pack - A. Signatory.pdf", "page": 3, "batch": "returned/2026-08-15/",
     "read_as": {"agreement": "Side Letter (not in execution set)", "party": "NORTHGATE HOLDINGS LIMITED"},
     "reason": "document not in execution set"}
  ],
  "receipt": {
    "pages_required": 27, "blocks_required": 27,
    "blocks_signed": 21, "blocks_partial": 0, "blocks_blank": 0, "blocks_unclear": 0, "blocks_missing": 6,
    "spare_originals": 0, "unmatched_returns": 2, "reserved_unassigned": 0,
    "complete": false, "as_of": "2026-08-18"
  }
}
```

## Fields that carry judgment

- **`id`** — stable and human-readable: a short document code plus page (`VA-p9`). Every report, filename, and conversation refers to it. Never renumber.
- **`blocks[]`** — one per signature block on the page. Status lives on the block, not the page, because a two-party page can be half signed.
- **Document integrity rule:** nothing is ever written onto a page that a party will sign or has signed — no stamps, tags, watermarks or annotations on pack pages or returned pages. The parties agreed to the execution version; the executed document must be page-identical to it. The only marks the skill ever adds are on the *compiled output* at the lawyer's instruction (the dating annotation) and the quarantine stickies on the *annotated review copy*, never on the signed instrument itself.
- **`blocks[].signatures[]`** — one entry per required mark within the block: `{"name": "...", "capacity": "...", "role": "signatory"|"witness"}`. Most blocks have one; a company signing by two directors, a director-plus-secretary block, a chop plus representative, or a deed signed "acting by X in the presence of Y" have two or more. A block is `signed` only when **every** required mark is present on the returned page; one of two is `partial`. The legacy single `signatory`/`capacity` pair is kept and means a one-signature block.
- **`copies_required`** — how many originals this party must sign of this page. Default 1. When the user asks for two originals, or a party must sign for each counterparty, set it here; `build` duplicates the page in that party's pack and the instructions table shows the count.
- **`reserved`** — a spare blank signature page some firms put at the back for late parties. It is a signature page with no party assigned; it is excluded from `blocks_missing` until a party is assigned to it. Assign a party on the ledger and the page becomes live: it is built into packs, counts as required, and appears in the missing list until signed.
- **Chasers and the checklist** — `chase` writes one Markdown file per party with outstanding blocks (what is held, what is still needed and why in the ledger's words, which pack was sent when, a subject line) plus `index.json`; nothing is sent. `checklist` (and every real `compile`, as `closing-checklist.md`) renders parties × documents with one mark per block. Both are read-only on the ledger.
- **`checkpoints[]`** — snapshots of every block's status, the receipt and the return outcomes, one per `read` (labelled with the batch folder) and one per `compile` (labelled `compile`), capped at the last 50. `compile` reports `since_last` against the previous checkpoint and prints one line above the receipt when anything moved; `status --since [batch | label | YYYY-MM-DD]` prints the same without writing. Legacy ledgers gain their first checkpoint on the next read or compile.
- **`esig_separator`** — set on a page when the firm wants a labelled separator sheet before it in the compiled PDF (mixed wet-ink / e-signed closings). Placement option, not a signature page.
- **`version_marker`** — the document ID + version string from the footer (`12345678-v9`), when printed. A returned page whose marker differs from the execution version's is a **wrong-version** page and is quarantined, not placed.

## Block status lifecycle

```
required  →  sent  →  signed | partial | blank | unclear | wrong-version
```

- `required` — in the manifest, no pack built yet.
- `sent` — included in a pack that was built.
- `signed` — a returned page for this block was looked at and the block carries a signature (ink, e-signature stamp, or a signed-and-dated mark) and the printed name matches the manifest signatory (or is blank in the manifest).
- `partial` — the page is back but this block on it is unsigned while another block on the same page is signed.
- `blank` — the page is back and this block is unsigned. Not placed. Reported.
- `unclear` — the render could not be read with confidence (bad scan, rotated, cropped). Not placed. Manual review.
- `wrong-version` — matched by document and party but the version marker differs. Not placed. Reported.

A block that is `signed` is never downgraded by a later return. A wrong-version or name-mismatch return that arrives after the block was signed is recorded on the block with its `reason`, listed under `rejected` in `compile-report.json`, and printed as `REJECTED`; the chosen sheet and the executed page do not change. Every returned sheet carries a `sheet_hash` (its content streams and images); a sheet whose hash is already on any block is recorded as `duplicate_of` that return and listed under `duplicates`, never as a spare and never as a conflict.

Only `signed` blocks are placed into the executed PDF. A page is placed once all its blocks are `signed`; a page with a `partial` block is placed **only if the user says so**, and the report says which block is missing. A page whose signed sheets are being held back is named in the receipt as `HELD`, with the waiting parties.

Two fields, two facts. `chosen: true` means *this is the return picked for this block* — written when the return is matched. `placed_in` means *this return is on disk at this address* — written only by the writer, on the run that actually writes the page, as the real output filename and output page index (separator sheets included). Stale `placed_in` values are cleared before every writer run; the ledger never claims a placement that did not happen.

A page executed in **counterparts** — two or more parties' blocks on one page, each party returning its own signed sheet — is genuinely several sheets, and all of them belong in the binder: the writer places every chosen sheet, one after another in block order, in place of the one unsigned page. The executed page count grows by the extra sheets, and each return's `placed_in` names its own output page.

## Returns

- `returned[]` on a block is a list: the same page can come back more than once (a duplicate in one pack, or two originals when `copies_required` is 2, or the same page in two batches). Each return records which pack, which page, which batch, what the render showed, and where it was placed. One return per required copy is placed; the rest are `spare: true` and go to `executed/spare-originals/`.
- `unmatched_returns[]` — pages the reader could assign to no manifest line. On real closings these are usually documents that were never handed over (a side letter, a fee letter). Say so; do not force a match.
- **Idempotent**: running compile again with a new `returned_dirs` entry places only what is new, never re-places, never double-counts, and recomputes the receipt. Nothing from the pack half is redone.

## Receipt

Recomputed after every operation, printed by `status`, and shown in every presentation:

> 27 pages / 27 blocks required · 21 signed · 0 partial · 0 blank · 0 unclear · 6 missing · 2 unmatched returns · 0 spare originals · **not complete**

`complete` is true only when every non-reserved block is `signed`. Reserved unassigned pages are listed separately. This line is the deliverable as much as the PDFs are.

## Dating

Optional, default off. Signed pages are held in escrow undated and are dated on the user's instruction at closing. When the user says "date them as [date]": for each placed page, the date is written as a visible PDF annotation on the block's date field (or the page's date line), never by editing the scanned pixels. A page that already carries a date is not overwritten; the date read is recorded in `dated`. The report says: dated N, already dated J, no date field K. `closing_date` is recorded on the ledger. Dating is an instruction, never a default: a sheet dated on one run keeps that date on every rebuild (`dated_applied` on the placed return), and a sheet placed for the first time is dated only on a run that passes `--date`. A late return after closing therefore arrives undated and the report counts it as `awaiting_instruction` until the lawyer says so.

## Where it lives and what it may contain

The ledger is a work-product file in the user's matter folder, like the executed PDFs. It contains party and signatory names because it must. It never goes into `lqprofile.md`, `lqplaybook.md`, or a repository. Journey capture belongs to the scribe.
