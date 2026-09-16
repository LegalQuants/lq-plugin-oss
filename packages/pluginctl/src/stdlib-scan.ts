import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { listSkillDirs } from "./pack.js";
import { PYTHON_STDLIB } from "./python-stdlib.js";
import type { LintFinding } from "./types.js";

export type StdlibFinding = LintFinding & {
  severity: "error" | "warning";
};

// These exact imports predate the static-skill dependency fence and are
// documented as user-installed document/PDF dependencies. Keep only these
// findings visible as warnings until the legacy scripts are migrated; every
// other shipped import, including a new import in one of these files, errors.
const LEGACY_DEPENDENCY_IMPORTS = new Set([
  "read-redline/scripts/annotate_pdf.py:pypdf",
  "read-redline/scripts/annotate_pdf.py:pdfplumber",
  "read-redline/scripts/make_issues_list.py:docx",
  "read-redline/scripts/parse_redline_pdf.py:pdfplumber",
  "sigpack/scripts/sigpack.py:pypdf",
  "sigpack/scripts/sigpack.py:pdfplumber",
  "sigpack/scripts/sigpack.py:PIL",
]);

export function scanShippedPython(repoRoot: string) {
  const findings: Array<StdlibFinding> = [];

  for (const { name, dir } of listSkillDirs(repoRoot)) {
    findings.push(...scanTree(dir, name));
  }

  return findings;
}

export function importedTopLevels(text: string) {
  const hits: Array<{ module: string; line: number }> = [];

  for (const [index, raw] of text.split("\n").entries()) {
    const line = raw.replace(/#.*$/, "").trim();
    const fromMatch = /^from\s+(\S+)\s+import\b/.exec(line);

    if (fromMatch?.[1] !== undefined) {
      const module = topLevel(fromMatch[1]);
      if (module !== undefined) {
        hits.push({ module, line: index + 1 });
      }
      continue;
    }

    const importMatch = /^import\s+(.+)$/.exec(line);

    if (importMatch?.[1] === undefined) {
      continue;
    }

    for (const part of importMatch[1].split(",")) {
      const name = part
        .trim()
        .split(/\s+as\s+/)[0]
        ?.trim();
      const module = name === undefined ? undefined : topLevel(name);
      if (module !== undefined) {
        hits.push({ module, line: index + 1 });
      }
    }
  }

  return hits;
}

function scanTree(root: string, skillName: string) {
  if (!existsSync(root)) {
    return [];
  }

  const findings: Array<StdlibFinding> = [];
  const bundledModules = listBundledScriptModules(root);

  for (const file of listShippedPython(root)) {
    for (const hit of importedTopLevels(readFileSync(file, "utf8"))) {
      if (PYTHON_STDLIB.has(hit.module) || bundledModules.has(hit.module)) {
        continue;
      }

      // A sibling module ships in the same scripts directory and is not an
      // external runtime dependency (for example wiki_retrieval.py importing
      // wiki.py). Keep the scanner focused on packages users must install.
      if (existsSync(join(dirname(file), `${hit.module}.py`))) {
        continue;
      }

      findings.push({
        file,
        line: hit.line,
        severity: LEGACY_DEPENDENCY_IMPORTS.has(
          `${skillName}/${relative(root, file).split(sep).join("/")}:${hit.module}`,
        )
          ? "warning"
          : "error",
        message: `non-stdlib import '${hit.module}' in a shipped script. Bundled MVP scripts must use the Python standard library only.`,
      });
    }
  }

  return findings;
}

function listBundledScriptModules(root: string) {
  const scripts = join(root, "scripts");
  const modules = new Set<string>();

  if (!existsSync(scripts)) {
    return modules;
  }

  for (const entry of readdirSync(scripts, { withFileTypes: true })) {
    if (entry.isFile() && entry.name.endsWith(".py")) {
      modules.add(entry.name.slice(0, -3));
      continue;
    }

    if (
      entry.isDirectory() &&
      existsSync(join(scripts, entry.name, "__init__.py"))
    ) {
      modules.add(entry.name);
    }
  }

  return modules;
}

function listShippedPython(root: string) {
  const files: Array<string> = [];
  walk(root, files);
  return files.filter((file) => {
    const rel = relative(root, file).split(sep).join("/");
    if (rel.split("/").includes("evals")) {
      return false;
    }

    return /(^|\/)scripts\/.+\.py$/.test(rel);
  });
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

function topLevel(spec: string) {
  if (spec.startsWith(".")) {
    return undefined;
  }

  const name = spec.split(".")[0];
  return name === undefined || name === "" ? undefined : name;
}
