import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { parse } from "yaml";
import type { PluginBundle } from "./validate-manifest.js";

const VENDORED_MANIFEST_SCHEMAS = new Set([
  "claude-code-plugin.schema.json",
  "plugin.schema.json",
  "openai-plugin.schema.json",
]);

export function validateReleaseMetadata(
  repoRoot: string,
  bundles: Array<PluginBundle>,
) {
  const path = join(repoRoot, "plugin.release.yaml");
  const raw: unknown = parse(readFileSync(path, "utf8"));
  const root = asRecord(raw);
  const errors: Array<string> = [];

  // The practice plugins take `core` (the shared daily-practice skills) plus
  // their own group. The companion is about the lawyer's own journey, not
  // matter work, so it takes only its own group and includes `core/lq-start` at
  // pack time from the single source, so /lq-start ships in every plugin.
  const audienceGroups = bundles.flatMap(({ skillGroups }) =>
    skillGroups.filter((group) => group !== "core"),
  );
  const shapeIsValid = ({ skillGroups, includeSkills }: PluginBundle) => {
    const includes = includeSkills.map(({ group, name }) => `${group}/${name}`);
    if (JSON.stringify(skillGroups) === JSON.stringify(["companion"])) {
      return JSON.stringify(includes) === JSON.stringify(["core/lq-start"]);
    }
    return (
      skillGroups.length === 2 &&
      skillGroups[0] === "core" &&
      includes.length === 0
    );
  };
  if (
    bundles.length !== 3 ||
    !bundles.every(shapeIsValid) ||
    JSON.stringify([...audienceGroups].sort()) !==
      JSON.stringify(["companion", "litigation", "transactional"])
  ) {
    errors.push(
      "plugin.release.yaml must define three bundles: core plus litigation, core plus transactional, and companion including core/lq-start",
    );
  }

  const providers = asRecord(root?.providers);
  const providerNames =
    providers === undefined ? [] : Object.keys(providers).sort();
  if (
    JSON.stringify(providerNames) !== JSON.stringify(["claude-code", "openai"])
  ) {
    errors.push(
      "plugin.release.yaml providers must contain only claude-code and openai for the current release",
    );
  }

  return errors;
}

export function validateContractSchemaCopies(repoRoot: string) {
  const contracts = join(repoRoot, "packages/contracts/schemas");
  const skillsRoot = join(repoRoot, "skills");

  if (!existsSync(contracts) || !existsSync(skillsRoot)) {
    return [];
  }

  const errors: Array<string> = [];

  for (const name of readdirSync(contracts)) {
    if (!name.endsWith(".schema.json") || VENDORED_MANIFEST_SCHEMAS.has(name)) {
      continue;
    }

    const canonical = readFileSync(join(contracts, name));

    for (const copy of findFilesNamed(skillsRoot, name)) {
      if (!readFileSync(copy).equals(canonical)) {
        errors.push(
          `${relative(repoRoot, copy)} must be byte-equal to packages/contracts/schemas/${name}`,
        );
      }
    }
  }

  return errors;
}

function asRecord(value: unknown) {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return undefined;
  }

  return value as Record<string, unknown>;
}

function findFilesNamed(root: string, name: string): Array<string> {
  const found: Array<string> = [];

  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name);

    if (entry.isDirectory()) {
      found.push(...findFilesNamed(path, name));
      continue;
    }

    if (entry.name === name) {
      found.push(path);
    }
  }

  return found;
}
