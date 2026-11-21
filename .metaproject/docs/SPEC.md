# Move metaproject's documents from docs/ to .metaproject/docs/ — Spec

**Author**: John Fricker.
**Derived from**: docs/INTENT.md (2026-11-21).
**Last updated**: 2026-11-21.
**Status**: Approved.
**Approved by**: John Fricker (2026-11-21).

Requirement IDs: `R-LOC` document locations & deliverables, `R-LEG` legacy detection & compatibility, `R-DRX` doctor migrations, `R-TPL` templates & store, `R-SKL` skills, hooks & docs text, `R-SELF` this repository, `R-NFR` non-functional.

## Requirements

### Functional

#### Document locations & deliverables (R-LOC)

- **R-LOC-1 Single deliverable declaration.** `src/metaproject/deliverables.py` declares every metaproject-owned document and directory under `.metaproject/docs/`, preserving filenames and deliverable classes:
  - **Working (8):** `.metaproject/docs/INTENT.md`, `.metaproject/docs/SPEC.md`, `.metaproject/docs/TECH-DESIGN.md`, `.metaproject/docs/PLAN.md`, `.metaproject/docs/STATE.md`, `.metaproject/docs/ARCHITECTURE.md`, `.metaproject/docs/DESIGN-INVARIANTS.md`, `.metaproject/docs/VERIFIED-FACTS.md`.
  - **On-demand (2):** `.metaproject/docs/HANDOFF.md`, `.metaproject/docs/TODO.md`.
  - **Directory (2):** `.metaproject/docs`, `.metaproject/docs/archive`.
  - **Unchanged locations (out of scope to move):** governance files at the project root (`AGENTS.md`, `CLAUDE.md`, `README.md`, `.gitignore`), identity anchor (`.metaproject.json`), merged settings (`.claude/settings.json`), hook scripts (`.claude/hooks/metaproject_hook.py`, `scripts/metaproject-session.sh`), and project skills (`.agents/skills/`, `.claude/skills`).
  - **Non-deliverable convention directories:** metaproject skills and workflows place backlog items under `.metaproject/docs/backlog/` and ad hoc discovery notes under `.metaproject/docs/discovery/`. Neither is scaffolded by `new` or required by `review`.
- **R-LOC-2 Never write to `docs/`.** `new`, `backfill`, `adopt`, `review` (Deploy/Update), `learn`, and bundled skills never create, modify, or write into `<project>/docs/`. The only code that touches `<project>/docs/` is `doctor`'s confirmed migration moving legacy metaproject files out of it (R-DRX-3, R-DRX-4).
- **R-LOC-3 Scaffolding & adoption.** `metaproject new` (fresh directory and `new .`) and `metaproject adopt` create all scaffolded working documents, `.metaproject/docs/.gitkeep`, and `.metaproject/docs/archive/.gitkeep` under `.metaproject/docs/`, and create nothing under `docs/`. On-demand deliverables (`.metaproject/docs/HANDOFF.md`, `.metaproject/docs/TODO.md`) remain excluded from `new` and default-mode `backfill`/`adopt`.
- **R-LOC-4 `backfill` alias resolution.** `deliverables.canonical_path` resolves every form case-insensitively to its declared `.metaproject/docs/` path, so older habits never create a root-level or `docs/` file:
  - New declared path: `.metaproject/docs/INTENT.md`, `.metaproject/docs/HANDOFF.md`, `.metaproject/docs/TODO.md`, `.metaproject/docs/DESIGN-INVARIANTS.md`, `.metaproject/docs/VERIFIED-FACTS.md`, `.metaproject/docs/archive`, etc.
  - Prior `docs/` path: `docs/INTENT.md`, `docs/design.md`, `docs/HANDOFF.md`, `docs/TODO.md`, `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md`, `docs`, `docs/archive`, etc.
  - Bare new filename: `INTENT.md`, `SPEC.md`, `TECH-DESIGN.md`, `PLAN.md`, `STATE.md`, `ARCHITECTURE.md`, `DESIGN-INVARIANTS.md`, `VERIFIED-FACTS.md`, `HANDOFF.md`, `TODO.md`.
  - Legacy root filename: `intent.md`, `spec.md`, `design.md`, `plan.md`.
