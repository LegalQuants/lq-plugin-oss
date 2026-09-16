import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative } from "node:path";
import { preparePackagedMarkdown, stripRepoOnly } from "./strip-repo-only.js";
import { PACK_TARGETS, PACK_WRITE_TARGETS } from "./types.js";
import {
  buildClaudeCodeManifest,
  validateClaudeCodeManifest,
} from "./validate-claude-manifest.js";
import {
  buildOpenAiManifest,
  loadPluginBundles,
  type PluginBundle,
  SKILL_GROUPS,
  type SkillGroup,
  validateOpenAiManifest,
} from "./validate-manifest.js";

const REPO_ONLY_SKILL_ENTRIES = new Set([
  "evals",
  "test",
  "tests",
  "__tests__",
  "README.md",
  "PRD.md",
  "product-management",
  "skill.yaml",
  "sections",
  "CLAUDE.md",
  "AGENTS.md",
]);

export const SKILLS_ROOT = "skills";
/**
 * Claude's Git marketplace reads the repository checkout directly. Keep its
 * source in a committed, generated subtree so installing that marketplace
 * never gives Claude the repository's tests or maintainer tooling. The
 * combined package stores OpenAI's optional hook configuration as
 * `hooks/openai.json`, which Claude does not auto-load.
 */
export const CLAUDE_MARKETPLACE_ROOT = "plugins";
export const OPENAI_MARKETPLACE_ROOT = ".agents/plugins";
export const MARKETPLACE_NAME = "legalquants-skills";
export const GENERATED_MARKER =
  "<!-- AUTO-GENERATED from skill.yaml and sections/; run pnpm pluginctl pack -->";

function isBytecodeArtifact(name: string): boolean {
  return (
    name === "__pycache__" || name.endsWith(".pyc") || name.endsWith(".pyo")
  );
}

// Every authored skill file ships in every target, agents/openai.yaml
// included: it is five inert lines on the portable and Claude targets, and
// keeping the packaged tree file-for-file identical to the authored one is
// what the parity checks guarantee. Nothing is provider-only today.
const OPENAI_ONLY_SKILL_PATHS: ReadonlySet<string> = new Set();

export type PackOptions = {
  repoRoot: string;
  check: boolean;
};

export type PackResult = {
  wrote: Array<string>;
  stale: Array<string>;
};

export type SkillDir = {
  group: SkillGroup;
  name: string;
  dir: string;
};

export function listSkillDirs(repoRoot: string): Array<SkillDir> {
  const root = join(repoRoot, SKILLS_ROOT);

  if (!existsSync(root)) {
    return [];
  }

  return readdirSync(root, { withFileTypes: true }).flatMap((groupEntry) => {
    if (!groupEntry.isDirectory()) return [];
    if (!SKILL_GROUPS.includes(groupEntry.name as SkillGroup)) {
      if (listFiles(join(root, groupEntry.name)).length === 0) return [];
      throw new Error(
        `${SKILLS_ROOT}/${groupEntry.name} is not a recognized skill group`,
      );
    }
    const group = groupEntry.name as SkillGroup;
    const groupRoot = join(root, group);
    const skillDirs = readdirSync(groupRoot, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => ({
        group,
        name: entry.name,
        dir: join(groupRoot, entry.name),
      }));

    for (const { group: skillGroup, name, dir } of skillDirs) {
      if (!existsSync(join(dir, "SKILL.md"))) {
        throw new Error(
          `${SKILLS_ROOT}/${skillGroup}/${name}/SKILL.md is required for every authored skill directory`,
        );
      }
    }

    return skillDirs;
  });
}

export function listPackableSkillDirs(repoRoot: string): Array<SkillDir> {
  return listSkillDirs(repoRoot);
}

/**
 * The skills a bundle packages: every skill in the groups it takes, plus any
 * `include_skills` projected in from a group it does not take (today: the
 * companion includes `core/lq-start` without taking `core`). One source on disk;
 * the include is resolved at pack time.
 */
