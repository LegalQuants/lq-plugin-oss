import { describe, expect, it } from "vitest";
import { findRepoRoot } from "../src/repo.js";
import {
  buildClaudeCodeManifest,
  CLAUDE_CODE_PLUGIN_SCHEMA_URL,
  validateClaudeCodeManifest,
} from "../src/validate-claude-manifest.js";
import { loadPluginBundles } from "../src/validate-manifest.js";

describe("Claude Code manifest", () => {
  it("derives a directly installable manifest from the canonical manifest", () => {
    const repoRoot = findRepoRoot();
    const bundle = loadPluginBundles(repoRoot)[0];
    if (bundle === undefined) throw new Error("missing plugin bundle");
    const manifest = buildClaudeCodeManifest(bundle.manifest);

    expect(manifest).toMatchObject({
      $schema: CLAUDE_CODE_PLUGIN_SCHEMA_URL,
      name: "legalquants-litigation",
      skills: "./skills/",
    });
    expect(manifest).not.toHaveProperty(
      "$schema",
      "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
    );
    expect(validateClaudeCodeManifest(repoRoot, manifest)).toEqual([]);
  });

  it("rejects manifests without a name or with non-relative skill paths", () => {
    const repoRoot = findRepoRoot();
    const errors = validateClaudeCodeManifest(repoRoot, {
      skills: "/skills/",
    });

    expect(errors.join("\n")).toMatch(
      /\.claude-plugin\/plugin\.json .*required property 'name'/i,
    );
    expect(errors.join("\n")).toMatch(
      /\.claude-plugin\/plugin\.json .*must match exactly one schema/i,
    );
  });

  it("rejects fields from the canonical manifest that Claude does not accept", () => {
    const repoRoot = findRepoRoot();
    const errors = validateClaudeCodeManifest(repoRoot, {
      name: "codex-for-legal",
      skills: "./skills/",
      extensions: {},
    });

    expect(errors.join("\n")).toMatch(/additional properties/i);
  });
});
