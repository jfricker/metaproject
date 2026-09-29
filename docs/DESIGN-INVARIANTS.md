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

