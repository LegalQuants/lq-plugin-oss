# Agentic Review Protocol

Read this reference only when subagents or equivalent model workers are available for definition discovery or semantic review.

## Roles

- **Discovery workers** inspect bounded, overlapping seed regions and submit `CandidateProposal` records.
- **Retriever** executes only the bounded `ContextRequest` actions permitted by the current capability profile.
- **Review workers** independently adjudicate every detected term from neutral term-and-context envelopes and submit a proposal revision rather than replacing an earlier record.
- **Reducer** validates revision chains, collapses exact normalized duplicates, and preserves non-exact candidates for semantic review.
- **Supervisor** owns the private mapping between review IDs and deterministic provenance, the canonical ledger, `ReviewTrace` records, and semantic `Finding` records. Workers never mutate shared facts concurrently.

If subagents are unavailable, one model may perform the same roles sequentially. Record that execution shape in `methods_run`; do not claim independent review.

## Stage barrier and default execution shape

Run stages in this order:

1. finish recall-only quoted-label scanning, lexical candidate closure, and every bounded discovery worker;
2. wait for all discovery results;
3. validate, reconcile, and exact-deduplicate proposals;
4. persist and freeze the complete semantic queue, including its count;
5. review that frozen queue in parallel batches or one complete pass;
6. freeze the accepted defined-term set and deterministically re-scan the full parsed document for each accepted canonical term and alias;
7. build the occurrence queue from that fresh usage index and review every non-definition occurrence, including exact canonical forms and allowed aliases; and
8. finalize artifacts once.

Parallelism is allowed within a stage, not across the discovery-to-semantic barrier. Never begin semantic review against an initial partial queue and then issue extra passes as discovery adds candidates. A candidate found after the freeze invalidates that queue and requires one deliberate rebuild.

Complete discovery even when it finds no additional labels: each discovery packet
returns its packet ordinal with an empty `rows` array. The packaged `expand`
command preserves these validated responses in the bundle's `discovery_review`,
bound to the source, prompt, and discovery queue hashes. Preserve that field when
expanding subsequent stages. The pipeline revalidates the responses against its
current discovery manifest and requires all discovered proposals in the bundle.
An empty semantic queue can complete only with this validated discovery record.
An empty occurrence queue completes after semantic review completes; no worker
decision or model call is invented for an empty queue. Missing or stale discovery
responses cannot turn a zero-candidate deterministic scan into a completed review.

Use one complete semantic pass by default. Independent duplicate passes are an evaluation or heightened-assurance option, not the ordinary execution path. When duplicate passes are requested, compare them mechanically and send only disagreements to a tie-break reviewer. Record elapsed time, worker-call count, queue count, and disagreement count for each model stage.

The pre-semantic usage scan supports candidate closure only. It is not authoritative after agent-discovered terms have been accepted. The post-finalization scan must start from the accepted term registry rather than filtering or extending the initial usage list. Every non-definition match enters occurrence-level semantic review, including exact canonical forms and allowed aliases. Preserve aliases and non-canonical case, number, spacing, possessive, or composite source forms as first-class variant records; every source occurrence is a separate instance linked to its variant.

## Candidate universe and recall policy

The semantic queue is the union of:

- every label emitted by the quoted-text scanner;
- every potential undefined-term candidate emitted by deterministic usage discovery; and
- every additional term proposed by a discovery worker.

The quoted-label scanner recognizes paired straight double quotes (`"Term"`), curly double quotes (`“Term”`), and guillemets (`«Term»`). Parentheses or collective wording around those labels do not affect capture, and each quoted label is a separate candidate. Unquoted parentheticals such as `(Term)`, single-quoted labels, multiline labels, non-alphabetic labels, and labels over 120 characters require discovery-worker review rather than quote-regex capture.

Review the entire exact-normalized, deduplicated queue. Do not sample, rank away, or silently omit low-confidence candidates in a full-capability run. Deterministic discovery is intentionally over-inclusive because prematurely suppressing noisy candidates creates false negatives before the semantic layer can inspect context. Do not add contextual noise guards merely to shrink the semantic queue. Safety, corrupt-input, and structurally impossible records may still fail closed before review.