export function bundleSkillDirs(
  skillDirs: Array<SkillDir>,
  bundle: PluginBundle,
): Array<SkillDir> {
  return skillDirs.filter(
    ({ group, name }) =>
      bundle.skillGroups.includes(group) ||
      bundle.includeSkills.some(
        (included) => included.group === group && included.name === name,
      ),
  );
}

export function classifySkillTree(
  repoRoot: string,
  bundles: Array<PluginBundle>,
) {
  const skillDirs = listSkillDirs(repoRoot);
  for (const bundle of bundles) {
    for (const { group, name } of bundle.includeSkills) {
      if (!skillDirs.some((s) => s.group === group && s.name === name)) {
        throw new Error(
          `${bundle.manifest.name} includes ${group}/${name}, but ${SKILLS_ROOT}/${group}/${name} does not exist`,
        );
      }
    }
    // A skill name must be unique within each packaged plugin.
    const groupsByName = new Map<string, SkillGroup>();
    for (const { group, name } of bundleSkillDirs(skillDirs, bundle)) {
      const priorGroup = groupsByName.get(name);
      if (priorGroup !== undefined) {
        throw new Error(
          `skill ${name} appears in both ${priorGroup} and ${group}, which ${bundle.manifest.name} packages together; packaged skill names must be unique`,
        );
      }
      groupsByName.set(name, group);
    }
  }
  for (const { group, name, dir } of skillDirs) {
    const entries = new Set(
      readdirSync(dir, { withFileTypes: true }).map((entry) => entry.name),
    );
    for (const entry of REPO_ONLY_SKILL_ENTRIES) {
      if (entries.has(entry)) {
        const destination =
          entry === "evals"
            ? "the private maintainer eval repository"
            : entry === "test" || entry === "tests" || entry === "__tests__"
              ? "packages/skill-tests/tests"
              : entry === "README.md" ||
                  entry === "PRD.md" ||
                  entry === "product-management"
                ? `packages/skill-docs/skills/${name}.md`
                : "a repository-level contributor directory";
        throw new Error(
          `${SKILLS_ROOT}/${group}/${name}/${entry} is repository-only; move it to ${destination}`,
        );
      }
    }

    const skillMdPath = join(dir, "SKILL.md");
    if (!existsSync(skillMdPath)) {
      throw new Error(
        `${SKILLS_ROOT}/${group}/${name}/SKILL.md is required for every authored skill directory`,
      );
    }

    if (readFileSync(skillMdPath, "utf8").includes(GENERATED_MARKER)) {
      throw new Error(
        `${SKILLS_ROOT}/${group}/${name}/SKILL.md is marked AUTO-GENERATED; authored skills are the package source`,
      );
    }
  }
}

export function packAll(options: PackOptions) {
  const result: PackResult = { wrote: [], stale: [] };
  const bundles = loadPluginBundles(options.repoRoot);
  classifySkillTree(options.repoRoot, bundles);

  if (options.check) {
    const tmp = mkdtempSync(join(tmpdir(), "pluginctl-check-"));

    try {
      for (const target of PACK_WRITE_TARGETS) {
        for (const bundle of bundles) {
          writeTarget(
            options,
            { wrote: [], stale: [] },
            target,
            targetOutRoot(tmp, target, bundle.manifest.name),
            bundle,
          );
        }
      }
      for (const bundle of bundles) {
        writeCombinedBundle(
          options,
          { wrote: [], stale: [] },
          combinedOutRoot(tmp, bundle.manifest.name),
          bundle,
        );
      }
      collectCopiedSkillDrift(options.repoRoot, tmp, result, bundles);
      collectGeneratedBundleDrift(options.repoRoot, tmp, result, bundles);
      collectMarketplaceDrift(options.repoRoot, result, bundles);
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }

    return result;
  }

  removeRetiredDistTrees(options.repoRoot);

  for (const target of PACK_WRITE_TARGETS) {
    for (const bundle of bundles) {
      writeTarget(
        options,
        result,
        target,
        targetOutRoot(options.repoRoot, target, bundle.manifest.name),
        bundle,
      );
    }
  }

  for (const bundle of bundles) {
    writeCombinedBundle(
      options,
      result,
      combinedOutRoot(options.repoRoot, bundle.manifest.name),
      bundle,
    );
  }
  syncMarketplaces(options.repoRoot, result, bundles);

  return result;
}

