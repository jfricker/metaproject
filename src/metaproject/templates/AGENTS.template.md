# AGENTS.md

## Dev environment tips
- Makefile is the primary tool for development and testing. Use `make help` to see available targets.

## Testing instructions
- Quality gate before any commit: `<quality gate, e.g. make format && make lint && make test>`.

## Process
This process is based on https://claude.com/blog/the-ai-native-sdlc-playbook with modifications. This document adds to the playbook and merges ideas. It doesn't supersede the playbook unless explicitly stated.

The cycle runs through seven stages, each a Claude Code skill:

1. **write-intent** — brainstorm a raw problem statement into `intent.md`.
2. **generate-spec** — turn an approved `intent.md` into `spec.md` (requirements and
   acceptance criteria).
3. **generate-design** — turn an approved `spec.md` into `design.md` (affected
   components, data flow, alternatives, trade-offs).
4. **generate-plan** — turn approved `spec.md`/`design.md` into `plan.md`
   (implementation steps, files touched, sequencing, risks).
5. **implement-plan** — implement strictly against approved `plan.md`, writing code
   and tests, keeping `STATE.md` updated as each step lands.
6. **execute-tests** — run and confirm the quality gate for the cycle's changes.
7. **wrapup** — archive the cycle and reset the working documents for the next one.

### HANDOFF.md
On-demand: created only when work is interrupted before completion, to capture the
state of the work and anything needed to resume it or hand it off to another agent at
another time.

### STATE.md
A running record of the current cycle. Its `## Process` section is a checklist of the
seven stages above; each stage ticks its own item as it completes. Update it as tasks
are completed.

### intent.md, spec.md, design.md, plan.md
The working documents of one cycle, produced in that order by the stages above and read
by the stages that follow. `wrapup` archives them once the cycle is complete.

### Pull requests are optional
A cycle may land as a PR or be committed straight to the default branch, operator's
choice. `wrapup` asks the operator which happened for the cycle it's closing rather
than assuming either way, and won't archive or reset until the operator confirms the
work is actually complete and committed.

### ARCHITECTURE.md
A long-lived, root-level index that never resets between cycles. `wrapup` updates it at
the end of every cycle: an entry in its cycle index linking to that cycle's archived
`spec.md`/`design.md`, a one-line summary, and (when the cycle changed structure) an
update to its diagram. Over time `ARCHITECTURE.md` becomes the sum of every cycle's
specifications plus the decisions made along the way — read it before `generate-design`
to avoid re-deriving context that's already settled.

### docs/DESIGN-INVARIANTS.md and docs/VERIFIED-FACTS.md
Long-lived, append-only companions to `STATE.md`'s "Design invariants (regression
guards)" and "Verified facts (do not re-investigate)" sections. `STATE.md` itself resets
to blank at the end of every cycle (`wrapup`), so before it does, `wrapup` appends
whatever those two sections hold — dated and linked to the cycle's archive — onto these
two files instead of letting the knowledge disappear. Read them at the start of
`generate-spec`/`generate-design`/`generate-plan` so a fact verified in one cycle
doesn't get re-investigated in the next.

### STATE.md's "Open items carried into plan.md"
Before `wrapup` resets `STATE.md`, it resolves this section with the operator first —
for each item, showing its own assessment of why the item is still open, then asking
the operator to discard it, carry it forward into the next `intent.md`'s Open
questions, or send the cycle back to `implement-plan` because it isn't actually
finished. A single "return to implement-plan" halts the whole wrapup before anything is
archived or reset.

### .metaproject.json and `metaproject backfill`
This project's governance and cycle documents are scaffolded and kept in sync by the
`metaproject` CLI from its central template store, identified by `.metaproject.json`
at the project root. If a document a skill needs is missing (a
fresh `design.md`, a `HANDOFF.md` on interruption), run `metaproject backfill <file>`
to create it from the template store rather than writing it from scratch — it never
overwrites an existing file.

### Archive layout
`wrapup` moves a completed cycle's `intent.md`, `spec.md`, `design.md`, `plan.md`,
`STATE.md` and (if present) `HANDOFF.md` into `docs/archive/YYYY-MM-DD-<slug>/`, after
appending `STATE.md`'s Design invariants and Verified facts to the long-lived docs
above.
