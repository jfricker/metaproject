# TODO

Standing list of things the operator still has to do or check by hand. Never archived,
never reset; delete or tick entries once done.

## Carry over

Work found during development or discovery that belongs to a later cycle. `wrapup` adds
each open item the operator chose to carry forward; tick it when a cycle picks it up.

<!-- Format:
- [ ] <item> — carried from `.metaproject/docs/archive/YYYY-MM-DD-<slug>/` (YYYY-MM-DD)
-->

- [ ] Release the config move: `make bump-version`, push `main` and the new tag, then reinstall the uv tool so plain `metaproject` is the new version — carried from `.metaproject/docs/archive/2026-11-21-move-project-identity-to-metaproject-config/` (2026-11-21)
- [ ] Doctor's "project identity" fix writes `.metaproject.json` into every cataloged folder without one, including non-projects from a home-wide `universe` scan (`~/.config/opencode`, `~/bin`); make it confirm per project or skip folders without git or `AGENTS.md` — carried from `.metaproject/docs/archive/2026-11-21-move-project-identity-to-metaproject-config/` (2026-11-21)
- [ ] Process note: this cycle's implement-plan ran in the main session instead of the prescribed subagent delegation, and generate-plan skipped plan mode under the operator's pre-approval; decide whether the skills should allow this explicitly — carried from `.metaproject/docs/archive/2026-11-21-move-project-identity-to-metaproject-config/` (2026-11-21)

<!-- Manual verification log: wrapup appends one dated entry per cycle below, newest
last. Format:

## YYYY-MM-DD: Needs manual verification (<cycle slug>)

- [ ] <what could not be verified> (<why: browser, device, CI run, third-party widget>)
  1. <exact step>
  2. <expected result>
-->

## 2026-11-21: Needs manual verification (move-docs-to-metaproject-docs)

- [ ] Release version bump `0.9.1` → `0.10.0` (`R-NFR-6`) and push tag (operator release step on `main`)
  1. From `/Users/johnfricker/Projects/MetaProject` (`main`), run `make bump-version && git push origin main v0.10.0`.
  2. `pyproject.toml`, `src/metaproject/__init__.py`, and `README.md` reflect `0.10.0`, and annotated tag `v0.10.0` exists on `origin`.
- [ ] Upgrade global CLI and migrate live `~/.metaproject/` environment & workspace projects (operator machine state outside repo)
  1. Run `make install-global && metaproject doctor --dry-run` to inspect findings (`docs.template/` → `.metaproject.template/docs.template/`, `config.json` `learn.targets`, and cataloged projects), then run `metaproject doctor` and confirm each fix.
  2. Follow-up `metaproject doctor --dry-run` exits `0` (`healthy`) and `review --no-tui` shows `OUTOFDATE: 0` across migrated projects.
- [ ] Clean up leftover untracked macOS `docs/.DS_Store` (and empty `docs/`) in `/Users/johnfricker/Projects/MetaProject` after fast-forward merge
  1. Check `/Users/johnfricker/Projects/MetaProject`: if `docs/` remains with only `.DS_Store`, run `rm -f docs/.DS_Store && rmdir docs`.
  2. `test ! -e /Users/johnfricker/Projects/MetaProject/docs` exits `0`.
- [ ] Verify GitHub issue #26 is closed once `v0.10.0` is pushed (GitHub remote state)
  1. Check `gh issue view 26` (or GitHub UI) after pushing `main` / `v0.10.0` and close with the `v0.10.0` reference if still open.
  2. Issue #26 status is `CLOSED`.

## 2026-11-21: Needs manual verification (move-project-identity-to-metaproject-config)

- [ ] SessionStart script finds `.metaproject/config.json` in a real Claude Code on the web session (web container; only tested with stubs locally)
  1. Open a web session on a repository whose config is at `.metaproject/config.json` with `scripts/metaproject-session.sh` installed.
  2. The session log shows the CLI installed at the pinned `metaproject_version` and `skills sync` run for that project.
- [ ] Doctor migration in a real tracked repository with old hook copies (only tested in temporary repos)
  1. After installing the release, run `metaproject doctor` in a project that still has `.metaproject.json` and an old `.claude/hooks/metaproject_hook.py`; accept "project config" and "project hook scripts".
  2. `git status` shows `R .metaproject.json -> .metaproject/config.json`, the hook script matches the bundled one, and an edit still triggers `commands.lint`.
