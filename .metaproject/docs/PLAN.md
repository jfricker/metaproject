# Move metaproject's documents from docs/ to .metaproject/docs/ — Implementation Plan

**Author**: John Fricker.
**Derived from**: docs/SPEC.md (2026-11-21), docs/TECH-DESIGN.md (2026-11-21).
**Last updated**: 2026-11-21.
**Status**: Approved.
**Approved by**: John Fricker (2026-11-21).

Requirement IDs (`R-*`) and Acceptance Criteria (`AC-*`) refer to `docs/SPEC.md`; design sections (`§1`–`§6`) refer to `docs/TECH-DESIGN.md`.

## Steps

### Step 1 — Relocated deliverables, template store layout, and `review` legacy detection (`R-LOC-1..4`, `R-TPL-1..4`, `R-LEG-1..2`, `R-NFR-1`, §1–§3)
Lands as one atomic green commit because `DELIVERABLES`, the bundled template store, `DEFAULT_LEARN_TARGETS`, and the core test suite assert they agree.

1. **`src/metaproject/deliverables.py`**
   - Update `DELIVERABLES`: move the 8 `WORKING`, 2 `ON_DEMAND`, and 2 `DIRECTORY` entries under `.metaproject/docs/` (`GOVERNANCE` and `SETTINGS` unchanged).
   - Add `MIGRATABLE_SUBDIRS = ("archive", "backlog", "discovery")`, `LEGACY_ROOT_NAMES` (the 7 v0.8 root files — intentionally excluding `DESIGN-INVARIANTS.md`, `VERIFIED-FACTS.md`, and `TODO.md`), `LEGACY_DIR_NAMES = {"docs": ".metaproject/docs", "docs/archive": ".metaproject/docs/archive"}`, and `LEGACY_LEARN_TARGETS = {**LEGACY_NAMES, "docs/": ".metaproject/docs/"}`.
   - Expand `LEGACY_NAMES` to map all 7 root old names, all 10 `docs/<NAME>.md` v0.9 paths, and `docs/<old>` lowercase spellings (`docs/intent.md`, `docs/spec.md`, `docs/design.md`, `docs/plan.md`) to their `.metaproject/docs/<NEW>.md` paths.
   - Update `canonical_path` to resolve `DELIVERABLES`, `LEGACY_NAMES`, `LEGACY_DIR_NAMES`, and file basenames case-insensitively.
   - Generalize `legacy_candidates(root, new, template_suffix=False)` across all 10 relocated files in priority order: `docs/<NAME>.md`, `docs/<old>` (plus lowercase `<name>.md`), root `<old>`/`<NAME>.md` (only for `LEGACY_ROOT_NAMES`), and `.metaproject/docs/<old>` / `.metaproject/docs/<name>.md` (APFS case variants), all checked via `exact_exists`.
   - Extend `legacy_locations(project_dir)` to check all 10 files plus `.metaproject/docs/archive` (`docs/archive`) and `.metaproject/docs` (`docs`, only when `docs/` contains at least one legacy metaproject file, `docs/archive`, `docs/backlog`, `docs/discovery`, or `docs/.gitkeep`).
2. **`src/metaproject/templates/`**
   - `git mv` every file under `src/metaproject/templates/docs.template/` (the 10 `.template.md` files, `.gitkeep`, and `archive.template/.gitkeep`) into `src/metaproject/templates/.metaproject.template/docs.template/`.
   - Update path references in `AGENTS.template.md` (adding a note that `.metaproject/docs/` is a dot-directory so `rg`/`fd` searches need `--hidden` or an explicit path), `README.template.md`, `.metaproject.template/docs.template/STATE.template.md`, and `.metaproject.template/docs.template/TODO.template.md`.
3. **`src/metaproject/config.py`**
   - Update `DEFAULT_LEARN_TARGETS` to replace `"docs/"` with `".metaproject/docs/"`.
