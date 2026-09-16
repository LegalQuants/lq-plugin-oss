# Choose a visual form

Start with the reader's question, not a template. Name the relationship that answers it, choose the simplest form, then specify what position, direction, length, or enclosure means. If a short paragraph or list answers it more clearly, use that instead.

## Recommended core

| Reader needs to understand | Component | Required visual meaning |
|---|---|---|
| What happens next | `flow` | Arrows connect consecutive stages; every arrow names the transition. No branching decisions. |
| What happened when | `timeline` | Chronological order with dates. Equal spacing means **order**, not elapsed time; disclose “not to time scale.” |
| Who owns what, or what belongs below what | `hierarchy` | A shared parent connects separately to each child. Enclosed leaves belong to that branch; siblings do not imply sequence. |
| Which items belong in each of two scopes | `zones` | Enclosure expresses membership. The crossing label must name an actual directed transition; for static membership, use a hierarchy instead. |
| What changes between two states | `beforeAfter` | Comparable states and a named transition. Do not invent a preferred or better state. |
| How several parties relate to one actor | `hub` | Equal-status spokes with explicit incoming or outgoing arrows. All spokes must share that direction. Mixed directions need a custom graph. |
| How two options differ on the same criteria | `compareTwo` | Aligned criteria rows and option columns. Highlight only a supported recommendation; use `none` otherwise. |
| How quantities compare | `rungBars` | Common zero baseline, length proportional to value, same units. |
| How a measured value changes across ordered observations | `hairlineLine` | Numeric x/y positions; chronological x values and their matching labels. Do not interpolate across missing observations silently. |
| How totals divide into comparable parts | `stackedRungs` | Additive, non-overlapping parts; consistent order and scale. Explain the parts, and compare totals or the baseline segment rather than floating middle segments. |
| What interval or uncertainty range applies | `rangeBars` | Low and high positions on one disclosed scale; an optional marker is a separately identified value, not a fabricated estimate. |

Use exact runtime IDs and parameter contracts in [components.md](components.md). `recommended: true` in [components.json](components.json) identifies this core. Other renderers exist to reopen older HTML; do not choose them for a new artifact. A legacy filename or familiar shape is not evidence that its geometry fits the present question.

## Layout and evidence

Fit the overview to the available window; 4:3 is a planning reference, not a locked ratio. If it will not fit at readable size, split it into another slide; do not shrink labels, crop content, or scroll the overview. Use popups for explanations and original-source excerpts, then link from those details to the underlying source. A compact preview must preserve the same facts and relationships as the complete diagram.

For each proposed graphic, explain its encoding in one concrete sentence: “Each column is an option; each row is the same criterion,” not “This shows the big picture.” Equal size means equal status unless a disclosed measure determines size. Arrows need a real directional relationship. Do not use mountains, gears, stairs, funnels, or pyramids as metaphors for unmeasured progress or importance.

Keep the tested component's geometry, tokens, and interaction contract together. Recompose the page around the material; do not inherit an example's outline. When no core component can encode the claim, use clear text or build and verify a specific new component—never force the claim into a shape that changes its meaning.

For a text-rich finding, consider a vertical `timeline` (`orientation: "vertical"`, three to five dated events) beside the finding, consequence, and action. It uses a slim event rail with left-aligned dates and labels rather than a chain of chunky cards. A multi-row placement can give it the combined height of the narrative stack. Use a full-width table instead when the important relationship is the mismatch between records on common criteria. Neither form replaces required explanation or increases the component's declared capacity.
