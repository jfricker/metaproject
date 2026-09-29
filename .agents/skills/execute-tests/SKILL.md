---
name: execute-tests
description: Run the project's test/build/lint feedback loop (via make, per AGENTS.md) and fix failures before a human reviews the work — every session checks its own work before a person sees it. Use after implement-plan, before opening or updating a PR. Sixth step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# execute-tests

> **Precondition.** This project must be metaproject-managed: `.metaproject.json` at the
> repository root and `metaproject` on `PATH`. If either is missing, stop and tell the
> operator to run `metaproject new .` (agents may run only `metaproject new . --dry-run`).

Stage 4 of the SDLC loop: the self-check loop that runs before a person is asked to
look — tests, build, and (for UI work) screenshots.

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
- Tick `docs/STATE.md` Process item 6 once this stage is done.

## When to use

- Code from `implement-plan` exists on the working branch and needs verification before
  handoff/PR.

## Inputs

- `docs/PLAN.md`'s **Verification plan** section and `docs/SPEC.md`'s **Acceptance criteria**.
- This project's `Makefile` (`make help` for targets) — the primary test/build entry
  point per `AGENTS.md`.

## Process

1. Run `make help` if you haven't already this session, to confirm the actual available
   targets — don't assume target names.
2. Run the test suite, build, and any lint/typecheck targets. Capture full output.
3. For UI-facing changes, use the `run` skill (or project-specific launch skill) to
   actually run the app and take a screenshot confirming the change works, not just that
   tests pass.
4. On failure: fix the code and re-run, don't just report the failure and stop, unless
   the fix requires a decision outside `docs/PLAN.md`'s scope — then stop and flag it.
5. Check each item in `docs/SPEC.md`'s Acceptance criteria against what was actually
   implemented; note any criteria not yet met.
6. Report results plainly: what passed, what failed, what was fixed, and anything still
   open — never claim tests pass without having run them.

## Output artifact

A verified, green test/build run (or an explicit list of what's still failing and why),
ready for `wrapup`/PR.

## Stop conditions / human gate

- Do not silently skip or delete a failing test to make the suite pass.
- If fixing a failure would require deviating from the approved `docs/PLAN.md`, stop and ask
  rather than reinterpreting the plan.