4. **`src/metaproject/review.py`, `src/metaproject/review_tui.py`, `src/metaproject/scaffold.py`, `src/metaproject/templates.py`, `src/metaproject/identity.py`, `src/metaproject/cli.py`**
   - Expand `_RELOCATED_PATHS` in `review.py` to every deliverable under `.metaproject/docs/` (all 8 working, 2 on-demand, and 2 directory deliverables) so `_present` uses `exact_exists` throughout.
   - Update `review.deploy_entry` so directory deploys exclude both `ON_DEMAND` paths and any paths in `legacy_locations(resolved_proj)` (relative to the directory prefix).
   - Update `docs/` docstrings and `backfill` CLI help text to `.metaproject/docs/`.
5. **Tests (keep full gate green)**
   - Update and expand `tests/test_deliverables.py`, `tests/test_bundled_templates.py`, `tests/test_templates.py`, `tests/test_config.py`, `tests/test_scaffold.py`, `tests/test_new_dry_run.py`, `tests/test_adopt.py`, `tests/test_nested_projects.py`, `tests/test_e2e.py`, `tests/test_web_profile.py`, `tests/test_review.py` (including AC-3 `docs/` → `OUTOFDATE`, AC-4 project-owned `docs/index.md` → `CLEAN`, APFS `.metaproject/docs/intent.md`), `tests/test_backfill.py` (AC-2 alias forms), and adjust any path assertions in `tests/test_doctor.py` / `tests/test_learn_*.py` needed so Step 1's suite is green.

### Step 2 — `backfill` no-args legacy safeguard (`R-LOC-5`, FC-2, AC-2, AC-10, §3)
1. **`src/metaproject/review.py`**
   - Add `legacy: Dict[str, str] = field(default_factory=dict)` to `BackfillResult`.
   - In `backfill_missing` (no-files mode), compute `legacy_found = legacy_locations(resolved_proj)` once up front and route any `path in legacy_found` into `result.legacy` (skipping `deploy_entry`).
2. **`src/metaproject/cli.py`**
   - Update `print_backfill_result` to print `result.legacy` in a `"Skipped (legacy location — run \`metaproject doctor\`)"` table (`<where> → <declared>`), and include `result.legacy` in the `"Nothing to do."` guard.
3. **Tests (`tests/test_backfill.py`)**
   - Update the APFS lowercase test and add tests for no-args `backfill` (and CLI output) on `docs/`-layout, root-layout, and `.metaproject/docs/intent.md` projects: nothing created for legacy deliverables, `result.legacy` populated, exit 0, output mentions `metaproject doctor`.

### Step 3 — `universe` and `learn` compatibility (`R-LEG-3`, `R-LEG-4`, `R-NFR-3`, FC-4, AC-11, §5)
1. **`src/metaproject/universe.py`**
   - Add `".metaproject/docs/INTENT.md"` to `is_project_root` alongside `"docs/INTENT.md"` and `"intent.md"`.
   - Update `has_intent_md`, `has_state_md`, and `has_handoff_md` in `scan_universe` to check `.metaproject/docs/`, `docs/`, and legacy root names.
   - Skip descending into child directory `".metaproject"` inside `walk_dirs` (leaving `IGNORED_DIRECTORIES` unchanged so `get_newest_mtime_in_dir` still sees edits in `.metaproject/docs/`).
2. **`src/metaproject/learn/collect.py`**
   - Skip descending into child directory `".metaproject"` in `iter_project_dirs`.
   - Update docstrings (preserving the `test_learn_guard.py` invariant: no `"claude"` string in `collect.py` or `guard.py`).
3. **Tests (`tests/test_universe.py`, `tests/test_learn_collect.py`, `tests/test_learn_apply.py`, `tests/test_learn_drift.py`, `tests/test_learn_structure.py`, `tests/test_learn_synth.py`, `tests/test_learn_guard.py`, `tests/fixtures/learn_workspace/`)**
   - Add AC-11 regression tests: `universe` recognizes all three layouts, sets `has_*_md` for all three, counts `.metaproject/docs/` edits in mtime, and does not catalog `.metaproject/docs/archive/<cycle>/` as a project; `learn` ignores a project's own `docs/guide.md`, collects structure diffs from `.metaproject/docs/`, and `learn apply` writes into `.metaproject.template/docs.template/`.

