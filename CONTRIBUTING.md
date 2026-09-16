# Contributing

LegalQuants welcomes focused improvements to the public skills and their supporting tooling. Start with an issue for a new skill, a change in scope, or a behavior that needs discussion; small documentation and reproducible bug fixes can go straight to a pull request.

Describe the user problem before proposing the implementation. For a skill change, include the intended trigger, inputs, workflow, deliverable, out-of-scope cases, and the limitation that a lawyer should see. Keep the description in plain language and show one representative input and output when the behavior is non-obvious.

Each skill has a maintainer or domain owner. Route substantive changes to that owner through the pull request and preserve the existing skill’s evidence and safety boundaries. A change that spans more than one skill or changes packaging needs review from the affected owners and the repository maintainers.

## Skill source and design notes

The canonical runtime source is `skills/<group>/<name>/SKILL.md`, with optional `scripts/`, `references/`, `assets/`, and `schemas/` directories beside it. The four groups are `core`, `litigation`, `transactional`, and `companion`.

Public design notes for current skills live in `packages/skill-docs/skills/<name>.md`. They describe intent, boundaries, and open limitations; they are not shipped inside a plugin. Do not put a design note, test, evaluation case, `AGENTS.md`, `CLAUDE.md`, `skill.yaml`, or generated file inside a canonical skill directory.

The public repository carries ordinary unit, browser, package, and packaging checks. Full private evaluation campaigns, confidential corpora, historical review records, and their results stay outside this repository. A public pull request must remain reproducible from the files available here.

## Set up

Use Node 22.19 or newer, the pinned pnpm version, and uv. From the repository root:

```sh
corepack enable
pnpm install
uv sync
pnpm exec playwright install chromium
```

On Linux, `pnpm exec playwright install --with-deps chromium` also installs the browser system libraries; CI uses that command.

No private repository, credential, or service account is required for the public checks. Do not add matter documents, credentials, private evaluation inputs, or generated caches to a pull request.

## Validate

Run the focused check for the area you changed, then run the root check before requesting review:

```sh
pnpm pluginctl validate
pnpm pluginctl pack --check
pnpm check
```

If you changed an authored skill or release metadata, regenerate the bundles before reviewing the diff:

```sh
pnpm pluginctl pack
```

Generated bundle directories under `plugins/` must be committed when the repository’s packer declares them tracked. The check command compares generated content with the canonical source and reports stale output; do not hand-edit generated bundle files.

Keep tests beside the package they exercise. Cross-skill and repository checks belong under `packages/skill-tests/tests`; plugin assembly and manifest checks belong under `packages/pluginctl/tests`; browser checks belong beside the public runtime package they exercise.

## Pull requests

Use a focused branch and pull request with a concise title. Explain the behavior before and after the change, list the checks you ran, and call out any limitation or follow-up that remains. Keep unrelated formatting or generated changes out of the pull request.

Reviewers should be able to reproduce the claim from the public tree. A green fixture test does not establish live provider behavior, legal correctness, marketplace publication, or workspace-admin approval; describe those boundaries when they matter.

Do not claim a skill supports a host, connector, jurisdiction, document format, or external service unless the repository contains a reproducible implementation and check for that claim. Provider-specific additions belong in generated adapters or optional host guidance, while the authored skill remains complete and safe without them.

The maintainers decide whether a change becomes canonical. Credit follows the work that is merged, and maintainers should preserve meaningful authorship in release notes or the pull request history.
