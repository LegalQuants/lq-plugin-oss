import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { findRepoRoot } from "../src/repo.js";
import {
  buildClaudeCodeManifest,
  validateClaudeCodeManifest,
} from "../src/validate-claude-manifest.js";
import {
  validateContractSchemaCopies,
  validateReleaseMetadata,
} from "../src/validate-consistency.js";
import {
  buildOpenAiManifest,
  loadPluginBundles,
  validateOpenAiManifest,
  validatePluginManifest,
} from "../src/validate-manifest.js";

describe("validatePluginManifest", () => {
  it("accepts every manifest in the canonical release catalog", () => {
    const repoRoot = findRepoRoot();
    const bundles = loadPluginBundles(repoRoot);
    expect(bundles.map(({ manifest }) => manifest.name)).toEqual([
      "legalquants-litigation",
      "legalquants-transactional",
      "legalquants-companion",
    ]);
    for (const { manifest } of bundles) {
      expect(validatePluginManifest(repoRoot, manifest)).toEqual([]);
    }
  });

  it("rejects unknown top-level fields", () => {
    const repoRoot = findRepoRoot();
    const errors = validatePluginManifest(repoRoot, {
      $schema: "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
      name: "codex-for-legal",
      hooks: "./hooks.json",
    });
    expect(errors.join("\n")).toMatch(/must NOT have additional properties/i);
  });
});

describe("OpenAI manifest", () => {
  it("validates the generated .codex-plugin/plugin.json shape", () => {
    const repoRoot = findRepoRoot();
    const bundle = loadPluginBundles(repoRoot)[0];
    if (bundle === undefined) throw new Error("missing plugin bundle");
    const openai = buildOpenAiManifest(bundle.manifest, {
      displayName: bundle.displayName,
    });

    expect(openai.skills).toBe("./skills/");
    expect(openai).not.toHaveProperty("$schema");
    expect(openai.interface.logo).toBe("./assets/lq-logo.png");
    expect(openai.interface.composerIcon).toBe("./assets/lq-logo.png");
    expect(openai.interface.displayName).toBe(
      "LegalQuants Skills for Litigators",
    );
    expect(validateOpenAiManifest(repoRoot, openai)).toEqual([]);
  });

  it("rejects a generated manifest without skills", () => {
    const repoRoot = findRepoRoot();
    const errors = validateOpenAiManifest(repoRoot, {
      name: "codex-for-legal",
      version: "0.1.0",
      description: "demo",
    });
    expect(errors.join("\n")).toMatch(/required property 'skills'/i);
  });

  it("rejects an OpenAI interface without required branding", () => {
    const repoRoot = findRepoRoot();
    const bundle = loadPluginBundles(repoRoot)[0];
    if (bundle === undefined) throw new Error("missing plugin bundle");
    const openai = buildOpenAiManifest(bundle.manifest, {
      displayName: bundle.displayName,
    });
    const errors = validateOpenAiManifest(repoRoot, {
      ...openai,
      interface: { displayName: "CODEX for Legal" },
    });

    expect(errors.join("\n")).toMatch(/required property 'logo'/i);
    expect(errors.join("\n")).toMatch(/required property 'composerIcon'/i);
  });
});

describe("Claude Code manifest", () => {
  it("validates the generated .claude-plugin/plugin.json shape", () => {
    const repoRoot = findRepoRoot();
    const bundle = loadPluginBundles(repoRoot)[0];
    if (bundle === undefined) throw new Error("missing plugin bundle");
    const claudeCode = buildClaudeCodeManifest(bundle.manifest);

    expect(claudeCode.skills).toBe("./skills/");
    expect(validateClaudeCodeManifest(repoRoot, claudeCode)).toEqual([]);
  });

  it("rejects a generated manifest without a name", () => {
    const repoRoot = findRepoRoot();
    const errors = validateClaudeCodeManifest(repoRoot, {
      skills: "./skills/",
    });

    expect(errors.join("\n")).toMatch(/required property 'name'/i);
  });
});

describe("source-of-truth checks", () => {
  it("keeps the three audience bundles well formed", () => {
    const repoRoot = findRepoRoot();
    expect(
      validateReleaseMetadata(repoRoot, loadPluginBundles(repoRoot)),
    ).toEqual([]);
  });

  it("advertises the currently shipped OpenAI and Claude Code providers", () => {
    const repoRoot = findRepoRoot();
    const release = readFileSync(join(repoRoot, "plugin.release.yaml"), "utf8");

    expect(release).toContain("  claude-code:");
    expect(release).toContain("  openai:");
    expect(release).not.toMatch(/^ {2}(?:claude|gemini):/m);
  });

  it("keeps contract schema copies byte-equal", () => {
    expect(validateContractSchemaCopies(findRepoRoot())).toEqual([]);
  });

  it("keeps the citation-level result contract strict and self-contained", () => {
    const repoRoot = findRepoRoot();
    const floor = readFileSync(
      join(repoRoot, "packages/contracts/schemas/work-unit-result.schema.json"),
      "utf8",
    );
    const strictText = readFileSync(
      join(
        repoRoot,
        "skills/litigation/cite-check/schemas/cite-check-unit-result.schema.json",
      ),
      "utf8",
    );
    const strict = JSON.parse(strictText) as {
      allOf?: Array<{ $ref?: string }>;
      additionalProperties?: boolean;
      properties?: Record<string, unknown>;
    };

    expect(strict.additionalProperties).toBe(false);
    expect(strict.allOf ?? []).not.toContainEqual({
      $ref: "work-unit-result.schema.json",
    });
    expect(Object.keys(strict.properties ?? {})).toEqual([
      "unitId",
      "disposition",
      "citations",
    ]);
    expect(strictText).not.toBe(floor);
  });
});