- **R-LOC-5 `backfill` on unmigrated projects.** In no-files mode (`metaproject backfill`), any relocated deliverable absent at `.metaproject/docs/` but present at a legacy location (`docs/` or root) is skipped (not created as a blank duplicate beside the legacy file) and reported with a pointer to `metaproject doctor`.

#### Legacy detection & compatibility (R-LEG)

- **R-LEG-1 Complete legacy mapping.** `deliverables.py` declares legacy locations for every relocated deliverable:
  - Cycle & architecture files (`INTENT.md`, `SPEC.md`, `TECH-DESIGN.md`, `PLAN.md`, `STATE.md`, `HANDOFF.md`, `ARCHITECTURE.md`): root old name (`intent.md`, `design.md`, ...), root new name (`INTENT.md`, ...), `docs/` old name (`docs/intent.md`, `docs/design.md`, ...), and `docs/` new name (`docs/INTENT.md`, ...).
  - Long-lived & on-demand files born in `docs/` (`DESIGN-INVARIANTS.md`, `VERIFIED-FACTS.md`, `TODO.md`): `docs/<NAME>.md`.
  - Directory deliverables: `docs/archive` for `.metaproject/docs/archive`, and `docs` (when `docs/` exists and holds any legacy metaproject file or `docs/archive`) for `.metaproject/docs`.
- **R-LEG-2 `review` reports legacy, never missing.**
  - For any relocated deliverable (file or directory) absent at its exact `.metaproject/docs/` path and present at a legacy location, `review_project` records it in `ReviewResult.legacy` and NEVER in `missing_files` or `deployable`.
  - Deploy cannot create a blank `.metaproject/docs/` file or directory beside a legacy copy.
  - A project compliant under the `docs/` layout reports `↻ OUTOFDATE` (`is_compliant == True`, `is_current == False`, `is_clean == False`) on upgrade, listing its legacy paths under "Legacy location — run `metaproject doctor`" with no Deploy action offered.
  - Board state precedence remains `INCOMPLETE > OUTOFDATE > DRIFTED > CLEAN`.
- **R-LEG-3 `universe` compatibility.**
  - `universe.is_project_root` recognizes `.metaproject/docs/INTENT.md` alongside `docs/INTENT.md`, `intent.md`, `.metaproject.json`, `AGENTS.md`, and package manifests, so both migrated and unmigrated projects are discovered.
  - `universe.scan_universe` sets `has_intent_md`, `has_state_md`, and `has_handoff_md` to `1` when present at `.metaproject/docs/<NAME>.md` OR at the legacy `docs/<NAME>.md` or root path.
  - `.metaproject/` is not ignored when computing newest file mtime (edits to `.metaproject/docs/` still count as project activity), and scanning a project root does not catalog archived cycles inside `.metaproject/docs/archive/` as separate projects.
- **R-LEG-4 `learn` targets & pipeline.**
  - `deliverables.learn_targets()` returns the 4 root governance files plus the 8 `.metaproject/docs/` working files.
  - `config.DEFAULT_LEARN_TARGETS` replaces `"docs/"` with `".metaproject/docs/"`, so `learn` scans `.metaproject/docs/` and never harvests from a project's own `docs/` directory.
  - `learn.collect` resolves `.metaproject/docs/` targets against the template store, keeps working-document structure-only rules (`kind == "structure"`, never body text), excludes on-demand deliverables (`.metaproject/docs/HANDOFF.md`, `.metaproject/docs/TODO.md`), and skips `SKILL_ROOTS` (`.agents`, `.claude`).
  - `learn.apply` writes accepted proposals for `.metaproject/docs/` targets to their template paths in the template store.
  - Existing `learn_proposals` and `learn_evidence` rows in `universe.db` keyed by old paths are left untouched (no database rewrite).

