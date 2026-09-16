# OpenAI Codex worker policy for Definition Check

This is a Codex-specific orchestration policy, not a portable model entitlement. It affects review workers only; it does not change the supervisor's model.

For every discovery, semantic, occurrence, retry, and replacement subagent, explicitly set:

```yaml
model: gpt-5.6-luna
reasoning_effort: medium
fork_turns: none
```

The rendered dispatch packet is the worker's complete task context, so use a context fork that permits explicit model overrides. Do not use a full-history fork when it would inherit the supervisor model or reject the overrides. Do not rely on an inherited default, agent profile, or role default to select the model.

Prefer the packaged Codex-first runner:

```text
python <skill-dir>/scripts/definition_check_review.py <input.docx> --output-dir <new-output-directory> --codex-command-json <argv> --max-workers auto
```

It launches each packet through a fresh `codex exec --ephemeral` process in an isolated temporary working directory, forces read-only sandboxing and the configuration above, writes UTF-8 artifacts while using ASCII-safe command transport, and records process-level timing without copying worker responses into the supervisor conversation. `auto` uses reported host capacity when available and otherwise defaults to four workers. Reference and occurrence workers share that capacity while running in parallel.

If the host cannot apply or confirm both `gpt-5.6-luna` and `medium`, do not silently dispatch that subagent on another configuration. Tell the user what cannot be enforced and offer a sequential run or another explicitly approved fallback.
