# Sdlc Skills — State

## Process
- [x] 1. Review intent.md and create spec.md
- [x] 2. Create plan.md from spec.md
- [x] 3. Implementation and verification

## Implementation phases
- [x] Created 7 skills under `.claude/skills/`: write-intent, generate-spec,
      generate-design, generate-plan, implement-plan, execute-tests, wrapup — covering
      the full loop from https://claude.com/blog/the-ai-native-sdlc-playbook as adapted
      by AGENTS.md.

## Design invariants (regression guards)
- `generate-spec`/`generate-design`/`generate-plan` own the canonical blank templates
  for `spec.md`/`design.md`/`plan.md`; `wrapup` must reuse those shapes, not redefine
  them, when it resets the repo root after archiving a cycle.
- `wrapup` only ever touches SDLC documents, `docs/archive/`, and worktrees — never
  source code, tests, or PRs.

## Open items carried into plan.md
- No `Makefile` exists yet despite `AGENTS.md`/`CLAUDE.md` referencing `make help` as
  the primary dev/test entry point — out of scope for this cycle (skills-authoring
  only), but `execute-tests` will need it once real implementation work starts.

## Verified facts (do not re-investigate)
- Repo's SDLC artifact conventions (intent.md → spec.md → plan.md, STATE.md, HANDOFF.md,
  archive naming `YYYY-MM-DD-<title>`) are defined in `AGENTS.md`.
- Blog playbook fetched from https://claude.com/blog/the-ai-native-sdlc-playbook on
  2026-09-13: 6 stages (Plan/Design/Build/Test/Deploy/Maintain); `design.md` as a
  distinct artifact from `spec.md` is this repo's own extension, anticipated by
  AGENTS.md's plan.md description ("spec.md and any design artifacts").
