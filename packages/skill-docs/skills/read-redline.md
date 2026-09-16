# Mini-PRD: `/read-redline`

**Maintainer:** Jamie

## Description: What is it?

> **Status:** The authored skill supports the current shipped redline-reading workflow. The roadmap below records capabilities that still require separate validation.

The redline module reads a redlined PDF or a Word file with tracked changes, identifies each change, rates its significance, and prepares a marked-up copy or issues list. Scanned or rasterized pages with no live text layer remain a limitation. Compare generation and version control are outside the current scope.

## Problem: What problem is this solving?

Lawyers often receive PDF redlines with no structured change data, only visual marks on a page. Generic text extraction can discard the formatting that shows what changed, so the skill preserves the source marks and treats extraction limits as review items.

## Why: How do we know this is a real problem and worth solving?

- The pipeline reads span-level PDF formatting metadata (colour, strikethrough/underline geometry) directly — `pdfplumber` for extraction and `pypdf` for annotation, with a rendering check when available.
- Generic AI tooling that flattens PDFs to text loses that formatting entirely — it can't identify what changed, let alone classify it.
- The workflow is aimed at a recurring review problem: the lawyer needs to understand a received redline without losing the visual evidence that identifies each change.

## Success: How do we know if we've solved this problem?

The client self-triages the redline by materiality colour directly, without needing a separate cover email narrating the changes. That's the value — a new client experience, not just a faster read for the lawyer.

## Audience: Who are we building for?

Transactional lawyers are the primary audience. Use in other practice areas requires the same source and output checks against their documents.

## What: Roughly, what does this look like in the product?

- **Trigger:** you receive a PDF redline or a Word file with tracked changes and need to review it.
- **Inputs:** a PDF or Word redline, plus any relevant playbook preferences and review instructions.
- **Steps:**
  - Extract changes using pymupdf's span-level formatting metadata (colour, strikethrough, underline).
  - Colour-code each change by materiality.
  - Annotate the PDF in place with a plain-language explanation of each change, inline — not a separate summary document.
- **Deliverable:** annotated PDF, materiality-coded, with each change's direction (`favours-us` / `favours-them` / `neutral` / `unknown`) carried through where the analysis supplies it.
- **Voice/significance profile:** a portable, customisable significance rubric — persisted in `lqprofile.md`'s structured appendix, or a firm-level asset file — refined across matters, so matter #2 benefits from tuning done on matter #1. The canonical default lives in `skills/transactional/read-redline/references/significance_rubric.md`, tiered **High / Medium / Low** (rendered as red/amber/green highlights):
  - **High** — quantitative terms, core rights and obligations, liability/indemnity/warranty scope, substantive clauses added or removed.
  - **Medium** — dates, deadlines, notice and process requirements, scope narrowing/broadening without touching the core.
  - **Low** — wording cleanup, renumbering, cross-references, formatting — surfaced, never dropped (the rubric's bias rule).

This default is not a universal truth — different firms will define significance differently. It's overridable via the same persisted profile mechanism.
- **Profile:** *reads* the voice/materiality calibration before applying the default rubric, and answers "explain how this works" at the user's level. *Writes back* only high-signal moments: (taste lens) a user overriding a tier or rejecting a comment voice — revealed preference, proposed as an exact Calibration line for confirmation; (education lens) failure moments the user dug out of, logged in their own words to the profile's AI-failure section (mirroring the LQ application's question — passive use accumulates real application material without a forced pitch). Optionally keeps a `## Usage` counter in place. No per-run diary lines.
- **Out of scope:** compare-docx generation, version control, automatic acceptance of changes, and legal approval of a proposed change. Judging whether a change is acceptable stays with the lawyer.

## How: What is the experiment plan?

- Public checks should use fictional redlined contracts and expected findings. Private evaluation cases and comparative results remain outside this repository. Robustness across different counterparty conventions requires additional validation.

## Roadmap (out of the current scope)

- **Scanned/rasterized redlines** (no live text layer — needs an OCR stage).
- **Compare-docx generation** (a separate workflow with its own review and output contract).
- **Version control** (a separate workflow for tracking document generations).

## When: When does it ship and what are the milestones?

The skill is shipped in the transactional bundle. Further capability claims should wait for public synthetic checks and maintainer review of the relevant changes.
