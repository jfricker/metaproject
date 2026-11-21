# Absorb sdlc-skills into metaproject; move cycle docs to docs/ — Spec

**Author**: John Fricker.
**Derived from**: intent.md (2026-09-28).
**Last updated**: 2026-09-28.
**Status**: Approved.
**Approved by**: John Fricker (2026-09-28).

Requirement IDs: `R-IMP` import, `R-SKL` project skills, `R-INI` init, `R-DOC` docs
relocation, `R-DRX` doctor, `R-TXT` skill/documentation text, `R-SELF` this repo,
`R-RET` retirement, `R-NFR` non-functional.

## Requirements

### Functional

#### Import (R-IMP)

- **R-IMP-1** The 8 skills (`backlog-new`, `write-intent`, `generate-spec`,
  `generate-design`, `generate-plan`, `implement-plan`, `execute-tests`, `wrapup`) are
  imported from `~/Projects/SDLC-skills` with `git subtree add` from a local-path remote
  into a staging prefix, so their commit history is reachable from metaproject's log.
- **R-IMP-2** Each `skills/<name>/` directory (SKILL.md and any sibling files) is moved
  with `git mv` into a bundled package-data directory inside `src/metaproject/`. The
  directory is `src/metaproject/sdlc_skills/`, so it cannot shadow the existing
  `metaproject.skills` module (FC-1).
- **R-IMP-3** After curation the staging prefix is gone: no `plugin.json`,
  `marketplace.json`, `hooks/`, SessionStart script, shell test, or the old repo's own
  SDLC/root docs remain in the metaproject tree.
- **R-IMP-4** `pyproject.toml` package data includes the new directory so the built wheel
  carries all 8 skills.

#### Project skills (R-SKL)

- **R-SKL-1** A single declaration lists the bundled project skills: the metaproject
  skill (`src/metaproject/skill/`) plus the 8 SDLC skills. Every consumer (`new`,
  `backfill`, `doctor`, tests) reads that declaration.
- **R-SKL-2** `metaproject new` (fresh directory and `new .`) copies every declared skill
  into `<project>/.agents/skills/<name>/`, after `link_agent_skills` has created the
  layout, as part of the same rollback-tracked transaction. `--dry-run` lists the skill
  directories it would create and writes nothing.
- **R-SKL-3** `metaproject backfill` with no file arguments also copies any declared
  skill whose `.agents/skills/<name>/` directory is absent. It never overwrites or adds
  files inside an existing skill directory. With explicit file arguments it touches only
  those files (skills are not implied).
- **R-SKL-4** Per-skill outcomes use the existing states: `installed` (written),
  `current` (byte-identical, nothing written), `stale` (differs; left untouched and
  reported). `new` and `backfill` never produce `updated`.
- **R-SKL-5** If `.claude/skills` is a real directory, or a symlink that does not resolve
  to the project's own `.agents/skills`, no skill is written and the command prints one
  notice naming the path and the reason. The rest of the scaffold/backfill proceeds.
- **R-SKL-6** Skills are ordinary project files: nothing written by `new` or `backfill`
  adds them to `.gitignore`, so they are committed with the project. `new`'s initial
  commit (when it runs git) includes them.
- **R-SKL-7** Skills are invoked by bare name (`/write-intent`, …). Each SKILL.md
  frontmatter `name` equals its directory name.
- **R-SKL-8** `review` does not report, diff, or remediate skill files, and `learn` never
  collects evidence from `.agents/skills/` or `.claude/skills/`.

#### init (R-INI)

- **R-INI-1** `metaproject init` installs no skill anywhere. The `--no-skill` option is
  removed, and `--force` no longer mentions or affects skills.
- **R-INI-2** `install_skill`'s global default target (`~/.claude/skills/metaproject/`)
  and the `METAPROJECT_SKILL_DIR` override are removed or repurposed; nothing in the
  package writes to `~/.claude/` any more, except `doctor`'s confirmed removal
  (R-DRX-6).

#### Docs relocation (R-DOC)

