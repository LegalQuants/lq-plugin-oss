# Mini-PRD: `/docreview`

**Proposer:** Victor

**Status:** Current public design note for the shipped workflow.

## Description

`/docreview` is a platform-less way for litigators to organize and review an incoming production against the matter's own requests or issues. It inventories every source, maps messages by thread, custodian, participant set, and month, names gaps before costly review, and produces an immutable finding proposal for every approved unit/question job. A lawyer rules on privilege and substantive calls through deterministic offline HTML and JSON receipts.

The skill now ships its inventory, orchestration, framework, review-copy, and reconciliation helpers inside `skills/litigation/docreview/`. Those files retain the shared contracts developed with `/diligence`, but `/docreview` has no runtime dependency on the Diligence skill or its installation.

The bundled deterministic path is Python-standard-library only. Poppler and LibreOffice are optional open-source executables when already present; nothing is installed during a matter run. If scripts cannot run, the skill preserves the same work units, privilege holds, lawyer gates, and parked lanes through a provider-neutral fallback while labeling any assurance it could not reproduce.

## Problem

Existing review platforms can host documents, but they do not begin with the lawyer's own pleading, chronology, or served requests and then deliver a verifiable account of what was reviewed, what was not, and why. Review teams also pay a large usability cost before substantive analysis: native emails, text, PDFs, spreadsheets, presentations, and Word documents do not arrive in one safe review surface.

Chat alone does not solve that problem. It loses corpus coverage, permits instructions to drift between document readers, and makes it difficult to separate a model proposal from a lawyer's ruling. `/docreview` makes those boundaries explicit: deterministic plans and receipts surround isolated judgment work, and every approval is tied to the exact artifact it authorizes.

## Why this matters

1. **Discovery management drives cost.** An inventory and gap map are useful the day a production lands, before a platform or review team finishes loading it.
2. **The matter should define the review.** Served requests, pleadings, and chronologies become a fixed review framework rather than informal prompt context.
3. **Coverage and finding quality are different assurances.** Count reconciliation proves that the approved work was accounted for; quote and checker receipts support the individual findings.
4. **Privilege remains human judgment.** Broad signals create a held queue; only the lawyer releases a document.
5. **A lawyer needs to see the source.** A filesystem link is provenance, not a review experience. The review-copy layer makes ordinary formats available inside the offline artifact and fails closed when it cannot.

## Audience

The primary user is a litigation associate or supervising lawyer receiving a production from opposing counsel, a client, or a vendor. Solo and midsize litigators without a dedicated review platform are an equally direct fit. The client, partner, or court-facing team may consume an approved derivative of the ledger, but the v1 skill itself prepares rather than sends or files anything.

## Product flow

### 1. Inventory and reviewability

The lawyer points `/docreview` at a local production and supplies any index or load file. The skill writes a content-hash manifest, reconciles duplicate, missing, unreadable, and index gaps, then builds `review-copies.json` and a content-addressed offline bundle.

The sidecar covers the exact manifest, full source hashes and byte counts, separately reviewable email attachments, renderer identity, derivative hashes, page order, and exact bundle contents. It never carries a responsiveness or privilege conclusion.

The built-in lane supports:

- escaped inline review for TXT, CSV, JSON, XML, Markdown, logs, and EML;
- familiar EML headers and body plus separately receipted attachments;
- common images inline;
- browser-native PDF with optional Poppler page images; and
- safe visible text for readable DOCX, XLSX, and PPTX packages, with optional LibreOffice-to-Poppler page images.

Unsupported, corrupt, legacy, or incomplete formats are **Needs rendering**. A valid sidecar with such an item is useful for diagnosis but cannot support a claim that the affected tier is lawyer-reviewable or coverage-certified.

### 2. Production map and review framework

Native message headers drive thread and channel clustering. The gap report shows missing custodian months, missing referenced messages, parser-scope limitations, and any manifest or index gaps. Flattened PDFs and images remain singleton review units; filenames do not become relationship evidence.

The lawyer supplies framing inputs. Enumerated RFPs, RFAs, SROGs, and declared issue lists receive a deterministic census and one framework item per served element. Pleadings and chronologies use conservative interpretive compilation. Both paths yield a validated framework and a plain-language readback. The approved framework is injected unchanged into every maker and checker job.

### 3. Plain-language setup approval

The first HTML asks four understandable questions: whether the review questions are right, whether collection coverage looks expected, whether the proposed five-unit sample is useful, and whether a disclosed metadata-deferral policy is acceptable. It explains that approval authorizes only that sample. Plan IDs, hashes, execution mode, and worker mechanics remain available in collapsed technical receipts.

The offline page downloads `review-setup-approval.json`; clicking does not start work. Deterministic ingest rejects corpus, framework, cluster, read-plan, review-plan, unit, issue, or metadata-policy drift and writes new approved-plan and confirmed-cluster copies without mutating the sources.

