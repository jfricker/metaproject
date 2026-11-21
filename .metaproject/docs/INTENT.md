# Move project identity to .metaproject/config.json

**Author**: John Fricker.
**Last updated**: 2026-11-21.
**Status**: Approved.
**Approved by**: John Fricker (2026-11-21).

## Problem

A managed project carries metaproject state in two places: `.metaproject.json` at the
repository root and the `.metaproject/` directory (which already holds `docs/`). The
root file is one more dotfile cluttering every managed repository, and it splits
metaproject's footprint for no reason now that `.metaproject/` exists.

The file is load-bearing: it is the project-root anchor (`identity.find_project_root`,
`resolve_project_dir`), the managed-project test (`catalog.is_managed`), a
`universe` project marker, and the home of `commands`, `skills.location`,
`templates.source` and `metaproject_version`. It is also read directly by the
stdlib hook scripts that are copied create-only into other projects
(`.claude/hooks/metaproject_hook.py`, `scripts/metaproject-session.sh`), and named in
the README, AGENTS template, the bundled metaproject skill and all eleven SDLC
skills' preconditions.

Moving it into `.metaproject/config.json` collides with the user-global store:
`~/.metaproject/config.json` already exists, and outside a git repository the root
walk runs to `/`, so it would treat `$HOME` as a managed project.

## Proposed outcome

- New and adopted projects get `.metaproject/config.json`; no command creates
  `.metaproject.json` any more.
- `.metaproject/config.json` is the project-root anchor, the managed-project test,
  and the `universe` marker. Every reader resolves it through one function in
  `identity.py`.
- An unmigrated project keeps working: when `.metaproject/config.json` is absent,
  `.metaproject.json` is read as a fallback and the command warns to run
  `metaproject doctor`. When both exist the new file wins.
- A `.metaproject/` directory without `config.json` (e.g. only `docs/`) is not a
  marker: only `.metaproject/config.json` or the legacy `.metaproject.json` anchors
  the root and marks a project managed.
- `metaproject doctor` (and `doctor .`) detects a legacy `.metaproject.json` and,
  behind confirmation, moves it to `.metaproject/config.json` preserving every key.
  If both files exist and are identical, it offers to remove the legacy one; if they
  differ, it refuses, shows the differing keys, and changes nothing. Agent sessions
  get the dry-run report only.
- `metaproject review` lists a legacy `.metaproject.json` under the existing
  "Legacy location — run `metaproject doctor`" section and counts it as
  `OUTOFDATE`, exactly as it does legacy document locations.
- The user-global store file `~/.metaproject/config.json` is renamed to
  `~/.metaproject/settings.json`; the old name is read as a fallback with a warning
  and doctor moves it, so a project config and the user config never share a path.
- Newly shipped hook scripts read `.metaproject/config.json`, falling back to
  `.metaproject.json`; doctor offers to refresh installed copies that predate this.
- Docs, templates and skills name the new path. This repository is migrated to it.

## Affected users and systems

- Operators of every managed project (existing repos need a doctor run, but keep
  working until then).
- Agents following the SDLC skills' precondition check.
- Code: `identity.py`, `scaffold.py` (`new`/`backfill`/`adopt`), `catalog.py`,
  `universe.py`, `skills.py`, `hooks.py`, `template_source.py`, `doctor.py`,
  `config.py` (user store), `cli.py`, `hook_scripts/`, bundled skill and SDLC skills,
  `templates/AGENTS.template.md`, README, AGENTS.md, tests.

## Scope

### In Scope (v1)

- New project config path and single resolver with legacy fallback.
- Root walk, catalog, universe marker on the new path (legacy still recognised).
- Doctor migration of the project file; doctor migration of the user store to
  `settings.json`.
- `review` reporting a legacy `.metaproject.json` as a legacy location.
- Hook scripts reading both paths; doctor refresh of stale installed copies.
- Docs, templates, skill text updates; self-migration of this repository.

### Out of Scope (v1)

- Removing the `.metaproject.json` fallback (a later cycle, once projects are migrated).
- Auto-migration by `adopt`, `backfill`, `new`, `review` or any command other than
  `doctor`.
- Changing the contents/schema of the project config.

## Resolved decisions

- **Legacy read**: fallback plus doctor migration, mirroring the root/`docs/` →
  `.metaproject/docs/` relocation.
- **Collision**: rename the user-global store file rather than special-casing the
  walk or choosing a different project filename.
- **Installed hook copies**: new scripts read both paths; doctor offers to refresh
  outdated copies.
- **Migration trigger**: doctor only, behind confirmation; agent sessions dry-run.
- **User store name**: `~/.metaproject/settings.json`.
- **Both files present**: identical → doctor offers to remove the legacy file;
  different → doctor refuses, shows the differing keys, changes nothing.
- **Marker**: `.metaproject/config.json` (or legacy `.metaproject.json`) only; a bare
  `.metaproject/` directory does not count.
- **Review**: reports a legacy `.metaproject.json` as a legacy location (`OUTOFDATE`).

## Constraints

- Core dependencies stay `typer`, `rich`, `jinja2`; hook scripts stay stdlib-only.
- Writers keep keys they do not own (existing `write_identity` invariant).
- Root walk still stops at the git boundary, inclusive.
- A corrupt config still anchors the root (presence, not validity).

## Open questions

None.