- **R-DOC-0 Naming.** Cycle documents get uppercase names, and the design document is
  renamed: `intent.md` → `INTENT.md`, `spec.md` → `SPEC.md`, `design.md` →
  `TECH-DESIGN.md`, `plan.md` → `PLAN.md`. `STATE.md`, `HANDOFF.md`, `ARCHITECTURE.md`
  keep their names. The old→new mapping is declared once and every rename and alias below
  reads it.
- **R-DOC-1** The deliverable declaration moves `INTENT.md`, `SPEC.md`,
  `TECH-DESIGN.md`, `PLAN.md`, `STATE.md`, `ARCHITECTURE.md` (working) and `HANDOFF.md`
  (on-demand) to `docs/<file>`. `AGENTS.md`, `CLAUDE.md`, `README.md`, `.gitignore` stay at the root.
  `docs`, `docs/archive`, `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md` are
  unchanged.
- **R-DOC-2** The bundled template store places those templates under `docs.template/`
  (e.g. `docs.template/INTENT.template.md`), so rendering produces `docs/INTENT.md` with
  no path special-casing. Template text that names cycle documents (e.g. the
  `**Derived from**: intent.md` header) uses the new names. `learn apply` writes to the moved template
  paths.
- **R-DOC-3** `new`, `backfill`, `review`, `learn` (collect, targets, apply), `universe`
  project markers and `has_*_md` columns, and `identity` use the `docs/` paths.
  `DEFAULT_LEARN_TARGETS` derives the new paths.
- **R-DOC-4** `backfill` accepts the new path (`docs/INTENT.md`), the bare new name
  (`INTENT.md`), and the old name (`intent.md`, `design.md`, …) for a relocated
  deliverable, matched case-insensitively, and resolves each to its `docs/` path, so an
  older-habit invocation creates the right file and never a root-level one.
- **R-DOC-5** `review` on a project that still has a relocated document at the root
  or under its old name (and not at its new `docs/` path) reports it as "at legacy location — run `metaproject doctor`"
  rather than as missing, and does not offer Deploy for it.
- **R-DOC-6** `universe` still recognizes an unmigrated project as a project (root
  `intent.md` stays a detection marker alongside `docs/INTENT.md`).

#### doctor (R-DRX)

`doctor` keeps its model: each check reports findings, and each fix needs operator
confirmation; `--dry-run` writes nothing. New and changed checks:

- **R-DRX-1 Template-store layout.** Detects root-level cycle templates in the live store
  (`~/.metaproject/templates/<name>.template.md` for the relocated set) and offers to
  move and rename them to `docs.template/<NEW-NAME>.template.md`. The store is a git repo: the move is a `git mv` plus one
  commit. If the destination already exists, that file is refused and reported. Runs
  before the existing missing-template check, so a migrated store isn't re-seeded with
  duplicates.
- **R-DRX-2 learn.targets.** Old root paths for relocated deliverables in
  `learn.targets` are reported and, on confirmation, rewritten to their `docs/` paths
  (order preserved, no duplicates).
- **R-DRX-3 Project docs migration.** For each cataloged, metaproject-managed project
  (has `.metaproject.json`), detects relocated documents at the root under old or new
  names. The fix, confirmed per project, moves and renames each to its `docs/` path
  (`intent.md` → `docs/INTENT.md`, `design.md` → `docs/TECH-DESIGN.md`, …) — `git mv` when the project is a git
  work tree and the file is tracked, a plain move otherwise. It never overwrites an existing
  `docs/<file>`; that file is left in place and reported. It does not commit in the
  project.
- **R-DRX-4 Project skills.** For each cataloged, metaproject-managed project, reports
  missing and stale declared skills. The fix, confirmed per project, installs missing
  skills only; stale skills are reported and never overwritten (FC-4). It skips projects
  under R-SKL-5 with the same notice.
- **R-DRX-5** The global-skill check (`check_skill` / `fix_skill`) is removed.
- **R-DRX-6 Orphaned global skill.** If `~/.claude/skills/metaproject/` exists, report it
  and, on confirmation, delete it. Nothing else under `~/.claude/` is touched.
