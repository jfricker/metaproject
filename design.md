# metaproject doctor — Design

**Author**: John Fricker.
**Derived from**: spec.md (2026-09-15, "metaproject doctor — Spec").
**Last updated**: 2026-09-15.
**Status**: Approved.
**Approved by**: John Fricker (2026-09-15).

## Affected components

- **New module `src/metaproject/doctor.py`** — all check/fix logic lives here, following
  the existing split (thin Typer commands in `cli.py`, behavior in feature modules like
  `review.py`, `scaffold.py`). Exports:
  - `@dataclass CheckResult`: `name`, `healthy: bool`, `findings: list[str]`,
    `fix_summary: str` (what the fix would do), `fixed: bool | None` (None = not
    attempted: dry-run or declined).
  - `run_checks(cfg: Config, dry_run: bool) -> list[CheckResult]` — runs the four
    checks in spec order (templates, config, skill, identity), prompts per check via
    `questionary.confirm` when interactive, and applies fixes by calling the existing
    owners below. Pure diagnostics are separate from fixes so tests can drive either.
- **`cli.py`** — new `@app.command(name="doctor")` with a single `--dry-run` option.
  Loads config, refuses in agent sessions (unless `--dry-run`) using the established
  `session.agent_marker()`/`override_hint()` pattern, prints a Rich findings table,
  exits 0/1 per R-DR-1. No logic in the command body.
- **`templates.py`** — no change. `seed_templates(store, force=False)` already has
  doctor's exact semantics: it creates missing files/dirs and *skips* existing ones.
  Doctor calls it as-is for R-DR-2's fix; diagnosis is a new helper in `doctor.py`
  that lists bundle-relative paths (junk-filtered via `is_junk_file_name`) missing
  from the live store, plus store-only extras for the informational report.
- **`skills.py`** — one additive change: `install_skill(..., prune_extra: bool = False)`.
  When True, after copying bundled files it deletes files under the destination that
  don't exist in the bundle (junk-filtered). Default False keeps `init`'s behavior
  byte-identical; doctor passes True. Detection reuses `is_skill_current` unchanged.
- **`config.py`** — no change to `LearnConfig`; the additive migration is a
  `doctor.py` helper: expected core = `deliverables.learn_targets()`; missing entries
  appended after the existing list, then `save_config`. (Not folded into `config.py`
  because it's doctor policy, not config semantics.)
- **`identity.py` / `db.py` / `universe.py` / `scaffold.py`** — no changes. The
  identity check reads cataloged non-missing projects via existing
  `db.query_projects(db)` and `identity.read_identity`; the fix calls
  `identity.write_identity` with `Identity(title, description, author, created,
  metaproject_version)` derived exactly as `scaffold.py` does (title/description via
  `fallback_identity`, author from `cfg.author`, created = today).
- **Tests** — new `tests/test_doctor.py` (check/fix/dry-run/agent-session/exit-code)
  plus a small addition to `tests/test_skills.py` for `prune_extra`. Test seams that
  already exist and are reused: `METAPROJECT_SKILL_DIR` env override, tmp dirs for
  the store, and config-file fixtures per `tests/test_config.py` conventions.
- **`README.md`** — "Upgrading" section (R-DR-9).

## Data flow / interfaces

```
metaproject doctor [--dry-run]
        │
        ▼
cli.py: doctor_cmd ── agent-session guard (interactive only; R-DR-8)
        │  load_config(config_file)            # missing config → error, "run init"
        ▼
doctor.run_checks(cfg, dry_run)
        │
        ├─ 1 templates: missing = bundle_paths − store_paths (junk-filtered)
        │     fix  → templates.seed_templates(store, force=False)   [adds only]
        │             extras reported, never touched (R-DR-2)
        ├─ 2 config:   missing = deliverables.learn_targets() − cfg.learn.targets
        │     fix  → append missing, save_config                   [additive]
        ├─ 3 skill:    stale = not is_skill_current(bundled, installed)
        │              or extras present
        │     fix  → skills.install_skill(force=True, prune_extra=True)
        ├─ 4 identity: projects = db.query_projects(db) where read_identity is None
        │     fix  → identity.write_identity(fallback-derived) per project
        ▼
Rich table: check │ healthy │ findings │ fix applied?          exit 0 iff all healthy
```

- Every fix funnels through the module that owns that concern — doctor holds no
  copy of seeding, installing, indexing, or identity logic (R-DR-11).
- `CheckResult` is the only interface `cli.py` consumes, keeping the command testable
  via `run_checks` with monkeypatched prompts.

## Alternatives considered

- **Fixes inside `cli.py`** — rejected: bloats an already 1,700-line command module
  and mirrors the `learn`/`review` precedent of logic-in-module, thin-command.
- **A `doctor/` package (checks as submodules)** — rejected at four checks; a single
  `doctor.py` (~250 lines with tests elsewhere) matches `review.py`-scale modules.
  Revisit if checks grow (e.g. the deferred universe check).
- **Content comparison for the template store** — rejected for v1 per spec R-DR-2
  (the store is `learn`-mutable; content equality would flag legitimate accepted
  drift). File-set only.
- **Detection via a version stamp written at seed time** — rejected (intent decision):
  file-set comparison needs no new persisted state and can't lie after a hand-edit.
- **Skill check strictly file-set** — strengthened deliberately: `is_skill_current`
  (byte compare) already exists, and the skill dir is package-owned, so content drift
  is flagged too. This exceeds R-DR-4's minimum in the safe direction; flagged below
  for sign-off.

## Trade-offs and risks

- **`install_skill(prune_extra=True)` deletes files in `~/.claude/skills/metaproject/`.**
  Risk: an operator's hand-added file there is destroyed. Mitigations: it's
  behind doctor's explicit per-check confirmation (or `--dry-run` visibility), the
  directory is documented package-owned, and pruning is opt-in at the API level so
  `init` never prunes. The asymmetry vs. the template store (prune vs. never-delete)
  is intentional and spec-encoded.
- **Identity backfill writes into other projects' directories** — the only doctor fix
  that reaches outside `~/.metaproject`. Bounded by: only cataloged, non-missing
  projects; only when `.metaproject.json` is absent (never overwrites); one
  confirmation listing every affected path before any write.
- **Agent-session refusal blocks the interactive path entirely** — consistent with
  `learn scan`, and `--dry-run` remains available; `METAPROJECT_AGENT_OVERRIDE=0`
  is the escape hatch.
- **Exit-code contract** (`1` on any finding, even after a declined fix) makes
  scripted use strict; that's the point of R-DR-1, but worth knowing when chaining.
- **No orchestration/locking** — two concurrent `doctor` runs could race on config
  writes. Accepted: single-operator tool today; the additive migration makes the
  realistic race benign.

## Open questions

None — resolved with the operator (2026-09-15):

- **Skill-check strengthening approved as designed**: detection uses
  `is_skill_current` (byte compare) plus extra-file detection, and the fix prunes.
  Rationale: the repo-bundled skill (`src/metaproject/skill`) is developer source;
  installed copies are package-owned — operators and end users install into global or
  project locations rather than editing what's there.
- **Skill check scope is global-only**: doctor checks and refreshes only the global
  install at `~/.claude/skills/metaproject` (respecting `METAPROJECT_SKILL_DIR`),
  which is what `init` writes via `install_skill`. Project-level skill copies
  (`.agents/skills/` / `.claude/skills/` in scaffolded projects) are **out of scope**
  — they refresh when a project re-scaffolds or runs `metaproject backfill`, and
  doctor reaching into every project's skill layout would enlarge the blast radius
  for no operational need.
