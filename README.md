# LegalQuants skills

LegalQuants skills are provider-neutral workflows for lawyers. The authored skills live under `skills/`; the repository builds three audience plugins from that one source tree.

The public repository is [LegalQuants/lq-plugin-oss](https://github.com/LegalQuants/lq-plugin-oss). The repository is being prepared for public distribution; installation commands below apply when your host can reach the repository and its catalog.

## Bundles

| Bundle | Source membership | Start here |
| --- | --- | --- |
| LegalQuants Skills for Litigators (`legalquants-litigation`) | `core` + `litigation` | `$lq-start`, then `$cite-check` for a filing |
| LegalQuants Skills for Transactional Attorneys (`legalquants-transactional`) | `core` + `transactional` | `$lq-start`, then `$read-redline` for a markup |
| The LegalQuants Companion (`legalquants-companion`) | `companion` + `core/lq-start` | `$legalquants` for the journey, `$lq-start` for the skill map |

`core` is shared source, not a fourth plugin. The transactional source group is named for the subject matter and supplies the transactional-attorney bundle.

The current source membership is defined in [`plugin.release.yaml`](plugin.release.yaml) and these group directories:

- `core`: `legaldesign`, `lq-start`, `regulatory`, `timenarratives`, `wiki`.
- `litigation`: `cite-check`, `client-update`, `correspondence`, `depositions`, `docreview`, `document-discovery`, `new-matter`, `organize-case-docs`, `pressuretest`, `writing`.
- `transactional`: `closing-bible`, `closing-checklist`, `conform`, `definition-check`, `diligence`, `playbook-builder`, `playbook-review`, `read-redline`, `sigpack`.
- `companion`: `legalquants`, `lq-apply`, `lq-ask`, `lq-connect`, `lq-mirror`, `lq-reflect`, `my-lq-moment`.

## Install one skill

When the repository is reachable, the skills installer can add one authored skill directly to a supported agent target:

```sh
pnpm dlx skills add LegalQuants/lq-plugin-oss --skill cite-check --agent codex
pnpm dlx skills add LegalQuants/lq-plugin-oss --skill cite-check --agent claude-code
```

Replace `cite-check` with another skill name from the current membership above. Direct skill installation selects a `SKILL.md`; it does not install an audience plugin, hooks, or the native catalog.

## Install an audience plugin from a native catalog

The repository contains a Claude Code marketplace catalog and generated bundles for both Claude Code and Codex. Add the repository marketplace once, then install the bundle you need.

For Codex:

```sh
codex plugin marketplace add LegalQuants/lq-plugin-oss
codex plugin add legalquants-litigation@legalquants-skills
```

Use `legalquants-transactional` or `legalquants-companion` in the second command for the other bundles. Local development uses the same native commands through `pnpm pluginctl install-openai`; that command is a local test path and does not publish a marketplace listing.

For Claude Code:

```sh
claude plugin marketplace add LegalQuants/lq-plugin-oss
claude plugin install legalquants-litigation@legalquants-skills
```

The equivalent interactive commands are `/plugin marketplace add LegalQuants/lq-plugin-oss` and `/plugin install legalquants-litigation@legalquants-skills`. Claude installs each generated bundle as a plugin and exposes its skills under that plugin’s namespace; see the [Claude Code marketplace documentation](https://code.claude.com/docs/en/discover-plugins) for scopes and host-specific behavior.

Some GUI workspaces offer a plugin or skill import screen. A workspace import is an administrator-controlled operation; a repository URL or a successful local clone does not grant permission to add it to an organization workspace. Ask the workspace administrator to import the reviewed bundle through the product’s native catalog or import flow.

## Develop

Contributors edit an authored skill at `skills/<group>/<name>/SKILL.md` and keep supporting scripts, references, assets, and schemas beside that file. Read [`.agents/skills/cross-platform/SKILL.md`](.agents/skills/cross-platform/SKILL.md) before changing a shared skill.

The generated bundle directories under `plugins/` are build products. After changing a source skill or packaging metadata, run `pnpm pluginctl pack`, review the generated changes, and use `pnpm pluginctl pack --check` to prove that generated files match the source. The root `pnpm check` command runs the repository’s formatting, lint, type, test, validation, and packaging checks.

Public contributors do not need access to the private development repository. Public tests, package sources, schemas, synthetic fixtures, and browser checks live under `packages/`; private full evaluation campaigns, corpora, results, and historical development records remain outside this repository.

Licensed under [Apache-2.0](LICENSE). Each skill and plugin bundle includes the license so it travels with standalone installations. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contribution workflow and [`SECURITY.md`](SECURITY.md) for reporting guidance.
