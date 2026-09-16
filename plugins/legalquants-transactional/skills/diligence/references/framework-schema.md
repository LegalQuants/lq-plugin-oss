# The checklist compiler contract

The compiler turns the lawyer's checklist into `framework.json`, the single file every worker is judged against. This document is the contract; `framework.schema.json` beside it is the machine-checkable version (`validate_framework.py` enforces it).

Three rules govern everything here:

1. **The framework is the only instruction channel.** The orchestrator injects the approved `framework.json` verbatim into every worker. Nothing else about the checklist reaches a worker. If a calibration is not written in the framework, it does not exist.
2. **Versions are immutable.** Every recompile increments `framework_version` and writes a new file (`framework.v3.json`). Gate 2 approval freezes one version; the run records which version it used. Calibration history is the diff between versions.
3. **Knobs are fields.** Calibration at Gate 2 means editing named fields, never freehand instructions to a worker.

## framework.json shape

```json
{
  "framework_version": 2,
  "approved": false,
  "source_inputs": [
    {"kind": "checklist", "label": "client DD request list"},
    {"kind": "rfp", "label": "defense RFP set, served 2026-05-01"}
  ],
  "lenses": [
    {
      "lens_id": "change-of-control",
      "name": "Change of control and assignment",
      "items": [
        {
          "issue_id": "coc-01",
          "question": "Does the agreement restrict change of control or assignment?",
          "hit_rule": "Consent required for change of control or assignment, or a termination right triggered by either.",
          "exclusions": ["Notice-only assignment clauses", "Assignment permitted to affiliates without consent"],
          "evidence": {
            "required": "verbatim quote plus section reference",
            "unresolved_when": "The clause cross-references a schedule or definition not in the data room, or the quote cannot be located"
          },
          "answer_shape": {
            "statuses": ["present", "absent", "unresolved"],
            "characterization_max_words": 30,
            "template": "SECTION: state the responsive language factually (QUOTE)."
          },
          "disposition": "report",
          "overlap_owner": null
        }
      ]
    }
  ]
}
```

Field meanings, and which are calibration knobs (K):

- `question`: the checklist item, in the lawyer's own terms.
- `hit_rule` (K): what counts as a finding. The most load-bearing field in the skill.
- `exclusions` (K): what looks like a hit and is not. Where Gate 2 noise complaints land.
- `materiality` (optional K): ranking rules only when the lawyer supplies them. Omit the field when the source checklist is silent; the compiler never invents a default severity. If present, `bands` and `default` operate as before.
- `evidence.required`: fixed at quote plus section; not a knob.
- `evidence.unresolved_when` (K): when a worker must stop deciding and route to the Gate 3 queue.
- `answer_shape.template` and `characterization_max_words` (K): what the finding text looks like.
- `disposition`: `report` (findings report), `register` (also feeds the further-enquiries register), `queue` (straight to the unresolved queue for a human).
- `overlap_owner` (K): when two lenses can catch the same clause, the lens_id that owns it; the other lens suppresses the duplicate.

## The read-back

`render_readback.py` derives `framework-readback.json` from framework.json. It preserves `framework_version` and `approved`, then carries one row per item with `{lens, issue_id, question, hit_rule, materiality, evidence_required}`. When `materiality` is omitted, the read-back says `not requested`. That file feeds the Gate 1 surface (render_gate1.py `--readback`). The read-back is a deliverable the lawyer approves, never an internal artifact; it must stay plain English, one line per field, no schema jargon.

## findings.json (the ledger the workers fill)

```json
{
  "framework_version": 2,
  "findings": [
    {
      "finding_id": "coc-01/sha256:9f3a1c04b2d7",
      "issue_id": "coc-01",
      "lens_id": "change-of-control",
      "unit_id": "sha256:aa10b2c9d001",
      "doc_id": "sha256:9f3a1c04b2d7",
      "status": "present",
      "section": "9.2",
      "quote": "neither party may assign this Agreement without the prior written consent",
      "characterization": "9.2: consent required on assignment and change of control.",
      "quote_verification": {"status": "confirmed", "checker": "deterministic-text-match"},
      "verification": {"status": "confirmed", "checker": "independent"},
      "current_position": true
    }
  ],
  "parked": [
    {"doc_id": "sha256:0c77d1e2f3a4", "reason": "metadata-incomplete"}
  ]
}
```

- `finding_id` is `issue_id/doc_id`: stable, so response handling can attach in v1.1.
- `unit_id` is the family when relationships exist, else the doc itself. `current_position: true` asserts the finding reflects the post-amendment position; a worker reading an amended family must set it and quote the governing text, never a superseded term.
- `band` and `band_basis` are optional and appear only when the approved framework item contains `materiality`.
- Every present quote receives a deterministic `quote_verification` receipt. Independent checker coverage follows the approved sample or full plan and is never selected by `band`.
- Checker outputs contain exactly `{checker_plan_id, finding_id, verdict, objection}`. `verdict` is `confirmed | refuted | unresolved`; a non-confirming verdict requires an objection and changes the finding to unresolved. Missing, duplicated, or stale checker outputs refuse the merge.
- Coverage invariant: every issue has exactly one finding for every reviewable substantive unit, unless that unit is parked. `reconcile_counts.py` refuses duplicate or missing issue/unit pairs and excludes confirmed `runner-control` files from substantive units.

## Compiler behavior (the model pass)

The compiler is a model step the SKILL.md orchestrates, with these constraints: it reads the lawyer's raw inputs (any format), proposes lenses and items, and must produce schema-valid output (validate_framework.py gates it, capped retries). It never invents materiality thresholds or a default severity: where the lawyer's input is silent, the item omits `materiality`, and the read-back marks it `not requested`. Vague inputs compile to conservative factual hit rules plus an explicit empty exclusions list: over-inclusion is tuned down at Gate 2, silence is never tuned up. The calibration eval (case-02) holds an example.
