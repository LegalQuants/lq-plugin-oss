# Mini-PRD: `/legaldesign`

Maintainer: Dan Sito (loxotolegal)

## Description

`/legaldesign` is a LegalQuants skill that transforms legal information and analysis into interactive, editable HTML artifacts with supported customization actions. It is a broad legal-communication capability for legal research, analysis, contract review, redline explanations, engagement and pricing options, document companions, and other legal workstreams. It is intentionally not limited to one document type, practice area, or decision point.

The skill gives lawyers dependable visual starting points without requiring coding or design expertise. Its reusable method combines dialed-in templates, tested SVG and interface components, predictable component behavior, progressive disclosure, and inspectable evidence. A lawyer can customize branding, tone, layout, and component selection, edit the generated artifact, and export it as clean standalone HTML.

## Problem

Lawyer-client communication still relies heavily on email, text-dense memoranda, and occasional PowerPoint diagrams. At the same time, AI-generated writing has increased the volume of material lawyers and clients are expected to read and understand. These formats often require a later call in which the lawyer translates the analysis into business implications, explains options, and answers predictable questions.

The problem is not merely that existing documents are unattractive or slow to create. A recipient needs to understand the answer, implications, options, supporting detail, and next steps well enough to make an informed decision. A conventional email or memo often presents those elements as a linear wall of text and merely sets up another explanatory conversation.

Before generative AI, a lawyer could theoretically commission a bespoke interactive web artifact, but producing one for each matter required specialist coding skill and an uneconomic amount of lawyer time. A nontechnical lawyer needs a practical way to turn matter-specific work into a substantively faithful, client-ready decision environment within minutes.

## Why

The contributor reports overwhelmingly positive recipient reactions to HTML-based legal communications used at General Legal and in earlier work, including artifacts for explaining redlines, presenting engagement letters and fixed-pricing options, and communicating analysis or advice. This is useful practitioner evidence, but it has not been quantified or independently validated.

The AI-native opportunity is to remove the coding and design barrier while preserving matter-specific judgment. The first bounded proof point is whether a first-time, nontechnical lawyer can turn a source memo into a faithful, editable artifact in under ten minutes without touching code. That target applies to the defined memo fixture, not every source set or reasoning setting. Product evaluation records time to the first useful response separately from total completion time and never trades source fidelity or an honest QA receipt for speed.

LegalQuants' primary advantage is distribution through the LegalQuants Codex for Legal plugin inside the Codex ecosystem. The `/legaldesign` method is open and technically portable, so the method itself is not a technical moat. A LegalQuants community process may strengthen the shared templates, tested components, reliability rules, and evals by incorporating the client-communication experience of practicing lawyers across firms, in-house teams, and solo practices, but that process is not the primary distribution advantage or a technical moat.

Two important propositions remain hypotheses:

- **Client-impact hypothesis:** an interactive decision environment improves comprehension, speeds decisions, or reduces clarification calls compared with the source memo or a text-only communication.
- **Community-strengthening hypothesis:** multiple LegalQuants members will contribute formats or repeatedly test them across distinct workflows, strengthening the templates, components, and evals.

The claim that `/legaldesign` is the only legal-specific visualization skill in the Codex ecosystem is unverified until the live marketplace is checked at launch. Evidence for the distribution advantage should include that marketplace scan plus installation and adoption data. The repeat-use thesis also remains unverified beyond the contributor's experience. Usage frequency by artifact category, replacement of clarification emails or calls, and independent reuse on later matters must be measured rather than presented as established facts.

## Success

`/legaldesign` succeeds when a lawyer without technical coding experience can provide legal work and communication context in a single free-form request, answer or skip no more than three targeted questions, and receive a predictable, editable visual artifact that requires minimal lawyer editing. The artifact must preserve the substance of the source material, expose supporting detail appropriately, and export as clean standalone HTML.

The first release proof is the memo-to-decision-map eval:

