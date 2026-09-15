# metaproject doctor — Implementation Plan

**Author**: John Fricker.
**Derived from**: spec.md, design.md (2026-09-15).
**Last updated**: 2026-09-15.
**Status**: Approved.
**Approved by**: John Fricker (2026-09-15, via plan-mode approval).

## Steps

1. **`src/metaproject/skills.py` — add `prune_extra` to `install_skill`.**
   Signature `install_skill(target_dir=None, force=False, prune_extra=False)`; after
   copying bundled files, when `prune_extra`, walk destination files (junk-filtered
   via `templates.is_junk_file_name`) and delete any not in the bundle; add
   `"pruned": [paths]` to the result dict. Default `False` keeps `init` identical.
   Extend `tests/test_skills.py`: prune removes an extra file when enabled, leaves it
   by default.
2. **`src/metaproject/doctor.py` — new module (all check/fix logic).**
   `CheckResult` dataclass (`name`, `healthy`, `findings`, `fix_summary`,
   `fixed: bool | None`). Pure diagnostics per check:
   - templates: missing = junk-filtered bundle rel-paths minus live-store rel-paths
     (`templates.get_bundled_templates_dir()` vs `cfg.templates_dir`); store-only
     extras reported informationally, never touched.
   - config: `deliverables.learn_targets()` − `cfg.learn.targets`.
   - skill: `not skills.is_skill_current(bundled, get_skill_install_dir())` or
     extras under the install dir.
   - identity: `db.query_projects(db.get_db(cfg.universe_db))` rows where
     `identity.read_identity(Path(row["path"]))` is None; skip rows whose dir is gone.
   `run_checks(cfg, config_file, dry_run, confirm=questionary.confirm)` — fixed order
   templates → config → skill → identity; per-check confirm; declining never blocks
   later checks. Fixes: `seed_templates(store, force=False)`; append missing core
   targets + `save_config`; `install_skill(force=True, prune_extra=True)`;
   `write_identity(...)` per project with `fallback_identity`-derived title/description,
   `author=cfg.author`, created=today, `metaproject_version=__version__` (mirrors
   `scaffold.py`).
3. **`src/metaproject/cli.py` — thin `doctor` command.**
   `@app.command(name="doctor")` with `--dry-run`. Missing `config.json` → error panel
   pointing at `metaproject init`, exit 1. Agent-session guard on the interactive path
   only, modeled on `refuse_scan_in_agent_session`: panel + `metaproject doctor
   --dry-run` handoff + `session.override_hint(marker)`, exit 1. Dry-run always runs.
   Rich results table; exit 0 iff every check healthy at end of run (R-DR-1).
4. **`tests/test_doctor.py`** — acceptance criteria 1–7: template restore
   (dry-run no-write, confirmed restore, extra file survives, exit 1→0); additive
   config migration preserving pins/order; skill refresh+prune; identity backfill
   (never overwrites existing); healthy env → exit 0 with no prompts; agent-session
   refusal + dry-run allowed; exit-code contract. Conftest autouse fixtures already
   isolate `METAPROJECT_CONFIG_DIR` / `METAPROJECT_SKILL_DIR` and pin
   `METAPROJECT_AGENT=0`.
5. **`README.md` — "Upgrading" section** after Installation & Development:
   `uv tool install -U .` (or PyPI), then `metaproject doctor` (try `--dry-run`
   first); one line per check.
6. **Gate** — `make lint`; `make test` unsandboxed with
   `--basetemp=/private/tmp/mp-gate-doctor` (no `claude` in path, per
   docs/VERIFIED-FACTS.md). STATE.md updated as steps land.

## Files touched

- `src/metaproject/skills.py` (modify: `prune_extra` param)
- `src/metaproject/doctor.py` (new)
- `src/metaproject/cli.py` (modify: `doctor` command + imports)
- `tests/test_skills.py` (modify: prune tests)
- `tests/test_doctor.py` (new)
- `README.md` (modify: Upgrading section)

## Sequencing

1 → 2 → 3 (doctor.py depends on `prune_extra`; cli.py depends on doctor.py) → 4
(tests against the finished command) → 5 → 6. Each step lands as its own commit
with STATE.md progress noted.

## Risks / rollback

- Skill prune deletes files under the global skill dir — opt-in param, behind
  doctor's per-check confirmation, dry-run visible. Rollback: revert commit; no
  data-model changes anywhere.
- Identity fix writes into other projects — bounded to cataloged projects with an
  absent `.metaproject.json`, one confirmation listing every path first.
- All changes additive; `init` semantics unchanged (prune defaults off).

## Verification plan

1. `make lint && make test` (unsandboxed, `--basetemp=/private/tmp/mp-gate-doctor`).
2. Manual smoke on this machine: `metaproject doctor --dry-run` (store freshly
   refreshed via `init --force`, so expect templates/skill healthy, config possibly
   missing targets, identity findings on older projects) — proves real wiring with
   zero writes.
