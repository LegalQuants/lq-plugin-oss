import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { lintVendorNeutralText } from "../src/lint.js";
import { listPackableSkillDirs, packAll } from "../src/pack.js";
import { findRepoRoot } from "../src/repo.js";
import { preparePackagedMarkdown } from "../src/strip-repo-only.js";

const citeCheck = () => join(findRepoRoot(), "skills/litigation/cite-check");
const docreview = () => join(findRepoRoot(), "skills/litigation/docreview");
const REPO_ONLY_SKILL_ENTRIES = [
  "evals",
  "test",
  "tests",
  "__tests__",
  "PRD.md",
  "product-management",
  "AGENTS.md",
  "CLAUDE.md",
  "skill.yaml",
  "sections",
] as const;

describe("static skill package source", () => {
  it("keeps repository-only material outside every packable skill root", () => {
    const repoRoot = findRepoRoot();

    for (const { name, dir } of listPackableSkillDirs(repoRoot)) {
      const entries = new Set(
        readdirSync(dir, { withFileTypes: true }).map((entry) => entry.name),
      );
      for (const entry of REPO_ONLY_SKILL_ENTRIES) {
        expect(
          entries.has(entry),
          `skills/${name}/${entry} must remain outside the shipped skill tree`,
        ).toBe(false);
      }
    }
  });

  it("has one authored capability-based SKILL.md", () => {
    const markdown = readFileSync(join(citeCheck(), "SKILL.md"), "utf8");
    const flatMarkdown = markdown.replace(/\s+/g, " ");
    expect(markdown).toContain("scripts/cite_check.py");
    expect(markdown).toContain("scripts/probe_environment.py");
    expect(markdown).toContain("one fresh Codex session");
    expect(markdown).toContain("one targeted retry");
    expect(markdown).toContain("the environment could not search");
    expect(markdown).not.toContain(
      "externally authenticated provider attestation",
    );
    expect(flatMarkdown).toContain("process those assignments one at a time");
    expect(markdown).toContain("CourtListener");
    expect(markdown).not.toContain("AUTO-GENERATED");
    expect(markdown).not.toContain("ChatGPT");
    expect(markdown).not.toContain("OpenAI / ChatGPT orchestration");
    expect(
      lintVendorNeutralText(join(citeCheck(), "SKILL.md"), markdown),
    ).toEqual([]);
    expect(existsSync(join(citeCheck(), "skill.yaml"))).toBe(false);
    expect(existsSync(join(citeCheck(), "sections"))).toBe(false);
    expect(existsSync(join(citeCheck(), "scripts/probe_environment.py"))).toBe(
      true,
    );
  });

  it("packs the same sanitized SKILL.md into every provider tree", () => {
    const repoRoot = findRepoRoot();
    const result = packAll({ repoRoot, check: true });
    expect(result.stale).toEqual([]);

    packAll({ repoRoot, check: false });
    const source = preparePackagedMarkdown(
      readFileSync(join(citeCheck(), "SKILL.md"), "utf8"),
    );
    expect(
      readFileSync(
        join(
          repoRoot,
          "dist/agent-plugins/legalquants-litigation/skills/cite-check/SKILL.md",
        ),
        "utf8",
      ),
    ).toBe(source);
    expect(
      readFileSync(
        join(
          repoRoot,
          "dist/openai/legalquants-litigation/skills/cite-check/SKILL.md",
        ),
        "utf8",
      ),
    ).toBe(source);
    expect(
      readFileSync(
        join(
          repoRoot,
          "dist/claude-code/legalquants-litigation/skills/cite-check/SKILL.md",
        ),
        "utf8",
      ),
    ).toBe(source);
    expect(
      existsSync(
        join(
          repoRoot,
          "dist/openai/legalquants-transactional/skills/definition-check/agents/openai.yaml",
        ),
      ),
    ).toBe(true);
    expect(
      existsSync(
        join(
          repoRoot,
          "dist/agent-plugins/legalquants-transactional/skills/definition-check/agents/openai.yaml",
        ),
      ),
    ).toBe(true);
    expect(
      existsSync(
        join(
          repoRoot,
          "dist/claude-code/legalquants-transactional/skills/definition-check/agents/openai.yaml",
        ),
      ),
    ).toBe(true);
    expect(
      existsSync(
        join(
          repoRoot,
          "dist/openai/legalquants-litigation/skills/wiki/agents/openai.yaml",
        ),
      ),
    ).toBe(true);
    expect(
      existsSync(
        join(
          repoRoot,
          "dist/agent-plugins/legalquants-litigation/skills/wiki/agents/openai.yaml",
        ),
      ),
    ).toBe(true);
    expect(
      existsSync(
        join(
          repoRoot,
          "dist/claude-code/legalquants-litigation/skills/wiki/agents/openai.yaml",
        ),
      ),
    ).toBe(true);
  }, 90_000);

  it("keeps DocReview in every provider tree and the committed Claude mirror", () => {
    const repoRoot = findRepoRoot();
    const result = packAll({ repoRoot, check: true });
    expect(result.stale).toEqual([]);

    packAll({ repoRoot, check: false });
    const sourceRoot = docreview();
    const sourceFiles = filesUnder(sourceRoot).sort();
    for (const packageRoot of [
      "dist/agent-plugins/legalquants-litigation",
      "dist/openai/legalquants-litigation",
      "dist/claude-code/legalquants-litigation",
      "plugins/legalquants-litigation",
    ]) {
      const packedRoot = join(repoRoot, packageRoot, "skills/docreview");
      expect(filesUnder(packedRoot).sort()).toEqual(sourceFiles);
      for (const relative of sourceFiles) {
        const source = join(sourceRoot, relative);
        const expected = relative.endsWith(".md")
          ? Buffer.from(preparePackagedMarkdown(readFileSync(source, "utf8")))
          : readFileSync(source);
        expect(
          readFileSync(join(packedRoot, relative)),
          `${packageRoot}/skills/docreview/${relative}`,
        ).toEqual(expected);
      }
    }
  }, 90_000);

  it("packs the passive environment probe with all static skill trees", () => {
    const repoRoot = findRepoRoot();
    packAll({ repoRoot, check: false });
    const source = readFileSync(
      join(citeCheck(), "scripts/probe_environment.py"),
      "utf8",
    );
    expect(
      readFileSync(
        join(
          repoRoot,
          "dist/agent-plugins/legalquants-litigation/skills/cite-check/scripts/probe_environment.py",
        ),
        "utf8",
      ),
    ).toBe(source);
    expect(
      readFileSync(
        join(
          repoRoot,
          "dist/openai/legalquants-litigation/skills/cite-check/scripts/probe_environment.py",
        ),
        "utf8",
      ),
    ).toBe(source);
    expect(
      readFileSync(
        join(
          repoRoot,
          "dist/claude-code/legalquants-litigation/skills/cite-check/scripts/probe_environment.py",
        ),
        "utf8",
      ),
    ).toBe(source);
  }, 30_000);

  it("keeps SKILL.md links as files in all packed trees", () => {
    const repoRoot = findRepoRoot();
    packAll({ repoRoot, check: false });
    const markdown = readFileSync(join(citeCheck(), "SKILL.md"), "utf8");
    const links = [...markdown.matchAll(/\]\(([^)#?]+)(?:#[^)]+)?\)/g)]
      .map((match) => match[1])
      .filter((link): link is string => link !== undefined);

    expect(links.length).toBeGreaterThan(0);
    for (const rel of links) {
      expect(existsSync(join(citeCheck(), rel))).toBe(true);
      expect(
        existsSync(
          join(
            repoRoot,
            "dist/openai/legalquants-litigation/skills/cite-check",
            rel,
          ),
        ),
      ).toBe(true);
      expect(
        existsSync(
          join(
            repoRoot,
            "dist/agent-plugins/legalquants-litigation/skills/cite-check",
            rel,
          ),
        ),
      ).toBe(true);
      expect(
        existsSync(
          join(
            repoRoot,
            "dist/claude-code/legalquants-litigation/skills/cite-check",
            rel,
          ),
        ),
      ).toBe(true);
    }
  }, 30_000);
});

function filesUnder(root: string, prefix = ""): Array<string> {
  const files: Array<string> = [];

  for (const entry of readdirSync(join(root, prefix), {
    withFileTypes: true,
  })) {
    if (
      entry.name === "__pycache__" ||
      entry.name.endsWith(".pyc") ||
      entry.name.endsWith(".pyo")
    ) {
      continue;
    }
    const relative = join(prefix, entry.name);
    if (entry.isDirectory()) {
      files.push(...filesUnder(root, relative));
    } else {
      files.push(relative);
    }
  }

  return files;
}
