---
name: implement-plan
description: Implement strictly against an approved plan.md, following CLAUDE.md conventions, producing code and tests and keeping STATE.md updated as each step lands. Use when plan.md is approved and the user wants the actual code written. Fifth step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# implement-plan

Stage 3b of the SDLC loop: execute the approved plan, not a reinterpretation of it.

## When to use

- `plan.md` exists at the repo root with `Status: Approved`.
- The user wants code written against that plan.

## Inputs

- Approved `plan.md` (and `spec.md`/`design.md` for context on *why*).
- `CLAUDE.md` for team conventions, commands, and mistakes to avoid.
- `STATE.md`'s checklist.

## Process

1. Read `plan.md` in full. Refuse to proceed if its Status isn't `Approved`.
2. Work through `plan.md`'s steps in the stated sequence. If reality diverges from the
   plan (a step doesn't apply, a file doesn't exist as expected), stop and flag it to the
   user rather than silently improvising past what was approved — a material deviation
   means the plan needs revisiting (back to `generate-plan`), not a unilateral pivot.
3. Follow `CLAUDE.md` conventions and reuse existing patterns/utilities found during
   `generate-design`/`generate-plan` rather than introducing new ones.
4. Write tests alongside the code covering `spec.md`'s acceptance criteria — don't defer
   all testing to `execute-tests`.
5. Update `STATE.md`'s checklist as each step of `plan.md` completes (check the box,
   don't just narrate progress).
6. If work is interrupted before the plan is fully implemented, write `HANDOFF.md`
   capturing exact state and next step, per `AGENTS.md`.

## Output artifact

Committed code + tests on the working branch, matching `plan.md`; `STATE.md` reflecting
real progress.

## Stop conditions / human gate

- Do not implement beyond what `plan.md` approved — new scope goes back through
  `generate-spec`/`generate-design`/`generate-plan`, not straight into code.
- Do not open a PR from this skill — hand off to `execute-tests` first.
