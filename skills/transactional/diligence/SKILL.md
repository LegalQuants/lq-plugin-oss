---
name: diligence
description: >-
  Use when a data room, deal folder, or contract portfolio needs review
  against an issue checklist and the lawyer needs factual results they can
  inspect: every match pin-cited, every agreement accounted for, scoped
  negatives shown, and everything the run could not resolve kept visible.
  Builds a file and contract-family manifest, compiles the lawyer's checklist
  into fixed review schemas, gates twice before the long run, and delivers a
  coverage-receipted issue/agreement HTML crosswalk plus a further-enquiries
  register. Trigger on "review this data room",
  "run diligence", "check these contracts against our list", or a folder of
  agreements plus any checklist, even without the word diligence.
---

# Diligence

## When to use
- A folder of agreements (a data room, a portfolio, a deal file) needs review against the lawyer's issues, with receipts.
- The gap report alone is wanted: what is missing, unreadable, or duplicated in a room nobody has read yet.
- The core output is factual: what the supplied agreement text says about each approved issue, where it says it, and what could not be determined. Risk ranking, recommendations, and conclusions about legal effect require a separate instruction.
- Out of scope: drafting or negotiating documents, litigation document review (that fork is the /docreview sibling), producing or serving anything. The skill prepares; it never sends, files, or publishes.

## Before you start
- Read `references/schemas.md`, `references/framework-schema.md`, and
  `references/review-copies.schema.json` in full. They are the data contracts;
  every artifact you produce must match them.
- Before producing any lawyer-facing HTML, read `references/review-ui.md` in
  full. It is the portable brand, accessibility, offline, and source-rendering
  contract for the setup, test-results, and final crosswalk pages.
- Read your `[diligence]` lines in `lqplaybook.md` if the file exists (default lenses, optional materiality rules, report voice, register format) and apply them. Read nothing else from the profile; it never shapes work product. Write nothing to the profile; the scribe owns it. When the user reveals a durable preference in-session, propose the exact `[diligence]` line and write it only on an explicit yes.
- Confidentiality: no client-identifying facts in any artifact except the report surfaces themselves. Run artifacts live in one temp master dataset directory for this run; delete it at completion. Never transmit anything anywhere.
- All scripts live in `scripts/`. Pass `--extractor stdlib` only in evals; real runs use the default so poppler is preferred when installed.
- Before substantive unit/lens dispatch, read
  `references/shared/execution-modes.md`,
  `references/shared/finding-worker-prompt.md`, and
  `references/shared/finding-worker.schema.json`. When an authorized local
  headless runtime will execute the jobs, also read <!-- vendor-neutral-waiver: this optional reference documents one local headless adapter; native and sequential paths remain complete. -->`references/openai-codex-runtime.md`.

## Execution portability

The bundled scripts named below are the normal path because they enforce deterministic schemas, receipts, and fail-closed gates. If a host cannot execute local scripts, preserve the same artifact shapes, assignments, validations, and gate conditions with host-native document and data capabilities; process isolated assignments sequentially when parallel workers are unavailable. Do not omit a validation because its helper cannot run. If the host cannot reproduce a required check or receipt, stop at that gate and report the limitation instead of claiming completion.

The substantive maker lane lives under `scripts/shared/` and is byte-identical
to the DocReview runtime. `prepare_review_jobs.py` materializes compact
assignments; `run_review_jobs.py` defaults to five bounded workers, preserves
immutable attempts, journals progress, and admits results through
`admit_finding_result.py`. Before fan-out, surface the runner's concurrency and
resource disclosure. Do not read or modify a host's global configuration.
Long runs use `--detach`; parked jobs require a receipted unpark.

## Workflow

