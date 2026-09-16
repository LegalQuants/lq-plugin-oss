# Mini-PRD: `/cite-check`

**Status:** Current public design note; this document is contributor documentation and is excluded from generated plugin packages.

**Maintainer:** John

*The authored `skills/litigation/cite-check/SKILL.md` is the package source. This note records the public design contract and known limits.*

## Product contract

`/cite-check` lets a nontechnical lawyer audit a brief, motion, filing, or excerpt against the supporting authorities supplied for that work product.

The skill reads the target and authority files with host-native document capabilities, writes temporary Markdown working copies when the host supports them, mechanically inventories every extractable text container, gives each prepared unit a terminal result, includes surrounding context, grounds findings in readable source material, reconciles the complete unit set, and emits a self-contained report artifact.

The method is source-grounded rather than memory-grounded: recognition of a citation is never verification, and a filename, URL, or model recollection is not source identity.

## Provider and jurisdiction boundary

The packaged Codex runner is the validated execution path for this release; “Codex-first” is a provider decision, not a restriction to United States law or sources.

The semantic contract is provider-neutral: the same intake, source manifest, review-unit scope, evidence requirements, result contract, completeness check, and report contract apply on every Codex execution surface.

Provider-specific mechanics belong in target-specific runtime material, not in shared semantic instructions. Any host adapter must preserve the same semantic contract and evidence requirements.

The skill reviews supplied readable authorities from any jurisdiction, including non-U.S. authorities, and must not silently reject them because of jurisdiction.

For non-U.S. or otherwise unfamiliar material, the report identifies the source and states the limits of the available authority and coverage; ethics and currentness guidance is representative, so the lawyer must confirm the applicable local professional-responsibility rules and whether the selected source supplies complete currentness treatment.

## Who invokes it

The user is a lawyer or legal professional who wants an auditable citation check before relying on a draft, filing, advice product, or other legal work product; no coding, package installation, API setup, or orchestration knowledge is assumed.

The lawyer supplies the target document and the supporting authority set, confirms the requested use, answers focused questions when context is material, and reviews the resulting report before relying on it.

## Intake and journey

Collect the target brief, motion, filing, or excerpt and its intended use, such as internal draft review, advice, or a proposed filing.

Collect the supporting authority files and any known source identity or pinpoint information; treat the supplied documents, not a citation string alone, as the evidence set.

Collect the tribunal, jurisdiction, and procedural posture when they affect citation meaning, controlling-authority analysis, or ethics context.

Collect an as-of date only when it affects citation meaning, controlling-authority analysis, currentness, or ethics context; do not demand irrelevant metadata.

Ask up to three focused questions for material missing context, or proceed with a clearly stated limitation when the lawyer elects not to supply it; never fabricate a tribunal, jurisdiction, posture, date, source identity, or intended use.

Use supplied authorities first. When an identifiable case is not in those files, search a public case source using citation metadata only. Report one simple outcome: the environment could not search; the search did not find the case and it may be hallucinated; or the case was found but was not supplied for substantive checking. A search hit does not verify what the case says.

## In-scope workflow

1. **Prep.** Prepare readable target and authority working copies through host-native capabilities, record extraction or readability limits, and mechanically inventory every extractable text container in source order with a stable ID, text, location, and relevant footnote anchor or surrounding context. Do not use a parent citation census or selector.

2. **Per-unit fan-out.** Create one independent review unit for each prepared text container, using one manifest and one terminal result contract for every unit, including explicit citation-free results. Run the packaged local runner so every prepared unit receives a fresh Codex session. If a host cannot run that script, preserve the same one-unit assignments with host workers or process them one at a time.

3. **Targeted retry.** Match each proposition or quotation to the readable supplied authority, preserve excerpts and pinpoints, and keep unresolved ambiguity visible. The runner gives one automatic retry when evidence fields are missing or inconsistent. It does not retry a substantive legal disagreement. If the evidence remains incomplete, keep the result amber and continue.

4. **Report and sense check.** Reconcile the manifest and results before reporting: every expected unit must be accounted for, and missing, invalid, or unreadable units must remain an explicit limitation rather than silently disappearing. Render the self-contained report and perform one bounded sense check, recording unresolved issues as caveats.

## Codex execution surfaces