### Step 4 — `doctor` migrations & `git.git_rm` (`R-DRX-1..5`, `R-NFR-1..2`, FC-3, FC-4, FC-6, AC-5..10, §4)
1. **`src/metaproject/git.py`**
   - Add `git_rm(repo_dir: Path, rel_path: str) -> None` (`git -C <repo> rm -- <rel_path>`).
2. **`src/metaproject/doctor.py`**
   - **Check 1 (template-store layout):** generalize `_planned_moves` over all 10 relocated deliverables, add store `.gitkeep` moves (`docs.template/.gitkeep` and `docs.template/archive.template/.gitkeep` → `.metaproject.template/docs.template/...`), remove emptied/junk-only `docs.template/archive.template` and `docs.template` (keeping `docs.template/` if any operator-added custom template remains), and update `STORE_LAYOUT_COMMIT` to `"chore(templates): relocate doc templates to .metaproject.template/docs.template/"`.
   - **Check 3 (config `learn.targets`):** switch `_migrated_targets` / `check_config` to `deliverables.LEGACY_LEARN_TARGETS` so root names, `docs/*`, and `"docs/"` rewrite in place to `.metaproject/docs/*` (order preserved, deduplicated).
   - **Check 6 (project docs):**
     - Plan moves for all 10 relocated deliverables (`_planned_moves(project_dir)`).
     - Plan per-file moves across `deliverables.MIGRATABLE_SUBDIRS` (`docs/archive/`, `docs/backlog/`, `docs/discovery/` → `.metaproject/docs/<subdir>/`), skipping OS junk (`templates.is_junk_file_name`) and `.git`: report-only conflict if destination exists (except redundant identical/empty `.gitkeep`, planned for removal); plan creating `.metaproject/docs/<subdir>` and removing empty source dir if a subdir is completely empty.
     - Plan `docs/.gitkeep`: move if `.metaproject/docs/.gitkeep` is absent; plan redundant removal if destination exists and `docs/.gitkeep` is empty, matches the bundled placeholder, or matches destination bytes; otherwise conflict.
     - In `fix_project_docs`: apply moves via `_relocate`, remove planned redundant `.gitkeep` via `git_rm` (if tracked) or `unlink`, then prune empty/untracked-junk-only `docs/<subdir>` trees and `docs/` itself — leaving `docs/` intact if any non-junk file, subdirectory, conflict leftover, or git-tracked file remains. Never edit document contents; never commit in projects.
3. **`src/metaproject/cli.py`**
   - Update `doctor_cmd` docstring/help text for `.metaproject/docs/`.
4. **Tests (`tests/test_doctor.py`)**
   - Update existing doctor tests and add full coverage for AC-5 (`docs/` + `archive/`/`backlog/`/`discovery/` + `docs/.gitkeep` + untracked `.DS_Store` cleanup + `git log --follow` + idempotent second run), AC-6 (project-owned `docs/user-guide.md` kept intact), AC-7 (direct v0.8 root → `.metaproject/docs/`), AC-8 (conflicts on top-level and nested `archive/` files), AC-9 (store layout migration from both v0.8 root and v0.9 `docs.template/`, custom `docs.template/` file preserved, `learn.targets` migration), AC-10 (APFS lowercase `docs/intent.md` and `.metaproject/docs/intent.md`), and scoped `doctor [PROJECT]` / web profile.

### Step 5 — Bundled skills, `skill_history.json`, hooks check, and skill/wheel tests (`R-SKL-1..4`, `R-TPL-3`, AC-12, §6)
1. **Bundled SDLC skills (`src/metaproject/sdlc_skills/*/SKILL.md` × 11):**
   - Update all metaproject document and directory references to `.metaproject/docs/` (`INTENT.md`, `SPEC.md`, `TECH-DESIGN.md`, `PLAN.md`, `STATE.md`, `HANDOFF.md`, `TODO.md`, `ARCHITECTURE.md`, `DESIGN-INVARIANTS.md`, `VERIFIED-FACTS.md`, `archive/`, `backlog/`, `discovery/`).
   - Add hidden-directory search guidance (`--hidden` for `rg`/`fd`, or explicit `.metaproject/docs/` path) where skills instruct agents to search docs/backlog/archive (`backlog-factory`, `implement-plan`, `write-intent`, `wrapup`, etc.).