#### doctor migrations (R-DRX)

`doctor` keeps its confirmation model: every check reports findings, every write needs operator confirmation (per project for project checks), declining one fix never blocks subsequent checks, and `--dry-run` writes nothing (and stays the only form allowed in an agent session).

- **R-DRX-1 Template-store layout migration.** Detects legacy template paths in the operator's live template store (`~/.metaproject/templates/`), covering both root-level cycle templates (`intent.template.md`, ...) and `docs.template/` templates (cycle, long-lived, on-demand, `.gitkeep`, `archive.template/.gitkeep`), and migrates them to the target store layout chosen in `TECH-DESIGN.md` using `git mv` (when tracked) plus one commit of only the moved paths. Runs before the missing-template check (`check_templates`), and `check_templates` excludes relocating templates so it never seeds blank duplicates beside them. Conflicts (destination already exists) are kept untouched and reported as report-only.
- **R-DRX-2 `config.json` `learn.targets` migration.** Detects legacy root paths (`intent.md`, `design.md`, `STATE.md`, ...) and legacy `docs/` paths (`docs/INTENT.md`, ..., `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md`, and `"docs/"`) in `config.json`'s `learn.targets`. On confirmation, rewrites them in place to their `.metaproject/docs/` equivalents (order preserved, deduplicated) and appends any missing core `learn_targets()`.
- **R-DRX-3 Per-project document migration.** For each cataloged, metaproject-managed project (`.metaproject.json` present) — or the single named project for `metaproject doctor [PROJECT]` and web-profile `doctor` — detects every relocated metaproject document at a root or `docs/` legacy location (all 10 working + on-demand files). On per-project confirmation, moves each file straight to `.metaproject/docs/<NAME>.md` using `git mv` when the project is a git work tree and the file is tracked, or a plain move (`os.rename`) otherwise. Never overwrites an existing destination file (conflict leaves both files intact and is reported as report-only). Never commits in the project repository. Never edits the contents of moved documents.
- **R-DRX-4 Per-project directory migration & `docs/` preservation.** As part of the same per-project `project docs` check and confirmation:
  - Moves metaproject's subdirectories from `docs/` to `.metaproject/docs/`: `docs/archive/` → `.metaproject/docs/archive/`, `docs/backlog/` → `.metaproject/docs/backlog/`, and `docs/discovery/` → `.metaproject/docs/discovery/`, preserving git history (`git mv` for tracked files) and never overwriting an existing file at the destination (conflicts keep both files and are reported).
  - Handles `docs/.gitkeep` (moving it to `.metaproject/docs/.gitkeep` if absent, or removing the redundant placeholder if `.metaproject/docs/.gitkeep` already exists).
  - Leaves `docs/` in place untouched if any non-metaproject file or directory remains in it; once only OS junk (per `templates.is_junk_file_name`, e.g. `.DS_Store`) or nothing remains, removes that junk and removes the empty `docs/` directory.
- **R-DRX-5 Single-project & web-profile doctor.** `metaproject doctor <PROJECT>` and web-profile `doctor` run the updated per-project docs check against the targeted project without requiring a local template store or catalog.

#### Templates & template store (R-TPL)

- **R-TPL-1 Render output.** Rendering the bundled template store via `new`, `backfill`, `adopt`, or `review` writes all working documents, on-demand documents (when explicitly requested), `.metaproject/docs/.gitkeep`, and `.metaproject/docs/archive/.gitkeep` under `.metaproject/docs/`, and writes nothing under `docs/`. (Exact on-disk layout of the template store itself is deferred to `generate-design` — see Open questions.)
- **R-TPL-2 Governance & document template text.** All bundled templates that reference document locations — including `AGENTS.template.md`, `README.template.md`, `STATE.template.md`, `TODO.template.md`, and any other template with `docs/` paths — use `.metaproject/docs/`. No structural heading changes or unrelated content changes are made.
- **R-TPL-3 Packaging, seeding & `templates.source`.** The built wheel includes all bundled templates; `metaproject init` seeds them cleanly into `~/.metaproject/templates/`; `template_source.resolve_templates` (local store, repo-relative path source, cached git source, bundled fallback) resolves `.metaproject/docs/` templates identically. Store walks continue to skip `.git` and `templates.is_junk_file_name`.
- **R-TPL-4 No silent bundled fallback for missing live-store templates.** Existing invariant holds: a template missing from the live store is reported (`missing_template`) rather than silently falling back to the bundled copy.

