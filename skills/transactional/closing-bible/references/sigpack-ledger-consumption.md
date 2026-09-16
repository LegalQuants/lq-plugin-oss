# Sigpack ledger consumption contract

`closing-bible` is a read-only consumer of `sigpack.ledger.json`. It never
writes to the ledger, never reclassifies a block, and never re-judges a
signature the ledger has judged (PRD §4, "Execution spotlight": "it does not
reclassify returned pages"). The ledger's shape is canonical at
[../../sigpack/references/ledger_schema.md](../../sigpack/references/ledger_schema.md);
this file states only what `closing-bible` reads, the gate that decides
whether it may read it, and how a block status becomes an execution finding.

## The gate: is the ledger current?

A ledger is cited only when it describes the files in front of us. Before
any field is read:

1. For every live signature page (`reserved: false`, or reserved with a
   party assigned), at least one of these must exist and hash-match a
   census `documents[].id`: the execution version at
   `<ledger folder>/<execution_dir>/<file>`, or the executed output named
   by any chosen return's `placed_in` (the part before `#`), resolved
   relative to the ledger folder. Names are not enough; the bytes must be
   the bytes the census saw. A folder holding only the `executed/`
   compilation and not the unsigned `execution/` versions passes.
2. `receipt.as_of` must be present.

If either check fails, the receipt records `sigpack.ledger_current: false`,
no ledger field is read, execution evidence for every family comes from
inspection alone, and the lawyer is told in one line that a ledger was
found but does not match the folder. A ledger that fails the gate
contributes nothing: no expected items, no family seeds, no agreement
names. Its own file is still set aside by hash (it was supplied), so it
never appears as an unexpected document or a phantom expected item.

## Fields read

Once the gate passes:

- `matter` — used as the index's `matter` when the user gives none.
- `closing_date` — echoed into `execution-overview.sigpack.closing_date`
  for information; never written onto any document and never used to
  decide `undated`.
- `execution_dir` — to find the execution versions the ledger describes.
- `signature_pages[]` — `id`, `file`, `page`, `agreement`, `reserved`; per
  block: `block`, `party`, `status`, `date_field`; and on the `chosen`
  return: `execution`, `dated`, `dated_applied`, `placed_in`.
  - `agreement` seeds a family's `sigpack_agreement` and, when no user
    checklist exists, the expected set (`index_source: sigpack-ledger`),
    in ledger order.
  - Block `party` values populate the index item's `parties` and the
    overview's `blocks[]`.
  - Block `status` is the execution evidence. Reconciliation reads it
    itself and records it as `evidence.source = "sigpack-ledger"` with
    `locator = <page id>` (rule 4). An inspection record that cites the
    ledger and disagrees with what the ledger says is rejected and
    counted in `receipt.inspection.rejected`.
  - `dated` on the chosen return, **or** `dated_applied` when sigpack's own
    dating workflow dated the page at closing, gives `document_date`
    (verbatim) and `execution.dated`, decided **per block and aggregated,
    worst wins**: any block with `date_field: true` and neither `dated` nor
    `dated_applied` → `undated`; otherwise every dated block → `dated`
    (the first date read is `document_date`); every block
    `date_field: false` → `not-expected`. One dated block never dates a
    document whose other block is waiting.
  - `placed_in` names the executed PDF and page for the overview's
    `signature_pages[]`. Read, never trusted for existence: the census must
    hold a file whose hash matches or the entry is omitted with a note.
- `receipt` — echoed verbatim into `execution-overview.sigpack.ledger_receipt`
  and compared with our own. If the ledger says `complete` and our index
  says an agreement is `unsigned`, that contradiction is itself an
  exception.

## Block status → apparent status

Applied per document over its live blocks, first matching row wins:

| # | Live blocks | `apparent_status` | Overview `exceptions[]` line |
|---|---|---|---|
| 1 | any block `unclear` | `unclear` | "unclear return on `<page id>` block N" |
| 2 | every block `required` or `sent` | `appears-unsigned` | — |
| 3 | any block `wrong-version` | `appears-incomplete` | "version-mismatched return on `<page id>` block N" |
| 4 | any block `partial`, `blank`, `required` or `sent` | `appears-incomplete` | "block N (`<party>`) not signed" |
| 5 | any page whose signed block's chosen return has no `placed_in` (a `HELD` sheet), or was placed into a file that is not the selected one | `appears-incomplete` | "signed sheet for `<page id>` held, not placed" / "signed sheet for `<page id>` placed in '<name>', not in the selected file" |
| 6 | every block `signed` and placed into the selected file | `appears-signed` | — |

Exception lines are written for every block that matches a row, whatever
row decides the status: a document with one blank block and one held sheet
carries both lines. The lawyer sees everything the ledger knows.

Reserved pages with no party assigned are ignored, as the ledger does.

## Resolving the files the ledger names

- An execution version is `<ledger folder>/<execution_dir>/<file>`; its
  bytes are hashed and must equal a census `documents[].id`.
- A `placed_in` value is a bare output name plus page (`(Executed)
  X.pdf#19`); `sigpack` does not record where it wrote it. The executed
  document is the census document whose path basename equals the name
  before `#`, anywhere under the closing folder. Exactly one match is the
  document. Several: the shallowest path is taken (the ledger sits at the
  closing-folder root by `sigpack`'s convention, so shallowest is closest
  to it) and the ambiguity is noted under "Ledger notes" in
  `exceptions.md`. None: the ledger's finding applies to no selected file
  (see below).
- The ledger file itself lives in the closing folder and is inventoried by
  the census like everything else. Reconciliation sets aside the document
  whose hash equals the supplied ledger file's — that one id, never a
  family chosen by title — from the index and from `unexpected_families`,
  records its family as `not-required` in the selection plan, and notes
  "the ledger itself, not a closing document" under "Ledger notes". It
  still counts in `sources.in_families`. Any other member of that family
  is a document and is reconciled as one.

## The ledger speaks about the executed file, not the folder

The ledger says the pages are signed *in the compiled executed PDF*. That
finding applies to an index item only when the item's `selected_id` is the
document the ledger placed the pages into (`placed_in`, resolved by name
per "Resolving the files") **and nothing inspected on that file
contradicts it**. `placed_in` is a name, not a hash; a draft saved under
the executed name resolves the same way. So when inspection records a
blank, partial or unclear block on the selected file, that visual finding
governs the item (`unsigned` on `visual-inspection` evidence), the
ledger's blocks are shown unchanged in the overview, and the disagreement
is written under "Ledger notes" — "inspection saw a blank block on the
selected file; the ledger's signed finding could not be tied to these
bytes". This declines an attachment; it reclassifies nothing. When the family holds only the unsigned execution version — the
compilation has not been run, or is not in this folder — the ledger is
still cited, but the item is `unsigned` with the qualification "ledger
shows N of N blocks signed; executed compilation not in folder". A page the
ledger marks `HELD` (signed, chosen return with no `placed_in`) is treated
the same way.

The ledger says nothing about whether the file is the right version of the
agreement, or whether Schedule 3 is attached. Version selection and
completeness are still inspected for ledger-covered documents.

## Fields not read

`packs_sent`, `unmatched_returns`, `checkpoints`, `returned_dirs`,
`version_marker`, `esig_separator`, `copies_required`, `sheet_hash`, and
every `returned[]` entry not `chosen`. Those are `sigpack`'s working record
for packing and compiling. `closing-bible` trusts the settled block status,
not the trail that produced it.

## Routing back to sigpack

If the user needs returned signature pages matched, packs prepared, pages
inserted, chasers drafted or a block reclassified, that is `$sigpack`'s
work (PRD §4, §5). `closing-bible` says so in one line and does not
duplicate it.