1. **Inventory and review copies.** `build_manifest.py --root <room> --out manifest.json --gaps gap-report.json`. If the room ships an index (spreadsheet or numbered folders), `reconcile_index.py --index <file> --manifest manifest.json --out gap-report.json`. Mark a request list, schedule, or other instruction document `review_role: "runner-control"` only when the lawyer confirms it governs the run rather than being an agreement to review; everything else defaults to `substantive`. Runner-control files remain in the corpus census and source table but never become sample or full-run units. Then `extract_metadata_prep.py --manifest manifest.json --room-root <room> --outdir <run>`. Build the immutable lawyer-review layer with `review_copies.py build --manifest manifest.json --source-root <room> --sidecar <run>/review-copies.json --bundle-root review-copies --mode auto`. Keep the sidecar and every lawyer-facing HTML file in the same run directory so its relative content-addressed references remain valid. Exit 0 means every source and attachment is review-ready; exit 1 means the hash-bound receipt is valid but at least one item is **Needs rendering**; exit 2 means integrity or containment failed. Report counts to the user: files, control inputs, substantive files, readability split, review-copy status, and gaps so far.
2. **Metadata model pass.** For each id in `worklist.json`, use one fresh worker per document when the host exposes parallel workers; otherwise process the same worklist sequentially, one document at a time, retaining only that document's schema output before starting the next. Use a small model reading only the opening pages and signature block, returning the metadata JSON shape in `references/schemas.md` exactly. Every model-sourced field carries a verbatim quote. Cap retries at 2 per document; park failures as metadata-incomplete and continue. Then `verify_quotes.py --metadata <run>/metadata --room-root <room> --write`: parked quotes stay parked; never hand-wave one through.
3. **Relationships.** `block_candidates.py`, then `build_families.py` (pass `--room-root` so model-proposed edges are quote-verified on entry). Model edge resolution, where needed, sends only the two metadata records to the model, never the documents.
4. **Compile the checklist.** Take the lawyer's checklist in whatever form it arrives. Compile it to `framework.json` per `references/framework-schema.md`: conservative factual hit rules, empty exclusion lists, and the contract's unresolved rule. Omit `materiality` when the lawyer did not supply ranking rules; never invent or default a severity. `validate_framework.py` must pass (capped retries, then ask the lawyer rather than loop), then `render_readback.py`. Every issue must trace to a named runner-control source input.
5. **Confirm the review setup (internal Gate 1).** Pick five representative
   substantive units, or every unit when the collection has five or fewer, and
   write `sample-scope.json` with `framework_version`, `sample_size`,
   `selection_basis`, and ordered `proposed_units` carrying `doc_id`, a
   plain-language `label`, and `reason`. Run `render_gate1.py --manifest
   --metadata <run>/metadata --families --gaps --readback --sample sample-scope.json --source-prefix
   <relative source folder> --review-copies <run>/review-copies.json
   --document-root <room> --out <run>/review-setup.html`. Show that page, not an
   internal gate receipt. It asks whether the questions, collection, and scope
   are right; implementation terms and stable IDs stay in collapsed technical
   details. The lawyer confirms or regroups families and approves the exact
   setup statement in their reply; record confirmation by writing
   `families.confirmed.json`. A bare "continue" does not advance this gate.
   Downstream reads only the confirmed file.
6. **Review the test results (internal Gate 2).** Run every approved issue
   against each sampled unit, then `render_sample.py --framework --findings
   --manifest --source-prefix <relative source folder> --review-copies
   <run>/review-copies.json --document-root <room> --out
   <run>/review-test-results.html`. Show factual matches, scoped negatives,
   results needing a decision, in-page review copies, and plain-language match definitions.
   Stable IDs, framework versioning, and raw schema field names stay in
   collapsed technical receipts. Lawyer feedback names the review question and
   describes what should count differently; translate that feedback into the
   corresponding framework fields, recompile as version N+1, validate, and
   rerun the sample when the issue test changes. Approval freezes that version.
7. **Scale.** Build and approve the targeted or full review plan, including the
   higher-capability model class, medium-or-higher reasoning effort,
   request-batch limit, projected model-call count, and cost basis, then run
   `scripts/shared/prepare_review_jobs.py`. Apply the substantive mapping
   quality gate in `references/shared/execution-modes.md`: no model context may
   receive more than 12 issues, and the sample must recover every
   source-verified positive under the same route used for scale. Use
   `scripts/shared/run_review_jobs.py run` for an authorized scripted fan-out;
   otherwise give the same bounded assignments to native workers or process
   them sequentially. A unit is the confirmed family where
   relationships exist, else the single agreement. Each worker returns one
   ordered determination per issue, cites documents by ordinal, and never
   constructs stable document or finding IDs. The admitter constructs those
   IDs, expands compact absent rows, and validates every receipt before writing
   the canonical checkpoint. A present result requires a verbatim quote and
   section locator. `current_position: true` is allowed only when the whole
   family, including later amendments, was read. Retry rejected judgment at
   most twice; keep transport failures on their separate budget; park failures
   visibly. Report `progress.json` and `parked.json`. Resume only validated
   attempts and checkpoints; never rerun admitted or silently unparked units.
