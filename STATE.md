# MetaProject — State

## Process

TDD per plan.md/AGENTS.md. Tests written before implementation for each deliverable.

## Implementation phases (plan.md §2)

- [x] Phase 0 — Schema & configuration
  - `src/metaproject/db.py`: `init_schema` additively creates `learn_proposals`,
    `learn_evidence`, `learn_runs` (spec.md §5.4.8 columns) plus the three named indexes
    (`learn_proposals(status, evidence_score)`, `learn_proposals(target_file)`,
    `learn_evidence(proposal_id)`), guarded by `table_names()` checks matching the
    existing `projects` table idiom. `projects` table untouched.
  - `src/metaproject/config.py`: added `LearnConfig` dataclass + `Config.learn: LearnConfig`
    field (default_factory), matching spec.md §4.2 defaults (`targets`, `resurface_factor`,
    `model`, `activity_weights`). `Config.__post_init__` coerces a plain dict (as loaded
    from JSON via `Config.from_dict`) into `LearnConfig`, filtering unknown keys the same
    way `Config.from_dict` does.
  - `src/metaproject/git.py`: added `ensure_template_repository()` — no-op if
    `target_dir` is already a git repo, otherwise delegates to existing `init_repository()`
    (branch `main`, commit `chore: initial template store`). Idempotent by construction.
  - `src/metaproject/cli.py`: `init_cmd` calls `ensure_template_repository` on
    `templates_dest` right after templates are seeded/copied, in both the `--force` and
    fresh-init paths.
  - Tests added: `tests/test_db.py` (new file), additions to `tests/test_config.py`,
    additions to `tests/test_scaffold.py`.
  - Gate results: `make lint` clean. `make test` → `61 passed` (full suite, including all
    pre-existing tests).
- [ ] Phase 1 — Collect & guard
- [ ] Phase 2 — Score & store
- [ ] Phase 3 — Synthesize
- [ ] Phase 4 — Apply
- [ ] Phase 5 — Acceptance TUI
- [ ] Phase 6 — `new_template` proposals & `review` integration
- [ ] Phase 7 — Documentation & release

## Design invariants (regression guards)

- The templates directory (`~/.metaproject/templates`) is now git-backed by `init`. Any
  code that walks that directory for scaffolding (`templates.render_template_tree`) must
  skip `.git` — `render_template_tree` now explicitly excludes any path whose parts
  contain `.git`. Without this, `metaproject new` crashes trying to UTF-8-decode git
  pack/object files. This was a real regression caught by `test_e2e.py`, not a
  hypothetical — future template-tree walkers (e.g. `learn`'s `collect.py`) need the same
  guard.
- `review.get_template_source` iterates `templates_dir.iterdir()` (top-level only) and
  name-matches via `transform_template_name`; `.git` never matches a standard deliverable
  name so it's harmless there — no change needed.
- `db.init_schema` pattern: each table is independently guarded by its own
  `if "<table>" not in db.table_names()` block, so partial-upgrade databases (e.g. one
  that somehow has `learn_proposals` but not `learn_evidence`) still self-heal on the next
  `get_db()` call.
- `Config.from_dict` filters unknown top-level keys for forward compatibility; `LearnConfig`
  mirrors this with its own `from_dict` classmethod so a future config key added to the
  `learn` block doesn't break older code loading a newer config file.

## Open items carried into plan.md

- None blocking. Phase 0 gate fully met; no scope was narrowed.

## Verified facts (do not re-investigate)

- `sqlite_utils` `Table.indexes` entries expose columns as a plain list of strings
  (`idx.columns`), not objects with a `.name` attribute — relevant when asserting index
  shape in tests.
- `tests/conftest.py`'s `isolate_test_environment` autouse fixture sets
  `METAPROJECT_CONFIG_DIR` per test via `tmp_path_factory`; `config.get_config_dir()`
  honors it. No additional isolation fixture is needed for `learn`-related tests.
- `metaproject init --force` skips the interactive `questionary` prompts entirely (see
  `cli.py`'s `if not force:` guard), so CLI-runner tests that need a non-interactive full
  init should pass `--force` rather than mocking `questionary`.
- `make install` / test commands require `dangerouslyDisableSandbox: true` in this
  environment — the default sandbox blocks `uv`'s cache directory
  (`~/.cache/uv/sdists-v9/.git`) with "Operation not permitted". `.venv/bin/pytest` and
  `.venv/bin/ruff` (used directly, not via `uv run`) also need the disabled sandbox to
  write `.pytest_cache`/etc. under this worktree.
