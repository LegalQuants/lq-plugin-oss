import { spawnSync } from "node:child_process";
import {
  cpSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join, resolve } from "node:path";
import { packAll } from "./pack.js";
import { loadPluginBundles } from "./validate-manifest.js";

export const LOCAL_MARKETPLACE_NAME = "lq-local";

export type CommandResult = {
  stdout: string;
  stderr: string;
  status: number;
};

export type CommandRunner = (
  command: string,
  args: Array<string>,
  cwd: string,
) => CommandResult;

export type InstallOpenAiOptions = {
  repoRoot: string;
  commandRunner?: CommandRunner;
  now?: Date;
};

export type InstallOpenAiResult = {
  marketplacePath: string;
  pluginPaths: Record<string, string>;
  versions: Record<string, string>;
  marketplaceAdded: boolean;
};

const defaultCommandRunner: CommandRunner = (command, args, cwd) => {
  const result = spawnSync(command, args, { cwd, encoding: "utf8" });
  return {
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    status: result.status ?? 1,
  };
};

export function installOpenAi(
  options: InstallOpenAiOptions,
): InstallOpenAiResult {
  const commandRunner = options.commandRunner ?? defaultCommandRunner;
  const repoRoot = resolve(options.repoRoot);
  const sourceRoot = join(repoRoot, "dist/openai");
  const marketplaceRoot = join(repoRoot, "dist/local-openai-marketplace");
  const bundles = loadPluginBundles(repoRoot);
  const marketplacePath = join(
    marketplaceRoot,
    ".agents/plugins/marketplace.json",
  );

  const packResult = packAll({ repoRoot, check: false });
  if (
    !bundles.every((bundle) =>
      packResult.wrote.some(
        (path) => resolve(path) === join(sourceRoot, bundle.manifest.name),
      ),
    )
  ) {
    throw new Error("pack did not write every OpenAI plugin");
  }

  const listed = runCodex(
    commandRunner,
    ["plugin", "marketplace", "list", "--json"],
    repoRoot,
  );
  const existing = findMarketplace(
    parseJsonOutput(listed.stdout, "marketplace list"),
    LOCAL_MARKETPLACE_NAME,
  );
  let marketplaceAdded = false;

  if (existing && resolveMarketplacePath(existing) !== marketplaceRoot) {
    throw new Error(
      `Marketplace ${LOCAL_MARKETPLACE_NAME} points elsewhere; expected ${marketplaceRoot}`,
    );
  }

  rmSync(marketplaceRoot, { recursive: true, force: true });
  mkdirSync(join(marketplaceRoot, "plugins"), { recursive: true });
  const pluginPaths: Record<string, string> = {};
  const versions: Record<string, string> = {};
  const timestamp = formatTimestamp(options.now ?? new Date());
  for (const bundle of bundles) {
    const pluginName = bundle.manifest.name;
    const pluginPath = join(marketplaceRoot, "plugins", pluginName);
    cpSync(join(sourceRoot, pluginName), pluginPath, { recursive: true });
    const manifestPath = join(pluginPath, ".codex-plugin/plugin.json");
    const manifest = readJson(manifestPath);
    const baseVersion = String(manifest.version).split("+", 1)[0];
    const version = `${baseVersion}+codex.local-${timestamp}`;
    manifest.version = version;
    writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
    pluginPaths[pluginName] = pluginPath;
    versions[pluginName] = version;
  }

  mkdirSync(join(marketplaceRoot, ".agents/plugins"), { recursive: true });
  writeFileSync(
    marketplacePath,
    `${JSON.stringify(buildMarketplace(bundles.map(({ manifest }) => manifest.name)), null, 2)}\n`,
  );

  if (!existing) {
    runCodex(
      commandRunner,
      ["plugin", "marketplace", "add", marketplaceRoot],
      repoRoot,
    );
    marketplaceAdded = true;
  }

  for (const bundle of bundles) {
    runCodex(
      commandRunner,
      [
        "plugin",
        "add",
        `${bundle.manifest.name}@${LOCAL_MARKETPLACE_NAME}`,
        "--json",
      ],
      repoRoot,
    );
  }

  return { marketplacePath, pluginPaths, versions, marketplaceAdded };
}

export function formatTimestamp(now: Date): string {
  const year = now.getUTCFullYear();
  const month = String(now.getUTCMonth() + 1).padStart(2, "0");
  const day = String(now.getUTCDate()).padStart(2, "0");
  const hours = String(now.getUTCHours()).padStart(2, "0");
  const minutes = String(now.getUTCMinutes()).padStart(2, "0");
  const seconds = String(now.getUTCSeconds()).padStart(2, "0");
  return `${year}${month}${day}-${hours}${minutes}${seconds}`;
}

function buildMarketplace(pluginNames: Array<string>) {
  return {
    name: LOCAL_MARKETPLACE_NAME,
    interface: { displayName: "LegalQuants local development" },
    plugins: pluginNames.map((name) => ({
      name,
      source: { source: "local", path: `./plugins/${name}` },
      policy: { installation: "AVAILABLE", authentication: "ON_INSTALL" },
      category: "Productivity",
    })),
  };
}

function runCodex(
  commandRunner: CommandRunner,
  args: Array<string>,
  cwd: string,
): CommandResult {
  const result = commandRunner("codex", args, cwd);
  if (result.status !== 0) {
    const detail =
      result.stderr.trim() || result.stdout.trim() || "unknown error";
    throw new Error(`codex ${args.join(" ")} failed: ${detail}`);
  }
  return result;
}

function readJson(path: string): Record<string, unknown> {
  return JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
}

function parseJsonOutput(stdout: string, label: string): unknown {
  try {
    return JSON.parse(stdout) as unknown;
  } catch {
    throw new Error(`codex ${label} returned invalid JSON`);
  }
}

function findMarketplace(
  value: unknown,
  name: string,
): Record<string, unknown> | undefined {
  const items = Array.isArray(value)
    ? value
    : value &&
        typeof value === "object" &&
        Array.isArray((value as { marketplaces?: unknown }).marketplaces)
      ? (value as { marketplaces: unknown[] }).marketplaces
      : [];
  return items.find((item): item is Record<string, unknown> =>
    Boolean(
      item &&
        typeof item === "object" &&
        (item as { name?: unknown }).name === name,
    ),
  );
}

function resolveMarketplacePath(marketplace: Record<string, unknown>): string {
  const path =
    marketplace.root ??
    (marketplace.marketplaceSource as { source?: unknown } | undefined)
      ?.source ??
    marketplace.path ??
    marketplace.source;
  if (typeof path === "string") {
    return resolve(path);
  }

  if (
    path &&
    typeof path === "object" &&
    typeof (path as { path?: unknown }).path === "string"
  ) {
    return resolve((path as { path: string }).path);
  }

  throw new Error(`Marketplace ${LOCAL_MARKETPLACE_NAME} has no local path`);
}
