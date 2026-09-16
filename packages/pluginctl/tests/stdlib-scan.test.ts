import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, posix, win32 } from "node:path";
import { describe, expect, it } from "vitest";
import { findRepoRoot } from "../src/repo.js";
import { importedTopLevels, scanShippedPython } from "../src/stdlib-scan.js";

function isInSkill(file: string, skill: string): boolean {
  return new RegExp(`/skills/(?:[^/]+/)?${skill}/`).test(
    file.replaceAll("\\", "/"),
  );
}

describe("importedTopLevels", () => {
  it("reads import and from lines and skips relatives and comments", () => {
    const hits = importedTopLevels(`
import json, sys
from pathlib import Path
from __future__ import annotations
from . import local
# import pdfplumber
import pdfplumber
from pypdf.annotations import Highlight
`);

    expect(hits.map((hit) => hit.module)).toEqual([
      "json",
      "sys",
      "pathlib",
      "__future__",
      "pdfplumber",
      "pypdf",
    ]);
  });
});

describe("scanShippedPython", () => {
  it("matches skill paths across POSIX and Windows separators", () => {
    expect(
      isInSkill(
        posix.join("/repo", "skills", "sigpack", "scripts", "sigpack.py"),
        "sigpack",
      ),
    ).toBe(true);
    expect(
      isInSkill(
        win32.join("D:\\repo", "skills", "sigpack", "scripts", "sigpack.py"),
        "sigpack",
      ),
    ).toBe(true);
  });

  it("keeps documented legacy dependency skills at warning severity", () => {
    const findings = scanShippedPython(findRepoRoot());
    const external = findings.filter((finding) =>
      finding.message.includes("non-stdlib import"),
    );

    expect(external).not.toHaveLength(0);
    expect(external.every((finding) => finding.severity === "warning")).toBe(
      true,
    );
    expect(
      external.every(
        (finding) =>
          isInSkill(finding.file, "read-redline") ||
          isInSkill(finding.file, "sigpack"),
      ),
    ).toBe(true);
    expect(findings.some((finding) => finding.message.includes("'wiki'"))).toBe(
      false,
    );
  });

  it("errors on unsupported imports in other static skill scripts", () => {
    const repoRoot = mkdtempSync(join(tmpdir(), "pluginctl-stdlib-"));

    try {
      const skillDir = join(repoRoot, "skills/core/demo");
      mkdirSync(join(skillDir, "scripts"), { recursive: true });
      writeFileSync(join(skillDir, "SKILL.md"), "# demo\n");
      writeFileSync(join(skillDir, "scripts/check.py"), "import pdfplumber\n");

      expect(scanShippedPython(repoRoot)).toEqual([
        expect.objectContaining({
          line: 1,
          severity: "error",
          message: expect.stringContaining("'pdfplumber'"),
        }),
      ]);
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
    }
  });

  it("errors on new imports in legacy dependency skills", () => {
    const repoRoot = mkdtempSync(join(tmpdir(), "pluginctl-stdlib-"));

    try {
      const skillDir = join(repoRoot, "skills/transactional/sigpack");
      mkdirSync(join(skillDir, "scripts"), { recursive: true });
      writeFileSync(join(skillDir, "SKILL.md"), "# sigpack\n");
      writeFileSync(join(skillDir, "scripts/sigpack.py"), "import requests\n");
      writeFileSync(join(skillDir, "scripts/other.py"), "import requests\n");

      expect(scanShippedPython(repoRoot)).toEqual([
        expect.objectContaining({ severity: "error" }),
        expect.objectContaining({ severity: "error" }),
      ]);
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
    }
  });

  it("recognizes cite-check's bundled common package as local", () => {
    const findings = scanShippedPython(findRepoRoot());
    expect(
      findings.filter((finding) => isInSkill(finding.file, "cite-check")),
    ).toEqual([]);
  });

  it("allows imports from a bundled scripts package", () => {
    const repoRoot = mkdtempSync(join(tmpdir(), "pluginctl-stdlib-"));

    try {
      const skillDir = join(repoRoot, "skills/core/demo");
      mkdirSync(join(skillDir, "scripts/common"), { recursive: true });
      writeFileSync(join(skillDir, "SKILL.md"), "# demo\n");
      writeFileSync(join(skillDir, "scripts/common/__init__.py"), "");
      writeFileSync(
        join(skillDir, "scripts/common/core.py"),
        "from common import helper\n",
      );

      expect(scanShippedPython(repoRoot)).toEqual([]);
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
    }
  });
});
