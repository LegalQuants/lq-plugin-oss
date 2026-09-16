import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { findRepoRoot } from "../src/repo.js";
import {
  buildTimeNarrativesJourney,
  type TimeNarrativesJourney,
} from "./helpers/timenarratives-journey.js";

const require = createRequire(import.meta.url);

type JsonObject = Record<string, unknown>;
type Validator = ((value: unknown) => boolean) & {
  errors?: Array<{ instancePath: string; message?: string }> | null;
};
type AjvConstructor = new (options: {
  allErrors: boolean;
  strict: boolean;
}) => { compile: (schema: object) => Validator };

const Ajv2020 = require("ajv/dist/2020") as AjvConstructor;
const repoRoot = findRepoRoot();

function readObject(path: string): JsonObject {
  const value: unknown = JSON.parse(readFileSync(path, "utf8"));
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("fixture must contain an object");
  }
  return value as JsonObject;
}

function validator(name: "map" | "deliverable"): Validator {
  const schema = readObject(
    join(
      repoRoot,
      "packages/contracts/schemas",
      `timenarratives-${name}.schema.json`,
    ),
  );
  return new Ajv2020({ allErrors: true, strict: true }).compile(schema);
}

function firstRow(value: JsonObject, key: string): JsonObject {
  const rows = value[key];
  if (!Array.isArray(rows) || typeof rows[0] !== "object" || rows[0] === null) {
    throw new Error(`${key} fixture must contain an object`);
  }
  return rows[0] as JsonObject;
}

describe("TimeNarratives paragraph schema", () => {
  let journey: TimeNarrativesJourney;

  beforeAll(() => {
    journey = buildTimeNarrativesJourney(repoRoot);
  });

  afterAll(() => {
    journey.cleanup();
  });

  it.each([
    ["map", "clauses"],
    ["deliverable", "narratives"],
  ] as const)("accepts the exact %s two-paragraph ceiling", (name, key) => {
    const value = structuredClone(journey.values[name]);
    firstRow(value, key).text = `a${"😀".repeat(599)}\n\n${"b".repeat(600)}`;
    expect(validator(name)(value)).toBe(true);
  });

  it.each([
    "First.\nSecond.",
    "First.\n\nSecond.\n\nThird.",
    " Leading whitespace.",
    "Trailing whitespace. ",
    "First.\u0085Second.",
    "First.\u2028Second.",
    "First.\u2029Second.",
    `${"a".repeat(601)}\n\nSupported.`,
    `${"😀".repeat(601)}\n\nSupported.`,
    Array.from({ length: 61 }, () => "Alpha").join(" "),
    "\u0000",
    "\u00a0",
    "\u034f",
    "\u115f",
    "\u1160",
    "\u17b4",
    "\u17b5",
    "\u180b",
    "A\u180fB",
    "\u200b",
    "\u2060",
    "A\u2065B",
    "\u3164",
    "\ufe0f",
    "\ufeffLeading",
    "\uffa0",
    "A\ufff0B",
    "\ud800",
    "A\u{110bd}B",
    "A\u{110cd}B",
    "A\u{13430}B",
    "A\u{1bca0}B",
    "A\u{1d173}B",
    "A\u{e0000}B",
    "A\u{e0001}B",
    "A\u{e0100}B",
    "A\u{e01f0}B",
    "Double  spacing is not canonical.",
  ])("rejects malformed paragraph text: %j", (text) => {
    for (const [name, key] of [
      ["map", "clauses"],
      ["deliverable", "narratives"],
    ] as const) {
      const value = structuredClone(journey.values[name]);
      firstRow(value, key).text = text;
      expect(validator(name)(value)).toBe(false);
    }
  });
});
