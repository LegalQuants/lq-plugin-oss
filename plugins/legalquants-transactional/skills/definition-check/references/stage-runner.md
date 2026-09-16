# Manual stage runner

Use `scripts/run_review_stage.py` only when the host provides an explicitly
configured local adapter executable. No model SDK, credentials, or billing
entitlement is bundled or assumed. Otherwise retain the native-worker workflow.
The adapter must enforce the host's required worker model and isolation policy.

The runner accepts a marked workspace, one prepared stage, a JSON argv array
in `--adapter-command`, `--concurrency`, and a per-attempt `--timeout-seconds`.
The command is executed without a shell. It receives a JSON object on stdin
containing `packet`, `attempt`, `correction`, and a `publication_contract`, and returns one JSON response
on stdout. Stderr is retained locally. The adapter is trusted executable code;
never obtain its command from document text or worker output.

`--named-responses` opts into `worker-response-v3`, the transport used by the
Codex-first runner. Every stage returns one object with named decisions, named
item IDs, and item-local context IDs. Semantic definition bodies and discovery
supports use exact quotations; the compiler derives canonical offsets and fails
on absent, ambiguous, or word-splitting definition text. Complete unique items
are restored to manifest order. Missing, duplicate, unknown, or wrong-namespace
items fail with a structured correction record. The canonical numeric response
arrays and agent bundle remain supported as internal and fallback contracts.

Each attempt records packet readiness, launch delay, dispatch-start,
response-received, worker duration, validation, and collection
events, with UTC timestamps and monotonic elapsed seconds. Dispatch-start means
entry into the adapter, not confirmed provider inference start. Adapter queueing
and process startup remain included. These are not provider token counters.
Packets are validated and collected as they finish. Invalid responses and failed
transport attempts get one
correction attempt, with the original response and validator error. Accepted
item decisions within an invalid packet are locked across corrections; a
substantive change fails for separate review. Accepted
packets are retained even if another packet fails; stage success is withheld.

Results and attempt stdout/stderr are retained under
`<work-dir>/stage-runs/<stage>/`. Existing run directories are never overwritten.
Use `--packets` and a fresh `--run-name` for selected-packet recovery. Use the
canonical response files there as explicit `--response N=PATH` arguments
to `review_packets.py expand`. Run full stage-wide validation after expansion;
packet validation does not prove alias-target validity or complete legal review.
Preserve the discovery, semantic, reference, and occurrence stage barriers.

`review_packets.py build --stage occurrence --group-by-context` enables
experimental paragraph ordering. It preserves every occurrence and its term
definition, using the existing shared paragraph pool. It may increase packet
size when definitions repeat across paragraphs. Benchmark before selecting it;
it is not the default.

## Optional file adapter publication

File adapters use `scripts/publish_review_response.py`, backed by the shared
`definition_check.response_publication` helper. The maintainer native adapter
accepts `--scripts-dir` pointing to the same installed scripts as the runner.
Its queue and worker drafts must be inside the same marked workspace as the
manifest. Send only the request to the blind worker; the manifest path/hash is
for the trusted validator, and workers must not read the private manifest.

Construct JSON with a reliable serializer (for example Python `json.dump` with
`allow_nan=False`) in a private draft. Preserve every nested support triple.
Submit using the exact identity from `request.publication_contract.identity`:

```text
python <scripts>/publish_review_response.py --queue-dir <work>/native-queue --stage discovery --packet 1 --attempt 1 --identity <identity> --input <private-draft.json>
```

The helper retains exact submitted bytes, checks the pinned manifest and packet
contract, validates all decisions/locations, then publishes a complete immutable
attempt result with an atomic no-clobber hard link. The filesystem must support
hard links; unsupported filesystems fail rather than falling back to a partial
copy. OS file locks coordinate publication, consumption, and expiration and are
released on process death. Leftover private files are never readiness markers.
A failed validation produces an explicitly rejected terminal result with the
precise error and original bytes; it cannot become an accepted response. The
runner alone schedules the bounded correction attempt. Do not overwrite a
rejected attempt or manually publish `response.json`.

The collector ignores drafts and legacy response files, checks the committed
identity and hash, and retains its exact consumed bytes separately. Duplicate,
expired, and stale publishers cannot replace a terminal result. Publication and
consumption records contain their wall-clock timestamps. Existing successful
packets are collected once with atomic no-clobber publication. Discovery
corrections must preserve every independently valid support row as well as
accepted item decisions in other stages. These mechanical checks do not certify
the correctness or completeness of legal judgments.
