# Multi-agent execution

Use this when a skill has many independent, bounded, verification-heavy
work units. Do not invent a different legal method per host. Vary only
the execution engine.

## Three tiers

### 1. Preferred — deterministic scheduler

One work unit per worker, one prompt template, one schema, bounded
concurrency, persisted intermediates, completeness check against a
manifest, retry failures only, compile at the end.

The parent agent invokes **one** script or workflow. The scheduler, not
the parent conversation, performs the N model calls.

This is the gold standard because it does not depend on the parent
context window remaining uncompacted.

Where a host already provides this (Claude Code Dynamic Workflows:
`pipeline()`, structured schemas, bounded concurrency), use that runtime.
Do not wrap it in an SDK.

### 2. Second — bundled programmatic orchestrator

A script can always orchestrate files. It can orchestrate **model calls**
only when the host exposes a callable runtime and credentials.

That is true for some local Codex setups. It is **not** a documented
contract for a hosted workspace (no install-time pip/npm, no documented handoff
of the parent chat's entitlement into `openai-codex`). Treat Work as
unable to run nested SDK fan-out until an empirical test says otherwise.

Do not make nested SDKs the MVP path.

### 3. Fallback — native workers, file-backed

Native subagents are the graceful-degradation path, not the preferred
path. Naive delegation is too loose: the parent must not run a 500-step
conversational protocol that stores every analysis in its own context.

Make the fallback a **file-backed map/reduce**:

1. Write `manifest.json` and batch input files.
2. Each worker writes `results/batch-NNN.json` and returns
   `DONE batch-NNN valid/expected`.
3. A deterministic validator diffs expected unit IDs against received
   schema-valid IDs and retries only the misses.
4. An aggregation step reads the files.

The parent sees completion lines, not tens of thousands of analysis
tokens. That survives compaction.

Use fewer, larger workers on this rung (order of 8–16 workers, each still
emitting **one result object per work unit**). Do not switch to "read
these six pages and tell me what looks wrong."

## Degradation ladder (encode this in the skill)

1. Provider-native deterministic workflow, if bundled and available.
2. Bundled programmatic orchestrator, if the runtime is actually present.
3. If a dependency is missing and the host can install it with the ordinary
   approval UI, offer that. Default for a nontechnical lawyer is continue,
   not "here are terminal instructions."
4. Structured native-worker fallback, file-backed.
5. Sequential, same schema, same validator, same report.

The default lawyer experience is: **it works**. Perhaps more slowly.

## What the remote MCP server must not do (MVP)

MCP cannot command the host to spawn six ChatGPT workers. The server does
not own the host scheduler. If the server calls a model API itself, we
are in billing/BYOK territory — a different product.

Deterministic MCP helpers (split, validate, merge, resume) are optional
and should not be the default for confidential documents.

## Isolation is the point

Independent work units are not gratuitous multi-agent complexity. Forced
attention per unit is how the method spends tokens on every assertion
instead of hoping a single long context notices everything. Do not
sacrifice that because a host only exposes a generic worker API. Degrade
the scheduler; keep the unit and the schema.