#### Skills, hooks & documentation text (R-SKL)

- **R-SKL-1 Bundled skills.** Every reference to metaproject-owned documents and directories across all 11 bundled SDLC skills (`write-intent`, `generate-spec`, `generate-design`, `generate-plan`, `implement-plan`, `execute-tests`, `wrapup`, `backlog-new`, `backlog-factory`, `shipit`, `verify-browser`) and the bundled `metaproject` skill (`SKILL.md`, `references/commands.md`, `references/documents.md`) is updated to `.metaproject/docs/`. Where the `metaproject` skill documents legacy aliases and `doctor` migration, it accurately describes both root-level and `docs/` legacy locations.
- **R-SKL-2 Hidden-directory search guidance.** Skills and governance documentation that instruct agents to search metaproject documents or backlog/archive files (including `AGENTS.template.md`, `metaproject` skill, `backlog-factory`, and relevant cycle skills) explicitly note that `.metaproject/docs/` is a dot-directory skipped by default by tools such as `rg` and `fd`, so searches targeting it must pass `--hidden` or pass `.metaproject/docs/` as an explicit path.
- **R-SKL-3 `skill_history.json` regeneration.** `src/metaproject/skill_history.json` is regenerated via `make skill-history` (`scripts/gen_skill_history.py`) so all updated bundled skill digests are recorded, the skill-history coverage test passes, and existing projects carrying unmodified copies from prior releases remain classified as `outdated` (auto-updatable by `skills sync` / `doctor`).
- **R-SKL-4 Hooks.** `src/metaproject/hook_scripts/metaproject_hook.py` and `src/metaproject/hook_scripts/metaproject-session.sh` remain stdlib-only with their own `.metaproject.json` upward walk (`.metaproject.json` stays at project root). Verified to contain no stale `docs/` assumptions.
- **R-SKL-5 CLI help, `review_tui.py`, and `README.md`.** `cli.py` help text (`backfill`, `doctor`, etc.), `review_tui.py` help/messages, and `README.md` (including upgrade/migration instructions for running `metaproject doctor`) reflect `.metaproject/docs/`.

#### This repository (R-SELF)

- **R-SELF-1 Migrate this repo's documents.** Move this repository's `docs/` metaproject files and subdirectories (`INTENT.md`, `SPEC.md`, `TECH-DESIGN.md`, `PLAN.md`, `STATE.md`, `ARCHITECTURE.md`, `DESIGN-INVARIANTS.md`, `VERIFIED-FACTS.md`, `.gitkeep`, `archive/`, `backlog/`, `discovery/`) to `.metaproject/docs/` via `git mv` so git history is preserved, and remove the emptied `docs/` directory.
- **R-SELF-2 Mid-cycle timing.** `SPEC.md`, `TECH-DESIGN.md`, and `PLAN.md` complete in `docs/`; self-migration lands during `implement-plan`, after which `execute-tests` and `wrapup` operate from `.metaproject/docs/`.
- **R-SELF-3 Sync this repo's skills and root governance docs.** Run `metaproject skills sync` so `.agents/skills/` and `.agents/skills/.metaproject-skills.json` match the updated bundle; update this repo's `AGENTS.md` and `README.md` to `.metaproject/docs/`. `.metaproject.json` stays at the repository root.

### Non-functional

