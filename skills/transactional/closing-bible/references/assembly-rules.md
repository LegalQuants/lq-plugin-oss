# Assembly rules — build and update

PRD §4 "Human gates" (Gate 2), "Assembly", "Outputs", and §9. These govern
`plan`, `build` and `update`. Audit (`references/status-taxonomy.md`) is
unchanged and always runs first: nothing is planned from an index that is
not `approved: true`.

## Gate 2 — build-plan approval

`plan` writes `build-plan.json` (`build-plan.schema.json`) from the approved
index and the selection plan. It is presented to the lawyer as a table, in
bible order: number, title, status, qualification, the selected source
file, the output name, the conversion step. Below it, every item that will
**not** enter the bible and why. The lawyer approves (`approved: true`),
reorders, or excludes; `build` refuses a plan that is not approved, whose
`index_sha256` no longer matches the index on disk, or whose `corpus_id` is
not the manifest's.

What enters the bible:

- `ready` items always.
- `unsigned`, `undated`, `incomplete` items only when the lawyer set
  `include_qualified: true` (PRD §9: express instruction). Each carries its
  qualification into the index, the HTML, the combined PDF's front matter
  and the receipt; the receipt's `outcome` can then never be `complete`.
- `not-required`, `missing`, `unreadable`, `version-conflict` never.

## The package

A new folder beside the closing folder, never inside it: `closing-bible-v001`,
`-v002`, … The version is one more than the highest existing sibling. A
package is never modified after it is written; `update` writes the next
version and leaves the prior one untouched (PRD §4 "preserve the prior
bible").

Contents (PRD §4 "Outputs"):

```
closing-bible-vNNN/
  closing-index.json        approved index, start_page filled for included items
  closing-index.html        the numbered index (title, parties, document date,
                            execution status, source reference, starting page)
  execution-overview.json
  execution-overview.html   the execution spotlight, front-matter of the bible
  source-manifest.json
  families.json
  selection-plan.json
  build-plan.json           as approved
  exceptions.md
  conversion-log.json       every conversion: source id, tool, output, pages
                            before/after, verified true/false, note
  closing-bible.pdf         or closing-bible-volume-NN.pdf + closing-bible-index.pdf
  indexed-set/
    001 - Share Purchase Agreement.pdf
    002 - Disclosure Letter.docx       native retained (PRD §9)
    002 - Disclosure Letter.pdf        rendered copy, when convertible
    …
  closing-receipt.json      mode build|update, package, included_outputs
  change-report.md          update only
```

## Assembly rules that do not move

1. **Zero source mutation** (rule 6). Sources are read and copied; the copy
   is the only thing written. The census hashes the closing folder before
   and after every `build`/`update`; a difference fails the run.
2. **Nothing is added to a document.** No text, signatures, dates, stamps or
   missing attachments (PRD §4). The only things the skill writes are its
   own pages: the front-matter index and execution overview, the volume
   master index, and PDF bookmarks/outlines. Pages of source documents are
   byte-for-byte copies.
3. **Every conversion is logged and verified.** A Word file is converted
   (bundled `soffice --headless`, per-run profile, the `sigpack convert`
   pattern) only for the combined PDF; the native file stays in
   `indexed-set/`. The rendered copy is verified before inclusion: page count
   recorded, and where Poppler is present each page is rendered and the
   count of pages with visible content compared with the native document's
   paragraph count as a sanity floor. An unverified conversion is
   `unrenderable`: the native file is in the set, the combined PDF omits it,
   and the receipt names it. Never guess.
4. **The combined PDF is the concatenation of the plan, in order**, preceded
   by the index page(s) and the execution overview page(s). Bookmarks: one
   per document (`NNN - Title`), and under each, `Execution` pointing at its
   signature pages from `execution_pages`. Where `volume_pages` is set, or
   the file would exceed it, numbered volumes are written, each with its own
   outline, plus `closing-bible-index.pdf` mapping every item to its volume
   and page (PRD §4 "numbered PDF volumes with a master index rather than
   omitting PDF delivery").
5. **Page counts reconcile or the receipt says so.** For every included
   item, `pages_expected` (the source, or the verified conversion) equals
   `pages_included` (what landed in the combined PDF). A mismatch is an
   `included_outputs` row with the two numbers and a `failed` outcome.
6. **The receipt balances** (rule 7) and additionally: every plan entry has
   exactly one `included_outputs` row; `package.version` is the folder's;
   `outcome` is `complete` only when every expected item is `ready` or
   `not-required` **and** every included output reconciled **and** no
   conversion is unverified.

## Capability ladder

The scripts are stdlib only. Assembly needs more, and says so:

- **pypdf** — combined PDF, outlines, volumes. Without it: `indexed-set/`
  and every JSON/HTML/MD output are still written; the combined PDF is not;
  the receipt's `included_outputs[].output` names the indexed-set copy and
  `package.combined_pdf` is `null`; the lawyer is told in one line that the
  combined PDF could not be built here and the indexed set is complete.
- **soffice** — Word conversion. Without it: Word files stay native in the
  set, are `unrenderable` in the plan, and are named in the receipt.
- **Poppler** — page counts for unconverted PDFs and render checks. Without
  it: page counts come from the PDF's own page tree (stdlib), render checks
  are skipped and the conversion log says `verified: false`.

Probe before touching client material; never ask to install anything inside
a hosted task.

## Update

`update` takes the prior package and the same closing folder, re-runs the
audit (census → families → inspection → reconcile with the prior approved
index), builds the next version, and writes `change-report.md`:

```
# Change report — closing-bible-v002 against v001

## Added        items in v002 not in v001, with source and status
## Replaced     items whose selected source id changed (old → new)
## Removed      items the lawyer marked not-required since v001
## Status changed   item, v001 status → v002 status, and why
## Unchanged    count only
```

Only the lawyer removes (`not-required` at Gate 1); the skill never drops an
item on its own. A late document is an addition or a replacement; it enters
through the same gates.
