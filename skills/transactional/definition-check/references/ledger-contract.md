# Ledger Contract 0.14.0

The JSON ledger is the canonical machine-readable artifact. Markdown and later Word/HTML views are derived from it.

## Empty review queues

The temporary `agent-bundle-v1` contract accepts an optional `discovery_review`
object containing the source, discovery-prompt, and discovery-queue SHA-256 hashes
plus every compact discovery packet response. The packaged discovery expander
creates this record even when all response rows are empty. The pipeline checks
the hashes, packet coverage, exact source spans, and proposal inclusion against
its freshly built manifest before accepting completion. This object remains an
internal bundle record; it does not change the canonical ledger schema.

Zero semantic candidates can complete only after that discovery validation.
Zero occurrence candidates can complete after semantic review completes. The
ledger records queue finalization without claiming nonexistent semantic or
occurrence worker calls. A deterministic zero-candidate scan alone remains
unreviewed. Legacy nonempty review bundles retain their existing contract; a
universal discovery-completion gate is separate hardening work.

## Top-level fields

- `schema_version`: ledger contract version.
- `engine_version`: deterministic checker version.
- `run_status`: completion or degradation status.
- `capability_profile`: effective runtime profile.
- `source`: source identity, hash, and structure coverage.
- `methods_run`: methods that completed.
- `methods_not_run`: skipped method plus reason.
- `definitions`: canonical definitions created only from source-validated semantic decisions.
- `term_variants`: first-class non-canonical forms mapped toward a canonical term, with mapped, rejected, shadowed, and unresolved instance IDs retained separately.
- `usages`: individual term instances. A non-canonical instance links to its `term_variants` record through `variant_id`.
- `findings`: deterministic and later semantic finding records.
- `evidence`: bounded excerpts and locations used by contextual review.
- `lexical_observations`: deterministic detector outputs with source spelling, normalized key, location, and detector metadata; never agent role, rationale, confidence, or semantic state.
- `candidate_proposals`: append-only, revisioned worker proposals.
- `context_requests`: bounded retrieval actions and result references.
- `review_traces`: structured supervisor decisions and uncertainty records.
- `term_candidates`: supervisor-side complete queue with raw provenance; this is not reviewer input.
- `semantic_adjudications`: one authoritative semantic decision per opaque review ID.
- `semantic_review`: queue, completion, and unresolved counts.
- `occurrence_candidates`: supervisor-side queue of every non-definition maximal-span lexical match requiring contextual identity review, including overlap metadata for exact-span ambiguity and partial overlaps.
- `occurrence_collisions`: first-class groups of overlapping matches for distinct accepted canonical terms, with mapped, rejected, shadowed, and unresolved members retained separately.
- `occurrence_adjudications`: one semantic decision per queued ambiguous occurrence.
- `occurrence_review`: occurrence queue, completion, and unresolved counts.
- `reference_candidates`: complete supervisor-owned queue of definitions whose exact source-validated body delegates meaning to a target.
- `reference_adjudications`: one scoped disposition per reference queue item; `out_of_scope` is used for external or omitted companion material.
- `reference_review`: reference queue, completion, and unresolved counts. A complete reference review is required before a DEF-006 finding or lawyer dashboard is emitted.
- `limitations`: run-level limitations in plain language.

## Record invariants

- IDs are deterministic for the same source hash, location, normalized term, and rule.
- Every definition and usage links to a source location.
- Every finding links to evidence locations or explicitly records why evidence is unavailable.
- `deterministic` and `semantic` findings are distinguishable.
- Coverage records parts parsed, parts omitted, and parse warnings.
- A report never asserts broader coverage than the ledger.
- `/conform` may consume only a supported schema version whose source hash is current.

The executable JSON Schema is `ledger-schema.json` in this directory.

## Compatibility policy

Consumers must validate `schema_version` before reading ledger fields and fail closed on an unsupported version. The checker emits `0.14.0`; response packets and consumers pinned to older schemas must fail stale and be upgraded deliberately. Schema changes require a version bump, an updated executable schema and contract, and consumer migration notes; adding a required field is never treated as backward compatible.

## Agentic extension

Schema `0.2.0` introduced the deterministic foundation for:

