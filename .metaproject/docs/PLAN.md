# Harness-neutral project skills: one source, per-harness adapters — Implementation Plan

**Author**: John Fricker.
**Derived from**: SPEC.md, TECH-DESIGN.md (2026-11-26, v2).
**Last updated**: 2026-11-26.
**Status**: Approved.
**Approved by**: John Fricker (2026-11-26; v2 after the spec review).

Context: replace the whole-directory `.claude/skills → .agents/skills` symlink with
manifest-tracked per-skill bridge entries for every bundled skill (SPEC v2 R-BRG-1…33,
TECH-DESIGN v2).

## Steps

Every step ends with `make format && make lint && make test` green. Old APIs stay as
deprecated shims until step 6 so each step is green and revertable on its own.

0. **Precondition (operator).** The unrelated uncommitted `README.md` "Inspiration" edit is
   committed or stashed by the operator before step 7 touches README.
1. **Foundations, no behaviour change.**
   - New `src/metaproject/treeops.py`: move `hash_content`, `file_map`, `_copy_tree`, `_remove`,
     `_record_tree` from `skills.py` (re-exported from `skills` for now); add `swap_tree` and
     `recover_staging` (with `dest.txt`), and make `_replace_skill`/`_recover_staging` use them.
   - `skills.py`: `Manifest` dataclass, `MANIFEST_VERSION = 2`, v1 load, `bridges` carried
     through by both callers.
   - `identity.update_settings` (R-BRG-6).
   - `git.read_only_query` + `READ_ONLY_KEYS`; route `get_git_identity` and
     `config.detect_git_user_name` through it.
   - Tests: new `tests/test_treeops.py` (swap success, injected failure, crash recovery);
     manifest v1→v2, version-3 guard, bridges preserved by a skills-only sync
     (`tests/test_skills_sync.py`); `update_settings` incl. legacy path and invalid JSON;
     `read_only_query` allowlist rejects other keys, timeout/absent git → None.
2. **`src/metaproject/bridges.py` in isolation.** Everything in TECH-DESIGN's bridges section.
   New `tests/test_bridges.py`: every `classify_entry` branch; `lost_user_skills` (dot dirs,
   no SKILL.md, bundled names excluded); shapes incl. unmaterialised legacy file; modes via config, `_is_windows` patch,
   real repo with `core.symlinks=false`, git missing; symlink `OSError` → copy; write denied;
   newer manifest; removal incl. `created`; mode rules (AC 7); `migrate_legacy_link` success,
   injected failure restores link and file forms exactly; `shadowing` with temp `HOME`.
3. **Wire bridges into skills.** `sync_project_skills`/`inspect_project_skills` run the bridge
   pass and write one manifest; `--force` to both passes; `SkillsReport.bridges`/`shadowing`;
   `project_skills_dir` refusal only for no-home; delegating sub-projects recorded in the home
   manifest. Keep `link`/`notice`/`ensure_skills_link`/`link_target` as shims.
   Tests: rewrite the R-SKL-5 / directory-link cases in `tests/test_skills.py`,
   `tests/test_skills_sync.py`, `tests/test_nested_projects.py` (AC 2, 6, 10, 11, 15, 16, 22).
4. **Scaffold / backfill / adopt.** `prepare_agent_skills`; record `skills.targets` via
   `update_settings` (tracked); result objects gain `skills_bridges` (old keys kept as shims).
   Tests: `tests/test_scaffold.py`, `tests/test_adopt.py`, `tests/test_e2e.py`,
   `tests/test_backfill.py` — directory-link assertions replaced; the two no-git tests become
   allowlist tests, plus the same for `adopt` (AC 1, 3, 14, 18).
5. **Doctor.** Four checks in R-BRG-20 order with separate check/fix callables.
   Tests: `tests/test_doctor.py` (AC 9, 12, 13, 19 incl. `CLAUDECODE=1` report-only).
