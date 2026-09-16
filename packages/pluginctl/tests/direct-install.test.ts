import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { parse } from "yaml";
import { listPackableSkillDirs, listSkillDirs } from "../src/pack.js";
import { findRepoRoot } from "../src/repo.js";

const EXPECTED_PRODUCT_SKILLS = [
  "cite-check",
  "lq-apply",
  "lq-ask",
  "lq-mirror",
  "lq-connect",
  "lq-reflect",
  "client-update",
  "closing-bible",
  "closing-checklist",
  "conform",
  "correspondence",
  "definition-check",
  "depositions",
  "diligence",
  "docreview",
  "document-discovery",
  "legaldesign",
  "legalquants",
  "my-lq-moment",
  "lq-start",
  "new-matter",
  "organize-case-docs",
  "playbook-builder",
  "playbook-review",
  "pressuretest",
  "read-redline",
  "regulatory",
  "sigpack",
  "timenarratives",
  "wiki",
  "writing",
] as const;

const NON_INSTALLABLE_DIRECTORIES = new Set([
  "dev-tools",
  "eval",
  "evals",
  "product-management",
  "test",
  "tests",
  "__tests__",
]);

type Frontmatter = Record<string, unknown>;

function readFrontmatter(path: string): Frontmatter {
  const source = readFileSync(path, "utf8");
  const match = source.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);

  if (match?.[1] === undefined) {
    throw new Error(`${path} is missing YAML frontmatter`);
  }

  const parsed: unknown = parse(match[1]);
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error(`${path} frontmatter must be a YAML mapping`);
  }

  return parsed as Frontmatter;
}

function nestedDirectoryNames(root: string): Array<string> {
  const names: Array<string> = [];

  for (const entry of readdirSync(root, { withFileTypes: true })) {
    if (!entry.isDirectory()) {
      continue;
    }

    names.push(entry.name);
    names.push(...nestedDirectoryNames(join(root, entry.name)));
  }

  return names;
}

describe("direct-install skill inventory", () => {
  it("includes the Apache license in every individually installable skill", () => {
    const repoRoot = findRepoRoot();
    const license = readFileSync(join(repoRoot, "LICENSE"), "utf8");
    for (const { dir } of listPackableSkillDirs(repoRoot)) {
      expect(readFileSync(join(dir, "LICENSE"), "utf8")).toBe(license);
    }
  });

  it("requires SKILL.md in every skills directory", () => {
    const repoRoot = findRepoRoot();
    const missing = listSkillDirs(repoRoot)
      .filter(({ dir }) => !existsSync(join(dir, "SKILL.md")))
      .map(({ name }) => name)
      .sort();

    expect(missing).toEqual([]);
  });

  it("exposes only the intended product skills under skills/", () => {
    const repoRoot = findRepoRoot();
    const discovered = listPackableSkillDirs(repoRoot)
      .map(({ name }) => name)
      .sort();

    expect(discovered).toEqual([...EXPECTED_PRODUCT_SKILLS].sort());
    expect(discovered).not.toContain("cross-platform");
  });

  it("gives every directly installable skill standard name and description fields", () => {
    const repoRoot = findRepoRoot();

    for (const { name, dir } of listPackableSkillDirs(repoRoot)) {
      const frontmatter = readFrontmatter(join(dir, "SKILL.md"));

      expect(frontmatter.name, `skills/${name}/SKILL.md name`).toBe(name);
      expect(
        frontmatter.description,
        `skills/${name}/SKILL.md description`,
      ).toEqual(expect.any(String));
      expect(
        (frontmatter.description as string).trim(),
        `skills/${name}/SKILL.md description`,
      ).not.toBe("");
    }
  });

  it("declares Definition Check's Python runtime requirement in shipped skill metadata", () => {
    const repoRoot = findRepoRoot();
    const frontmatter = readFrontmatter(
      join(repoRoot, "skills/transactional/definition-check/SKILL.md"),
    );

    expect(frontmatter.compatibility).toBe(
      "Requires local command execution and Python 3.12 or newer. Uses only the Python standard library and requires no network access.",
    );
    expect(frontmatter.metadata).toEqual(
      expect.objectContaining({
        "legalquants.python-requires": ">=3.12",
        "legalquants.python-dependencies": "stdlib-only",
      }),
    );
  });

  it("keeps evaluation and development material out of every installable skill", () => {
    const repoRoot = findRepoRoot();

    for (const { name, dir } of listPackableSkillDirs(repoRoot)) {
      const forbidden = nestedDirectoryNames(dir).filter((entry) =>
        NON_INSTALLABLE_DIRECTORIES.has(entry),
      );

      expect(
        forbidden,
        `skills/${name} contains non-installable directories`,
      ).toEqual([]);
    }
  });

  it("marks the contributor cross-platform skill as internal", () => {
    const repoRoot = findRepoRoot();
    const frontmatter = readFrontmatter(
      join(repoRoot, ".agents/skills/cross-platform/SKILL.md"),
    );
    const metadata = frontmatter.metadata;

    expect(metadata).toEqual(expect.objectContaining({ internal: true }));
  });
});
