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