6. **CLI and shim removal.** `print_skills_report`, `new`/`backfill`/`adopt` narration (incl.
   dry-run text), `skills status` text + JSON, exit codes and `sync --all` failure counting
   (R-BRG-27…30); then delete the shims (`SkillsTarget.link`, `SkillsReport.link`,
   `ensure_skills_link`, `link_target`, result `skills_link`/`skills_notice`) and the
   `skills.py` re-exports of moved helpers if unused.
   Tests: CLI cases in `tests/test_skills_sync.py`, `tests/test_skills_sync_all.py` (replace the
   real-directory R-SKL-5 refusal at l.214), AC 20, 21.
7. **Docs, skill history, self-migration.**
   - Update AGENTS.md (§1, §5, Key Files, git rule at l.76/78/82/148), README (l.14, 40, 93,
     106–121, 145–148, 299–324, 520–522), `src/metaproject/skill/SKILL.md`,
     `references/commands.md` (+ harness matrix, SessionStart note), `references/documents.md`,
     `src/metaproject/templates/AGENTS.template.md`; `cli.py`/`scaffold.py` docstrings saying
     "never runs git".
   - `make skill-history`.
   - Operator runs `metaproject doctor .` in a terminal (doctor fixes are report-only in agent
     sessions) → AC 23; commit `.claude/skills` with the cycle.

## Files touched

- New: `src/metaproject/treeops.py`, `src/metaproject/bridges.py`, `tests/test_treeops.py`,
  `tests/test_bridges.py`.
- Modified source: `skills.py`, `identity.py`, `git.py`, `config.py`, `scaffold.py`,
  `review.py`, `doctor.py`, `cli.py`.
- Modified tests: `test_skills.py`, `test_skills_sync.py`, `test_skills_sync_all.py`,
  `test_nested_projects.py`, `test_scaffold.py`, `test_adopt.py`, `test_backfill.py`,
  `test_e2e.py`, `test_doctor.py`, plus identity/git test files for the new helpers.
- Docs/data: `AGENTS.md`, `README.md`, `src/metaproject/skill/SKILL.md`,
  `src/metaproject/skill/references/commands.md`, `references/documents.md`,
  `src/metaproject/templates/AGENTS.template.md`, `src/metaproject/skill_history.json`.
- This repo after step 7: `.claude/skills/` (directory of per-skill links),
  `.agents/skills/.metaproject-skills.json` (v2), `.metaproject/config.json` (`skills.targets`).
- Not touched: `hook_scripts/metaproject-session.sh` (R-BRG-32),
  `sdlc_skills/generate-plan/SKILL.md` (no link reference). `ARCHITECTURE.md` and
  DESIGN-INVARIANTS superseded notes are updated at wrapup.

## Sequencing

Strictly 0/1 → 7: `treeops`/manifest/config/git helpers (1) underpin `bridges.py` (2), which
`skills.py` calls (3); scaffold (4), doctor (5) and CLI (6) consume the new reports while shims
keep the old ones compiling; shims are deleted only in 6; docs and the self-migration (7)
describe and exercise the finished behaviour. No step can run in parallel with another.

## Risks / rollback

- Test churn is concentrated in steps 3–4; each may need a dedicated pass.
- The restated git rule is enforced by the allowlist test (AC 18); any new git call fails it.
- Manifest v2 locks out older CLIs (accepted).
- Each step is revertable on its own thanks to the shims. The legacy link keeps working until
  step 7; the migration is reversible by restoring `.claude/skills` from git.

## Verification plan

- Full gate after every step; final `make test` count reported.
- Manual: `metaproject new` in a temp dir → `.claude/skills` holds per-skill links; Claude Code
  lists `/write-intent`; re-run the Copilot `skillsLoad` probe on the new layout (one entry per
  name); `adopt` into a repo with its own `.claude/skills/shipit` and a user skill in
  `.agents/skills/`.
- A real Windows checkout check goes to `.metaproject/docs/TODO.md` at wrapup.
