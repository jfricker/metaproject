# wrapup deletes the merged cycle branch

**Captured**: 2026-09-16, end of the `universe-hard-scoping-and-details-tui` wrapup in
MetaProject (operator had to ask separately about the leftover branch).
**Status**: backlog — not specced, not scheduled.
**Target**: `~/Projects/SDLC-skills` (`skills/wrapup/SKILL.md` step 8 / output artifact).

## Goal

Close out a cycle with nothing left over: when wrapup merges the cycle branch to main
(the "merge to main, then wrapup" path), it should also delete that cycle branch, so the
operator isn't left with a dangling fully-merged branch and a follow-up question at the
end of every cycle.

## Current behavior (verified 2026-09-16)

- `skills/wrapup/SKILL.md` step 8 removes the cycle's **worktrees** only; it says
  nothing about the cycle **branch**.
- After the universe-hard-scoping-and-details-tui wrapup, main had the merge
  (`e80a4a6`) but the branch `universe-details-tui` was left behind; the operator was
  told "say the word if you want it deleted" — manual follow-up for every future cycle
  (earlier cycles left `review-tui-redesign` and `claude/make-command-c9591b` behind
  the same way).
- Safe deletion exists in git: `git branch -d` refuses a branch whose commits are not
  reachable from HEAD.

## Proposed direction

Extend wrapup's step 8 (worktree bookkeeping) into branch-and-worktree bookkeeping:

- On a **merge close-out** (operator chose "merge to main, then wrapup" and the merge
  is confirmed), delete the cycle branch with `git branch -d <branch>` after the
  worktree removal. `-d` (not `-D`) is the safety net: it refuses if the branch is not
  actually merged, which can only mean the close-out wasn't what it claimed.
- On the **"wrap up on branch only"** path, leave the branch untouched — it still
  carries the unmerged cycle.
- Never touch a branch wrapup didn't create/checkout for this cycle (the cycle branch
  is the one the worktree or merge step identified; if wrapup ran entirely on main
  with no cycle branch, there is nothing to delete and the step no-ops).
- Update the skill's **Output artifact** checklist line ("No worktrees left over from
  the closed cycle") to cover the branch too: "No worktrees or cycle branches left
  over from the closed cycle."
- Operator decision (2026-09-16): auto-delete, not a per-cycle prompt — the safe `-d`
  flag is the guard, the operator already confirmed the merge itself.

## Open questions

(none blocking a spec — smallest change is a few sentences in `skills/wrapup/SKILL.md`;
a future cycle may also want to sweep the two pre-existing leftover branches,
`review-tui-redesign` and `claude/make-command-c9591b`, as part of adoption.)