Heading recognition must not remove candidates. If every detected location is in a heading-like block, record the supervisor-side structural hint `likely_heading`; if only some locations are, record `includes_likely_heading_occurrence`. These are debugging and review-provenance tags, not reviewer inputs or conclusions. The semantic worker receives the exact source context and decides whether the text is a defined-term use, heading noise, or something else.

Exact normalization is an internal deduplication mechanism only. Similar but non-identical terms remain separate until semantic review. A full-capability run is not review-complete while any queued term lacks a final decision or an explicit `needs_context`, `needs_review`, or `insufficient_evidence` state.

## Compact semantic-review packet

Canonical discovery, semantic, occurrence, and dispatch prompts ship under `references/prompts/` and are loaded by the packaged prompt registry. The registry supplies the instruction, fixed output shape, numeric decision legend, prompt version, and content hash. Packets embed the complete stage instruction, so a generic worker needs only the packet and the standardized dispatch task. Do not use a separately maintained prompt or a predefined-agent profile.

Create an opaque review ID for each queued term, keep it private, and assign a deterministic run-local numeric ordinal. The review worker receives only:

1. the numeric item ordinal;
2. a length-preserving ASCII projection of the source spelling;
3. numbered, length-preserving ASCII projections of bounded source context around candidate locations;
4. additional bounded source context retrieved for ambiguous candidates; and
5. the compact stage instruction and numeric decision legend.

Do **not** pass the detector origin, originating rule, candidate class, rank, score, severity, confidence, or a statement that a lexical layer considered the term defined or undefined. Do not pass a normalized key unless it is necessary to execute a reviewer-requested search; the supervisor or retriever performs that search without exposing detector provenance.

The private manifest retains the exact original Unicode source. The projection substitutes one ASCII character for each non-ASCII source character, so offsets remain stable and expansion can reconstruct exact source spelling without exposing private IDs or asking the reviewer to repeat text. Context-pool entries use short string keys only for packet deduplication; each item maps those keys to item-local numeric context ordinals, and workers cite only the numeric ordinals. The manifest also records the packaged prompt version and SHA-256 used to build the packet.

The reviewer, not regex, identifies whether and how the source assigns meaning. A `confirmed_defined` response identifies `[context, start, end]`; the supervisor reconstructs the exact definition text from the original private source slice and fails closed on any bad index or offset.

Use `confirmed_alias` when the candidate is one of multiple labels assigned to the same antecedent and another queued label is the canonical term. Return the canonical item's numeric ordinal, cite a context containing both labels, and use a null definition span. Prefer a substantive party or concept label over a pronoun; if co-equal labels remain, use their source order. Synthetic examples:

- `the supplying entity (together, "Provider", "we")` -> `Provider` is `confirmed_defined`; `we` is `confirmed_alias` with `canonical_term: "Provider"`.
- `the purchasing entity ("Buyer", "you")` -> `Buyer` is `confirmed_defined`; `you` is `confirmed_alias` with `canonical_term: "Buyer"`.

Do not use `confirmed_alias` merely because two expressions are similar or frequently co-occur. The source must assign them to the same antecedent. The supervisor rejects missing targets, self-references, alias chains, non-confirmed targets, and evidence that does not contain both labels.

A parenthetical short-form label is different from a co-defined alias. When source text expressly introduces a reusable short form after its referent, the short form is itself the canonical defined label and the preceding source phrase is its exact definition text. Synthetic examples:

- `International Digital Transactions Board ("IDTB")` -> `IDTB` is `confirmed_defined` with definition text `International Digital Transactions Board`.
- `Procedural Code of the International Digital Transactions Board ("IDTB Code")` -> `IDTB Code` is `confirmed_defined` with the full code name as definition text.

An external institution, ruleset, statute, publication, or proper name is not excluded merely because it exists outside the contract. If the document expressly creates a reusable short-form label, review that label as a definition; external status may affect `reference_target`, but not whether the label was defined.

