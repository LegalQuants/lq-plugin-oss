import { describe, expect, it } from "vitest";
import { isValidRfc3339 } from "./helpers/timenarratives-rfc3339.js";

describe("TimeNarratives RFC3339 calendar parity", () => {
  it.each([
    "not-a-timestamp",
    "0000-01-01T00:00:00Z",
    "2024-00-01T00:00:00Z",
    "2024-13-01T00:00:00Z",
    "2024-01-00T00:00:00Z",
    "2026-02-30T12:00:00Z",
    "2025-02-29T12:00:00+01:00",
    "1900-02-29T12:00:00Z",
    "2024-02-29T24:00:00Z",
    "2024-02-29T23:60:00Z",
    "2024-02-29T23:59:60Z",
    "2024-02-29T23:59:59+24:00",
    "2024-02-29T23:59:59+00:60",
  ])("rejects Python-invalid calendar value %s", (value) => {
    expect(isValidRfc3339(value)).toBe(false);
  });

  it.each([
    "0001-01-01T00:00:00Z",
    "2000-02-29T23:59:59Z",
    "2024-02-29T23:59:59.123456+05:30",
    "2024-02-29T23:59:59.123456789-00:00",
    "2024-12-31T23:59:59+23:59",
  ])("accepts Python-valid calendar value %s", (value) => {
    expect(isValidRfc3339(value)).toBe(true);
  });
});