- A first-time, nontechnical lawyer starts with a conventional legal-research memo.
- On the bounded reference fixture, the lawyer produces an editable, client-ready one-page decision map in under ten minutes without touching code; longer thorough runs remain acceptable when their scope and elapsed time are disclosed.
- The output states the answer up front and makes governing rules, authorities, risks, implications, and recommended next steps navigable.
- The output contains no invented legal analysis, facts, authorities, or conclusions.
- The lawyer can edit the working artifact and export clean standalone HTML with editing controls removed.
- Any supplied citation evidence bundle retains the verified citation, canonical link, precise locator, screenshot where available, and provenance or fidelity metadata.

Success across the broader product is evaluated by:

- factual and citation fidelity to supplied and verified source material;
- correct, predictable behavior of interactive and editable components;
- the amount and type of lawyer editing required before delivery;
- recipient comprehension compared with the source memo or text-only format;
- time to an informed decision and the number of clarification calls or emails, where observable;
- successful independent reuse by another lawyer on a second matter; and
- repeated use across more than one artifact category.

Only the under-ten-minute target is currently a confirmed numeric threshold. Baselines and pass thresholds for editing effort, comprehension, decision time, clarification volume, and repeat use must be established through the eval program rather than invented in advance.

## Audience

The audience is intentionally broad: client-facing lawyers, in-house counsel, and specialist lawyers communicating with an internal audience. The common need is to explain legal information or analysis to someone who does not share the same domain expertise.

The product thesis is that `/legaldesign` becomes a core, always-available communication tool across practice areas and matters. It can support legal analysis, contract and redline explanations, engagement letters, pricing options, legal research, document companions, and other communications. The memo-to-decision-map is the first demo and eval specification, not the boundary of the skill.

## What

### Trigger

The lawyer invokes `/legaldesign` in Codex. The command tells the agent to use the LegalQuants visualization method, templates, components, and reliability rules instead of designing an artifact from first principles.

The skill is built for Codex and optimized for its local file, code-execution, preview, and durable-artifact workflow. The underlying method is not technically exclusive to Codex and could be adapted to another capable coding harness. This is a technical-capability statement only, not a claim about branding, licensing, release strategy, or exclusivity in the OpenAI partnership.

### Inputs

The input is flexible and may include:

- a free-form description of what the lawyer needs to communicate;
- the legal work itself or directions to relevant local files;
- the client or other target audience, what it already knows, and the intended message, decision, or action;
- a preferred artifact format or template;
- desired content placement, layout, tone, or interaction; and
- a user- or firm-controlled `design.md`, confirmed `[visualize]` preference, or other express branding rules.

The skill reviews the request and relevant accessible local files before asking questions. It asks no more than three targeted clarification questions in total before the initial build and asks them together. A request that supplies only a source and an artifact family is still bare: the skill must ask who the audience is and what that audience should understand, decide, or do, rather than silently inferring those fields. A third question normally chooses one-page versus staged walkthrough and the first-reading detail level; if the source record is missing, or linked original-source images require retrieval authorization, that request takes priority. The lawyer may answer, skip, or expressly direct the skill to proceed with stated presentation assumptions.

Before building, the skill states a compact working brief: audience, intended message or action, mode and detail, controlling source record, design source, assumptions, and unresolved substantive gaps. A presentation assumption may be stated and used. Any assumption affecting substance must remain supported by the record; unsupported substantive gaps are flagged rather than filled.

### Steps

1. Review the request, controlling local material, audience context, and applicable `/legaldesign` design authority.
2. For a bare request, ask the grouped intake questions and wait for the lawyer's answer, skip, or express direction to proceed; do not infer audience or intended action from the source alone.
3. State the working brief, including assumptions and unresolved substantive gaps.
4. Write visible copy, name the relationship, and select a tested template and compatible component contract.
5. Create and validate a small build specification, then reuse the tested shell and component runtime rather than regenerating them.
6. Structure the supplied legal work for the selected format, using progressive disclosure where it improves clarity.
7. Build one primary editable HTML artifact and test its source, visual, interactive, accessibility, sanitization, and export behavior.
8. Open the completed artifact automatically in the Codex app or, for Codex CLI, in a browser.
9. Allow the lawyer to edit and review the artifact, then export either a clean deliverable or a sanitized reusable template.

