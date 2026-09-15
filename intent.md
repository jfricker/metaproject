# <Title>

**Author**: John Fricker.
**Last updated**: 2026-09-15.
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

- **`metaproject doctor`** (carried forward from the
  [template-source-of-truth](docs/archive/2026-09-15-template-source-of-truth/) cycle,
  FC-3 + spec R-LRN-3 + R-DOC-1): a future command that refreshes the live store at
  `~/.metaproject/templates` from the bundled package templates after an upgrade
  (currently a manual, by-hand refresh); migrates a `config.json` that pins
  `learn.targets` so newly added working deliverables get scanned; and refreshes the
  installed skill at `~/.claude/skills/metaproject/`.