- **R-NFR-1 Case-insensitive filesystem safety (macOS APFS).** Every presence check on relocated deliverables uses `deliverables.exact_exists` (directory-entry comparison), never `Path.exists()`, and case-only renames go through an intermediate filename.
- **R-NFR-2 No data loss & idempotency.** No migration, deploy, or backfill ever overwrites an existing file. Move conflicts leave both files intact and report the conflict. Each move stands alone so an interrupted `doctor` run can be re-run to completion, and a clean re-run finds nothing.
- **R-NFR-3 Hidden-directory traversal.** Internal Python walks (`templates.render_template_tree`, `learn.collect.iter_target_files`, `doctor._relative_files`, `universe.get_newest_mtime_in_dir`) traverse `.metaproject/docs/` correctly, while `review.os_walk_with_depth` continues to skip dot-directories when discovering sub-projects so `.metaproject/` is never treated as a nested project.
- **R-NFR-4 Existing design invariants hold.**
  - Working deliverables remain structure-checked only and never updatable (`ReviewResult.updatable` holds governance files only).
  - Core commands (`--version`, `new`, `backfill`, `adopt`, `review --no-tui`) never import `textual`, `questionary`, or `sqlite-utils` (`tests/test_extras.py`).
  - `learn/collect.py` and `learn/guard.py` never contain the string `claude`.
  - Hook scripts remain stdlib-only.
  - `new`, `backfill`, and `adopt` preserve their create-only / agent-safe contracts; `doctor` writes remain operator-confirmed.
- **R-NFR-5 Quality gate & test suite.** `make format && make lint && make test` pass and the wheel builds via hatchling; existing tests are updated for `.metaproject/docs/` rather than deleted.
- **R-NFR-6 Release version.** Minor version bump (`0.9.1` → `0.10.0`) via `bump_version.sh` heuristics under the major-0 policy.

## Acceptance criteria

1. **Fresh scaffold (`new`) & `adopt`:** `metaproject new demo --yes --no-git` in a temp directory creates `.metaproject/docs/{INTENT,SPEC,TECH-DESIGN,PLAN,STATE,ARCHITECTURE,DESIGN-INVARIANTS,VERIFIED-FACTS}.md`, `.metaproject/docs/.gitkeep`, and `.metaproject/docs/archive/.gitkeep`; `demo/docs/` does not exist, no cycle docs exist at root, and `HANDOFF.md`/`TODO.md` are not created. `metaproject adopt` in an existing repo with its own `docs/guide.md` creates `.metaproject/docs/...` and leaves `docs/guide.md` untouched. `--dry-run` writes nothing. (R-LOC-1..3, R-TPL-1)
2. **`backfill` aliases & legacy safeguard:** `backfill intent.md`, `backfill INTENT.md`, `backfill docs/INTENT.md`, and `backfill .metaproject/docs/INTENT.md` each create `.metaproject/docs/INTENT.md` only; `backfill design.md` and `backfill docs/design.md` create `.metaproject/docs/TECH-DESIGN.md`; `backfill HANDOFF.md` / `docs/HANDOFF.md` creates `.metaproject/docs/HANDOFF.md`; `backfill TODO.md` / `docs/TODO.md` creates `.metaproject/docs/TODO.md`; `backfill docs/DESIGN-INVARIANTS.md` creates `.metaproject/docs/DESIGN-INVARIANTS.md`. None creates a file at root or under `docs/`. Running no-args `metaproject backfill` on an unmigrated `docs/` project skips deliverables present at legacy locations (creating no blank `.metaproject/docs/` duplicates) and points to `metaproject doctor`. (R-LOC-2, R-LOC-4, R-LOC-5)
3. **`review` on `docs/` and root legacy layouts:** On a fixture compliant with the `docs/` layout (including `docs/INTENT.md`, ..., `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md`, `docs/archive/`), `metaproject review --no-tui` reports `↻ OUTOFDATE` (`is_compliant == True`, `is_current == False`), lists every relocated document and `docs/archive` in `ReviewResult.legacy`, leaves `missing_files` and `deployable` empty, and offers no Deploy action for any of them. The same holds for an older root-level layout (`intent.md`, `design.md`, `STATE.md`, ...). (R-LEG-1, R-LEG-2, R-NFR-1)
4. **`review` on a project with its own `docs/`:** A migrated project that has `.metaproject/docs/` AND a project-owned `docs/index.md` (e.g. MkDocs) reports `✓ CLEAN` and never flags or modifies `docs/index.md`. (R-LOC-2, R-LEG-2)
5. **`doctor` project migration (`docs/` → `.metaproject/docs/`):** In a git fixture with `docs/{INTENT,SPEC,TECH-DESIGN,PLAN,STATE,ARCHITECTURE,DESIGN-INVARIANTS,VERIFIED-FACTS,HANDOFF,TODO}.md`, `docs/.gitkeep`, `docs/archive/2026-09-29-cycle/INTENT.md`, `docs/backlog/idea.md`, and `docs/discovery/notes.md`:
   - `doctor --dry-run` reports all planned moves and writes nothing.
   - Confirming the fix moves all files and directories to `.metaproject/docs/` via `git mv` (history preserved via `git log --follow`), makes no commit in the project repo, and removes the now-empty `docs/` directory.
   - A second `doctor` run reports healthy. (R-DRX-3, R-DRX-4, R-NFR-2)