- candidate proposals and their revisions;
- context requests, retrieval scope, and returned source locators;
- inclusion, exclusion, merge, escalation, and abstention decisions;
- supporting and contradicting evidence;
- concise structured rationale and uncertainty;
- the responsible agent role plus prompt/schema/model configuration identifiers where available; and
- trace visibility and retention metadata.

These records support reconciliation, evaluation, and debugging. They are not a request to store or expose raw chain-of-thought. The supervisor owns canonical revisions; workers submit proposals rather than mutating shared facts concurrently. Traces are internal by default and may be separated into a hash-linked artifact in a later schema if firm retention policy requires it.

## Semantic adjudication boundary

A full-capability run reviews the complete exact-normalized union of quoted-text candidates, potential undefined-term candidates, and additional agent-discovered candidates. The deterministic layer does not parse antecedents or definition bodies. Semantic decisions determine whether a term is confirmed defined, confirmed undefined, rejected as noise, or unresolved. Raw candidate locations remain in the ledger for provenance; lawyer-facing `DEF-001` evidence retains the confirmed candidate's source spelling and omits a shorter candidate location wholly contained in a longer retained candidate or accepted-label usage location, including a case or spacing variant. Standalone source-spelled occurrences of the shorter term remain visible.

Semantic reviewers receive a provenance-blind compact packet containing numeric item and item-local context ordinals plus a length-preserving ASCII projection of source spelling and bounded source text. The private manifest retains the original Unicode source so validated offsets reconstruct exact definition text. Opaque IDs, source locations, deterministic pattern/rule/class/rank/score/severity/confidence fields, and execution metadata stay supervisor-side. Workers return a numeric decision, source references where required, and a short note; the supervisor reconnects IDs and execution metadata.

Schema `0.3.0` added the complete term queue, semantic adjudications, and an explicit completion summary. A complete run requires exactly one adjudication for every opaque review ID. The decisions are `confirmed_defined`, `confirmed_undefined`, `rejected_not_a_term`, `needs_review`, and `insufficient_evidence`. Renderers derive lawyer-facing status from these records. When semantic review is not complete, candidates and potential undefined terms are explicitly labeled unreviewed rather than confirmed.

Schema `0.4.0` separates lexical occurrence matching from semantic identity. After term-level semantic review completes, `usages` is rebuilt by a full parsed-document scan for every accepted canonical term and alias. The current engine queues every non-definition match—including exact canonical forms and aliases—for contextual adjudication. A complete occurrence review classifies each as `defined_term_use`, `ordinary_language`, `inconsistent_capitalization`, `needs_review`, or `insufficient_evidence`. When contextual review confirms identity, ordinary capitalization of an all-caps canonical label and all-caps presentation of an ordinarily capitalized label are normalized to `defined_term_use`; typography alone does not create a lawyer-facing inconsistency. Lawyer-facing counts and DEF-004/DEF-005 projections exclude `ordinary_language` collisions; the canonical ledger retains them for debugging.

The full `semantic-review-envelopes.json` and `occurrence-review-envelopes.json` files are temporary debugging and backward-compatibility artifacts in the run workspace. Workers receive only `review-packet-v3` packet files from `<work-dir>/packets/<stage>/`, conforming to `review-packet-schema.json`. Each packet supplies one compact JSON `response_schema`, a complete `response_template`, and item-local constraint rows where needed. The schema constrains packet number, row count, field types, and shared enums without repeating a full schema per item; the template and constraints make row order, item ordinals, and allowed contexts explicit, and the supervisor validator enforces them fail-closed. `render-dispatch` derives a canonical response path and prefills it from the template; stage expansion discovers those paths without hand-built response flags. Private manifests under `<work-dir>/private/` map numeric ordinals to IDs, hashes, prompt versions, prompt hashes, and source locations; the supervisor fails closed if packet or item coverage is incomplete or mismatched.

`term_candidates.structural_hints` may contain `likely_heading` or `includes_likely_heading_occurrence`. Heading recognition is advisory: it never suppresses a candidate, and structural hints are omitted from semantic-review envelopes to prevent anchoring.

Schema `0.5.0` removes deterministic definition and antecedent parsing. Regex is recall-only: it preserves plausible quoted labels for review. A `confirmed_defined` submission must copy the exact definition text from one supplied context and return the context index plus zero-based start/end offsets. Reconciliation requires an exact source-slice match and rejects hallucinated, normalized, paraphrased, or out-of-bounds text. Only a validated submission materializes a canonical `definitions` record.

