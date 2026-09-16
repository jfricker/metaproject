# MetaProject — State

## Process

<!-- each stage ticks its own item here as it completes -->
- [x] 1. write-intent: intent.md approved
- [x] 2. generate-spec: spec.md approved
- [x] 3. generate-design: design.md approved
- [x] 4. generate-plan: plan.md approved
- [x] 5. implement-plan: code and tests written
- [x] 6. execute-tests: tests passing
- [ ] 7. wrapup: cycle archived

## Implementation phases

<!-- written by implement-plan as steps land -->
- [x] 1. Scan-root hard scoping: `resolve_scan_root`/`UniverseScopeError` in universe.py; CLI refuses outside roots before opening the DB (e5f0d7a)
- [x] 2. Dependency: `textual==8.2.8` exact pin in pyproject.toml (23fd333)
- [x] 3. `gitinfo.py`: bounded (5s) subprocess inspection, staleness scoring with separate uncommitted flag, neutral for detached/unknown base (23fd333)
- [x] 4. `universe_tui.py`: Textual list → project detail → worktree detail; DB-read on open, `r` rescans, read-only
- [x] 5. CLI wiring: `--no-tui`, TUI as default no-args interface behind `tui_enabled`, lazy Textual import; table path unchanged
- [x] 6. Tests: test_gitinfo.py (18), test_universe_tui.py (13), test_universe.py updated for scoping; suite 637 passed

## Design invariants (regression guards)

<!-- written by implement-plan/execute-tests; appended to docs/DESIGN-INVARIANTS.md by wrapup -->

## Open items carried into plan.md

<!-- written by implement-plan/execute-tests; resolved with the operator by wrapup -->

## Verified facts (do not re-investigate)

<!-- written by implement-plan/execute-tests; appended to docs/VERIFIED-FACTS.md by wrapup -->
- Textual apps need a headless pilot run (`app.run_test`) in the suite: builder and
  gate tests passed while the real `ProjectDetailScreen` crashed on mount (path string
  where a record was expected). Fixed in 206db10; pilot test kept as a regression guard.
- Worktree gate run: `--basetemp=/private/tmp/mp-gate-final`, suite run unsandboxed
  (git-writing tests); 638 passed, ruff clean, wheel builds (2026-09-16).
