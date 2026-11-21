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
- [x] 1. Resolver in identity.py
- [x] 2. Readers and writers on the resolver; review legacy entry; CLI warning
- [x] 3. User store rename to settings.json
- [x] 4. Doctor store-file, project-config and project-hooks checks
- [x] 5. Hook scripts read both paths with store guard
- [x] 6. Test fixtures on the new path
- [x] 7. Docs, templates and skills text; skill history
- [x] 8. Self-migration of this repository

## Design invariants (regression guards)

<!-- written by implement-plan/execute-tests; appended to .metaproject/docs/DESIGN-INVARIANTS.md by wrapup -->
- Every project-config reader goes through `identity.config_path`/`has_config`: new path first, legacy `.metaproject.json` fallback (`tests/test_identity.py::test_legacy_only_project_is_still_read_and_anchors`, `::test_new_file_wins_over_legacy`).
- A `.metaproject/` dir without `config.json` is never an anchor or universe root (`test_identity.py::test_bare_dot_metaproject_dir_is_not_an_anchor`, `test_config_location.py::test_bare_dot_metaproject_is_not_a_universe_root`).
- The user store dir (`METAPROJECT_CONFIG_DIR`/`~/.metaproject`) is never a project anchor, in the CLI and the hook script (`test_identity.py::test_user_store_dir_is_never_an_anchor`, `test_hooks.py::test_hook_never_anchors_on_the_user_store`).
- `write_identity` updates a legacy file in place; only doctor moves it (`test_identity.py::test_write_identity_updates_a_legacy_file_in_place`, `test_config_location.py::test_adopt_keeps_a_legacy_config_where_it_is`).
- Doctor never touches a differing legacy/new pair; it reports the differing keys (`test_config_location.py::test_doctor_reports_a_differing_pair_and_changes_nothing`, `::test_doctor_store_identical_and_differing_pairs`).
- `review` puts a legacy `.metaproject.json` in `ReviewResult.legacy` (OUTOFDATE) (`test_config_location.py::test_review_reports_the_legacy_config_as_out_of_date`).
- Hook scripts read `.metaproject/config.json`, falling back to the legacy file (`test_hooks.py::test_post_edit_reads_a_legacy_config_when_the_new_one_is_absent`, `test_session_hook.py::test_script_reads_the_pin_from_a_legacy_config`).

## Open items carried into PLAN.md

<!-- written by implement-plan/execute-tests; resolved with the operator by wrapup -->
- Nothing is committed: the commit of the code steps was blocked by the auto-mode permission classifier. All changes (plus the staged `git mv .metaproject.json → .metaproject/config.json`) are uncommitted on branch `move-identity-to-metaproject-config`.
- The operator's own `~/.metaproject/config.json` is still on the legacy name (every command prints the warning); run `metaproject doctor` to rename it to `settings.json`. Other managed projects need `metaproject doctor` to move their `.metaproject.json` and refresh old hook copies.
- Deviation: implement-plan's subagent delegation was not used (steps implemented directly in this session); generate-plan's plan mode was skipped because the operator pre-approved every stage.
- No version bump was done (`make bump-version` is the operator's call at release).

## Verified facts (do not re-investigate)

<!-- written by implement-plan/execute-tests; appended to .metaproject/docs/VERIFIED-FACTS.md by wrapup -->
- The user config file path is resolved in one place, `config.get_config_file_path` (`rg get_config_file_path src`); `doctor`, `init` and `session` all go through it.
- The editable install's metadata had drifted to 0.9.1 while `pyproject.toml` said 0.10.0, failing `test_baseline`/`test_readme`; `make install` fixed it (no code change).
- This repository has no installed hook scripts (`.claude/hooks/` and `scripts/metaproject-session.sh` are absent), so the hook-refresh check has nothing to do here (`metaproject doctor . --dry-run`: all healthy after the move).
- Gate on 2026-11-21: `make lint` clean, `make test` 1115 passed, `make build` built sdist and wheel.
