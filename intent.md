# Absorb sdlc-skills into metaproject; move cycle docs to docs/

**Author**: John Fricker.
**Last updated**: 2026-09-28.
**Status**: Approved.
**Approved by**: John Fricker (2026-09-28).

## Problem

The SDLC cycle is split across two repos. metaproject owns the templates and CLI; the
sdlc-skills plugin (`~/Projects/SDLC-skills`, local-only, registered as a `directory`
marketplace) owns the 8 cycle skills (`backlog-new`, `write-intent`, `generate-spec`,
`generate-design`, `generate-plan`, `implement-plan`, `execute-tests`, `wrapup`). They are
coupled one-way by a version-gated SessionStart hook (metaproject ≥ 0.7.0 +
`.metaproject.json`). Two repos, two version schemes, two doc sets for one product, and a
new project gets the templates from `metaproject new` but the skills only if the operator
separately installs the plugin.

Separately, every metaproject-managed project's root is cluttered with the cycle's working
documents (`intent.md`, `spec.md`, `design.md`, `plan.md`, `STATE.md`, `HANDOFF.md`,
`ARCHITECTURE.md`) alongside the governance files, while the rest of the long-lived docs
(`DESIGN-INVARIANTS.md`, `VERIFIED-FACTS.md`, `archive/`, `backlog/`) already live in
`docs/`.

Source: `docs/backlog/sdlc-skills-merge-with-metaproject.md` (2026-09-15). This intent
keeps that note's locked decisions except where overridden below — chiefly, skills are
installed per project by `new`, not globally by `init`.

## Proposed outcome

- The 8 SDLC skills live in the metaproject repo and ship in the metaproject wheel; the
  sdlc-skills repo and plugin are retired.
- `metaproject new` copies the SDLC skills and the metaproject skill into the new
  project's `.agents/skills/` (reachable through the existing `.claude/skills` symlink),
  so a freshly scaffolded project has the whole cycle available with no plugin install.
  `metaproject backfill` adds any that are missing to an existing project, create-only.
- `metaproject init` no longer installs any skill into `~/.claude/skills/`; its focus is
  the operator's metaproject environment (config and template store).
- Cycle documents — `intent.md`, `spec.md`, `design.md`, `plan.md`, `STATE.md`,
  `HANDOFF.md`, and `ARCHITECTURE.md` — are scaffolded, reviewed, learned from, and
  referenced at `docs/<file>`. Only `AGENTS.md`, `CLAUDE.md`, `README.md`, and
  `.gitignore` remain at the project root.
- Every reference to the old root locations is updated: skills, the metaproject skill and
  its references, templates (including `AGENTS.md`/`CLAUDE.md` templates), `README.md`,
  `AGENTS.md`, `ARCHITECTURE.md`, and code that names these paths (`deliverables.py`,
  `review`, `learn`, `identity`, `universe` markers, etc.).
- `metaproject doctor` detects a project with root-level cycle docs and, with
  confirmation, migrates them into `docs/` (preserving git history via `git mv` where the
  project is a git repo). `doctor` also reports missing or out-of-date project skills.
- This repo is itself migrated to the new layout.

## Affected users and systems

- Operator (John Fricker) and every metaproject-managed project on this machine.
- Agents running the SDLC skills (skill text, invocation names, precondition checks).
- `src/metaproject/`: `deliverables.py`, `scaffold.py`, `skills.py`, `cli.py` (`init`,
  `new`, `backfill`), `doctor.py`, `review.py`, `learn/`, `identity.py`, `universe.py`,
  bundled `templates/` and `skill/`; new bundled SDLC skills directory; `pyproject.toml`
  package data.
- The central template store `~/.metaproject/templates/` (layout for cycle templates).
- `~/Projects/SDLC-skills` repo and the Claude Code plugin/marketplace registration.
- Docs: `README.md`, `AGENTS.md`, `ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`,
  `docs/VERIFIED-FACTS.md`.

## Scope

### In Scope (v1)

- Import the 8 skills with history (`git subtree add` into a staging prefix, curate into
  the package, delete the staging prefix and all plugin/hook/marketplace files).
- Bundle the skills as package data; `new` and `backfill` copy them into
  `.agents/skills/<name>/` using the existing CURRENT / INSTALLED / UPDATED / STALE
  semantics (never silently clobber operator edits).
