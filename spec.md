# metaproject doctor — Spec

**Author**: John Fricker.
**Derived from**: intent.md (2026-09-15, "metaproject doctor — environment health check and repair").
**Last updated**: 2026-09-15.
**Status**: Approved.
**Approved by**: John Fricker (2026-09-15).

## Requirements

### Functional

- **R-DR-1 Command surface.** `metaproject doctor [--dry-run]` registered in
  `cli.py` alongside `init`/`new`/`universe`/`review`/`backfill`. It runs four checks in
  a fixed order — template store, config, skill, project identity — prints a
  Rich findings report, and exits 0 iff the environment is healthy at the end of the run
  (no findings, or every finding fixed), 1 otherwise (including dry-run with findings).
- **R-DR-2 Template-store check.** The live store at `~/.metaproject/templates` is
  stale iff any bundle template file (recursive relative paths under
  `src/metaproject/templates/`, junk-filtered via `templates.is_junk_file_name`) is
  missing from the live store. File-set comparison only; content is not compared (v1).
  The fix **adds missing bundle templates** (reusing the `templates.seed_templates`
  path, not a copy). Extra files present in the live store but not in the bundle are
  reported informationally and **never deleted or overwritten** — the store is
  git-backed and user-mutable via `learn apply` (see Flagged concerns, resolved).
- **R-DR-3 Config migration.** `config.json` is stale iff `learn.targets` is missing
  any target in `deliverables.learn_targets()` (the deliverable-derived core of
  `DEFAULT_LEARN_TARGETS`). The fix appends exactly the missing core targets, in
  declaration order; existing user entries are never removed, reordered, or edited
  (additive migration).
- **R-DR-4 Skill refresh.** The installed skill at `~/.claude/skills/metaproject/` is
  stale iff its file set (relative paths under the skill dir, junk-filtered) differs
  from `src/metaproject/skill/`. The fix reuses `skills.install_skill(force=True)`.
  Missing and extra files both count (this directory is package-owned, unlike the
  template store).
- **R-DR-5 Project identity check.** A cataloged project (rows in `universe.db`) is
  stale iff `identity.read_identity(<project_dir>)` returns None (no
  `.metaproject.json`). The fix offers backfill via `identity.write_identity` using the
  same fallback derivation (`identity.fallback_identity`) the scaffold path uses. One
  confirmation covers the check; affected projects are listed before confirming.
- **R-DR-6 Universe staleness — deferred (operator decision, 2026-09-15).** No
  universe check, fix, or `universe.py`/`db.py` change in this cycle. If revisited
  later, the leading candidate is a full re-scan comparison via
  `universe.scan_universe` (single fast pass at workspace scale) rather than an
  mtime heuristic; `metaproject init` remains the manual reindex path meanwhile.
- **R-DR-7 Dry-run.** `--dry-run` prints each check's findings and the fix it would
  apply, prompts nothing, writes nothing (no store, config, skill, project, or db
  changes). Dry-run is permitted inside agent sessions.
- **R-DR-8 Confirmation and agent-session policy.** In an interactive run, each check
  with findings gets its own `questionary.confirm` prompt (dual-confirm pattern);
  declining one fix never blocks the remaining checks. In an agent session
  (`session.is_agent_session`), the interactive fix path refuses with the existing
  override hint convention (same guard as `learn scan`); only `--dry-run` runs there.
- **R-DR-9 Documentation.** README gains an "Upgrading" section: upgrade the package
  (`uv tool install -U ...`), then run `metaproject doctor` (or `doctor --dry-run`
  first) to bring the environment current.

### Non-functional

- **R-DR-10 No new dependencies**; Python 3.11+; Typer/Rich/questionary idioms matching
  the existing commands.
- **R-DR-11 Reuse, don't fork.** All fixes call the existing code paths
  (`templates.seed_templates`, `skills.install_skill`, `universe.scan_universe`,
  `identity.write_identity`, config load/save) so `doctor` and `init` cannot drift
  apart. No parallel implementations of seeding, installing, or indexing.
- **R-DR-12 Tests.** Each check has diagnose-path and fix-path tests, plus: dry-run
  writes nothing; config migration is additive (pins preserved); live-store extras are
  never deleted; agent-session refusal; exit codes. Suite stays green under the
  existing make gate.

## Acceptance criteria

1. With a template deleted from `~/.metaproject/templates`: `doctor --dry-run` reports
   the missing file and changes nothing; `doctor` (confirmed) restores it; exit code is
   1 then 0. An extra file placed in the store is reported but still present after a
   fixing run.
2. With a `config.json` whose `learn.targets` predates a newly declared working
   deliverable: `doctor` appends the missing target and leaves pre-existing
   user-added entries (`docs/`, `Makefile`, `pyproject.toml`, or custom) intact and in
   order.
3. With a stale skill directory (file added or removed under
   `~/.claude/skills/metaproject/`): `doctor` restores the packaged file set via the
   existing installer.
4. With a cataloged project whose `.metaproject.json` was deleted: `doctor` lists it,
   and on confirmation writes an identity anchored the same way scaffold does.
5. On a fully current environment: `doctor` reports all checks healthy and exits 0
   with no prompts.
6. Inside an agent session: `doctor` (interactive) refuses with the override hint;
   `doctor --dry-run` still reports findings.
7. `make` gate passes (ruff + full pytest) and README documents the upgrade workflow.

## Flagged concerns

- **Resolved — learned templates vs. bundle refresh**: the live template store is
  git-backed and legitimately diverges from the bundle when `learn apply` commits an
  accepted change, so a naive "make live == bundle" fix would destroy learned content.
  Decision (per R-DR-2): doctor only *adds* missing bundle templates; it never deletes
  or overwrites anything already in the store, and extras are informational only.
  Content-level refresh remains out of scope (a deliberate `init --force` still exists
  for that).

## Open questions

None. The SessionStart-guard pointer from intent is **out of scope for this repo** —
the guard lives in the SDLC-skills plugin; pointing its version-mismatch notice at
`metaproject doctor` is a follow-up task there once this ships.