6. **`doctor` preserves non-empty `docs/`:** In a fixture where `docs/` contains both metaproject files (`docs/INTENT.md`, `docs/archive/`) and a project-owned file (`docs/user-guide.md`), confirming `doctor` moves only metaproject's files/directories to `.metaproject/docs/` and leaves `docs/user-guide.md` and `docs/` intact. (R-DRX-4, R-NFR-2)
7. **`doctor` direct migration from root-level layout:** In a fixture with v0.8 root-level docs (`intent.md`, `design.md`, `STATE.md`, ...), confirming `doctor` moves them directly to `.metaproject/docs/{INTENT,TECH-DESIGN,STATE}.md` in one run without staging through `docs/`. (R-DRX-3)
8. **`doctor` conflict safety:** If `.metaproject/docs/INTENT.md` (or a file inside `.metaproject/docs/archive/`) already exists alongside `docs/INTENT.md`, `doctor` leaves both files untouched and reports the conflict as report-only. (R-DRX-3, R-DRX-4, R-NFR-2)
9. **`doctor` template-store and `config.json` migration:** On a fixture with a legacy template store (root-level or `docs.template/`) and `config.json` containing legacy `learn.targets` (`intent.md`, `docs/INTENT.md`, `docs/DESIGN-INVARIANTS.md`, `"docs/"`):
   - `doctor --dry-run` reports all findings and writes nothing.
   - Confirming migrates the store (one git commit of only the moved paths, no duplicate seeding by `check_templates`) and rewrites `learn.targets` to `.metaproject/docs/` paths (order preserved, deduplicated).
   - A second run reports healthy. (R-DRX-1, R-DRX-2, R-NFR-2)
10. **APFS case-insensitivity:** Fixtures with lowercase filenames (`docs/intent.md`, `intent.md`, `.metaproject/docs/intent.md`) are detected accurately via `exact_exists` (not reported present at `.metaproject/docs/INTENT.md`), reported as legacy by `review`, and renamed cleanly by `doctor`. (R-NFR-1)
11. **`universe` & `learn`:**
    - `universe` discovers projects having `.metaproject/docs/INTENT.md`, `docs/INTENT.md`, or `intent.md`, sets `has_intent_md` / `has_state_md` / `has_handoff_md` for all three layouts, counts edits in `.metaproject/docs/` in activity mtime, and does not catalog `.metaproject/docs/archive/<cycle>/` as a separate project.
    - `learn` default targets use `.metaproject/docs/` (not `docs/`), collect structure-only heading diffs from `.metaproject/docs/` working files, ignore a project's own `docs/`, and `learn apply` patches the template store cleanly. (R-LEG-3, R-LEG-4, R-NFR-3)