- **R-DRX-7** Declining one fix never blocks the remaining checks (existing R-DR-8).
  `doctor --dry-run` stays the only form allowed in an agent session.

#### Skill and documentation text (R-TXT)

- **R-TXT-1** Each of the 8 SKILL.md files opens its body with the same precondition
  preamble: the project must have `.metaproject.json` at its root and `metaproject` on
  PATH; if either is missing, stop and tell the operator to run `metaproject new .`
  (agents run only `metaproject new . --dry-run`). The "Session assumption" / SessionStart
  wording and the version check are removed.
- **R-TXT-2** No `sdlc-skills:` string, `/plugin` install instruction, "this plugin"
  wording, or SessionStart reference remains in the bundled skills, the metaproject
  skill, templates, `README.md`, `AGENTS.md`, or `ARCHITECTURE.md`.
- **R-TXT-3** Every reference to a relocated document uses its new name and path
  (`docs/INTENT.md`, `docs/TECH-DESIGN.md`, …): skills
  (inputs, outputs, blank rule, `metaproject backfill docs/<file>` examples, wrapup's
  archive source and reset), the metaproject skill and `references/`, the
  `AGENTS`/`CLAUDE`/`README`/`ARCHITECTURE` templates, and this repo's `README.md`,
  `AGENTS.md`, `CLAUDE.md`, `ARCHITECTURE.md`. "At the repo root" wording for those
  documents is gone.
- **R-TXT-4** `ARCHITECTURE.md`'s invariant "the cycle lives in the sdlc-skills plugin"
  is replaced by "the cycle skills ship in the metaproject wheel and are copied into each
  project by `new`/`backfill`". `README.md` documents the project-local skill story,
  bare names, the in-skill precondition, and `doctor` migration.

#### This repo (R-SELF)

- **R-SELF-1** This repo's cycle docs and `ARCHITECTURE.md` live in `docs/` at the end
  of the cycle (moved with `git mv`), and the repo has the declared skills in
  `.agents/skills/`. The current cycle's documents move as part of the implementation, and
  the remaining SDLC stages read them from `docs/`.

#### Retirement (R-RET)

