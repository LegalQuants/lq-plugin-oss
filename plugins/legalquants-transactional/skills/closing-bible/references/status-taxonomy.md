# Status taxonomy

Every expected closing item carries exactly one status. The statuses are the
PRD's (§4, "Expected-set reconciliation"), reproduced here because every
script, every output and every sentence to the lawyer uses these words and
no others.

## Item statuses

| Status | Meaning |
|---|---|
| `ready` | The selected final version appears complete and, where execution is expected, appears executed and dated on inspected evidence. |
| `unsigned` | Final form found; execution is expected but execution evidence is absent or incomplete. |
| `undated` | Appears signed but no authorised completion date is present where one is expected. |
| `incomplete` | A schedule, annex, exhibit or page appears to be missing from the selected source. The missing component is named, with where it was referenced (a clause, a contents page, or a checklist row). |
| `version-conflict` | More than one plausible final version and the evidence does not separate them. The family stops here until the user decides. |
| `missing` | Expected item not found in the source folder. |
| `unexpected` | Source item not represented in the approved index. Preserved; the user decides inclusion. |
| `unreadable` | Encrypted, corrupt or otherwise unavailable for review. |
| `not-required` | Confirmed by the user as outside the closing set. |

Who sets what:

- `missing` and `not-required` are set by reconciliation and by the user.
- `unreadable` is set by reconciliation from the census (`readability` of
  `encrypted` or `corrupt`), and may also be proposed by inspection for a
  file that opens but cannot be rendered or read with confidence.
- `unexpected` is a family, not an index row. A family that matches no
  expected item is listed under `closing-index.unexpected_families` and
  counted in `closing-receipt.unexpected_families`. It never appears in
  `items[]` with status `unexpected`. At Gate 1 the user either promotes it
  to an item (which then takes a real status on the next run) or marks it
  `not-required`, in which case it becomes an item with that status and
  keeps its `family_id`.
- `ready`, `unsigned`, `undated`, `incomplete`, `version-conflict` (and
  `unreadable`, above) are proposed by inspection in `inspection.json` and
  written into the index by reconciliation only when the recorded findings
  support them under the derivation below.

## Derivation: from what was found to one status

Inspection records, per family, a structured execution finding
(`execution.apparent_status`, `execution.dated`) and a list of missing
components, alongside the evidence for each. The status is derived from
those findings — never the other way round — in this order. The first row
that applies wins; `missing_components` is carried on the item whatever
the status.

| # | Finding | Status |
|---|---|---|
| 1 | No pick can be separated from the other members | `version-conflict` |
| 2 | The pick cannot be opened, rendered or read with confidence | `unreadable` |
| 3 | `execution_expected` and `apparent_status` ∈ {`appears-incomplete`, `appears-unsigned`, `unclear`, `not-inspected`} | `unsigned` |
| 4 | `execution_expected`, `appears-signed`, and `dated` ∈ {`undated`, `unclear`} | `undated` |
| 5 | Any `missing_components` | `incomplete` |
| 6 | Otherwise | `ready` |

