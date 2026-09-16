# The map — every skill by the situation that calls for it

Read at run time by `/lq-start`, then split by what the catalog says is
installed. Every entry names one skill with the group it ships in, and each
group belongs to one plugin:

- `litigation` and `core` ship in **LegalQuants Skills for Litigators**
  (`legalquants-litigation`): source-grounded workflows for litigators.
- `transactional` and `core` ship in **LegalQuants Skills for Transactional
  Attorneys** (`legalquants-transactional`): contract and deal workflows.
- `companion` ships in **The LegalQuants Companion** (`legalquants-companion`):
  your journey with AI as a lawyer.

`core` is the shared daily-practice set, so it is installed with either
practice plugin. A test keeps this file honest: every shipping skill appears
here exactly once, nothing here names a skill that does not ship, and the
plugin ids match the release manifest.

## Transactional: from markup to closing

The route most deal work travels.

1. **The other side sent a markup** → `$read-redline` (transactional). Every
   change found, rated High / Medium / Low, an annotated copy to hand back and
   an issues list to circulate. Takes a compare PDF or a Word file with tracked
   changes. Not for comparing two clean drafts.
2. **The defined terms feel loose** → `$definition-check` (transactional).
   Coverage, orphans and circular definitions, with evidence per finding. Often
   the step after a redline and before you send comments.
3. **A new draft must conform to an approved precedent** → `$conform`
   (transactional). Normalizes both documents' defined terms deterministically,
   then maps precedent positions onto the draft with an HTML redline. Fails
   closed on stale ledgers; never merges cross-document meanings on its own.
4. **You need to turn approved precedents into reusable positions** →
   `$playbook-builder` (transactional). Builds a source-linked contract
   playbook with preferred positions, fallbacks and lawyer-curated Matter
   Lenses. It does not approve inferred policy for you.
5. **A live draft needs checking against that approved playbook** →
   `$playbook-review` (transactional). Starts from Standard Baseline, applies
   only the Matter Lenses you actively choose, and returns a clause-anchored
   issues list with suggested inline markup and coverage receipts. It accepts
   substantially equivalent drafting and maps house defined terms into the
   counterparty document before proposing changes. It does not create a Word
   redline.
6. **The deal needs a working closing checklist, or the one you have needs
   updating** → `$closing-checklist` (transactional). Drafts an editable Word
   checklist from the SPA or anchor agreement, or proposes and applies changes
   to your existing one after revised agreements or new instructions, keeping
   house formatting, references and timing. It does not chase status, build
   signature packs (`$sigpack`) or audit the closing folder (`$closing-bible`).
7. **Closing this week** → `$sigpack` (transactional). Signature packs out,
   executed pages compiled back, who is still outstanding and a chaser drafted.
   Works from the closing folder and keeps a ledger.
8. **After closing, the set has to be accounted for and bound** →
   `$closing-bible` (transactional). Audits the closing folder against the
   checklist or the sigpack ledger: which version is final, what appears
   executed, what is missing or duplicated, and a receipt that balances. Not
   for preparing or inserting signature pages; that is `$sigpack`.

On the side of that flow:

- **A data room and a checklist** → `$diligence` (transactional). Reviews the
  room against your issue list at corpus scale, with pin-cited findings. Not a
  redline tool, and not for a single document; for one document use
  `$read-redline` or `$definition-check`.

## Litigation: from production to filing

- **A new dispute needs a controlled start** → `$new-matter` (litigation).
  Captures the matter, forum, posture, authority, conflicts status, urgent dates,
  preservation needs and existing-or-first-use workspace choices before anything
  is written or moved.
- **The case file needs a working map** → `$organize-case-docs` (litigation).
  Builds the source manifest, chronology, proof chart, issue and evidence maps,
  matter briefing and document-review handoff without moving native originals.
- **In U.S. federal civil practice, you are planning preservation, serving
  requests, answering them, or handling a subpoena** → `$document-discovery`
  (litigation). Builds a proportionate preservation or hold work package, or
  drafts targeted requests, itemized responses and objections, meet-and-confer
  positions, privilege routing and subpoena triage. A production already
  received goes to `$docreview`; preservation in another forum needs its own
  controlling-authority check, with `$regulatory` available to retrieve the
  operative official text.
