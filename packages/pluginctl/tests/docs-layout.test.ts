import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { findRepoRoot } from "../src/repo.js";

describe("repository documentation layout", () => {
  it("keeps public documentation in package-owned locations", () => {
    const repoRoot = findRepoRoot();

    for (const legacyPath of [
      "PRD.md",
      "skills/TEMPLATE.md",
      "docs/environment/PRD.md",
    ]) {
      expect(existsSync(join(repoRoot, legacyPath)), legacyPath).toBe(false);
    }

    for (const legacyDir of ["governance", "lq", "references"]) {
      const path = join(repoRoot, legacyDir);
      if (existsSync(path)) {
        expect(readdirSync(path), legacyDir).toEqual([]);
      }
    }

    const packageDocs = join(repoRoot, "packages/skill-docs");
    expect(existsSync(join(packageDocs, "README.md"))).toBe(true);

    const skillDocs = join(packageDocs, "skills");
    const entries = readdirSync(skillDocs, { withFileTypes: true });
    expect(entries.length).toBeGreaterThan(0);
    expect(
      entries.every((entry) => entry.isFile() && entry.name.endsWith(".md")),
    ).toBe(true);
    for (const entry of entries) {
      expect(readFileSync(join(skillDocs, entry.name), "utf8").trim()).not.toBe(
        "",
      );
    }

    expect(
      existsSync(join(repoRoot, ".agents/skills/cross-platform/SKILL.md")),
    ).toBe(true);
    expect(existsSync(join(repoRoot, "dev-tools"))).toBe(false);
  });
});