An inspection record whose `proposed_status` differs from the derived
status is rejected with the reason "proposed X but findings support Y" and
counted in `receipt.inspection.rejected`. When `execution_expected` is
false, `apparent_status` must be `not-expected` and `dated` must be
`not-expected`. When `execution_expected` is true, `apparent_status` must
be a finding; `dated` may still be `not-expected` where the execution page
carries no date line (the ledger's `date_field: false`, or none seen).

**Findings are about the pick.** Every `execution` or `date` evidence
record, and every `signature_pages` entry, must name the proposed pick as
its `document_id` (a `sigpack-ledger` evidence record may name the pick or
carry `null`). A record whose execution evidence points at another member,
another family, or nothing is rejected: "execution evidence cites a
document that is not the pick". `dated: dated` requires at least one
`date` evidence record on the pick, and `document_date` must read as a
date (a digit or a month name; never a placeholder such as `[DATE]` or a
row of dots). `apparent_status: not-inspected` requires `dated: unclear`
and `document_date: null`.

**Not inspected.** A family with no valid inspection record cannot be
`ready`: nothing was looked at. Reconciliation writes `unsigned` when
`execution_expected` is true and `incomplete` otherwise, with the
qualification "not inspected", and names the family under "Not inspected"
in `exceptions.md`. When a current ledger covers the family's only member,
its execution record is taken from the ledger (rule 4) and the status
follows the derivation table with "completeness not inspected" as a
missing component — so a ledger reading all signed and dated lands
`incomplete`, never `ready`, and never `unsigned` (which would contradict
the ledger). A family with several members and no inspection has no pick
and lands `version-conflict`: nothing separates them without a look — not
even a ledger `placed_in` naming one member, because the ledger speaks to
execution, not to which version is final (PRD §7: zero silent version
choices). When nothing — checklist, ledger or inspection — says whether a
document is one the parties sign, execution is presumed expected.

## Rules that do not move

These come straight from the PRD and are enforced in `models.py` and
tested, not merely described.

1. **A filename is not evidence.** No item is `ready` solely because its
   filename says "final", "signed" or "executed" (§4). An `execution` or
   `date` evidence record must have `source` `sigpack-ledger` or
   `visual-inspection`; a `filename` evidence record may support a
   `version` or `identity` observation and nothing else. `appears-signed`
   requires at least one `execution` evidence record.
2. **`version-conflict` is a stop.** No `selected_id` is written for a
   family in `version-conflict` (§4, "Version selection"). The user
   resolves it at Gate 1 or the receipt is qualified.
3. **Timestamps are not dates.** Filename dates and filesystem timestamps
   are never execution dates (§3, out of scope). `execution.dated` and
   `execution.document_date` come from the inspected execution page or the
   ledger's `dated`/`dated_applied`.
4. **A current `sigpack` ledger is authoritative for its blocks, and is
   never reclassified** (§4, "Execution spotlight"). When a current ledger
   covers the selected document, reconciliation reads the block statuses
   itself, shows them verbatim in the overview, and derives
   `apparent_status` and `dated` from them; an inspection record citing
   the ledger that disagrees with the ledger's blocks is rejected and
   counted. The ledger cannot name the bytes of the executed file it wrote
   (`placed_in` is a name), so its `appears-signed` attaches to a pick only
   while nothing inspected on that pick contradicts it: a visual finding of
   a blank or partial block on the selected file makes the item
   `unsigned` on `visual-inspection` evidence, with the disagreement noted
   under "Ledger notes" — the ledger's block stays `signed`; it is the
   attachment to these bytes that is declined, not the block. See
   `sigpack-ledger-consumption.md` for the mapping and its precedence.
5. **Never infer authority or delivery from a signature** (§4, "Execution
   evidence"). The words are "appears signed", "appears incomplete",
   "appears unsigned" (nothing came back), "unclear" — never "validly
   executed".
6. **Nothing is deleted, renamed, moved or overwritten** (§3, §4
   "Assembly"). Duplicates are grouped, never removed.
7. **The receipt balances or is not written.** `expected_items` equals the
   sum of items by status; every distinct source document sits in exactly
   one family; `sources.duplicates` equals `files − distinct`; and
   `outcome` equals the value the rules below derive from the counts (§7,
   "complete source and expected-item accounting").

## Receipt outcomes

| `outcome` | Condition |
|---|---|
| `complete` | Every expected item is `ready` or `not-required`; `unexpected_families` is 0; `sources.unreadable` is 0. |
| `qualified` | Every expected item is accounted for and none is `missing`, but at least one is not `ready`/`not-required`, or an `unexpected` family remains undecided. Assembly only on express instruction, visibly qualified (§9). |
| `failed` | Any expected item is `missing`, any item is `unreadable`, any source document is unreadable (`sources.unreadable` > 0, which counts `encrypted`, `corrupt` and `suspect`), the expected set is empty, or the counts do not reconcile. No assembly. |

Every expected item that is not `not-required` is material: there is no
separate materiality flag, and one `missing` item fails the receipt. An
empty expected set is not a clean closing; it is nothing to audit, and it
fails. Entries the census could not inventory are listed in the manifest under
`skipped[]` with a reason. Symlinks pointing outside the folder, unreadable
directories and special files are counted in `sources.skipped`, and any of
those keeps the receipt from `complete`. Hidden entries (`.DS_Store`, `._*`,
`.git`) are listed so nothing vanishes silently but are not counted: they
are the operating system's, not the closing's.

The receipt line, printed after every run and shown even when complete,
reads like `sigpack`'s so the two skills read the same way at closing:

> 14 expected · 9 ready · 2 unsigned · 1 undated · 0 incomplete · 1 version-conflict · 1 missing · 0 unreadable · 0 not-required · 2 unexpected · **QUALIFIED**
