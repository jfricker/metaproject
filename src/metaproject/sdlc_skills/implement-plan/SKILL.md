---
name: implement-plan
description: Implement strictly against an approved PLAN.md, following CLAUDE.md conventions, producing code and tests and keeping STATE.md updated as each step lands. Use when PLAN.md is approved and the user wants the actual code written. Fifth step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# implement-plan

> **Precondition.** This project must be metaproject-managed: `.metaproject.json` at the
> repository root and `metaproject` on `PATH`. If either is missing, stop and tell the
> operator to run `metaproject new .` (agents may run only `metaproject new . --dry-run`).

Stage 3b of the SDLC loop: execute the approved plan, not a reinterpretation of it.

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
- Tick `docs/STATE.md` Process item 5 once this stage is done.
- Before editing, grep to locate the exact target and count matches. After editing,
  diff to confirm no sibling or identically-structured code changed. If a direct Edit
  fails twice on this file, switch to a perl/python scripted edit instead of retrying
  blind.

## When to use

- `docs/PLAN.md` exists with `Status: Approved`.
- The user wants code written against that plan.

## Inputs

- Approved `docs/PLAN.md` (and `docs/SPEC.md`/`docs/TECH-DESIGN.md` for context on *why*).
- `CLAUDE.md` for team conventions, commands, and mistakes to avoid.
- `docs/STATE.md`'s checklist.

## Process

1. Read `docs/PLAN.md` in full. Refuse to proceed if its Status isn't `Approved`.
2. Work through `docs/PLAN.md`'s steps in the stated sequence. If reality diverges from the
   plan (a step doesn't apply, a file doesn't exist as expected), stop and flag it to the
   user rather than silently improvising past what was approved — a material deviation
   means the plan needs revisiting (back to `generate-plan`), not a unilateral pivot.
3. Follow `CLAUDE.md` conventions and reuse existing patterns/utilities found during
   `generate-design`/`generate-plan` rather than introducing new ones.
4. Write tests alongside the code covering `docs/SPEC.md`'s acceptance criteria — don't defer
   all testing to `execute-tests`.
5. Update `docs/STATE.md`'s checklist as each step of `docs/PLAN.md` completes (check the box,
   don't just narrate progress).
6. If work is interrupted before the plan is fully implemented, run
   `metaproject backfill docs/HANDOFF.md` (it's an on-demand document) and fill it in with
   exact state and next step, per `AGENTS.md`.

## Output artifact

Committed code + tests on the working branch, matching `docs/PLAN.md`; `docs/STATE.md` reflecting
real progress.

## Stop conditions / human gate

- Do not implement beyond what `docs/PLAN.md` approved — new scope goes back through
  `generate-spec`/`generate-design`/`generate-plan`, not straight into code.
- Do not open a PR from this skill — hand off to `execute-tests` first.
