# Composition recipes

Use the communication plan from [method.md](method.md) and the fixed UI in [component-grammar.md](component-grammar.md). A proven composition is welcome; novelty is not a requirement.

## Inspect, then adapt

Inspect relevant packaged assets for both reading flow and component anatomy. Filled `stacked-explainer`, `diligence-report`, `slide-brief`, and `method-map` assets are legacy-compatible anatomy references for narrative rhythm, figures, cards, and purposeful detail. All shipping reusable templates use v4; `card-hub` adds the compact framing-card/peer-cards/conclusion format. Consult the current registry and component/build contracts for new authoring.

Reuse useful arrangements without requiring a named-template import. Adapt their claim allocation, density, and geometry; never copy example matter or impose its page count. Importing an exact template is a separate user-named path in [build.md](build.md).

## Default issue-page anatomy

For a slide brief explaining legal issues, findings, documents, or deal risks, use
the shared `issueLayout` component on each issue page. This is the default even
without an exact-template request. The builder, not the agent, places its slots:

| Left: analysis | Right: support |
| --- | --- |
| **What they said / What we found:** the precise disclosed term or supplied finding, with its qualification. | One registered graphic that explains the actual relationship; an authentic source clip or exact quotation; or both, stacked in one column. |
| **Why it matters:** the supplied consequence, condition, or practical significance. | A graphic explains; an excerpt proves what the document says. They must not pretend to do each other's job. |
| **Recommendation / Next check:** the supplied advice, authorized recommendation, or honestly unresolved question. | Clicking the source preview opens its purpose-specific popup, locator, limitations, and original. |

One descriptive issue title spans both columns. Keep the three left cards
separate, with the action card's restrained accent. Keep headings consistent
across the brief, adapting their wording to the record. Do not invent advice to
fill a box: when no advice is supplied, use **Next check** and identify the
missing question or decision. A filing's risk statement is not automatically
the lawyer's finding or recommendation. Distinguish issuer statements, analysis,
and proposed follow-up.

Use a compact timeline, condition tree, comparison, ownership structure, or
other supported form only when its geometry helps explain the issue. If a source
passage is the useful supporting visual, it can occupy the right column alone;
no decorative diagram quota applies. Put the useful source passage on the page,
not only behind a popup, when the source itself is central to understanding.
Never recreate a document image or use a paraphrase as an exact quotation.

The overview remains a facts/question/answer dashboard with linked topics and
optional subject groups. It is not an issue page. A full-width comparison table,
an actual document viewer, or another composition may replace the issue recipe
when the user requests it or when a specific relationship cannot honestly fit
the two-column anatomy; record that reason in the plan. Do not silently fall
back to generic card grids or full-width prose because a diagram failed a test.

## Other useful recipes

| Relationship/task | Composition and what the arrangement communicates |
| --- | --- |
| Explain a finding in context | Narrative findings beside an event rail or source register. Narrative gives consequence/action; aligned context makes the supporting sequence or record visible. A figure may span several narrative rows. |
| Compare alternatives or obligations | Shared criteria and aligned rows, followed by the qualified conclusion and action. Position supports exact comparison; color does not invent a score. |
| Explain scope, hierarchy, or conditional rights | A labelled boundary, tree, or supported route beside concise conditions. Enclosure means membership; connections mean the stated dependency, not mere association. |
| Introduce a slide brief | Visible facts, question, and answer followed by distinct topic targets. Topic order is reading order, not an implied chronology; each target leads to one explanatory page. |

These alternatives do not override the default issue-page anatomy without the specific reason above. For other forms, use open text for a single proposition, a table for exact repeated mappings, and a diagram only when its geometry reduces reconstruction by the reader. A page of equal cards is unsuitable when it obscures an important hierarchy or dependency; a supported source/table composition is not deficient merely because it has no diagram.

## Allocate space by meaning

Give the answer and core relationship distinct hierarchy. Pair supporting narrative with a figure when each does different work; avoid explaining the same point three times. Use the least enclosure needed, with shared alignment for peers. Do not stretch a small point across an empty page or fill space with decorative content.

When content does not fit the fixed readable system, remove redundancy, move supplementary explanation into detail, or add a deep-dive page. A one-pager must remain complete; if that is impossible, resolve the form with the user under the intake gate. Never solve overflow by shrinking desktop type, hiding a material warning, or deleting the intended explanation after a failed render.

Check each graphic's labels, grouping, directions, and scales against the planned relationship. Long labels call for clearer surface wording with faithful detail, more figure space, or coordinated views—not invented shorthand. Technical validity is not visual review; use [qa.md](qa.md).