function collectCopiedSkillDrift(
  repoRoot: string,
  tmpRoot: string,
  result: PackResult,
  bundles: Array<PluginBundle>,
) {
  for (const bundle of bundles) {
    const skills = bundleSkillDirs(listPackableSkillDirs(repoRoot), bundle);
    for (const { group, name, dir } of skills) {
      const source = Buffer.from(
        preparePackagedMarkdown(readFileSync(join(dir, "SKILL.md"), "utf8")),
      );

      for (const target of PACK_WRITE_TARGETS) {
        const packed = join(
          targetOutRoot(tmpRoot, target, bundle.manifest.name),
          "skills",
          name,
          "SKILL.md",
        );
        if (!existsSync(packed) || !readFileSync(packed).equals(source)) {
          result.stale.push(
            `skills/${group}/${name}/SKILL.md would differ in the ${target}/${bundle.manifest.name} package`,
          );
        }
      }
    }
  }
}

function collectGeneratedBundleDrift(
  repoRoot: string,
  tmpRoot: string,
  result: PackResult,
  bundles: Array<PluginBundle>,
) {
  const hasGeneratedOutputs = hasCommittedGeneratedOutputs(repoRoot);

  // Pack fixtures and portable-only consumers do not need a checked-in
  // marketplace mirror. The real repository does, because Claude installs
  // the source named by marketplace.json from Git without running pack.
  if (!hasGeneratedOutputs) {
    return;
  }

  for (const bundle of bundles) {
    const expected = combinedOutRoot(tmpRoot, bundle.manifest.name);
    const actual = join(
      repoRoot,
      CLAUDE_MARKETPLACE_ROOT,
      bundle.manifest.name,
    );

    if (!existsSync(actual)) {
      result.stale.push(
        `${relative(repoRoot, actual)} is missing; run pnpm pluginctl pack`,
      );
      continue;
    }

    const expectedFiles = listFiles(expected);
    const actualFiles = listFiles(actual);
    const allFiles = new Set([...expectedFiles, ...actualFiles]);

    for (const relativePath of allFiles) {
      const expectedPath = join(expected, relativePath);
      const actualPath = join(actual, relativePath);

      if (
        !existsSync(expectedPath) ||
        !existsSync(actualPath) ||
        !readFileSync(expectedPath).equals(readFileSync(actualPath)) ||
        (existsSync(expectedPath) &&
          existsSync(actualPath) &&
          readFileMode(expectedPath) !== readFileMode(actualPath))
      ) {
        result.stale.push(
          `${relative(repoRoot, actualPath)} would differ from the generated combined package`,
        );
      }
    }
  }

  const generatedRoot = join(repoRoot, CLAUDE_MARKETPLACE_ROOT);
  const declared = new Set(bundles.map(({ manifest }) => manifest.name));
  if (existsSync(generatedRoot)) {
    for (const entry of readdirSync(generatedRoot, { withFileTypes: true })) {
      if (entry.isDirectory() && !declared.has(entry.name)) {
        result.stale.push(
          `${relative(repoRoot, join(generatedRoot, entry.name))} is not declared in plugin.release.yaml`,
        );
      }
    }
  }
}

