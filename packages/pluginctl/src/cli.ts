import { relative, sep } from "node:path";
import { installOpenAi } from "./install-openai.js";
import {
  collectLiveSkillMarkdown,
  lintVendorNeutralFiles,
  relativeFinding,
} from "./lint.js";
import { packAll } from "./pack.js";
import { findRepoRoot } from "./repo.js";
import { scanShippedPython } from "./stdlib-scan.js";
import type { LintFinding } from "./types.js";
import {
  buildClaudeCodeManifest,
  validateClaudeCodeManifest,
} from "./validate-claude-manifest.js";
import {
  validateContractSchemaCopies,
  validateReleaseMetadata,
} from "./validate-consistency.js";
import {
  buildOpenAiManifest,
  loadPluginBundles,
  validateOpenAiManifest,
} from "./validate-manifest.js";

export function main(argv: Array<string>) {
  const [command, ...rest] = argv;
  const repoRoot = findRepoRoot();

  switch (command) {
    case "assemble":
    case "pack":
      return runPack(repoRoot, rest.includes("--check"));
    case "lint":
      return runLint(repoRoot);
    case "validate":
      return runValidate(repoRoot);
    case "install-openai":
      return runInstallOpenAi(repoRoot);
    case undefined:
    case "help":
    case "--help":
      process.stdout.write(helpText());
      return 0;
    default:
      process.stderr.write(`Unknown command: ${command}\n${helpText()}`);
      return 2;
  }
}

function runPack(repoRoot: string, check: boolean) {
  const result = packAll({ repoRoot, check });

  if (result.stale.length > 0) {
    process.stderr.write(
      `Packed SKILL.md files would differ from source. Run: pnpm pluginctl pack\n${result.stale.join("\n")}\n`,
    );
    return 1;
  }

  process.stdout.write(
    check
      ? "Static skills are current.\n"
      : `Wrote ${result.wrote.length} paths.\n`,
  );
  return 0;
}

function runLint(repoRoot: string) {
  const findings = lintVendorNeutralFiles(collectLiveSkillMarkdown(repoRoot));

  const stdlib = scanShippedPython(repoRoot);
  const stdlibErrors = stdlib.filter((finding) => finding.severity === "error");
  const stdlibWarnings = stdlib.filter(
    (finding) => finding.severity === "warning",
  );

  for (const warning of stdlibWarnings) {
    process.stderr.write(formatStdlibWarning(repoRoot, warning));
  }

  const errors = [...findings, ...stdlibErrors];

  if (errors.length > 0) {
    process.stderr.write(
      `${errors.map((finding) => relativeFinding(repoRoot, finding)).join("\n")}\n`,
    );
    return 1;
  }

  process.stdout.write("Vendor-neutral lint passed.\n");

  if (stdlibWarnings.length > 0) {
    process.stdout.write(
      `${stdlibWarnings.length} stdlib warning(s) on live skill scripts.\n`,
    );
  }

  return 0;
}

function runValidate(repoRoot: string) {
  try {
    const bundles = loadPluginBundles(repoRoot);
    const errors = [
      ...validateReleaseMetadata(repoRoot, bundles),
      ...bundles.flatMap((bundle) =>
        validateOpenAiManifest(
          repoRoot,
          buildOpenAiManifest(bundle.manifest, {
            displayName: bundle.displayName,
          }),
        ),
      ),
      ...bundles.flatMap((bundle) =>
        validateClaudeCodeManifest(
          repoRoot,
          buildClaudeCodeManifest(bundle.manifest),
        ),
      ),
      ...validateContractSchemaCopies(repoRoot),
    ];

    if (errors.length > 0) {
      process.stderr.write(`${errors.join("\n")}\n`);
      return 1;
    }
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : error}\n`);
    return 1;
  }

  const lintStatus = runLint(repoRoot);

  if (lintStatus !== 0) {
    return lintStatus;
  }

  return runPack(repoRoot, true);
}

function runInstallOpenAi(repoRoot: string) {
  try {
    const result = installOpenAi({ repoRoot });
    process.stdout.write(
      `Installed ${Object.entries(result.versions)
        .map(([name, version]) => `${name}@${version}`)
        .join(", ")}. Start a new Codex task to load the updated plugins.\n`,
    );
    return 0;
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : error}\n`);
    return 1;
  }
}

function formatStdlibWarning(repoRoot: string, finding: LintFinding) {
  const file = relative(repoRoot, finding.file).split(sep).join("/");
  const message = finding.message;

  if (process.env.GITHUB_ACTIONS === "true") {
    return `::warning file=${file},line=${finding.line}::${message}\n`;
  }

  return `warning: ${file}:${finding.line}: ${message}\n`;
}

function helpText() {
  return `pluginctl — lint, pack, and locally install static skills

Commands:
  pack [--check]      Build native dist/ packages, combined plugins/, and catalogs
  assemble [--check]  Alias of pack
  install-openai      Pack and install a cache-busted local OpenAI plugin copy
  lint                Fail on provider-specific tokens in authored SKILL.md
  validate            Manifest schema + release metadata + lint + --check
`;
}