2. **Bundled metaproject skill (`src/metaproject/skill/SKILL.md`, `references/commands.md`, `references/documents.md`):**
   - Update all canonical paths to `.metaproject/docs/`, update legacy-alias and `doctor` notes for both root and `docs/` layouts, and add the hidden-directory search note.
3. **Hooks check (`R-SKL-4`):**
   - Verify `src/metaproject/hook_scripts/metaproject_hook.py` and `src/metaproject/hook_scripts/metaproject-session.sh` contain no `docs/` assumptions and remain stdlib-only.
4. **Regenerate `src/metaproject/skill_history.json` (`R-SKL-3`):**
   - Run `make skill-history` (`scripts/gen_skill_history.py`) so all 12 updated skill digests are appended while keeping all prior release digests intact.
5. **Tests (`tests/test_sdlc_skills.py`, `tests/test_backlog_factory_skill.py`, `tests/test_verify_browser_skill.py`, `tests/test_skills.py`, `tests/test_skills_sync.py`):**
   - Update skill text assertions to `.metaproject/docs/`, strengthen `test_no_root_location_reference_to_a_relocated_document` to also reject stale `docs/<DOC>.md` references in SDLC skills, assert hidden-directory search guidance (`--hidden`), update `test_wheel_contains_every_skill` to check `metaproject/templates/.metaproject.template/docs.template/INTENT.template.md` and `.gitkeep` (AC-12), and confirm `test_skills_sync.py` ledger checks pass.

### Step 6 — Root governance documentation & grep sweep (`R-SKL-5`, `R-SELF-3`, §6)
1. **`README.md`:** update all metaproject document paths to `.metaproject/docs/`, document v0.10.0 `doctor` migration (`docs/` → `.metaproject/docs/` and template store), and add the hidden-directory search note (`rg --hidden` / explicit path).
2. **`AGENTS.md`:** update Architecture, Key Files, and Process sections to `.metaproject/docs/` and `.metaproject.template/docs.template/`, plus the hidden-directory search note.
3. Run an `rg` sweep across `src/`, `tests/`, `README.md`, and `AGENTS.md` to confirm no stray `docs/` references remain outside explicit legacy/migration code and tests.

### Step 7 — Self-migrate this repository & sync `.agents/skills/` (`R-SELF-1..3`, FC-5, AC-13)
1. `git mv` all metaproject files and subdirectories in `docs/` (`INTENT.md`, `SPEC.md`, `TECH-DESIGN.md`, `PLAN.md`, `STATE.md`, `ARCHITECTURE.md`, `DESIGN-INVARIANTS.md`, `VERIFIED-FACTS.md`, `.gitkeep`, `archive/`, `backlog/`, `discovery/`) into `.metaproject/docs/`, preserving history.
2. Remove untracked `docs/.DS_Store` (if present) and remove the now-empty `docs/` directory.
3. Run `.venv/bin/metaproject skills sync` (unsandboxed — `.agents/skills/` is write-denied in the sandbox per `VERIFIED-FACTS.md`) so `.agents/skills/` and `.agents/skills/.metaproject-skills.json` match the updated bundle.
4. Dogfood `.venv/bin/metaproject review --no-tui` and `.venv/bin/metaproject doctor --dry-run .` on this repository to confirm no legacy/missing doc findings (AC-13).
5. Update `.metaproject/docs/STATE.md` (Implementation phases, Design invariants, Verified facts). Note: version bump (`0.9.1` → `0.10.0`, `R-NFR-6`) runs via `make bump-version` at release/wrapup time once `execute-tests` is green.

## Files touched

