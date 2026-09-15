# metaproject doctor — environment health check and repair

**Author**: John Fricker.
**Last updated**: 2026-09-15.
**Status**: Approved.
**Approved by**: John Fricker (2026-09-15).

## Problem

Everything metaproject installs on a machine outside the package — the live template
store at `~/.metaproject/templates`, `~/.metaproject/config.json` (which pins
`learn.targets`), the Claude Code skill at `~/.claude/skills/metaproject/`, the
`universe.db` catalog, and per-project `.metaproject.json` anchors — goes stale when the
package is upgraded. Today the only repair is a manual `metaproject init --force` plus
hand-editing config, which is undocumented, all-or-nothing, and easy to forget. This
bit us directly on 2026-09-15: after installing 0.7.0 over 0.6.1, the sdlc-skills
SessionStart guard failed and templates stayed stale until someone remembered the
manual incantation.

Carried forward from the
[template-source-of-truth](docs/archive/2026-09-15-template-source-of-truth/) cycle
(FC-3 + spec R-LRN-3 + R-DOC-1).

## Proposed outcome

`metaproject doctor` diagnoses the local environment against the installed package and
repairs what's stale, behind per-fix confirmations:

- After any upgrade, running `doctor` brings the environment back to healthy —
  templates, config, skill, and project anchors all consistent with the
  installed version — without a manual `init --force`.
- Every fix is offered individually with the codebase's dual-confirm pattern; nothing
  is overwritten without an explicit yes (`--dry-run` previews findings and proposed
  fixes with no prompts, matching the f998269 dry-run convention).
- A clean run exits 0 and says so; findings are reported per check.

## Affected users and systems

- **Users**: metaproject CLI users on this machine (John today); indirectly every
  sdlc-skills session, whose SessionStart guard depends on a current install.
- **Systems**: the CLI (`metaproject doctor` command), the template-store seeding and
  skill-install paths currently owned by `init`, config load/migration, `universe`
  indexing, and per-project identity (`.metaproject.json`) backfill.

## Scope

### In Scope (v1)

- One `metaproject doctor` command with `--dry-run`.
- Four checks, each diagnose → confirmed fix:
  1. **Template store refresh** — live store at `~/.metaproject/templates` vs the
     bundled package templates (the manual `init --force` today).
  2. **Config migration** — `learn.targets` pinned in `config.json` miss newly added
     working deliverables; migrate additively (append new targets, keep user pins).
  3. **Skill refresh** — installed skill at `~/.claude/skills/metaproject/` vs the
     current package's skill files.
  4. **Project identity** — cataloged projects missing a `.metaproject.json` anchor;
     offer backfill.
- Tests for each check's diagnose and fix paths, plus dry-run behavior.
- README documentation of the upgrade workflow (`uv tool install -U` → `doctor`).

### Out of Scope (v1)

- Per-template *content* drift between live store and bundle beyond the staleness
  signal v1 uses (deferred; see Open questions).
- Auto-fix / non-interactive `--fix` mode for CI (dry-run output is enough for now).
- Anything multi-machine or remote.
- **Universe staleness check** — deferred (operator decision, 2026-09-15): no changes
  to `universe.py`/`universe.db` in this cycle; `metaproject init` remains the manual
  reindex path.
- Changes to what `init` itself does at first install.

## Resolved decisions

- **Diagnose + confirmed fix**, not diagnose-only or auto-fix — matches the
  dual-confirm, preserve-existing-files pattern the codebase already uses for `new`,
  `backfill`, and `learn`.
- **One command + `--dry-run`**, not subcommands — smaller surface to document, test,
  and remember.
- **Config migration is additive** — new deliverable targets are appended; existing
  user pins are never removed or reordered.
- **Staleness signal is file-set comparison** — the live template store and installed
  skill are stale iff their file sets (names + presence) differ from the bundled
  package's; per-file content comparison is out of scope for v1.

## Constraints

- Python 3.11+, Typer/Rich/questionary conventions; no new dependencies.
- Reuse the existing seeding/skill-install/indexing code paths (`init`, `universe`)
  rather than forking them, so `doctor` and `init` can't drift apart.
- Fixes must be individually declineable; declining one check must not block the others.

## Open questions

None open — resolved or explicitly deferred:

- ~~Staleness signal~~ — **resolved**: file-set comparison (see Resolved decisions).
- **Deferred to spec**: whether the sdlc-skills SessionStart guard's version-mismatch
  notice should point at `metaproject doctor` as the fix (touches the SDLC-skills repo,
  not this one).
- **Deferred to spec**: universe-staleness detection strategy (mtime/size heuristic vs
  full re-scan comparison).
