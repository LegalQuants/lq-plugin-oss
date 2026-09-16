#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";

if (process.argv.includes("--help")) {
  process.stdout.write(
    "Usage: pnpm hooks:install\nInstall this repo's pre-commit hook only when no existing hook dispatcher is configured.\nExisting hooks and global Git configuration are preserved.\n",
  );
  process.exit(0);
}

function git(args) {
  return execFileSync("git", args, { encoding: "utf8" }).trim();
}

const root = git(["rev-parse", "--show-toplevel"]);
process.chdir(root);

let existing = "";
try {
  existing = git(["config", "--get", "core.hooksPath"]);
} catch {
  // `git config --get` exits 1 when no value is configured.
}

if (existing === "packages/pluginctl/githooks") {
  process.stdout.write(
    "Repository hooks are already installed from packages/pluginctl/githooks.\n",
  );
  process.exit(0);
}

if (existing !== "") {
  process.stdout.write(
    `Existing core.hooksPath left unchanged: ${existing}\n` +
      "Keep that dispatcher and configure it to run this repository's .pre-commit-config.yaml.\n",
  );
  process.exit(0);
}

const defaultHooksDirectory = git(["rev-parse", "--git-path", "hooks"]);
const defaultHooks = existsSync(defaultHooksDirectory)
  ? readdirSync(defaultHooksDirectory).filter(
      (name) => !name.endsWith(".sample"),
    )
  : [];

if (defaultHooks.length > 0) {
  process.stdout.write(
    `Existing hooks in ${defaultHooksDirectory} left unchanged: ${defaultHooks.join(", ")}\n` +
      "Keep that dispatcher and configure it to run this repository's .pre-commit-config.yaml.\n",
  );
  process.exit(0);
}

git(["config", "--local", "core.hooksPath", "packages/pluginctl/githooks"]);
process.stdout.write(
  "Installed repository hooks from packages/pluginctl/githooks.\n",
);
