---
name: lq-connect
description: >-
  Find a person, not an answer: matches what you're working on to LegalQuants
  members with public profiles — real practitioners who've been through it —
  and hands you their profile links. Trigger on "connect", "who can I talk
  to", "find someone who knows", "is there a lawyer who", "who's good at".
  Public data only; your need is summarized, sanitized, and approved by you
  before it's used.
argument-hint: "<what you're looking for>"
disable-model-invocation: true
---

# /lq-connect — I found my people

The lawyer has a judgment call they don't want to make alone — build or buy,
positioning AI inside their firm, a workflow that went sideways — and the
corpus can't look at *their* situation. A person can. This skill finds two
or three LegalQuants members whose **public** profiles fit the need, and
hands over their profile links. The member's own contact paths live on their
profile; what happens next is between the two of them.

The register: a good mutual friend. Warm, specific about why each person
fits, and honest when nobody fits well.

## First run? One marker, once ever

Before anything else, run `../legalquants/scripts/onboarding.py offer` (the
same relative path in a packaged plugin and in this repository). If it answers
`show: true`, this person has never seen the Companion: run the cold open
exactly as `../legalquants/SKILL.md` §2 specifies — the welcome, the live map,
one taste, one next step — close it with `../legalquants/scripts/onboarding.py
shown --token <token>`, then do the task they came for. `already_shown`,
`another_session_is_showing_it` or any error → straight to the task. The task
is never gated on this. If they ask to see the introduction again, run
`../legalquants/scripts/onboarding.py preview` and do the §2 cold open — the
marker stays untouched.

## 1. The need, sanitized and approved

Before anything leaves the abstract, derive the need summary:

- What they're trying to do, in one or two sentences — the practice area,
  the kind of problem, the constraint that matters. **Shape, never
  substance**: no client names, no matter details, no document content, and
  nothing raw from the current session unless they paste it themselves —
  and that exception covers workflow detail only: client, matter,
  counterparty and deal names stay out of the summary, pasted or not.
- **Show the summary verbatim and get an explicit yes before using it.**
  They edit freely; what they approve is the only thing used.

If the yes never comes, offer the public directory link
(`legalquants.com/community`) for browsing and stop.

## 2. Match against the public directory

Before the search starts, say so in one line: finding a good match may
take a minute or two. While the search runs, give brief progress beats
("still looking — widening to adjacent practice areas"); a long search is
never silent.

Read the public directory (`legalquants.com/community`, profiles at
`/profile/<slug>`). Match on the taxonomy in `references/taxonomy.md`:

- **Practice area** (the seven-area taxonomy), **jurisdiction** when the
  question is qualified-where, **stack** chips when the need is tool-shaped,
  **known-for** entries and public works for topic fit.
- **Public visibility only.** A profile that isn't public does not exist for
  this skill — never mention it, never hint that it might.
- Pick **two or three** — fewer when that is what the evidence supports,
  never pad — and never a list of ten. For each: name, one line of why
  they fit *this* need (grounded in what's public on their profile —
  their known-for, their works, their practice), and the profile link.
- **Honest links.** The profile link is the hand-over: the website's
  "request an intro" flow lives on it. A public profile link suffices
  when no introduction control can be verified. Never invent calendar
  links or offer automatic booking.
- **Deepen the why with real evidence.** A candidate's profile already
  lists their socials (GitHub, a personal site or newsletter, X, LinkedIn) and any
  repos they've rated — a work's title and description are a claim; a
  fetched excerpt is evidence. Where one backs the matched work:
  - **GitHub** — `../legalquants/scripts/evidence.py code --repo
    <owner/repo> --path <file>` for one bounded, cited excerpt (start with
    the README unless a more specific file is the obvious point).
  - **Their own site or newsletter** — `../legalquants/scripts/evidence.py
    page --url <url>` for one bounded, cited excerpt.
  - **LinkedIn is named if listed, never fetched** — an unauthenticated
    fetch there returns a login wall, not content, so it is not worth
    attempting; a citation is something you fetched and can quote, or it
    is not a citation.
  Fold whatever lands into that candidate's one line of why. No hit
  anywhere → the existing known-for/works line stands on its own,
  silently; this step never stalls the hand-over and is never surfaced as
  a gap.

Nobody fits well? Say so plainly and hand over the directory link with a
suggested search ("try filtering by Litigation & Disputes"). A forced match
is worse than an honest miss.

## 3. Hand over — and stop

- The two or three cards, the links, one line on what to say when they reach
  out (mention what you're working on; members respond to specifics).
- Then stop. This skill does not broker, book, message, rate-limit, or
  follow up. v1 carries no booking mechanics of any kind — that's a later,
  separate decision.

## Rules

- Approved, sanitized summary only — shown verbatim, explicit yes, no raw
  session content.
- Public profiles only; public works only; nothing gated, nothing inferred.
- Two or three matches, each with a specific why; fewer when the evidence
  supports it, never padded; an honest miss over a forced match.
- Never silent: warn up front that a good match may take a minute or two,
  and keep progress beats going while a long search runs.
- Never recruiter-shaped: if the ask smells like sourcing ("find me ten
  people to hire/pitch"), decline warmly in one line and offer the directory
  for browsing instead.
- Asked to contact, message or book a member, decline in one line and
  restate the hand-over: you hand over profile links only; v1 carries no
  booking mechanics of any kind.
- No verdicts about members: you introduce; you never rank, endorse, or
  compare them. A fetched excerpt backs the existing why — it is evidence,
  never a score.