### Source (`src/metaproject/`)
- `deliverables.py` — relocated paths, `MIGRATABLE_SUBDIRS`, `LEGACY_ROOT_NAMES`, `LEGACY_DIR_NAMES`, `LEGACY_LEARN_TARGETS`, `LEGACY_NAMES`, `canonical_path`, `legacy_candidates`, `legacy_locations`.
- `templates/` — `git mv` `docs.template/` → `.metaproject.template/docs.template/`; edit `AGENTS.template.md`, `README.template.md`, `STATE.template.md`, `TODO.template.md`.
- `config.py` — `DEFAULT_LEARN_TARGETS` (`"docs/"` → `".metaproject/docs/"`).
- `review.py` — `_RELOCATED_PATHS`, `deploy_entry` legacy exclusion, `BackfillResult.legacy`, `backfill_missing` no-args legacy skip.
- `review_tui.py`, `scaffold.py`, `templates.py`, `identity.py` — docstrings/comments/messages.
- `cli.py` — `print_backfill_result` legacy table, `backfill`/`doctor` help strings.
- `universe.py` — `is_project_root`, `has_*_md` across all three layouts, `walk_dirs` skip `.metaproject`.
- `learn/collect.py` — `iter_project_dirs` skip `.metaproject`, docstrings.
- `git.py` — new `git_rm` helper.
- `doctor.py` — store layout migration (`.metaproject.template/docs.template/` + `.gitkeep`s), `LEGACY_LEARN_TARGETS` config migration, per-project file + `archive/`/`backlog/`/`discovery/` + `docs/.gitkeep` migration + empty/junk-only `docs/` cleanup.
- `sdlc_skills/*/SKILL.md` (all 11 skills) — `.metaproject/docs/` paths + hidden-directory search note.
- `skill/SKILL.md`, `skill/references/commands.md`, `skill/references/documents.md` — `.metaproject/docs/` paths, legacy notes, hidden-directory search note.
- `skill_history.json` — regenerated via `make skill-history`.

### Tests (`tests/`)
- Core & deliverables: `test_deliverables.py`, `test_bundled_templates.py`, `test_templates.py`, `test_config.py`, `test_scaffold.py`, `test_new_dry_run.py`, `test_adopt.py`, `test_nested_projects.py`, `test_e2e.py`, `test_web_profile.py`, `test_extras.py`.
- Review & backfill: `test_review.py`, `test_backfill.py`.
- Universe & learn: `test_universe.py`, `test_learn_collect.py`, `test_learn_apply.py`, `test_learn_drift.py`, `test_learn_structure.py`, `test_learn_synth.py`, `test_learn_guard.py` (verify `tests/fixtures/learn_workspace/` needs no unintended changes).
- Doctor: `test_doctor.py`.
- Skills & packaging: `test_sdlc_skills.py`, `test_backlog_factory_skill.py`, `test_verify_browser_skill.py`, `test_skills.py`, `test_skills_sync.py`.

### Repository docs & installed skills
- `README.md`, `AGENTS.md`.
- `docs/*` → `.metaproject/docs/*` (`git mv`, empty `docs/` removed).
- `.agents/skills/*` and `.agents/skills/.metaproject-skills.json` (synced via `metaproject skills sync`).

## Sequencing

1. **Step 1 must land first and atomically:** `deliverables.py`, bundled template store, `config.py`, and core tests are tightly coupled and must move together so the gate stays green.
2. **Step 2 (`backfill` legacy safeguard) and Step 3 (`universe`/`learn`)** depend on Step 1's `deliverables.legacy_locations` and `.metaproject/docs/` paths; they are independent of each other.
3. **Step 4 (`doctor` + `git.git_rm`)** depends on Step 1's `deliverables` constants (`LEGACY_LEARN_TARGETS`, `MIGRATABLE_SUBDIRS`, generalized `legacy_candidates`) and `.metaproject.template/docs.template/` store layout.
4. **Step 5 (skills + `skill_history.json`)** can run once the new CLI behavior is settled (after Steps 1–4) so skill docs describe the exact implemented `backfill`/`doctor` behavior; `make skill-history` runs after all 12 skill edits are complete.
5. **Step 6 (`README.md`, `AGENTS.md`)** runs after Step 5 so the repo-wide `rg` sweep audits the complete tree.
6. **Step 7 (self-migration + `metaproject skills sync`)** runs last in `implement-plan`, after both the updated CLI and updated bundled skills are green, so `.agents/skills/` never diverges from `docs/STATE.md` during Steps 1–6 and we can dogfood `review` and `doctor --dry-run .` immediately afterward.