function collectMarketplaceDrift(
  repoRoot: string,
  result: PackResult,
  bundles: Array<PluginBundle>,
) {
  const hasGeneratedOutputs = hasCommittedGeneratedOutputs(repoRoot);
  if (!hasGeneratedOutputs) {
    return;
  }

  const expected = [
    [
      join(repoRoot, ".claude-plugin/marketplace.json"),
      renderJson(buildClaudeMarketplace(bundles)),
    ],
    [
      join(repoRoot, `${OPENAI_MARKETPLACE_ROOT}/marketplace.json`),
      renderJson(buildOpenAiMarketplace(bundles)),
    ],
  ] as const;

  for (const [path, content] of expected) {
    if (!existsSync(path)) {
      result.stale.push(
        `${relative(repoRoot, path)} is missing; run pnpm pluginctl pack`,
      );
      continue;
    }
    if (readFileSync(path, "utf8") !== content) {
      result.stale.push(
        `${relative(repoRoot, path)} would differ from generated marketplace metadata`,
      );
    }
  }
}

function syncMarketplaces(
  repoRoot: string,
  result: PackResult,
  bundles: Array<PluginBundle>,
) {
  const generatedRoot = join(repoRoot, CLAUDE_MARKETPLACE_ROOT);
  const declared = new Set(bundles.map(({ manifest }) => manifest.name));
  if (existsSync(generatedRoot)) {
    for (const entry of readdirSync(generatedRoot, { withFileTypes: true })) {
      if (entry.isDirectory() && !declared.has(entry.name)) {
        rmSync(join(generatedRoot, entry.name), {
          recursive: true,
          force: true,
        });
      }
    }
  }
  writeFile(
    join(repoRoot, ".claude-plugin/marketplace.json"),
    renderJson(buildClaudeMarketplace(bundles)),
  );
  writeFile(
    join(repoRoot, `${OPENAI_MARKETPLACE_ROOT}/marketplace.json`),
    renderJson(buildOpenAiMarketplace(bundles)),
  );
  result.wrote.push(
    join(repoRoot, ".claude-plugin/marketplace.json"),
    join(repoRoot, `${OPENAI_MARKETPLACE_ROOT}/marketplace.json`),
  );
}

function hasCommittedGeneratedOutputs(repoRoot: string): boolean {
  return (
    existsSync(join(repoRoot, ".claude-plugin/marketplace.json")) ||
    existsSync(join(repoRoot, `${OPENAI_MARKETPLACE_ROOT}/marketplace.json`)) ||
    existsSync(join(repoRoot, CLAUDE_MARKETPLACE_ROOT))
  );
}

function listFiles(root: string, prefix = ""): Array<string> {
  if (!existsSync(root)) {
    return [];
  }

  const files: Array<string> = [];

  for (const entry of readdirSync(root, { withFileTypes: true })) {
    if (isBytecodeArtifact(entry.name)) {
      continue;
    }

    const relativePath = join(prefix, entry.name);
    const path = join(root, entry.name);

    if (entry.isDirectory()) {
      files.push(...listFiles(path, relativePath));
    } else {
      files.push(relativePath);
    }
  }

  return files;
}

function targetOutRoot(
  repoRoot: string,
  target: (typeof PACK_WRITE_TARGETS)[number],
  pluginName: string,
) {
  const targetRoot =
    target === "portable"
      ? join(repoRoot, "dist/agent-plugins")
      : join(repoRoot, "dist", target);
  return join(targetRoot, pluginName);
}

function combinedOutRoot(repoRoot: string, pluginName: string) {
  return join(repoRoot, CLAUDE_MARKETPLACE_ROOT, pluginName);
}

function removeRetiredDistTrees(repoRoot: string) {
  const written = new Set<string>(PACK_WRITE_TARGETS);

  for (const target of PACK_TARGETS) {
    if (written.has(target)) {
      continue;
    }

    rmSync(join(repoRoot, "dist", target), { recursive: true, force: true });
  }
}

function writeTarget(
  options: PackOptions,
  result: PackResult,
  target: (typeof PACK_WRITE_TARGETS)[number],
  outRoot: string,
  bundle: PluginBundle,
) {
  rmSync(outRoot, { recursive: true, force: true });
  writeManifest(options.repoRoot, outRoot, target, bundle);
  copySkills(options.repoRoot, outRoot, target, bundle);
  copyPortableInstructions(options.repoRoot, outRoot, target);
  if (target === "openai") {
    copyOpenAiAssets(options.repoRoot, outRoot);
    copyOpenAiHooks(options.repoRoot, outRoot);
    writeBannerData(options.repoRoot, outRoot, bundle);
  }
  result.wrote.push(outRoot);
}

