---
name: wrapup
description: End-of-cycle archive and reset, run on main after the PR for this cycle has merged. Archives intent.md, spec.md, design.md, plan.md, and HANDOFF.md into docs/archive/, removes worktrees created for the cycle, and resets those docs (plus STATE.md) back to blank templates so main is ready for the next write-intent cycle. Touches only SDLC documents and worktrees — never source code or tests. Final step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# wrapup

Closes the loop: after a cycle's PR has merged to `main`, archive everything the cycle
produced and reset the repo root to a blank slate for the next `write-intent`.

**Scope discipline**: this skill only ever touches SDLC documents (`intent.md`,
`spec.md`, `design.md`, `plan.md`, `HANDOFF.md`, `STATE.md`), the `docs/archive/`
directory, and git worktree bookkeeping. It never edits source code, tests, or opens a
PR — if any of those are still outstanding, the cycle isn't done; send the user back to
`execute-tests`/`implement-plan` instead of running `wrapup`.

## When to use

- The PR for the current cycle has merged and you're on (or returning to) `main`.
- `intent.md` at the repo root shows `Status: Approved` and the work it describes is
  actually done and merged — don't archive an in-flight or abandoned cycle without
  confirming with the user first.

## Inputs

- The current `intent.md`, `spec.md`, `design.md`, `plan.md`, `HANDOFF.md` (if present)
  at the repo root.
- `git worktree list` for any worktrees created during this cycle.

## Process

1. Confirm with the user which cycle is being closed if it's at all ambiguous (more than
   one `intent.md`-shaped thing could be meant, or the merge isn't obviously landed).
2. Derive an archive slug from `intent.md`'s title and today's date:
   `docs/archive/YYYY-MM-DD-<slugified-title>/`.
3. `git mv` (or move + `git add`) each of `intent.md`, `spec.md`, `design.md`, `plan.md`,
   and `HANDOFF.md` (if present) into that archive directory, preserving history.
4. Remove worktrees created for this cycle: for each one listed by `git worktree list`
   under `.claude/worktrees/` that belongs to this cycle, run
   `git worktree remove <path>` (add `--force` only after confirming with the user there's
   nothing uncommitted worth keeping in it).
5. Recreate blank templates at the repo root for `intent.md`, `spec.md`, `design.md`,
   `plan.md`, using the same blank shapes defined in `write-intent`, `generate-spec`,
   `generate-design`, and `generate-plan` respectively (don't invent a divergent shape
   here — reuse those).
6. Reset `STATE.md`'s checklist back to:
   ```markdown
   # <Project> — State

   ## Process
   - [ ] 1. Review intent.md and create spec.md
   - [ ] 2. Create plan.md from spec.md
   - [ ] 3. Implementation and verification

   ## Implementation phases

   ## Design invariants (regression guards)

   ## Open items carried into plan.md

   ## Verified facts (do not re-investigate)
   ```
   Keep the project title line as it already reads; don't rename the project.
7. Commit the archive + reset as its own commit (e.g. `chore: archive <slug> cycle,
   reset SDLC docs`).

## Output artifact

- `docs/archive/YYYY-MM-DD-<slug>/{intent,spec,design,plan}.md` (+ `HANDOFF.md` if it
  existed).
- Root `intent.md`, `spec.md`, `design.md`, `plan.md`, `STATE.md` reset to blank
  templates.
- No worktrees left over from the closed cycle.

## Stop conditions / human gate

- Never run this against an `intent.md` that isn't `Approved` and actually merged —
  check with the user rather than assume.
- Never delete a worktree with uncommitted or unmerged work without explicit
  confirmation.
- If asked to also clean up source code, tests, or open a new PR, that's out of scope
  for `wrapup` — say so and point back to the right earlier-stage skill.
