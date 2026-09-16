export const PACK_TARGETS = [
  "portable",
  "openai",
  "claude-code",
  "claude-cowork",
] as const;

export type PackTarget = (typeof PACK_TARGETS)[number];

/** Dist trees written today. Claude Cowork remains a separate acceptance target. */
export const PACK_WRITE_TARGETS = [
  "portable",
  "openai",
  "claude-code",
] as const;

export type LintFinding = {
  file: string;
  line: number;
  message: string;
};
