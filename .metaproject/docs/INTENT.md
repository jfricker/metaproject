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

- Agent output cosmetics: `skills status --all` table has no agents column and `skills sync --all` totals exclude agents; named-file `backfill` lists a disabled/symlink-blocked agent under "Refused — already exists" (from [.metaproject/docs/archive/2026-11-26-ship-project-subagents-as-a-deliverable/](archive/2026-11-26-ship-project-subagents-as-a-deliverable/))
- `doctor` does not mention modified agents (SPEC R-AGT-16 said "reported"; only `skills status` shows them) (from [.metaproject/docs/archive/2026-11-26-ship-project-subagents-as-a-deliverable/](archive/2026-11-26-ship-project-subagents-as-a-deliverable/))
- `review --format json` can shallow-fetch an uncached git `templates.source` into `~/.metaproject/cache/templates/` (R-AGT-22 said "never writes") (from [.metaproject/docs/archive/2026-11-26-ship-project-subagents-as-a-deliverable/](archive/2026-11-26-ship-project-subagents-as-a-deliverable/))
- `review --managed --format json` top-level `"templates"` is the first project's store; consider per-project only (from [.metaproject/docs/archive/2026-11-26-ship-project-subagents-as-a-deliverable/](archive/2026-11-26-ship-project-subagents-as-a-deliverable/))
- Regenerate `skill_history.json` right after the next version bump: new agent/skill digests are labelled `0.12.0` (already tagged) and `backlog-worker` has an unreleased intermediate digest (from [.metaproject/docs/archive/2026-11-26-ship-project-subagents-as-a-deliverable/](archive/2026-11-26-ship-project-subagents-as-a-deliverable/))
