# Fixed component contract

This is the sole UI contract for new outputs. Assemble the chosen explanation with the shared runtime; do not redesign its controls, themes, editor, or popup system. Palette values and configuration belong to [../DESIGN.md](../DESIGN.md); typed authoring fields belong to [build.md](build.md).

## Geometry and typography

- Desktop type is stable: 28px page title, 20px section/card heading, 16px body, 12px compact labels/support. Use the packaged Helvetica Neue-led sans stack; the Charter-led serif stack is for exact document excerpts only. No responsive enlargement, fit-loop font adjustment, or whole-page up/down scaling on new desktop output.
- Use the runtime's 12-column grid, 16px gaps, 24px outer padding, 20px card inset, and 1440px maximum page width. A wider window adds surrounding space, not larger type or endlessly stretched prose. Peer components share alignment, padding, and comparable density. These are fixed tokens, not a required 4:3 ratio or 1200×900 canvas.
- The first content is a full-width descriptive title; an optional subtitle shares its padded bounds. Popup headings and introductions also use the full frame. Main pages do not scroll or overflow. If readable content cannot fit, change its allocation under [design.md](design.md), not the type scale.
- Window resizing reflows available frames without changing desktop text size. Compact diagram density changes inter-node gaps, not actual text size; narrow diagrams retain their native width without upscaling. Explicit editor resizing is different: HTML text rewraps in the selected frame; SVG bounds resize geometrically. Preserve saved geometry overrides.
- Center diagram-node labels by default, except where table/list reading requires alignment. Keep at least 12px visible clearance from unrelated geometry; a connector's own label uses an intentional small break. Label quantities, units, axes, grouping, and connector meaning; position or size must not imply unsupported measurements.

## Component families

| Family | Use and anatomy |
| --- | --- |
| Open narrative | Title, answer, consequence, or action on the page ground or a quiet band. Findings keep finding → consequence → action in a consistent reading order; do not box everything. |
| Card or row | A specific heading with restrained support. Plain text cards are generally borderless; interactive cards retain the packaged soft depth and one whole-object target. Numbered rows indicate a genuine countable sequence. |
| Table or register | Shared columns and aligned values/statuses for exact repeated comparison. Avoid replacing deterministic data with decorative cards. |
| Figure or zone | Registered geometry on open ground or quiet tint, without an outer floating shadow. Boundaries encode membership; connections encode the declared relationship. Give each meaningful node one accessible target when it has detail. |
| Decision | A question, explicit options with consequences, and optional decision-specific notes. Selected state is distinct from unresolved status; there is no universal comments layer. |
| Issue page | Full-width issue title, equal-width analysis/support columns, three separate left cards (statement/finding, significance, next action), and one or two right supports (registered figure and/or authentic source preview). The builder owns slot placement; fixed type, padding, reading order, and export behavior apply. |
| Source preview | Actual captured document pixels or an exact recorded excerpt with source/locator/status caption. One whole-object target opens the source popup. No invented facsimile, full-sentence link underlining, remote image, or provenance promotion. |

Use the least enclosure needed. A decorative child is not an independent control. Keep prose at the runtime's reading measure; a vertical event rail follows its useful rail width, while aligned tables and headings may use the full frame. Equal event spacing is ordinal unless an honest time scale is explicitly encoded.

## Color and feedback

The light page is light gray so white cards stand out; the Default dark page is pure black. Optional Lavender, Mint, and Sand presets add a quiet tinted ground and coordinated accent in both themes. Edit → Palette offers four buttons; Default restores the artifact's design authority rather than deleting a configured firm palette. Dark diagram nodes have subtly raised near-black fills, clear light/gray or semantic-accent outlines, and white labels/arrows. Do not replace this with white nodes or default solid-accent boxes. Popups and chrome retain their separate overlay surfaces. Preserve truthful quantitative encodings and explicit editor paint overrides.

Semantic accent expresses an exception, boundary, decision, or required action—not arbitrary emphasis. Reading targets use subtle neutral hover and visible keyboard-focus feedback; editor selection uses a neutral outline and handles, not saturated blue or semantic red. Feedback applies only to the actual target, never every object sharing its detail. Preserve semantic action accents during hover. Noninteractive decoration has no pointer or hover border; hover never moves layout. Dark popup introductions and explanatory prose use primary near-white ink; source metadata may remain secondary, and explicit user paint overrides remain authoritative.