Schema `0.6.0` separates deterministic `lexical_observations` from agent-authored `candidate_proposals`. Queue construction deduplicates both record types by exact normalized key while retaining separate source IDs and source locations. Deterministic observations cannot carry agent rationale or confidence, and those source-side fields remain absent from semantic-review envelopes.

Schema `0.7.0` makes variants and their instances explicit. A `term_variants` record identifies the observed form and variant type, while each `usage` remains the source-grounded instance and links through `variant_id`. Mapping outcomes are instance-sensitive: the registry separately retains mapped, rejected, and unresolved usage IDs, and may therefore be `mixed`. A plural or other variant rejected as a separate glossary label is not presented as a rejected lexical match when occurrence review maps that same source span to a canonical defined term.

Schema `0.8.0` adds `confirmed_alias` as a first-class term-level semantic decision. Each alias adjudication records the exact `canonical_term` and supervisor-resolved `canonical_review_id`; the target must be a separate `confirmed_defined` queue item. Materialization creates one canonical `definitions` record and appends the alias to its `aliases` array rather than creating a duplicate definition. An expressly introduced parenthetical short-form label remains `confirmed_defined` with source-validated definition text; `confirmed_alias` is reserved for multiple labels assigned to the same antecedent.

Schema `0.9.0` introduced overlap-aware occurrence records. The current index applies maximal-span matching first: a lexical match wholly contained in a longer semantically retained label is suppressed, including a shorter accepted definition inside a longer confirmed-undefined label. `occurrence_collisions` records only the remaining exact-span ambiguity or partial overlap and its competing usage IDs. Each non-definition member of such a collision remains independently reviewable. `shadowed_by_overlapping_term` means that a retained overlapping match contextually belongs to a different accepted term; it is excluded from lawyer-facing counts without erasing the raw match.

Schema `0.10.0` binds each materialized definition label to the same source block as its source-validated definition span, rather than selecting the label's first document occurrence. It also records an observed singular form as a `singular` variant when that source candidate pluralizes to an accepted plural canonical label. Every such occurrence remains subject to contextual occurrence review. A reviewed occurrence that resolves to an accepted canonical term does not remain a lawyer-facing undefined-term finding, while the raw term-level decision remains available for developer provenance.

Schema `0.11.0` allows one confirmed semantic decision to carry multiple exact source-validated definition spans. Materialization creates one canonical `definitions` record per span, preserving duplicate definition locations for DEF-003 while retaining one semantic queue decision per normalized term. The legacy singular definition fields remain populated from the first span for downstream readers and old single-span bundles.

Schema `0.12.0` adds a scoped reference-review stage. Target extraction records the exact target phrase and source span but does not resolve it deterministically. A complete reference queue must receive exactly one disposition per item. Only `broken` emits DEF-006; `resolved` and `out_of_scope` do not. External references and omitted companion documents are `out_of_scope`, not broken. `needs_review`, `insufficient_evidence`, or missing coverage keep the run out of the lawyer dashboard.

Schema `0.13.0` distinguishes local undefined terms from specifically identified outside documents. Confirmed undefined terms carry `scope_qualification`, `scope_target`, and exact `scope_evidence`; `possible_inherited_definition` reports a source-backed possibility without inventing an inherited definition. `confirmed_external_reference` produces informational DEF-007 and never DEF-001. Unresolved semantic, occurrence, and reference decisions require a structured `review_reason`. Packet schema v3 and new prompt hashes make every older response packet stale. Every validated definition span remains materialized; renderers distinguish exact repeated meaning text from differing or potentially conflicting text.

Schema `0.14.0` distinguishes proper names from ordinary prose at both review levels. `rejected_proper_name` records a complete person, organization, product, place, or other named entity that merely identifies that entity rather than serving as a contractual label. `proper_name_component` records a lexical match that appears solely inside such a name and does not invoke the accepted definition. Both remain in the canonical ledger for audit, but neither contributes to lawyer-facing usage counts or DEF-004/DEF-005 findings. Contractual function takes precedence: an expressly assigned proper name remains a confirmed definition or alias.

