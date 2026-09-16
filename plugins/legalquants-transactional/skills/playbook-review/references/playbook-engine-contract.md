# Playbook Engine artifact contract

The canonical JSON Schema is `../schemas/playbook-engine.schema.json`. Both
skills ship the same bytes. JSON is canonical; Markdown and HTML are views.

## Source manifest

`source-manifest.json` freezes the declared input boundary, file order, source
role, SHA-256, readability, page-reading method, warnings, and stable element
IDs. It also indexes deterministically recognised definitions with a stable term
ID, exact definition text, document hash, and element ID. Preserve exact source
text in the element index. For a scanned page, update `pending-vision` only after
the host has rendered and read the page.

The manifest's `manifestSha256` is the SHA-256 of the canonical artifact type,
schema version, input boundary, and document records. It excludes the manifest
ID, creation time, and the hash field itself, so repeating the same census at
the same boundary produces the same content identity. Downstream artifacts
carry the stored value.

## Contract playbook

`playbook.json` has `artifactType: contract-playbook` and schema version `1.0`.
Its `sourceManifestSha256` binds it to the source census.

An issue contains:

- `issueId`, `topic`, and `status`;
- `basePosition`: summary, preferred wording, consecutive fallbacks, red line,
  and priority;
- source provenance with document hash, element ID, exact text, and source role;
  and
- dependency issue IDs.

Only status `approved` is operative. Candidate and conflicted issues remain
visible but do not control a review.

A Matter Lens contains approved or candidate adjustments. Each adjustment
targets an issue and supplies explicit field changes such as
`preferred.text`, `redLine`, or the whole `fallbacks` list. It never activates
itself.

## Matter Lens activation and effective stance

`matter-lens-activation` records separately:

- `suggestedLenses`, which are non-operative recommendations;
- `activatedLenses`, which the lawyer explicitly selected;
- one-off `matterInstructions`; and
- `confirmedByLawyer`, which must be true even when the selection is Standard
  Baseline alone.

The compiler applies Standard Baseline, then compatible lawyer-activated lens
adjustments, then explicit matter instructions. Two active lenses that assign
different values to the same issue field block the stance. The compiler never
chooses one. An explicit matter instruction may override a lens and remains in
the trace; conflicting matter instructions block the stance.

`effective-stance.json` is usable only when `status` is `ready`. It records the
activated and suggested lenses separately, every applied trace, conflicts, and
its own canonical hash.

## Term map and substantial equivalence

`term-map.json` binds the approved playbook source manifest to the contract
source manifest. It has one entry per distinct approved house term.

- `exact`: same normalized label and definition text; deterministic.
- `equivalent`: different drafting with substantially the same legal scope;
  model judgment or lawyer confirmation with both definitions cited.
- `undefined`: no counterparty definition; propose a separate definition
  insertion before using the house term.
- `defined-differently`: the scopes differ; hard-stop affected drafting for the
  lawyer.
- `unresolved`: deterministic matching found no safe answer; non-operative
  until assessed.

The reviewer judges alignment by substantive legal and commercial effect. A
wording difference alone is not a deviation. Approved house wording is a
provenance source, not a style template to impose. Suggested drafting passes
through the validated term map and makes only the minimum change needed.

## Issues list and markup

`issues-list.json` is the reviewer work product. Every issue is anchored by
document hash and element ID. `originalText` is the exact source passage under
review. `proposedText` is the clean suggested revision.

`markupSegments` is an ordered list of:

```json
{"op": "equal | delete | insert", "text": "non-empty exact text"}
```

Concatenating `equal + delete` must reproduce `originalText` byte for byte.
Concatenating `equal + insert` must reproduce `proposedText` byte for byte.
Renderers escape all text before showing deletions and insertions. Raw HTML is
never stored in the canonical record.

Drafting provenance is one of `approved-playbook`, `candidate-drafting`,
`mixed`, or `none`. A playbook gap is never disguised as approved policy.

## Coverage receipt

Coverage has three independent reconciliations:

- documents: completed + parked + unreadable = expected;
- elements: completed + parked + unreadable = expected; and
- operative rules: evaluated + not applicable + blocked = expected.

`reconciled: true` is allowed only when all three equations hold. A receipt
proves accounting, not the correctness of legal judgment.
