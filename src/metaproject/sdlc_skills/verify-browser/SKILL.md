---
name: verify-browser
description: Proves a browser bug is fixed in every engine — reproduces it in WebKit with a failing Playwright test, then iterates on the fix until the test passes in webkit, chromium and a mobile-safari viewport with the full gate green, with before/after screenshots and a real-device list. Use when the user says "verify in Safari", "verify-browser", "cross-browser check", "reproduce this in WebKit", "it only breaks on iPhone", or a UI fix is about to be committed without being seen in the engine where it fails. Not for the general test loop — that is execute-tests.
---

# verify-browser

> **Precondition.** This project must be metaproject-managed: the nearest `.metaproject.json`
> (this directory or an ancestor) and `metaproject` on `PATH`. If either is missing, stop and tell the
> operator to run `metaproject new .` (agents may run only `metaproject new . --dry-run`).

Cross-browser verification loop: reproduce a browser bug in WebKit with a failing
regression test, fix it until the test passes in every target engine, and report what
still needs a real device. A utility skill, not a cycle stage — it does not tick the
`docs/STATE.md` Process list.

## When to use

- A bug shows up in one browser (most often Safari or iPhone) and a fix is planned or
  already drafted.
- A UI fix is about to be committed without having been seen in the engine where it
  fails.
- Not for the general test/build/lint loop — that is `execute-tests`.

## Inputs

- The bug description and the affected URL or route.
- `e2e_port` from `.metaproject.json` (the port the preview/dev server uses for e2e).
- The project's Playwright config (`playwright.config.*`) and its projects.
- The quality gate as `AGENTS.md` / the `Makefile` define it (`make help` for targets).

## Process

1. **Check the tooling.** If the project has no Playwright config, stop and ask whether
   to add one. Do not scaffold a test framework unasked.
2. **Isolate browsers.** Apply `execute-tests` step 2 before every e2e run: stop stale
   preview/dev servers on `e2e_port`, and handle a held Playwright install lock the way it
   describes. In this skill, always set `PLAYWRIGHT_BROWSERS_PATH` to the worktree-local
   `.playwright-browsers/`, not only when the lock is held. Confirm it is git-ignored
   (`git check-ignore .playwright-browsers`); if it is not, ask before adding it to
   `.gitignore`. Install only `webkit` and `chromium`
   (`npx playwright install webkit chromium`). Never delete another session's lock.
3. **Map the three targets** to the config's projects: `webkit`, `chromium`, and
   `mobile-safari` (the WebKit engine with an iPhone device descriptor). If the config
   lacks one, add that project on the branch and say so in the report. Never rename or
   remove existing projects.
4. **Before screenshots** of the affected route at desktop and mobile widths. Use the
   chrome-devtools MCP where it is available; it drives Chromium only, so label those
   screenshots Chromium. Otherwise use Playwright `page.screenshot`. WebKit screenshots
   always come from Playwright.
5. **Reproduce in WebKit first.** Write a regression test (`*.spec.ts`, beside the
   project's other e2e tests) that fails on current `main` when run with
   `--project=webkit`. If it passes, adjust in this order: timing and waits, viewport,
   animation frames (`requestAnimationFrame` stepping, reduced motion on and off), then
   screenshot pixel sampling. Stop after about five rounds and write up why it cannot be
   reproduced: what was tried and the likely real-device-only cause. A test that never
   failed proves nothing; do not move on to a fix with it unless the operator says so.
6. **Confirm it fails for the right reason**: the assertion on the bug fails, not a
   selector, navigation or timeout error.
7. **Fix and iterate** until the same test passes in `webkit`, `chromium` and
   `mobile-safari`. Run only the affected projects (`--project=<name>`) while iterating,
   then the full matrix once, then the full gate.
8. **After screenshots**, same routes, widths and tools as step 4.
9. **Commit** only when all three projects pass and the gate is green.
10. **Report**: the regression test names with their failing-then-passing result per
    project, before and after screenshot paths (and which engine took each), any
    Playwright project added in step 3, and what still needs a real device (Safari on
    macOS, Safari on iOS, other devices).
11. **Record what needs a real device.** Append a dated
    `## YYYY-MM-DD: Needs manual verification (<slug>)` entry to `docs/TODO.md`, as
    `wrapup` does; if the file is missing, create it first with
    `metaproject backfill docs/TODO.md`. List each item as `- [ ]` with the exact steps
    for the operator and the expected result. Append only; never edit earlier entries.
    Unlike `wrapup`, add no entry when nothing is outstanding.

## Output artifact

A committed fix with a WebKit regression test that failed before the fix and now passes
in `webkit`, `chromium` and `mobile-safari`, plus the report from step 10 and any
`docs/TODO.md` entry from step 11. If the bug cannot be reproduced, the output is the
"cannot be reproduced" write-up instead, and nothing is committed.

## Stop conditions / human gate

- Do not commit until `webkit`, `chromium` and `mobile-safari` all pass and the full gate
  is green. The fix is not complete until the WebKit regression test passes.
- Never weaken, skip or delete the regression test to get green.
- Never claim "verified in Safari": Playwright WebKit is not Safari on a real device. Say
  "WebKit", and list the real-device checks in `docs/TODO.md`.
- Never wait on, or delete, a held Playwright install lock.
- Do not edit cycle documents (`docs/INTENT.md`, `docs/SPEC.md`, `docs/TECH-DESIGN.md`,
  `docs/PLAN.md`, `docs/STATE.md`).
