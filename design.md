# Create docs/archive/ so wrapup has somewhere to archive into — Design

**Author**: Claude.
**Derived from**: spec.md (2026-09-13).
**Last updated**: 2026-09-13.
**Status**: Approved (John Fricker).

## Affected components

- **`docs/archive/`** (new, empty, git-tracked directory) — sibling to the existing
  `docs/.gitkeep`-tracked `docs/` directory. Holds a single placeholder file,
  `docs/archive/.gitkeep`, so git tracks the otherwise-empty directory (git doesn't
  track directories themselves, only files).
- **`.claude/skills/wrapup/SKILL.md`** — Process step 3 gets one clause added: before
  `git mv`-ing cycle docs into `docs/archive/YYYY-MM-DD-<slug>/`, confirm
  `docs/archive/` exists; if it doesn't, stop and tell the user rather than creating it
  implicitly. No other step changes.

## Data flow / interfaces

None — this is static repo scaffolding, not a runtime component. The only "flow" is
`wrapup`'s existing `git mv` step now targeting a path (`docs/archive/<slug>/`) whose
parent is guaranteed to pre-exist and be tracked, instead of a path whose parent may or
may not exist depending on repo history.

## Alternatives considered

1. **Have `wrapup` `mkdir -p docs/archive` itself instead of requiring it to pre-exist.**
   Rejected: `spec.md`'s functional requirement #3 explicitly wants a loud failure if
   the convention is broken, not silent self-healing — `wrapup` already has a "no source
   code" scope discipline, and quietly creating directories on every run is the kind of
   implicit behavior that convention exists to avoid.
2. **Track `docs/archive/` with a `README.md` explaining the archive layout instead of a
   bare `.gitkeep`.** Rejected for v1: `spec.md` scoped this to matching the existing
   `docs/.gitkeep` convention; a README is a reasonable follow-up but is new scope, not
   what was approved.

## Trade-offs and risks

- **Trade-off**: a bare `.gitkeep` documents nothing about what belongs in the
  directory. Acceptable — `wrapup`'s SKILL.md is already the source of truth for the
  archive layout (`YYYY-MM-DD-<slug>/`), so a second explanation in the directory itself
  would be duplication, not new information.
- **Risk**: none identified. This is an additive, non-executable change with no
  consumers other than `wrapup`, which is edited in the same change.

## Open questions

None.