## Details and targets

The runtime supplies purpose-specific source, explainer, and detail popups with a shared surface/shadow, full-width header, round close control, focus trap, and return to the exact trigger. Their content/source requirements are in [evidence.md](evidence.md). A popup may scroll internally; an accordion is allowed only when its expanded state fits and improves comparison.

Standalone popup phrases are underlined pointer targets. A whole clickable card/node has one accessible name and tab stop, not separate heading/body controls. Distinct actions never overlap or nest buttons. Topic navigation and popup disclosure cannot share a target. Closing detail clears transient pointer highlighting while preserving keyboard focus; from the phone reader it returns to the same reader position and trigger.

## Shell, navigation, and phones

Exactly four utility controls: Edit, Theme, Export HTML, Export template. No approach selector, animation controls, fullscreen control, or extra permanent export button. The separate Read page control and slide navigation are reading controls, not authoring utilities.

Slide briefs have a persistent left contents index with concise labels and current position, plus Previous/Next. Desktop entries are compact, natural-height rows, not tall cards; touch entries retain 44px targets. A grouped overview automatically supplies the same collapsible subject groups to the index, with one group open at a time. Navigation reveals the current page's group; repaint does not undo manual collapse. Do not author a duplicate group list. The index ends with the measured content, stays within the active page frame, and scrolls internally only if needed; never stretch a navigation rail or park a pager below the content. Overview topics, index, pager, and restored page stay synchronized. Navigation is not selectable document content.

A large overview uses the optional shared subject-group accordion: short labelled summaries with topic counts, one group open at a time, and compact whole-card links to individual pages. Grouping changes navigation, not coverage. Keep facts/question/answer above it; use no extra custom shell. The phone reader stacks the same topic cards, and client/template exports preserve their destinations.

On phones the index becomes a compact Contents control. Only the phone overview may scale down. On initial v4 phone load, the existing reader opens once with the active page's unchanged content, unscaled 18px body text, and responsive diagrams; closing it returns to the scaled canvas/book, and Read page can reopen it. Wide figures may pan inside their frame. Reader/popups may scroll internally, but the main document and reader shell do not overflow horizontally. This is a runtime reading mode, not another authored composition.

Native pinch zoom magnifies the existing layout; it must not trigger a compensating page-fit or change reading mode. Use the layout viewport for fitting and breakpoint decisions, not the pinch-sensitive visual viewport. Genuine window/orientation changes still reflow.

## Editor, persistence, and exports

Edit mode selects on click; its popup tool opens selected detail for editing. Each working/template popup also has a pencil beside Close. It enters popup-local editing without a large toolbar: click an object to select it, double-click to type, drag selection handles to resize, drag the selected object to move, and press Delete/Backspace to remove it. Alt-click a section selects the whole block; standard Undo/Redo shortcuts remain available. The bottom-right popup grip resizes the frame by drag or arrow keys; double-click or Enter fits its height. Click the pencil again to finish and restore the preceding page mode. The I-beam appears only while typing. Preserve text/diagram editing, visible Fill/Text swatches, Add text box, independent Duplicate/Delete, object move/resize, fully enclosed marquee/group drag, popup attach/edit/remove, and undo/redo.

User text, geometry, colors, added objects, and popup presentation are overrides over the validated baseline. Rerendering and Save/reopen preserve them with theme, palette, page position, and explicit decision responses/notes. Presentation editing never changes source identity or upgrades verification. Client exports contain no pencil, resize grip, palette chooser, or file-saving/export capability; reusable templates retain those authoring tools.

The temporary Read page view is not an editable source popup and has no pencil. Edit its underlying page or authored detail instead; do not offer edits to a disposable reader clone.

Export HTML keeps the single composition, edits, and intended reader interactions without authoring chrome or rationale. Export template keeps reusable structure/editor behavior with descriptive placeholders and no private matter. The post-export result may offer Open exported HTML in a separate tab: this previews the exact serialized copy, not proof of a verified disk write. Report native success only after write completion; a browser download remains unconfirmed. Full persistence, export, and privacy checks are in [qa.md](qa.md).
