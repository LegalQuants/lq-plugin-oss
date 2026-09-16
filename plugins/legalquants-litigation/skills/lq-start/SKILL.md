---
name: lq-start
description: >-
  Ask which CODEX for Legal skill fits the work in front of you. A map of the
  installed skills by situation, with one pick and the prompt to type, and a
  line on what the other LegalQuants plugins add. The same door ships in every
  LegalQuants plugin. Type it when you do not know what to type. Not for doing
  legal work, and not a coach.
argument-hint: "[the task in front of you, or your practice]"
disable-model-invocation: true
---

# /lq-start — which skill fits

You will not remember every skill, so ask. Say what is in front of you and get
one pick and the prompt to type. Say what you practise and get the few that
fit. Say nothing and get the map, and the shelf next door.

This door ships in every LegalQuants plugin and reads every one that is
installed, so the copies are the same: whichever the picker offers, pick any.

This verb writes nothing, reads no transcripts, and never opens `~/.lq/`.

## 1. Read the shelf, never remember it

Run `scripts/catalog.py --all-plugins --format json`. It lists every skill
installed across the CODEX for Legal plugins on this machine, read from the
skills' own files, each with the plugin it came from (`plugin`, and
`plugin_name` in plain words). That output is the only list you may name an
installed skill from. Skills come and go between releases; if a name is not
in the output, it is not installed here.

Skill names render in the host's own form. Where skills are picked with a `$`
menu, write `$read-redline`; where they are slash commands, write
`/read-redline`. Pass `--prefix '$'` or `--prefix /` to the catalog to match.

The catalog omits `/lq-start` itself by design: the door is not a
destination, so the list is always one shorter than the shelf. Do not compare
counts. Warn only if the catalog comes back empty, or a skill the map names
for a plugin that is installed is missing from it; then say so in one line,
point at reinstalling that plugin, and still show what the catalog returned.

## 2. Read the map, then split it

Read `references/map.md`. It places every skill in every LegalQuants plugin
by the situation that calls for it, tagged with the group it ships in, and
its header says which plugin carries each group. Split it by the catalog
output:

- Installed entries come from the catalog output. A section appears only when
  at least one of its skills is in the catalog output; an entry appears only
  when its skill is. Keep the map's own words for each entry. It says what the
  skill is for, what it is not for, and which neighbour to use instead. That
  is the routing.
- The rest come from the map, marked not installed. They are named only in
  the "In other LegalQuants plugins" block of §3 and in §5, never offered as
  a pick, and never described beyond their name.

## 3. Nothing given: the map, then the shelf next door

Open with one line that says what is installed here, from the catalog output:
the plugins (`plugin_name`, in plain words) and the count. Then render the
installed map, one entry per line, names in the host's form. No questions.

Then, only when the map has entries that are not installed, one short block
headed "In other LegalQuants plugins". One line per plugin that is not
installed, from the map's header: the plugin's name, what it is for in the
header's own words, and its skills' names, nothing more. Close the block
with one line: "Install that plugin to add these."
When everything in the map is installed, the block is not shown. The block
is last and short: discovery, not description.

Close with one line: "Tell me what you're working on, or what you practise,
and I'll point you at one." When `legalquants` is in the catalog output, add
one more: "New to the Companion? `$legalquants` walks you in."

## 4. A situation given: one pick

Match on the work described, never on the lawyer's level or seniority. Then:

- Name one skill, in two sentences: what it will do with this, and the next
  real thing to run it on. End with the exact prompt to type — the closing
  line below always comes last, after it.
- If two fit, pick the one closest to the task as described and mention the
  other in half a line as "and next".
- If nothing fits, say so and name the closest thing on the shelf. Do not
  invent a skill and do not stretch one.

## 4a. A practice given: the few that fit

"I'm in-house, technology and data" or "M&A, Singapore, private practice" is
a practice, not a task. Answer with the two or three map entries that fit
that practice, each in the map's own words with the prompt to type, and
nothing else from the shelf. Skip any entry the map marks as private practice
only when the lawyer is in-house, and phrase the prompts for an in-house
reader: the business, not the client. Practice is an input for this reply
only; nothing is stored, and nothing about seniority or AI experience is
asked or inferred.

## 5. The pick is not installed here

When the map's entry fits but its skill is missing from the catalog output,
say so in one line and name the plugin the map's header gives for the entry's
tag: "That is `$cite-check`, in LegalQuants Skills for Litigators." Then
stop. Do not offer a substitute from another section unless the lawyer asks.

## Rules

- Installed names only from the catalog output; not-installed names only
  from the map, never offered as a pick. Never recite a skill from memory.
- One pick, not a menu, when a task is given; two or three when a practice
  is given.
- Match on the work or the practice, never on the user's level or seniority.
- Nothing about lessons, levels or the profile. If the lawyer asks how they
  have been working with AI, point at `$lq-reflect` when it is installed, and
  otherwise say the companion plugin has it.
- Asked to do the legal work itself — draft the clause, review the document —
  decline in one line: "I route; I don't do the work." Then name the closest
  skill from the catalog output.

End every reply with this line, unchanged: "CODEX for Legal is a workflow aid,
not legal advice. The judgement stays yours."
