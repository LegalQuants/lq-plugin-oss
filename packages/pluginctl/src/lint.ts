import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import type { LintFinding } from "./types.js";

const WAIVER = /<!--\s*vendor-neutral-waiver:\s+.+\s*-->/;

const BANNED = [
  /\bChatGPT\b/i,
  /\bClaude\b/i,
  /\bGemini\b/i,
  /\bGrok\b/i,
  /\bCursor\b/i,
  /\bOpenAI\b/i,
  /\bAnthropic\b/i,
  /\bCopilot\b/i,
  /\bCLAUDE_PLUGIN_ROOT\b/,
  /\bGROK_PLUGIN_ROOT\b/,
  /\bGEMINI\.md\b/,
  /\$\{extensionPath\}/,
  /\$\{user_config\./,
];

const CODEX_EXCEPT_PLUGIN = /\bCodex\b/i;

export function lintVendorNeutralFiles(paths: Array<string>) {
  return paths.flatMap((file) =>
    lintVendorNeutralText(file, readFileSync(file, "utf8")),
  );
}

export function collectMarkdownFiles(root: string) {
  if (!existsSync(root)) {
    return [];
  }

  const files: Array<string> = [];
  walk(root, files);
  return files.filter((file) => file.endsWith(".md") || file.endsWith(".yaml"));
}

export function collectLiveSkillMarkdown(repoRoot: string) {
  const liveRoot = join(repoRoot, "skills");

  if (!existsSync(liveRoot)) {
    return [];
  }

  const files: Array<string> = [];
  walk(liveRoot, files);
  return files.filter((file) => file.endsWith(`${join("", "SKILL.md")}`));
}

export function lintVendorNeutralText(file: string, text: string) {
  const findings: Array<LintFinding> = [];
  const lines = text.split("\n");

  for (const [index, line] of lines.entries()) {
    if (WAIVER.test(line)) {
      continue;
    }

    const previous = index > 0 ? lines[index - 1] : undefined;

    if (previous !== undefined && WAIVER.test(previous)) {
      continue;
    }

    const masked = line
      .replace(/CODEX for Legal/gi, "PLUGIN")
      .replace(/Codex for Legal/gi, "PLUGIN");

    for (const pattern of BANNED) {
      if (pattern.test(masked)) {
        findings.push({
          file,
          line: index + 1,
          message: `provider-specific token matches ${pattern}. Add a vendor-neutral-waiver comment if this name is required.`,
        });
      }
    }

    if (CODEX_EXCEPT_PLUGIN.test(masked)) {
      findings.push({
        file,
        line: index + 1,
        message:
          'provider-specific token "Codex". "CODEX for Legal" is allowed; other Codex references need a waiver.',
      });
    }
  }

  return findings;
}

function walk(dir: string, files: Array<string>) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);

    if (entry.isDirectory()) {
      walk(path, files);
      continue;
    }

    if (entry.isFile()) {
      files.push(path);
    }
  }
}

export function relativeFinding(repoRoot: string, finding: LintFinding) {
  return `${relative(repoRoot, finding.file)}:${finding.line}: ${finding.message}`;
}
