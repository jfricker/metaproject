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
    to `upsert_proposal`; nothing else changes if it switches. **Phase 3 chose
    `evidence_hash`** — see the Phase 3 entry for the measurement behind it. Both
    functions remain; `content_hash` is now unused by the pipeline and kept as the
    documented alternative.
  - Tests: `tests/test_learn_score.py` (31) and `tests/test_learn_store.py` (33), both new.
    Acceptance cases asserted here: C2 (the eleven contributing projects, by name), C3, C4,
    C10, C15, C22. C13 ("project-specific text is not promoted") is Phase 3's — it is a
    property of what the model is allowed to emit, and there is no model yet.
  - Gate results: `make lint` clean. `make test` → `193 passed` (129 pre-existing retained,
    64 new). Each headline gate was mutation-checked: flattening the activity table → 10
    failures; unbounding the recency term → 2; keying the contribution dict per-line instead
    of per-project → 1; making the resurfacing comparison non-strict → 2; hashing raw instead
    of normalized content → 3. None passes vacuously.
- [x] Phase 3 — Synthesize
  - `src/metaproject/learn/synth.py`: `Bundle`/`Proposal`/`SynthResult` (all frozen),
    `bundle_evidence` (one bundle per target file, never per target × kind, so a target
    that resolves to a template for some projects and not others still costs one call),
    `measure`, `render_block`, `build_prompt`, `build_reduce_prompt`, `split_record`,
    `chunk_bundle`, `resolve_claude`, `claude_command`, `run_claude`, `parse_response`,
    `normalize_excerpt`, `is_generalizable`, `validate_proposal`, `synthesize`.
  - `src/metaproject/exceptions.py`: added `ModelUnavailableError` (missing `claude`) and
    `ModelOutputError` (unparseable or schema-violating model output, and a non-zero
    `claude` exit). Both `MetaProjectError` subclasses, so Phase 4's CLI turns either into
    a non-zero exit with one `except`.
  - `learn/__init__.py` re-exports the new surface; `AGENTS.md` §6 gains the `synth.py`
    bullet. `cli.py` is untouched — `learn` is still the Phase 1 stub that exits 1, and
    wiring the real subcommands remains Phase 4's.
  - **Invocation (R8).** `claude_command()` is the single place the CLI contract lives:
    `[claude, "-p"]` plus `["--model", M]` when a model is configured. The prompt goes on
    **stdin**, not argv — an evidence bundle routinely exceeds `ARG_MAX`. `resolve_claude`
    runs *first* in `synthesize`, before any prompt is assembled, so a missing binary
    fails having done nothing.
  - **R3 hashing decision: `evidence_hash`, not `content_hash`.** A proposal's identity is
    `store.evidence_hash(target_file, verified_source_lines, kind)`. Rationale, measured
    rather than assumed (`test_r3_hashing_the_model_body_would_not_have_been_stable`): the
    model rewords itself between runs on identical input, so hashing the generated body
    mints a fresh identity every scan and silently resurrects every rejection — R3's exact
    failure. The evidence set is produced entirely by `collect`/`guard`, which are
    deterministic, so an unchanged workspace yields a byte-identical hash no matter what
    the model wrote. The column stays named `content_hash`; it holds identity, not a hash
    of the body.
  - **Provenance is derived, never accepted.** The schema asks the model for
    `source_lines` — evidence lines it claims to be generalizing. Each is matched back
    against the bundle's actual `added_lines` (whitespace-insensitively, the same
    normalization `score.candidate_key` uses) and dropped if it is not really there;
    contributing projects are then computed from the survivors, and a model-supplied
    `contributing_projects` key is ignored outright. A proposal citing no real evidence is
    discarded. This is also what makes each proposal's hash proposal-specific rather than
    per-target.
  - **Context budget is measured (R4).** `chunk_bundle` renders the prompt envelope once
    and measures each evidence block as the UTF-8 bytes it actually contributes; the check
    is `len(head) + sum(len(block)) + len(tail) <= budget_bytes`, on the exact strings
    sent, never a token estimate or a record count. `DEFAULT_BUDGET_BYTES = 200_000`. A
    single record too large on its own is split along diff lines by `split_record`
    (lossless and order-preserving — asserted by rejoining the pieces), never truncated.
    More than one chunk triggers a final reduce call, so calls per target file are
    `chunks + 1`.
  - Tests: `tests/test_learn_synth.py` (54), new. Acceptance cases asserted here: C8, C13,
    C16, C17, C25. Each headline gate was mutation-checked: dropping the generalization
    check → 6 failures; `MAX_ATTEMPTS = 1` → 3; skipping `chunk_bundle` → 2; trusting
    unverified `source_lines` → 2; not neutralizing the evidence fence → 1; keeping unknown
    model keys at the parse boundary → 1. None passes vacuously.
  - Gate results: `make lint` clean. `make test` → `247 passed` (193 pre-existing retained,
    54 new).
