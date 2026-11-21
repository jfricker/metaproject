# Branch at write-intent — cycle-per-worktree for concurrent agents

**Captured**: 2026-09-15, during the `metaproject doctor` cycle (research for a future
cycle in the SDLC-skills repo).
**Status**: backlog — not specced, not scheduled.
**Target repo**: `~/Projects/SDLC-skills` (skill text), with workflow implications for
every repo using the sdlc-skills plugin.

## Goal

Allow multiple agents and operators to work in one repo concurrently using the sdlc
skills. Today the cycle is single-threaded: the root `intent.md`/`spec.md`/`design.md`/
`plan.md`/`STATE.md` set means only one cycle can be in flight per repo, because
`write-intent` requires a blank root `intent.md`.

## Current behavior (verified 2026-09-15)

- The sdlc-skills docs never prescribe *when* a worktree is created. Only `wrapup`
  mentions worktrees — step 8 removes any under `.claude/worktrees/` at cycle end.
  `implement-plan`/`execute-tests` say only that code lands on a "working branch".
- De facto convention in MetaProject: docs stages (write-intent → generate-plan) commit
  root docs straight to main; `implement-plan` creates the `.claude/worktrees/<slug>`
  worktree; wrapup merges it (no-ff, e.g. `d905994`) and removes it.

## Proposed change

Branch **at write-intent**: each cycle starts by creating branch `cycle/<slug>` checked
out in its own worktree, and the entire cycle (docs through wrapup) runs there.

Key refinement: the concurrency primitive is branch **+ worktree** (separate directory),
not branch alone — a branch without its own working directory still shares one root
`intent.md`, so agents still collide.

### Why the skills tolerate this unchanged

- Every stage skill operates on repo-root docs relative to the session's cwd. In a
  worktree, "repo root" is the worktree root: blank-rule checks, Status gates, and
  `metaproject backfill` behave identically.
- With one worktree per cycle, each agent's coordination surface is its own worktree;
  main only receives finished merges.

### Resulting shape

- `write-intent`: create `cycle/<slug>` branch + worktree first, then draft there.
- `implement-plan`: no longer creates a second worktree — the cycle worktree *is* the
  working branch.
- `wrapup`: archives/resets inside the worktree, merges to main (no-ff), removes the
  cycle worktree (replaces current step 8).
- All other skills: unchanged.

## Design work a future spec must cover (merge seams)

1. **Root-doc rename/rename conflicts.** Two cycles both `git mv intent.md →
   docs/archive/<different-slug>/`. Git reports rename/rename; resolution is mechanical
   (keep both archives, take the blank reset). Either serialize wrapup merges or
   rebase-then-re-resolve for the second cycle to land.
2. **Append-only long-lived docs.** `ARCHITECTURE.md` cycle index and
   `docs/DESIGN-INVARIANTS.md`/`docs/VERIFIED-FACTS.md` get appended on every branch —
   same-region text conflicts. A fixed insertion convention (always append at end, dated
   headings) keeps resolutions trivial but won't auto-merge.
3. **Cross-cycle staleness.** A slow cycle merges against a moved main; wrapup's
   `ARCHITECTURE.md` diagram edits are the likeliest semantic conflict.
4. **Skill text edits** (small): write-intent gains branch+worktree creation; wrapup
   step 8 becomes merge-and-remove; implement-plan drops worktree creation.

## Caveat noted at capture time

The `metaproject doctor` cycle ran single-threaded on main (docs-on-main convention) —
finish such in-flight cycles before adopting branch-at-write-intent.
