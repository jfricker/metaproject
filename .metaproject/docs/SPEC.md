# Move project identity to .metaproject/config.json — Spec

**Author**: John Fricker.
**Derived from**: INTENT.md (2026-11-21).
**Last updated**: 2026-11-21.
**Status**: Approved.
**Approved by**: John Fricker (2026-11-21, pre-approved in session).

## Requirements

### Functional

- **R-CFG-1 New path.** The project config path is `.metaproject/config.json`. `new`,
  `backfill` (scaffold-into-existing) and `adopt` write it there, creating
  `.metaproject/` when needed. No command creates `.metaproject.json`.
- **R-CFG-2 One resolver.** Every reader of the project config (identity, settings,
  hook config, `templates.source`, `skills.location`, managed-project test, root walk,
  `skills` guard) resolves the file through `identity`'s resolver: the new path when it
  is a regular file, else the legacy `.metaproject.json` when it is a regular file,
  else the new path (absent).
- **R-CFG-3 Anchor.** `find_project_root` and `universe.is_project_root` treat either
  file as an anchor/marker. A `.metaproject/` directory without `config.json` is not
  one. The walk still stops at the git boundary, inclusive; a corrupt file still
  anchors.
- **R-CFG-4 Store guard.** A `.metaproject/config.json` whose `.metaproject/` directory
  is the user-global store directory (`METAPROJECT_CONFIG_DIR`, default
  `~/.metaproject`) is never a project anchor, in the CLI and in the hook scripts.
- **R-CFG-5 Write in place.** `write_identity` writes to the file the resolver returns
  (an existing legacy file is updated where it is, never silently moved), keeping keys
  it does not own.
- **R-CFG-6 Legacy warning.** When the project a command resolves (via
  `resolve_project`) carries only the legacy file, one stderr line tells the operator to
  run `metaproject doctor <dir>`.
- **R-CFG-7 Doctor project migration.** In both the full run (every managed project) and
  `doctor <PROJECT>`, a "project config" check:
  - legacy only → fix moves `.metaproject.json` to `.metaproject/config.json`
    (`git mv` when tracked; never commits), content byte-identical;
  - both present, identical JSON → fix removes the legacy file;
  - both present, different → report-only conflict naming the differing top-level
    keys; nothing changes.
  Behind doctor's per-check confirmation; agent sessions get the dry-run report.
- **R-CFG-8 Review.** A project carrying `.metaproject.json` reports it in
  `ReviewResult.legacy` as `{".metaproject/config.json": ".metaproject.json"}`, so it is
  `OUTOFDATE` and listed under the legacy section. Identity notes name the new path.
- **R-STORE-1 User store rename.** The user-global config file is
  `<config dir>/settings.json`. `get_config_file_path` returns `settings.json` when it
  exists, else an existing legacy `config.json`, else `settings.json`; `init` writes
  `settings.json`.
- **R-STORE-2 Store warning.** While only the legacy `config.json` exists, every CLI
  invocation prints one stderr line pointing at `metaproject doctor`.
- **R-STORE-3 Doctor store migration.** An environment-wide "config file" check, before
  the `learn.targets` check: legacy only → rename to `settings.json`; both identical →
  remove legacy; both different → report-only conflict. Later checks write to the
  resolved path at fix time.
- **R-HOOK-1 Hook scripts.** The bundled `metaproject_hook.py` and
  `metaproject-session.sh` anchor on and read `.metaproject/config.json`, falling back
  to `.metaproject.json`, applying the R-CFG-4 guard. Both stay stdlib/POSIX-only and
  never fail a session.
- **R-HOOK-2 Doctor hook refresh.** A per-project "project hook scripts" check reports
  an installed copy that does not reference `.metaproject/config.json` (it predates this
  change) and, behind confirmation, replaces it with the bundled copy. Missing scripts
  and copies that already know the new path are not findings.
- **R-DOC-1 Text.** README, AGENTS.md, `AGENTS.template.md`, the bundled `metaproject`
  skill and its references, and all SDLC skills name `.metaproject/config.json` (and
  `~/.metaproject/settings.json`); `skill_history.json` covers the new bundle; this
  repository's own skills are synced.
- **R-SELF-1 Self-migration.** This repository carries `.metaproject/config.json` and no
  `.metaproject.json`, and its installed hook scripts are current.

### Non-functional

- Core dependencies unchanged (`typer`, `rich`, `jinja2`); no optional extra reached
  from a core path.
- No command other than doctor moves or deletes either legacy file.
- Readers never raise on a missing, unreadable or malformed config (unchanged).

## Acceptance criteria

1. `new`/`adopt`/`backfill` on a fresh directory create `.metaproject/config.json` and
   no `.metaproject.json` (tests).
2. A project with only `.metaproject.json` is found by `find_project_root`,
   `catalog.is_managed`, `universe.is_project_root`, `read_identity`, `read_settings`,
   `read_hook_config`, the `templates.source` reader and `skills_location` (tests).
3. With both files, the new file's values win everywhere (test).
4. A bare `.metaproject/` (only `docs/`) is not an anchor (test).
5. `.metaproject/config.json` inside the user store directory is not an anchor, in
   `find_project_root` and in the hook script (tests).
6. `doctor` moves a legacy-only file preserving bytes; removes an identical legacy copy;
   reports a differing pair without changing either (tests, plain dir and git repo).
7. `doctor` renames a legacy user `config.json` to `settings.json`, handling the same
   three cases (tests); `init` writes `settings.json` (test).
8. `review` lists `.metaproject.json` as legacy and the project is not clean (test).
9. Hook script post-edit reads commands from `.metaproject/config.json`, and from the
   legacy file when the new one is absent (tests); doctor replaces a pre-change copy
   (test).
10. `rg -F '.metaproject.json'` in `src/` matches only the legacy constant,
    fallback/migration code and text explicitly describing the legacy file.
11. `make format && make lint && make test` pass.

## Flagged concerns

- **Transition collision (resolved).** Until doctor renames the user store, the legacy
  `~/.metaproject/config.json` would make `$HOME` look like a project. Resolved by the
  R-CFG-4 guard, which costs one path comparison and also protects a custom
  `METAPROJECT_CONFIG_DIR`.
- **Overwriting hook copies (resolved).** R-HOOK-2 replaces an operator-edited copy that
  predates the change; acceptable because it is behind confirmation and the summary says
  it overwrites.

## Open questions

None.
