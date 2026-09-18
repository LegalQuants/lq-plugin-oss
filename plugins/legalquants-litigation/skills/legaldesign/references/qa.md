# QA before delivery

Validate the specification, compare the source record, and inspect the rendered artifact. Schema success or a screenshot file is not proof of fidelity, legibility, or functioning interactions. Correct failures and rerun affected/dependent checks; disclose anything unavailable.

## 1. Intake and explanation

- Check the conversation actually paused after unanswered intake; an unanswered question followed by production fails the method, even if the resulting file works.
- Compare inputs → ledger → artifact and back. Preserve every material claim, qualification, uncertainty, option, and source status; justify omissions. Verify facts, question, qualified answer, supported relationship, and action under [method.md](method.md).
- Check one-page completeness or slide-overview coverage. On slides, visible facts/question/answer precede deep dives; each concise topic reaches its promised page exactly once. A topic must not also open a popup.
- Compare the chosen representation with its intended meaning. Verify comparison alignment, connections, membership, units, scales, and labels. Reject interchangeable cards that conceal a central dependency, but do not demand a diagram where text or a table explains better.
- For slide-brief issue pages, check the actual three-card analysis column and adjacent support column, not just the prose plan. Require a specific reason for a non-issue layout. The action must be sourced advice or labelled proposed follow-up, never a recommendation invented merely to fill the recipe. Source previews must match the recorded excerpt/clip and retain their source target after Save and both exports.
- Read every labelled arrow aloud as source → verb → target. Check that it expresses the supported direction: permission enables service; service depends on permission. Check negated outcomes too: preventing completion is not preventing blocked completion. A plausible label attached to the reverse arrow is still a wrong explanation.

## 2. Visual and responsive behavior

- Inspect every page in both themes at 1280×800, 1440×900, and 2560×1440, then resize back. Check the [fixed geometry/type contract](component-grammar.md): effective displayed desktop type must not enlarge or shrink with the window. Inspect transformed ancestors as well as computed font sizes. No clipping, overlap, empty navigation-caused pages, document scrolling, or rail/pager below the content frame.
- Inspect a cold first paint, including a Retina-scale laptop, before hovering or toggling a theme. Text must not snap into place only after interaction. Check headings, prose measure, card depth, figures, label clearance, and authentic source clips against the actual house components; geometry coordinates alone do not prove correct painted text.
- Inspect 430×932 and 390×844 phones: initial v4 load opens the existing 18px reader once with unchanged content; closing returns to the scaled canvas/book, and Read page reopens it. Check compact contents, responsive figures, and internally scrolling detail. Wide figures pan inside their frame rather than overflowing the reader. Any accordion fits expanded.
- Check light/dark semantic roles, subtle neutral reading feedback, visible keyboard focus/editor selection, explicit paint overrides, and final text contrast of at least 4.5:1, including configured firm colors. Dark popup prose should use primary ink, not metadata gray. A no-overflow pass cannot compensate for losing the explanation.

## 3. Reading and source interactions

- Open every overview topic and purposeful detail target with real pointer and keyboard input, including figure targets in phone reader mode. Forced/programmatic clicks do not establish usable hit areas; diagnose intercepting geometry or faulty targets instead of deleting the explanation.
- Confirm popup purpose, exact excerpt/clip correspondence, provenance/limits, and actual original link or honest unavailable state under [evidence.md](evidence.md). A working link or matching checksum does not establish verification. Supplied narrative and clip content must not be silently conflated.
- Test one-target semantics, short underlined text links, hover isolation, visible keyboard focus, Escape/scrim close, and return focus/reader position. No sticky pointer highlighting or competing navigation/popup action.
- Exercise overview topics, contents, Previous/Next, saved position, and compact phone navigation. Labels, destination, current position, and page count remain synchronized after reopen and export/template reset.
- For grouped overviews, open each group and every topic; check one-open behavior, expanded fit, keyboard access, and full coverage in working, client, template, and phone-reader modes. Export must reject overflow hidden in a closed group. Template group labels must be neutral placeholders.
- Cold-open grouped cards at 1800px and 2560px wide before any resize: each automatic card must fill its grid track. Check narrow-to-wide resize and preserve explicit editor widths across Save and both exports. Check the compact grouped index separately: manual collapse, keyboard activation, the correct active entry when group order differs from page order, automatic group reveal after Next/Previous, and no long flat list when subject groups exist.
- Pinch in and out repeatedly on phones, including reader/canvas, open detail, editing, and reopened exports. Displayed content must magnify, not shrink to compensate; pinch alone must not rerender a diagram or steal text-edit focus. Check a genuine resize separately and disclose simulated versus physical-device coverage.

## 4. Editor and persistence

- Exercise all editor capabilities in [component-grammar.md](component-grammar.md) with actual pointer/keyboard actions, not only state setters. Include HTML reflow and SVG geometry resizing, diagram labels, popup title/lede/sections, and undo/redo of added/duplicated objects and popup changes.
- Save and reopen the working HTML. Confirm text, geometry, paint, additions, popup edits, theme, page, and explicit decision response/note persist over the validated baseline. Source identity/status stay protected; no extra authoring utilities or unsupported comments layer appear.
- Test the popup pencil from reading mode and from page-edit mode. Resize the frame and a text object, edit text, delete a section, undo/redo, then close and reopen. The page behind it must not become selectable; no large popup toolbar may consume its content area. Check frame and content edits after working Save and client export. Test all four palette buttons in both themes, including restoring Default over a configured authority; preserve the choice in Save and both exports without retaining palette controls in the client.
- For the card-hub template, check the intro, four peer cards and concluding card at wide and narrow widths. Desktop text stays fixed-size; compact desktop cards reflow without skinny tracks. Check the phone overview and full-size reader separately. Open every card's popup by pointer and keyboard, including after template export.

## 5. Exports and privacy

- Reopen Export HTML: the single composition, intended reader interactions, navigation, spacing, user formatting, and permitted clip bytes work offline without editor chrome or authoring rationale. Test the post-export Open exported HTML preview separately from disk-save confirmation; canceled/failed export must not present a stale success link.
- Client HTML must contain the reader runtime only: no file-picker or writable-file APIs, generated-file download code, Save responses control, or callable Save/Export methods. Inspect the exported bytes as well as the visible UI. Working copies and reusable templates retain saving/exporting. Client decision responses may persist in local browser storage but cannot be saved as another HTML file. This removes unnecessary capabilities; it does not guarantee acceptance by email attachment scanners.
- Reopen Export template: reusable geometry, informative heading/navigation placeholders, and editing work. Scan visible/hidden markup, inert data, SVG, URLs, images, metadata, recovery identifiers, decisions, added text, and popup edits for private matter. Source clips become labelled neutral frames, with identifying bytes/metadata removed.
- Check strict serialization, allowlisted rendering, and absence of remote code/font/image dependencies. For package/runtime changes, regenerate and reopen every shipping template and run relevant repository validators/browser tests; a showcase screenshot or privacy scan alone is insufficient.

## Handoff

Give the working file, what it explains, checks actually run, and remaining input, source-access, or validation gaps. Do not claim a browser check from code inspection or a verified source from a functioning popup.