function writeCombinedBundle(
  options: PackOptions,
  result: PackResult,
  outRoot: string,
  bundle: PluginBundle,
) {
  rmSync(outRoot, { recursive: true, force: true });
  writeManifest(options.repoRoot, outRoot, "openai", bundle);
  writeManifest(options.repoRoot, outRoot, "claude-code", bundle);
  copySkills(options.repoRoot, outRoot, "openai", bundle);
  copyOpenAiAssets(options.repoRoot, outRoot);
  copyOpenAiHooks(options.repoRoot, outRoot);
  writeBannerData(options.repoRoot, outRoot, bundle);
  result.wrote.push(outRoot);
}

function copyOpenAiAssets(repoRoot: string, outRoot: string) {
  copyShippedTree(
    join(repoRoot, "packages/pluginctl/assets/openai"),
    join(outRoot, "assets"),
  );
}

function copyOpenAiHooks(repoRoot: string, outRoot: string) {
  const hooks = join(repoRoot, "packages/pluginctl/hooks");

  if (existsSync(join(hooks, "openai.json"))) {
    copyShippedTree(hooks, join(outRoot, "hooks"), new Set(["README.md"]));
  }
}

/**
 * The session card's data, beside the banner hook: the plugin's display name
 * and its one first move. Every `$name` in the first move must be a skill in
 * this bundle, so the card never names a skill the plugin does not ship.
 */
function writeBannerData(
  repoRoot: string,
  outRoot: string,
  bundle: PluginBundle,
) {
  if (!existsSync(join(outRoot, "hooks"))) return;
  const shipped = new Set(
    bundleSkillDirs(listSkillDirs(repoRoot), bundle).map(({ name }) => name),
  );
  const firstMove = bundle.firstMove;
  if (firstMove !== undefined) {
    for (const [, name] of firstMove.matchAll(/\$([a-z0-9-]+)/g)) {
      if (name === undefined || !shipped.has(name)) {
        throw new Error(
          `${bundle.manifest.name} first_move names $${name}, which the bundle does not ship`,
        );
      }
    }
  }
  writeFile(
    join(outRoot, "hooks/banner.json"),
    `${JSON.stringify(
      {
        plugin: bundle.displayName,
        ...(firstMove === undefined ? {} : { first_move: firstMove }),
      },
      null,
      2,
    )}\n`,
  );
}

function writeManifest(
  repoRoot: string,
  outRoot: string,
  target: "portable" | "openai" | "claude-code",
  bundle: PluginBundle,
) {
  const portable = bundle.manifest;

  if (target === "openai") {
    const hooksPath = existsSync(
      join(repoRoot, "packages/pluginctl/hooks/openai.json"),
    )
      ? "./hooks/openai.json"
      : undefined;
    const manifest = buildOpenAiManifest(portable, {
      ...(hooksPath === undefined ? {} : { hooks: hooksPath }),
      displayName: bundle.displayName,
      ...(bundle.shortDescription === undefined
        ? {}
        : { shortDescription: bundle.shortDescription }),
    });
    const errors = validateOpenAiManifest(repoRoot, manifest);

    if (errors.length > 0) {
      throw new Error(
        `generated OpenAI manifest is invalid:\n${errors.join("\n")}`,
      );
    }

    writeFile(
      join(outRoot, ".codex-plugin/plugin.json"),
      `${JSON.stringify(manifest, null, 2)}\n`,
    );
    return;
  }

  if (target === "claude-code") {
    const manifest = buildClaudeCodeManifest(portable);
    const errors = validateClaudeCodeManifest(repoRoot, manifest);

    if (errors.length > 0) {
      throw new Error(
        `generated Claude Code manifest is invalid:\n${errors.join("\n")}`,
      );
    }

    writeFile(
      join(outRoot, ".claude-plugin/plugin.json"),
      `${JSON.stringify(manifest, null, 2)}\n`,
    );
    return;
  }

  writeFile(
    join(outRoot, "plugin.json"),
    `${JSON.stringify(portable, null, 2)}\n`,
  );
}