- **R-RET-1** `README.md` (or a release note) lists the operator steps, in order:
  install the new release; uninstall the `sdlc-skills` plugin and remove its directory
  marketplace; run `metaproject doctor`; add a README pointer ("absorbed into metaproject
  ≥ <version>") to `~/Projects/SDLC-skills` and leave it read-only on disk.
- **R-RET-2** The SDLC-skills backlog doc `wrapup-delete-cycle-branch.md` is copied into
  this repo's `docs/backlog/` so it isn't lost with the retired repo.

### Non-functional

- **R-NFR-1** `make format && make lint && make test` pass and the wheel builds; existing
  tests are updated for the new paths rather than deleted.
- **R-NFR-2** `new` and `backfill` remain create-only and agent-safe; every
  `doctor` write stays behind a confirmation.
- **R-NFR-3** No data loss: no move overwrites a file; a migration interrupted part-way
  can be re-run and completes the rest (idempotent).
- **R-NFR-4** Existing design invariants hold, in particular: working deliverables are
  never updatable; a template missing from the live store is an error, never a silent
  fallback to the bundled copy; store walks skip junk files and `.git`.
- **R-NFR-6** Name detection and renames are correct on case-insensitive filesystems
  (macOS APFS default): existence checks for old vs new names compare actual directory
  entries, not `Path.exists()`, and a case-only rename goes through an intermediate name.
- **R-NFR-5** Version bump by `bump_version.sh` heuristics (expected minor).

## Acceptance criteria

1. The built wheel contains all 8 SDLC SKILL.md files and the metaproject skill;
   `git log` in this repo reaches at least one commit authored in SDLC-skills.
   (R-IMP-1..4)
2. The tree contains no `sdlc-skills-import/` prefix, `.claude-plugin/`, or
   `check-metaproject.sh`. (R-IMP-3)
3. `metaproject new demo` in a temp directory produces `demo/.agents/skills/<name>/SKILL.md`
   for all 9 skills, reachable via `demo/.claude/skills/<name>/SKILL.md`, and
   `demo/docs/{INTENT,SPEC,TECH-DESIGN,PLAN,STATE,ARCHITECTURE}.md`; the root has no
   cycle docs and no lowercase cycle-doc names exist anywhere.
   `--dry-run` writes nothing. (R-SKL-2, R-DOC-0..3)
4. Running `backfill` twice on a project with one skill directory deleted recreates only
   that directory the first time; the second run writes nothing. An edited skill is
   reported stale and left byte-identical. (R-SKL-3, R-SKL-4)
5. With `.claude/skills` as a real directory, `new .`/`backfill` write no skill and print
   the notice; other deliverables are still created. (R-SKL-5)
6. `metaproject init` in a temp HOME creates no `~/.claude` entry; `init --no-skill` is
   rejected as an unknown option. (R-INI-1, R-INI-2)
7. `backfill intent.md`, `backfill INTENT.md`, and `backfill docs/INTENT.md` each create
   `docs/INTENT.md` only; `backfill design.md` creates `docs/TECH-DESIGN.md`.
   (R-DOC-4)
8. `review` on a project with root `intent.md` reports it as legacy-location, not
   missing, and does not offer Deploy for it. (R-DOC-5)
9. `doctor --dry-run` on a fixture with: a legacy store layout, old `learn.targets`, a
   project with root cycle docs, a project missing skills, and
   `~/.claude/skills/metaproject/` reports every finding and writes nothing. Confirming
   each fix migrates the store (one commit in the store repo), rewrites targets, moves the
   docs (history preserved via `git mv` in a git project), installs missing skills
   (a stale skill is reported and left byte-identical), and removes the orphaned global
   skill. A second run finds nothing. (R-DRX-1..7, R-NFR-3)
10. A doctor docs migration where `docs/INTENT.md` already exists leaves both files in
    place and reports the conflict. (R-DRX-3, R-NFR-3)
11. Tests assert every bundled SKILL.md has frontmatter `name` equal to its directory
    and a `description`, contains the precondition preamble, and contains no
    `sdlc-skills:` / SessionStart / root-location reference to a relocated document.
    (R-SKL-7, R-TXT-1..3)
12. `learn` scans ignore `.agents/skills/`, and `review` output never mentions skill files.
    (R-SKL-8)
13. This repo has `docs/INTENT.md`, `docs/SPEC.md`, `docs/TECH-DESIGN.md`, `docs/PLAN.md`,
    `docs/STATE.md`, `docs/ARCHITECTURE.md`, no root copies, and
    `.agents/skills/` holds the 9 skills. (R-SELF-1)
14. The quality gate passes. (R-NFR-1)

## Flagged concerns

All resolved by the product owner, 2026-09-28:

- **FC-1 Package-data name.** Resolved: skills are bundled in
  `src/metaproject/sdlc_skills/` to avoid colliding with `metaproject/skills.py` (R-IMP-2).
- **FC-2 Mid-cycle self-migration.** Resolved: spec, design, and plan are completed at
  the root; moving this repo's documents to `docs/` (with the renames) is the
  implementation's first step, and later stages run from `docs/` (R-SELF-1).
- **FC-3 Learn ledger continuity.** Resolved: existing proposals and evidence in
  `universe.db` keyed by old paths are left as they are; no rewrite.
- **FC-4 Stale project skills.** Resolved: `doctor` reports stale project skills only; it
  installs missing ones on confirmation but never overwrites (R-DRX-4).
- **FC-5 doctor scope.** Resolved: project-level checks cover only `universe`-cataloged
  projects; expected for v1.
- **FC-6 Intent amendment.** Resolved: intent.md amended to record the renames and
  re-approved.
- **FC-7 Archives keep old names.** Resolved: existing `docs/archive/<cycle>/` folders keep
  their lowercase names; only new archives use the new names.

## Open questions

None beyond the flagged concerns.