12. **Wheel, skills, templates & history:**
    - In-process hatchling wheel build contains all bundled templates and all 12 bundled skills (`metaproject` + 11 SDLC skills).
    - Tests verify every bundled SKILL.md and reference doc uses `.metaproject/docs/` for metaproject paths (outside explicit legacy-alias/migration notes), includes hidden-directory search guidance where search tools are referenced, and has its digest recorded in `skill_history.json`.
    - Governance templates (`AGENTS.template.md`, `README.template.md`, `STATE.template.md`, `TODO.template.md`) use `.metaproject/docs/`. (R-TPL-1..3, R-SKL-1..5)
13. **This repository migrated:** This repo's metaproject documents and `archive/`, `backlog/`, `discovery/` live under `.metaproject/docs/` with git history intact, `docs/` is gone, `.agents/skills/` is synced, `AGENTS.md` and `README.md` reference `.metaproject/docs/`, and `metaproject review --no-tui` on this repo reports no legacy/missing doc findings. (R-SELF-1..3)
14. **Quality gate & invariants:** `make format && make lint && make test` pass, including `tests/test_extras.py` and `tests/test_learn_guard.py`. (R-NFR-4, R-NFR-5)

## Flagged concerns

All resolved by the product owner, 2026-11-21:

- **FC-1 Target version.** Resolved: minor version bump (`0.9.1` → `0.10.0`); `docs/INTENT.md` updated to remove the conflicting `0.9.2` line (R-NFR-6).
- **FC-2 No-args `metaproject backfill` on unmigrated `docs/` projects.** Resolved: no-args `backfill` skips deliverables present at a legacy location and points to `metaproject doctor`, preventing blank `.metaproject/docs/` duplicates that would conflict on migration (R-LOC-5).
- **FC-3 `doctor` subdirectories, `docs/.gitkeep`, and emptied `docs/`.** Resolved: `doctor` moves `docs/archive/`, `docs/backlog/`, `docs/discovery/`, and `docs/.gitkeep` to `.metaproject/docs/` (conflict-safe, preserving `docs/` if any non-metaproject entry remains; removing OS junk like `.DS_Store` when nothing else remains so empty `docs/` is cleaned up), and `review` treats `docs/archive` and `docs` (when holding legacy metaproject items) as legacy so `docs/`-era projects report `OUTOFDATE` (R-LEG-1, R-LEG-2, R-DRX-4).
- **FC-4 `learn.targets` and existing `universe.db` learn ledger.** Resolved: replace `"docs/"` with `".metaproject/docs/"` in `DEFAULT_LEARN_TARGETS`, have `doctor` rewrite both root and `docs/` entries in `config.json`, and leave existing `learn_proposals`/`learn_evidence` rows in `universe.db` untouched (R-LEG-4, R-DRX-2).
- **FC-5 Mid-cycle self-migration timing.** Resolved: finish `SPEC.md`, `TECH-DESIGN.md`, and `PLAN.md` in `docs/`, migrate this repo to `.metaproject/docs/` during `implement-plan`, and run `execute-tests` and `wrapup` from `.metaproject/docs/` (R-SELF-2).
- **FC-6 Preserving moved document contents and archive links.** Resolved: `doctor` never edits Markdown contents inside moved project files, and existing `archive/` cycles keep their filenames and contents (R-DRX-3).

## Open questions

- **Template store layout (deferred to `generate-design`).** Carried over from `docs/INTENT.md`: should `docs.template/` move to `.metaproject.template/docs.template/` (or `.metaproject/docs.template/`), or keep its name `docs.template/` in the store and map to `.metaproject/docs/` on render? `generate-design` will evaluate the trade-offs (rendering mechanics, `hatchling` dot-directory packaging, `rglob`/hidden-dir behavior, `doctor` store migration, and `learn apply` path mapping).