Ordinary `contexts` may contain parenthetical, inline, glossary, cross-reference, or other drafting forms. Review their meaning rather than assuming a fixed syntax. If a candidate is a substring of a longer defined phrase, review the complete phrase and do not treat the substring as a separate term unless the document independently gives it a meaning or uses it as that concept.

An unquoted explanatory parenthetical is not, by itself, a definition. For text such as `a prolonged infrastructure outage (service interruption)`, require affirmative evidence that the document creates a reusable contractual label—for example express assignment language or subsequent label-like reuse—before returning `confirmed_defined`. Otherwise classify the parenthetical as explanatory ordinary language. This is a semantic review rule, not a deterministic suppression rule: keep the candidate in the queue and decide it from source context.

The supervisor retains deterministic provenance, locations, raw records, stable IDs, and execution metadata outside the worker prompt and reconnects them only after receiving the structured decision. The worker does not return confidence, reason codes, an agent role, or model/prompt identifiers.

A semantic evidence citation supports the decision but does not identify the definition span. Only the separately submitted and source-validated definition span creates a canonical definition record or excludes text from usage counts. Bind the canonical label to the matching occurrence in that definition span's source block; never substitute an earlier use merely because it has the same spelling.

## Discovery seed

Give each discovery worker:

1. A bounded region with modest block overlap.
2. Its document-order range and nearest headings.
3. Exact source text and locations for possible terms, without deterministic classifications or confidence signals.
4. The allowed `ContextRequest.request_type` values and remaining budget.
5. The requirement to return structured records only.

The seed region is an intake boundary, not a conclusion boundary. A worker that lacks material context returns `needs_context` with a specific request and reason.

Generate stable seeds and the bounded outline with:

```text
python <skill-dir>/scripts/seed_document.py <input.docx> --work-dir <temporary-work-directory> --output <temporary-work-directory>/bundles/seeds.json
```

The command refuses to overwrite an existing artifact. Treat source coverage warnings in the seed artifact as review limitations.

## Allowed context actions

- `expand_location`: retrieve nearby blocks around the candidate location.
- `search_term`: search the document for an exact or normalized query.
- `retrieve_occurrences`: retrieve bounded occurrences of the candidate term.
- `retrieve_definitions_section`: retrieve a bounded definitions-section window.
- `retrieve_reference`: retrieve a matching section, article, schedule, exhibit, or annex heading and bounded following context.
- `escalate_review`: ask the supervisor to assign document-search-capable review; the deterministic retriever does not satisfy this action itself.

Never use a request to dump the entire document. Narrow or reject over-broad queries. Exceeding hop, result, request, or character budgets becomes `budget_exhausted` and leads to `needs_review` or `insufficient_evidence`.

Write one `context-request-v1` object conforming to `context-request-schema.json` to a run-specific temporary path and execute it with:

```text
python <skill-dir>/scripts/context_query.py <input.docx> --work-dir <temporary-work-directory> --request <temporary-work-directory>/responses/<request.json> --output <temporary-work-directory>/bundles/<response.json> [--location <temporary-work-directory>/private/<location.json>]
```

The `context-result-v1` response conforms to `context-result-schema.json` and contains source identity, the updated request, bounded evidence, and a retrieval note. Preserve those records in the eventual agent bundle; do not substitute a prose summary for their IDs and locators.

## Proposal rules

Each worker proposal identifies exact source spelling, a numbered source fragment plus offsets, state, a short reviewer note, and any bounded context request. The supervisor resolves source locations and adds stable proposal/candidate IDs, revision metadata, normalized form, evidence references, and available execution identifiers. Compatibility-only fields are supervisor-owned and empty unless a legacy bundle supplies them.

Allowed states are:

- `candidate`
- `not_a_candidate`
- `needs_context`
- `abstain`

Revisions are append-only. A later revision must explicitly supersede the immediately prior proposal for the same candidate. Exact normalized duplicate candidates may be merged deterministically before neutral envelopes are created. Similar but non-identical candidates remain separate until a model reviews their meaning.