### 4. Sample, privilege, and verification

Each approved unit/question pair gets one isolated maker job. Checkpoints must echo the exact review plan and conform to the fixed result schema. Missing or invalid work is retried at most twice and then parked.

Any privilege signal places the complete unit on hold. The lawyer reviews a plain-language privilege page and exports `privilege-rulings.json`; deterministic ingest rejects stale queue or manifest bindings. The ruled queue is a new file. Only `not-privileged` releases the unit.

Present high-band findings go to a separate checker without the maker's reasoning. A missing, stale, or non-confirming checker result becomes unresolved rather than disappearing. The lawyer calibrates the framework on the checked sample before approving a full plan.

### 5. Requests/Documents review and lawyer overlays

The primary review HTML is deterministic and works from `file://` without network requests:

- **Requests** shows each served request and the documents proposed as responsive; responsive documents lead and reviewed negatives are collapsed.
- **Documents** reverses the same ledger and embeds each source once.
- **Needs attention** shows an unresolved document once rather than once per request.
- **Needs rendering** is a source-review blocker, not a responsiveness result.

The page uses plain-language status labels and keeps hashes and stable IDs in technical receipts. It embeds only content revalidated through the sibling `review-copies.json`; the original remains a secondary evidence link.

The lawyer exports sorted, timestamp-free `review-feedback.json` with explicit Responsive, Not responsive, Needs review, or Privileged rulings and any document-level image confirmation. Ingest binds the exact ledger, framework, plan, frame, corpus, machine status, finding, and image proposal bundle. It refuses drift before output and writes an additive ruled copy. Machine statuses, quotes, evidence receipts, checker receipts, and the privilege queue never change.

The export → ingest → rerender loop is entirely deterministic. It reuses the existing model proposals and source receipts and makes no new model call.

### 6. Scale and delivery

The calibrated framework receives a new explicitly approved targeted or full plan. The same maker, privilege, checker, review-copy, and lawyer-feedback loop runs over that scope.

Delivery requires both:

1. document-review reconciliation proving the complete issue-by-unit equation, privilege holds, checker coverage, and exact lawyer confirmation of every image-review bundle; and
2. a final `review_copies.py verify` exit 0 against the current manifest, source bytes, attachment inventory, derivatives, and bundle set.

An exit 1 rendering state or exit 2 integrity failure remains a visible stop condition. Neither may be called lawyer-reviewed, client-ready, or coverage-certified.

## Data and judgment boundaries

- Machine findings are immutable proposals. Lawyer decisions are additive overlays with separate provenance.
- The framework is the sole instruction channel to judgment workers.
- A claim without a verified quote is unresolved.
- `present`, `absent`, and `unresolved` remain wire values; the interface uses Responsive, Nothing found, and Needs a decision.
- Privilege, responsiveness, relevance, and materiality remain lawyer calls.
- Durable artifacts have stable IDs and sorted JSON, with no run-added timestamps, host names, absolute paths, or remote dependencies.
- Matter documents remain local. The skill does not transmit, produce, serve, file, or publish them.

## Deliverables

- manifest, message map, confirmed clusters, and gap report;
- validated framework, readback, approval receipt, and approved plans;
- immutable machine findings and checker receipts;
- privilege candidate and ruled queue artifacts;
- `review-copies.json` plus the content-addressed review bundle;
- setup, sample, privilege, and Requests/Documents HTML;
- additive lawyer-feedback and image-confirmation overlays; and
- final document-review and review-copy verification receipts.

## Out of scope for v1

- preparing or sending an outgoing production;
- making lawyer-only relevance, materiality, responsiveness, or privilege determinations;
- jurisdiction-specific disclosure law;
- PST, forensic-image, and other container ingestion beyond an extracted local folder; and
- silently treating an unsupported or unrendered source as reviewed.

## Success criteria

- Every seeded gap is found, every seeded privilege candidate reaches the lawyer queue, and every planted issue link survives lawyer spot-check.
- The same approved inputs produce byte-identical deterministic artifacts.
- The setup page lets a new lawyer understand what they are approving without reading plan IDs or worker mechanics.
- Every approved result is reviewable inside the production HTML or visibly blocked as Needs rendering.
- Repeated lawyer feedback changes only the additive overlays and requires no model rerun.
- Final counts and review-copy verification both pass before any coverage certification.

## Evaluation plan

The seeded benchmark combines native messages, ordinary text, images, PDF, OOXML Office files, duplicates, missing custodian slices, broken threads, privilege signals, responsive and nonresponsive request calls, unresolved calls, and a stale-feedback case. It exercises setup approval, sample review, privilege export/ingest, Requests/Documents filtering, deterministic feedback, review-copy tamper refusal, Gate 3 reconciliation, and a second byte-identical render.

The adoption test is a lawyer with no build history reaching an approved five-unit sample, understanding what approval does, and completing the export/ingest/rerender loop without builder assistance.
