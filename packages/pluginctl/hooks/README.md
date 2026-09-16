# Hooks

Codex-only. `openai.json` may contain nothing but the `hooks` key: Codex 0.142
rejects the whole file on any other top-level field, silently, so every hook
in it stops running.

- **SessionStart and UserPromptSubmit → `wiki_hook.py`.** Optional Wiki
  retrieval. Inert until the user explicitly enables it; every manual Wiki
  workflow works without it. Intake is a deliberate Wiki action, so there is
  no after-every-turn continuation.
- **SessionStart (startup only) → `banner.py`.** The CODEX for Legal card:
  a `systemMessage` the host shows, and the same card as `additionalContext`
  for the model. Reads `~/.lq/` if it exists and never writes there. Its
  second line is the plugin's one first move ("Have a markup? $read-redline
  on it."), read from `banner.json`, which `pluginctl pack` writes beside it
  from `first_move` in `plugin.release.yaml`; the line is shown only when
  every skill it names is in the live catalog, and only when this is the sole
  CODEX for Legal plugin installed. Every installed plugin runs this hook, so
  the first to run leaves a marker for the session id in the temp folder and
  the others stand down: one session, one card, counting every plugin.
  Codex sets `CLAUDE_PLUGIN_ROOT` for its plugin hooks, so the banner never
  reads it as a Claude Code signal.
- `wiki_hook.py` exits quietly in a bundle that does not ship the wiki skill
  (the Companion), rather than failing the hook on every start and prompt.