The semantic decision must distinguish at least:

- confirmed defined term;
- confirmed alias of another queued canonical term;
- confirmed undefined term usage;
- rejected because the phrase is not a defined-term concept;
- needs more context or lawyer review; and
- insufficient evidence.

Encode the conclusion in the validated adjudication fields and do not present an unreviewed candidate as semantically confirmed.

## Trace rules

When full-review token or latency telemetry is requested, follow
[stage-telemetry.md](stage-telemetry.md). The supervisor records stage boundaries
and each packet attempt before dispatch and after response or failure, including
retries. Keep measured host latency and provider usage separate from local Python
phase timings and payload estimates. Telemetry is optional instrumentation, not
a substitute for the review-completion gates below.

Keep a concise structured trace for each material include, exclude, merge, escalate, or abstain action. Capture evidence for and against, context requests, conclusion, uncertainty, the short reviewer note, and supervisor-added execution identifiers. Do not request confidence, reason codes, an agent role, or raw chain-of-thought from workers. Internal traces are omitted from the normal lawyer view and exposed only to an authorized reviewer mode.

## Finalization

The supervisor must:

1. Preserve deterministic quoted-label observations, usages, findings, and provenance as raw records for reproducibility and debugging. Keep these `LexicalCandidateObservation` records separate from agent-authored `CandidateProposal` records.
2. Resolve or explicitly defer every term in the complete semantic queue.
3. Keep semantic adjudication separate from raw deterministic observations, while allowing the adjudication to control the lawyer-facing term status and views.
4. Never create or label a definition until semantic review accepted it and its exact source span passed validation.
5. Add semantic findings only when supported by ledger evidence.
6. Label ambiguity as `needs_review` or `insufficient_evidence`.
7. Validate all evidence and request references before serialization.
8. Derive Markdown and HTML views from reviewed states; expose raw deterministic candidates only in an explicitly unreviewed or debugging view.
9. Treat every retained lexical match as an occurrence candidate, not proof that the defined concept is invoked. Before queueing, apply maximal-span matching across semantically retained labels: discard a match wholly contained in a longer confirmed defined, alias, or undefined label, including an alias contained in its own canonical form and a shorter independently defined term contained in a longer one. Semantically adjudicate retained exact canonical forms, allowed aliases, case-folded forms, singulars, plurals, possessives, spacing variants, composite matches, exact-span ambiguities, and partial overlaps before they contribute to lawyer-facing usage counts or usage-dependent findings. Exact canonical and alias occurrences need not create variant records, but they still require occurrence adjudications. Present remaining collision sets to each reviewer and permit `shadowed_by_overlapping_term` only for a retained non-containing overlap when another accepted term is the actual contextual mention. Roll up mapped, rejected, shadowed, and unresolved variant-instance IDs on the variant record; allow a `mixed` status when context produces different outcomes.
10. Build those occurrence candidates from a fresh full-document scan of the semantically accepted term set. Do not allow an agent-discovered definition to retain a zero usage count merely because it was absent from the pre-semantic lexical list.

Complete occurrence review is intentionally exhaustive: every retained non-definition occurrence is queued, not only spelling or capitalization variants. Its worker-item count therefore grows with the number of retained occurrences in the document, and packet count grows with the resulting bounded payload size. Operators should use the emitted queue counts and debug telemetry when planning runtime capacity; do not infer a fixed per-document review cost from the number of defined terms alone.
11. Rebuild usage-dependent findings after the fresh scan. Remove stale potential-undefined findings for terms confirmed as defined or rejected, and derive undefined findings only from `confirmed_undefined` decisions. Project their evidence instance by instance: retain the candidate's confirmed source spelling, suppress a location wholly contained in a longer confirmed defined, undefined, or alias candidate, or in a longer accepted-label usage (including case and spacing variants), and preserve any standalone source-spelled location for the shorter term.

