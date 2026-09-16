import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { parse } from "yaml";

const require = createRequire(import.meta.url);

type AjvError = {
  instancePath: string;
  message?: string;
};

type AjvValidator = {
  (data: object): boolean;
  errors: Array<AjvError> | null | undefined;
};

type AjvConstructor = new (options: {
  allErrors: boolean;
  strict: boolean;
}) => {
  compile: (schema: object) => AjvValidator;
};

const Ajv2020 = require("ajv/dist/2020") as AjvConstructor;

export type PluginManifest = {
  $schema: string;
  name: string;
  version?: string;
  description?: string;
  author?: {
    name?: string;
    email?: string;
    url?: string;
  };
  homepage?: string;
  repository?: string;
  license?: string;
  keywords?: Array<string>;
};

export type OpenAiManifestOptions = {
  hooks?: string;
  displayName?: string;
  /** The one-line card subtitle Codex shows under the display name. */
  shortDescription?: string;
};

export const SKILL_GROUPS = [
  "core",
  "litigation",
  "transactional",
  "companion",
] as const;

export type SkillGroup = (typeof SKILL_GROUPS)[number];

/** A single skill projected into a bundle from a group the bundle does not take. */
export type IncludedSkill = {
  group: SkillGroup;
  name: string;
};

export type PluginBundle = {
  displayName: string;
  /** `short_description` in plugin.release.yaml: the card subtitle, per plugin. */
  shortDescription?: string;
  /** The session card's one first move, e.g. `Have a markup? $read-redline on it.` */
  firstMove?: string;
  skillGroups: Array<SkillGroup>;
  /** `include_skills` entries, written `group/name` in plugin.release.yaml. */
  includeSkills: Array<IncludedSkill>;
  manifest: PluginManifest;
};

export function loadPluginBundles(repoRoot: string): Array<PluginBundle> {
  const path = join(repoRoot, "plugin.release.yaml");
  const root = asRecord(parse(readFileSync(path, "utf8")));
  const release = asRecord(root?.release);
  const rawPlugins = root?.plugins;
  const errors: Array<string> = [];

  if (release === undefined) {
    throw new Error("plugin.release.yaml must have a release mapping");
  }
  if (!Array.isArray(rawPlugins) || rawPlugins.length === 0) {
    throw new Error("plugin.release.yaml must declare at least one plugin");
  }

  const author = asRecord(release.author);
  const common = {
    $schema: "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
    version: asString(release.version),
    author:
      author === undefined
        ? undefined
        : {
            name: asString(author.name),
            ...(asString(author.email) === undefined
              ? {}
              : { email: asString(author.email) }),
            ...(asString(author.url) === undefined
              ? {}
              : { url: asString(author.url) }),
          },
    homepage: asString(release.homepage),
    repository: asString(release.repository),
    license: asString(release.license),
    keywords: asStringArray(release.keywords),
  };

  const bundles = rawPlugins.flatMap((rawPlugin, index) => {
    const plugin = asRecord(rawPlugin);
    if (plugin === undefined) {
      errors.push(`plugins[${index}] must be a mapping`);
      return [];
    }

    const id = asString(plugin.id);
    const displayName = asString(plugin.display_name);
    const description = asString(plugin.description);
    const firstMove = asString(plugin.first_move);
    const shortDescription = asString(plugin.short_description);
    if (
      plugin.short_description !== undefined &&
      shortDescription === undefined
    )
      errors.push(`plugins[${index}].short_description must be a string`);
    if (shortDescription !== undefined && shortDescription.length > 80)
      errors.push(
        `plugins[${index}].short_description is a card subtitle; keep it under 80 characters`,
      );
    const skillGroups = asStringArray(plugin.skill_groups);
    if (plugin.first_move !== undefined && firstMove === undefined)
      errors.push(`plugins[${index}].first_move must be a string`);
    if (firstMove !== undefined && !/\$[a-z0-9-]+/.test(firstMove))
      errors.push(
        `plugins[${index}].first_move must name a skill as $name so the banner can check it is installed`,
      );
    const rawIncludes =
      plugin.include_skills === undefined
        ? []
        : asStringArray(plugin.include_skills);
    if (id === undefined) errors.push(`plugins[${index}].id is required`);
    if (displayName === undefined)
      errors.push(`plugins[${index}].display_name is required`);
    if (description === undefined)
      errors.push(`plugins[${index}].description is required`);
    if (skillGroups === undefined || skillGroups.length === 0)
      errors.push(`plugins[${index}].skill_groups is required`);

    const invalidGroups = (skillGroups ?? []).filter(
      (group) => !SKILL_GROUPS.includes(group as SkillGroup),
    );
    if (invalidGroups.length > 0) {
      errors.push(
        `plugins[${index}].skill_groups contains unknown groups: ${invalidGroups.join(", ")}`,
      );
    }

    const includeSkills: Array<IncludedSkill> = [];
    if (rawIncludes === undefined) {
      errors.push(
        `plugins[${index}].include_skills must be a list of group/name`,
      );
    } else {
      for (const entry of rawIncludes) {
        const match = /^([a-z][a-z0-9-]*)\/([a-z][a-z0-9-]*)$/.exec(entry);
        const group = match?.[1];
        const name = match?.[2];
        if (
          match === null ||
          group === undefined ||
          name === undefined ||
          !SKILL_GROUPS.includes(group as SkillGroup)
        ) {
          errors.push(
            `plugins[${index}].include_skills entry "${entry}" must be <group>/<name> with a known group`,
          );
          continue;
        }
        if ((skillGroups ?? []).includes(group)) {
          errors.push(
            `plugins[${index}].include_skills entry "${entry}" is already covered by skill_groups`,
          );
          continue;
        }
        includeSkills.push({ group: group as SkillGroup, name });
      }
    }

    if (
      id === undefined ||
      displayName === undefined ||
      description === undefined ||
      skillGroups === undefined ||
      invalidGroups.length > 0 ||
      rawIncludes === undefined ||
      includeSkills.length !== rawIncludes.length
    ) {
      return [];
    }

    const manifest = {
      ...common,
      name: id,
      description,
    } as PluginManifest;
    for (const error of validatePluginManifest(repoRoot, manifest)) {
      errors.push(`plugins[${index}] ${error}`);
    }

    return [
      {
        displayName,
        ...(shortDescription === undefined ? {} : { shortDescription }),
        ...(firstMove === undefined ? {} : { firstMove }),
        skillGroups: skillGroups as Array<SkillGroup>,
        includeSkills,
        manifest,
      },
    ];
  });

  const ids = bundles.map(({ manifest }) => manifest.name);
  if (new Set(ids).size !== ids.length) {
    errors.push("plugin ids must be unique");
  }
  if (errors.length > 0) {
    throw new Error(`plugin.release.yaml is invalid:\n${errors.join("\n")}`);
  }

  return bundles;
}

