# backlog-new skill — pre-cycle idea parking lot

**Captured**: 2026-09-15, brainstormed in MetaProject (design session approved by John Fricker).
**Status**: backlog — not specced, not scheduled.
**Target**: `~/Projects/SDLC-skills` (new `skills/backlog-new/`, one-line edit to `write-intent`), rides the approved sdlc-skills→metaproject merge.

## Goal

Add an eighth sdlc-skills skill, `backlog-new`: a pre-write-intent capture flow for ideas
that are not ready to become a cycle. It invokes the built-in `brainstorming` skill when
present (falling back to its own question loop when not), distills the session into
`docs/backlog/<kebab-slug>.md`, and commits it. Distinct from `write-intent`, which is for
work being started now.

## Current behavior (verified 2026-09-15)

- `docs/backlog/` is an ad-hoc convention that exists only in MetaProject (two docs:
  `branch-when-write-intent.md`, `sdlc-skills-merge-with-metaproject.md`); no skill owns it.
- The built-in `brainstorming` skill (superpowers-style, at `~/.claude/skills/brainstorming`)
  is machine-local and not shipped with sdlc-skills, so it cannot be a hard dependency.
- The approved merge design (MetaProject `docs/backlog/sdlc-skills-merge-with-metaproject.md`,
  commit `a263384`) says "curate 7 SKILL.md" — this becomes 8.

## Proposed direction

### The skill

- **Location**: `skills/backlog-new/SKILL.md`, invoked as `sdlc-skills:backlog-new`.
- **Triggers**: "new backlog", "backlog-new", "park this idea", "add to backlog",
  "save this for later", "brainstorm this but don't start a cycle". Description routes
  away from write-intent when the user wants to start work now.
- **Flow**:
  1. Invoke the built-in `brainstorming` skill if available; run its questioning/refinement
     flow but override its terminal state — stop before any spec file, plan, or
     implementation, and distill into the backlog doc instead.
  2. If `brainstorming` is not installed, run a custom loop: classify (quick idea vs.
     needs exploration), ask clarifying questions one at a time, explore repo context as
     needed, stop at "direction understood".
  3. Write `docs/backlog/<kebab-slug>.md` (create the directory if missing).
  4. Commit the doc.
- **Doc format** (standardized from the existing backlog docs):
  ```markdown
  # <Title>

  **Captured**: YYYY-MM-DD[, <triggering context>]
  **Status**: backlog — not specced, not scheduled. | promoted YYYY-MM-DD (<cycle>)
  **Target**: <repo/system this would change>

  ## Goal
  ## Current behavior (verified <date>)
  ## Proposed direction
  ## Open questions
  ```

### Supporting edits

- `write-intent` SKILL.md: one added line — if the idea comes from `docs/backlog/`, treat
  that doc as the raw problem statement and flip its Status header to
  `promoted <date> (<cycle name>)` when the cycle starts.
- MetaProject merge design doc: update "7 SKILL.md" → "8 SKILL.md".
- No STATE.md/Process changes — backlog-new sits before the 7-stage cycle.
- No code or tests in metaproject — pure skill text.

### Deliberate omissions (YAGNI)

- No `backlog list`/`backlog review` companion — `ls docs/backlog/` plus Status headers
  answer that.
- No dedicated promote machinery — promotion is a convention edit made by write-intent.
