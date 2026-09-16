# Static skill authoring and packaging

Provider-neutral means one authored skill tree and one semantic workflow. The canonical source is already the portable package: `pluginctl` copies it into each generated provider tree. Do not create a provider-specific fork of a shared `SKILL.md`.

## Source layout

Classify and author a skill under `skills/<group>/<name>/`, where `group` is `core`, `litigation`, `transactional`, or `companion`:

```text
skills/<group>/<name>/
├── SKILL.md                 # the one authored skill and portable golden
├── scripts/                 # optional local, deterministic helpers
├── references/              # optional supporting instructions
├── assets/                  # optional templates and static resources
└── schemas/                 # optional machine-readable contracts
```

Keep the method, evidence rules, safety boundaries, and output contract in that one `SKILL.md`. Supporting files are part of the same tree and must use relative links that remain valid after packaging.

Public design notes live in `packages/skill-docs/skills/<name>.md`; they are repository documentation and never ship. Private maintainer evals, corpora, and result records remain in the private development repository. Public unit, browser, and packaging tests live in `packages/skill-tests/`, `packages/pluginctl/`, or the owning runtime package.

Do not put tests, `PRD.md`, `AGENTS.md`, `CLAUDE.md`, `skill.yaml`, or `sections/` under `skills/<group>/<name>/`. The packer rejects those repository-only entries rather than silently removing them.

HTML comments in authored Markdown are maintainer annotations by default. The packer removes repository-only comments from provider packages. Keep user-facing limitations visible in the authored skill; keep contributor rationale and historical records in public design notes or private maintainer records.

Use only standard Agent Skills frontmatter (`name` and `description`). Do not add generated markers, symlinks, provider-only source variants, or another manifest inside a canonical skill directory.

## Packaging

`pnpm pluginctl pack` builds the three audience plugins from the same source bytes. The generated bundle directories under `plugins/<plugin-id>/` contain the provider manifests and flattened `skills/<name>/` trees required by their catalogs. Each generated bundle carries the Claude Code and Codex manifest for that bundle; provider build directories under `dist/` are disposable local outputs unless the repository explicitly tracks them.

The practice plugins receive `core` plus one practice group. The Companion receives `companion` plus the explicitly included `core/lq-start` skill. `plugin.release.yaml` is the source of truth for those memberships.

The packer flattens each selected source skill to `skills/<name>/` inside a bundle and preserves the authored `SKILL.md` bytes after removing repository-only annotations. `pnpm pluginctl pack --check` regenerates into a temporary directory and fails when any generated bundle is missing or stale.

Provider manifests, hooks, and catalog metadata belong in generated adapter trees, never in the shared skill source. This repository authors the combined OpenAI hook at `packages/pluginctl/hooks/openai.json`; the packer emits it as `hooks/openai.json` and points only the Codex manifest at that explicit path. A provider adapter may add progressive enhancements, but the shared skill must remain complete and safe without them. OpenAI-only hooks must not be discovered by a Claude package, and Claude-only hooks must not be assumed by a Codex package.

Run these commands from the repository root:

```bash
pnpm pluginctl lint
pnpm pluginctl validate
pnpm pluginctl pack
pnpm pluginctl pack --check
```

Review the generated diff after `pack`. Do not hand-edit generated bundle files; change the canonical source or release metadata and regenerate.

## Capability-based runtime selection

Runtime differences are selected from capabilities observed in the current host, not from a hard-coded provider variant or a model-name guess. A skill that can use local scripts or fan-out should describe this decision in its authored `SKILL.md` and keep the same work-unit, evidence, and result contract on every path.

Use this order unless the skill has a stricter safety boundary:

1. Run a deterministic environment probe and record only capabilities it establishes: local execution, the packaged script, native workers, and any supported scheduler or fan-out mechanism. An installed executable proves presence, not authorization or usable credentials.
2. If a script would invoke a model or another provider, require an explicit user or firm configuration choice before sending matter material or incurring model spend. Otherwise stay on the host-native path.
3. Prefer the highest-capability authorized path: a bounded deterministic scripted fan-out when the current host exposes and permits it, then host-managed workers or subagents, then a file-backed segmented plan, and finally sequential processing. Every path keeps the same assignments and output schema.
4. Report the selected path, observed capabilities, authorization basis, and any unavailable capability. Never infer that a provider or fan-out path worked from command presence or from a failed canary.

Use stable semantic capability names:

```text
scripted_fanout     — a permitted scheduler can launch bounded work units
native_delegation   — the host manages workers or subagents
sequential          — the parent can process the same units one at a time
```

A host without local code execution or workers still follows the same legal method sequentially.