function copySkills(
  repoRoot: string,
  outRoot: string,
  target: "portable" | "openai" | "claude-code",
  bundle: PluginBundle,
) {
  for (const { name, dir } of bundleSkillDirs(
    listPackableSkillDirs(repoRoot),
    bundle,
  )) {
    copySkillTree(
      dir,
      join(outRoot, "skills", name),
      target === "openai" ? undefined : OPENAI_ONLY_SKILL_PATHS,
    );
  }
}

function copySkillTree(
  from: string,
  to: string,
  excludedPaths?: ReadonlySet<string>,
  relativePath = "",
) {
  mkdirSync(to, { recursive: true });

  for (const entry of readdirSync(from, { withFileTypes: true })) {
    if (isBytecodeArtifact(entry.name)) {
      continue;
    }

    const entryPath = relativePath
      ? `${relativePath}/${entry.name}`
      : entry.name;
    if (excludedPaths?.has(entryPath)) {
      continue;
    }

    const source = join(from, entry.name);
    const dest = join(to, entry.name);

    if (entry.isDirectory()) {
      copySkillTree(source, dest, excludedPaths, entryPath);
      continue;
    }

    if (entry.name.endsWith(".md")) {
      writeFile(dest, preparePackagedMarkdown(readFileSync(source, "utf8")));
      continue;
    }

    cpSync(source, dest);
  }
}

function copyPortableInstructions(
  repoRoot: string,
  outRoot: string,
  target: "portable" | "openai" | "claude-code",
) {
  if (target === "portable") {
    writeFile(
      join(outRoot, "AGENTS.md"),
      stripRepoOnly(readFileSync(join(repoRoot, "AGENTS.md"), "utf8")),
    );
  }
}

function copyShippedTree(
  from: string,
  to: string,
  excludedPaths: ReadonlySet<string> = new Set(),
  relativePath = "",
) {
  mkdirSync(to, { recursive: true });

  for (const entry of readdirSync(from, { withFileTypes: true })) {
    const entryPath = relativePath
      ? `${relativePath}/${entry.name}`
      : entry.name;
    if (excludedPaths.has(entryPath)) {
      continue;
    }
    const source = join(from, entry.name);
    const dest = join(to, entry.name);

    if (entry.isDirectory()) {
      copyShippedTree(source, dest, excludedPaths, entryPath);
      continue;
    }

    if (entry.name.endsWith(".md")) {
      writeFile(dest, preparePackagedMarkdown(readFileSync(source, "utf8")));
      continue;
    }

    cpSync(source, dest);
  }
}

function writeFile(path: string, content: string) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content);
}

function readFileMode(path: string): number {
  return statSync(path).mode & 0o777;
}

function renderJson(value: object): string {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function buildClaudeMarketplace(bundles: Array<PluginBundle>) {
  return {
    name: MARKETPLACE_NAME,
    owner: {
      name: "LegalQuants",
      url: "https://legalquants.com",
    },
    description: "Practice-focused LegalQuants skill bundles.",
    plugins: bundles.map(({ manifest }) => ({
      name: manifest.name,
      source: `./plugins/${manifest.name}`,
      description: manifest.description,
      strict: true,
    })),
  };
}

function buildOpenAiMarketplace(bundles: Array<PluginBundle>) {
  return {
    name: MARKETPLACE_NAME,
    interface: { displayName: "LegalQuants Skills" },
    plugins: bundles.map(({ manifest }) => ({
      name: manifest.name,
      source: {
        source: "local",
        path: `./plugins/${manifest.name}`,
      },
      policy: {
        installation: "AVAILABLE",
        authentication: "ON_INSTALL",
      },
      category: "Productivity",
    })),
  };
}
