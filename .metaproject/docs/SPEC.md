# Harness-neutral project skills: one source, per-harness adapters — Spec

**Author**: John Fricker.
**Derived from**: INTENT.md (2026-11-26 amendment).
**Last updated**: 2026-11-26.
**Status**: Approved.
**Approved by**: John Fricker (2026-11-26; v2 after the spec review, v1 approved 2026-11-25).

Terms: **source** = `<home>/.agents/skills/<name>/` holding a `SKILL.md` (`home` is the project,
or a `skills.location: "root"` sub-project's home). A **bundled** skill is one metaproject
ships; a **user** skill is any other source directory. **Bridge entry** =
`<project>/.claude/skills/<name>`, a per-skill symlink or copy making a source visible to
Claude Code. **Target** = a harness needing bridge entries; v1 defines exactly one, `claude`.
**Manifest** = `<home>/.agents/skills/.metaproject-skills.json`. **Read-only git query** = one
of the allowlist in R-BRG-25.

## Requirements

### Functional

**Source of truth**

- **R-BRG-1** The source stays `.agents/skills/<name>/`. Bundled skills are written only through
  `skills.sync_project_skills` (existing invariant). metaproject never writes a symlink inside
  `.agents/skills/` and never writes into a user skill.
- **R-BRG-2** No command creates `.claude/skills` (or any harness directory) as a symlink.
  `.claude/skills` is a real directory shared with the user's own entries.

**Configuration**

- **R-BRG-3** `.metaproject/config.json` gains `skills.targets` (list; v1 accepts `"claude"`;
  `[]` = no bridge) and `skills.link_mode` (`"auto"` default, `"symlink"`, `"copy"`). An
  unknown target name or mode yields one warning per run and is ignored, never an error.
- **R-BRG-4** When `new`, `backfill` or `adopt` runs and `skills.targets` is absent, it is set to
  `["claude"]`. Once present, metaproject never changes it.
- **R-BRG-5** A project whose config has no `skills.targets` behaves as `["claude"]` in
  `skills status|sync` and `doctor`; `doctor` offers to record it (R-BRG-20).
- **R-BRG-6** Recording `skills.targets` writes through `identity.config_path` (a legacy config
  file is updated in place), adds only that key, and keeps every other key byte-for-byte as
  parsed. A config that is unreadable or not a JSON object is not written: one warning, and
  the R-BRG-5 default applies. This amends the invariant "an existing config is kept as
  written" (DESIGN-INVARIANTS 2026-09-29) to "kept, except that an absent
  `skills.targets` is added".

**Claude bridge**

- **R-BRG-7** For target `claude`, every bundled skill gets one bridge entry at
  `<project>/.claude/skills/<name>`, pointing at its source (the home's, for a delegating
  sub-project). User skills in `.agents/skills/` get no bridge entry (operator decision
  2026-11-26); see R-BRG-20.1.
- **R-BRG-8** Link mode for `auto`: **copy** when `_is_windows()` or the read-only query
  `git config --get core.symlinks` in the project returns `false`; otherwise **symlink**. Any
  git failure (absent, timeout, error, sandbox) = no opinion. A symlink entry's text is
  relative, computed from resolved paths. Explicit `"symlink"`/`"copy"` overrides detection.
  If writing a symlink fails (e.g. no privilege), that entry is written as a copy with a
  warning. The mode and its reason are reported.
- **R-BRG-9** Ownership: metaproject owns a bridge entry only if the manifest records it. An
  unrecorded `.claude/skills/<name>` is **foreign**: never replaced, moved or deleted; that
  name's bridge is skipped with a warning (and the note "identical" when it already matches
  the source). `skills sync --force NAME` records an identical foreign entry, or replaces a
  differing one; nothing else claims it. Other entries in `.claude/skills/` are never read.
- **R-BRG-10** The manifest records, per project (key = path relative to the home, POSIX
  separators, `.` for the home) and target: `created` (which of `.claude/`,
  `.claude/skills/` metaproject created) and per entry its mode plus the symlink text or the
  copy's per-file sha256 map. The manifest format version becomes 2.
- **R-BRG-11** Bridge entry states (`skills status`):
  - `current` — symlink with the expected text, or copy whose files hash to the source.
  - `missing` — no entry and none recorded, or recorded but absent.
  - `outdated` — recorded and pristine but not current: a symlink with stale text; a copy
    matching its recorded hashes but not the source; an **unmaterialised symlink** (a regular
    file whose content equals the recorded link text — a git symlink checked out without
    symlink support); a dangling symlink.
  - `modified` — recorded copy edited by hand, or a recorded entry replaced by anything other
    than an unmaterialised symlink.
  - `foreign` — R-BRG-9.
