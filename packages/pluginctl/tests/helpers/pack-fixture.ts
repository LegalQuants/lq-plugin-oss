import {
  cpSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { findRepoRoot } from "../../src/repo.js";

export function makePackFixture(options?: {
  livePassthrough?: boolean;
  orphanGenerated?: boolean;
  leftoverYaml?: boolean;
  openAiHooks?: boolean;
}) {
  const repoRoot = mkdtempSync(join(tmpdir(), "pluginctl-"));
  const real = findRepoRoot();
  cpSync(join(real, "LICENSE"), join(repoRoot, "LICENSE"));

  // The real manifest has the companion include `core/lq-start`; the fixture only
  // ships a `demo` skill, so point the include at that instead.
  writeFileSync(
    join(repoRoot, "plugin.release.yaml"),
    readFileSync(join(real, "plugin.release.yaml"), "utf8")
      .replace("- core/lq-start", "- core/demo")
      .replace(/first_move: .*/g, 'first_move: "Try $demo."'),
  );
  writeFileSync(join(repoRoot, "AGENTS.md"), "# Plugin\n\nShipped rules.\n");
  mkdirSync(join(repoRoot, "docs/lq/scribe"), { recursive: true });
  writeFileSync(
    join(repoRoot, "docs/lq/scribe/PRD.md"),
    "<!-- REPO-ONLY -->\nsecret\n<!-- /REPO-ONLY -->\n\n# Scribe\n",
  );
  mkdirSync(join(repoRoot, "docs/lq/templates"), { recursive: true });
  writeFileSync(
    join(repoRoot, "docs/lq/templates/lqplaybook.md"),
    "# LQ Playbook\n",
  );
  writeFileSync(
    join(repoRoot, "docs/lq/templates/lqprofile.md"),
    "# LQ Profile\n",
  );

  mkdirSync(join(repoRoot, "packages/contracts/schemas"), { recursive: true });
  cpSync(
    join(real, "packages/contracts/schemas/plugin.schema.json"),
    join(repoRoot, "packages/contracts/schemas/plugin.schema.json"),
  );
  cpSync(
    join(real, "packages/contracts/schemas/openai-plugin.schema.json"),
    join(repoRoot, "packages/contracts/schemas/openai-plugin.schema.json"),
  );
  cpSync(
    join(real, "packages/contracts/schemas/claude-code-plugin.schema.json"),
    join(repoRoot, "packages/contracts/schemas/claude-code-plugin.schema.json"),
  );
  mkdirSync(join(repoRoot, "packages/pluginctl/assets"), { recursive: true });
  cpSync(
    join(real, "packages/pluginctl/assets/openai"),
    join(repoRoot, "packages/pluginctl/assets/openai"),
    { recursive: true },
  );

  const skillDir = join(repoRoot, "skills/core/demo");
  mkdirSync(join(skillDir, "scripts"), { recursive: true });
  writeFileSync(join(skillDir, "SKILL.md"), "# demo\n\nRun scripts/ok.py.\n");
  writeFileSync(join(skillDir, "scripts/ok.py"), "import json\n");

  if (options?.leftoverYaml) {
    writeFileSync(join(skillDir, "skill.yaml"), "name: demo\n");
  }

  if (options?.orphanGenerated) {
    mkdirSync(join(repoRoot, "skills/core/ghost"), { recursive: true });
    writeFileSync(
      join(repoRoot, "skills/core/ghost/SKILL.md"),
      "<!-- AUTO-GENERATED from skill.yaml and sections/; run pnpm pluginctl pack -->\n",
    );
  }

  if (options?.livePassthrough) {
    mkdirSync(join(repoRoot, "skills/core/sidecar"), { recursive: true });
    writeFileSync(
      join(repoRoot, "skills/core/sidecar/SKILL.md"),
      "# sidecar\n",
    );
  }

  if (options?.openAiHooks) {
    const hooks = join(repoRoot, "packages/pluginctl/hooks");
    mkdirSync(hooks, { recursive: true });
    writeFileSync(join(hooks, "openai.json"), '{"hooks": {}}\n');
    writeFileSync(join(hooks, "adapter.py"), "import json\n");
  }

  return {
    repoRoot,
    cleanup() {
      rmSync(repoRoot, { recursive: true, force: true });
    },
  };
}