The normal path is the bundled local Codex runner. It starts one fresh session per prepared unit; this one-unit fan-out is part of the cite-check method, not an optional optimization.

If that runner is unavailable, use the host's native workers with the same one-unit assignments, manifest, schema, and evidence requirements.

If native workers are unavailable, process the same units one at a time; changing the scheduler must not change the method, evidence standard, result contract, or report shape.

Every path uses the same units, evidence requirements, result contract, and report shape. The packaged runner is the expected path; host workers and one-at-a-time processing are availability fallbacks.

## Outputs

Emit a self-contained report artifact that identifies the target, intended use, authority set, and any retrieval or extraction limits. Keep model, sandbox, cache, and runner details in the internal run receipt rather than the lawyer-facing report.

Include one auditable result for every expected review unit, with the unit text and location, surrounding context, and any observed citation. The unit `disposition` is `citations_found` or `no_citations_found`. Each citation row carries `citation_kind`, `source_resolution`, `fabrication_indicators`, the three accuracy enums (`accuracy_of_source_characterization`, `pincite_accuracy`, `accuracy_of_direct_quotation`), matched source identity, excerpt, and pinpoint. The model makes the legal call. Deterministic code only checks the evidence envelope and maps it to red/amber/yellow/green: missing or invalid evidence is amber and cannot appear green. It does not decide whether a proposition is legally correct.

Include the final completeness reconciliation, assumptions, focused unresolved questions, jurisdiction and currentness limits, unavailable source coverage, and lawyer-facing next steps; do not collapse different failure modes into one vague “possibly incorrect” bucket.

## Responsibilities and nonclaims

The skill is responsible for faithful preparation, explicit unit accounting, independent source-grounded review, evidence preservation, reconciliation, and an honest report of what the run did and did not establish.

The lawyer remains responsible for supplying or confirming the relevant source universe and intake context, judging legal meaning and controlling effect, confirming local ethics and professional-responsibility requirements, deciding whether currentness research is sufficient, and giving final approval for reliance or filing.

The skill does not claim that a matched proposition is legally correct, controlling, good law, complete, or suitable for filing; it does not replace legal research, professional judgment, or lawyer review.

Uploaded-source review does not claim Shepard’s, KeyCite, equivalent citator treatment, comprehensive currentness, later history, amendment status, or completeness beyond the disclosed source universe; a currentness service or supplied results must be separately reviewed when needed.

## Explicit non-goals for this release

- No hosted MCP server.
- No remote retention.
- No tenant service for confidential work.
- No custom deterministic legal-citation parser; the small deterministic layer only validates result fields and source links.
- No bespoke DOCX, PDF, or OCR pipeline; unreadable material produces a limitation and a request for a readable copy.
- No promise of current citator treatment in uploaded-source mode.
- No provider expansion beyond OpenAI Codex in this phase.
- No autonomous filing, publishing, emailing, or other external action.
- No silent replacement of a missing, wrong, ambiguous, or inaccessible authority with a similar source.

## Release gate and deferred questions

The dedicated `/cite-check` path is the supported invocation. Other host adapters remain subject to their own capability checks.

The release gate is a cold-reader journey in which a nontechnical lawyer can provide the target and authority set, supply material intake context, understand the available Codex execution surfaces, and audit a self-contained report without relying on hidden setup.

### Runtime contract

The current runtime guidance is recorded in [the runner reference](../../../skills/litigation/cite-check/references/openai-codex-runtime.md). The packaged runner starts one fresh model session for every prepared unit. Host workers or one-at-a-time processing are availability fallbacks. Technical runtime details stay in internal receipts; the lawyer-facing report stays focused on the citations and the simple scope note.

## Runtime capability validation

The passive environment probe checks filesystem access, subprocess and concurrent-process support, and the required Codex CLI flags. Package identity and presentation metadata are not runtime capabilities: renaming a plugin, switching logo formats, or running from the source checkout must not force fallback when the required capabilities pass. Receipt validation retains the passive-probe markers and capability requirements. This preflight does not authenticate the CLI or grant host permissions; actual worker startup remains subject to the ephemeral read-only sandbox and existing source/output boundaries. Regression coverage lives in `packages/skill-tests/tests/cite-check/test_environment_probe.py` and `packages/skill-tests/tests/cite-check/test_runner.py`.