- **R-BRG-12** Mode changes. Under `auto`, a **working** entry is never converted to the other
  mode (a valid copy on a symlink-capable machine stays a copy), so mixed-OS teams do not
  flip entries back and forth; broken entries (`outdated` above) are rewritten in the
  resolved mode. With an explicit `link_mode`, a pristine entry of the other mode is
  `outdated` and is rewritten.
- **R-BRG-13** Writes, through one bridge write path:
  - `new` / `backfill` / `adopt` (create-only): create `missing` entries only.
  - `skills sync` and `doctor`'s fix: create `missing`, rewrite `outdated`; `modified` only
    with `--force NAME`; `foreign` per R-BRG-9.
  - `--force NAME` applies to both the bundled source and the bridge entry for `NAME`.
  - A copy is staged under the existing `.agents/.metaproject-skills-tmp/`, verified, swapped
    in; nothing metaproject-owned is staged under `.claude/`.
  - `--dry-run` and `skills status` write nothing.
- **R-BRG-14** Target removal: when `claude` is not in `skills.targets`, `skills sync` and
  `doctor`'s fix remove recorded pristine entries and their records, listing each. Modified
  entries are left and reported. `.claude/skills/` and then `.claude/` are removed only if the
  manifest says metaproject created them and they are empty.
- **R-BRG-15** Write denied: when the bridge write is refused by the OS or sandbox
  (`PermissionError`), the source pass still completes, no bridge state is recorded for the
  refused entries, and the report says to run `metaproject skills sync` outside the sandbox.
  Not a failure (exit code unchanged), like the hooks' write-denied notice.
- **R-BRG-16** Newer manifest: when the manifest version is greater than 2, the bridge pass
  writes nothing and removes nothing (ownership unknown); the existing source-pass rules
  apply unchanged (`update` raises, create-only callers install missing sources and leave the
  manifest alone).

**Delegating sub-projects (`skills.location: "root"`)**

- **R-BRG-17** A delegating sub-project keeps no source of its own. Its bridge entries live in
  its own `.claude/skills/<name>` and point at (or copy) the home's sources. Its targets and
  link mode are its own config's.
- **R-BRG-18** Its entries are recorded in the home's manifest under the sub-project's relative
  path.

**The whole-directory link (legacy) and other `.claude/skills` shapes**

- **R-BRG-19** **Legacy link** = `.claude/skills` that is a symlink resolving to the project's (or
  home's) `.agents/skills`, or a regular file whose content is that link's text (the
  unmaterialised form on Windows / `core.symlinks=false`). While present,
  `new`/`backfill`/`adopt`/`skills sync` leave it alone, write no bridge entries, and report
  `legacy link: run metaproject doctor`. Exit code unchanged.
- **R-BRG-20** `doctor` checks, each reported and confirmed separately, in this order:
  1. **legacy link** — the finding names every **user skill that would be lost**: each
     non-dot directory with a `SKILL.md` in the linked `.agents/skills/` that is not a bundled
     skill (Claude Code sees it only through the link). Fix: remove the link, create a real
     `.claude/skills/` (recorded as created), write bridge entries for the bundled skills,
     record `skills.targets` if absent. On any failure: remove what was created and restore the
     original link (or file) exactly. After success, print the lost-skill list again with the
     instruction to add a `.claude/skills/<name>` entry for any skill Claude Code should still
     see, then "commit `.claude/skills`". The list is warning-only: it never blocks the fix.
     Never runs git.
  2. **skills targets** — absent `skills.targets`: fix records `["claude"]` (R-BRG-6).
  3. **project skills** — sources and bridge entries (missing/outdated → fixable; modified,
     foreign, newer manifest → report-only).
  4. **skill shadowing** — report-only (R-BRG-23).
  Agent sessions report only (existing doctor rule).
- **R-BRG-21** `.claude/skills` as a symlink resolving elsewhere, or as any other regular file:
  never touched; sources are installed; bridge entries are not written; the reason is
  reported; exit code unchanged. Replaces the R-SKL-5 refusal.
- **R-BRG-22** `.claude/skills` as a real directory: bridge entries are added beside the user's
  entries per R-BRG-9. R-SKL-5 is retired.

**Shadowing and drift (detection only)**

- **R-BRG-23** `skills status` and `doctor` warn per skill when a same-named skill exists where
  it takes precedence over the project's: `~/.claude/skills/<name>` (Claude Code personal >
  project) and `<project>/.github/skills/<name>` (Copilot reads `.github` first). Nothing is
  written; exit code unchanged.
- **R-BRG-24** A `modified` copy entry is reported with the note that Copilot loads
  `.agents/skills` instead, so the two harnesses run different text.

**Git rule**

