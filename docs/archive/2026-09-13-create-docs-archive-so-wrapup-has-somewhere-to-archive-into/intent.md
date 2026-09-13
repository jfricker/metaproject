# Create docs/archive/ so wrapup has somewhere to archive into

**Author**: John Fricker.
**Last updated**: 2026-09-13.
**Status**: Approved (John Fricker).

## Problem
`wrapup` (`.claude/skills/wrapup/SKILL.md`) moves each cycle's `intent.md`, `spec.md`,
`design.md`, `plan.md`, and `HANDOFF.md` into `docs/archive/YYYY-MM-DD-<slug>/` — but
`docs/archive/` doesn't exist in the repo yet (only `docs/.gitkeep` is present). The
first real `wrapup` run will hit a missing-directory error instead of archiving cleanly.

## Proposed outcome
`docs/archive/` exists and is tracked in git (so `wrapup` can `git mv` into a
subdirectory of it without first having to create the parent), and `wrapup`'s own
SKILL.md is explicit that the directory is expected to pre-exist rather than assuming
`git mv`/`mkdir -p` will paper over it.

## Affected users and systems
- The `wrapup` skill (`.claude/skills/wrapup/SKILL.md`) — its Process step 3 (move
  cycle docs into the archive).
- Anyone running the write-intent → ... → wrapup cycle in this repo — this is the first
  time any cycle would actually reach `wrapup`.

## Scope

### In Scope (v1)
- Create `docs/archive/` with a `.gitkeep` (or equivalent) so git tracks the empty
  directory.
- Confirm/clarify in `wrapup`'s SKILL.md that the directory is a precondition, not
  something the skill creates on the fly.

### Out of Scope (v1)
- Running an actual `wrapup` cycle against this repo's own `intent.md`/`STATE.md` — this
  intent is only about the missing directory, not closing the meta-cycle that produced
  the skills themselves.
- Any other gaps in the skill set (e.g. the missing `Makefile` already noted in
  `STATE.md`'s Open items).

## Resolved decisions
- Track the directory with a `.gitkeep` placeholder, matching the existing convention
  used for `docs/.gitkeep`.

## Constraints
- No source code or tests are affected — this is a repo-scaffolding fix, consistent
  with `docs`/`AGENTS.md`'s artifact conventions.

## Open questions
- None — this is a small, self-contained test cycle.