- [x] Phase 4 — Apply
  - `src/metaproject/learn/apply.py`: `Section`/`ApplyPlan`/`ApplyResult` (all frozen),
    `normalize_heading`, `iter_sections`, `resolve_section`, `body_is_present`, `splice`,
    `template_name`/`template_destination`, `proposal_body`, `evidence_project_names`,
    `resolve_template_file`, `plan_apply`, `ensure_clean_repository`, `commit_message`,
    `commit_file`, `apply_plan`, `apply_proposal`. The only module in `learn` that writes
    to a template.
  - `src/metaproject/learn/api.py`: the public surface — `scan` (stages 1–4), `review`,
    `parse_since`, `ScanResult`, and `reject_proposal` re-exported from `store`. It
    imports nothing from `apply`, so a scan cannot reach the write path even by mistake.
  - `src/metaproject/exceptions.py`: added `ApplyError` (dirty template repository,
    unresolvable template file, refused R7 fallback). A `MetaProjectError` subclass, so
    `cli.py` turns it into a non-zero exit with the same `except` as the Phase 3
    model errors.
  - `src/metaproject/cli.py`: the Phase 1 `learn` stub is replaced by a `typer.Typer`
    **command group** (`learn_app`, `no_args_is_help=True`) carrying `scan`, `list`,
    `show`, `apply`, `edit`, `reject` — spec.md §5.4.4 minus the Phase 5 TUI entries
    (`learn [root]` default mode and `learn review`). Helpers: `learn_db`,
    `resolve_templates_dir`, `open_in_editor`, `render_proposal_table`, `print_plan`,
    `apply_one`. `--templates` is accepted on every subcommand.
  - **Splicing (C12).** `splice` inserts at the end of the named section's content,
    before the next heading of the same or a shallower level. Headings inside fenced
    code blocks are not structure. Heading matching is exact on `normalize_heading`
    (hashes, case and internal spacing removed) and nothing looser — a fuzzy match is
    the silent misplacement R7 warns about. No banner is ever written; the legacy
    "Added via metaproject learn" EOF append is gone and asserted gone.
  - **R7 fallback.** An unresolvable `target_section` is never faked and never
    approximated. `splice` appends at end of file, sets `ApplyPlan.fallback_reason`
    naming the missing heading, and `print_plan` prints it as a warning above the diff
    before the confirmation prompt. The commit message records it too
    (`Section '...' was not present; appended at end of file.`). `apply_plan(...,
    allow_fallback=False)` is how a reviewer refuses, and raises `ApplyError` having
    written nothing.
  - **Commits (R6).** `ensure_clean_repository` refuses both a non-repository template
    store and a dirty worktree, before any write. Each accept stages exactly one file
    and makes exactly one commit, subject `learn: <title>`, body naming
    `#<proposal id>`, the target file, the placement, the rationale,
    `Contributing projects: ...`, and `Proposal-Hash:`. Accepts are never batched:
    `learn apply --all` loops one-commit-per-proposal.
  - **A no-op accept makes no commit.** If the template already carries the body,
    `apply_plan` marks the proposal `applied` with `commit=None` rather than making an
    empty commit.
  - Tests: `tests/test_learn_apply.py` (28) and `tests/test_learn_cli.py` (17), both new.
    `tests/test_e2e.py`'s learn step was updated for the command group (see the design
    invariant below). Acceptance cases asserted here: C12, C14, C21, C27.
  - Gate results: `make lint` clean. `make test` → `292 passed` (247 pre-existing
    retained, 45 new). Each headline gate was mutation-checked: forcing `resolve_section`
    to `None` (always append) → 5 failures; making `proposed_body` win over `edited_body`
    → 1; skipping `ensure_clean_repository` → 2; dropping the contributing-project line
    from the commit message → 2; never setting `fallback_reason` → 3; making the CLI exit
    0 on a `MetaProjectError` → 1; having `scan` write into the template store → 3. None
    passes vacuously.
- [x] Phase 5 — Acceptance TUI
  - `src/metaproject/learn/tui.py`: the `rich` review loop (spec.md §5.4.5). Public
    surface: `SessionResult`, `tui_enabled`, `stdout_is_a_terminal`, `should_open_tui`,
    `effective_view`, `toggle_view`, `order_for_review`, `open_in_editor`, `read_key`,
    `diff_rows`, `side_by_side_table`, `unified_view`, `header_line`,
    `provenance_lines`, `render_candidate`, `run_review`. No `textual`, no widget
    framework: `run_review` reads one keystroke, repaints, and loops (R9).
  - **Keystroke → subcommand delegation.** `a` and `e` call `plan_apply` / `apply_plan`
    (exactly what `cli.apply_one` calls), `d` calls `store.reject_proposal` (exactly
    what `learn reject` calls), `e` additionally calls `store.set_edited_body` and the
    same `open_in_editor`. `s` writes nothing. There is no TUI-only write path.
  - `src/metaproject/cli.py`: `learn` is now a `LearnGroup` (a `TyperGroup` subclass)
    whose `parse_args` routes anything that is not a known subcommand — including no
    args at all — to a hidden `__default__` command. That is what makes
    `metaproject learn [ROOT]` the scan-then-review default without an optional
    positional on the group swallowing `learn scan` as a path. `--help` still belongs
    to the group. New: `learn review [--target] [--status] [--min-score] [--no-tui]`.
    New helpers: `perform_scan` (shared by `learn scan` and the default mode, so the
    two cannot scan differently) and `open_review_queue` (the TUI-or-table decision,
    shared by the default mode and `learn review`).
  - `cli.open_in_editor` is now a three-line delegation to `tui.open_in_editor`; the
    implementation moved rather than being copied.
  - **`learn edit`'s aborted-edit exit code changed from 1 to 0.** Phase 4 left this
    open. spec.md §5.4.10 says an aborted edit means "keep the candidate pending, stay
    in the TUI" — a deliberate no-op, not a failure — and under "one queue, two
    interfaces" the subcommand is the same action reached another way, so it now prints
    the same message and returns zero, matching `learn apply`'s existing behavior when
    the diff confirmation is declined. `tests/test_learn_cli.py::
    test_edit_aborted_leaves_the_candidate_pending` was updated accordingly.
  - `tests/test_e2e.py`'s learn step was rewritten for the new default: it mocks
    `synth.resolve_claude` / `synth.run_claude` (returning zero proposals), asserts
    `metaproject learn <root> --yes` and the bare `metaproject learn --yes` both exit
    **zero**, and keeps the byte-identical template-store assertion around every form
    including the new `learn review --no-tui`.
  - Tests: `tests/test_learn_tui.py` (20, new) and 8 additions to
    `tests/test_learn_cli.py`.
  - Gate results: `make lint` clean. `make test` → `320 passed` (292 pre-existing
    retained, 28 new). Each headline gate was mutation-checked: making `s` also reject
    → 5 failures; making `effective_view` never degrade → 2; letting an empty queue
    open the reviewer → 1; ignoring `no_tui` → 2; ignoring `TERM=dumb` → 2; making an
    aborted edit advance → 1; making `a` skip `apply_plan` → 4. None passes vacuously.
