# Create docs/archive/ so wrapup has somewhere to archive into — Spec

**Author**: Claude.
**Derived from**: intent.md (2026-09-13).
**Last updated**: 2026-09-13.
**Status**: Approved (John Fricker).

## Requirements

### Functional

1. `docs/archive/` exists as a git-tracked directory in the repo.
2. The directory is tracked via a `.gitkeep` placeholder file, matching the existing
   convention at `docs/.gitkeep`.
3. `wrapup`'s SKILL.md (Process step 3) is updated to state that `docs/archive/` is a
   precondition it expects to already exist, not something it creates itself
   (`mkdir -p` or otherwise) — so a future run fails loudly and early if the convention
   is ever broken, instead of silently improvising a directory.

### Non-functional

- No behavior change to any other skill or to source code/tests — this is a
  repo-scaffolding-only change, consistent with `intent.md`'s Constraints.

## Acceptance criteria

- [ ] `docs/archive/.gitkeep` exists and `git ls-files docs/archive/` lists it.
- [ ] `git status` shows `docs/archive/` as tracked (not present only on disk).
- [ ] `.claude/skills/wrapup/SKILL.md`'s Process section explicitly names
      `docs/archive/` as a precondition to check for, rather than implying it will be
      created on demand.
- [ ] No other file in the repo is modified.

## Flagged concerns

None. No policy skills (security/compliance/brand/UX) in the available-skills listing
apply to adding an empty, git-tracked directory and a one-line doc clarification.

## Open questions

None.
