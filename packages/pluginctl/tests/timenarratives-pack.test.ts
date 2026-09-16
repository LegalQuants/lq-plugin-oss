import { spawnSync } from "node:child_process";
import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { packAll } from "../src/pack.js";
import { findRepoRoot } from "../src/repo.js";
import { makePackFixture } from "./helpers/pack-fixture.js";

function listRelativeFiles(root: string, prefix = ""): Array<string> {
  const files: Array<string> = [];
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    if (entry.name === "__pycache__" || entry.name.endsWith(".pyc")) {
      continue;
    }
    const relative = prefix === "" ? entry.name : join(prefix, entry.name);
    if (entry.isDirectory()) {
      files.push(...listRelativeFiles(join(root, entry.name), relative));
    } else {
      files.push(relative);
    }
  }
  return files;
}

function findPythonCommand(): string {
  for (const candidate of ["python3", "python"]) {
    const probe = spawnSync(candidate, ["--version"], { encoding: "utf8" });
    if (probe.status === 0) {
      return candidate;
    }
  }
  throw new Error("Python is required for the TimeNarratives pack smoke test");
}

function runPython(
  python: string,
  script: string,
  args: string[],
  cwd: string,
): Record<string, unknown> {
  const result = spawnSync(python, [script, ...args], {
    cwd,
    encoding: "utf8",
  });
  expect(result.status, result.stderr || result.stdout).toBe(0);
  return JSON.parse(result.stdout) as Record<string, unknown>;
}

