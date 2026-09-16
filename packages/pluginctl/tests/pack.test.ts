import { execFileSync, spawnSync } from "node:child_process";
import {
  chmodSync,
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";
import { listPackableSkillDirs, packAll } from "../src/pack.js";
import { findRepoRoot } from "../src/repo.js";
import { preparePackagedMarkdown } from "../src/strip-repo-only.js";
import { makePackFixture } from "./helpers/pack-fixture.js";

function findPythonCommand(): string {
  for (const candidate of ["python3", "python"]) {
    const probe = spawnSync(candidate, ["--version"], { encoding: "utf8" });
    if (probe.status === 0) {
      return candidate;
    }
  }
  throw new Error("Python is required for the packaged cite-check smoke test");
}

describe("packAll", () => {
  it("copies sanitized authored SKILL.md into every package", () => {
    const fixture = makePackFixture();

    try {
      cpSync(
        join(findRepoRoot(), "skills/litigation/cite-check"),
        join(fixture.repoRoot, "skills/litigation/cite-check"),
        { recursive: true },
      );
      packAll({ repoRoot: fixture.repoRoot, check: false });

      const source = readFileSync(
        join(fixture.repoRoot, "skills/litigation/cite-check/SKILL.md"),
        "utf8",
      );
      const openaiSkill = readFileSync(
        join(
          fixture.repoRoot,
          "dist/openai/legalquants-litigation/skills/cite-check/SKILL.md",
        ),
        "utf8",
      );
      const portableSkill = readFileSync(
        join(
          fixture.repoRoot,
          "dist/agent-plugins/legalquants-litigation/skills/cite-check/SKILL.md",
        ),
        "utf8",
      );
      const claudeSkill = readFileSync(
        join(
          fixture.repoRoot,
          "dist/claude-code/legalquants-litigation/skills/cite-check/SKILL.md",
        ),
        "utf8",
      );

      const packagedSource = preparePackagedMarkdown(source);
      expect(openaiSkill).toBe(packagedSource);
      expect(portableSkill).toBe(packagedSource);
      expect(claudeSkill).toBe(packagedSource);
      expect(openaiSkill).not.toContain("<!--");
      expect(openaiSkill).not.toContain("openai-native-fallback.md");
      expect(portableSkill).not.toContain("AUTO-GENERATED");
      expect(claudeSkill).not.toContain("AUTO-GENERATED");
    } finally {
      fixture.cleanup();
    }
  });

  it("keeps authored skills current without writing dist", () => {
    const check = packAll({ repoRoot: findRepoRoot(), check: true });
    expect(check.stale).toEqual([]);
    expect(check.wrote).toEqual([]);
  }, 30_000);

  it("writes MVP dist trees from authored SKILL.md in a fixture", () => {
    const fixture = makePackFixture();

    try {
      const result = packAll({ repoRoot: fixture.repoRoot, check: false });
      expect(result.stale).toEqual([]);
      const license = readFileSync(join(fixture.repoRoot, "LICENSE"), "utf8");
      for (const output of result.wrote.filter((path) =>
        statSync(path).isDirectory(),
      )) {
        expect(readFileSync(join(output, "LICENSE"), "utf8")).toBe(license);
      }
      expect(
        readFileSync(
          join(fixture.repoRoot, "skills/core/demo/SKILL.md"),
          "utf8",
        ),
      ).toBe("# demo\n\nRun scripts/ok.py.\n");
      expect(
        readFileSync(
          join(
            fixture.repoRoot,
            "dist/openai/legalquants-litigation/skills/demo/SKILL.md",
          ),
          "utf8",
        ),
      ).toBe("# demo\n\nRun scripts/ok.py.\n");
      expect(
        existsSync(
          join(
            fixture.repoRoot,
            "dist/openai/legalquants-litigation/skills/demo/scripts/ok.py",
          ),
        ),
      ).toBe(true);
      expect(
        existsSync(
          join(
            fixture.repoRoot,
            "dist/openai/legalquants-litigation/.codex-plugin/plugin.json",
          ),
        ),
      ).toBe(true);
      expect(readdirSync(join(fixture.repoRoot, "dist/openai")).sort()).toEqual(
        [
          "legalquants-companion",
          "legalquants-litigation",
          "legalquants-transactional",
        ],
      );
      expect(existsSync(join(fixture.repoRoot, "dist/agent-plugins"))).toBe(
        true,
      );
      expect(existsSync(join(fixture.repoRoot, "dist/claude-code"))).toBe(true);
      expect(
        existsSync(
          join(
            fixture.repoRoot,
            "dist/claude-code/legalquants-litigation/.claude-plugin/plugin.json",
          ),
        ),
      ).toBe(true);
      expect(
        JSON.parse(
          readFileSync(
            join(
              fixture.repoRoot,
              "dist/claude-code/legalquants-litigation/.claude-plugin/plugin.json",
            ),
            "utf8",
          ),
        ),
      ).toMatchObject({
        name: "legalquants-litigation",
        skills: "./skills/",
        license: "Apache-2.0",
      });
      expect(existsSync(join(fixture.repoRoot, "dist/claude-cowork"))).toBe(
        false,
      );
      for (const target of [
        "openai",
        "agent-plugins",
        "claude-code",
      ] as const) {
        expect(existsSync(join(fixture.repoRoot, `dist/${target}/lq`))).toBe(
          false,
        );
      }
      expect(
        packAll({ repoRoot: fixture.repoRoot, check: true }).stale,
      ).toEqual([]);
    } finally {
      fixture.cleanup();
    }
  });

  it("runs the packaged offline report aggregator as an installed smoke", () => {
    const fixture = makePackFixture();

    try {
      cpSync(
        join(findRepoRoot(), "skills/litigation/cite-check"),
        join(fixture.repoRoot, "skills/litigation/cite-check"),
        {
          recursive: true,
          filter: (source) => !/[\\/]evals(?:[\\/]|$)/.test(source),
        },
      );
      packAll({ repoRoot: fixture.repoRoot, check: false });

      const portableSkill = join(
        fixture.repoRoot,
        "dist/agent-plugins/legalquants-litigation/skills/cite-check",
      );
      const openaiSkill = join(
        fixture.repoRoot,
        "dist/openai/legalquants-litigation/skills/cite-check",
      );
      const claudeSkill = join(
        fixture.repoRoot,
        "dist/claude-code/legalquants-litigation/skills/cite-check",
      );
      const openaiPackage = join(
        fixture.repoRoot,
        "dist/openai/legalquants-litigation",
      );
      const claudePackage = join(
        fixture.repoRoot,
        "dist/claude-code/legalquants-litigation",
      );
      const shipped = [
        "assets/report-template.html",
        "references/cite-check-rubric.md",
        "references/document-context.md",
        "schemas/coverage.schema.json",
        "schemas/manifest.schema.json",
        "scripts/common/validate_json.py",
        "scripts/aggregate_report.py",
        "scripts/cite_check.py",
        "scripts/common/__init__.py",
        "scripts/common/contracts.py",
        "scripts/common/core.py",
        "scripts/common/report_core.py",
        "scripts/common/report_render.py",
        "scripts/common/runtime.py",
        "scripts/common/severity.py",
      ];

      for (const packageSkill of [portableSkill, openaiSkill, claudeSkill]) {
        for (const rel of shipped) {
          expect(existsSync(join(packageSkill, rel))).toBe(true);
        }
      }
      const excludedFromPackages = [
        "evals",
        "evals/real-world/tools/build_manifest.py",
        "evals/real-world/fixtures/kettering-v-collier/ground-truth.json",
        "PRD.md",
        "skill.yaml",
        "sections",
        "CLAUDE.md",
        "AGENTS.md",
        "references/architecture.md",
        "schemas/cite-check-work-unit-result.schema.json",
        "schemas/report.schema.json",
        "schemas/sol-review.schema.json",
        "schemas/work-unit-result.schema.json",
      ];
      for (const packageSkill of [portableSkill, openaiSkill, claudeSkill]) {
        for (const rel of excludedFromPackages) {
          expect(
            existsSync(join(packageSkill, rel)),
            `${packageSkill} unexpectedly contains ${rel}`,
          ).toBe(false);
        }
      }
      expect(
        existsSync(
          join(
            fixture.repoRoot,
            "dist/agent-plugins/legalquants-litigation/AGENTS.md",
          ),
        ),
      ).toBe(true);
      expect(existsSync(join(openaiPackage, "AGENTS.md"))).toBe(false);
      expect(existsSync(join(claudePackage, "AGENTS.md"))).toBe(false);
      expect(
        existsSync(join(openaiPackage, "agents/claude-cowork/unit-worker.md")),
      ).toBe(false);
      expect(
        existsSync(join(openaiPackage, "workflows/claude-code/fanout.js")),
      ).toBe(false);
      expect(existsSync(join(openaiPackage, "mcp.json"))).toBe(false);
      expect(existsSync(join(openaiPackage, "credentials.json"))).toBe(false);
      expect(existsSync(join(claudePackage, "hooks"))).toBe(false);
      expect(existsSync(join(claudePackage, "credentials.json"))).toBe(false);
      expect(readFileSync(join(portableSkill, "SKILL.md"), "utf8")).not.toMatch(
        /openai-codex|gpt-5\.6|Codex cite-check premortem/i,
      );

      for (const packageSkill of [portableSkill, openaiSkill]) {
        const schemas = readdirSync(join(packageSkill, "schemas"))
          .filter((name) => name.endsWith(".schema.json"))
          .map((name) => join(packageSkill, "schemas", name));
        for (const schemaPath of schemas) {
          const schema = readFileSync(schemaPath, "utf8");
          for (const match of schema.matchAll(
            /"\$ref"\s*:\s*"([^"#][^"]*)"/g,
          )) {
            const ref = match[1]?.split("#", 1)[0];
            if (ref === undefined || /^https?:\/\//.test(ref)) {
              continue;
            }
            expect(existsSync(join(dirname(schemaPath), ref))).toBe(true);
          }
        }
      }

      const runDir = mkdtempSync(join(fixture.repoRoot, "cite-check-run-"));
      mkdirSync(join(runDir, "input"), { recursive: true });
      mkdirSync(join(runDir, "authorities"), { recursive: true });
      writeFileSync(join(runDir, "input/brief.md"), "The rule applies.\n");
      writeFileSync(
        join(runDir, "authorities/A0001.md"),
        "Authority A0001 supports the rule.\n",
      );
      writeFileSync(
        join(runDir, "manifest.json"),
        JSON.stringify({
          schemaVersion: "cite-check.manifest.v2",
          runId: "pack-smoke-run",
          target: {
            path: "input/brief.md",
            fullDocumentRef: "input/brief.md",
            displayName: "Pack smoke brief",
          },
          authorities: [
            {
              sourceId: "A0001",
              path: "authorities/A0001.md",
              filename: "A0001.md",
              readability: "readable",
              contentIdentity: { caseName: "Authority A0001" },
            },
          ],
          units: [
            {
              unitId: "P0001",
              kind: "paragraph",
              path: "input/brief.md",
              lineStart: 1,
              lineEnd: 1,
              footnoteAnchorUnitId: null,
            },
          ],
          limitations: [],
        }),
      );
      writeFileSync(
        join(runDir, "result.json"),
        JSON.stringify({
          unitId: "P0001",
          disposition: "citations_found",
          citations: [
            {
              citation_as_written_in_unit: "Example v. Smith, 1 F.4th 2",
              matched_citation: "Example v. Smith, 1 F.4th 2",
              proposition: "The rule applies.",
              matched_source_id: "A0001",
              source_excerpt: "Authority A0001 supports the rule.",
              source_locator: "p. 1",
              accuracy_of_source_characterization:
                "confirmed_fair_characterization_of_source",
              pincite_accuracy: "NA_no_pincite_for_this_citation",
              accuracy_of_direct_quotation:
                "NA_no_direct_quotation_for_this_citation",
              recommended_changes: null,
            },
          ],
        }),
      );

      const outputDir = join(runDir, "report");
      const aggregator = join(
        fixture.repoRoot,
        "dist/openai/legalquants-litigation/skills/cite-check/scripts/aggregate_report.py",
      );
      const stdout = execFileSync(
        findPythonCommand(),
        [
          aggregator,
          "--manifest",
          join(runDir, "manifest.json"),
          "--results",
          join(runDir, "result.json"),
          "--output-dir",
          outputDir,
        ],
        { cwd: fixture.repoRoot, encoding: "utf8" },
      );

      expect(stdout).toContain("json: cite-check-results.json");
      const report = JSON.parse(
        readFileSync(join(outputDir, "cite-check-results.json"), "utf8"),
      ) as {
        status?: string;
        unitResults?: Array<unknown>;
        coverage?: { isComplete?: boolean };
      };
      expect(report.status).toBe("complete");
      expect(report.coverage?.isComplete).toBe(true);
      expect(report.unitResults).toHaveLength(1);
    } finally {
      fixture.cleanup();
    }
  }, 30_000);

  it("does not write dist during --check", () => {
    const fixture = makePackFixture();

    try {
      const check = packAll({ repoRoot: fixture.repoRoot, check: true });
      expect(check.stale).toEqual([]);
      expect(existsSync(join(fixture.repoRoot, "dist"))).toBe(false);
    } finally {
      fixture.cleanup();
    }
  });

  it("preserves unknown files outside the generated bundle directories", () => {
    const fixture = makePackFixture();

    try {
      const staleClaude = join(
        fixture.repoRoot,
        "dist/claude-code/leftover.txt",
      );
      mkdirSync(join(fixture.repoRoot, "dist/claude-code"), {
        recursive: true,
      });
      writeFileSync(staleClaude, "stale");

      packAll({ repoRoot: fixture.repoRoot, check: false });
      expect(existsSync(join(fixture.repoRoot, "dist/claude-code"))).toBe(true);
      expect(
        existsSync(join(fixture.repoRoot, "dist/claude-code/leftover.txt")),
      ).toBe(true);
      expect(existsSync(join(fixture.repoRoot, "dist/claude-cowork"))).toBe(
        false,
      );
    } finally {
      fixture.cleanup();
    }
  });

  it.each([
    ["evals", "the private maintainer eval repository"],
    ["test", "packages/skill-tests/tests"],
    ["tests", "packages/skill-tests/tests"],
    ["__tests__", "packages/skill-tests/tests"],
    ["README.md", "packages/skill-docs/skills/sidecar.md"],
    ["PRD.md", "packages/skill-docs/skills/sidecar.md"],
    ["product-management", "packages/skill-docs/skills/sidecar.md"],
    ["AGENTS.md", "a repository-level contributor directory"],
    ["CLAUDE.md", "a repository-level contributor directory"],
    ["sections", "a repository-level contributor directory"],
    ["skill.yaml", "a repository-level contributor directory"],
  ])("rejects repository-only skill entry %s", (entry, destination) => {
    const fixture = makePackFixture({ livePassthrough: true });

    try {
      const skillDir = join(fixture.repoRoot, "skills/core/sidecar");
      const entryPath = join(skillDir, entry);
      if (entry.includes(".")) {
        writeFileSync(entryPath, "contributor-only\n");
      } else {
        mkdirSync(entryPath, { recursive: true });
      }

      expect(() =>
        packAll({ repoRoot: fixture.repoRoot, check: true }),
      ).toThrow(
        `skills/core/sidecar/${entry} is repository-only; move it to ${destination}`,
      );
    } finally {
      fixture.cleanup();
    }
  });

  it("ships lifecycle hooks only in the OpenAI package overlay", () => {
    const fixture = makePackFixture({ openAiHooks: true });

    try {
      packAll({ repoRoot: fixture.repoRoot, check: false });
      expect(
        readFileSync(
          join(
            fixture.repoRoot,
            "dist/openai/legalquants-litigation/hooks/openai.json",
          ),
          "utf8",
        ),
      ).toBe('{"hooks": {}}\n');
      expect(
        JSON.parse(
          readFileSync(
            join(
              fixture.repoRoot,
              "dist/openai/legalquants-litigation/hooks/banner.json",
            ),
            "utf8",
          ),
        ),
      ).toEqual({
        plugin: "LegalQuants Skills for Litigators",
        first_move: "Try $demo.",
      });
      expect(
        existsSync(
          join(
            fixture.repoRoot,
            "dist/openai/legalquants-litigation/hooks/adapter.py",
          ),
        ),
      ).toBe(true);
      const combined = join(fixture.repoRoot, "plugins/legalquants-litigation");
      expect(existsSync(join(combined, ".claude-plugin/plugin.json"))).toBe(
        true,
      );
      expect(existsSync(join(combined, ".codex-plugin/plugin.json"))).toBe(
        true,
      );
      expect(existsSync(join(combined, "hooks/openai.json"))).toBe(true);
      expect(existsSync(join(combined, "hooks/hooks.json"))).toBe(false);
      expect(existsSync(join(combined, "hooks/README.md"))).toBe(false);
      expect(
        JSON.parse(
          readFileSync(join(combined, ".claude-plugin/plugin.json"), "utf8"),
        ),
      ).not.toHaveProperty("hooks");
      expect(
        JSON.parse(
          readFileSync(join(combined, ".codex-plugin/plugin.json"), "utf8"),
        ),
      ).toMatchObject({ hooks: "./hooks/openai.json" });
    } finally {
      fixture.cleanup();
    }
  });

  it("preserves executable modes for hook scripts in generated packages", () => {
    const fixture = makePackFixture({ openAiHooks: true });

    try {
      const source = join(
        fixture.repoRoot,
        "packages/pluginctl/hooks/adapter.py",
      );
      chmodSync(source, 0o755);
      packAll({ repoRoot: fixture.repoRoot, check: false });

      for (const packageRoot of [
        join(fixture.repoRoot, "dist/openai/legalquants-litigation"),
        join(fixture.repoRoot, "plugins/legalquants-litigation"),
      ]) {
        expect(
          statSync(join(packageRoot, "hooks/adapter.py")).mode & 0o111,
        ).toBe(0o111);
      }
    } finally {
      fixture.cleanup();
    }
  });

  it("does not pack Python bytecode caches from skill scripts", () => {
    const fixture = makePackFixture();

    try {
      const cache = join(
        fixture.repoRoot,
        "skills/core/demo/scripts/__pycache__",
      );
      mkdirSync(cache, { recursive: true });
      writeFileSync(join(cache, "ok.cpython-312.pyc"), "bytecode");
      packAll({ repoRoot: fixture.repoRoot, check: false });
      expect(
        existsSync(
          join(
            fixture.repoRoot,
            "dist/agent-plugins/legalquants-litigation/skills/demo/scripts/__pycache__",
          ),
        ),
      ).toBe(false);
      expect(
        existsSync(
          join(
            fixture.repoRoot,
            "dist/openai/legalquants-litigation/skills/demo/scripts/__pycache__",
          ),
        ),
      ).toBe(false);
    } finally {
      fixture.cleanup();
    }
  });

  it("rejects an AUTO-GENERATED SKILL.md", () => {
    const fixture = makePackFixture({ orphanGenerated: true });

    try {
      expect(() =>
        packAll({ repoRoot: fixture.repoRoot, check: true }),
      ).toThrow(/AUTO-GENERATED/);
    } finally {
      fixture.cleanup();
    }
  });

  it("rejects a discovered skill directory without SKILL.md in pack and check modes", () => {
    const fixture = makePackFixture();

    try {
      mkdirSync(join(fixture.repoRoot, "skills/core/missing"), {
        recursive: true,
      });
      for (const check of [false, true]) {
        expect(() => packAll({ repoRoot: fixture.repoRoot, check })).toThrow(
          "skills/core/missing/SKILL.md is required for every authored skill directory",
        );
      }
    } finally {
      fixture.cleanup();
    }
  });
});

describe("listPackableSkillDirs", () => {
  it("returns an empty list when skills/ is missing", () => {
    const fixture = makePackFixture();

    try {
      expect(listPackableSkillDirs(join(fixture.repoRoot, "missing"))).toEqual(
        [],
      );
    } finally {
      fixture.cleanup();
    }
  });
});
