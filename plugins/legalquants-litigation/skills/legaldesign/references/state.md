# Portable state

One inert JSON block carries the semantic record, decisions, popup content, and composition baseline. Saved HTML also carries authored geometry and object structure: transforms, sizes, colors, duplicates, added text boxes, and popup attachments. Save serializes both together; browser recovery mirrors both with the same artifact identity. Standalone opening, editing, saving, and exporting require no server, host, or model.

## The block

```html
<script id="legaldesign-state" type="application/json">{ "schema": "legaldesign.state.v1", … }</script>
```

New composed working state uses `sourceSchemaVersion: legaldesign.build.v4`. Its authoring fields follow [build.md](build.md); this reference covers their portable representation and legacy recovery.

| Field | Portable contract |
| --- | --- |
| `schema` | `legaldesign.state.v1`. |
| `artifactId`, `savedAt` | Stable working-file ID and ISO timestamp of last Save (null before Save). Exported copies derive location-scoped instance IDs to isolate recovery. |
| `brief`, `style` | Preserve the validated brief and authority reference. New `brief.form` is `one-page` or `slide-brief`. Style mapping cannot alter source meaning or fixed UI. |
| `composition`, `overview`, `claims` | The one v4 composition, typed first-section overview, and stable material-claim ledger. Keep section order, placements, and `rowSpan` (default one). |
| `units` | Object keyed by unit ID, retaining kind/role, claim, relationship, candidates, claim/evidence references, placeholder, and edits. Each new unit has `variants.a` and `selected: a` as compatibility sentinels, not choices. Its variant carries encoding and allowlisted copy HTML or registered figure component/parameters. Decision units also retain their question/options and selection/custom/note permissions. |
| `evidence` | Object keyed by `data-evidence-id`, preserving source/claim references, identity/status, original, detail, and purpose-specific popup presentation. Compatibility cite/locator/excerpt/link/image data do not impose a visible layout. Original identity and status are not free-text editor fields. |
| `review` | `theme` (`light\|dark`), `location` (zero-based page index or null), and `decisions` keyed by explicit decision unit. Single responses are a choice or `{choice, custom, note}`; multiple responses are choices or `{choices, custom, note}`. New v4 state has no `review.approach`. |
| `history` | Optional change entries (`at`, `what`), capped at 200. |

Issue sections retain `issueLayout` and its analysis/support unit references.
Source-preview units retain the `sourcePreview` flag and generated inert visible
HTML in working state. The client preserves the rendered layout and permitted
preview; the template remaps slot IDs and replaces source text/pixels/captions
with neutral placeholders. A source preview is not a new source identity.

A supported original URL becomes validated absolute HTTP(S) `link`; a local or unsupported original stays structured in `original` with `link: null`. Optional build `exhibit` maps to `evidence.image` with `status: supplied-unverified`, embedded `data`, image `sha256`, `sourceSha256`, `locator`, `captureMethod`, `capturedAt`, and `alt`. This is capture integrity, not verification; preserve separate evidence status and the safeguards in [evidence.md](evidence.md).

## Recovery and persistence

1. Mirror each working-file change to `localStorage['legaldesign:' + artifactId + ':v1']`. Export modes have separate namespaces, opaque blueprint/instance identities, and no working-file recovery data. Location-scoped instances distinguish copied files while ignoring navigation query strings/fragments. Ordinary template exports receive a fresh non-matter blueprint ID; packaged blueprints may use deterministic IDs for build checks. If a newer applicable mirror exists, offer a Restore/Discard banner, not a dialog.
2. Save writes in place only when the browser permits it after file selection; otherwise download the HTML. A host may supply a save path, but standalone correctness never depends on it. Serialize and round-trip-check the inert block under [build.md](build.md); mismatch is an error, not a silent fallback.
3. Reopen the same composition, valid page position, edits, theme, and explicit decision responses/notes. Diagram labels and each rendered popup title/lede/section heading/body commit to state and recovery. Presentation edits never upgrade source status or rewrite original identity.
4. Manual geometry and edits overlay the validated baseline. Preserve added/duplicated objects, independent popup attachments, relative group positions, and correct screen distance in scaled SVGs. Undo restores detached detail and its attachment. Editor behavior is defined once in [component-grammar.md](component-grammar.md).

## Export representation

| Data | Working file | Export HTML | Export template |
| --- | --- | --- | --- |
| Brief and authority | Full validated data | Generic interaction metadata; sources/assumptions/gaps and local `style.ref` cleared | Descriptive placeholders and safe color roles |
| Composition, overview, claims, encoding | Full authoring record | Minimal section/layout and overview navigation references retained; rationale, claims, and encoding removed | Reusable topology and overview links with neutral content |
| Units and edits | Complete single-rendering units and overrides | Only rendered units; edited visible HTML canonicalized into minimal valid variants | Structure/geometry retained; all matter-bearing fields replaced |
| Rationales, claim text, candidates, figure parameters | Full | Removed | Neutral structural content, never realistic invented matter |
| Evidence | Full structured record | Permitted source detail/clip retained in fixed popup DOM; portable evidence map emptied | Exact text, URLs, image bytes, and identifying metadata removed |
| Decisions, theme, location | Current values | Intended decisions remain live; valid location/theme retained | Decisions cleared; location reset; theme retained |

Client state is a minimal interaction store, not an authoring archive. Keep only decisions for rendered units and an opaque location-scoped identity; the recipient must not need the author's brief, filesystem paths, claim ledger, or component parameters. Resolved palette roles are embedded. Template placeholders cover list, table, card, diagram, popup, navigation, numeric, and added/edited content—not just visible headlines. Apply the complete privacy and reopened-export checks in [qa.md](qa.md).

## v2/v3 compatibility only

Older v1 files may omit `sourceSchemaVersion`; v2 imports may retain per-unit variants, edits, axis, and why data. Approach-led v3 state may retain `approaches.a/b`, two distinct roots, `review.approach`, and independent page locations/overrides. Preserve those structures when reopening or explicitly importing them; do not expose legacy per-unit A/B or Why controls in new output or convert a legacy file by dropping material.

For legacy two-approach files, switching restores a valid location for that approach, never an out-of-range page from the other. Their client export fixes the selected DOM and removes the other root/orphan units; their template export may preserve both legacy topologies. Legacy `review.comments` and `reactions` are preserved but unused in working recovery, then removed from exports. These compatibility behaviors do not add an approach selector or universal feedback layer to a new v4 composition.
