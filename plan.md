# Absorb sdlc-skills into metaproject; move cycle docs to docs/ — Implementation Plan

**Author**: John Fricker.
**Derived from**: spec.md (2026-09-28), design.md (2026-09-28).
**Last updated**: 2026-09-28.
**Status**: Approved.
**Approved by**: John Fricker (2026-09-28).

## Context

Approved intent/spec/design (2026-09-28): the 8 SDLC skills move from the separate
`~/Projects/SDLC-skills` plugin into the metaproject wheel and are copied into each
project's `.agents/skills/` by `new`/`backfill`; `init` stops installing skills; cycle
documents move to `docs/` with new names (`INTENT.md`, `SPEC.md`, `TECH-DESIGN.md`,
`PLAN.md`, `STATE.md`, `HANDOFF.md`, `ARCHITECTURE.md`); `review` gains an `OUTOFDATE`
state for legacy layouts; `doctor` migrates stores, config and projects. Spec IDs
(R-*) and design sections (§n) are referenced below.

## Setup

- Commit the approved cycle docs on `main` (`intent.md`, `spec.md`, `design.md`,
  `plan.md`, `STATE.md`, backlog status line).
- Work in worktree `.claude/worktrees/sdlc-skills-in-metaproject` on branch
  `sdlc-skills-in-metaproject`; build its venv unsandboxed (`uv`, VERIFIED-FACTS).
- Gate per step: `make format && make lint && make test` with
  `--basetemp=/private/tmp/mp-<step>` (no `claude` in path), run unsandboxed. Commit only
  when green; update STATE.md Implementation phases per step.

## Steps

### 1. Self-migrate this repo's documents (R-SELF-1, FC-2)
- `git mv` `intent.md`→`docs/INTENT.md`, `spec.md`→`docs/SPEC.md`,
  `design.md`→`docs/TECH-DESIGN.md`, `plan.md`→`docs/PLAN.md`, `STATE.md`→`docs/STATE.md`,
  `ARCHITECTURE.md`→`docs/ARCHITECTURE.md`; fix relative links inside them (archive
  links in ARCHITECTURE lose the `docs/` prefix).
- Copy `~/Projects/SDLC-skills/docs/backlog/wrapup-delete-cycle-branch.md` into
  `docs/backlog/` (R-RET-2).
- Check no test reads root `ARCHITECTURE.md`/cycle docs from the repo; fix if so.

### 2. Import the skills with history (R-IMP-1..4, §8)
- `git remote add sdlc-skills ~/Projects/SDLC-skills && git fetch sdlc-skills &&
  git subtree add --prefix=sdlc-skills-import sdlc-skills main` (includes `e6f42a4`).
- `git mv sdlc-skills-import/skills/<name> src/metaproject/sdlc_skills/<name>` ×8;
  `git rm -r sdlc-skills-import`; `git remote remove sdlc-skills`.
- `pyproject.toml`: add `sdlc_skills/**` to hatchling package data.
- Commit ("import sdlc-skills with history"); no text edits yet.

### 3. Relocated deliverables + template store (R-DOC-0..4, §1, §2)
Lands together so the suite stays consistent.
- `src/metaproject/deliverables.py`: new paths; `LEGACY_NAMES`, `canonical_path`,
  `legacy_locations`, `exact_exists` (os.listdir exact-name compare).
- `src/metaproject/templates/`: `git mv` the 7 templates into `docs.template/` with new
  names; edit bodies that name cycle docs (`**Derived from**` headers, AGENTS/CLAUDE
  process text, ARCHITECTURE links, STATE comments).
- `review.deploy_entry`: directory deploys pass on-demand paths (relative to the
  directory) as `exclude` to `render_template_tree` — reuse the `_ON_DEMAND_PATHS`
  pattern in `scaffold.py`.
- `review.backfill_missing`: canonicalise named files via `canonical_path`; `exact_exists`
  for relocated paths.
- `config.DEFAULT_LEARN_TARGETS` follows automatically; verify.
- Tests: `test_deliverables.py` (mapping, aliases, APFS case fixture with lowercase
  `docs/intent.md`), `test_bundled_templates.py`, `test_templates.py`, `test_backfill.py`
  (acceptance 7, HANDOFF not created by `docs` deploy), and path updates across the
  ~16 test files that name root cycle docs.

### 4. Review legacy detection + `OUTOFDATE` (R-DOC-5, §4)
- `review.ReviewResult`: `legacy` field (+ `from_mapping`), `is_current`, `is_clean`
  requires it; `review_project` routes legacy docs to `legacy`.
- `review_tui.py`: `GLYPH_OUTOFDATE = "↻"`, `STATE_OUTOFDATE` (cyan), precedence
  INCOMPLETE > OUTOFDATE > DRIFTED > CLEAN; detail screen "Legacy location — run
  `metaproject doctor`" section, no action key; `?` help; printed board and header score.
- Tests: `test_review.py` (acceptance 8, verdict precedence, NO_COLOR glyph).