- Remove skill installation from `init` (and its `--no-skill` flag / skill parts of
  `--force`); rework `doctor`'s global-skill check into a per-project skill check.
- Replace the SessionStart hook with an in-skill precondition preamble
  (`.metaproject.json` at root, `metaproject` on PATH; otherwise stop and tell the
  operator to run `metaproject new .`). Version check dropped — skills and CLI are
  co-versioned.
- Relocate cycle documents and `ARCHITECTURE.md` to `docs/` in deliverables, templates,
  scaffolding, review, learn, and all skill/documentation references. `wrapup` archives
  from and resets into `docs/`.
- `doctor` migration of root-level cycle docs into `docs/`, confirmed per project,
  refusing to overwrite an existing `docs/<file>`.
- Tests for bundling, frontmatter/precondition, no stale `sdlc-skills:` strings,
  project-local install idempotency, the new doc paths, and the `doctor` migration.
- Migrate this repo's own cycle docs to `docs/`.
- Retirement steps for the plugin and the SDLC-skills repo, documented for the operator.

### Out of Scope (v1)

- Cycle-per-worktree / concurrent cycles (`docs/backlog/branch-when-write-intent.md`).
- `wrapup` deleting cycle branches (SDLC-skills backlog `wrapup-delete-cycle-branch.md`)
  — may be carried over as a backlog doc, not implemented.
- Automatic bulk migration of every project in the universe; migration is per project via
  `doctor`.
- Keeping a global `~/.claude/skills/` install as an option.
- Any change to the doc templates' content beyond path references.

## Resolved decisions

- **Absorption**: full — single source of truth, co-versioning, fewer repos (from backlog).
- **History**: preserved via `git subtree add` to a staging prefix, then curated (backlog
  approach A).
- **Skill distribution**: project-local only, written by `new` / `backfill` into
  `.agents/skills/`. No plugin, no marketplace, no global install.
- **`init`**: stops installing skills — including the metaproject skill — so it focuses
  on the operator's metaproject environment.
- **Session gate**: in-skill precondition only; the SessionStart hook is removed.
- **Docs location**: cycle docs + `HANDOFF.md` + `ARCHITECTURE.md` move to `docs/`;
  `AGENTS.md`, `CLAUDE.md`, `README.md`, `.gitignore` stay at root. `docs/archive/`,
  `docs/backlog/`, `DESIGN-INVARIANTS.md`, `VERIFIED-FACTS.md` stay where they are.
- **Migration**: explicit, via `metaproject doctor`, confirmed per project.
- **Retirement order** (from backlog): uninstall the plugin and remove its directory
  marketplace *before* archiving `~/Projects/SDLC-skills`; leave the old repo on disk,
  read-only, with a README pointer to metaproject.
- **Skill names**: bare (`/write-intent`, etc.). A `metaproject:` namespace would require
  a plugin; deferred.
- **Skill drift**: `review` does not treat project skills as deliverables; `doctor`'s
  per-project check is enough for v1. `learn` never learns from project skills.
- **Skill target**: skills are written into `.agents/skills/`; a project whose
  `.claude/skills` is a real directory (not the symlink) is skipped with a notice.
- **Template store layout**: cycle templates (and `ARCHITECTURE`) move under
  `docs.template/` in both the bundled and central store, mirroring output paths;
  `doctor` migrates an existing `~/.metaproject/templates/` to that layout.
- **Orphaned global skill**: `doctor` offers to remove `~/.claude/skills/metaproject/`
  left by earlier `init` runs.
- **Version control**: copied skills are committed in each project, like other
  scaffolded files (default accepted at approval).

## Constraints

- Python 3.11+, Typer, Rich; skills ship as package data via `importlib.resources`
  (hatchling `package-data`).
- Gate: `make format && make lint && make test` green before any commit; wheel builds.
- `new`/`backfill` remain create-only and agent-safe; `doctor` fixes are confirmed.
- Existing projects must not break silently: until migrated, `review`/`doctor` must say
  clearly that docs are at the old location rather than report them all missing.
- Version bump per `bump_version.sh` heuristics (new files → minor under major-0).
- Sandbox quirks: tests may need `--basetemp` under `/private/tmp`; `git subtree` uses a
  local-path remote (no network).

## Open questions

None — all resolved above.
