# The generic bottleneck list (handwritten)

The ways AI-assisted legal sessions go wrong, distilled from practitioner
experience into a private diagnostic toolbox for live mode. Generic by
design: no resident, cohort, firm, or matter is identifiable in anything
here, and that is a hard rule — this list informs the diagnosis, it never
carries anyone's story. Never recite it to the user; they hear their own
situation, not a taxonomy.

## 1. The loop

The session circles: same edit, same apology, same edit. What failed: the
model lost the thread and nobody noticed for ten turns. The move: stop, restate
the task in one sentence with the one source that matters, restart clean.
Loops are not persistence problems; they are context problems.

## 2. Unchecked trust

A plausible answer walked straight into the work product — a clause number, a
citation, a date — and the first check happened after someone else read it.
The move: the part that carries the weight gets verified first, always,
before anything downstream. Trust is fine; sequence is the fix.

## 3. Hand-work a tool does

Twenty minutes of manual find-and-replace, renaming, or cross-checking that
an installed skill does in one run. The move: run the catalog script and name
the skill that does it — but only when the session actually earned the
recommendation.

## 4. Context starvation

The model was asked to judge against something it was never shown: "is this
consistent with our position" with no position supplied; "check this cite"
with no source given. It then guessed, confidently. The move: supply the
source, or narrow the question to what the model can actually see. Guessing
is a feeding problem.

## 5. Tool mismatch

A redline question asked of a chat prompt; a corpus-scale review attempted in
a single message; a formatting task sent to a reasoning model. The move:
match the task to the tool — and when the tool doesn't exist yet, say so
rather than forcing the session to fake it.

## 6. The structural wall

The same failure three sessions running. Not a prompting problem: a missing
tool, a firm constraint, a gap in the user's setup. The move: stop patching,
name the wall plainly, and say that some walls are worth a mentor's eyes —
once, declinable.