## Risks / rollback

- **APFS case-insensitivity (`R-NFR-1`):** Every presence check on relocated paths must use `deliverables.exact_exists`, and case-only renames must use `_relocate`'s interim rename. Mitigated by dedicated lowercase fixtures (`docs/intent.md`, `.metaproject/docs/intent.md`) in `test_deliverables.py`, `test_review.py`, `test_backfill.py`, and `test_doctor.py`.
- **Worktree pytest & sandbox gotchas (from `VERIFIED-FACTS.md`):**
  - Run `pytest` with `--basetemp=/private/tmp/mp-gate` (no `claude` in path — worktree paths contain `.claude/worktrees/`, which trips the no-`claude`-subprocess guard) and unsandboxed (sandboxed `git init` fails with exit 128; `.agents/skills/` is write-denied in the sandbox).
- **Large test diff (~25 test files in Step 1):** Each step ends with a clean, gate-green commit so any single step can be reverted independently with `git revert` without unwinding prior work.
- **Self-migration timing (Step 7):** Moving `docs/` → `.metaproject/docs/` last in `implement-plan` keeps this repo's active `.agents/skills/` aligned with `docs/STATE.md` throughout Steps 1–6; if Step 7 needs rollback, `git revert` restores `docs/` and `.agents/skills/` cleanly.
- **No changes to operator machine state:** This plan does not touch `~/.metaproject/` or other projects on disk; upgrading the global CLI (`make install-global`), running `metaproject doctor` on the operator's real store/projects, and tagging/pushing `v0.10.0` stay operator actions after merge/wrapup.

## Verification plan

1. **Per-step quality gate (run unsandboxed with clean basetemp):**
   ```bash
   make format && make lint && .venv/bin/pytest -v tests --basetemp=/private/tmp/mp-gate
   ```
   Must be 100% green before committing each step, including `tests/test_extras.py` (no `tui` extra leak on core commands) and `tests/test_learn_guard.py` (no `claude` string in `collect.py`/`guard.py`).
2. **Wheel build & contents (AC-12):**
   - Verified in-process by `test_wheel_contains_every_skill` via `hatchling.builders.wheel.WheelBuilder` (confirming all 12 skills and `metaproject/templates/.metaproject.template/docs.template/INTENT.template.md` + `.gitkeep` are packaged), plus `make build` (`uv build --no-build-isolation`).
3. **End-to-end smoke checks in a temporary `HOME` and workspace (AC-1..AC-11):**
   - `metaproject new demo --yes --no-git` → `.metaproject/docs/` created, no `docs/`, no `HANDOFF.md`/`TODO.md`.
   - `metaproject adopt` in a repo containing `docs/user-guide.md` → creates `.metaproject/docs/`, leaves `docs/user-guide.md` untouched.
   - `metaproject review --no-tui` on a v0.9 `docs/` fixture → `↻ OUTOFDATE`, zero missing/deployable; on a migrated repo with `docs/index.md` → `✓ CLEAN`.
   - `metaproject backfill` (no args) on an unmigrated `docs/` fixture → skips into legacy table pointing to `metaproject doctor`, writes nothing under `.metaproject/docs/`.
   - `metaproject doctor --dry-run` then confirmed run on a legacy store + `config.json` + v0.9 `docs/` project (with `archive/`, `backlog/`, `discovery/`, `.gitkeep`) + mixed-`docs/` project + v0.8 root project → migrates cleanly with `git mv` history preserved, removes empty `docs/`, preserves non-empty `docs/`, and a second run reports healthy.
4. **This repository dogfooding (AC-13):**
   - `git log --follow .metaproject/docs/INTENT.md` shows history across the rename.
   - `docs/` does not exist in this repository.
   - `.venv/bin/metaproject review --no-tui` reports no legacy/missing doc findings.
   - `.venv/bin/metaproject doctor --dry-run .` reports healthy (`exit 0`).
   - `.venv/bin/metaproject skills status` reports all 12 skills `current`.
