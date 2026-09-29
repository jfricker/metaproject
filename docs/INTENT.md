# <Title>

**Author**: John Fricker.
**Last updated**: 2026-09-29.
**Status**: Draft.
**Approved by**: —

## Problem

<What problem, ticket, or incident prompted this cycle?>

## Proposed outcome

<What should be true once this cycle ships?>

## Affected users and systems

<Who or what this touches.>

## Scope

### In Scope (v1)

### Out of Scope (v1)

## Resolved decisions

## Constraints

## Open questions

- Carried forward from [absorb-sdlc-skills-into-metaproject-move-cycle-docs-to-docs](archive/2026-09-29-absorb-sdlc-skills-into-metaproject-move-cycle-docs-to-docs/):
  - `backfill` / doctor's skills fix install into `.agents/skills/` even when a project has no `.claude/skills` symlink (skills then invisible to Claude Code). Only `new` creates the link. Candidate follow-up: have backfill/doctor create or report the missing link.
  - README's retirement note says "absorbed into metaproject ≥ 0.9.0" — confirm the version when `bump_version.sh` runs.
  - Operator steps after merge (R-RET-1): install release, uninstall sdlc-skills plugin and its marketplace, `metaproject doctor` on the real store/projects, SDLC-skills README pointer.