- [x] Phase 6 — `new_template` proposals & `review` integration
  - **`new_template` needed no new machinery, only an end-to-end assertion.** Phases 1–4
    had already built the seam: `collect.collect_project` sets `kind = "new_template"`
    when `resolve_template` finds nothing, `synth.bundle_evidence` carries that kind on
    the bundle, `store.ProposalDraft` persists it, and `apply.resolve_template_file`
    routes it to `apply.template_destination`, where a non-existent file yields
    `PLACEMENT_NEW_FILE`. Phase 6's work was to prove the whole chain rather than each
    link: `tests/test_learn_apply.py::
    test_c9_a_recurring_untemplated_file_becomes_a_new_file_in_the_template_store`
    scans kiln/beacon/quarry (mocked runner) with `targets=["Makefile"]`, asserts the
    ledger row is `kind == "new_template"` with `evidence_count == 3`, and applies it —
    asserting `templates/Makefile.template` now exists, that
    `transform_template_name` maps it back to `Makefile` (so the walker will render it
    for the next `metaproject new`), that the accept staged exactly that one file, and
    that the worktree is clean afterwards. **No production change was required for
    this half of the gate**; it is recorded as verified, not as newly built.
  - `src/metaproject/learn/drift.py` (new): `review` findings reduced to a scoring
    signal. Public surface: `added_lines`, `DriftSignal` (`lines`, `missing`, `pairs`,
    `reports`), `EMPTY_DRIFT`, `collect_drift`. It calls `review.review_project` behind
    a late import and a `reviewer=` seam, and **`src/metaproject/review.py` is
    byte-unchanged** (R10).
  - `src/metaproject/learn/score.py`: added `DRIFT_BOOST = 0.25`, `drift_factor()`, a
    `drift: bool = False` parameter on `weigh_project`, and a `drift: Optional[
    DriftLookup]` parameter on `group_candidates`. `DriftLookup` is a `Protocol`, so
    `score` does not import `drift` (which imports `review`) and scoring stays a pure
    function of evidence plus a lookup.
  - `src/metaproject/learn/api.py`: `scan()` gained `drift: Optional[DriftSignal] =
    None`. When absent it calls `collect_drift(projects, templates_dir)` — **after** the
    egress confirmation, so a declined scan does no work — and each contributing
    project's weight becomes `base * drift_factor(...)`. `api` still imports nothing
    from `apply`.
  - `src/metaproject/learn/__init__.py`: re-exports the four `drift` names plus
    `drift_factor`.
  - Tests: `tests/test_learn_drift.py` (11, new) and 2 additions to
    `tests/test_learn_apply.py`.
  - Gate results: `make lint` clean. `make test` → `333 passed` (320 pre-existing
    retained, 13 new). Non-vacuity checked by setting `DRIFT_BOOST = 0.0`: 3 failures,
    including the end-to-end gate test.
