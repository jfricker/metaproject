---
name: generate-plan
description: Turn approved SPEC.md and TECH-DESIGN.md into an implementation PLAN.md — files touched, sequencing, risks — using Claude Code's plan mode so no code is written until the plan is approved. Use when SPEC.md and TECH-DESIGN.md are approved and the user is ready to plan implementation. Fourth step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# generate-plan

> **Precondition.** This project must be metaproject-managed: `.metaproject.json` at the
> repository root and `metaproject` on `PATH`. If either is missing, stop and tell the
> operator to run `metaproject new .` (agents may run only `metaproject new . --dry-run`).

Stage 3a of the SDLC loop: plan mode prevents code generation until strategy is
approved.

## Conventions (metaproject)

- **Documents come from metaproject**: working documents are templated by metaproject,
  not by this skill, and live in `docs/` (`docs/INTENT.md`, `docs/SPEC.md`,
  `docs/TECH-DESIGN.md`, `docs/PLAN.md`, `docs/STATE.md`, `docs/ARCHITECTURE.md`).
  Create a missing one with `metaproject backfill docs/<FILE>.md` (create-only — it
  never overwrites); `metaproject backfill` with no files creates every missing
  scaffolded deliverable at once. `docs/HANDOFF.md` is on-demand:
  `metaproject backfill docs/HANDOFF.md`.
- If a metaproject command fails, stop and show the user its output.
- **Blank rule**: a cycle document (INTENT/SPEC/TECH-DESIGN/PLAN) is blank iff its first
  `# ` heading contains `<Title>`.
- **Status vocabulary**: `Draft`, `Approved`, `Complete`, `Cancelled`, `Deferred`,
  `Superseded`. Header fields are `Author`, `Derived from` (not on INTENT.md),
  `Last updated`, `Status`, `Approved by`. On approval set `**Status**: Approved.` and
  `**Approved by**: <name> (<YYYY-MM-DD>).`; approval gates check that Status is
  `Approved`. Never set it to `Approved` yourself.
- Tick `docs/STATE.md` Process item 4 once this stage is done.

## When to use

- `docs/SPEC.md` and `docs/TECH-DESIGN.md` both exist with `Status: Approved`.
- The user is ready to move from "what/how" to "in what order, touching which files."

## Inputs

- Approved `docs/SPEC.md` and `docs/TECH-DESIGN.md`.
- This repo's `CLAUDE.md` (conventions) and any relevant organization policy skills
  (installed as other plugins, or the project's own `.claude/skills/` if any exist).

## Process

1. Read `docs/SPEC.md` and `docs/TECH-DESIGN.md` in full. Refuse to proceed if either isn't `Approved`.
2. Enter plan mode (`EnterPlanMode`) — do not write or edit source files in this step.
3. If `docs/PLAN.md` doesn't exist, create it with
   `metaproject backfill docs/PLAN.md` once plan mode work is ready to be written down.
4. Build the plan from `docs/TECH-DESIGN.md`'s components: concrete steps, the specific files to
   create/modify, sequencing (what must land before what), and risks/rollback
   considerations. Reference existing functions/utilities to reuse rather than
   reinventing them.
5. Exit plan mode (`ExitPlanMode`) to get user approval on the plan content. The
   operator's approval through `ExitPlanMode` counts as their sign-off — write
   `**Status**: Approved.` and `**Approved by**: <name> (<YYYY-MM-DD>).` into `docs/PLAN.md`
   on that basis; don't ask for a second, separate approval.
6. Once approved, write the approved plan into `docs/PLAN.md` with **Status: Approved**.

## Output artifact

`docs/PLAN.md`, status `Approved`.

## Stop conditions / human gate

- No source code or test changes in this skill — plan mode only, until `ExitPlanMode` is
  approved.
- Don't write `Status: Approved` on your own judgment — `ExitPlanMode` approval from the
  operator is what authorizes it (step 5); without that approval, leave Status at
  `Draft`.
