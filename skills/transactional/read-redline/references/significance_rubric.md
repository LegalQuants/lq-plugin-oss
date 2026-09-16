# Significance Rubric

Rate every surfaced change High, Medium, or Low by *what kind of thing
changed* — not by how much text moved. A one-word edit can be High; a
rewritten paragraph can be Low.

## High
Changes a number, amount, price, rate, quantity, or other quantitative term;
changes a core right or obligation; changes liability, indemnity, or warranty
scope; or adds or removes a substantive clause. If someone relying on this
document would want to know before signing, it is High.

## Medium
Changes a date, deadline, notice period, or other timing term; changes a
procedural, reporting, or process requirement; or narrows/broadens the scope
of an existing obligation without touching its core.

## Low
Wording cleanup, renumbering, cross-reference fixes, formatting, defined-term
tidy-ups, or restating a provision with no change in legal effect.

## Bias rule
When you genuinely cannot tell whether a change is substantive or cleanup,
**give it a Low row rather than dropping it.** For a document that circulates,
surfacing a borderline change beats hiding it. Do not inflate the tier to
justify surfacing it — an unsure change is a Low row, not a Medium one.

## Direction
Direction is orthogonal to materiality: a High change can be favourable or
adverse, and so can a Low one. Record it as an optional `direction` on the
row — `favours-us`, `favours-them`, `neutral`, or `unknown`. Heuristic: ask
who the change relieves and who it burdens — a change that lightens our
obligations or tightens theirs favours us; the reverse favours them. When
both sides move, or you cannot tell, use `neutral` or `unknown` rather than
guessing.

## Comment voice
Each comment is a one-to-two sentence plain-English summary of *what changed
and why it matters* — the consequence, not the diff. A comment that walks
through the old and new wording is telling the reader what they can already
see. For a pure insertion, say what it now grants or requires and that it did
not exist before. For a deletion, say what is gone and what it was tied to.
Write full sentences understandable to someone who has not read the document.

## When it is genuinely ambiguous
If a change sits on the line between two tiers, say so in the comment
("borderline Medium/High — ...") rather than silently picking one. A rating
should be defensible to someone who disagrees with the tier but agrees with
the reasoning.