export function validatePluginManifest(repoRoot: string, value: object) {
  return validateJsonSchema(
    join(repoRoot, "packages/contracts/schemas/plugin.schema.json"),
    value,
  );
}

export function buildOpenAiManifest(
  portable: PluginManifest,
  options?: OpenAiManifestOptions,
) {
  const manifest = {
    name: portable.name,
    version: portable.version,
    description: portable.description,
    skills: "./skills/",
    ...(portable.author === undefined ? {} : { author: portable.author }),
    ...(portable.homepage === undefined ? {} : { homepage: portable.homepage }),
    ...(portable.repository === undefined
      ? {}
      : { repository: portable.repository }),
    ...(portable.license === undefined ? {} : { license: portable.license }),
    ...(portable.keywords === undefined ? {} : { keywords: portable.keywords }),
    interface: buildOpenAiInterface(
      portable,
      options?.displayName,
      options?.shortDescription,
    ),
    ...(options?.hooks === undefined ? {} : { hooks: options.hooks }),
  };

  return manifest;
}

export function validateOpenAiManifest(repoRoot: string, value: object) {
  return validateJsonSchema(
    join(repoRoot, "packages/contracts/schemas/openai-plugin.schema.json"),
    value,
  ).map((error) => `.codex-plugin/plugin.json ${error}`);
}

export function validateJsonSchema(schemaPath: string, value: object) {
  const schema = readJsonObject(schemaPath);
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  const validate = ajv.compile(schema);

  if (validate(value)) {
    return [];
  }

  return (validate.errors ?? []).map((error) => {
    const where = error.instancePath === "" ? "/" : error.instancePath;
    return `${where} ${error.message ?? "is invalid"}`;
  });
}

function readJsonObject(path: string) {
  const raw: unknown = JSON.parse(readFileSync(path, "utf8"));

  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new Error(`${path} must be a JSON object`);
  }

  return raw;
}

function buildOpenAiInterface(
  portable: PluginManifest,
  displayName?: string,
  shortDescription?: string,
) {
  return {
    displayName: displayName ?? humanizePluginName(portable.name),
    shortDescription: shortDescription ?? "Legal workflows for lawyers",
    ...(portable.description === undefined
      ? {}
      : { longDescription: portable.description }),
    ...(portable.author?.name === undefined
      ? {}
      : { developerName: portable.author.name }),
    category: "Productivity",
    logo: "./assets/lq-logo.png",
    composerIcon: "./assets/lq-logo.png",
    ...(portable.homepage === undefined
      ? {}
      : { websiteURL: portable.homepage }),
  };
}

function humanizePluginName(name: string) {
  return name
    .split("-")
    .map((word, index) => {
      if (word === "codex") {
        return "CODEX";
      }
      if (index > 0 && word === "for") {
        return word;
      }
      return `${word.slice(0, 1).toUpperCase()}${word.slice(1)}`;
    })
    .join(" ");
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return undefined;
  }
  return value as Record<string, unknown>;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function asStringArray(value: unknown): Array<string> | undefined {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value
    : undefined;
}
