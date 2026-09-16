import { join } from "node:path";
import type { PluginManifest } from "./validate-manifest.js";
import { validateJsonSchema } from "./validate-manifest.js";

export const CLAUDE_CODE_PLUGIN_SCHEMA_URL =
  "https://json.schemastore.org/claude-code-plugin-manifest.json";

export type ClaudeCodeManifest = {
  $schema: string;
  name: string;
  version?: string;
  description?: string;
  author?: {
    name: string;
    email?: string;
    url?: string;
  };
  homepage?: string;
  repository?: string;
  license?: string;
  keywords?: Array<string>;
  skills: "./skills/";
};

export function buildClaudeCodeManifest(
  portable: PluginManifest,
): ClaudeCodeManifest {
  const author = buildAuthor(portable.author);

  return {
    $schema: CLAUDE_CODE_PLUGIN_SCHEMA_URL,
    name: portable.name,
    ...(portable.version === undefined ? {} : { version: portable.version }),
    ...(portable.description === undefined
      ? {}
      : { description: portable.description }),
    ...(author === undefined ? {} : { author }),
    ...(portable.homepage === undefined ? {} : { homepage: portable.homepage }),
    ...(portable.repository === undefined
      ? {}
      : { repository: portable.repository }),
    ...(portable.license === undefined ? {} : { license: portable.license }),
    ...(portable.keywords === undefined ? {} : { keywords: portable.keywords }),
    skills: "./skills/",
  };
}

export function validateClaudeCodeManifest(
  repoRoot: string,
  value: object,
): Array<string> {
  return validateJsonSchema(
    join(repoRoot, "packages/contracts/schemas/claude-code-plugin.schema.json"),
    value,
  ).map((error) => `.claude-plugin/plugin.json ${error}`);
}

function buildAuthor(
  portable: PluginManifest["author"],
): ClaudeCodeManifest["author"] | undefined {
  if (portable?.name === undefined) {
    return undefined;
  }

  return {
    name: portable.name,
    ...(portable.email === undefined ? {} : { email: portable.email }),
    ...(portable.url === undefined ? {} : { url: portable.url }),
  };
}
