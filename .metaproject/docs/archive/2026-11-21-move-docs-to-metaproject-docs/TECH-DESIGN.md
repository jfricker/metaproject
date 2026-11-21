# Move metaproject's documents from docs/ to .metaproject/docs/ — Design

**Author**: John Fricker.
**Derived from**: docs/SPEC.md (2026-11-21).
**Last updated**: 2026-11-21.
**Status**: Approved.
**Approved by**: John Fricker (2026-11-21).

Requirement IDs refer to `docs/SPEC.md`. Per FC-5 (`R-SELF-2`), this document stays in `docs/` through planning; self-migration to `.metaproject/docs/` lands during `implement-plan`.

## Affected components

### 1. Template store layout: `.metaproject.template/docs.template/` (R-TPL-1..4)

Resolves the open question deferred from `INTENT.md` / `SPEC.md`: the bundled template store moves `docs.template/` to `.metaproject.template/docs.template/` (and `docs.template/archive.template/` to `.metaproject.template/docs.template/archive.template/`).

Why this layout fits the existing engine with zero path special-casing:

- `templates.transform_template_name` already strips `.template` from dot-prefixed entries (`".metaproject.template"` → `".metaproject"`, `"docs.template"` → `"docs"`, `"INTENT.template.md"` → `"INTENT.md"`).
- `deliverables.template_path(".metaproject/docs/INTENT.md")` and `learn/apply.py`'s `template_destination` already produce `.metaproject.template/docs.template/INTENT.template.md` verbatim.
- `templates.render_template_tree`, `templates.seed_templates`, `review.resolve_template_entry`, `learn.collect.resolve_template`, and `doctor._relative_files` all walk/resolve component-by-component without skipping `.metaproject.template` (only `.git` and `templates.is_junk_file_name` are skipped).
- `hatchling` wheel packaging (`"metaproject" = ["templates/**", ...]`) includes dot-directories and `.gitkeep` files under `templates/.metaproject.template/docs.template/` with no `pyproject.toml` changes (empirically verified via `WheelBuilder`).
- Operators who intentionally keep a custom project-docs template in `docs.template/` keep it rendering to `docs/` without colliding with metaproject's own templates.

One store-path nuance handled explicitly: `.gitkeep` files in the store do not carry a `.template` suffix (`docs.template/.gitkeep` → `.metaproject.template/docs.template/.gitkeep` and `docs.template/archive.template/.gitkeep` → `.metaproject.template/docs.template/archive.template/.gitkeep`), whereas `template_path()` appends `.template` to dotfiles. Store-layout migration declares those two `.gitkeep` store moves alongside the ten `.template.md` moves so neither is missed or re-seeded as a duplicate.

### 2. `deliverables.py`: single declaration for paths, aliases & legacy locations (R-LOC-1, R-LOC-4, R-LEG-1)

All metaproject-owned deliverables move under `.metaproject/docs/`:

| Class | Paths |
|---|---|
| `GOVERNANCE` | `AGENTS.md`, `CLAUDE.md`, `README.md`, `.gitignore` (unchanged) |
| `WORKING` | `.metaproject/docs/{INTENT,SPEC,TECH-DESIGN,PLAN,STATE,ARCHITECTURE,DESIGN-INVARIANTS,VERIFIED-FACTS}.md` |
| `ON_DEMAND` | `.metaproject/docs/HANDOFF.md`, `.metaproject/docs/TODO.md` |
| `DIRECTORY` | `.metaproject/docs`, `.metaproject/docs/archive` |
| `SETTINGS` | `.claude/settings.json` (unchanged) |

Supporting declarations in `deliverables.py` so no downstream module re-derives paths or migration rules:

