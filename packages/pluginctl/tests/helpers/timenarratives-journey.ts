import { spawnSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export type SchemaName =
  | "request"
  | "packet"
  | "map"
  | "confirmation"
  | "deliverable";
export type JsonObject = Record<string, unknown>;
export type TimeNarrativesJourney = {
  cleanup: () => void;
  values: Record<SchemaName, JsonObject>;
};

function readObject(path: string): JsonObject {
  const parsed: unknown = JSON.parse(readFileSync(path, "utf8"));
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error(`${path} must contain a JSON object`);
  }
  return parsed as JsonObject;
}

function findPython(): string {
  for (const candidate of ["python3", "python"]) {
    if (spawnSync(candidate, ["--version"]).status === 0) {
      return candidate;
    }
  }
  throw new Error("Python is required for the TimeNarratives schema journey");
}

function runPython(
  python: string,
  script: string,
  args: string[],
  cwd: string,
): void {
  const result = spawnSync(python, [script, ...args], {
    cwd,
    encoding: "utf8",
  });
  if (result.status !== 0) {
    throw new Error(result.stderr || result.stdout || `${script} failed`);
  }
}

function writeJson(path: string, value: JsonObject): void {
  writeFileSync(path, JSON.stringify(value), "utf8");
}

function requiredText(value: JsonObject, key: string): string {
  const text = value[key];
  if (typeof text !== "string") {
    throw new Error(`${key} must be a string`);
  }
  return text;
}

function requiredInteger(value: JsonObject, key: string): number {
  const number = value[key];
  if (!Number.isInteger(number)) {
    throw new Error(`${key} must be an integer`);
  }
  return number as number;
}

export function buildTimeNarrativesJourney(
  repoRoot: string,
): TimeNarrativesJourney {
  const root = mkdtempSync(join(tmpdir(), "tn-schema-parity-"));
  const cleanup = () => rmSync(root, { force: true, recursive: true });
  try {
    const skillRoot = join(repoRoot, "skills/core/timenarratives");
    const sourceRoot = join(root, "selected");
    mkdirSync(sourceRoot);
    const request: JsonObject = {
      schemaVersion: "timenarratives.request.v1",
      runId: "NodeSchemaParity",
      actor: { id: "LAWYER1", name: "Synthetic Lawyer", aliases: [] },
      matter: { id: "MATTER1", client: "Synthetic Client", aliases: [] },
      selections: [
        {
          kind: "user_note",
          text: "Synthetic Lawyer prepared claim analysis for MATTER1.",
        },
      ],
      filters: {
        sourceTypes: ["user_note"],
        since: null,
        until: null,
        asOf: "2024-02-29T23:59:59.123456+05:30",
      },
    };
    const requestPath = join(root, "request.json");
    const packetPath = join(root, "packet.json");
    writeJson(requestPath, request);
    const python = findPython();
    runPython(
      python,
      join(skillRoot, "scripts/build_packet.py"),
      [
        "--source-root",
        sourceRoot,
        "--request",
        requestPath,
        "--out",
        packetPath,
      ],
      skillRoot,
    );
    const packet = readObject(packetPath);
    const units = packet.units;
    if (!Array.isArray(units) || units.length !== 1) {
      throw new Error("schema journey must compile exactly one unit");
    }
    const unit = units[0] as JsonObject;
    const mapping: JsonObject = {
      schemaVersion: "timenarratives.map.v1",
      runId: requiredText(packet, "runId"),
      packetDigest: requiredText(packet, "packetDigestSha256"),
      unitAssessment: [
        {
          unitId: requiredText(unit, "unitId"),
          disposition: "used",
          reason: null,
        },
      ],
      atoms: [
        {
          atomId: "ATOM1",
          unitId: requiredText(unit, "unitId"),
          startByte: 0,
          endByte: requiredInteger(unit, "utf8End"),
          spanSha256: requiredText(unit, "canonicalUtf8Sha256"),
          components: ["actor", "action", "object", "matter"],
        },
      ],
      events: [
        {
          eventId: "EVENT1",
          assertedBy: requiredText(unit, "sourceAuthor"),
          performedByActorId: "LAWYER1",
          namedTimekeeperActorId: "LAWYER1",
          action: "Prepared claim analysis",
          object: "Meridian proceedings",
          purpose: null,
          matterId: "MATTER1",
          workstreamId: "WORK1",
          atomIds: ["ATOM1"],
        },
      ],
      workstreams: [
        {
          workstreamId: "WORK1",
          label: "Claim strategy",
          category: "substantive",
        },
      ],
      clauses: [
        {
          clauseId: "CLAUSE1",
          workstreamId: "WORK1",
          clauseOwnerActorId: "LAWYER1",
          eventIds: ["EVENT1"],
          text:
            "Prepared a matter-focused analysis of the selected claim material.\n\n" +
            "Organised the supported points for lawyer review within the selected proceedings.",
        },
      ],
    };
    const mapPath = join(root, "map.json");
    const validationPath = join(root, "validation.json");
    writeJson(mapPath, mapping);
    runPython(
      python,
      join(skillRoot, "scripts/validate_map.py"),
      ["--packet", packetPath, "--map", mapPath, "--out", validationPath],
      skillRoot,
    );
    const validation = readObject(validationPath);
    const confirmation: JsonObject = {
      schemaVersion: "timenarratives.confirmation.v1",
      runId: requiredText(packet, "runId"),
      packetDigest: requiredText(packet, "packetDigestSha256"),
      mapDigest: requiredText(validation, "mapDigest"),
      decision: "confirmed",
      recording: "session_recorded_user_confirmation",
      confirmationToken: requiredText(validation, "confirmationToken"),
    };
    const confirmationPath = join(root, "confirmation.json");
    const output = join(root, "rendered");
    writeJson(confirmationPath, confirmation);
    runPython(
      python,
      join(skillRoot, "scripts/render_deliverable.py"),
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
        output,
      ],
      skillRoot,
    );
    const deliverable = readObject(
      join(output, "artifacts", "deliverable.json"),
    );
    return {
      cleanup,
      values: { request, packet, map: mapping, confirmation, deliverable },
    };
  } catch (error) {
    cleanup();
    throw error;
  }
}
