import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { findRepoRoot } from "../src/repo.js";
import {
  buildTimeNarrativesJourney,
  type JsonObject,
  type SchemaName,
  type TimeNarrativesJourney,
} from "./helpers/timenarratives-journey.js";
import { isValidRfc3339 } from "./helpers/timenarratives-rfc3339.js";

const require = createRequire(import.meta.url);

type Validator = ((value: unknown) => boolean) & {
  errors?: Array<{ instancePath: string; message?: string }> | null;
};
type AjvConstructor = new (options: {
  allErrors: boolean;
  strict: boolean;
}) => {
  addFormat: (
    name: string,
    format: { type: "string"; validate: (value: string) => boolean },
  ) => void;
  compile: (schema: object) => Validator;
};
type InvalidCase = {
  name: string;
  schema: SchemaName;
  mutate: (value: JsonObject) => void;
};

const Ajv2020 = require("ajv/dist/2020") as AjvConstructor;
const SCHEMA_NAMES: SchemaName[] = [
  "request",
  "packet",
  "map",
  "confirmation",
  "deliverable",
];

function readObject(path: string): JsonObject {
  const parsed: unknown = JSON.parse(readFileSync(path, "utf8"));
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error(`${path} must contain a JSON object`);
  }
  return parsed as JsonObject;
}

function objectValue(value: unknown): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("fixture path must resolve to an object");
  }
  return value as JsonObject;
}

function objectAt(value: JsonObject, key: string): JsonObject {
  return objectValue(value[key]);
}

function firstObjectAt(value: JsonObject, key: string): JsonObject {
  const rows = value[key];
  if (!Array.isArray(rows) || rows.length === 0) {
    throw new Error(`fixture ${key} must contain an object`);
  }
  return objectValue(rows[0]);
}

function validators(repoRoot: string): Record<SchemaName, Validator> {
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  ajv.addFormat("date-time", {
    type: "string",
    validate: isValidRfc3339,
  });
  return Object.fromEntries(
    SCHEMA_NAMES.map((name) => [
      name,
      ajv.compile(
        readObject(
          join(
            repoRoot,
            "packages/contracts/schemas",
            `timenarratives-${name}.schema.json`,
          ),
        ),
      ),
    ]),
  ) as Record<SchemaName, Validator>;
}