- **`MIGRATABLE_SUBDIRS: Tuple[str, ...]`** — `("archive", "backlog", "discovery")`, the subdirectories `doctor` relocates from `docs/` to `.metaproject/docs/` (`R-DRX-4`).
- **Legacy file mappings:**
  - `LEGACY_ROOT_NAMES` (the 7 files that existed at project root in v0.8): `intent.md`, `spec.md`, `design.md`, `plan.md`, `STATE.md`, `HANDOFF.md`, `ARCHITECTURE.md` → `.metaproject/docs/<NEW>.md`. (`DESIGN-INVARIANTS.md`, `VERIFIED-FACTS.md`, and `TODO.md` were born in `docs/` and intentionally have NO root-level legacy mapping, so a project's own root `TODO.md` is never mistaken for a metaproject file.)
  - `LEGACY_NAMES: Mapping[str, str]` — covers every legacy file path that maps to a `.metaproject/docs/` deliverable: all 7 root old names, all 10 `docs/<NAME>.md` v0.9 paths, plus `docs/<old>` lowercase spellings (`docs/intent.md`, `docs/spec.md`, `docs/design.md`, `docs/plan.md`).
  - `LEGACY_DIR_NAMES: Mapping[str, str]` — `{"docs": ".metaproject/docs", "docs/archive": ".metaproject/docs/archive"}`.
  - `LEGACY_LEARN_TARGETS: Mapping[str, str]` — `{**LEGACY_NAMES, "docs/": ".metaproject/docs/"}`, used by `doctor.check_config`/`fix_config` (`R-DRX-2`).
- **`canonical_path(name) -> str`** (`R-LOC-4`): matches case-insensitively against (1) declared `DELIVERABLES` paths, (2) `LEGACY_NAMES` and `LEGACY_DIR_NAMES` (handling trailing slashes via `PurePosixPath`), and (3) basenames of declared file deliverables (`INTENT.md`, `TODO.md`, `DESIGN-INVARIANTS.md`, ...). Everything else is returned unchanged.
- **`legacy_candidates(root, new, template_suffix=False) -> List[str]`**: generalized to cover all 10 relocated file deliverables (not only the original 7), in priority order so the most recent layout wins if multiple copies exist and older copies surface as conflicts:
  1. `docs/<NAME>.md` (v0.9 canonical)
  2. `docs/<old>` (v0.9 lowercase / `docs/design.md`, plus lowercase `<name>.md` for `DESIGN-INVARIANTS.md` / `VERIFIED-FACTS.md` / `TODO.md`)
  3. `<old>` and `<NAME>.md` at project root (for the 7 files in `LEGACY_ROOT_NAMES` only)
  4. `.metaproject/docs/<old>` / `.metaproject/docs/<name>.md` (wrong-case file already inside `.metaproject/docs/`, for APFS case-sensitivity per `R-NFR-1`)
  Every check uses `exact_exists` (directory-entry compare) and excludes `new` itself. With `template_suffix=True`, each candidate and `new` are converted via `template_path()`.
- **`legacy_locations(project_dir) -> Dict[str, str]`** (`R-LEG-1`, `R-LEG-2`):
  - Checks all 10 relocated file deliverables via `exact_exists` and `legacy_candidates`.
  - Checks directory deliverable `.metaproject/docs/archive`: if absent at its exact path and `exact_exists(root / "docs/archive")` is a directory, maps `".metaproject/docs/archive": "docs/archive"`.
  - Checks directory deliverable `.metaproject/docs`: if absent at its exact path and `exact_exists(root / "docs")` is a directory **that contains at least one legacy metaproject file (`docs/*`), `docs/archive`, `docs/backlog`, `docs/discovery`, or `docs/.gitkeep`**, maps `".metaproject/docs": "docs"`. A project whose `docs/` holds only its own documentation (e.g. MkDocs `docs/index.md`) is NOT treated as legacy `.metaproject/docs`.

### 3. `review.py`, `review_tui.py`, and `cli.py` (R-LOC-2, R-LOC-5, R-LEG-2, R-SKL-5)

- **`_RELOCATED_PATHS`** in `review.py` includes every deliverable under `.metaproject/docs/` (all 8 working, 2 on-demand, and 2 directory deliverables), so `_present()` uses `exact_exists` for all of them (`R-NFR-1`).
- **`review_project`** already checks `if path in legacy_found: legacy[path] = legacy_found[path]; continue` before `missing_files` / `deployable`. Because `legacy_locations` now covers all 10 files plus `.metaproject/docs` and `.metaproject/docs/archive`, a compliant v0.9 `docs/` project produces `missing_files == []`, `deployable == []`, and `ReviewResult.legacy` populated — giving `↻ OUTOFDATE` (`is_compliant=True`, `is_current=False`) with no Deploy action offered (`R-LEG-2`).
- **`deploy_entry` directory-tree exclusion:** when deploying a directory deliverable (`.metaproject/docs`), `deploy_entry` excludes both on-demand paths (existing behavior) **and** any path under that directory currently reported in `legacy_locations(resolved_proj)`. This guarantees that deploying `.metaproject/docs` on a hybrid/v0.8 root-layout project (where root `intent.md` exists but `docs/` does not) never creates a blank `.metaproject/docs/INTENT.md` beside root `intent.md`.
- **`backfill_missing` legacy safeguard (`R-LOC-5`, FC-2):**
  - `BackfillResult` adds `legacy: Dict[str, str] = field(default_factory=dict)` (declared path → legacy location).
  - In no-files mode (`files is None`), `backfill_missing` computes `legacy_found = legacy_locations(resolved_proj)` once up front. Any deliverable in `legacy_found` is skipped into `result.legacy` (never passed to `deploy_entry`) so no-args `backfill` (and `adopt` on an unmigrated repo) never creates blank `.metaproject/docs/` duplicates that would conflict during `doctor`.
  - `cli.print_backfill_result` renders `result.legacy` in a table titled `"Skipped (legacy location — run \`metaproject doctor\`)"` showing `<where> → <declared>`, and counts `result.legacy` when deciding whether to print `"Nothing to do."`. Exit code remains `0`.
- **`review_tui.py` & `cli.py` help text:** update help text and docstrings (`backfill`, `doctor`, `review_tui` help) from `docs/` to `.metaproject/docs/`. `review_tui`'s existing `OUTOFDATE` cell, `legacy_panel`, and board legacy lines already format arbitrary `{where} → {declared}` entries and require no structural change.

### 4. `doctor.py` and `git.py` (R-DRX-1..5, R-NFR-1..2)

Check order is unchanged: (1) template store layout, (2) template store, (3) config `learn.targets`, (4) orphaned global skill, (5) project identity, (6) per-project docs, (7) per-project skills.

- **New git helper (`git.py`):** `git_rm(repo_dir: Path, rel_path: str) -> None` runs `git -C <repo> rm -- <rel_path>`, used only when removing a git-tracked redundant placeholder (`docs/.gitkeep` or `docs/archive/.gitkeep` when an identical destination placeholder already exists). Never commits.
- **Check 1 — Template-store layout (`check_store_layout` / `fix_store_layout`, `R-DRX-1`):**
  - `_store_moves(store)` combines `_planned_moves(store, template_suffix=True)` across all 10 relocated templates with explicit `.gitkeep` moves (`docs.template/.gitkeep` → `.metaproject.template/docs.template/.gitkeep` and `docs.template/archive.template/.gitkeep` → `.metaproject.template/docs.template/archive.template/.gitkeep`, conflict-checked with `exact_exists`).
  - `fix_store_layout` runs `_apply_moves`, cleans up empty/junk-only `docs.template/archive.template` and `docs.template` directories (leaving `docs.template/` intact if the operator placed any custom template there), and commits only the moved paths in one commit (`STORE_LAYOUT_COMMIT = "chore(templates): relocate doc templates to .metaproject.template/docs.template/"`).
  - `check_templates` continues to read `_store_moves(store)[0]` so relocating templates (including both `.gitkeep` files) are neither reported missing nor reported as extras.
- **Check 3 — Config `learn.targets` (`check_config` / `fix_config`, `R-DRX-2`):**
  - Reads `deliverables.LEGACY_LEARN_TARGETS` instead of `LEGACY_NAMES`, rewriting root paths (`intent.md`, `design.md`, ...), `docs/` file paths (`docs/INTENT.md`, ..., `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md`), and `"docs/"` → `".metaproject/docs/"` in place while preserving order and deduplicating, then appending any missing core `deliverables.learn_targets()`.
- **Check 6 — Per-project docs & directory migration (`check_project_docs` / `fix_project_docs`, `R-DRX-3..5`):**
  - Plans all actions cleanly before execution (so `--dry-run` and the confirmation prompt show the exact plan):
    1. **Relocated files (all 10 working + on-demand):** `_planned_moves(project_dir)` moves root and `docs/` files straight to `.metaproject/docs/<NAME>.md` (first candidate wins; extra candidates or taken destinations become report-only conflicts).
    2. **Metaproject subdirectories (`docs/archive/`, `docs/backlog/`, `docs/discovery/`):** walks each present directory for non-junk files (`not templates.is_junk_file_name(part)` and `".git" not in parts`), planning per-file moves `docs/<subdir>/<rel>` → `.metaproject/docs/<subdir>/<rel>`. Per-file planning (rather than directory-level `git mv`) handles partial/merged destinations cleanly without nesting or failing:
       - If the destination file already exists (`exact_exists`): for a redundant placeholder `.gitkeep` (empty or matching destination bytes), plan redundant removal; for any other file, record a report-only conflict (`conflict: {src} kept; {dest} already exists`) and leave both untouched.
       - If an entire `docs/<subdir>/` exists as an empty directory (no files), plan creating `.metaproject/docs/<subdir>` (if absent) and removing the empty source directory.
    3. **`docs/.gitkeep`:** if present, plan move to `.metaproject/docs/.gitkeep` when absent; when `.metaproject/docs/.gitkeep` already exists and `docs/.gitkeep` is empty, matches the bundled placeholder, or matches destination bytes, plan redundant removal; otherwise report conflict.
  - Execution (`fix_project_docs`):
    - Applies all planned file moves via `_relocate` (`git mv` when tracked, `os.rename` otherwise; interim rename for case-only APFS moves; never overwrites; never commits).
    - Removes planned redundant `.gitkeep` files (`git_rm` when tracked, `unlink` otherwise).
    - Cleans up emptied `docs/<subdir>` trees and then `docs/` itself **only if** every remaining entry (if any) is an untracked OS junk file per `templates.is_junk_file_name` (e.g. `.DS_Store`), unlinking such junk before `rmdir`. If any non-junk file, subdirectory, conflict leftover, or git-tracked file remains in `docs/`, `docs/` stays untouched (`R-DRX-4`).
  - `metaproject doctor [PROJECT]` and web-profile `doctor` call the exact same `check_project_docs` / `fix_project_docs` functions (`R-DRX-5`).

### 5. `universe.py`, `config.py`, and `learn/` (R-LEG-3, R-LEG-4, R-NFR-3)

- **`universe.py`:**
  - `is_project_root` checks `".metaproject/docs/INTENT.md"` alongside `"docs/INTENT.md"` and `"intent.md"`.
  - `scan_universe` checks all three layouts for `has_intent_md`, `has_state_md`, and `has_handoff_md`. No SQLite schema changes.
  - `walk_dirs` skips descending into a child named `".metaproject"` during project discovery so scanning a project root never catalogs archived cycles inside `.metaproject/docs/archive/<cycle>/` as nested projects (`R-LEG-3`). `IGNORED_DIRECTORIES` does NOT include `".metaproject"`, so `get_newest_mtime_in_dir` continues to count edits inside `.metaproject/docs/` toward project activity.
- **`config.py`:**
  - `DEFAULT_LEARN_TARGETS = [*deliverables.learn_targets(), ".metaproject/docs/", "Makefile", "pyproject.toml"]` (`R-LEG-4`).
- **`learn/collect.py` & `learn/apply.py`:**
  - `iter_project_dirs` skips descending into `".metaproject"` during workspace project discovery (same guard as `universe.walk_dirs`).
  - `iter_target_files`, `resolve_template`, and `apply.resolve_template_file` work directly on `.metaproject/docs/` targets with no special-casing. Existing `universe.db` `learn_proposals`/`learn_evidence` rows stay untouched (FC-4). `collect.py` and `guard.py` keep the no-`claude`-string invariant (`R-NFR-4`).

### 6. Bundled templates, skills, hooks, and documentation (R-TPL-2, R-SKL-1..5, R-SELF-1..3)

- **Templates:** move `docs.template/` → `.metaproject.template/docs.template/` and update path references in `AGENTS.template.md`, `README.template.md`, `STATE.template.md`, `TODO.template.md` (and any other template referencing `docs/`). `AGENTS.template.md` adds a brief note that `.metaproject/docs/` is a hidden directory so `rg`/`fd` searches targeting it need `--hidden` or an explicit path (`R-SKL-2`).
- **Skills (12 total):** update every metaproject path in `src/metaproject/sdlc_skills/*/SKILL.md` (11 skills) and `src/metaproject/skill/` (`SKILL.md`, `references/commands.md`, `references/documents.md`) to `.metaproject/docs/`, update legacy-migration notes in the `metaproject` skill to document both root and `docs/` legacy layouts, and add hidden-directory search guidance (`--hidden` / explicit path) wherever skills reference searching docs, backlog, or archive (`backlog-factory`, `implement-plan`, `metaproject` skill, etc.). Regenerate `src/metaproject/skill_history.json` via `make skill-history` (`R-SKL-3`).
- **Hooks (`R-SKL-4`):** `metaproject_hook.py` and `metaproject-session.sh` walk upward for `.metaproject.json` (which stays at project root) and contain no `docs/` path assumptions; both remain stdlib-only and unchanged.
- **This repository (`R-SELF-1..3`):** during `implement-plan`, `git mv` this repo's `docs/` files and subdirectories (`archive/`, `backlog/`, `discovery/`) to `.metaproject/docs/`, remove the emptied `docs/`, sync `.agents/skills/` via `metaproject skills sync`, and update `AGENTS.md` and `README.md` (including v0.10.0 upgrade notes).

## Data flow / interfaces

```
new / adopt ───► deliverables (paths) ──► templates (.metaproject.template/docs.template/) ──► project/.metaproject/docs/*.md

backfill ──────► deliverables (canonical_path, legacy_locations)
                   ├── named files ──► resolve alias ──► project/.metaproject/docs/<file>
                   └── no-files ────► skip legacy (BackfillResult.legacy → "run doctor")
                                      deploy missing (excluding on-demand + legacy)

review ────────► deliverables.legacy_locations (files + docs + docs/archive)
                   └──► ReviewResult.legacy ──► board: ↻ OUTOFDATE ("run doctor", no Deploy)

doctor ────────► 1. store layout (_store_moves: root + docs.template + .gitkeep → .metaproject.template/docs.template/, 1 git commit)
                 2. template store (seed missing; skips relocating)
                 3. config (LEGACY_LEARN_TARGETS: root + docs/* + docs/ → .metaproject/docs/*)
                 4. orphaned global skill
                 5. project identity
                 6. project docs (per project: 10 files + archive/backlog/discovery + .gitkeep → .metaproject/docs/,
                    git mv, conflict-safe, remove empty/junk-only docs/, never commits)
                 7. project skills
```

Public / cross-module interface changes:

| Interface | Change |
|---|---|
| `deliverables.DELIVERABLES` | Working, on-demand, and directory paths move to `.metaproject/docs/...` |
| `deliverables.LEGACY_ROOT_NAMES`, `LEGACY_DIR_NAMES`, `LEGACY_LEARN_TARGETS`, `MIGRATABLE_SUBDIRS` | New constants; `LEGACY_NAMES` expanded to cover all `docs/` and root file aliases |
| `deliverables.legacy_candidates`, `legacy_locations`, `canonical_path` | Extended for all 10 files, `.metaproject/docs` / `.metaproject/docs/archive` directories, and APFS `.metaproject/docs/<lowercase>` |
| `review.BackfillResult.legacy` | New field (`Dict[str, str]`, default empty) for no-args legacy skips (`R-LOC-5`) |
| `review.deploy_entry` | Directory deploys exclude `legacy_locations` entries in addition to `ON_DEMAND` |
| `git.git_rm` | New helper for removing tracked redundant `.gitkeep` placeholders during migration |
| `config.DEFAULT_LEARN_TARGETS` | Replaces `"docs/"` with `".metaproject/docs/"` |

## Alternatives considered

- **Keep `docs.template/` in the template store and map it to `.metaproject/docs/` in code.** Rejected: requires a translation layer across `render_template_tree`, `resolve_template_entry`, `learn.collect.resolve_template`, `learn.apply.template_destination`, `deliverables.template_path`, and `deploy_entry`; prevents operators from keeping a real `docs.template/` for project documentation; breaks the 1-to-1 store-to-project path rule established in the 2026-09-29 cycle.
- **Name the store directory `.metaproject/docs.template/` (without `.template` on `.metaproject`).** Rejected: breaks exact round-trip symmetry with `deliverables.template_path()` and `learn/apply.py`'s `template_name()` (both emit `.metaproject.template`), requiring special-case code for `.metaproject` and diverging from `.gitignore.template` / `archive.template`.
- **Move `docs/archive/`, `docs/backlog/`, `docs/discovery/` with directory-level `git mv`.** Rejected: fails or nests directories when `.metaproject/docs/archive/` already exists (partial migration or earlier `backfill`); per-file `git mv` preserves identical `R100` git history while handling conflicts file-by-file without overwriting.
- **Add `.metaproject` to `universe.IGNORED_DIRECTORIES`.** Rejected: `get_newest_mtime_in_dir` skips `IGNORED_DIRECTORIES`, which would make edits to `.metaproject/docs/` invisible to project activity classification (`Active Now` / `Idle`). Skipping `.metaproject` only during project-root discovery walks preserves mtime accuracy while preventing `.metaproject/docs/archive/<cycle>/` from being cataloged as a project.
- **Treat root `TODO.md` as a legacy metaproject location.** Rejected: metaproject never placed `TODO.md` at the project root, and many repositories own a root `TODO.md`; only `docs/TODO.md` is legacy.
- **Let `doctor` rewrite Markdown links inside moved files.** Rejected per `INTENT.md` Out of Scope and FC-6: relative links (`archive/...`) inside `ARCHITECTURE.md` continue to resolve because `ARCHITECTURE.md` and `archive/` move together, and mutating user document text risks unintended diffs.

## Trade-offs and risks

- **Dot-directory visibility in CLI search tools (`rg`, `fd`, editor quick-open).** `.metaproject/` is hidden by default in `rg`/`fd` and some harnesses. Mitigated by explicit `--hidden` / path guidance in `AGENTS.template.md` and bundled skills (`R-SKL-2`), while internal Python walks traverse `.metaproject/docs/` explicitly.
- **Broad test churn (~29 test files).** Existing assertions hardcode `docs/` and `docs.template/`. All tests are updated for `.metaproject/docs/` rather than deleted (`R-NFR-5`), plus new regression tests cover `docs/` → `.metaproject/docs/` migration, `archive/`/`backlog/`/`discovery/`, non-empty `docs/` preservation, `backfill` legacy skips, and APFS case handling.
- **Mid-cycle switch (`R-SELF-2`).** Once `implement-plan` moves this repository's `docs/` → `.metaproject/docs/` and syncs `.agents/skills/`, `execute-tests` and `wrapup` run against `.metaproject/docs/`. Updating `skill_history.json` and syncing `.agents/skills/` before finishing `implement-plan` ensures the local skills match the moved tree.
- **Subdirectory ownership heuristic in `doctor`.** A metaproject-managed project that happened to put non-metaproject files inside `docs/archive/`, `docs/backlog/`, or `docs/discovery/` will have them listed as planned moves in `doctor`. Mitigated by `doctor` printing every planned file move and requiring explicit per-project confirmation (with `--dry-run` preview) before touching disk.
- **APFS case-insensitivity.** All presence checks on relocated paths go through `deliverables.exact_exists`, and case-only renames go through `_relocate`'s interim-file two-step rename. Any missed `Path.exists()` check on a relocated path would misclassify a lowercase file on macOS; regression fixtures cover `docs/intent.md` and `.metaproject/docs/intent.md`.
- **Two-step template store vs project upgrade order.** If an operator upgrades the CLI and runs `review` or `backfill` before `doctor`, their live store at `~/.metaproject/templates/` still has `docs.template/` until `doctor` migrates it (`check_store_layout` runs first). `backfill`'s legacy safeguard (`R-LOC-5`) prevents creating blank duplicates in unmigrated projects, and `doctor` migrates store, config, and projects in one guided pass.

## Open questions

None — the template store layout question from `INTENT.md` / `SPEC.md` is resolved in §1 (`.metaproject.template/docs.template/`), pending operator sign-off on this design.