### 5. learn / universe markers (R-DOC-3, R-DOC-6, R-SKL-8, §5)
- `learn/collect.iter_target_files`: drop paths under `.agents/` or `.claude/`.
- `universe.is_project_root`: also `docs/INTENT.md`; `has_*_md` true for either location.
- `identity.py` docstring. Tests: `test_learn_collect.py` (acceptance 12),
  `test_universe.py`.

### 6. Project skills, `new`/`backfill`, `init` (R-SKL-1..7, R-INI-1..2, §3, §7)
- `src/metaproject/skills.py` rewrite: `BundledSkill`, `bundled_skills`,
  `project_skills_dir` (R-SKL-5 refusal), `skill_state` (reuse `is_skill_current`,
  `_bundled_files`), `install_project_skills` (create-only, tracker-aware),
  `LEGACY_GLOBAL_SKILL_DIR`; remove `get_skill_install_dir`, `METAPROJECT_SKILL_DIR`,
  force/prune paths.
- `scaffold.scaffold_project`: call after `link_agent_skills`, before git init; add
  `skills` to the result.
- `review.backfill_missing` no-files mode: install missing skills; `BackfillResult.skills`,
  `skills_notice`.
- `cli.py`: `new`/`backfill` print skills report + notice; `init` drops
  `report_skill_install`, `--no-skill`, skill wording of `--force`.
- `tests/conftest.py`: drop `METAPROJECT_SKILL_DIR`; ensure HOME is tmp for init tests.
- Tests: `test_skills.py` rewrite, `test_scaffold.py`, `test_new_dry_run.py`,
  `test_backfill.py`, `test_e2e.py` (acceptance 3–6).

### 7. doctor (R-DRX-1..7, §6)
- `git.py`: `is_tracked`, `git_mv`, `commit_paths`.
- `doctor.py`: `_relocate` (exact-exists conflict refusal, mkdir parent, git mv vs
  os.rename, case-only rename via `<dest>.metaproject-tmp`); new checks in order:
  store layout (commit only moved paths), store, config (+ legacy target rewrite),
  orphaned global skill, identity, project docs (per project `_apply`), project skills
  (install missing; stale/refused reported only). Delete `check_skill`/`fix_skill`.
  Reuse `db.query_projects` + `identity.read_identity` as in `check_identity`.
- `cli.doctor_cmd` docstring/output.
- Tests: `test_doctor.py` (acceptance 9, 10; re-run idempotent; dry-run writes nothing).

### 8. Skill text + skill tests (R-TXT-1..3, R-SKL-7)
- Separate commit after step 2's move: in each `sdlc_skills/*/SKILL.md` — precondition
  preamble under the title, drop SessionStart/version bullets, `docs/<NEW>.md` paths,
  blank rule, `backfill` examples, wrapup archive source/reset, no `sdlc-skills:` or
  "plugin" wording.
- `src/metaproject/skill/SKILL.md` + `references/`: new paths, project-skill story.
- New `tests/test_sdlc_skills.py`: 9 bundled skills; frontmatter `name` == dir and
  `description`; preamble present; no `sdlc-skills:` / SessionStart / root-location
  names; wheel contains them (`uv build --no-build-isolation` into tmp, inspect zip).

### 9. Documentation (R-TXT-2..4, R-RET-1, §9)
- `README.md`: project-local skills, bare names, precondition, docs layout, `doctor`
  migration, ordered retirement steps.
- `AGENTS.md` (architecture: review states incl. `OUTOFDATE`, doctor, skills module),
  `CLAUDE.md` Process section, `docs/ARCHITECTURE.md` invariant replacement.
- `rg` sweep: no remaining root-location references or `sdlc-skills:` strings outside
  `docs/archive/` and `docs/backlog/`.

### 10. Populate this repo's skills (R-SELF-1)
- Run the worktree's `metaproject backfill` (unsandboxed — `.agents/skills` is
  write-denied in the sandbox) to install the 9 skills; commit them.

## Risks / rollback
- APFS case-insensitivity: every relocated presence check uses `exact_exists`; covered by
  lowercase fixtures.
- Steps 3 and 6 carry most test churn; each commit is gate-green so any step can be
  reverted independently (step 3 is atomic by design).
- Mid-cycle: after step 1 the installed plugin skills read the root; remaining stages
  follow the bundled skill text with `docs/` paths.
- No operator machine state changes in this plan: plugin uninstall, `uv tool install`,
  `doctor` on the real store/projects, bump, and the SDLC-skills README pointer are
  operator steps after merge (R-RET-1), handled at wrapup.

## Verification
- Full gate green; wheel builds and contains `sdlc_skills/*/SKILL.md` + `skill/`.
- Manual smoke in a tmp HOME: `metaproject init` (no `~/.claude` created); `metaproject
  new demo` → `docs/INTENT.md…`, `.claude/skills/write-intent/SKILL.md` resolves;
  `review` on a legacy fixture shows `↻ OUTOFDATE`; `doctor --dry-run` then confirmed
  run on a legacy store + project migrates and a second run is clean.
- `git log --follow src/metaproject/sdlc_skills/write-intent/SKILL.md` reaches
  SDLC-skills commits.
