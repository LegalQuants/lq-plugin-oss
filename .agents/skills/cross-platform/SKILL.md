---
name: cross-platform
description: >-
  Author provider-neutral skills and MCP for the CODEX for Legal plugin.
  Use when adding or editing a skill, choosing Claude-only primitives,
  packaging for ChatGPT Work or Codex, describing host capabilities, or
  designing multi-agent fan-out. ChatGPT Work is a first-class target.
metadata:
  internal: true
---

# Cross-platform skills

This is a **contributor** skill. It does not ship in the plugin. Read it
before adding or editing anything under `skills/`.

## What OpenAI and Claude both support

These are the portable primitives. Shared skills may depend on them.

| Primitive | Portable? | Notes |
|-----------|-----------|--------|
| Agent Skills (`SKILL.md` + optional `scripts/`, `references/`, `assets/`) | Yes | Authored under `skills/<group>/<name>/`; flattened to an immediate child of packaged `skills/`. Standard frontmatter only. |
| MCP servers | Yes | Prefer one remote Streamable HTTP server. No secrets in `mcp.json`. |
| Host document tools | Yes, when present | Read/convert local files. Degrade if absent. |
| Subagents / parallel workers | Sometimes | Capability, not a product name. Never required. |
| Local code execution | Sometimes | Python/Node may be missing. Scripts must be optional. |

Agent Plugins 1.0.0 is the portable ABI: root `plugin.json`, optional
`skills/`, optional `mcp.json`. It is a published spec, not a guarantee
that one ZIP is accepted unchanged by every marketplace. Generate
provider-native submission packages from that core.

## What is not jointly supported

Claude Code and Claude Cowork add primitives that ChatGPT Work does not
implement the same way, or at all:

- Dynamic Workflows (scripted fan-out in Claude Code)
- Plugin-packaged custom subagents (Cowork; not ordinary Claude Chat)
- Claude `hooks`, slash commands, `CLAUDE_PLUGIN_ROOT`
- Claude skill `dependencies:` that auto-install PyPI/npm packages

OpenAI plugins add their own extras, which Claude does not consume as-is:

- `.codex-plugin/plugin.json`
- OpenAI lifecycle hooks declared by the generated Codex manifest (this repository authors the combined hook at `packages/pluginctl/hooks/openai.json` and emits it as `hooks/openai.json`)
- `.app.json` connector mappings
- `agents/openai.yaml` MCP tool dependencies — **not** pip/npm install

A Claude Code or Claude Cowork skill dumped into this repo will often fail
in ChatGPT Work. **Ensuring the plugin works well in ChatGPT Work is a
first-class goal.** Codex launch is the immediate release; other hosts are
generated adapters, not a reason to block the MVP.

Do not put provider-only primitives in the shared skill corpus. Describe
optional host capabilities in the one authored `SKILL.md`. See
[assembly.md](references/assembly.md) and
[multi-agent.md](references/multi-agent.md).

## Rules for shared `SKILL.md`

1. Use only standard Agent Skills frontmatter (`name`, `description`).
   Do not use experimental `allowed-tools` in canonical source.
2. Do not mention ChatGPT, Claude, Gemini, Grok, or Cursor unless a
   behaviour genuinely differs — and then only in an orchestration
   fragment, with a `<!-- vendor-neutral-waiver: … -->` if the name
   appears in a common section.
3. Do not require hooks, commands, subagents, installation prompts, live
   artifacts, or provider-specific environment variables.
4. Do not require a particular model.
5. Refer to semantic operations ("retrieve the authority"), not
   `mcp__server__tool` names.
6. Provider-specific behaviour is progressive enhancement, never the only
   path that prevents a bad outcome (including confidentiality).

Most Legal Quants should write one skill that works cross-platform. Scripts
and orchestration are optional capabilities in the authored `SKILL.md`, not
provider-specific source variants.

## ChatGPT Work assumptions (design to these)

Treat the hosted ChatGPT Work sandbox as:

```text
public internet = unavailable
package installation = unavailable
sudo = unavailable
SDK credential handoff = unavailable
```

OpenAI skills may contain executable scripts. They have **no** documented
Claude-style `dependencies: pandas>=…` that installs PyPI/npm on plugin
install. Network access in Work is a user/admin setting, not a default
plugin authors can rely on.

Local Codex is a different surface (OS sandbox, configurable network).
Do not assume the hosted Work environment matches a laptop running Codex.

## MVP: no nested model SDKs

Do not ship the Codex SDK or the Claude Agent SDK as the required
orchestrator for the public plugin. Those introduce installation,
authentication, and billing problems the host's own workers already
cover for a GUI-first lawyer.

A later optional local-Codex runner is fine. It is not the ChatGPT Work
path.

## Remote MCP

Put behind MCP only work that needs auth, licensed data, persistence,
audit, or deterministic validation shared across hosts.

Do not move host-funded model inference onto our server for MVP. That
creates billing, accounts, and retention. A cheap deterministic splitter
or validator is optional; sending confidential briefs to our server just
to split text is usually the wrong default. Prefer local stdlib scripts,
then host-native extraction, then an optional disclosed stateless MCP
helper.

## Commands

```bash
pnpm pluginctl lint
pnpm pluginctl validate
pnpm pluginctl pack
pnpm pluginctl pack --check
```

Canonical skills live in `skills/<group>/<name>/`, where `group` is
`core`, `litigation`, `transactional`, or `companion`. The three generated
`plugins/<plugin-id>/` bundles are the catalog-facing outputs; each carries
the Claude Code and Codex manifest for that bundle. Provider build outputs
under `dist/` are disposable unless the repository explicitly tracks them.
Private maintainer evals belong to the private development repository and
never ship. Public design notes belong in
`packages/skill-docs/skills/<name>.md`; they stay in this repository and
never ship. `skills/<group>/<name>/` is the package source, so tests,
`PRD.md`, `AGENTS.md`, `CLAUDE.md`, `skill.yaml`, and `sections/` are
repository-only entries and validation errors there. Private eval cases stay
outside this public tree.
