# CODEX for Legal repository instructions

<!-- REPO-ONLY — everything between these markers is contributor plumbing, stripped at packaging; plugin users never see it. -->

This repository is the public source for the LegalQuants skill bundles. Read `CONTRIBUTING.md` before changing source, packaging, or public design notes.

Before adding or editing a shared skill, read [`.agents/skills/cross-platform/SKILL.md`](.agents/skills/cross-platform/SKILL.md). The canonical source is `skills/<group>/<name>/SKILL.md`; the groups are `core`, `litigation`, `transactional`, and `companion`.

Public design notes live in `packages/skill-docs/skills/`. Public checks and synthetic fixtures live under `packages/skill-tests/`, `packages/pluginctl/`, and the owning runtime package. Private evaluation campaigns, corpora, results, and historical development records do not belong in this repository.

After changing source skills or release metadata, run `pnpm pluginctl pack` and review the generated bundle directories under `plugins/`. Run `pnpm pluginctl pack --check` and `pnpm check` before requesting review. Do not hand-edit generated bundle output.

<!-- /REPO-ONLY -->

These rules apply to every skill in the generated plugins. Skill-specific instructions live in `skills/<group>/<name>/SKILL.md`; this file records the shared runtime boundaries.

## Profile and playbook separation

The playbook is the only stored surface that can affect ordinary skill behavior. It contains namespaced, confirmed preference lines such as `- [redline] prefers terse comment voice`.

A skill may read only confirmed entries in its own namespace. A skill may propose a line when the user reveals a preference, but it must show the exact text and write it only after explicit agreement. Unconfirmed proposals must not influence work.

The journey profile records the user’s practice context, learning history, and usage. Skills do not read `lqprofile.md` while doing legal work. A skill may read the archetype only when the user asks for coaching or an explanation, and that explanation is not work product.

Companion skills may write journey information through their shared store only with the user’s consent. A host-provided scribe may record session-level journey notes, but this repository does not activate a scribe or add a session-stop hook; current runtime behavior remains unchanged. Until such a component is explicitly provided and reviewed, companion skills are the only journey writers.

Never put client-confidential facts in a profile, playbook, journey note, or public repository file. Silence is not consent for a playbook entry.

## Tool cascade

Every skill that touches external tools states its cascade from open-source local tooling to host-native capabilities and, when the user or firm selects it, a licensed legal-grade service. The chosen rung must not change the evidence, safety, or approval contract.

## Judgment boundary

Encode method that travels across jurisdictions and practices. Keep firm playbooks, disputed positions, and single-jurisdiction choices as user or firm configuration rather than universal skill behavior.

## Provider-neutral skills

Shared skills must work with ordinary Agent Skills support, model reasoning, and optional MCP tools. Hooks, commands, subagents, and provider-specific environment variables are optional enhancements and must never be the only control that prevents a destructive action or confidentiality breach.

If a host exposes workers or local code, a skill may use them after checking the observed capability. Without those capabilities, use the same work units, evidence rules, and output contract sequentially.

## Temporary working data

For a multi-document run, use one temporary master JSON dataset for extraction and reconciliation instead of repeatedly rereading sources. Delete it on completion unless the user explicitly asks to retain a deliverable or audit record. Never write confidential working data into the repository or a generated plugin.