For occurrence review, exact spelling is not a semantic shortcut. A canonical-looking match inside a heading, title, longer ordinary phrase, quotation, or unrelated referent may be ordinary language rather than a defined-term use. Lowercase common nouns and noun phrases such as “confidential information,” “affiliates,” or “agreement” are likewise not defined-term uses merely because an uppercase canonical term exists elsewhere. Classify an occurrence as `ordinary_language` when its paragraph uses the wording as generic or descriptive prose. Classify it as `proper_name_component` when the match appears solely inside the name of a person, organization, product, place, or other named entity and does not invoke the accepted definition. Wholly contained accepted-label matches do not reach occurrence review; the deterministic maximal-span index retains the longer label only. For exact-span ambiguity or partial overlap, assess every retained match and use `shadowed_by_overlapping_term` only when another accepted overlapping label is the contextual mention. Use `needs_review` when the context does not resolve the distinction. Do not call a case-only difference `inconsistent_capitalization` when an all-caps canonical label appears in ordinary title or sentence capitalization, or when the source uses all-caps heading, signature-block, or other formatting-wrapper typography. Those are permitted presentation variants after contextual identity is confirmed.

The final bundle is an `agent-bundle-v1` object conforming to `agent-bundle-schema.json`, with arrays named `evidence`, `context_requests`, `candidate_proposals`, `review_traces`, `semantic_findings`, `semantic_adjudications`, `occurrence_adjudications`, and `reference_adjudications`. Omitted arrays are treated as empty. Term adjudications cover the complete term queue. Occurrence adjudications cover every queued non-definition occurrence and classify it as `defined_term_use`, `ordinary_language`, `proper_name_component`, `inconsistent_capitalization`, `shadowed_by_overlapping_term`, `needs_review`, or `insufficient_evidence`. Reference adjudications cover every queued definition reference and classify it as `resolved`, `broken`, `out_of_scope`, `needs_review`, or `insufficient_evidence`; external and omitted companion references are `out_of_scope`, not broken. Keep packets, manifests, responses, envelopes, and intermediate bundles in one marked OS-temporary workspace and submit the final bundle through:

```text
python <skill-dir>/scripts/definition_check.py <input.docx> --output-dir <new-output-directory> --work-dir <temporary-work-directory> --agent-bundle <temporary-work-directory>/bundles/<agent-bundle.json>
```

Delete the marked workspace with `review_packets.py workspace-cleanup` after successful finalization unless retained debugging was explicitly requested.

The checker rejects oversized bundles, unknown fields, unresolved non-escalation requests, invalid revision chains, dangling evidence/request references, non-semantic agent findings, and source locations outside the parsed document.

Treat that deterministic rejection as the validation authority. Never accept a worker's statement that its JSON is valid without submitting the artifact to the packaged validator/checker. Correct schema errors before any review result is incorporated or shown to a user.

## Document-aware matter packets

Matter, version-comparison, and companion-document work uses the deliberately
versioned `review-packet-v3` contract. Every packet states `view_type`,
`authority: proposal_only`, `matter_id`, `document_id`, `version_id`, an optional
comparison version, the validated snapshot hash, and the canonical prompt hash.
Its items remain bounded and provenance-neutral. Detector fields, ranks, scores,
confidence hints, private manifests, and review traces are prohibited.

The supervisor obtains these packets only from a validated matter projection.
Targeted retrieval must name a selected document version and must not cross into
an unselected version. A response repeats the packet hash and document scope.
The response conforms to `matter-review-response-schema.json`. The supervisor rejects it if the snapshot, prompt, packet, matter, document, or
version no longer matches. Workers retain proposal-only authority; only the
supervisor may reconcile responses, materialize canonical components, and
publish a new parent-linked immutable snapshot.

For two-version work, `prior` and `current` derive from explicit manifest
lineage, never packet order or filenames. Semantic identity requires a reviewed
mapping with exact evidence from both versions. Companion-document work begins
only after the multi-version structural and semantic gate passes, uses only the
selected manifest scope, and records external or unselected materials as
out-of-scope rather than silently searching them.
