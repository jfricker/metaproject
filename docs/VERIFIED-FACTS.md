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