const INVALID_CASES: InvalidCase[] = [
  ...(["request", "packet", "map", "confirmation", "deliverable"] as const).map(
    (schema) => ({
      name: `${schema} rejects an unknown top-level field`,
      schema,
      mutate: (value: JsonObject) => {
        value.unexpected = true;
      },
    }),
  ),
  {
    name: "request rejects duplicate aliases",
    schema: "request",
    mutate: (value) => {
      objectAt(value, "actor").aliases = ["same", "same"];
    },
  },
  {
    name: "request rejects an absolute selected path",
    schema: "request",
    mutate: (value) => {
      value.selections = [{ kind: "file", path: "/private/source.txt" }];
    },
  },
  {
    name: "request selection oneOf rejects mixed file and note fields",
    schema: "request",
    mutate: (value) => {
      firstObjectAt(value, "selections").path = "mixed.txt";
    },
  },
  {
    name: "request rejects an impossible calendar date",
    schema: "request",
    mutate: (value) => {
      objectAt(value, "filters").asOf = "2026-02-30T12:00:00Z";
    },
  },
  {
    name: "request rejects a false legacy authority flag",
    schema: "request",
    mutate: (value) => {
      value.authorityConfirmed = false;
    },
  },
  {
    name: "packet requires actor aliases",
    schema: "packet",
    mutate: (value) => {
      delete objectAt(value, "actor").aliases;
    },
  },
  {
    name: "packet rejects duplicate aliases",
    schema: "packet",
    mutate: (value) => {
      objectAt(value, "matter").aliases = ["same", "same"];
    },
  },
  {
    name: "packet rejects an invalid as-of timestamp",
    schema: "packet",
    mutate: (value) => {
      objectAt(value, "filters").asOf = "not-a-timestamp";
    },
  },
  {
    name: "packet rejects a negative container byte length",
    schema: "packet",
    mutate: (value) => {
      firstObjectAt(value, "containers").byteLength = -1;
    },
  },
  {
    name: "packet rejects boolean unit byte offsets",
    schema: "packet",
    mutate: (value) => {
      firstObjectAt(value, "units").utf8Start = true;
    },
  },
  {
    name: "packet roots remain closed objects",
    schema: "packet",
    mutate: (value) => {
      firstObjectAt(value, "roots").absolutePath = "C:/private/source.txt";
    },
  },
  {
    name: "map requires unit assessments",
    schema: "map",
    mutate: (value) => {
      delete value.unitAssessment;
    },
  },
  {
    name: "map assessment oneOf rejects a mismatched reason",
    schema: "map",
    mutate: (value) => {
      firstObjectAt(value, "unitAssessment").reason = "not_relevant";
    },
  },
  {
    name: "map rejects boolean atom byte offsets",
    schema: "map",
    mutate: (value) => {
      firstObjectAt(value, "atoms").startByte = true;
    },
  },
  {
    name: "map rejects duplicate atom components",
    schema: "map",
    mutate: (value) => {
      firstObjectAt(value, "atoms").components = ["action", "action"];
    },
  },
  {
    name: "map enforces authored-text bounds",
    schema: "map",
    mutate: (value) => {
      firstObjectAt(value, "events").action = "x".repeat(301);
    },
  },
  {
    name: "map rejects control characters in external actor IDs",
    schema: "map",
    mutate: (value) => {
      firstObjectAt(value, "events").performedByActorId = "ACTOR\n1";
    },
  },
  {
    name: "confirmation requires the confirmed decision",
    schema: "confirmation",
    mutate: (value) => {
      value.decision = "rejected";
    },
  },
  {
    name: "confirmation rejects a malformed token",
    schema: "confirmation",
    mutate: (value) => {
      value.confirmationToken = "TN-not-a-token";
    },
  },
  {
    name: "confirmation rejects a noncanonical digest",
    schema: "confirmation",
    mutate: (value) => {
      value.packetDigest = "A".repeat(64);
    },
  },
  {
    name: "deliverable receipt remains a closed object",
    schema: "deliverable",
    mutate: (value) => {
      objectAt(value, "receipt").diagnostic = "not shipped";
    },
  },
  {
    name: "deliverable rejects negative receipt counts",
    schema: "deliverable",
    mutate: (value) => {
      objectAt(objectAt(value, "receipt"), "counts").units = -1;
    },
  },
  {
    name: "deliverable rejects an unknown status",
    schema: "deliverable",
    mutate: (value) => {
      value.status = "complete";
    },
  },
  {
    name: "deliverable narratives require unique event IDs",
    schema: "deliverable",
    mutate: (value) => {
      const narrative = firstObjectAt(value, "narratives");
      const eventIds = narrative.eventIds;
      if (!Array.isArray(eventIds) || eventIds.length === 0) {
        throw new Error("fixture narrative must contain an event ID");
      }
      narrative.eventIds = [eventIds[0], eventIds[0]];
    },
  },
  {
    name: "deliverable requires its receipt",
    schema: "deliverable",
    mutate: (value) => {
      delete value.receipt;
    },
  },
];

describe("TimeNarratives JSON Schema corpus", () => {
  const repoRoot = findRepoRoot();
  const compiled = validators(repoRoot);
  let journey: TimeNarrativesJourney;

  beforeAll(() => {
    journey = buildTimeNarrativesJourney(repoRoot);
  });

  afterAll(() => {
    journey.cleanup();
  });

  it.each(SCHEMA_NAMES)("%s accepts the real journey artifact", (schema) => {
    const validate = compiled[schema];
    const value = journey.values[schema];

    expect(validate(value), JSON.stringify(validate.errors)).toBe(true);
  });

  it.each(INVALID_CASES)("rejects $name", ({ schema, mutate }) => {
    const validate = compiled[schema];
    const value = structuredClone(journey.values[schema]);
    mutate(value);

    expect(validate(value)).toBe(false);
    expect(validate.errors?.length).toBeGreaterThan(0);
  });
});
