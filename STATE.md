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
- [x] Phase 1 — Collect & guard
  - `src/metaproject/learn.py` **deleted**, along with its three public functions
    (`extract_file_additions`, `learn_from_project`, `apply_learned_enhancement`) and
    `learn_workspace`. Replaced by the `src/metaproject/learn/` package.
  - `src/metaproject/learn/collect.py`: `normalize_text` (CRLF fold, per-line trailing
    whitespace strip, single trailing newline), `project_variables` (title/description
    from `universe.extract_title`/`extract_description`, so a template renders as that
    project would have been scaffolded), `resolve_template` (per-component
    `transform_template_name` match, `.git` skipped), `iter_target_files` (directory
    targets ending in `/` expand; symlinks and symlinked directories are never followed),
    `classify`, `collect_project`, `iter_project_dirs`, `collect_workspace`. Emits frozen
    `EvidenceRecord`s carrying a unified diff (n=3) plus the non-blank `added_lines`.
  - `src/metaproject/learn/guard.py`: `GitignoreMatcher` (dependency-free `.gitignore`
    parser), `redact`/`contains_secret`, `is_denylisted`, `exclusion_reason`,
    `filter_paths`, `build_manifest`/`SendManifest`, `guard_evidence`, `confirm_send`.
  - `src/metaproject/cli.py`: `learn_cmd` reduced to a transitional stub that prints
    "`metaproject learn` is being rebuilt" and exits 1. It writes nothing. The real
    subcommand surface (spec.md §5.4.4) is wired in Phase 4.
  - Tests: `tests/test_learn_collect.py` (24) and `tests/test_learn_guard.py` (48), both
    new. `tests/test_learn.py` **deleted** — its four tests exercised only the deleted
    legacy functions and the old CLI behavior; they are replaced, not ported.
    `tests/test_e2e.py`'s learn step now asserts the stub exits 1 *and* leaves the
    template store byte-identical. `pyproject.toml` gains `"."` to `pythonpath` so tests
    can import `tests.fixtures.learn_workspace.build`.
  - Gate results: `make lint` clean. `make test` → `129 passed` (57 pre-existing retained,
    4 legacy learn tests deleted, 72 new). Acceptance cases asserted here: C1, C5, C6, C7,
    C11, C18, C19, C20, C23, C24, C26, C28. Each of the three headline gates was
    mutation-checked (disable redaction → 10 failures; disable normalization → 4; diff the
    raw template instead of the rendered one → 2), so none of them passes vacuously.
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
- **Render before diffing, always.** The whole placeholder false-positive class comes back
  the moment any code path compares a project file to a raw template. `collect.py` renders
  with `project_variables()` first; `guard`/`score`/`synth` must never re-derive evidence
  from raw template text.
- **Normalize before diffing, always.** `normalize_text` runs on both sides. Skipping it
  makes a CRLF project file (fixture `lattice`) differ on every line, which is the most
  likely source of silent false-positive noise on a real workspace.
- **The guard is the single egress chokepoint.** `guard_evidence` re-checks path exclusion
  even though `collect` already enumerated only target files. Later phases must send
  `GuardResult.records`, never raw `EvidenceRecord`s, and must not add a second path from
  collected evidence to `synth`.
- **Denylist is deliberately two-tier.** `*secret*`/`*credentials*` matching a `.md`/`.rst`/
  `.txt`/`.adoc` file excludes only when the content is actually credential-shaped. A
  blanket filename exclusion would drop `cipher/secrets.md`, which is documentation and
  exactly the kind of content `learn` exists to harvest (acceptance case C20). Do not
  "simplify" this into a flat denylist.
- **Redaction must stay precise.** Hex strings, UUIDs, and tokens under 32 characters are
  exempt from the entropy rule, so git SHAs, UUIDs, and base64 test vectors survive.
  Raising aggressiveness to catch more will start eating the signal.
- Removals are never evidence. `_added_lines` only reports insertions/replacements, so a
  zero-byte project file (fixture `husk`) cannot become a deletion proposal.

## Open items carried into plan.md

- `README.md` §5 still documents the deleted line-diff harvester (`metaproject learn` as an
  append-to-template command). It is stale as of Phase 1 and is rewritten in Phase 7.
- `metaproject learn` is a stub that exits 1 until Phase 4 wires the real subcommands. This
  is deliberate: the alternative was keeping the legacy behavior alive, which is the thing
  being removed.
- Only the project-root `.gitignore` is parsed; nested per-directory ignore files and
  `.git/info/exclude` are not. Not needed by any acceptance case, and the hard denylist is
  the backstop. Revisit if a real workspace shows it matters.
- C22's open question ("should Archived projects be scanned at all?") is answered
  *yes, at weight 0.1*: `collect` scans them and records the classification. The weighting
  itself is Phase 2's.

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
- `tests/fixtures/learn_workspace/build.py` is importable as
  `tests.fixtures.learn_workspace.build` only because `pyproject.toml`'s
  `[tool.pytest.ini_options] pythonpath` now includes `"."`. There is no `tests/__init__.py`;
  it resolves as an implicit namespace package.
- `build_workspace()` must be given a `tmp_path` under a directory the sandbox can write.
  It calls `os.utime` on `beacon/outside.link`, a symlink pointing above the workspace root,
  and `utime` follows the link — building into the system temp dir fails with
  `PermissionError`. pytest's `tmp_path` is fine; ad-hoc `tempfile.mkdtemp()` may not be.
- Measured Shannon entropy of the fixture tokens (bits/char), which is why the redaction
  threshold is 4.2 over a 32-character minimum: AWS example key 4.61 (redacted), git SHA
  3.94 (hex-exempt anyway), UUID 3.66, base64 test vector 4.35 but only 28 chars long.
  `ghp_`/`sk_live_` tokens sit *below* 4.2, so prefix shapes — not entropy — are what catch
  them.
- `universe.resolve_project_timestamp` uses the last *commit* time for a clean git repo, so
  the fixture's `atlas` classifies from its build-time commit rather than its stamped
  mtimes. It still lands on `Active Now`, matching `expectations.json`.
- `difflib.SequenceMatcher(autojunk=False)` matters here: with autojunk on, files with many
  repeated lines (the generated `spire/docs/reference.md`) diff wrongly.
