---
name: generate-plan
description: Turn approved spec.md and design.md into an implementation plan.md — files touched, sequencing, risks — using Claude Code's plan mode so no code is written until the plan is approved. Use when spec.md and design.md are approved and the user is ready to plan implementation. Fourth step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# generate-plan

Stage 3a of the SDLC loop: plan mode prevents code generation until strategy is
approved.

## Conventions (metaproject)

- **Session assumption**: a `SessionStart` hook already checked that metaproject ≥
  0.7.0 is installed and `.metaproject.json` exists; this skill doesn't re-check. If
  the session-start `[sdlc-skills]` notice reported a failure, stop and repeat its fix
  instead of proceeding. If a metaproject command fails anyway, stop and show the user
  its output.
- **Documents come from metaproject**: working documents are templated by metaproject,
  not by this skill. Create a missing one with `metaproject backfill <file>`
  (create-only — it never overwrites); `metaproject backfill` with no files creates
  every missing scaffolded deliverable at once. `HANDOFF.md` is on-demand:
  `metaproject backfill HANDOFF.md`.
- **Blank rule**: a cycle document (intent/spec/design/plan) is blank iff its first
  `# ` heading contains `<Title>`.
- **Status vocabulary**: `Draft`, `Approved`, `Complete`, `Cancelled`, `Deferred`,
  `Superseded`. Header fields are `Author`, `Derived from` (not on intent.md),
  `Last updated`, `Status`, `Approved by`. On approval set `**Status**: Approved.` and
  `**Approved by**: <name> (<YYYY-MM-DD>).`; approval gates check that Status is
  `Approved`. Never set it to `Approved` yourself.
- Tick STATE.md Process item 4 once this stage is done.

## When to use

- `spec.md` and `design.md` both exist at the repo root with `Status: Approved`.
- The user is ready to move from "what/how" to "in what order, touching which files."

## Inputs

- Approved `spec.md` and `design.md`.
- This repo's `CLAUDE.md` (conventions) and any relevant organization policy skills
  (installed as other plugins, or the project's own `.claude/skills/` if any exist).

## Process

1. Read `spec.md` and `design.md` in full. Refuse to proceed if either isn't `Approved`.
2. Enter plan mode (`EnterPlanMode`) — do not write or edit source files in this step.
3. If `plan.md` doesn't exist at the repo root, create it with
   `metaproject backfill plan.md` once plan mode work is ready to be written down.
4. Build the plan from `design.md`'s components: concrete steps, the specific files to
   create/modify, sequencing (what must land before what), and risks/rollback
   considerations. Reference existing functions/utilities to reuse rather than
   reinventing them.
5. Exit plan mode (`ExitPlanMode`) to get user approval on the plan content. The
   operator's approval through `ExitPlanMode` counts as their sign-off — write
   `**Status**: Approved.` and `**Approved by**: <name> (<YYYY-MM-DD>).` into `plan.md`
   on that basis; don't ask for a second, separate approval.
6. Once approved, write the approved plan into `plan.md` with **Status: Approved**.

## Output artifact

`plan.md` at the repo root, status `Approved`.

## Stop conditions / human gate

- No source code or test changes in this skill — plan mode only, until `ExitPlanMode` is
  approved.
- Don't write `Status: Approved` on your own judgment — `ExitPlanMode` approval from the
  operator is what authorizes it (step 5); without that approval, leave Status at
  `Draft`.
