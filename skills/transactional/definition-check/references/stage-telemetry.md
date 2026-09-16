# Stage token and latency telemetry

Use this optional developer workflow when the user requests token usage or
latency for a complete review. Keep it out of lawyer-facing reports. It measures
the host-orchestrated review separately from the local Python phase timings in
`definition-check-debug.json`.

The supervisor is the sole journal writer. Workers receive their neutral review
packets and return ordinary review responses; they must not edit the journal or
invent token counters. Store the journal and summaries in the authorized run
workspace, never in the skill installation.

This instrumentation does not install a model SDK or make model API calls. The
host continues to perform the review using its available model workers.

## Recording the run

Use `scripts/review_telemetry.py --help` and the subcommand help for supported
arguments. Every command takes `--journal <journal.jsonl>` and `--source
<contract.docx>`. The journal is bound to that source's SHA-256.

1. Start a stage immediately before its work begins. Use descriptive, unique
   stage IDs such as `discovery-1`, `semantic-1`, `reference-1`, and `occurrence-1`.
   Also record intake, finalization, retrieval, or orchestration when applicable.
2. Immediately before dispatching a model packet, start an attempt with a unique
   attempt ID, its stage ID, packet ID, and input payload file. Include the actual
   dispatched task text as an additional payload when it was saved separately.
3. End the attempt when its response is received or failure is observed. Include
   the response payload file if available. Record failed attempts as failures;
   retries get new attempt IDs referring to the prior attempt. Do not overwrite
   a failed attempt with a successful retry.
4. Close the stage only after its workers and validation/reconciliation finish.
   If validation requires a replacement response, keep the stage open and record
   the replacement as a new attempt. A rebuilt queue gets a new stage ID.
5. Generate JSON and Markdown summaries. If a run stops early, summarize the
   incomplete journal rather than manufacturing end times or successful stages.

For example, surround a real discovery packet dispatch with these commands
(replace placeholder paths; do not run them as a simulated review):

```text
python <skill-dir>/scripts/review_telemetry.py --journal <run>/review-events.jsonl --source <contract.docx> stage-start --stage discovery --stage-id discovery-1
python <skill-dir>/scripts/review_telemetry.py --journal <run>/review-events.jsonl --source <contract.docx> attempt-start --stage-id discovery-1 --attempt-id discovery-p1-a1 --packet-id 1 --payload <packet.json>
```

After the actual response arrives:

```text
python <skill-dir>/scripts/review_telemetry.py --journal <run>/review-events.jsonl --source <contract.docx> attempt-end --attempt-id discovery-p1-a1 --status completed --payload <response.json>
```

After every required discovery response is validated and expanded:

```text
python <skill-dir>/scripts/review_telemetry.py --journal <run>/review-events.jsonl --source <contract.docx> stage-end --stage-id discovery-1 --status completed
python <skill-dir>/scripts/review_telemetry.py --journal <run>/review-events.jsonl --source <contract.docx> summarize --json-output <run>/review-telemetry.json --markdown-output <run>/review-telemetry.md
```

Use a fresh summary filename for later snapshots. Add `--usage-json <usage.json>`
to `attempt-end` only when actual per-attempt host usage is available. An example
of that file's shape is `{"input_tokens":120,"output_tokens":30,"provenance":
"host response usage","request_id":"request-123"}`; these example numbers are
not evidence and must never be used in a real run.

Use event-time recording around actual work. Explicit `--at` timestamps are only
for trustworthy host event timestamps, not reconstructed guesses. Instrumenting
the supervisor measures dispatch-to-observed-response latency, which includes
host scheduling and response delivery; it is not pure model inference time.
Keep stage boundaries outside Python checker calls that belong to that stage so
stage elapsed time includes local validation and orchestration. Enable
`--debug-telemetry` on every checker invocation and retain each debug JSON in its
own fresh output directory for the detailed local phase breakdown.

## Token evidence

When the host exposes provider-reported usage for an individual attempt, pass
that usage via `--usage-json`. Supply a provenance description and the provider
request ID when available. Report only counters actually exposed for that call;
missing counters remain unknown. Do not use account-wide usage percentages or
cumulative session counts as if they were per-attempt tokens.

- `input_tokens` includes `cached_input_tokens`; do not add cached input twice.
- `output_tokens` includes `reasoning_output_tokens`; do not add reasoning twice.
- Total tokens are input plus output when both are available.
- Partial reporting is labelled partial. Available subtotals are not represented
  as the complete run's usage.
- Payload estimates use character counts divided by four, rounded up. They are
  not provider usage and omit unsaved system context, tool traffic, hidden
  reasoning, cache behavior, and other host overhead. Record input and response
  estimates separately. Never present these estimates as billing tokens.

## Reading the summary

Stage wall time measures elapsed stage duration. Summed attempt time measures
the sum of worker intervals and can exceed stage wall time when calls run in
parallel. Neither should be described as the other. Retries consume real work
and remain included in recorded attempt usage. Repeated stages remain distinct
instead of silently replacing an earlier stage.

A completed telemetry journal does not prove a complete legal review. Validate
discovery receipts, every required semantic/reference/occurrence decision, source
evidence, run status, and final artifacts separately. No model call is needed for
an empty queue: close that stage without fabricating an attempt or token count.
