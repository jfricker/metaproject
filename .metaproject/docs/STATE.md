# MetaProject — State

## Process

<!-- each stage ticks its own item here as it completes -->
- [x] 1. write-intent: INTENT.md approved
- [x] 2. generate-spec: SPEC.md approved
- [x] 3. generate-design: TECH-DESIGN.md approved
- [x] 4. generate-plan: PLAN.md approved
- [x] 5. implement-plan: code and tests written
- [x] 6. execute-tests: tests passing
- [ ] 7. wrapup: cycle archived

## Implementation phases

<!-- written by implement-plan as steps land -->
- [x] 1. Relocated deliverables, template store layout, and review legacy detection
- [x] 2. backfill no-args legacy safeguard
- [x] 3. universe and learn compatibility
- [x] 4. doctor migrations and git.git_rm
- [x] 5. Bundled skills, skill_history.json, and skill/wheel tests
- [x] 6. Root governance docs (README.md, AGENTS.md) and grep sweep
- [x] 7. Self-migrate this repo and sync .agents/skills/

## Design invariants (regression guards)

<!-- written by implement-plan/execute-tests; appended to docs/DESIGN-INVARIANTS.md by wrapup -->
- All metaproject-owned working, on-demand, and directory deliverables live under `.metaproject/docs/` (`deliverables.DELIVERABLES`); `new`, `backfill`, `adopt`, `review`, and `learn` never write into project `docs/` (`R-LOC-1..4`).
- The bundled template store uses `.metaproject.template/docs.template/` (`R-TPL-1..4`), matching `deliverables.template_path` and `learn/apply.py`'s `template_destination` 1:1 while leaving custom operator `docs.template/` trees intact.
- No-args `backfill_missing` skips deliverables found via `legacy_locations` into `BackfillResult.legacy` (pointing to `metaproject doctor`), and `deploy_entry` excludes legacy child paths during directory deploys so duplicates never block `doctor` (`R-LOC-5`).
- `universe` and `learn.collect` skip descending into `.metaproject` during project-root discovery walks while leaving `.metaproject` out of `universe.IGNORED_DIRECTORIES` so `.metaproject/docs/` edits still update activity mtime (`R-LEG-3`).
- `doctor` migrates root and `docs/` layouts (including `docs/{archive,backlog,discovery}/` per-file, `.gitkeep`, and `docs.template/` `.gitkeep`s) via `exact_exists` + conflict-safe `git mv`/`git rm` and prunes `docs/` only when empty or untracked-junk-only, never committing inside projects (`R-DRX-1..5`).

## Open items carried into PLAN.md

<!-- written by implement-plan/execute-tests; resolved with the operator by wrapup -->

## Verified facts (do not re-investigate)

<!-- written by implement-plan/execute-tests; appended to docs/VERIFIED-FACTS.md by wrapup -->
- `WheelBuilder` packages dot-directories and `.gitkeep` files under `metaproject/templates/.metaproject.template/docs.template/` with zero `pyproject.toml` changes (`tests/test_sdlc_skills.py::test_wheel_contains_every_skill`).
- `make skill-history` regenerates `src/metaproject/skill_history.json` additively across all 12 skills while retaining all prior release digests.
- `AGENTS.md`, `CLAUDE.md`, `README.md`, `.gitignore`, `.metaproject.json`, `.agents/skills/`, `.claude/`, and hook scripts stay at their existing locations; `DESIGN-INVARIANTS.md`, `VERIFIED-FACTS.md`, and `TODO.md` have no root-level mapping in `LEGACY_ROOT_NAMES`.
- Worktree pytest runs must pass `--basetemp=/private/tmp/mp-...` because the worktree path includes `.claude/worktrees/`, which trips `test_learn_guard`'s `claude` path guard.
- `tests/test_doctor.py::_cli_env` sets `COLUMNS=140` so Rich table titles do not wrap long pytest `--basetemp` project paths across lines.
- Wheel build (`make build`) and `zipfile` inspection confirm all 12 bundled skills (`SKILL.md` + `references/`) and all 12 entries under `metaproject/templates/.metaproject.template/docs.template/` (10 `.template.md` + two `.gitkeep` files) are packaged with zero `metaproject/templates/docs.template/` entries.
- End-to-end CLI smoke check in an isolated `HOME`/`METAPROJECT_CONFIG_DIR` passed AC-1..AC-11 (`init`, `new`, `adopt`, `backfill` aliases + no-args legacy skip, `review --no-tui`, `universe`, and `doctor` store/config/project migrations with `git mv --follow` history).
- `scripts/bump_version.py --dry-run` evaluates the diff as `MINOR` (`0.9.1` → `0.10.0`), matching `R-NFR-6` (deferred until release/wrapup).
