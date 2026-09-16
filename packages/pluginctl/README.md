# `@lq/pluginctl`

Lint, pack, and locally install static skills.

```bash
pnpm pluginctl pack          # build all three plugins from skills/<group>/<name>/
pnpm pluginctl pack --check  # fail if leftover assembly files exist or packed SKILL.md would drift
pnpm pluginctl install-openai # pack and install a cache-busted local OpenAI copy
pnpm pluginctl lint          # vendor names in authored SKILL.md
pnpm pluginctl validate      # manifests + release metadata + lint + check
```

Use the root `pnpm pluginctl` script. Every skill lives in
`skills/<group>/<name>/` with an authored `SKILL.md`. The four source groups
are `core`, `litigation`, `transactional`, and `companion`. A bundle in
`plugin.release.yaml` lists the groups it takes under `skill_groups`, and may
name individual skills from other groups under `include_skills` as
`group/name` (the Companion includes `core/lq-start` this way).
See `.agents/skills/cross-platform/SKILL.md`.

The `skills/` tree is also the direct-install source. Once the repository is public, skills can be installed without a build with:

```bash
npx skills add https://github.com/LegalQuants/lq-plugin-oss/tree/main/skills
```

That command is distinct from `pluginctl`: it does not assemble a provider package or use a repository marketplace. The URL may not be reachable while the repository is private.

`pack` is the full-provider path. It assembles one package for each configured audience under `dist/agent-plugins/<plugin-id>/`, `dist/openai/<plugin-id>/`, and `dist/claude-code/<plugin-id>/` from the same authored skill bytes, then refreshes the three committed combined `plugins/<plugin-id>/` packages. Each combined package contains both provider manifests; its OpenAI hook configuration is named explicitly as `hooks/openai.json`, so Claude does not auto-load it. The root `.claude-plugin/marketplace.json` and `.agents/plugins/marketplace.json` catalogs are generated from the same bundle definitions. `pack --check` fails when a native package, combined package, or catalog differs from generated output. Claude Cowork remains a separate acceptance target.

`install-openai` keeps `pack` pure: it first runs the normal pack, then copies
the three `dist/openai/<plugin-id>/` trees into the ignored
`dist/local-openai-marketplace` tree. It writes
the `lq-local` marketplace entry, replaces only the staged manifest's version
with a UTC `+codex.local-YYYYMMDD-HHMMSS` cachebuster, verifies any configured
marketplace with that name points at this path, and installs all three plugins
from `lq-local`. The process runner is injectable in tests, and the
command asks you to start a new Codex task after installation so updated skills
and tools are loaded.

The local `lq-local` marketplace is for repository testing, not the OpenAI portal. Portal upload and review happen separately and are not performed by `pluginctl`. Likewise, adding the repository-local `.claude-plugin/marketplace.json` as an arbitrary Git marketplace in Claude Code is a user-selected source path; it installs only the three committed generated `plugins/<plugin-id>/` subtrees and is not a reviewed community listing. A reviewed community-marketplace listing requires a separate acceptance and publication step. No public OpenAI or Claude marketplace artifact is implied by these local/generated paths.
