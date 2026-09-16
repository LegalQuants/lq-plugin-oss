import {
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { packAll } from "../src/pack.js";
import { findRepoRoot } from "../src/repo.js";
import { preparePackagedMarkdown } from "../src/strip-repo-only.js";
import {
  loadPluginBundles,
  validateOpenAiManifest,
} from "../src/validate-manifest.js";
import { makePackFixture } from "./helpers/pack-fixture.js";

describe("OpenAI release package", () => {
  it("contains canonical skills and only package-local runtime files", () => {
    const fixture = makePackFixture({ openAiHooks: true });
    const repoRoot = findRepoRoot();
    const sourceSkill = join(repoRoot, "skills/litigation/cite-check");
    const fixtureSkill = join(fixture.repoRoot, "skills/litigation/cite-check");

    try {
      cpSync(sourceSkill, fixtureSkill, {
        recursive: true,
        filter: (source) => !/[\\/]evals(?:[\\/]|$)/.test(source),
      });
      mkdirSync(join(fixture.repoRoot, "dev-tools/cite-check/evals"), {
        recursive: true,
      });
      writeFileSync(
        join(fixture.repoRoot, "dev-tools/cite-check/evals/secret.txt"),
        "maintainer-only\n",
      );

      packAll({ repoRoot: fixture.repoRoot, check: false });

      const packageRoot = join(
        fixture.repoRoot,
        "dist/openai/legalquants-litigation",
      );
      const manifestPath = join(packageRoot, ".codex-plugin/plugin.json");
      const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as {
        [key: string]: unknown;
      };
      const bundle = loadPluginBundles(fixture.repoRoot)[0];
      if (bundle === undefined) throw new Error("missing plugin bundle");
      const canonical = bundle.manifest;

      expect(manifest).toMatchObject({
        name: canonical.name,
        version: canonical.version,
        description: canonical.description,
        author: canonical.author,
        homepage: canonical.homepage,
        repository: canonical.repository,
        keywords: canonical.keywords,
        skills: "./skills/",
        hooks: "./hooks/openai.json",
        interface: {
          displayName: "LegalQuants Skills for Litigators",
          shortDescription: "Source-grounded workflows for litigators",
          longDescription: canonical.description,
          developerName: "LegalQuants",
          category: "Productivity",
          logo: "./assets/lq-logo.png",
          composerIcon: "./assets/lq-logo.png",
          websiteURL: canonical.homepage,
        },
      });
      expect(manifest).not.toHaveProperty("interface.privacyPolicyURL");
      expect(manifest).not.toHaveProperty("interface.termsOfServiceURL");
      expect(validateOpenAiManifest(fixture.repoRoot, manifest)).toEqual([]);

      // The LegalQuants logo-kit mark ships as a real PNG (the upload
      // surfaces don't render SVG); the SVG source ships alongside.
      const logoPng = readFileSync(join(packageRoot, "assets/lq-logo.png"));
      expect([...logoPng.subarray(0, 8)]).toEqual([
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
      ]);
      expect(logoPng.length).toBeGreaterThan(1000);
      const logoSvg = readFileSync(
        join(packageRoot, "assets/lq-logo.svg"),
        "utf8",
      );
      expect(logoSvg).toContain("<title>LegalQuants</title>");
      expect(logoSvg).not.toContain("<text");

      for (const relative of filesUnder(fixtureSkill)) {
        const source = join(fixtureSkill, relative);
        const packed = join(packageRoot, "skills/cite-check", relative);
        expect(existsSync(packed), `missing packaged file ${relative}`).toBe(
          true,
        );
        const expected = relative.endsWith(".md")
          ? Buffer.from(preparePackagedMarkdown(readFileSync(source, "utf8")))
          : readFileSync(source);
        expect(readFileSync(packed)).toEqual(expected);
      }

      expect(readFileSync(join(packageRoot, "hooks/openai.json"))).toEqual(
        readFileSync(
          join(fixture.repoRoot, "packages/pluginctl/hooks/openai.json"),
        ),
      );
      expect(readFileSync(join(packageRoot, "hooks/adapter.py"))).toEqual(
        readFileSync(
          join(fixture.repoRoot, "packages/pluginctl/hooks/adapter.py"),
        ),
      );
      expect(existsSync(join(packageRoot, "dev-tools"))).toBe(false);
      expect(existsSync(join(packageRoot, "packages"))).toBe(false);
      expect(existsSync(join(packageRoot, "tests"))).toBe(false);
      expect(existsSync(join(packageRoot, ".git"))).toBe(false);
      expect(existsSync(join(packageRoot, "AGENTS.md"))).toBe(false);

      const repositoryOnlyFiles = filesUnder(packageRoot).filter((relative) =>
        /(^|\/)(AGENTS\.md|CLAUDE\.md|PRD\.md)$|^(docs|dev-tools|packages|tests?)(\/|$)|^\.git(\/|$)/.test(
          relative,
        ),
      );
      expect(repositoryOnlyFiles).toEqual([]);
    } finally {
      fixture.cleanup();
    }
  });

  it("does not advertise an absent hook component", () => {
    const fixture = makePackFixture();

    try {
      packAll({ repoRoot: fixture.repoRoot, check: false });
      const packageRoot = join(
        fixture.repoRoot,
        "dist/openai/legalquants-litigation",
      );
      const manifest = JSON.parse(
        readFileSync(join(packageRoot, ".codex-plugin/plugin.json"), "utf8"),
      ) as Record<string, unknown>;

      expect(manifest).not.toHaveProperty("hooks");
      expect(existsSync(join(packageRoot, "hooks"))).toBe(false);
    } finally {
      fixture.cleanup();
    }
  });
});

function filesUnder(root: string, prefix = ""): Array<string> {
  const files: Array<string> = [];

  for (const entry of readdirSync(join(root, prefix), {
    withFileTypes: true,
  })) {
    if (entry.name === "__pycache__" || entry.name.endsWith(".pyc")) {
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