Definition spans may not begin or end inside an alphanumeric token. Reference extraction rejects non-referential fragments, reference context retrieval uses bounded phrase-aware matching, and lawyer-facing reference annotations use the exact `reference_location`; additional adjudication evidence remains supporting context rather than additional issue occurrences.

`review-packet-v3` is the internal packet transport. The semantic response fourth field is `definition_spans`; the manifest prompt hash rejects stale semantic responses. The current agent-bundle schema still carries `reason_codes`, `confidence`, and `agent_role` for backward compatibility. Compact expansion writes `reason_codes: []`, `confidence: null`, and a supervisor-configured `agent_role`; workers neither receive nor produce those fields.

`semantic-v3` retains that response schema and narrows the decision boundary: ordinary descriptive wording is not an undefined term, while a specifically named document used in operative incorporation language is not discarded merely because it is external or separately documented. The changed prompt hash invalidates older semantic response packets.

`semantic-v4`, `occurrence-v5`, `reference-v2`, and `discovery-v2` require workers to start from the packet's response template and conform to its packet-specific schema. The packaged validator remains authoritative for semantic cross-field rules and exact source-span checks that JSON Schema alone cannot express safely.

## Matter snapshot contract 1.0.0

Schema `0.14.0` remains the canonical single-document ledger contract. Matter
snapshot `1.0.0` is the additive, explicitly invoked contract for persistence
across document versions and selected companion documents. Its executable
schemas are `matter-schema.json`, `matter-record-schema.json`,
`matter-view-schema.json`, and `matter-review-packet-schema.json`.
Every remaining model-facing machine contract is executable as
`review-packet-schema.json`, `context-request-schema.json`,
`context-result-schema.json`, `agent-bundle-schema.json`, or
`matter-review-response-schema.json`.

A `matter.definition-check` file is an immutable ZIP snapshot. `manifest.json`
declares one neutral matter, document families, document versions, explicit
parent/supersedes lineage, the selected scope, declared document relationships,
and every component's role, authority, SHA-256 hash, and record count. Complete
selected versions must have document metadata, an accepted defined-term
registry, an authoritative post-finalization usage index, and findings. Paths
are normalized relative POSIX paths. Duplicate, absolute, traversal, undeclared,
oversized, over-compressed, encrypted, corrupt, hash-mismatched, count-mismatched,
or unsupported-version members fail closed. Publication is temporary-file-first,
fully validated, and atomic; an existing completed snapshot is never overwritten.

The authority boundary is structural:

- `defined-term-registry.json` contains only accepted definitions and aliases
  backed by accepted adjudications.
- `usage-index.jsonl` contains only the authoritative post-finalization usages
  of accepted canonical terms or aliases.
- `findings.json` contains document-local conclusions and exact evidence.
- lexical observations, candidate proposals, adjudications, and review traces
  are separate provenance components. Candidate records never become accepted
  definitions by placement or naming.
- version-lineage and cross-document findings are comparison components layered
  over completed document-local facts; they never rewrite those facts.

Every source location carries `matter_id`, `document_id`, and `version_id` in
addition to the `0.12.0` block and offset fields. Each imported local stable ID
is retained and mapped deterministically to a document-version-qualified ID.
The importer accepts only complete `0.12.0` ledgers and the compatibility
projector reconstructs the supported legacy shape without inventing lineage or
document relationships.

Version mappings are one-to-one reviewed records with exact evidence from each
affected version. Supported states are `added`, `removed`, `renamed`, `moved`,
`materially_changed`, `unchanged`, `changed_usage`, and `unresolved`. Matching
spelling is never enough to link two definitions. Cross-document findings are
limited to the manifest's selected versions and distinguish valid selected
companion definitions, conflicts, missing selected companions, broken
selected-scope references, out-of-scope documents, and unresolved mappings.

The standard-library implementation is `definition_check/matter.py`; the
packaged command surface is `scripts/matter_snapshot.py`. The validator reads
members in place and never extracts an archive to an uncontrolled directory.
Lawyer views disclose selected scope and missing companions, distinguish
document-local facts from reviewed comparisons, and attach exact
document-version-qualified navigation data to every displayed evidence item.
Developer provenance requires separate explicit authorization.
