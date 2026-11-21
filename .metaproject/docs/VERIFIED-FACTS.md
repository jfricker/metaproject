# Verified facts (do not re-investigate)

Long-lived, append-only. `wrapup` moves STATE.md's "Verified facts (do not
re-investigate)" section here, dated and linked to the cycle's archive, before resetting
STATE.md. Read this before re-deriving something a prior cycle already confirmed.

## 2026-09-15 — [template-source-of-truth](../archive/2026-09-15-template-source-of-truth/)

- Running pytest inside the Claude Code sandbox: the default TMPDIR contains `claude-501`,
  which trips the test suites' "no `claude` subprocess" guard (24 false failures). Use
  `--basetemp=<repo>/.pytest_cache/tmp-<lane>` (outside any `claude` path); baseline
  435 passed that way (2026-09-14).
- `uv` needs the sandbox disabled (its cache under ~/.cache/uv is not readable); worktree
  venvs were created unsandboxed (2026-09-14).
- The prior "improve learn command" cycle shipped (v0.6.0, 333 tests) but was never
  wrapped up; its docs, including its full STATE.md with invariants, facts and open
  items, are archived under `docs/archive/2026-09-04-improve-learn-command/` (2026-09-13).

### Update, 2026-09-15 (execute-tests gate run)

- The first bullet above is **incomplete for worktree runs**: the guard trips on any
  subprocess *argument* containing `claude`, and a worktree checkout lives under
  `.claude/worktrees/`, so `--basetemp=<repo>/.pytest_cache/...` *inside a worktree*
  fails the same guard (31 false failures). Use a basetemp with no `claude` anywhere in
  the path, e.g. `--basetemp=/private/tmp/mp-gate-exec` (588 passed, 2026-09-15).
