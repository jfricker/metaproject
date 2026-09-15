# Handoff: Make metaproject the source of truth for SDLC document templates

**Date**: 2026-09-14
**Author**: Claude (for John Fricker)
**Status**: Superseded — work resumed 2026-09-14; see STATE.md. Waiting on operator for E3 (install branch build, `metaproject new .` in SDLC-skills).

## Current state

Cycle is in **implement-plan** (STATE.md Process item 5). Intent, spec, design and plan
are Approved (John Fricker, 2026-09-14). Implementation stopped at the operator's request
after B2. Every completed step has passed a full independent test gate.

| Step | State | Where |
|---|---|---|
| A1 deliverables.py | done, merged | metaproject `template-source-of-truth` |
| A2 markdown.py | done, merged | metaproject |
| A3 identity.py + variables | done, merged | metaproject |
| A4 placeholder warnings | done, merged | metaproject |
| B1 scaffold writes `.metaproject.json` | done | metaproject (6569a42) |
| B2 review classes | done | metaproject (8a5da49) |
| D3 discovery doc | done, merged | metaproject |
| E1 SessionStart hook + Makefile | done | sdlc-skills (131525f) |
| E2 7 SKILL.md rewrite | done | sdlc-skills (d4fe2e3) |
| B3, B4, C1–C4, D1, D2, E3, F | not started | — |

Last gate (B2, 2026-09-14): `ruff check` + `ruff format --check` clean; full suite
**491 passed**.

Uncommitted work: none in either worktree (this file is the only addition).

## Branches and worktrees

- **metaproject**: `~/Projects/MetaProject/.claude/worktrees/template-source-of-truth`,
  branch `template-source-of-truth`, HEAD `8a5da49` (before this handoff commit).
- **sdlc-skills**: `~/Projects/SDLC-skills/.claude/worktrees/template-source-of-truth`,
  branch `template-source-of-truth`, HEAD `d4fe2e3`.
- Merged step worktrees/branches `ts-a1…ts-d3` were removed on 2026-09-14.
- Nothing is merged to `main` in either repo. `~/.metaproject/` is untouched.

## Commands to re-run

From the metaproject worktree (each step's gate):

```bash
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
.venv/bin/pytest -q -p no:cacheprovider \
  --basetemp=/Users/johnfricker/Projects/MetaProject/.pytest_cache/tmp-resume tests
```

From the sdlc-skills worktree: `make test`.

Environment gotchas (see STATE.md Verified facts):
- Default TMPDIR contains `claude-501`, which trips the suites' "no `claude` subprocess"
  guard; always pass `--basetemp` outside any `claude` path.
- After the session resume on 2026-09-14 the sandbox also blocked git inside pytest temp
  repos (101 errors in `test_learn_tui.py` etc.); the same suite passes with the sandbox
  disabled. Run the gate unsandboxed.
- `uv` needs the sandbox disabled. Each worktree has its own `.venv`.

## Immediate next steps

1. **B3** — `review.backfill_missing` + `metaproject backfill [FILE...] [--dir]` CLI
   (spec R-TPL-8, AC-10). Create-only; no file args → all missing scaffolded deliverables;
   named existing file → exit 1, write nothing; allowed in agent sessions; never runs git.
2. **B4** — board/CLI surfaces: structure drift detail, notes/warnings, `new` prints
   warnings and "wrote .metaproject.json"; `new .` wording stops saying "backfill".
3. **C1 → C2 → C3 → C4** — heading-structure evidence, local `learn/structure.py`
   proposals (min 2 projects), apply add/remove heading, drift for structure.
4. **D1** — bundled templates (spec/design/plan/ARCHITECTURE/long-lived docs/archive,
   rewritten AGENTS/CLAUDE/README/STATE/HANDOFF/intent/.gitignore); delete repo-root
   `templates/`; then **delete `full_cycle_templates_store` from `tests/test_review.py`**
   and use the bundled store.
5. **D2** — skill docs (`skill/SKILL.md`, `references/documents.md`, `commands.md`), README.
6. **E3** — sdlc-skills README/AGENTS, root doc re-heading, `plugin.json` 0.0.2; operator
   installs the branch build (`uv tool install --force <metaproject worktree>`) and runs
   `metaproject new .` in the sdlc-skills worktree after a `--dry-run` preview.
7. Then `execute-tests`, then Phase F on `main` (merge metaproject → bump 0.7.0 → operator
   refreshes `~/.metaproject/templates` → merge sdlc-skills), then `wrapup`.

Parallelism that worked: B3 is independent of C1; D2 can run alongside C-steps once B4
lands. E3 must follow D1.

Process the operator asked for: sonnet agents code, haiku agents run the gate and report
test status; parallel when practical; stop and report on anything unexpected.

## Open issues or blockers

- **Test-local template store (B2).** Until D1, the bundled store lacks templates for six
  working deliverables, so no project reviewed against it can be CLEAN. B2 tests use
  `full_cycle_templates_store`; two pre-existing tests
  (`test_review_compliant_project`, `test_deployed_files_do_not_immediately_report_as_drifted`)
  were switched to it, contrary to plan.md's "unmodified". Recorded in STATE.md open items.
- **Deviations already recorded**: design.md default learn targets amended (A1; approved);
  A4 widened the placeholder regex to skip `${…}` (no bundled template uses it); A3 fixed
  README description extraction to stop at the next heading; E2 ran before D1 (skill text
  only).
- **Deferred to `doctor`** (STATE.md open items): live store refresh, pinned
  `learn.targets`, installed skill refresh.
- The B2 coding agent hit an API session limit before its own commit; its work was
  verified (lint + 491 passed) and committed by the coordinator.
