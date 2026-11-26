# Harness-neutral project skills: one source, per-harness adapters

**Author**: John Fricker.
**Last updated**: 2026-11-26.
**Status**: Approved.
**Approved by**: John Fricker (2026-11-26; first approved 2026-11-25, amended after the spec review).

## Problem

`metaproject new`/`backfill`/`adopt` install the bundled skills into `.agents/skills/` and make
`.claude/skills` a **whole-directory symlink** to it (`scaffold.link_agent_skills`,
`skills.ensure_skills_link`). That works on the author's Mac with Claude Code, but it is the wrong
default for third-party users who run several harnesses (Claude Code, GitHub Copilot, ZCode,
Antigravity/agy, Codex, Gemini CLI, Cursor, OpenCode) and already have their own skills and config.

### Assumptions tested (2026-11-25)

| # | Assumption | Verdict | Evidence |
|---|---|---|---|
| A1 | The `.claude/skills → .agents/skills` directory symlink is bad practice for the public. | **True, for more reasons than stated.** | (a) Claude Code documents symlinks only for *individual* `<skill-name>` entries, not for `.claude/skills` itself. (b) It takes over a directory the user owns: a user with an existing `.claude/skills` gets the link skipped, so Claude Code never sees the metaproject skills; a user who has the link can only add Claude-only skills by writing into the shared `.agents/skills`. (c) It is committed as a git symlink (mode `120000`), which becomes a plain text file on Windows / `core.symlinks=false` checkouts, so the skills disappear silently. (d) ~~Harnesses that read both locations list every skill twice~~ — **disproved for Copilot**, see A7. |
| A2 | Each harness needs its own skills location, so a source of truth has to be fanned out to all of them. | **Mostly false.** `.agents/skills/` is now the cross-harness project location. Claude Code is the only listed harness that does not read it. | `.agents/skills` read by: Copilot (with `.github/skills`, `.claude/skills`), Codex, Antigravity (its default; `.agent/skills` is legacy), ZCode 4.0 (with `.zcode/skills`, cwd up to repo root; *not* `.claude/skills` — per its bundled `zcode-configuration-guide` skill), Gemini CLI (documented alias of `.gemini/skills`), Cursor (documented, with `.cursor/skills`; also reads `.claude/skills`; forum reports of gaps in the agent CLI). Claude Code reads only `.claude/skills` (project, parents up to repo root, nested, `--add-dir`), `~/.claude/skills`, plugins; [anthropics/claude-code#31005](https://github.com/anthropics/claude-code/issues/31005) is still open (dupes closed into it as late as 2026-11-20). |
| A3 | Per-skill symlinks are a workable option. | **True for Claude Code; still a symlink.** | Claude Code docs: a `<skill-name>` entry "can be a symlink to a directory elsewhere" and is loaded once even if several locations point at it. Codex documents following symlinked skill folders. Leaves the user's other `.claude/skills/*` entries alone. Same Windows caveat as A1(c); same duplicate-listing caveat as A1(d). |
| A4 | Installing copies per configuration pattern, with metaproject owning the source, is workable. | **True, and metaproject already has the machinery.** | The install manifest (`.agents/skills/.metaproject-skills.json`) + `skill_history.json` already tell a pristine copy from a user edit, so a copy can be re-synced safely. Cost: duplicated files in the repo and the same duplicate-listing caveat. |
| A5 | Installing at user level is workable. | **False as the primary mechanism.** | The SDLC skills are per-project and versioned with the project (pinned CLI, `skills sync`, cloud sessions clone the repo and see only committed files). User-level paths differ per harness (`~/.claude/skills`, `~/.agents/skills`, `~/.copilot/skills`, `~/.gemini/config/skills`, `~/.zcode/skills`) and in Claude Code a personal skill **overrides** a project skill of the same name, so a user-level copy would shadow a project's own edits and leak into unrelated projects. Viable only as an opt-in. |
| A6 | (Unstated) metaproject skills can coexist with the user's own skills by name. | **At risk.** | Bundled names are generic (`shipit`, `wrapup`, `verify-browser`). Claude Code resolves same-name skills enterprise > personal > project, so a user's own `~/.claude/skills/shipit` silently wins; Copilot keeps the first by location order (A7). |
| A7 | A Claude adapter makes Copilot list each skill twice. | **False (tested 2026-11-25).** Copilot dedupes by skill **name**, not by path or symlink target. | Tested the Copilot runtime that ships with VS Code 1.148.0 (`@github/copilot` 1.0.73) by calling its native `skillsLoad` on four fixture repos: whole-dir symlink, per-skill symlink, copy, and `.agents`-only. Each returned `alpha` once, from `.agents/skills`. A repo with different `alpha` content in `.github`, `.agents` and `.claude` returned only the `.github` one; a `.claude`-only repo returned the `.claude` one (so `.claude/skills` is scanned). Runtime precedence: `.github` > `.agents` > `.claude`. VS Code's own chat loader (`computeSkillDiscoveryInfo` in `workbench.desktop.main.js`) also skips a repeated name ("Skipping duplicate agent skill name"), scanning `.agents` > `.github` > `.claude`; skipped entries are recorded with `skipReason: "duplicate-name"`, which is probably why the docs say both appear on the Skills page. The model sees one. Not tested: Copilot CLI standalone/cloud agent, OpenCode, Cursor. |

## Proposed outcome

A third-party user can run `metaproject new`/`adopt`/`backfill` in a repository that already has its
own skills and harness config, and afterwards:

1. **One source of truth**: the bundled skills live once, as real files, in `.agents/skills/<name>/`,
   tracked by the existing install manifest. `skills sync`, `doctor` and `review` act on that copy only.
2. **Per-harness adapters, recorded in config**: `.metaproject/config.json` declares which harnesses
   need a bridge (e.g. `"skills": {"targets": ["claude"]}`). Harnesses that read `.agents/skills`
   need no adapter. `new`/`backfill`/`adopt` record `["claude"]` when the setting is absent;
   later runs never change it, and setting `[]` removes the bridge.
3. **The Claude Code adapter** writes one entry per bundled skill at `.claude/skills/<name>`:
   a relative per-skill symlink by default, or a managed copy where symlinks are unavailable or the
   user chooses copies. It records what it wrote in the manifest and never creates, replaces or
   deletes a `.claude/skills/*` entry it did not write.
4. **No directory takeover**: metaproject never makes `.claude/skills` (or any harness directory) a
   symlink again. `metaproject doctor` migrates an existing whole-directory link to the adapter
   layout behind confirmation, preserving any non-metaproject skills.
5. Nothing changes for a harness the user did not opt into; removing a target removes only the
   entries metaproject wrote.
6. When Claude Code ships `.agents/skills` discovery (#31005), the Claude adapter can be dropped by
   config with no change to the source of truth.

## Affected users and systems

- Third-party metaproject users on any harness, including Windows users and teams mixing harnesses.
- Existing metaproject projects with the whole-directory link (this repository included) — migration.
- Sub-projects using `skills.location: "root"` (today: a `.claude/skills` link up to the home).
- Code: `scaffold.link_agent_skills`, `skills.py` (`ensure_skills_link`, `inspect_project_skills`,
  `sync_project_skills`, manifest schema), `doctor.py`, `review.py` (R-SKL-5 message),
  `identity`/config schema, the bundled `metaproject` skill and SDLC skill docs that describe the
  layout, `AGENTS.md`/README, and the web `SessionStart` script (`skills sync`).

## Scope

### In Scope (v1)

- `.agents/skills/` as the single, real-file source of truth.
- `skills.targets` config and a Claude Code adapter (per-skill symlink, copy fallback, manifest-tracked).
- Symlink capability detection (OS / `core.symlinks`) choosing copy mode automatically, with an override.
- `doctor` check + fix migrating the whole-directory link; `skills status` reporting adapter state.
- Re-design of `skills.location: "root"` sub-projects on top of the adapter.
- Documentation of the supported harness matrix and how metaproject coexists with user skills.

### Out of Scope (v1)

- User-level (`~/...`) installation as a default. May be added later as an explicit opt-in.
- Adapters for harnesses that already read `.agents/skills` (Copilot, Codex, Antigravity, ZCode, Gemini CLI, Cursor).
- Packaging the skills as a Claude Code plugin.
- Managing or rewriting skills metaproject did not install.
- A gitignored (uncommitted) bridge mode.
- Renaming or prefixing the bundled skills.

## Resolved decisions

- `.agents/skills/` stays the canonical location: it is the shared Agent Skills standard path and
  is read natively by every listed harness except Claude Code.
- The fix is an adapter for the one outlier (Claude Code), not a fan-out to every harness.
- User-level install is rejected as the primary mechanism (A5).
- metaproject owns only entries it wrote, identified by the manifest.
- **Duplicates are acceptable** (Q1, 2026-11-25): Copilot dedupes by name (A7); where a harness
  does list a skill twice, that is tolerated, not designed around.
- **Default targets: Claude** (Q2, amended 2026-11-26): ~~auto-detect~~ — detection after this
  run's own writes always found `CLAUDE.md`/`.claude/settings.json`, so the default is simply
  `["claude"]`, written to `skills.targets` when absent and respected thereafter.
- **Git rule restated** (2026-11-26): `backfill`, `adopt` and `skills sync [--all]` never change
  the repository. They may run only allowlisted read-only git queries (`git config --get
  <key>`, `git config user.name|user.email`), with a timeout and no prompt; any git failure
  means "no opinion", never an error. Supersedes the literal "never runs git".
- **The bridge covers bundled skills only; migration flags the rest** (2026-11-26, operator):
  a user's own skill in `.agents/skills/` is reachable by Claude Code today only through the
  whole-directory link. Removing that link is a one-time operation for a small user base, so
  instead of bridging user skills, `doctor` names every such skill before and after the
  migration so the operator can add their own `.claude/skills` entry.
- **Bridge mode: per-skill relative symlink, automatic copy fallback** (Q3) on Windows or
  `core.symlinks=false`, with a config override; copies are manifest-tracked like the source.
- **Names: keep bare names, detect shadowing** (Q4): `/write-intent` … `/wrapup` are unchanged;
  `skills status` and `doctor` warn when a same-name skill elsewhere (e.g. `~/.claude/skills`, a
  higher-precedence Copilot location) shadows a metaproject skill, and when a `.claude/skills`
  copy has drifted from `.agents/skills` (invisible to Copilot).
- **Bridge entries are always committed** (Q6): fresh clones and cloud sessions see the skills with
  no setup step. A gitignored mode is out of scope.

## Constraints

- Core dependencies stay `typer`, `rich`, `jinja2`; no new runtime dependency.
- Every write goes through the existing single skills write path and stays create-only for
  `new`/`backfill`/`adopt`; migrations are behind confirmation; agent sessions only report.
- Must work on macOS, Linux and Windows checkouts.
- Existing projects must keep working until migrated (no silent breakage on upgrade).

## Open questions

All closed 2026-11-25 (see Resolved decisions). Verification notes carried into the spec:

- Q5: ZCode confirmed from its bundled docs; Gemini CLI and Cursor confirmed from their official
  docs only. Cursor's agent CLI has forum reports of `.agents/skills` not loading; OpenCode untested.
  None of these needs a bridge under this design, so the residual risk is documentation accuracy.
- Untested for duplicates: standalone Copilot CLI, Copilot cloud agent, Cursor, OpenCode
  (tolerated per Q1).
