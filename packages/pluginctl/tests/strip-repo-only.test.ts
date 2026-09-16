import { describe, expect, it } from "vitest";
import {
  preparePackagedMarkdown,
  stripRepoOnly,
} from "../src/strip-repo-only.js";

describe("stripRepoOnly", () => {
  it("removes contributor plumbing and keeps shipping rules", () => {
    const source = [
      "# Plugin",
      "",
      "<!-- REPO-ONLY -->",
      "",
      "Do not ship this paragraph.",
      "",
      "<!-- /REPO-ONLY -->",
      "",
      "Skills do the work.",
      "",
    ].join("\n");

    expect(stripRepoOnly(source)).toBe("# Plugin\n\nSkills do the work.\n");
  });

  it("strips more than one REPO-ONLY block", () => {
    const source = [
      "# Plugin",
      "",
      "<!-- REPO-ONLY -->",
      "First secret.",
      "<!-- /REPO-ONLY -->",
      "",
      "Keep this.",
      "",
      "<!-- REPO-ONLY -->",
      "Second secret.",
      "<!-- /REPO-ONLY -->",
      "",
      "And this.",
      "",
    ].join("\n");

    expect(stripRepoOnly(source)).toBe("# Plugin\n\nKeep this.\n\nAnd this.\n");
  });

  it("strips the long opening comment used in AGENTS.md", () => {
    const source = [
      "# Plugin",
      "",
      "<!-- REPO-ONLY — plumbing, stripped at packaging -->",
      "",
      "Do not ship this paragraph.",
      "",
      "<!-- /REPO-ONLY -->",
      "",
      "Skills do the work.",
      "",
    ].join("\n");

    expect(stripRepoOnly(source)).toBe("# Plugin\n\nSkills do the work.\n");
  });

  it("strips an AGENTS.md-style contributor block", () => {
    const source = [
      "# Public contributor rules",
      "",
      "<!-- REPO-ONLY — generated contributor plumbing -->",
      "",
      "Maintainer-only pluginctl instructions.",
      "",
      "<!-- /REPO-ONLY -->",
      "",
      "Skills do not read `lqprofile.md` while doing legal work.",
      "",
    ].join("\n");
    const stripped = stripRepoOnly(source);
    expect(stripped).not.toContain("REPO-ONLY");
    expect(stripped).not.toContain("pluginctl");
    expect(stripped).toContain(
      "Skills do not read `lqprofile.md` while doing legal work.",
    );
  });

  it("strips REPO-ONLY plumbing from a maintainer PRD fixture", () => {
    const source = [
      "# Scribe",
      "",
      "<!-- REPO-ONLY -->",
      "CONTRIBUTING rule: maintainer review is required.",
      "Open questions (for review)",
      "<!-- /REPO-ONLY -->",
      "",
      "The scribe is a passive observer.",
      "",
    ].join("\n");
    const stripped = stripRepoOnly(source);
    expect(stripped).not.toContain("REPO-ONLY");
    expect(stripped).not.toContain("CONTRIBUTING rule");
    expect(stripped).not.toContain("Open questions (for review)");
    expect(stripped).toContain("The scribe is a passive observer");
  });

  it("throws on an unclosed block", () => {
    expect(() => stripRepoOnly("<!-- REPO-ONLY -->\nstuck")).toThrow(
      /Unclosed/,
    );
  });
});

describe("preparePackagedMarkdown", () => {
  it("removes internal HTML comments from public markdown", () => {
    const source = [
      "# Public guidance",
      "",
      "<!-- maintainer-only source review",
      "checked 2026-08-26 -->",
      "",
      "Keep this limitation visible.",
      "",
    ].join("\n");

    expect(preparePackagedMarkdown(source)).toBe(
      "# Public guidance\n\nKeep this limitation visible.\n",
    );
  });

  it("throws on an unclosed internal comment", () => {
    expect(() => preparePackagedMarkdown("<!-- internal")).toThrow(/Unclosed/);
  });

  it("does not leave a blank line when the internal comment ends the file", () => {
    expect(preparePackagedMarkdown("# Public\n\n<!-- internal -->\n")).toBe(
      "# Public\n",
    );
  });
});