The workflow should not be over-prescribed. The skill may delegate discrete implementation tasks where useful, but responsibility for a coherent, faithful final artifact remains with `/legaldesign`.

### Deliverable

The default deliverable is one working HTML artifact that opens automatically and supports direct text editing. Where feasible, the lawyer can also reposition and resize text boxes and graphics, scale elements, and retain correct text reflow and wrapping. Its export controls generate the clean standalone and sanitized-template variants on demand; sibling files are materialized only when requested or required by the delivery workflow.

The artifact supports two exports:

- **Standalone HTML:** a clean client deliverable with editing controls removed.
- **Sanitized template:** the lawyer's modified design with client-identifying information removed and substantive text replaced by blanks or placeholders so it can be reused safely.

The first template family is a layered one-page explainer. Its first evaluated use is an interactive legal-research decision map with the answer, governing rules and authorities, risks, recommended next steps, and expandable supporting detail. The shipped staged families now include the base slide brief and a specialized due diligence report with a dashboard, persistent contents rail, section checklists, and finding pages. Later families include a redline walkthrough, engagement or pricing-options artifact, legal-research issue map, and a document or contract companion that moves through corresponding sections of a separate document.

For evidence-bearing components, `/legaldesign` presents evidence but does not verify legal authority independently. Its consumer-side v2 compatibility mapping reads the existing canonical `/cite-check` aggregate JSON together with the exact preparation manifest, preserves normalized citation fields, validator flags, aggregator severity, coverage, source identity, and limitations, and assigns only a run-scoped presentation ID. It requires no producer-side change. A highlighted matched supplied-source image may be derived from a uniquely matched, readable authority using the exact excerpt and locator after manifest and path validation. If the record contains only a link, retrieval or capture of the linked original requires an available permitted capability and the lawyer's authorization. The image is presentation evidence, not proof that the supplied file is the original source, verification, or currentness. Missing, inaccessible, or ambiguous source material receives a disclosed text-and-link fallback rather than a retyped or decorative image. `/cite-check` remains the owner of every schema and status it emits; any producer-side interface or cross-reference requires its maintainer's approval.

### Playbook

Only preferences in the `[visualize]` namespace of `lqplaybook.md` may affect `/legaldesign` behavior. The design resolution order is: current request, an explicitly supplied or identified matter `design.md`, confirmed `[visualize]` lines, an authorized observation of a supplied public firm website, then neutral packaged defaults. Website observations must record URL and date and distinguish observed from inferred rules. `/legaldesign` may propose an exact durable preference after user confirmation, but persistence is routed through the repository-authorized playbook writer; the skill itself does not write `lqplaybook.md` or `lqprofile.md`.

`/legaldesign` must not write preferences to `lqprofile.md` or `lqplaybook.md`, and no other profile namespace may silently change its behavior. If the skill proposes a durable preference, it supplies exact text for `[visualize]` and routes any approved update through the authorized writer under the repository's normal approval rules.

Coordination is required with the skills that produce the source-grounded material a visual artifact presents, including `/cite-check`, `/diligence`, `/read-redline`, `/definition-check`, and `/legalquants`. `/legaldesign` remains the reusable presentation layer and consumes versioned, structured outputs where appropriate rather than duplicating their workflow or authority-verification logic. It preserves stable IDs, status meanings, provenance, and limitations and normally produces a labelled companion to the native report. A proposed producer-side cross-reference or design handoff requires that skill's maintainer approval; no firm-specific tokens are baked into another skill by this note.

### Out of scope

Version one does not:

- invent legal analysis, facts, authorities, or conclusions;
- speculate to fill unsupported substantive gaps;
- replace lawyer review or judgment;
- independently verify legal authorities already assigned to `/cite-check`;
- duplicate the workflow logic of `/diligence`, `/read-redline`, `/definition-check`, or `/legalquants`;
- transmit confidential material outside the approved workspace;
- automatically publish, email, or share an artifact;
- operate as a full general-purpose design application; or
- promise non-HTML export formats.

