---
name: execute-tests
description: Runs the project's test/build/lint feedback loop (via make, per AGENTS.md) and fixes failures before a human reviews the work — every session checks its own work before a person sees it. Use after implement-plan, before opening or updating a PR. Sixth step of the write-intent → generate-spec → generate-design → generate-plan → implement-plan → execute-tests → wrapup cycle.
---

# execute-tests

> **Precondition.** This project must be metaproject-managed: the nearest `.metaproject/config.json`
> (this directory or an ancestor) and `metaproject` on `PATH`. If either is missing, stop and tell the
> operator to run `metaproject new .` (agents may run only `metaproject new . --dry-run`).

Stage 6 of 7: the self-check loop that runs before a person is asked to
look — tests, build, and (for UI work) screenshots.

## Conventions (metaproject)

- **Documents come from metaproject**: working documents are templated by metaproject,
  not by this skill, and live in `.metaproject/docs/` (`.metaproject/docs/INTENT.md`, `.metaproject/docs/SPEC.md`,
  `.metaproject/docs/TECH-DESIGN.md`, `.metaproject/docs/PLAN.md`, `.metaproject/docs/STATE.md`, `.metaproject/docs/ARCHITECTURE.md`).
  Create a missing one with `metaproject backfill .metaproject/docs/<FILE>.md` (create-only — it
  never overwrites); `metaproject backfill` with no files creates every missing
  scaffolded deliverable at once. `.metaproject/docs/HANDOFF.md` is on-demand:
  `metaproject backfill .metaproject/docs/HANDOFF.md`. Note: `.metaproject/docs/` is a
  hidden dot-directory, so pass `.metaproject/docs/` explicitly or `--hidden` to `rg`/`fd`.
- If a metaproject command fails, stop and show the user its output.
- **Blank rule**: a cycle document (INTENT/SPEC/TECH-DESIGN/PLAN) is blank iff its first
  `# ` heading contains `<Title>`.
- **Status vocabulary**: `Draft`, `Approved`, `Complete`, `Cancelled`, `Deferred`,
  `Superseded`. Header fields are `Author`, `Derived from` (not on INTENT.md),
  `Last updated`, `Status`, `Approved by`. On approval set `**Status**: Approved.` and
  `**Approved by**: <name> (<YYYY-MM-DD>).`; approval gates check that Status is
  `Approved`. Set `Approved` only on the operator's explicit sign-off, never on your
  own judgment.
- Tick `.metaproject/docs/STATE.md` Process item 6 once this stage is done.

## When to use

- Code from `implement-plan` exists on the working branch and needs verification before
  handoff/PR.

## Inputs

- `.metaproject/docs/PLAN.md`'s **Verification plan** section and `.metaproject/docs/SPEC.md`'s **Acceptance criteria**.
- This project's `Makefile` (`make help` for targets) — the primary test/build entry
  point per `AGENTS.md`.

## Process

1. Run `make help` if you haven't already this session, to confirm the actual available
   targets — don't assume target names.
2. **Before any e2e run**, clear the way (skip when the project has no Playwright e2e):
   - Stop stale preview/dev servers on the e2e port (`e2e_port` in `.metaproject/config.json`;
     `lsof -nP -iTCP:<port> -sTCP:LISTEN`). The bundled pre-Bash hook already does this
     for commands that mention playwright.
   - Check whether a Playwright install lock is held: a `__dirlock` directory under the
     browsers path (`$PLAYWRIGHT_BROWSERS_PATH`, else `~/Library/Caches/ms-playwright` on
     macOS or `~/.cache/ms-playwright` on Linux), or a running `playwright install`
     process. **If it is held, do not wait.** Set `PLAYWRIGHT_BROWSERS_PATH` to a
     worktree-local, git-ignored directory (`.playwright-browsers/`), install only the
     engines this run needs (`npx playwright install <engine>`), and run only the
     affected project(s) (`--project=<name>`) rather than the whole matrix. If a stale
     lock is suspected, report it to the operator; never delete another session's lock.
3. Run the test suite, build, and any lint/typecheck targets. Capture full output.
4. For UI-facing changes, use the `run` skill (or project-specific launch skill) to
   actually run the app and take a screenshot confirming the change works, not just that
   tests pass.
5. On failure: fix the code and re-run, don't just report the failure and stop, unless
   the fix requires a decision outside `.metaproject/docs/PLAN.md`'s scope — then stop and flag it.
6. Check each item in `.metaproject/docs/SPEC.md`'s Acceptance criteria against what was actually
   implemented; note any criteria not yet met.
7. Record in `.metaproject/docs/STATE.md` (wrapup reads these sections and nothing else): unmet
   acceptance criteria and unresolved failures under **Open items carried into PLAN.md**;
   new regression guards under **Design invariants**; facts this run established under
   **Verified facts**.
8. Report results plainly: what passed, what failed, what was fixed, and anything still
   open — never claim tests pass without having run them.

## Output artifact

A verified, green test/build run (or an explicit list of what's still failing and why),
ready for `wrapup`. No cycle skill opens a PR: if the project uses them, opening one is the
operator's call, and landing the branch is `/shipit`'s.

## Stop conditions / human gate

- Do not silently skip or delete a failing test to make the suite pass.
- If fixing a failure would require deviating from the approved `.metaproject/docs/PLAN.md`, stop and ask
  rather than reinterpreting the plan.