describe("TimeNarratives packaged installation", () => {
  it("ships its complete offline contract and runs a confirmed no-event journey", () => {
    const fixture = makePackFixture();

    try {
      const skillName = "timenarratives";
      const realSkill = join(findRepoRoot(), "skills/core", skillName);
      const fixtureSkill = join(fixture.repoRoot, "skills/core", skillName);
      cpSync(realSkill, fixtureSkill, {
        recursive: true,
        filter: (source) => !/[\\/]evals(?:[\\/]|$)/.test(source),
      });
      packAll({ repoRoot: fixture.repoRoot, check: false });

      const packaged = {
        portable: join(
          fixture.repoRoot,
          "dist/agent-plugins/legalquants-litigation/skills",
          skillName,
        ),
        openai: join(
          fixture.repoRoot,
          "dist/openai/legalquants-litigation/skills",
          skillName,
        ),
      };
      const sourceFiles = listRelativeFiles(fixtureSkill);
      expect(sourceFiles.length).toBeGreaterThan(0);
      for (const target of ["portable", "openai"] as const) {
        for (const relative of sourceFiles) {
          expect(
            existsSync(join(packaged[target], relative)),
            `${target} package is missing ${relative}`,
          ).toBe(true);
        }
        for (const excluded of ["evals", "PRD.md", "skill.yaml", "sections"]) {
          expect(
            existsSync(join(packaged[target], excluded)),
            `${target} package unexpectedly contains ${excluded}`,
          ).toBe(false);
        }
      }

      const python = findPythonCommand();
      const runRoot = mkdtempSync(join(fixture.repoRoot, "tn-pack-run-"));
      const sourceRoot = join(runRoot, "selected");
      mkdirSync(sourceRoot);
      writeFileSync(
        join(sourceRoot, "work.txt"),
        "Reviewed the café chronology.\n",
        "utf8",
      );
      const requestPath = join(runRoot, "request.json");
      writeFileSync(
        requestPath,
        JSON.stringify({
          schemaVersion: "timenarratives.request.v1",
          runId: "PackSmoke01",
          actor: { id: "LAWYER1", name: "Synthetic Lawyer", aliases: [] },
          matter: {
            id: "MATTER1",
            client: "Synthetic Client",
            aliases: [],
          },
          selections: [{ kind: "file", path: "work.txt" }],
          filters: {
            sourceTypes: ["text"],
            since: null,
            until: null,
            asOf: "2026-08-21T12:00:00+01:00",
          },
        }),
      );
      const openaiSkill = packaged.openai;
      const packetPath = join(runRoot, "packet.json");
      runPython(
        python,
        join(openaiSkill, "scripts/build_packet.py"),
        [
          "--source-root",
          sourceRoot,
          "--request",
          requestPath,
          "--out",
          packetPath,
        ],
        openaiSkill,
      );
      const packet = JSON.parse(readFileSync(packetPath, "utf8")) as {
        runId: string;
        packetDigestSha256: string;
        units: Array<{ unitId: string }>;
      };
      expect(packet.units).toHaveLength(1);

      const mapPath = join(runRoot, "map.json");
      writeFileSync(
        mapPath,
        JSON.stringify({
          schemaVersion: "timenarratives.map.v1",
          runId: packet.runId,
          packetDigest: packet.packetDigestSha256,
          unitAssessment: [
            {
              unitId: packet.units[0]?.unitId,
              disposition: "read_but_unused",
              reason: "not_relevant",
            },
          ],
          atoms: [],
          events: [],
          workstreams: [],
          clauses: [],
        }),
      );
      const validationPath = join(runRoot, "validation.json");
      const validation = runPython(
        python,
        join(openaiSkill, "scripts/validate_map.py"),
        ["--packet", packetPath, "--map", mapPath, "--out", validationPath],
        openaiSkill,
      );
      expect(validation.status).toBe("passed");
      const mapDigest = validation.mapDigest;
      expect(mapDigest).toMatch(/^[0-9a-f]{64}$/);
      if (typeof mapDigest !== "string") {
        throw new Error("validation did not return a map digest");
      }
      const confirmationToken = validation.confirmationToken;
      expect(confirmationToken).toMatch(/^TN-[0-9a-f]{16}$/);
      if (typeof confirmationToken !== "string") {
        throw new Error("validation did not return a confirmation token");
      }
      const confirmationPath = join(runRoot, "confirmation.json");
      writeFileSync(
        confirmationPath,
        JSON.stringify({
          schemaVersion: "timenarratives.confirmation.v1",
          runId: packet.runId,
          packetDigest: packet.packetDigestSha256,
          mapDigest,
          decision: "confirmed",
          recording: "session_recorded_user_confirmation",
          confirmationToken,
        }),
      );

      const renderedRoot = join(runRoot, "rendered");
      runPython(
        python,
        join(openaiSkill, "scripts/render_deliverable.py"),
        [
          "--request",
          requestPath,
          "--source-root",
          sourceRoot,
          "--packet",
          packetPath,
          "--map",
          mapPath,
          "--confirmation",
          confirmationPath,
          "--out-dir",
          renderedRoot,
        ],
        openaiSkill,
      );
      const deliverablePath = join(
        renderedRoot,
        "artifacts",
        "deliverable.json",
      );
      const markdownPath = join(renderedRoot, "artifacts", "narratives.md");
      const deliverable = JSON.parse(readFileSync(deliverablePath, "utf8")) as {
        status: string;
        narratives: unknown[];
        receipt: Record<string, unknown>;
      };
      expect(deliverable.status).toBe("no_supported_activity");
      expect(deliverable.narratives).toEqual([]);
      expect(deliverable.receipt).toMatchObject({
        packetScope: "expressly_selected_only",
        workdayCompleteness: "not_assessed",
        postingState: "unposted_draft",
        confirmationToken,
      });
      expect(readFileSync(markdownPath, "utf8")).toContain(
        "Status: no supportable work found for the named lawyer in the selected sources",
      );

      const existingOutput = join(runRoot, "existing-output");
      mkdirSync(existingOutput);
      const marker = join(existingOutput, "preserve.txt");
      writeFileSync(marker, "preserve", "utf8");
      const refused = spawnSync(
        python,
        [
          join(openaiSkill, "scripts/render_deliverable.py"),
          "--request",
          requestPath,
          "--source-root",
          sourceRoot,
          "--packet",
          packetPath,
          "--map",
          mapPath,
          "--confirmation",
          confirmationPath,
          "--out-dir",
          existingOutput,
        ],
        { cwd: openaiSkill, encoding: "utf8" },
      );
      expect(refused.status, refused.stderr || refused.stdout).toBe(2);
      expect(refused.stdout).toContain('"status": "operational_fault"');
      expect(readFileSync(marker, "utf8")).toBe("preserve");

      const emptyOutput = join(runRoot, "empty-output");
      mkdirSync(emptyOutput);
      const emptyRefused = spawnSync(
        python,
        [
          join(openaiSkill, "scripts/render_deliverable.py"),
          "--request",
          requestPath,
          "--source-root",
          sourceRoot,
          "--packet",
          packetPath,
          "--map",
          mapPath,
          "--confirmation",
          confirmationPath,
          "--out-dir",
          emptyOutput,
        ],
        { cwd: openaiSkill, encoding: "utf8" },
      );
      expect(
        emptyRefused.status,
        emptyRefused.stderr || emptyRefused.stdout,
      ).toBe(2);
      expect(emptyRefused.stdout).toContain('"status": "operational_fault"');
      expect(existsSync(emptyOutput)).toBe(true);
    } finally {
      fixture.cleanup();
    }
  }, 30_000);
});
