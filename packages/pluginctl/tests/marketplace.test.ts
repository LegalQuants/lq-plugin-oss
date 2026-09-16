import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { CLAUDE_MARKETPLACE_ROOT, listPackableSkillDirs } from "../src/pack.js";
import { findRepoRoot } from "../src/repo.js";
import { loadPluginBundles } from "../src/validate-manifest.js";

type ClaudeMarketplace = {
  name?: unknown;
  owner?: unknown;
  plugins?: unknown;
};

type ClaudePluginEntry = {
  name?: unknown;
  source?: unknown;
  strict?: unknown;
  skills?: unknown;
};

type OpenAiMarketplace = {
  name?: unknown;
  interface?: unknown;
  plugins?: unknown;
};

const marketplacePath = (repoRoot: string) =>
  join(repoRoot, ".claude-plugin/marketplace.json");

const openAiMarketplacePath = (repoRoot: string) =>
  join(repoRoot, ".agents/plugins/marketplace.json");

function readMarketplace(repoRoot: string): ClaudeMarketplace {
  return JSON.parse(
    readFileSync(marketplacePath(repoRoot), "utf8"),
  ) as ClaudeMarketplace;
}

describe("Claude repository marketplace", () => {
  it("declares three strict plugins from committed generated packages", () => {
    const repoRoot = findRepoRoot();
    const marketplace = readMarketplace(repoRoot);
    const plugins = marketplace.plugins;

    expect(marketplace.name).toBe("legalquants-skills");
    expect(marketplace.owner).toMatchObject({ name: "LegalQuants" });
    expect(Array.isArray(plugins)).toBe(true);
    expect(plugins).toHaveLength(3);
    expect(plugins).toEqual(
      loadPluginBundles(repoRoot).map(({ manifest }) =>
        expect.objectContaining({
          name: manifest.name,
          source: `./plugins/${manifest.name}`,
          strict: true,
        }),
      ),
    );
    for (const plugin of plugins as Array<ClaudePluginEntry>) {
      expect(plugin).not.toHaveProperty("skills");
    }
    expect(listPackableSkillDirs(repoRoot)).not.toHaveLength(0);
  });

  it("points at a checked-in generated package and excludes repository material", () => {
    const repoRoot = findRepoRoot();
    const plugins = readMarketplace(repoRoot)
      .plugins as Array<ClaudePluginEntry>;
    const bundles = loadPluginBundles(repoRoot);
    for (const [index, plugin] of plugins.entries()) {
      const bundle = bundles[index];
      if (bundle === undefined) throw new Error("missing plugin bundle");
      const source = resolve(repoRoot, String(plugin.source));
      expect(String(plugin.source)).toBe(`./plugins/${bundle.manifest.name}`);
      expect(existsSync(join(source, ".claude-plugin/plugin.json"))).toBe(true);
      expect(existsSync(join(source, ".codex-plugin/plugin.json"))).toBe(true);
      expect(existsSync(join(source, "skills"))).toBe(true);
      expect(existsSync(join(source, "hooks/hooks.json"))).toBe(false);
      expect(existsSync(join(source, "hooks/openai.json"))).toBe(true);

      for (const forbidden of [
        "AGENTS.md",
        "CLAUDE.md",
        "README.md",
        "PRD.md",
        "dev-tools",
        "docs",
        "tests",
        "node_modules",
        ".venv",
        ".claude-plugin/marketplace.json",
      ]) {
        expect(
          existsSync(join(source, forbidden)),
          `${CLAUDE_MARKETPLACE_ROOT}/${bundle.manifest.name} unexpectedly contains ${forbidden}`,
        ).toBe(false);
      }

      const claudeManifest = JSON.parse(
        readFileSync(join(source, ".claude-plugin/plugin.json"), "utf8"),
      ) as Record<string, unknown>;
      const openAiManifest = JSON.parse(
        readFileSync(join(source, ".codex-plugin/plugin.json"), "utf8"),
      ) as Record<string, unknown>;
      expect(claudeManifest).not.toHaveProperty("hooks");
      expect(openAiManifest).toMatchObject({ hooks: "./hooks/openai.json" });

      for (const { group, name } of listPackableSkillDirs(repoRoot)) {
        const included = bundle.includeSkills.some(
          (skill) => skill.group === group && skill.name === name,
        );
        expect(
          existsSync(join(source, "skills", name, "SKILL.md")),
          `${bundle.manifest.name} skills/${name}`,
        ).toBe(bundle.skillGroups.includes(group) || included);
      }
    }
  });
});

describe("OpenAI repository marketplace", () => {
  it("has the same ordered bundle inventory and relative package paths", () => {
    const repoRoot = findRepoRoot();
    const marketplace = JSON.parse(
      readFileSync(openAiMarketplacePath(repoRoot), "utf8"),
    ) as OpenAiMarketplace;
    const bundles = loadPluginBundles(repoRoot);
    expect(marketplace).toMatchObject({
      name: "legalquants-skills",
      interface: { displayName: "LegalQuants Skills" },
    });
    expect(marketplace.plugins).toEqual(
      bundles.map(({ manifest }) => ({
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
    );
  });
});