- **R-BRG-25** `new`'s existing git init aside, `backfill`, `adopt` and `skills status|sync
  [--all]` never change a repository. The only git commands they may run are
  `git config --get core.symlinks` and `git config user.name` / `user.email` (allowlist),
  each with a timeout, `GIT_TERMINAL_PROMPT=0`, and failure treated as no opinion. This
  restates AGENTS.md's "never runs git" and the DESIGN-INVARIANTS line "adopt … runs no git".

**Reporting, contracts and docs**

- **R-BRG-27** `skills status` text output shows per skill the source state and, per target,
  the bridge state; the mode and reason; legacy-link, foreign-link, write-denied, shadowing
  and drift notices.
- **R-BRG-28** `skills status --format json`: the top-level `link` key is removed; `refusal`
  remains only for a delegating sub-project with no home; a `bridges` object is added
  (`{"<target>": {"mode", "mode_reason", "notice", "entries": {"<name>": {"state", "action"}}}}`)
  plus `shadowing: [...]`.
- **R-BRG-29** Exit codes: `skills status|sync` exit 1 only for the existing failures (unknown
  `--force` name, newer manifest under `update`, I/O failure after rollback, delegating
  sub-project with no home). Foreign entries, legacy link, foreign `.claude/skills`, write
  denied and shadowing exit 0. `sync --all` counts a project as failed only for those exit-1
  causes.
- **R-BRG-30** `new`/`backfill`/`adopt` output and their result objects (`scaffold_project`'s
  result `skills_link`, `AdoptResult.skills_link`, `BackfillResult.skills_notice` /
  `skills_link`) report bridge results instead of the directory link and R-SKL-5.
- **R-BRG-31** Documentation: AGENTS.md (architecture, key files, git rule), README (adoption,
  skills, refusal text being retired), the bundled `metaproject` skill (`SKILL.md`,
  `references/commands.md`, `references/documents.md`), `templates/AGENTS.template.md`, and a
  harness matrix (natively `.agents/skills`: Copilot, Codex, Antigravity, ZCode, Gemini CLI,
  Cursor; Claude Code via the bridge). DESIGN-INVARIANTS gets superseded notes for R-SKL-5,
  "adopt keeps config as written" and "runs no git".
- **R-BRG-32** SessionStart script: no change. It runs the pinned CLI's `skills sync`; a pin
  older than this release meeting a v2 manifest reports `newer` and the script still exits 0.
  Documented in the metaproject skill.
- **R-BRG-33** This repository is migrated with `metaproject doctor .` run by the operator.

### Non-functional

- **N-1** No new runtime dependency; core stays `typer`, `rich`, `jinja2`.
- **N-2** Idempotent: a second run of any command writes nothing; the manifest is byte-identical.
- **N-3** Atomic per entry: a failed bridge write leaves the previous entry (or nothing), never a
  half-copied directory; a crash mid-swap is recovered on the next run.
- **N-4** Portable: one `_is_windows()` seam and the git query are the only platform inputs;
  tests drive both through the seam and a real repo with `core.symlinks=false`.
- **N-5** Existing projects keep working without migration (R-BRG-5, R-BRG-19).
- **N-6** Agent-session rules unchanged: `skills status|sync` agent-safe; doctor fixes need an
  operator.
- **N-7** Full gate passes: `make format && make lint && make test`.

## Acceptance criteria

1. **New project** — `metaproject new`: `.claude/skills/` is a real directory with one relative
   symlink per bundled skill into `.agents/skills/`; config has `"targets": ["claude"]`; nothing
   under `.agents/skills/` is a symlink (R-BRG-1/2/4/7).
2. **Adopt with user skills** — repo with `.claude/skills/my-skill/` and `.claude/skills/shipit/`:
   `adopt` installs all sources, bridges every bundled skill except `shipit`, warns that
   `.claude/skills/shipit` is foreign, leaves both user directories byte-identical; `skills sync
   --force shipit` replaces it and records it (R-BRG-9/22).
3. **Adopt with no Claude files** — repo with no `CLAUDE.md`/`.claude/`: `"targets": ["claude"]`
   recorded; bridge entries created (R-BRG-4).
4. **Copy mode** — `link_mode: "copy"`; separately `_is_windows()` patched true; separately a repo
   with `core.symlinks=false`; separately git absent from `PATH` (→ symlink, no error): entries
   are real directories hashing equal to the source where copy applies; mode reason reported
   (R-BRG-8).
5. **Symlink failure** — `os.symlink` patched to raise: entry written as a copy with a warning.
6. **Sync** — after a bundled skill changes: source updated; copy entries updated; symlink
   entries untouched; a symlink with stale text is `outdated` and rewritten; a hand-edited copy
   is `modified`, reported with the Copilot note, replaced only with `--force NAME`
   (R-BRG-11/13/24).
7. **Mode rules** — explicit `link_mode` change converts pristine entries; under `auto` a working
   copy on a symlink-capable machine stays a copy; an unmaterialised symlink file is `outdated`
   and rewritten in the resolved mode (R-BRG-12).
8. **Target removal** — `"targets": []`: recorded pristine entries removed, a modified one kept and
   reported, `.claude/skills/` and `.claude/` removed only if recorded as created and empty
   (R-BRG-14).
9. **Legacy migration** — fixture with the whole-directory link and a user skill
   `.agents/skills/mine/`: `skills sync` reports the legacy link, writes nothing under `.claude/`,
   exits 0; `doctor`'s finding names `mine` as a skill that would be lost; after confirmation it
   yields a real `.claude/skills/` with entries for every bundled skill and none for `mine`,
   records `targets`, and repeats the `mine` warning with the add-an-entry instruction;
   `mine` is untouched in `.agents/skills/`; an injected failure restores the link exactly; the
   same with the link as an unmaterialised regular file (R-BRG-19/20).
10. **Foreign `.claude/skills`** — symlink to an unrelated directory, and separately an unrelated
    regular file: sources installed, no bridge writes, reason reported, untouched, exit 0
    (R-BRG-21/29).
11. **Delegating sub-project** — `skills.location: "root"`: no source of its own; its entries
    resolve to the home's sources; recorded in the home manifest under its relative path; a
    former directory link to the home is a legacy link (R-BRG-17/18/19).
12. **Shadowing** — temp `HOME` with `~/.claude/skills/wrapup` and project `.github/skills/shipit`:
    both warned in `skills status` and `doctor`; exit 0; nothing written (R-BRG-23).
13. **Old projects** — config without `skills.targets`: status treats it as `claude`; `doctor` lists
    "skills targets" and records it on confirm; an unparseable config is left untouched with a
    warning (R-BRG-5/6).
14. **Config preservation** — adopt/backfill on a config with extra keys, and on a legacy-location
    config: only `skills.targets` added, in place (R-BRG-6).
15. **Newer manifest** — manifest `"version": 3`: no bridge writes or removals; existing source
    behaviour unchanged (R-BRG-16).
16. **Write denied** — bridge write raising `PermissionError`: sources written, notice reported,
    nothing recorded for the refused entries, exit 0 (R-BRG-15).
17. **Atomicity** — failure injected during a copy swap leaves the previous entry; a leftover
    staging `.old` is restored on the next run (N-3).
18. **Git allowlist** — `backfill`, `adopt`, `skills status|sync [--all]` with `subprocess.run`
    patched to reject any command outside R-BRG-25's allowlist: pass; none changes git state
    (R-BRG-25).
19. **Agent sessions** — under `CLAUDECODE=1`, `doctor` reports the legacy link and targets but
    writes nothing; `skills sync` works (N-6).
20. **Reporting** — `skills status` text and `--format json` match R-BRG-27/28; an unknown target
    or mode warns once (R-BRG-3); `new`/`backfill`/`adopt` narration shows bridge results and
    no R-SKL-5 text (R-BRG-30).
21. **Exit codes** — R-BRG-29 matrix, including `sync --all` with one legacy-link project (exit 0)
    and one newer-manifest project under `update` (exit 1).
22. **Idempotence** — `new`, `adopt`, `skills sync` run twice: no writes the second time; manifest
    bytes unchanged (N-2).
23. **This repo (manual)** — after the operator runs `metaproject doctor .`: `.claude/skills` is a
    real directory of per-skill symlinks and Claude Code lists `/write-intent` … `/wrapup`
    (R-BRG-33).
24. Gate green (N-7); docs updated (R-BRG-31/32).

## Flagged concerns

All resolved; recorded so the design does not reopen them.

1. **Copilot opening a delegating sub-project alone** — resolved by R-BRG-17 (its own
   `.claude/skills` entries, which Copilot reads).
2. **Manifest v2 stops older CLIs syncing** — accepted (R-BRG-16, R-BRG-32).
3. **Migration is a git-visible change** — doctor never runs git; tells the operator to commit.
4. **Sync deletes on target removal** — only recorded pristine entries, each listed (R-BRG-14).
5. **Windows not exercisable here** — simulated (N-4); a real Windows check goes to TODO.md at
   wrapup.
6. **Spec review 2026-11-26** (24 findings) — resolved in this version: git rule restated by the
   operator (R-BRG-25); default target fixed to `claude` by the operator (R-BRG-4); config
   writes (R-BRG-6); unmaterialised symlinks and mode rules (R-BRG-11/12/19); user skills
   flagged at migration rather than bridged (R-BRG-7, R-BRG-20.1; operator, 2026-11-26); "claimable" dropped in favour of `--force` (R-BRG-9); write denied
   (R-BRG-15); newer manifest (R-BRG-16); doctor split (R-BRG-20); JSON and exit codes
   (R-BRG-28/29); SessionStart (R-BRG-32); untested-as-written ACs reworded (4, 15, 23).

## Open questions

None.
