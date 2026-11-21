# Move project identity to .metaproject/config.json — Implementation Plan

**Author**: John Fricker.
**Derived from**: SPEC.md, TECH-DESIGN.md (2026-11-21).
**Last updated**: 2026-11-21.
**Status**: Approved.
**Approved by**: John Fricker (2026-11-21, pre-approved in session).

## Steps

1. **Resolver.** `identity.py`: `IDENTITY_FILE`/`LEGACY_IDENTITY_FILE`, `config_path`,
   `has_config`, `legacy_config`, `_is_store_dir`; `find_project_root`, `read_settings`,
   `read_identity`, `write_identity` on top of them. Tests in `tests/test_identity.py`.
2. **Readers and writers.** `hooks.read_hook_config`, `template_source`, `skills`,
   `catalog`, `cli._skills_project`, `scaffold` (new + adopt), `universe` markers,
   `review` (legacy entry + note), `cli.resolve_project` warning. Tests for each
   acceptance criterion 1–5 and 8.
3. **User store rename.** `config.py` constants and resolver; `MetaprojectGroup.invoke`
   warning; `init` writes `settings.json`. Tests in `tests/test_config.py`.
4. **Doctor.** `_pair_state`; store-file, project-config and project-hooks checks wired
   into `run_checks` and `_project_checks`; `fix_config` path resolved at fix time.
   Tests in `tests/test_doctor.py`.
5. **Hook scripts.** `metaproject_hook.py` and `metaproject-session.sh` resolver + guard.
   Tests in `tests/test_hooks*.py`/`tests/test_session_hook.py`.
6. **Fixtures.** Move test fixtures representing current projects to the new path;
   keep explicit legacy fixtures.
7. **Text.** README, AGENTS.md, `AGENTS.template.md`, `skill/`, `sdlc_skills/`;
   `make skill-history`.
8. **Self-migration.** `metaproject doctor .` equivalent for this repo (move the file,
   refresh hook copies), `metaproject skills sync`.

## Files touched

`src/metaproject/{identity,config,cli,scaffold,catalog,universe,skills,hooks,
template_source,review,doctor}.py`, `src/metaproject/hook_scripts/*`,
`src/metaproject/templates/AGENTS.template.md`, `src/metaproject/skill/**`,
`src/metaproject/sdlc_skills/**`, `src/metaproject/skill_history.json`, `README.md`,
`AGENTS.md`, `tests/**`, `.metaproject.json` → `.metaproject/config.json`,
`.claude/hooks/metaproject_hook.py`, `scripts/metaproject-session.sh`, `.agents/skills/**`.

## Sequencing

1 before 2–5 (everything reads through the resolver). 3 before 4 (doctor uses the store
helpers). 6 alongside 2–5 as tests fail. 7 after code. 8 last, once the installed CLI
(editable) has the new code.

## Risks / rollback

- Broad fixture churn — mitigated by the legacy fallback: unmigrated fixtures still pass.
- Single branch `move-identity-to-metaproject-config`; rollback is dropping the branch.
- Hook copies in other projects keep working through the fallback until refreshed.

## Verification plan

Targeted pytest per step, then `make format && make lint && make test`; check SPEC
acceptance criteria 1–11; `metaproject doctor . --dry-run` and `metaproject review` on
this repo after self-migration.
