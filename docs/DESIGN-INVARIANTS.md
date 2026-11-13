# Design invariants (regression guards)

Long-lived, append-only. `wrapup` moves STATE.md's "Design invariants (regression
guards)" section here, dated and linked to the cycle's archive, before resetting
STATE.md. Read this before `generate-spec`/`generate-design`/`generate-plan` so an
invariant established in one cycle isn't accidentally violated in the next.

## 2026-09-15 — [template-source-of-truth](../archive/2026-09-15-template-source-of-truth/)

- Working deliverables are never updatable: `ReviewResult.updatable` reads only `diffs`,
  which holds governance files; structural drift lives in `structure` (design.md).
- Heading (structure) evidence never reaches the egress guard, confirmation, or any model
  prompt; it is turned into proposals locally (spec R-LRN-1, design.md).
- Heading proposals need ≥ `learn.min_structure_evidence` (default 2) projects; model
  proposals for governance files stay ranked, not gated (spec R-LRN-1c).
- A template missing from the live store is an error, never a silent fallback to the
  bundled copy (design.md).
- Template-store walks skip OS/editor junk files (`.DS_Store`, `Thumbs.db`,
  `desktop.ini`, `._*`, `*~`, `.*.swp`) as well as `.git`; the rule lives once in
  `templates.is_junk_file_name` and is applied everywhere the store is walked.

## 2026-09-29 — [absorb-sdlc-skills-into-metaproject-move-cycle-docs-to-docs](archive/2026-09-29-absorb-sdlc-skills-into-metaproject-move-cycle-docs-to-docs/)

- Every presence check on a relocated cycle document uses `deliverables.exact_exists`
  (directory-entry compare), never `Path.exists()`: on APFS `docs/INTENT.md` "exists"
  when only `docs/intent.md` does. Covered by lowercase fixtures in test_deliverables,
  test_backfill, test_review.
- A document at a legacy location is `ReviewResult.legacy`, never `missing_files` or
  `deployable` — Deploy must not create a blank copy beside the real one.
- Project skills are create-only: nothing (`new`, `backfill`, `doctor`) writes into an
  existing `.agents/skills/<name>/`; a differing copy is only reported `stale`.
- `doctor` moves never overwrite (conflict → both kept, reported), never commit in a
  project, and commit only the moved paths in the template store.
- `doctor`'s confirm must actually ask: the default wraps `questionary.confirm(...).ask()`
  (regression test `test_default_confirm_asks_and_respects_no`).
- `learn/collect.py` and `learn/guard.py` must not contain the string `claude`
  (test_learn_guard's phase-one gate); shared constants like `SKILL_ROOTS` live in
  `deliverables.py`.



## 2026-11-12 — issue #3 part 3a (web profile, `adopt`, optional `tui` extra)

- Core paths (`--version`, `new`, `backfill`, `adopt`, `review --no-tui`) never import
  `textual`, `questionary` or `sqlite-utils`; those go through `metaproject.extras`
  (`require`/`LazyModule`). `tests/test_extras.py` runs each core command in an
  interpreter that blocks the three and fails on any leak.
- `metaproject.learn` resolves its public names lazily (PEP 562), so importing a
  submodule (`review` uses `learn.collect`) never imports `store`/`api`.
- `adopt` is create-only and runs no git: an existing `.metaproject.json` is kept as
  written, an unreadable one stops the run rather than being replaced, and deliverables
  and skills go through `backfill_missing`. `new .` keeps its operator-confirmed flow.
- A *detected* author (git `user.name`, `$USER`) that is a container identity
  (`config.CONTAINER_DEFAULT_AUTHORS`: Claude, root, …) is never used. An explicit author
  (`--author`, config, `.metaproject.json`) is used as written.
- Web profile precedence: `METAPROJECT_PROFILE` (both directions) > an existing config's
  `profile` ("local" when absent) > `CLAUDE_CODE_REMOTE` truthy. A local machine's config
  is never reclassified by the environment.
- In the web profile `doctor` suppresses only its environment-wide checks (store layout,
  store, config, orphaned global skill, catalog); the per-project checks run against an
  explicit `doctor PROJECT`, else the current directory, via
  `doctor.run_checks(..., project=...)`. Every fix still needs an operator to confirm it.
- A machine-readable web-profile notice never corrupts stdout: it goes to stderr, and
  `--format json` writes an `{"available": false, ...}` envelope.
- The `FALLBACK_AUTHOR` placeholder is never written to `config.json` (`Config.to_dict`
  writes ""), so an undetected identity cannot outrank a later real git `user.name`.
- `adopt` never records `FALLBACK_AUTHOR` in `.metaproject.json`: that file is
  create-only and tops the author precedence, so when no `--author`, config author or
  non-container git/`$USER` name exists, adopt refuses (exit 1, "pass --author") before
  writing anything.

## 2026-11-12 — issue #7 (Claude Code hooks)

- `.claude/settings.json` is merged, never overwritten or rendered: `hooks.merge_hooks`
  is the only write path, it preserves every existing key and hook in order, and it
  writes nothing when every entry is already present (idempotent, byte-for-byte).
- A hook entry's identity is its `command` string under its event; an operator's own
  edits to our entry's matcher or timeout are kept, never "corrected".
- An existing settings file that is not a JSON object (or whose `hooks` is not an
  object of lists) is refused and reported — nothing, not even the hook script, is
  written — and never fails a scaffold or the rest of a backfill batch.
- The hook script is installed create-only, like the project skills; a differing copy
  is only reported (review note), never rewritten.
- The hook script never blocks the operator's work: every internal problem exits 0;
  only a configured lint/typecheck command that fails exits 2. The merged command string
  itself exits 0 when the script file is absent (deleted, gitignored, not checked out),
  since `python3 <missing file>` exits 2 and would block every Bash call.
- A hooks install the sandbox denies is a notice, not a failure, in default-mode
  `backfill` (exit 0, listed "Not written"); unmergeable settings JSON, or an explicitly
  named `.claude/settings.json` that cannot be written, is refused with exit 1.
- `write_identity` keeps keys of `.metaproject.json` it does not own (`commands`,
  `e2e_port`).