- [x] Phase 7 — Documentation & release
  - `README.md`: §5 rewritten from scratch. The stale line-diff harvester documentation
    (`metaproject learn --yes` appending additions to templates) that Phase 1 deleted the
    code for is gone. It now documents the corroborated-proposal pipeline: the six stages
    and who decides each, the default scan-then-review mode, `scan`, `review`, `list`,
    `show`, `apply`, `edit`, `reject` with their flags, the TUI keymap and its three
    degradation triggers, rejection/resurfacing semantics, `new_template` proposals, the
    `claude -p` requirement and the failure modes, and a "Safety properties" subsection
    covering scan-never-writes, the egress manifest and redaction, model-output-as-data,
    verified provenance, the git-backed store with one commit per accept, and the
    admitted-append placement fallback. The Features bullet was updated to match.
  - `AGENTS.md`: added the missing `drift.py` bullet to §6 (Phase 6 shipped the module but
    only extended §6's other entries); corrected the "Key Files" `learn/` line, which still
    read "`collect`, `guard`, `score`, `store`; further stages per `plan.md`"; corrected §1
    to describe `learn` as a command group with a hidden default command and record that a
    new subcommand must be registered on `learn_app` or it is silently read as a path;
    relabeled the `learn` box in the architecture diagram.
  - `src/metaproject/cli.py`: the **only** production change in this phase. The `learn`
    group's help text now documents the default mode's own surface. See the §5.4.4 gate
    note below for why.
  - `tests/test_learn_cli.py::test_learn_help_lists_every_subcommand` extended to assert
    `[ROOT]`, `--no-tui` and `--templates` appear in the group help, so the gate cannot
    silently regress.
  - **§5.4.4 `--help` gate.** Every subcommand's `--help` was captured and diffed against
    the spec table. Seven of the eight rows matched exactly. The eighth — row 1,
    `metaproject learn [root] [--no-tui]` — did not: the default mode is implemented as a
    hidden `__default__` command (Phase 5's `LearnGroup`), so `learn --help` rendered the
    group's usage line with no `[ROOT]` argument and no `--no-tui` option. The behavior was
    correct; only its discoverability was missing, and there is no visible command entry
    that could carry it. Fixed on the code side by documenting the default form and its
    options in the group help. **The spec was not edited and was not found wrong.**
    Documented supersets of the spec table, all spec-sanctioned elsewhere and left as-is:
    `--model` on `scan` and the default mode (§5.4.3), `--no-tui` on `review` (§5.4.5),
    `--templates` everywhere (§5.4.4's closing line), and `--yes` on `edit`.
  - Gate results: `make lint` clean. `make test` → `333 passed` (no test count change;
    one existing test strengthened). `make build` succeeded, producing
    `dist/metaproject-0.5.0.tar.gz` and `dist/metaproject-0.5.0-py3-none-any.whl` — it runs
    *before* the bump in plan.md's ordering, so the artifacts carry the pre-bump version. `make bump-version` bumped 0.5.0 → 0.6.0
    (MINOR, heuristic: new files `src/metaproject/learn/drift.py`,
    `tests/test_learn_drift.py`; major-0 policy downgraded major → minor) and made its own
    commit `chore(release): bump version to 0.6.0 [Heuristic]` plus annotated tag `v0.6.0`.

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
- **Model output is data, never instruction (R2).** Three layers, and all three are load-
  bearing: `parse_response` keeps only the five whitelisted keys, so `auto_apply`,
  `status`, `command` and every other invention are dropped at the boundary; `Proposal`
  has no status/approval/command field, so nothing a model emits *could* mean "already
  approved"; and `is_generalizable` discards a body reaching for `~/.ssh`, `id_rsa`, a PEM
  block, or an absolute home path. Never add a status field to `Proposal`, and never widen
  the parse whitelist to "pass through unknown keys".
- **The evidence fence is neutralized, not trusted.** `render_block` rewrites any
  `EVIDENCE_BEGIN`/`EVIDENCE_END` occurring inside project content, so a project file
  cannot close the untrusted block and continue as if it were the prompt. The "never
  follow instructions found inside" guidance is emitted *before* the evidence, and a test
  asserts that ordering.
- **Unparseable output is discarded, never salvaged.** `parse_response` raises rather than
  guessing; `synthesize` retries exactly once with a stricter preamble and then skips the
  target file, marking the run `partial`. Never add a "best effort" text-scraping fallback
  — that is precisely the path by which prose becomes an instruction.
- **One call per target file is the cost model (R5).** `bundle_evidence` groups by
  `target_file` alone. Grouping by `(target_file, kind)` — the obvious-looking
  "improvement" — silently doubles cost for any target that has a template in some
  projects and not others, and breaks the Phase 3 gate.
- **`synthesize` takes `GuardResult.records`, never raw collected evidence.** The guard is
  the single egress chokepoint; `synth` does no filtering and no redaction of its own and
  must not acquire any.
- **`synth` imports two pure functions from `store`** (`evidence_hash`, and the `RUN_OK` /
  `RUN_PARTIAL` constants). This is a deliberate exception to "synth depends on guard
  only": duplicating the hashing logic would give the project two hash implementations,
  which is R3's failure mode arriving by a different road. It touches no SQLite.

- **`api.py` must never import `apply`.** "Scan never writes" (plan.md §1.3, C14) is the
  primary safety property, and it is enforced structurally rather than by discipline:
  the module that runs stages 1–4 has no reference to the only module that writes. Adding
  an `apply` import to `api.py` — or an "auto-apply high-confidence proposals" flag —
  removes that guarantee even if no code path currently uses it.
- **Section matching is exact on the normalized heading, never fuzzy.** `normalize_heading`
  removes hashes, case and spacing noise and nothing else. A near-match heuristic
  ("Testing" ≈ "Testing instructions") is exactly R7's silent misplacement, and would
  land content under a heading the operator did not review. When a heading does not
  resolve, the answer is the reviewed append with `fallback_reason` set — never a guess.
- **`fallback_reason` must reach the operator before the write.** `ApplyPlan` computes the
  whole write before anything is written precisely so the reason can be printed above the
  diff. Any future caller of `plan_apply`/`apply_plan` (the Phase 5 TUI included) has to
  surface it; dropping it turns a reviewed append back into a silent misplacement.
- **Headings inside fenced code blocks are not structure.** `iter_sections` tracks ``` and
  ~~~ fences. Template files routinely contain fenced Markdown examples with `#` lines;
  treating those as headings would splice content into the middle of a code block.
- **One accept, one commit, one file staged.** `commit_file` stages the single template
  path, never `git add -A`. R6's whole mitigation is that reverting one commit undoes
  exactly one decision; staging broadly, or batching `--all` into one commit, destroys it.
- **A no-op accept commits nothing.** An empty commit would claim in the history that a
  template changed when it did not. `apply_plan` marks the proposal `applied` with a null
  `applied_commit` instead.
- **`splice` is convergent.** `body_is_present` compares whitespace-normalized lines, so
  re-applying a proposal a template already satisfies is a no-op rather than a duplicate
  paragraph. This is what makes C27 (applied content stops being drift) hold across scans.
- **`resolve_template_file` refuses a stored `template_path` outside the template store.**
  `template_path` comes from a scan row and could in principle point anywhere;
  the containment check is what keeps an accept's blast radius inside the git-backed
  store where it can be reverted.
- **`learn` is a Typer command group with a hidden default command.** Phase 4 had no
  bare form (`learn <path>` exited 2). As of Phase 5, `LearnGroup.parse_args` prepends
  `__default__` to anything that is not a registered subcommand, so both `metaproject
  learn` and `metaproject learn <root>` run the scan-then-review default and exit zero.
  `no_args_is_help` is now False; `--help` is still routed to the group.
- **`learn show` prints provenance as soft-wrapped lines, not as a `rich` table.** The
  whole point of the view is absolute contributing-project paths (spec.md §5.4.4), and a
  table column ellipsizes them at any ordinary terminal width
  (`/private/var/folders/7k/_13bgbq…`). `console.print(..., soft_wrap=True)` emits the
  path in full. Do not "tidy" this back into a table.

- **The TUI is a caller of the subcommands' functions, never a parallel implementation.**
  `run_review`'s `a`/`e` go through `plan_apply` + `apply_plan`, `d` through
  `store.reject_proposal`, `e` through `store.set_edited_body` and `tui.open_in_editor`.
  Adding a TUI-local write — a batched "apply everything at the end", a direct
  `UPDATE learn_proposals`, a second editor helper — reintroduces exactly the divergence
  plan.md §1.3.2 forbids. `tests/test_learn_tui.py`'s three equivalence tests assert the
  resulting ledger row and template bytes against the subcommand's, on identically
  seeded proposals in two identical template stores, so a divergence fails a test rather
  than being caught by review.
- **Nothing is buffered in a review session.** Each keystroke writes through before the
  next repaint, which is what makes "quit mid-session loses nothing" true. `run_review`
  also re-reads the row from the ledger on every repaint rather than trusting the
  snapshot the session opened with, since the queue is shared with the subcommands.
- **`e` does not advance when the edit aborts.** spec.md §5.4.10 is explicit: no
  `$EDITOR`, a non-zero exit, or unchanged text returns to the *same* candidate. Making
  the abort advance silently converts an aborted edit into a skip.
- **Degradation is three independent triggers, and each is testable alone.**
  `stdout_is_a_terminal` exists as a separate seam precisely so a test can force the TTY
  half true and prove that `--no-tui` or `TERM=dumb` is what caused the fallback. Folding
  it back into `tui_enabled` makes both CLI degradation tests vacuous under `CliRunner`,
  whose stdout is never a TTY.
- **The empty-queue rule is enforced twice on purpose.** `should_open_tui` returns False
  for an empty queue, and `cli.open_review_queue` returns early before asking. Neither is
  redundant: the helper protects any future caller, the CLI branch is what prints "the
  templates are current" instead of an empty table.
- **`LearnGroup.parse_args` routes unknown first arguments to the default command.** The
  consequence is deliberate: `metaproject learn scam` is read as a *root path*, not as a
  misspelled subcommand. Hanging an optional positional off the group instead would make
  `learn scan` mean "scan the directory named scan", which is worse. Any new `learn`
  subcommand must therefore be registered on `learn_app`, or it silently becomes a path.
- **The TUI must surface `fallback_reason` before an accept writes.** `render_candidate`
  prints it above the diff, exactly as `cli.print_plan` does. This is the Phase 4
  invariant ("any future caller of `plan_apply`/`apply_plan`, the Phase 5 TUI included")
  discharged, and `test_accept_surfaces_the_fallback_reason_before_writing` holds it.
- **A refused accept keeps the session running.** A dirty template repository, or an
  unresolvable template, prints the error, leaves the candidate `pending`, and stays on
  it. Ending the session on an `ApplyError` would lose the operator's place over a
  condition they can fix in another terminal.

- **`review` corroboration is a multiplier, never a contribution.** This is the whole
  of how spec.md §5.4.9 avoids double-counting the same divergence twice. `collect_drift`
  returns a *lookup table* and nothing else; every candidate, proposal, and
  `learn_evidence` row still comes from `collect`. A project `review` flags that
  `collect` has no evidence for contributes nothing, `evidence_count` and the provenance
  list are untouched, and the weight of one project's single contribution is scaled once.
  `test_review_drift_creates_no_candidate_of_its_own` and
  `test_review_drift_raises_the_score_rather_than_creating_a_parallel_finding` hold both
  halves — the latter asserts the boosted score is `unboosted * (1 + DRIFT_BOOST)` to
  within `rel=1e-3`, so a second boost applied to the same project fails it.
- **`missing_files` is recorded and never scored.** `review` reporting that a project
  *lacks* `CLAUDE.md` is a finding about that project, not evidence for a template
  change: there is no file, so there are no added lines and nothing for a proposal to be
  about. `DriftSignal.missing` exists so a caller can explain the signal; `reports()`
  consults only `lines`. Wiring `missing` into scoring would invent evidence.
- **`DRIFT_BOOST` is bounded for the same reason `RECENCY_BONUS` is.** A second code path
  agreeing about one project is corroboration of that project's evidence, not a second
  project. One drift-confirmed project must still rank below two projects that agree;
  `test_the_boost_cannot_outrank_corroboration` asserts exactly that. Raising it toward
  1.0 would let `review` — which today only diffs `AGENTS.md`, against the *unrendered*
  template — start deciding queue order.
- **`score` must not import `drift`.** `drift` imports `review`, which imports `config`,
  `templates` and `universe`. The `DriftLookup` `Protocol` in `score.py` is what keeps
  scoring a pure function of evidence plus a lookup, and keeps the dependency arrow
  pointing one way (`drift` → `score`, never back).
- **A failing `review` is skipped, not fatal.** `collect_drift` swallows per-project
  exceptions. Losing a whole scan because one directory is unreadable would be a poor
  trade for a bounded bonus; `test_a_failing_review_is_not_fatal_to_a_scan` pins it.

## Open items carried into plan.md

- ~~`README.md` §5 still documents the deleted line-diff harvester (`metaproject learn` as
  an append-to-template command).~~ **Resolved in Phase 7**: §5 was rewritten for the
  corroborated-proposal pipeline.
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
- C16 ("semantically identical, textually different") and C17 ("contradictory conventions
  are not merged") are model-judgment cases, and every Phase 3 test mocks the model. What
  is asserted is therefore what the pipeline *asks for*: the prompt requires reworded
  variants of one convention to be folded into a single proposal citing all of them, and
  forbids merging a contradiction into one recommendation (propose the corroborated
  majority; surface the minority separately). Whether the model obeys is measurable only
  against a live model, which no test may invoke. Recorded here rather than quietly
  claimed as passing.
- **The "missing `claude` exits non-zero" gate is asserted at the exception boundary**, not
  at the process boundary: `synthesize` raises `ModelUnavailableError` naming the binary,
  having assembled no prompt (asserted by patching `build_prompt`) and left the template
  store byte-identical. Turning that into an exit code is Phase 4's, since `cli.py` is out
  of Phase 3's scope; the existing `learn` stub's exit 1 would have made a CLI-level
  assertion vacuous.
- `is_generalizable` rejects a proposal that mentions a **contributing project's** name,
  case-insensitively at word boundaries. Deliberately blunt: a genuinely general proposal
  has no reason to name a project that fed it. The known false-positive class is a project
  whose name is an ordinary word (the fixture has `echo`, `forge`, `spire`), which could
  cost a legitimate proposal. Scoping the check to the bundle's own contributors keeps the
  blast radius small; revisit only if a real workspace shows it biting.
- `evidence_hash` identity is stable against model rewording but **not** against the
  evidence set growing: a twelfth project stating the convention in genuinely new words
  adds a `source_line` and therefore mints a new identity, which a prior rejection does not
  suppress. This is the accepted direction of failure — new content arguably *is* a new
  candidate, whereas a reworded body over identical evidence is not. The alternative
  (hashing the body) fails in the far worse direction, every single scan.
- `run_claude` has no test of its own beyond `claude_command`: exercising it would mean
  spawning a subprocess, which the Phase 3 gate forbids. The autouse `no_model_ever`
  fixture in `tests/test_learn_synth.py` patches both `subprocess.run` (for any argv
  mentioning `claude`) and `synth.run_claude`, so the "no test invokes a model" gate is
  enforced by the suite rather than trusted.

## Verified facts (do not re-investigate)

- `review.review_project` on the fixture workspace reports content drift for exactly one
  file — `AGENTS.md` — because `review.py` only diffs that one deliverable, and it diffs
  the project against the **unrendered** template. So every fixture project with an
  `AGENTS.md` is drift-reported, and the drift boost is in practice near-uniform across
  `AGENTS.md` today. That is acceptable (the boost is bounded and per-line-matched) and
  is a property of `review`'s current narrowness, not of `drift.py`: widening `review` to
  diff more deliverables would make the signal sharper with no change here.
- `collect` already yields `kind == "new_template"` for `Makefile` in kiln, beacon and
  quarry (identical bodies, 8 added lines each) and for `docs/architecture.md`,
  `docs/reference.md` and `pyproject.toml` in spire. Confirmed by running
  `group_candidates(guard_evidence(collect_workspace(...)).records)` over the full
  fixture, so C9's and C28's collect halves were already true before Phase 6.
- `apply.template_destination("Makefile", templates)` is `templates/Makefile.template`,
  and `templates.transform_template_name` maps it back to `Makefile` — verified by
  assertion in the C9 end-to-end test, not assumed, since a mismatch would create a
  template the walker silently ignores.
- Two `scan()` calls over the same workspace produce `evidence_score`s that differ in the
  ~1e-8 range even with the drift boost disabled, because `project_age_days` reads the
  wall clock per call. Any test comparing scores across two scans must use a tolerance
  (`pytest.approx(..., rel=1e-3)`), never equality.

- `typer.Typer(cls=...)` is honored through `app.add_typer(...)`: Typer builds the
  sub-group from `typer_instance.info.cls`, so a `TyperGroup` subclass is how `learn`
  gets a default command. Verified against the installed Typer, not assumed.
- `click`'s `MultiCommand` resolves the first non-option argument as a subcommand name
  *before* any group-level positional would see it, which is why `metaproject learn
  [ROOT]` cannot be implemented as an optional `Argument` on the group callback.
- A `rich` `Console` constructed with `file=StringIO()` and `force_terminal=False` drops
  control segments, so `console.clear()` in `run_review` is a no-op in tests and no
  escape sequences pollute an assertion on the painted text.
- `CliRunner`'s stdout is never a TTY, so every CLI-level review invocation degrades to
  the `list` table by default. A CLI test that wants the reviewer to actually open must
  patch `tui.tui_enabled` (or `tui.stdout_is_a_terminal`) and `tui.read_key`.
- `difflib.SequenceMatcher(autojunk=False)` is used again in `tui.diff_rows` for the same
  reason `collect` uses it: templates repeat lines, and autojunk diffs them wrongly.

- `sqlite_utils` `Table.indexes` entries expose columns as a plain list of strings
  (`idx.columns`), not objects with a `.name` attribute — relevant when asserting index
  shape in tests.
- `tests/conftest.py`'s `isolate_test_environment` autouse fixture sets
  `METAPROJECT_CONFIG_DIR` per test via `tmp_path_factory`; `config.get_config_dir()`
  honors it. No additional isolation fixture is needed for `learn`-related tests.
- `metaproject init --force` skips the interactive `questionary` prompts entirely (see
  `cli.py`'s `if not force:` guard), so CLI-runner tests that need a non-interactive full
  init should pass `--force` rather than mocking `questionary`.
- **`make bump-version` leaves `make test` failing until you re-run `make install`.**
  `metaproject.__version__` reads `importlib.metadata.version("metaproject")`, i.e. the
  *installed* dist-info, not `pyproject.toml`. The bump rewrites the source and
  `tests/test_baseline.py`'s expected string but cannot refresh the editable install's
  metadata, so `test_package_version` and `test_cli_version_flag` fail with the old version
  until `make install` re-prepares it. Observed on the 0.5.0 → 0.6.0 bump: 2 failed / 331
  passed, then 333 passed after reinstalling. Not a code defect; sequence `bump-version`
  then `install` then `test`.
- `make build` (`uv build --no-build-isolation`) fails in a fresh worktree venv with
  `ModuleNotFoundError: No module named 'hatchling'`. `--no-build-isolation` is deliberate
  (see AGENTS.md's offline-packaging learning) but requires the backend to be present
  locally: `.venv/bin/python -m pip install hatchling` once per worktree. `hatchling` is not
  in `[dev]`, so this is not a one-time repo fix but a per-environment step.
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
- `claude -p` takes its prompt on **stdin** in `synth.run_claude`; an evidence bundle for
  a real workspace exceeds the platform argument-length limit, so passing it as argv is not
  an option.
- The fixture builder shells out to `git`, so a test fixture that blanket-patches
  `subprocess.run` breaks `build_workspace`. `tests/test_learn_synth.py`'s guard therefore
  filters on argv containing `claude` and delegates everything else to the real `run`.
- `dataclasses.replace` on `EvidenceRecord` is how `split_record` and `chunk_bundle` build
  sub-records; the record is frozen, so nothing can mutate evidence in place between the
  guard and the prompt.
- `tests/fixtures/learn_workspace/build.py` already accepts `git_init_templates=True`
  (added in Phase 0); it is what every commit / clean-worktree assertion in Phase 4 uses.
  `Workspace` exposes `.templates`, `.projects`, and `.project(name)`.
- The Phase 1 `learn` stub exited 1 on `metaproject learn <path>`. With Phase 4's command
  group the same argv exits **2** — Click's "no such command" — and a bare `metaproject
  learn` also exits 2 via `no_args_is_help=True`. This is why `tests/test_e2e.py` asserted
  `2 == 1` after Phase 4 landed; the fix is on the test side, and the assertion is now
  `!= 0` rather than an exact code.
- The "missing `claude` exits non-zero having written nothing" gate is now asserted at the
  **process boundary** as Phase 3 deferred it:
  `tests/test_learn_cli.py::test_missing_claude_exits_non_zero_having_written_nothing`
  patches `shutil.which` to `None` (which is what `synth.resolve_claude` calls), runs
  `metaproject learn scan --yes` through `CliRunner`, and asserts a non-zero exit, the
  binary named in the output, a byte-identical template store, and zero rows in
  `learn_proposals`. Verified non-vacuous: making `learn_scan_cmd` exit 0 on a
  `MetaProjectError` fails it.
- `rich.table.Table` truncates a long cell with `…` rather than wrapping once column
  widths are contested at the default 80-column `CliRunner` width. Any assertion on a full
  absolute path in CLI output needs a non-table rendering (`console.print(...,
  soft_wrap=True)`); `overflow="fold"` does not help either, since folding inserts newlines
  mid-path and a substring assertion still fails.
- `typer.Typer(no_args_is_help=True)` added via `app.add_typer(learn_app, name="learn")`
  produces the group's help on a bare invocation and **exit code 2**, not 0.
- Both new Phase 4 test files carry the same autouse `no_model_ever` guard as
  `tests/test_learn_synth.py`: any argv mentioning `claude` raises, everything else (`git`,
  which the fixture builder and the commit path both need) reaches the real
  `subprocess.run`. `tests/test_learn_cli.py` additionally patches `synth.resolve_claude`
  and `synth.run_claude` for the scan tests, so the "no test invokes a model" gate holds
  across the whole `learn` suite.

## Closing — what shipped, and what is still open

`src/metaproject/learn.py`'s line-diff harvester is gone. In its place,
`src/metaproject/learn/` is a nine-module corroborated-proposal pipeline —
`collect`, `guard`, `score`, `store`, `synth`, `apply`, `drift`, `api`, `tui` — reached
through a `learn` command group with a hidden default command, backed by three new tables
in `universe.db` and a git-backed template store. 333 tests, `make lint` clean, version
0.6.0. Every plan.md §2 phase gate was met; each phase's headline gates were
mutation-checked rather than trusted.

The following were deferred or narrowed by earlier phases and remain open. None is a
regression; each is a bounded, deliberate limit that a future change would have to lift.

**Model judgment is asserted as intent, not as behavior (Phase 3).**
- **C16** ("semantically identical, textually different" variants fold into one proposal)
  and **C17** ("contradictory conventions are not merged") are properties of what the
  model does, and no test may invoke a model. What is asserted is what the prompt *asks
  for*. Whether the model obeys is measurable only against a live model. Unverified, and
  recorded as unverified.
- `run_claude` itself has no test beyond `claude_command`, for the same reason: exercising
  it means spawning a subprocess, which the Phase 3 gate forbids.

**TUI (Phase 5).**
- `read_key`'s terminal branch (`termios`/`tty` raw-mode read) is `# pragma: no cover` and
  is exercised by no test — testing it needs a real PTY. Everything above it is tested
  through the `read_key` seam, so a break here would surface only in manual use.
- **There is no paging for a long proposal.** `render_candidate` paints the whole diff in
  one repaint; a proposal taller than the terminal scrolls off the top and cannot be
  scrolled back within the TUI. `learn show <id>` is the workaround. spec.md §5.4.5 does
  not require paging, so this is a usability gap, not a gate miss.

**Drift signal (Phase 6).**
- The `review` drift signal is **not surfaced anywhere in the UI.** It multiplies a
  contributing project's weight inside `score`, but nothing in `learn list`, `learn show`,
  or the TUI's provenance view tells the operator that a score was boosted or which
  projects `review` corroborated. `DriftSignal.reports()` exists to explain it; no caller
  uses it. An operator therefore cannot account for the number they are being ranked by.
- `DriftSignal.missing` is recorded and deliberately never scored — a missing file has no
  added lines, so there is nothing for a proposal to be about. Wiring it into scoring would
  invent evidence. Intentional; noted so it is not "fixed" later.
- **`review.py`'s narrowness bounds the signal's value.** `review_project` diffs exactly
  one deliverable, `AGENTS.md`, and diffs it against the *unrendered* template. So the
  boost is near-uniform across `AGENTS.md` and absent everywhere else. That is a property
  of `review`, not of `drift.py`: widening `review` to diff more deliverables (and to
  render before diffing, as `collect` does) would sharpen the signal with no change in
  `learn`.

**CLI surface (Phase 4).**
- `--templates` is accepted on `list`, `show` and `reject` but never read — those three
  are read-only against the ledger and never touch the template store. spec.md §5.4.4
  mandates the flag on all subcommands, so it is kept for a uniform surface; it is inert
  on those three, and passing it changes nothing.

**Collection and scoring limits (Phases 1–2).**
- Only the project-root `.gitignore` is parsed. Nested per-directory ignore files and
  `.git/info/exclude` are not. The hard denylist is the backstop.
- `is_generalizable` rejects a proposal naming a *contributing* project, case-insensitively
  at word boundaries. The known false-positive class is a project whose name is an ordinary
  word (`echo`, `forge`, `spire` in the fixture), which could cost a legitimate proposal.
- `evidence_hash` identity is stable against model rewording but **not** against the
  evidence set growing: a new project stating the convention in genuinely new words mints a
  new identity, which a prior rejection does not suppress. Accepted direction of failure —
  the alternative (hashing the body) fails far worse, every scan.
- `evidence_score` is a plain sum of weights, so ~10 `Archived` projects carry about as
  much weight as one `Active Now` project. Deliberate: the number stays explainable by the
  provenance list.
- `score.group_candidates` clusters one candidate per normalized line. That is the
  corroboration signal, not the proposal; `synth` regroups. Fine today, but it means
  corroboration is measured line-wise even when a convention spans several lines.

**Not in scope, and still not.**
- `learn` proposes additions and modifications only. Proposing a *removal* from a template
  is out of scope per spec.md §5.4.6 and nothing implements it.
- `learn.targets` is configurable but the shipped default list is what every test and
  fixture exercises; other target sets are untried.
