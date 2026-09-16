# The companion store contract — how saving works

Every companion skill that remembers anything does it through one script:
`../lq-reflect/scripts/profile_store.py` in a packaged plugin,
`../../lq-reflect/scripts/profile_store.py` in this repository.
`~/.lq/` holds the store. `--root DIR` overrides it (tests).

## The one rule

Show the user the exact content first — the short note and any preference to
retain — and continue only on an explicit yes. Silence is not consent. If they
decline, say nothing was saved and continue with their work; declining blocks
nothing. Reading consent and permission to draft are separate from saving.

## Checking the record

`status` answers `{"exists": false}` on a fresh machine — a normal answer, never
an error, and never a traceback. `exists:false` does not mean the person has no
AI experience; it means nothing has been saved here yet. Never tell the user to
wait a week merely to open a profile.

## Saving — the `save` door

Any companion skill may save, including when no store exists yet:

1. Show the exact content. Get an explicit yes.
2. Call `save --confirmed` with the JSON payload on stdin or `--file`:
   ```json
   {
     "operation_id": "reflect-2026-09-06-walkthrough",
     "quoting": "C",
     "events": [
       {"type": "friction", "source": "debrief",
        "lesson": "Walk through a real user action before approving a design.",
        "status": "kept"}
     ]
   }
   ```
3. `quoting` is required only when the save creates the store (A = selected
   quotations, B = sanitized quotations, C = no quotations). Once set it is a
   preference: a save that carries a different posture is refused — confirm a
   change with the user explicitly rather than overwriting it.
4. `operation_id` makes the save idempotent: retrying with the same id appends
   nothing twice. Use it whenever a save might be retried — and never reuse an
   id for different content: a same-id save with different events is reported
   as already saved and appends nothing.
5. `--confirmed` records the caller's preview-and-consent decision. It does not
   authenticate anyone; the skill's conversation is where consent happens.
6. Report the helper's result honestly.

Other verbs: `status` (read counters), `append` (add events to an existing
store), `rebaseline` (append a fluency reading to the level history — the verb
assess uses to record a fluency/archetype update), `render` (regenerate the
profile view), `export --out DIR` (copy the store out), `forget --entry <id>` /
`forget --all --confirm` (remove — explain what dies first). Verbs that need a
store refuse cleanly when none exists.

## What may be saved

Shape, never substance. Event types: `lq_moment`, `friction`, `technique`,
`repetition`, `debrief_run`, `office_hours_run`. Sources: `user`, `debrief`,
`office-hours`, `baseline`. The script runs a coarse mechanical net over
free-text fields (long digit runs, multiple proper-noun phrases) and refuses
suspect content — a floor, not a guarantee. These prose checks are conservative
heuristics with both misses and false positives; never describe them as
guaranteed anonymisation. No client names, matter numbers, or document content,
under any quoting posture.

Moments: a kept `lq_moment` is recorded only after an explicit yes, one
shape-only line (technique + receipt shape, never matter substance), shown
verbatim. A refusal writes nothing.

## Deferred

The amended-plugin proposal's atomic single-file record with regenerated views
and its richer moment taxonomy (`practice_moment` vs `earned_moment`) are a
persistence-format migration — a separate round, the maintainer's call.
