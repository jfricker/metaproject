# Move metaproject's documents from docs/ to .metaproject/docs/

**Author**: John Fricker.
**Last updated**: 2026-11-21.
**Status**: Complete.
**Approved by**: John Fricker (2026-11-21).
**Origin**: [jfricker/metaproject#26](https://github.com/jfricker/metaproject/issues/26)

## Problem

metaproject writes everything it owns into the project's `docs/` directory: the cycle
documents, the long-lived knowledge documents, `TODO.md`, `HANDOFF.md`, `archive/`,
`backlog/` and `discovery/`. `docs/` is a conventional name that other tools and the
project itself already claim:

- **Doc-site generators** (MkDocs, Docusaurus, Sphinx, Astro and others) own `docs/`.
  They publish or fail to build on cycle documents they were never meant to see.
- **Projects with their own documentation** in `docs/` get metaproject's files mixed into
  it. That makes `docs/` hard to read and makes it unclear which files a project owns.

This affects every operator who adopts metaproject in an existing repository, and every
new project that later adds a doc site.

## Proposed outcome

- Every file and directory metaproject owns lives under `.metaproject/docs/`, and
  metaproject never writes to `docs/`.
- `new`, `backfill`, `adopt`, `review`, `learn`, `universe`, `doctor` and every bundled
  skill and hook use the new location.
- An existing project still on `docs/` keeps working. `review` reports it `OUTOFDATE`
  (legacy location), and `metaproject doctor` moves it behind a confirmation with
  `git mv`, so history is kept.
- This repository is migrated as part of the cycle.

## Affected users and systems

- **Operators**: everyone with metaproject-managed projects. Each project needs one
  `doctor` run.
- **Code**: `deliverables.py` (the single declaration of paths), `scaffold.py`,
  `review.py`/`review_tui.py`, `doctor.py`, `universe.py` (the `docs/INTENT.md` root
  marker), `learn/` (default targets), `template_source.py`, `cli.py` help text. In all,
  about 650 `docs/` references across 29 source and test files.
- **Template store**: `docs.template/` in the bundled templates and in every operator's
  `~/.metaproject/templates/`.
- **Skills**: the 11 SDLC skills and the metaproject skill (about 275 `docs/`
  references), plus the repository's own installed copies in `.agents/skills/`.
- **Hooks**: `metaproject_hook.py` and `metaproject-session.sh`, which carry their own
  stdlib copy of the path logic.
- **Governance templates**: `AGENTS.template.md`'s Process section names `docs/`.

## Scope

### In Scope (v1)

- Move all metaproject-owned documents and directories (cycle, long-lived, on-demand,
  `archive/`, `backlog/`, `discovery/`) to `.metaproject/docs/`, keeping their names.
- Update `deliverables.py`, and every consumer of it, to the new paths.
- Treat `docs/<NAME>.md` as a legacy location for each relocated deliverable, alongside
  the existing root-level and lowercase legacy names. `review` reports it as legacy,
  never as missing, so Deploy cannot create a blank copy beside the real one.
- A `doctor` migration that moves `docs/` documents (and the older root-level ones)
  straight to `.metaproject/docs/` with `git mv`, behind a confirmation, leaving
  `docs/` in place if anything else is in it.
- Update the bundled template store layout, and have `doctor` migrate an operator's
  local store.
- Update all bundled skills, hooks, the governance templates and the README, then
  regenerate `skill_history.json`.
- Migrate this repository.

### Out of Scope (v1)

- A configurable document directory (a `docs_dir` setting).
- Moving `.metaproject.json` into `.metaproject/`.
- Moving `.agents/skills/` or `.claude/` content.
- Any change to what the documents contain.

## Resolved decisions

- **Location is `.metaproject/docs/`, fixed.** Nesting under `.metaproject/` leaves room
  for other per-project metaproject state later. A setting would multiply code paths and
  force every skill to read it. Checked: `universe` does not use a `.metaproject`
  directory as a project marker, so the name is free.
- **Everything metaproject owns moves**, including `ARCHITECTURE.md` and the other
  long-lived documents. `docs/` is left entirely to the project.
- **Migration reuses the 2026-09-29 relocation machinery**: `LEGACY_NAMES`,
  `exact_exists`, `ReviewResult.legacy` and `OUTOFDATE`, and the doctor docs migration.
  No hard cut.
- **Both collision kinds count**: doc-site generators and a project's own documentation.
- **Minor version bump**, not 1.0.0. Old layouts keep working until `doctor` migrates
  them, so nothing breaks on upgrade.
- **Old carried-forward items discarded** (from the 2026-09-29 cycle; operator decision
  2026-11-21).

## Constraints

- **Hidden directory.** `rg` and `fd` skip dot-directories by default, and so may other
  agents' file searches. Skills and documentation that tell an agent to search the
  documents must say so, or pass `--hidden`.
- The design invariants from the 2026-09-29 relocation still hold. Every presence check
  goes through `deliverables.exact_exists`, because APFS is case-insensitive. A document
  at a legacy location is never reported as missing.
- The hook scripts stay stdlib-only and carry their own copy of the path walk.
- Merge and never overwrite: the migration never replaces a file that already exists at
  the destination. It stops and reports instead.
- The quality gate (`make format && make lint && make test`) is green before any commit.

## Open questions

- **Template store layout** (deferred to `generate-design`). Does `docs.template/` become `.metaproject/docs.template/`,
  or keep its name and map to the new destination? This is a design question for
  `generate-design`, recorded here so it is not lost.