8. **Verify.** Run `verify_finding_quotes.py --findings ... --manifest ... --room-root ... --out findings.quote-checked.json`, then run `build_checker_plan.py --findings findings.quote-checked.json --framework ... --out checker-plan.json`. The first script confirms every present quote or changes the result to unresolved. The checker plan selects every remaining present finding in the approved sample or full ledger, never by severity: a factual finding cannot escape checking merely because materiality was omitted. A separate checker receives the finding, quote, governing framework item, and source text without the maker's reasoning and returns `{checker_plan_id, finding_id, verdict, objection}`. Run `merge_checker_results.py --findings findings.quote-checked.json --checker-plan checker-plan.json --results-dir ... --out findings.checked.json`; missing, stale, or non-confirming checker results fail closed or become unresolved. Keep the mechanical quote receipt and independent checker receipt distinct.
9. **Gate 3 and delivery.** Run `reconcile_counts.py` first. It must prove the complete issue × substantive-unit cross-product, with parked units visible; if it fails, fix the run, never the numbers. Re-run `review_copies.py verify --manifest ... --source-root <room> --sidecar <run>/review-copies.json`, then run `render_crosswalk.py --framework ... --findings ... --manifest ... --families ... --gaps ... --source-prefix <relative source folder> --review-copies <run>/review-copies.json --document-root <room> --out <run>/crosswalk.html --receipt <run>/crosswalk-receipt.json` and `export_register.py`. The default Issues tab answers “where was this issue found?”; Agreements reverses the same ledger and embeds each source once; Scope & gaps accounts for control inputs, substantive sources, families, parked items, unreadable items, missing materials, and control-input review copies; Audit carries input and sidecar hashes. The lawyer rules on items labeled **Needs a decision** and decides how to use the factual output. A valid receipt with any **Needs rendering** item keeps the crosswalk receipt failed until a verified copy is rebuilt. Do not add recommendations, risk rankings, or a claim that the surface is legal advice unless separately instructed.

## Conventions
- Deterministic artifacts throughout: sorted keys, no timestamps, no absolute paths. Same inputs, same bytes.
- Every page shown to the lawyer follows the same review convention: state the
  decision in plain language, use the shared `lq-lawyer-review-v1` brand
  contract, keep amber for discrete items needing attention rather than the
  whole page, support light/dark and 320px screens, expose keyboard focus, and
  place stable IDs and runner mechanics in collapsed technical receipts or the
  Audit tab. Use **Needs a decision** for the visible unresolved state. Internal
  `render_report.py` output is a reconciliation receipt, not a substitute for
  the lawyer-facing setup, test-results, or issue/agreement crosswalk pages.
- `/legaldesign` is not a runtime dependency of these deterministic review
  pages. It may consume an approved Diligence result later only when the lawyer
  separately asks for a client-facing explainer. Firm branding stored in a
  different playbook namespace does not silently change Diligence output.
- A source link proves provenance but is not the review experience. Apply the
  renderability gate in `references/review-ui.md`: every reviewed document and
  separately reviewable attachment needs an in-page representation bound to
  the source ID and hash. Use the built-in safe preview, then an available
  open-source renderer, then a firm-selected native or legal-grade renderer.
  A missing or stale render becomes **Needs rendering** and stops approval for
  dependent results; it never changes a model proposal or evidence receipt.
  `review-copies.json` is additive presentation evidence only. Revalidation
  binds its manifest digest, full source hashes, attachment hashes, derivative
  hashes, and exact bundle file set before any embed is emitted. Never copy a
  sidecar between manifests or edit it by hand; rebuild it. It does not mutate
  or replace a model proposal, finding, framework, quote receipt, checker
  receipt, or lawyer ruling.
- A claim without a verified verbatim quote does not enter any artifact. Parked means visible, never silently dropped.
- “Not found” is always scoped to the supplied visible text in the reviewed agreement unit. It is not a portfolio-wide absence claim and does not cover missing materials.
- The framework is the only instruction channel to workers. If a calibration is not a framework field, it does not exist.
- Model routing: a small model may perform per-document metadata reads. Use a
  higher-capability reasoning model at medium effort or above for substantive
  issue mapping, compilation, edge residue, verification, and synthesis. The
  user may override after seeing the recall, cost, and speed tradeoff; honor
  that choice and record it.
- Tool cascade for extraction and review copies: built-in stdlib probes and
  safe text/email/image previews, then Poppler or LibreOffice when available,
  then the firm's selected legal-grade renderer. Say which rung ran; never pip
  install inside a run.

## Dependencies
Python 3 stdlib. Optional and preferred: Poppler (`pdfinfo`, `pdftotext`,
`pdftoppm`) and LibreOffice. Nothing else; never pip install inside a run. The
deterministic stdlib path still renders escaped text/EML, common images,
browser PDFs, and safe visible text from DOCX/XLSX/PPTX; optional tools add
receipted page images.

## Final checks
- `reconcile_counts.py` exits 0: every approved issue has exactly one result for every reviewable substantive unit, or that unit is visibly parked; runner-control files remain separately accounted for.
- Every present finding carries a quote, section locator, deterministic quote receipt, and the checker coverage required by the approved plan.
- review-setup.html, review-test-results.html, and crosswalk.html are each rendered and looked at in light and dark before showing the user.
- Every interaction works at 320px and desktop width, and every in-scope source
  has a verified in-page review representation; otherwise the run remains at
  **Needs rendering** rather than advancing on a raw-file link.
- The frozen framework version is recorded in `findings.json` and matches what Gate 2 approved.
- The sample recovered every source-verified positive under the same model
  class, effort, and request-batch limit used for scale; schema validity and
  runtime speed alone are not calibration.
- The temp master dataset is deleted; the deliverables and the run's JSON artifacts are in the matter folder; nothing was transmitted.