- **A production landed against your requests** → `$docreview` (litigation).
  Reviews it against the requests or issues and flags the gaps, with coverage
  receipts. Privilege calls stay with the lawyer.
- **A deposition needs preparing or reconciling** → `$depositions` (litigation).
  Turns the proof plan into witness, topic, exhibit, admission and impeachment
  work, including Rule 30(b)(6), nonparty and transcript follow-through.
- **A brief, regulator paper or client memorandum needs drafting** → `$writing`
  (litigation). Chooses advocacy or neutral-analysis mode, then writes from the
  record with the right candor, authority and review controls.
- **A position or the other side's case needs to survive contact** →
  `$pressuretest` (litigation). Maps the argument, confirms the map with you,
  attacks it every way the material allows, and reports where it breaks —
  logic, dates, figures and cross-document consistency only. Citations stay
  with `$cite-check`.
- **A filing cites authorities you have in hand** → `$cite-check` (litigation).
  Verifies every citation and quotation against the authorities you supply.
  Never guesses at a source it was not given; if you need the source itself,
  see `$regulatory`.
- **A litigation letter or settlement exchange needs drafting** →
  `$correspondence` (litigation). Handles discovery, substantive and settlement
  correspondence with source, formation and no-send review gates.
- **The client, co-counsel or portfolio owner needs the status** →
  `$client-update` (litigation). Separates verified developments, analysis,
  recommendations and decisions in matter, event, OC and portfolio formats.

## Any practice

- **You need the controlling official text** → `$regulatory` (core). Finds the
  primary source and proves its version. The answer to "is this still the
  law", not "does this brief cite it correctly".
- **Time entries need narratives** → `$timenarratives` (core). Drafts candidate
  narratives from the files you select for the named lawyer and matter. Deal
  or dispute, same skill. Private practice only; in-house lawyers skip this.
- **Completed work needs explaining to a client, a board or a colleague** →
  `$legaldesign` (core). One editable, evidence-grounded page or deck, built
  from work already done. After the work, never instead of it.
- **You want to keep what you learned** → `$wiki` (core). Your personal legal
  wiki, built from what the other skills produce. Records reusable law and
  method, never matter facts. The layer underneath everything.

## Getting better at this

- **You want to talk to someone who's been through it** → `$lq-connect`
  (companion). Matches what you're working on to LegalQuants members with
  public profiles — two or three, with the specific why — and hands you
  their profile links. Your need is sanitized and approved by you first.

- **You want to show the world what you can do** → `$lq-apply` (companion).
  Compiles your journey into a draft you can send — the real LQ
  application (which is LQ Assess), a CV, or a public profile — from
  confirmed evidence, with an honest list of what still needs you. Never
  publishes, never inflates.

- **You want to know what LegalQuants has said in public** → `$lq-ask`
  (companion). Answers from what LegalQuants has published — the Insights
  essays, the free weekly digest, the public repositories — with a link to
  each page it read, and a plain line on which it reached. It does not
  search member discussions; those need an LQ member connection, and it
  says so rather than guessing. Not for legal research; that is
  `$regulatory`.
- **You want to know where you stand with AI** → `$lq-mirror` (companion).
  Twelve short questions and an honest reading — your archetype, said in a
  way that respects you. Recognition, never a verdict; not the formal
  LQ Assess and not a step toward it.
- **You want to know where you are with AI, and what to do next** →
  `$legalquants` (companion). Reads your journey privately from your own
  machine and offers the one or two moves that make sense now. Never a menu,
  never a test, never for the work itself.
- **You think something genuinely impressive just happened** →
  `$my-lq-moment` (companion). Checks the session against a fixed rubric
  and, only when it clears the bar, articulates your LQ Moment with a
  receipt, a shareable post and a typographic cover. Borderline means not
  earned; no participation trophies.
- **You want to see how you actually practised with AI this week** →
  `$lq-reflect` (companion). Goes through your sessions with your permission and
  shows the moments that mattered, one change to keep, and your moment of the
  week. Also live, when a session just went sideways: what failed, why, and
  the next move. Private, never public; not for the work itself.