- Sandboxed `git init` fails with exit 128 (`cannot copy ... git-core/templates/...:
  Operation not permitted` — Xcode's template dir is outside the sandbox read scope),
  which surfaces as ~112 false ERRORs across git-writing tests. Run the suite unsandboxed.

## 2026-09-15 — [metaproject-doctor](../archive/2026-09-15-metaproject-doctor/)

- `.git` is **not** part of `templates.is_junk_file_name` (that rule covers only
  OS/editor junk); every walk of the live template store must skip `.git` explicitly
  and separately. `doctor`'s `_relative_files` initially flooded its extras report
  with the store's `.git` internals until the explicit skip was added — the
  DESIGN-INVARIANTS wording ("skip junk … as well as `.git`; the rule lives once in
  `is_junk_file_name`") overstates what that one function does.
- On a real machine, the identity check's anchorless list includes the scan root
  itself and nested worktree/skill directories cataloged by `universe` — the findings
  are genuine catalog data; doctor reports, the operator decides.

## 2026-09-16 — [universe-hard-scoping-and-details-tui](../archive/2026-09-16-universe-hard-scoping-and-details-tui/)

- Textual apps need a headless pilot run (`app.run_test`) in the suite: builder and
  gate tests passed while the real `ProjectDetailScreen` crashed on mount (a path
  string was passed where the DB record was expected). The pilot test is kept as a
  regression guard (206db10).
- A main-checkout-only suite failure can be untracked leftovers the worktree never
  had: the stray repo-root `templates/` (only `.DS_Store`) tripped
  `test_repo_root_templates_directory_is_gone` on main after the merge while the
  worktree run was green. `Path(__file__).resolve()`-based repo checks see the
  checkout they run in, untracked files included.

## 2026-09-29 — [absorb-sdlc-skills-into-metaproject-move-cycle-docs-to-docs](archive/2026-09-29-absorb-sdlc-skills-into-metaproject-move-cycle-docs-to-docs/)

- `git subtree add` from a local-path remote brings the full SDLC-skills history (merge
  d67cc74, parent 2 = e6f42a4); `git mv` of the skill directories then records renames,
  but `--follow` stops at the prefix move (2026-09-28).
- `markdown.normalize_heading` casefolds, so renaming the STATE heading "Open items
  carried into plan.md" → "PLAN.md" causes no structure drift in existing projects.
- A scratch gate script piping pytest into `tail` masks failures unless `pipefail` is set
  — one commit went through red and was amended (2026-09-28).
- hatchling's `WheelBuilder(root).build(directory=...)` builds the wheel in-process with
  no network, so wheel-content tests need neither `uv build` nor an unsandboxed run.


## 2026-11-12 — issue #3 part 3a (web profile, `adopt`, optional `tui` extra)

- `importlib` from-import of a submodule (`from metaproject.learn import tui`) still works
  when the package defines a module-level `__getattr__` that raises `AttributeError` for
  unknown names: the import system falls back to importing the submodule.
- `uv pip install -e ".[dev]"` resolves a self-referential extra (`dev = ["metaproject[tui]", …]`).
- `typer.Typer(cls=...)` accepts a `TyperGroup` subclass; overriding `invoke` there sees
  exceptions from every subcommand, nested groups included.
- Rich treats `[tui]` in a printed string as markup and drops it; messages that name the
  extra are passed through `rich.markup.escape`.
- `tests/test_skills.py::test_ac5_real_claude_skills_directory…` was sensitive to the
  temporary-path length (Rich wrapped "real directory" across lines); it now compares
  whitespace-normalized output.

## 2026-11-12 — issue #7 (Claude Code hooks)

- The Claude Code sandbox this was built in lists a project's `.claude/settings.json`
  and `.claude/hooks/` as write-denied; an agent-run `backfill` there gets
  `PermissionError`, which `install_hooks` turns into a notice (2026-11-12).
- A function-local `from metaproject.deliverables import DeliverableClass` placed
  late in a function makes the name local for the whole function, so an earlier use
  raises `UnboundLocalError` — `backfill_missing` now uses the module-level import.
- `subprocess.run(..., shell=True, timeout=...)` only kills the shell; the hook runs the
  command in its own session and kills the process group on timeout so a lint child
  holding the pipe cannot hang the hook.
- `tests/test_skills.py::test_ac5_...` failed on `main` before this change: Rich wraps
  the long tmp path and splits "real directory" across lines; the assertion now compares
  whitespace-normalised output.

## 2026-11-13 — issue #3 part 3c

- `git init` + `git fetch --depth 1 --no-tags -- <url> <ref>` + `git checkout --detach
  FETCH_HEAD` shallow-fetches a named branch from a `file://` remote; verified by
  `tests/test_template_source.py` with a real local repository (no network). Tags and
  `HEAD` take the same path but are only exercised against a fake git runner.
- `metaproject --version` prints "Package Manifest — metaproject v<version>" first, so
  the session script's `grep -oE '[0-9]+\.[0-9]+\.[0-9]+…' | head -n 1` reads the
  installed version (run with `COLUMNS=200` so Rich does not wrap the title).
- `v0.9.1` and earlier have no `skills` or `templates` command (`git show
  v0.9.1:src/metaproject/cli.py` has no `skills_app`/`templates_app`), so a pinned install
  of those versions cannot run the session script's steps 2 and 3.
- As of 2026-11-13 origin has no tags (`gh api repos/jfricker/metaproject/tags` is empty;
  v0.6.1..v0.9.1 exist only locally), so every `@v<version>` install currently fails and
  falls back to the default branch. "Install at the pinned version" needs release tags
  pushed to origin.

## 2026-11-13 — issue #4 (install / update cycle)

- `git ls-remote --tags origin` returns no tags: `v0.6.1`..`v0.9.1` exist only locally
  and `bump_version.sh` never pushes, so `uv tool install ...@v0.9.1` cannot resolve
  until the tag is pushed (2026-11-13).
- pypi.org's `metaproject` is an unrelated 0.0.1 package ("Scaffod projects from
  metaproject templates."); `pip install metaproject` installs it, not this CLI.
- Typer 0.29 vendors click (`typer._click`): a `click.UsageError` raised inside a command
  is not recognised and exits 1, not 2. `skills --all` usage errors print one line and
  `raise typer.Exit(code=2)` instead.
