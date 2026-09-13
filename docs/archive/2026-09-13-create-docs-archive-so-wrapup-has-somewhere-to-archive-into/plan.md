# Create docs/archive/ so wrapup has somewhere to archive into — Implementation Plan

**Author**: Claude.
**Derived from**: spec.md, design.md (2026-09-13).
**Last updated**: 2026-09-13.
**Status**: Approved (John Fricker).

## Steps

1. Create `docs/archive/.gitkeep` (empty file) so git tracks the otherwise-empty
   directory, matching the existing `docs/.gitkeep` convention.
2. Edit `.claude/skills/wrapup/SKILL.md`'s Process section (step 3, the `git mv` step)
   to add a precondition check: before moving cycle docs, confirm `docs/archive/`
   exists; if it doesn't, stop and tell the user rather than creating it implicitly.
   This is a documentation-only change to the skill's instructions — no code.

## Files touched

- `docs/archive/.gitkeep` (new)
- `.claude/skills/wrapup/SKILL.md` (edit Process step 3)

## Sequencing

Step 1 before step 2 is not strictly required (they're independent), but doing the
directory first lets step 2's wording reference it as already real. No other
dependencies.

## Risks / rollback

None of note — additive, non-executable, two-file change. Rollback is `git revert` of
the single commit.

## Verification plan

- `git ls-files docs/archive/` lists `docs/archive/.gitkeep`.
- `git status` shows `docs/archive/` tracked, not just present on disk.
- `.claude/skills/wrapup/SKILL.md` Process step 3 explicitly names `docs/archive/` as a
  precondition to check for.
- No other files modified (`git status --short` shows exactly these two paths).
