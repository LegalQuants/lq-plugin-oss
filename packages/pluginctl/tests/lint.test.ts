import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  collectLiveSkillMarkdown,
  collectMarkdownFiles,
  lintVendorNeutralFiles,
  lintVendorNeutralText,
} from "../src/lint.js";
import { findRepoRoot } from "../src/repo.js";

describe("lintVendorNeutralText", () => {
  it("allows the plugin product name and flags other Codex uses", () => {
    const allowed = lintVendorNeutralText(
      "skill.md",
      "The CODEX for Legal plugin verifies citations.\n",
    );
    expect(allowed).toEqual([]);

    const banned = lintVendorNeutralText(
      "skill.md",
      "Open the Codex SDK next.\n",
    );
    expect(banned.length).toBeGreaterThan(0);
  });

  it("flags ChatGPT and Claude unless a waiver is present", () => {
    const flagged = lintVendorNeutralText(
      "skill.md",
      "This requires ChatGPT Work.\n",
    );
    expect(flagged).toHaveLength(1);

    const waived = lintVendorNeutralText(
      "skill.md",
      "<!-- vendor-neutral-waiver: host capability note -->\nThis requires ChatGPT Work.\n",
    );
    expect(waived).toEqual([]);
  });

  it("flags OpenAI, Anthropic, and Copilot", () => {
    expect(
      lintVendorNeutralText("skill.md", "This works best in OpenAI.\n"),
    ).toHaveLength(1);
    expect(
      lintVendorNeutralText("skill.md", "Requires the Anthropic API.\n"),
    ).toHaveLength(1);
    expect(
      lintVendorNeutralText("skill.md", "Use Copilot for this step.\n"),
    ).toHaveLength(1);
  });

  it("returns no files when the root is missing", () => {
    expect(collectMarkdownFiles("/no/such/pluginctl-skills-root")).toEqual([]);
  });

  it("accepts live SKILL.md files under skills/", () => {
    const files = collectLiveSkillMarkdown(findRepoRoot());
    expect(
      files.some((file) =>
        file.endsWith(`${join("read-redline", "SKILL.md")}`),
      ),
    ).toBe(true);
    expect(lintVendorNeutralFiles(files)).toEqual([]);
  });
});