The skill may synthesize workspace information, make reasonable interpretations, and fill communicative gaps when the record supports them. If substantive information is genuinely missing, the artifact flags the gap.

## How

Build and harden one template family at a time. Each family combines the skill instructions, template, tested components, export behavior, and eval fixtures. The thorough path uses one source ledger and small build specification, an optional standard-library scaffold that copies the closest tested shell without overwriting, and strict component validation that rejects unknown IDs, missing fields, and silent truncation. Model judgment remains responsible for audience, message, source fidelity, copy, relationship selection, evidence, and final inspection. A host without local scripts follows the same contract manually.

Generate artifacts across distinct legal workflows, inspect failures, refine the relevant reusable primitive, and save improvements back into the template or component system. Host model or reasoning controls may change elapsed time and polish, but not the fidelity, disclosure, accessibility, or export contract.

The initial eval program is:

1. **Memo-to-decision-map eval.** Give a first-time, nontechnical lawyer a conventional research memo and record time to the first useful response and time to an opened editable artifact. On the bounded fixture, test the under-ten-minute target while separately verifying substantive fidelity, absence of unsupported claims, successful editing, correct interactive behavior, and clean standalone HTML export. Record model/reasoning settings as context rather than changing the quality gate.
2. **Redline-explanation eval.** Supply a contract redline and the lawyer's explanation of the changes. Test whether the artifact accurately connects each material change to why it matters without creating new legal conclusions. Record lawyer corrections, component failures, and recipient comprehension.
3. **Engagement or pricing-options eval.** Supply supported engagement terms or fixed-pricing options. Test whether a recipient can distinguish the choices, understand their implications, and identify the next action. Record editing effort and any clarification questions or calls.
4. **Legal-research issue-map eval.** Supply grounded research and compatible `/cite-check` evidence bundles. Verify the question, rules, key authorities, competing interpretations, and factual dependencies against the source record. Test that each source card opens the correct evidence, locator, and provenance information.
5. **Document-companion eval.** Pair an artifact with a separate contract or document represented by an embedded PDF or HTML. Test navigation between each visual step and its corresponding document section. Bounded predetermined document changes are a later exploration, not a version-one commitment.
6. **Independent-reuse eval.** After a template passes its first workflow test, have another lawyer use it on a second matter. Record whether the template works without contributor intervention, what the lawyer changes, whether the output is delivered, and whether the lawyer chooses `/legaldesign` again for another artifact category.

For every eval, preserve the source material and primary generated output, log elapsed time and user edits, check factual and citation fidelity, exercise every interactive component, and verify both standalone and sanitized-template export paths when applicable. Temporary export files used for QA are removed unless they are part of the recorded eval evidence. Use a short comprehension task or set of decision questions to compare the artifact with its source communication. Treat any claimed improvement as unverified until the comparison produces evidence.

## When

`/legaldesign` ships as part of the LegalQuants plugin. No source-backed calendar date is committed in this Mini-PRD. The milestones are sequential:

1. Define the shared rubric, safety boundaries, `[visualize]` playbook contract, and cross-skill interfaces.
2. Build and pass the memo-to-decision-map eval for the layered one-page explainer.
3. Validate editing, clean standalone HTML export, and sanitized template export.
4. Add and harden the slide-deck template family.
5. Add and harden the due diligence report specialization, including fixed rail geometry and clean client-export chrome.
6. Run and refine the redline, engagement or pricing-options, research issue-map, and document-companion evals.
7. Demonstrate independent second-matter reuse and gather evidence for client comprehension, clarification reduction, and cross-workflow repeat use.
8. Add further document and visual-artifact types only after their templates and components meet the same fidelity, behavior, editing, and reuse standards.

The green light for each family depends on eval evidence, not on the breadth of the concept alone.
