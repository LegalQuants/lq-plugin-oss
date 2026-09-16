# The matching taxonomy (from the legalquants.com data model, verified 2026-09-05)

## Practice areas (the seven on works + directory filters)

Contract Review & Drafting · Compliance & Regulatory · Litigation &
Disputes · Practice Infrastructure & Tooling · Legal Research · Corporate &
Transactional · IP & Patents

Map the user's words to the nearest area; when their need spans two, pick
the one the *question* is about, not the one their practice is in.

## Jurisdiction

Free text on profiles ("New York; England & Wales") — the hiring manager's
first question is qualified-where, not sitting-where. Use when the need is
jurisdiction-shaped; ignore otherwise.

## Stack chips (builder identity, ≤8 per profile)

What members actually build with. Use when the need is tool-shaped ("someone
who ships Next.js viewers", "has wired up docx pipelines"). Match chips
literally; don't infer equivalents.

## Known-for + public works

`known_for` entries ({label, value}) are the member's own "discusses
mainly…" lines — the best topic signal on the profile. Public works
(title, description, practice area, platform, chips) are proof: prefer a
member whose public work *is* the thing the user is trying to do over one
who merely shares a practice area.

## Socials and rated repos — evidence, not a matching signal

A profile's `socials` (GitHub, a personal site or newsletter, X, LinkedIn) and any
`ratedRepos` never decide *who* matches — the taxonomy above does that.
Once a candidate is picked, they back the "why" with a fetched excerpt
instead of a paraphrased title. LinkedIn is named if listed, never fetched
(see `SKILL.md` §2).

## What's deliberately not used

Firm and level (each has its own visibility toggle, default gated — treat as
invisible unless explicitly public), cohort, roles, the editorial register.
Public means what the member set to public, full stop.
