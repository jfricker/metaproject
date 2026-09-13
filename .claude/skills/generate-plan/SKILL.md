---
name: generate-plan
description: Turn approved spec.md and design.md into an implementation plan.md — files touched, sequencing, risks — using Claude Code's plan mode so no code is written until the plan is approved. Use when spec.md and design.md are approved and the user is ready to plan implementation. Fourth step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# generate-plan

Stage 3a of the SDLC loop: plan mode prevents code generation until strategy is
approved.

## When to use

- `spec.md` and `design.md` both exist at the repo root with `Status: Approved`.
- The user is ready to move from "what/how" to "in what order, touching which files."

## Inputs

- Approved `spec.md` and `design.md`.
- This repo's `CLAUDE.md` (conventions) and any relevant `.claude/skills/` policies.

## Process

1. Read `spec.md` and `design.md` in full. Refuse to proceed if either isn't `Approved`.
2. Enter plan mode (`EnterPlanMode`) — do not write or edit source files in this step.
3. If `plan.md` doesn't exist at the repo root, create it from the **blank template**
   below once plan mode work is ready to be written down.
4. Build the plan from `design.md`'s components: concrete steps, the specific files to
   create/modify, sequencing (what must land before what), and risks/rollback
   considerations. Reference existing functions/utilities to reuse rather than
   reinventing them.
5. Exit plan mode (`ExitPlanMode`) to get user approval on the plan content.
6. Once approved, write the approved plan into `plan.md` with **Status: Approved**.

## Blank template (`plan.md`)

```markdown
# <Title> — Implementation Plan

**Author**: {agent/user}.
**Derived from**: spec.md, design.md ({date}).
**Last updated**: {date}.
**Status**: Draft.

## Steps

## Files touched

## Sequencing

## Risks / rollback

## Verification plan
```

## Output artifact

`plan.md` at the repo root, status `Approved`.

## Stop conditions / human gate

- No source code or test changes in this skill — plan mode only, until `ExitPlanMode` is
  approved.
- Never set Status to `Approved` yourself.
