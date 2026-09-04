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
- [x] Phase 2 — Score & store
  - `src/metaproject/learn/score.py`: `activity_weight` (config table lookup, `Idle` as the
    fallback for an unknown/absent classification), `recency_factor` (half-life decay,
    `RECENCY_HALF_LIFE_DAYS = 30`, clamped at 1.0 for a future mtime), `weigh_project`
    (`activity * (1 + RECENCY_BONUS * recency)`, `RECENCY_BONUS = 0.5`), `project_age_days`
    (delegates to `universe.resolve_project_timestamp`), `candidate_key`, `group_candidates`,
    `rank_candidates`, `order_queue`. Emits frozen `Candidate`s (each carrying frozen
    `ProjectWeight` contributions with `activity`, `recency`, `age_days`, `weight` and the
    contributing `excerpt`), with `evidence_count`/`evidence_score` as derived properties.
  - `src/metaproject/learn/store.py`: `normalize_for_hash`, `content_hash`, `evidence_hash`,
    `should_resurface`, `upsert_proposal`, `replace_evidence`, `reject_proposal`,
    `forget_proposal_by_hash`, `mark_applied`, `set_edited_body`, `is_suppressed`,
    `list_proposals`, `get_proposal`/`get_proposal_by_hash`/`get_evidence`,
    `start_run`/`finish_run`/`get_run`/`latest_run`. Raw `db.conn` SQL throughout, so the
    module is the single SQLite surface for `learn`.
  - `src/metaproject/learn/__init__.py` re-exports both modules. `cli.py` is untouched:
    the `learn` stub still exits 1, exactly as Phase 1 left it.
  - **R3 hashing decision.** Two namespaced hash domains, both over `normalize_for_hash`
    output (CRLF folded, per-line whitespace collapsed, blank lines dropped) and never over
    raw model prose: `content_hash(target_file, body, kind)` is the primary identity that the
    schema's `content_hash` column stores, and `evidence_hash(target_file, excerpts, kind)`
    is R3's named fallback — the normalized, deduplicated, sorted *set* of evidence excerpts,
    which is model-wording-independent and (because it is a set of distinct excerpts, not of
    contributors) stable as more projects join a candidate. Phase 3 picks which one it feeds
    to `upsert_proposal`; nothing else changes if it switches.
  - Tests: `tests/test_learn_score.py` (31) and `tests/test_learn_store.py` (33), both new.
    Acceptance cases asserted here: C2 (the eleven contributing projects, by name), C3, C4,
    C10, C15, C22. C13 ("project-specific text is not promoted") is Phase 3's — it is a
    property of what the model is allowed to emit, and there is no model yet.
  - Gate results: `make lint` clean. `make test` → `193 passed` (129 pre-existing retained,
    64 new). Each headline gate was mutation-checked: flattening the activity table → 10
    failures; unbounding the recency term → 2; keying the contribution dict per-line instead
    of per-project → 1; making the resurfacing comparison non-strict → 2; hashing raw instead
    of normalized content → 3. None passes vacuously.
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
- **Recency is a bounded bonus, not a second axis.** `weigh_project` multiplies the
  activity weight by `1 + 0.5 * recency`, so recency only ever reorders projects *within*
  an activity class. `universe` classification is already coarsely recency-derived; letting
  recency scale freely would double-count it and let a freshly-touched `Ancient` project
  outrank a stale `Active Now` one. There is a test for exactly that.
- **Frequency counts distinct projects, never occurrences.** `group_candidates` keys
  contributions by project path, so `spire/docs/reference.md`'s 6000 repetitions of one
  phrase are one project's opinion. Any future regrouping must preserve that key.
- **`evidence_score` is a plain sum of contribution weights**, so the number is always
  explainable by the provenance list. The consequence is deliberate and should not be
  "fixed": fractional weights mean what they say, so ~10 `Archived` projects carry about
  as much weight as one `Active Now` project. The Phase 2 gate ("a single-project candidate
  ranks below a corroborated one") holds at equal activity, which is spec.md §5.4.2's
  "accumulates ... weighted".
- **Status belongs to the ledger, not to the scan.** `upsert_proposal` refreshes content,
  counts, and score on every scan, but cannot reopen an `applied` proposal and cannot
  overturn a `rejected` one except through `should_resurface`. That single path is what
  makes rejection durable; adding a second way to set `status = "pending"` would silently
  restore the legacy "forgets every rejection" behavior.
- **Resurfacing is strictly greater than.** `evidence_score > rejected_score * factor`.
  Equal is not stronger evidence; making it `>=` re-surfaces a candidate on an unchanged
  workspace whenever `rejected_score` is 0.
- **Evidence rows are replaced, never appended.** `learn_evidence` describes the current
  scan; appending would inflate `evidence_count` forever and quietly clear every
  resurfacing bar.
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
- `score.py` groups evidence into candidates by normalized line, one line per candidate.
  That is the deterministic corroboration signal; it is not the proposal. Phase 3's `synth`
  is what turns a cluster (or several related clusters) into a coherent proposal body, and
  it may regroup. `group_candidates` exists so frequency/recency/activity can be measured
  and gated before any model runs.
- C13 ("project-specific text is not promoted") is listed in `expectations.json` as a
  Phase 2 case but is really Phase 3's: it constrains what the model may emit. `collect`
  already strips the placeholder class; the remaining absolute-path/project-name leak is a
  synthesis concern. Assert it in `tests/test_learn_synth.py`.
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
- The C2 line (`- Run \`make check\` before every commit.`) is corroborated by exactly the
  eleven projects `expectations.json` names, as produced by
  `group_candidates(guard_evidence(collect_workspace(...)).records)`. Verified, not assumed:
  `echo` (different wording), `notes` (not a project root), `quarry`, `husk`, and `orbit`
  are correctly absent. `test_c2_contributing_projects_are_exactly_the_eleven_expected`
  asserts the set by name, so a regression in any earlier stage surfaces here.
- The full fixture workspace scores C2 at roughly 11.5 and the C4 one-off at roughly 0.43,
  so C15's resurfacing cannot be demonstrated by adding a few projects to the full
  workspace — doubling 11.5 is out of reach. `test_c15_...` therefore builds with
  `build_workspace(tmp_path, only=["atlas", "relic"])` (score ~1.7), rejects, then rebuilds
  the full workspace at the same path. `build_workspace` `rmtree`s and recreates only
  `<dest>/learn_workspace`, so a `universe.db` kept at `tmp_path` survives the rebuild —
  which is what makes "extend the workspace, never edit the ledger" testable.
- `sqlite3` `cursor.lastrowid` after an `INSERT` through `db.conn` is the new row's id;
  `sqlite_utils`' own `insert()` is not needed and is not used in `store.py`.
- `difflib.SequenceMatcher(autojunk=False)` matters here: with autojunk on, files with many
  repeated lines (the generated `spire/docs/reference.md`) diff wrongly.
