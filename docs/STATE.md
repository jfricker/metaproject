# MetaProject — State

## Process

<!-- each stage ticks its own item here as it completes -->
- [x] 1. write-intent: intent.md approved
- [x] 2. generate-spec: spec.md approved
- [x] 3. generate-design: design.md approved
- [x] 4. generate-plan: plan.md approved
- [x] 5. implement-plan: code and tests written
- [ ] 6. execute-tests: tests passing
- [ ] 7. wrapup: cycle archived

## Implementation phases

<!-- written by implement-plan as steps land -->
- [x] 1. Self-migrate this repo's documents to docs/ (R-SELF-1)
- [x] 2. Import the skills with history (R-IMP-1..4)
- [x] 3. Relocated deliverables + template store (R-DOC-0..4)
- [x] 4. Review legacy detection + OUTOFDATE (R-DOC-5)
- [x] 5. learn / universe markers (R-DOC-3, R-DOC-6, R-SKL-8)
- [x] 6. Project skills, new/backfill, init (R-SKL-1..7, R-INI-1..2; doctor global-skill check removed here, pulled forward from step 7)
- [x] 7. doctor (R-DRX-1..7; also fixed default confirm never prompting)
- [x] 8. Skill text + skill tests (R-TXT-1..3, R-SKL-7)
- [x] 9. Documentation (R-TXT-2..4, R-RET-1)
- [x] 10. Populate this repo's skills (R-SELF-1)

## Design invariants (regression guards)

<!-- written by implement-plan/execute-tests; appended to docs/DESIGN-INVARIANTS.md by wrapup -->
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

## Open items carried into plan.md

<!-- written by implement-plan/execute-tests; resolved with the operator by wrapup -->
- `git log --follow src/metaproject/sdlc_skills/<name>/SKILL.md` does not cross the
  subtree prefix (plan Verification item). History is reachable (acceptance 1):
  `git log d67cc74^2 -- skills/<name>/SKILL.md` shows the SDLC-skills commits.
- Plan sequencing deviation: doctor's global-skill check was deleted in step 6 (not 7)
  so step 6's commit stayed green after `install_skill` was removed.
- Unplanned fix in step 7: `doctor.run_checks`' default confirm returned a truthy
  `questionary.Question`, so interactive doctor applied every fix unprompted (bug
  predates this cycle). Now asks; regression test added.
- `backfill` / doctor's skills fix install into `.agents/skills/` even when a project has
  no `.claude/skills` symlink (skills then invisible to Claude Code). Only `new` creates
  the link. Candidate follow-up: have backfill/doctor create or report the missing link.
- `doctor` template-store "extra" findings are now informational (never make the check
  unhealthy, never prompt); previously an extras-only store exited 1 and prompted.
- README's retirement note says "absorbed into metaproject ≥ 0.9.0" — confirm the version
  when `bump_version.sh` runs.
- Skill text lines rewritten by script exceed the files' usual ~88-column wrap in places
  (cosmetic).
- Operator steps after merge (R-RET-1): install release, uninstall sdlc-skills plugin and
  its marketplace, `metaproject doctor` on the real store/projects, SDLC-skills README
  pointer.

## Verified facts (do not re-investigate)

<!-- written by implement-plan/execute-tests; appended to docs/VERIFIED-FACTS.md by wrapup -->
- `git subtree add` from a local-path remote brings the full SDLC-skills history (merge
  d67cc74, parent 2 = e6f42a4); `git mv` of the skill directories then records renames,
  but `--follow` stops at the prefix move (2026-09-28).
- `markdown.normalize_heading` casefolds, so renaming the STATE heading "Open items
  carried into plan.md" → "PLAN.md" causes no structure drift in existing projects.
- A scratch gate script piping pytest into `tail` masks failures unless `pipefail` is set
  — one commit went through red and was amended (2026-09-28).
- hatchling's `WheelBuilder(root).build(directory=...)` builds the wheel in-process with
  no network, so wheel-content tests need neither `uv build` nor an unsandboxed run.
