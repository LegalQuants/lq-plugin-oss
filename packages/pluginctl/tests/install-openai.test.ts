import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  type CommandResult,
  formatTimestamp,
  installOpenAi,
} from "../src/install-openai.js";
import { makePackFixture } from "./helpers/pack-fixture.js";

const PLUGIN_NAMES = [
  "legalquants-litigation",
  "legalquants-transactional",
  "legalquants-companion",
] as const;

function runnerFor(
  marketplaceList: unknown,
  options?: { failingArgs?: string },
) {
  const calls: Array<{ args: Array<string>; cwd: string }> = [];
  const runner = (
    _command: string,
    args: Array<string>,
    cwd: string,
  ): CommandResult => {
    calls.push({ args, cwd });
    if (options?.failingArgs === args.join(" ")) {
      return { stdout: "", stderr: "boom", status: 1 };
    }
    if (args.join(" ") === "plugin marketplace list --json") {
      return { stdout: JSON.stringify(marketplaceList), stderr: "", status: 0 };
    }
    return { stdout: "{}", stderr: "", status: 0 };
  };
  return { calls, runner };
}

describe("installOpenAi", () => {
  it("formats the UTC cachebuster timestamp", () => {
    expect(formatTimestamp(new Date("2026-08-18T19:04:05.000Z"))).toBe(
      "20260818-190405",
    );
  });

  it("stages OpenAI output and replaces an existing version suffix", () => {
    const fixture = makePackFixture();
    try {
      const releasePath = join(fixture.repoRoot, "plugin.release.yaml");
      writeFileSync(
        releasePath,
        readFileSync(releasePath, "utf8").replace(
          "version: 0.1.0",
          "version: 0.1.0+old-token",
        ),
      );
      const { calls, runner } = runnerFor([]);
      const result = installOpenAi({
        repoRoot: fixture.repoRoot,
        commandRunner: runner,
        now: new Date("2026-08-18T19:04:05.000Z"),
      });

      const staged = JSON.parse(
        readFileSync(
          join(
            result.pluginPaths["legalquants-litigation"] ?? "",
            ".codex-plugin/plugin.json",
          ),
          "utf8",
        ),
      ) as Record<string, unknown>;
      expect(staged.version).toBe("0.1.0+codex.local-20260818-190405");
      const packed = JSON.parse(
        readFileSync(
          join(
            fixture.repoRoot,
            "dist/openai/legalquants-litigation/.codex-plugin/plugin.json",
          ),
          "utf8",
        ),
      ) as Record<string, unknown>;
      expect(packed.version).toBe("0.1.0+old-token");
      expect(calls.map(({ args }) => args)).toEqual([
        ["plugin", "marketplace", "list", "--json"],
        [
          "plugin",
          "marketplace",
          "add",
          join(fixture.repoRoot, "dist/local-openai-marketplace"),
        ],
        ...PLUGIN_NAMES.map((name) => [
          "plugin",
          "add",
          `${name}@lq-local`,
          "--json",
        ]),
      ]);
    } finally {
      fixture.cleanup();
    }
  });

  it("reuses a configured marketplace without adding it again", () => {
    const fixture = makePackFixture();
    try {
      const marketplaceRoot = join(
        fixture.repoRoot,
        "dist/local-openai-marketplace",
      );
      const { calls, runner } = runnerFor([
        { name: "lq-local", root: marketplaceRoot },
      ]);
      const result = installOpenAi({
        repoRoot: fixture.repoRoot,
        commandRunner: runner,
      });
      expect(result.marketplaceAdded).toBe(false);
      expect(calls.map(({ args }) => args)).toEqual([
        ["plugin", "marketplace", "list", "--json"],
        ...PLUGIN_NAMES.map((name) => [
          "plugin",
          "add",
          `${name}@lq-local`,
          "--json",
        ]),
      ]);
    } finally {
      fixture.cleanup();
    }
  });

  it("writes the complete local marketplace shape", () => {
    const fixture = makePackFixture();
    try {
      const { runner } = runnerFor([]);
      const result = installOpenAi({
        repoRoot: fixture.repoRoot,
        commandRunner: runner,
      });
      const marketplace = JSON.parse(
        readFileSync(result.marketplacePath, "utf8"),
      ) as Record<string, unknown>;
      expect(marketplace).toMatchObject({
        name: "lq-local",
        plugins: PLUGIN_NAMES.map((name) => ({
          name,
          source: { source: "local", path: `./plugins/${name}` },
          policy: { installation: "AVAILABLE", authentication: "ON_INSTALL" },
          category: "Productivity",
        })),
      });
      for (const name of PLUGIN_NAMES) {
        expect(
          existsSync(
            join(result.pluginPaths[name] ?? "", "skills/demo/SKILL.md"),
          ),
        ).toBe(true);
      }
    } finally {
      fixture.cleanup();
    }
  });

  it("fails when lq-local points to another path", () => {
    const fixture = makePackFixture();
    try {
      const marketplaceRoot = join(
        fixture.repoRoot,
        "dist/local-openai-marketplace",
      );
      const sentinelPath = join(marketplaceRoot, "sentinel.txt");
      mkdirSync(marketplaceRoot, { recursive: true });
      writeFileSync(sentinelPath, "preserve me\n");
      const { runner } = runnerFor([
        {
          name: "lq-local",
          marketplaceSource: { source: join(fixture.repoRoot, "elsewhere") },
        },
      ]);
      expect(() =>
        installOpenAi({ repoRoot: fixture.repoRoot, commandRunner: runner }),
      ).toThrow("Marketplace lq-local points elsewhere");
      expect(readFileSync(sentinelPath, "utf8")).toBe("preserve me\n");
    } finally {
      fixture.cleanup();
    }
  });

  it("surfaces Codex command failures without continuing", () => {
    const fixture = makePackFixture();
    try {
      const { calls, runner } = runnerFor([], {
        failingArgs: "plugin marketplace list --json",
      });
      expect(() =>
        installOpenAi({ repoRoot: fixture.repoRoot, commandRunner: runner }),
      ).toThrow("codex plugin marketplace list --json failed: boom");
      expect(calls).toHaveLength(1);
    } finally {
      fixture.cleanup();
    }
  });
});
