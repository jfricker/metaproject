# Make metaproject the source of truth for SDLC document templates — Spec

**Author**: Claude.
**Derived from**: intent.md (2026-09-14).
**Last updated**: 2026-09-14.
**Status**: Approved.
**Approved by**: John Fricker (2026-09-14).

Requirement IDs (`R-…`) are referenced by acceptance criteria (`AC-…`) and should be cited
by design.md and plan.md. "Project" means a directory metaproject scaffolds or reviews;
"store" means the template directory `review`/`new`/`learn` resolve (bundled seed or
`~/.metaproject/templates`).

## Requirements

### Functional

#### Deliverable classes (metaproject `review`)

- **R-CLS-1** Every deliverable belongs to exactly one class, declared in one place in
  code:
  - *governance*: `AGENTS.md`, `CLAUDE.md`, `README.md`, `.gitignore`;
  - *working*: `intent.md`, `spec.md`, `design.md`, `plan.md`, `STATE.md`,
    `ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md`;
  - *on-demand*: `HANDOFF.md`;
  - *directory*: `docs/`, `docs/archive/`.
- **R-CLS-2** Governance deliverables keep today's behavior: render-then-full-diff;
  DRIFTED on difference; offered for Update and Deploy.
- **R-CLS-3** Working deliverables are checked for *structure* only: DRIFTED iff a
  heading in the rendered template has no matching heading in the project file. A
  template heading matches a project heading at the same level whose text equals, or
  starts with, the template heading's text (so `## Implementation phases (plan.md §2)`
  satisfies `## Implementation phases`). Extra project headings and all body text are
  ignored. Placeholder-only headings (e.g. `# <Title> — Spec`) match any heading of that
  level.
- **R-CLS-4** Working deliverables are never offered for Update (board, `u all`, or
  `update_entry`); `update_entry` raises for them. They remain deployable when missing.
- **R-CLS-5** On-demand deliverables are neither scaffolded by `new` nor reported
  missing by `review`; their templates remain in the store.
- **R-CLS-6** Directory deliverables remain presence checks.

#### Project identity (`.metaproject.json`)

- **R-ID-1** `metaproject new` (fresh or backfill) writes `.metaproject.json` at the
  project root containing at least `title`, `description`, `author`, `created`
  (YYYY-MM-DD scaffold date) and `metaproject_version`. A backfill never overwrites an
  existing `.metaproject.json` (same skip-existing/rollback rules as other files);
  `--dry-run` lists it. The file is tracked in git (included in `new`'s initial commit).
- **R-ID-1a** `metaproject_version` is the version of metaproject that last brought the
  project up to date: written by `new`, and updated only by the future `metaproject
  doctor` (deferred, FC-3). No other command modifies it.
- **R-ID-2** Variable resolution for `review`, `learn`, `backfill`, and `universe` reads
  `.metaproject.json` first; `{Date}` and `{Year}` render from `created`, not today.
- **R-ID-3** Without `.metaproject.json`, title/description fall back in order:
  `README.md` first `# ` heading / first paragraph → `pyproject.toml` `[project]`
  `name`/`description` → `package.json` `name`/`description` → directory name. `intent.md`
  is never read for identity. Title is never truncated at `-`.
- **R-ID-4** `.metaproject.json` is not a reviewable deliverable (never diffed, never
  DRIFTED) but its absence is reported by `review` as an informational note, not
  INCOMPLETE.

- **R-ID-5** *(Amended 2026-09-15 during implementation, approved by John Fricker.)*
  The agent-skills layout `new` creates (`.agents/skills/` plus the `.claude/skills` →
  `../.agents/skills` symlink) includes `.agents/skills/.gitkeep`, so the layout survives
  commit and clone (git does not track empty directories; without it a clone has a
  dangling `.claude/skills` link). Existing files are never overwritten.

#### Template store

- **R-TPL-1** Repo-root `templates/` is removed; `src/metaproject/templates/` is the only
  in-repo template tree.
- **R-TPL-2** Placeholder convention across all templates: `{Var}` is tool-rendered and
  must be whitelisted; `<…>` is author-filled and left as-is. No other placeholder style
  (`{Problem description}`, `{agent/user}`, `YYYY-MM-DD` as a placeholder) remains in
  bundled templates.
- **R-TPL-3** Rendering reports any single-braced `{identifier}` that is not whitelisted:
  `new` (including `--dry-run`) and `review` print a warning naming the file and
  placeholder; rendering still completes.
- **R-TPL-4** The store provides templates for: `spec.md`, `design.md`, `plan.md`,
  `ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md`,
  `docs/archive/.gitkeep`, in addition to existing ones. `new` scaffolds all of them
  except on-demand deliverables.
- **R-TPL-5** Cycle-document templates (intent, spec, design, plan) share a header:
  `# <Title>[ — Spec|Design|Implementation Plan]`, `**Author**`, `**Derived from**`
  (except intent), `**Last updated**`, `**Status**: Draft.`, `**Approved by**: —`.
  Status vocabulary: `Draft`, `Approved`, `Complete`, `Cancelled`, `Deferred`,
  `Superseded`.
- **R-TPL-6** A cycle document is *blank* iff its first `# ` heading contains `<Title>`.
  This is the single detection rule documented for skills and tools. An intent.md seeded
  with carried-forward open questions but still titled `<Title>` is blank.
  `ARCHITECTURE.md` and the long-lived docs use a `{ProjectTitle}`-style header, not the
  cycle header, and are never blank.
- **R-TPL-7** Template content:
  - `STATE.md`: 7-item Process list (write-intent … wrapup) and a one-line HTML comment
    under each section naming which stage writes it.
  - `AGENTS.md`: process section covering the 7 stages in order with skill names; the
    artifact conventions currently in SDLC-skills' `AGENTS.md` (design.md, optional PRs,
    ARCHITECTURE.md, long-lived docs, open-items gate); archive layout
    `docs/archive/YYYY-MM-DD-<slug>/`; a testing-gate placeholder
    (`<quality gate, e.g. make format && make lint && make test>`, full-diffed like the
    rest of AGENTS.md); the Vibe Annotations line removed; typos fixed.
  - `HANDOFF.md`: no filler text; sections for current state, SDLC stage, branch/worktree,
    last commit, command(s) to re-run, next steps, blockers.
  - `CLAUDE.md`: `@AGENTS.md` import plus Claude-specific notes; renders with no stray
    blank line when description is empty.
  - `README.md`: no claim that specs live in `docs/`.
  - `.gitignore`: includes `.claude/worktrees/`.
- **R-TPL-8** A new non-interactive command `metaproject backfill [FILE...] [--dir
  PROJECT_DIR]` creates missing deliverables from the store in a project (default: the
  current directory):
  - with no `FILE`, it creates **every** missing deliverable that `new` scaffolds, in one
    call (on-demand deliverables excluded);
  - with `FILE`s, it creates exactly those, including on-demand ones (`HANDOFF.md`);
  - it never overwrites: an existing named `FILE` is reported and the command exits
    non-zero without writing anything; with no `FILE`, existing files are skipped and
    listed;
  - supports `--dry-run`; renders with R-ID-2 variables, resolved once before the first
    write; is permitted in agent sessions; never runs git.
  Distinct from `metaproject new .` (the interactive, git-aware backfill of a directory
  that isn't yet a metaproject project), which is unchanged. *(See Flagged concern FC-1.)*

#### `learn`

- **R-LRN-1** For working deliverables, `collect` produces evidence from heading
  structure only: the rendered template's heading list diffed against the project's
  heading list. Body text of working documents never enters evidence, scoring, or model
  prompts.
- **R-LRN-1a** Proposals for a working deliverable are heading changes only: *add* a
  heading (with an optional one-line HTML comment describing the section), inserted after
  its nearest preceding heading shared with the template; or *remove* a template heading
  together with the template's own body under it.
- **R-LRN-1b** Heading removal is proposable for working deliverables, reversing the
  archived learn spec's no-deletions rule (§5.4.6) for this class only. Removal evidence
  comes only from a non-empty project file whose heading list lacks the template heading;
  a missing or empty file is never removal evidence. Removals are scored like additions.
  Governance deliverables still never get deletion proposals.
- **R-LRN-1c** *(Amended 2026-09-14 during design, approved by John Fricker.)* A heading
  proposal is emitted only when at least `learn.min_structure_evidence` distinct projects
  (default 2) contribute. This replaces the archived "ranked, not gated" rule for heading
  proposals only.
- **R-LRN-2** Governance deliverables keep current evidence behavior.
- **R-LRN-3** `learn`'s default targets include the new working deliverables and exclude
  on-demand ones. A `config.json` that already pins `learn.targets` is not rewritten;
  updating it belongs to the deferred `doctor` (FC-3). A heading whose level changed
  counts as one removal plus one addition.
- **R-LRN-4** `drift.py`'s review signal uses the R-CLS-3 structural result for working
  deliverables.

#### metaproject skill docs

- **R-DOC-1** `skill/SKILL.md` and `skill/references/documents.md` describe the 7-stage
  cycle, the deliverable classes, `.metaproject.json`, the blank-detection rule, and
  `metaproject backfill`. `references/commands.md` documents `backfill`. Installed copies
  under `~/.claude/skills/metaproject/` are refreshed by `init --force` or the deferred
  `doctor`, not by this cycle.
- **R-DOC-2** `docs/discovery/2026-09-04-learn-cycle-open-observations.md` records the
  archived learn cycle's "Open items carried into plan.md" and "Closing — what is still
  open" content verbatim, each item with its source section; items already struck
  through are marked "resolved in cycle"; nothing is re-verified against current code.
  `docs/archive/2026-09-04-improve-learn-command/README.md` indexes the archived files and
  links to the discovery doc. `docs/discovery/` is ad hoc: no template, not a deliverable.

#### sdlc-skills

- **R-SK-1** No `skills/*/SKILL.md` contains an inline document template. Skills refer to
  metaproject's templates by deliverable name.
- **R-SK-2** The plugin ships a `SessionStart` hook (`hooks/hooks.json` +
  script) that, at the git top-level of the session's working directory, checks:
  (a) `metaproject` is on PATH and reports version ≥ 0.7.0; (b) `.metaproject.json`
  exists. If both pass it prints nothing. Otherwise it injects one short context notice
  naming the failure and the fix (install/upgrade metaproject; or preview with
  `metaproject new . --dry-run` and have the operator run `metaproject new .`). The hook
  never blocks the session and never writes files.
- **R-SK-2a** Skills treat "metaproject ≥ 0.7.0 is installed and `.metaproject.json`
  exists" as a session-wide assumption and do not re-check it. If the session-start
  notice reported a failure, a skill stops and repeats that fix instead of proceeding.
  If a metaproject command fails anyway (e.g. the operator fixed things mid-session, or
  the file was removed), the skill stops and reports the command output.
- **R-SK-3** A skill that needs a missing document (e.g. `generate-design` with no
  `design.md`, `implement-plan` writing `HANDOFF.md`) runs `metaproject backfill <file>`.
- **R-SK-4** "Blank" is decided by R-TPL-6 everywhere a skill checks it (write-intent's
  precondition, generate-spec's stale-spec check, wrapup's reset).
- **R-SK-5** Skills write and check status with the R-TPL-5 vocabulary and fill
  `**Approved by**` on approval; approval gates check `Status: Approved`.
- **R-SK-6** Each skill ticks its own item in STATE.md's 7-item Process list.
- **R-SK-7** `wrapup` sets intent.md `Status: Complete`, then `git mv`s intent, spec,
  design, plan, STATE and (if present) HANDOFF into the cycle archive — STATE.md is
  archived whole, after its invariants/facts are appended to the long-lived docs. It then
  recreates them with a single `metaproject backfill` (no file arguments) and seeds
  carried-forward open items into the new intent.md. If ARCHITECTURE.md or a long-lived
  doc is missing, it runs `metaproject backfill <file>` for it before appending. `wrapup` carries
  no templates of its own.
- **R-SK-8** SDLC-skills `AGENTS.md` and `README.md` state that metaproject is required
  and owns the document templates; SDLC-skills' own root docs are brought in line with
  the new templates (header fields, 7-item STATE Process list) and it gains a
  `.metaproject.json`, created by the operator running `metaproject new .` in the
  SDLC-skills worktree after the agent previews it with `--dry-run`.

#### Release

- **R-REL-1** metaproject version bumped to the next minor (0.6.1 → 0.7.0) via the
  project's bump script, with README/baseline tests synchronized. The bump runs on `main`
  after the branch is merged, not on the branch, so the `v0.7.0` tag lands on `main`.
- **R-REL-2** sdlc-skills `plugin.json` (and marketplace entry, if versioned) is set to
  `0.0.2`, marking the plugin experimental.

### Non-functional

- **R-NF-1** `make format && make lint && make test` green in metaproject; new behavior
  covered by tests written before implementation (TDD per AGENTS.md).
- **R-NF-2** Archived-cycle invariants still hold, except as amended by R-LRN-1b: render before diffing; template-tree
  walkers skip `.git`; remediation batches resolve variables once before the first write;
  no test invokes a model.
- **R-NF-3** No command overwrites an existing project file without today's operator
  confirmations (backfill prompts, `--force`); `backfill` never overwrites.
- **R-NF-4** A test fails if a bundled template contains a non-whitelisted `{identifier}`
  or a deliverable lacks a class.
- **R-NF-5** Both repos' branches are mergeable together: sdlc-skills references only
  commands and templates that exist on metaproject's branch. Merge order: metaproject
  first (then its version bump on `main`), operator refreshes `~/.metaproject/templates`
  by hand (FC-3), then sdlc-skills.
- **R-NF-6** sdlc-skills remains a valid Claude Code plugin: all 7 skills and the
  `SessionStart` hook load.
- **R-NF-7** SDLC-skills gains a minimal `Makefile` with `help` and `test`; `make test`
  runs a shell test of the session-start hook script covering AC-14a.

## Acceptance criteria

- **AC-1** (R-CLS-2/3) A project scaffolded by `new`, whose intent/spec/design/plan/STATE
  are then filled with arbitrary content but keep their headings, reviews as `✓ CLEAN`.
- **AC-2** (R-CLS-3) Removing `## Verified facts (do not re-investigate)` from that
  project's STATE.md makes review report STATE.md DRIFTED; renaming it to
  `## Verified facts (do not re-investigate) — 2026` does not.
- **AC-3** (R-CLS-4) A DRIFTED working deliverable is not listed as updatable; calling
  `update_entry` on it raises `MetaProjectError`.
- **AC-4** (R-CLS-5) `new` does not create `HANDOFF.md`; review of a project without it
  is not INCOMPLETE.
- **AC-5** (R-ID-1/2) A project scaffolded with a fixed clock, then reviewed with the
  clock advanced 1 day and 1 year, reviews `✓ CLEAN`; `.metaproject.json` has the five
  fields.
- **AC-5a** (R-ID-1a, R-ID-4) `review` and `backfill` never modify `metaproject_version`;
  a project without `.metaproject.json` gets an informational note, not `! INCOMPLETE`.
- **AC-6** (R-ID-3) With no `.metaproject.json`, replacing intent.md's title with
  `<Title>` changes neither review results nor the universe catalog title; a
  hyphenated README title is not truncated; pyproject/package.json fallbacks are each
  covered.
- **AC-7** (R-TPL-1/2/4, R-NF-4) Repo-root `templates/` is gone; the bundled-template
  test passes; `new --dry-run` lists every R-TPL-4 file and no HANDOFF.md.
- **AC-8** (R-TPL-3) A store template containing `{projcet}` produces a warning naming
  file and placeholder from `new` and `review`.
- **AC-9** (R-TPL-5/6/7) Each cycle template has the shared header; each is blank by the
  R-TPL-6 rule; STATE.md has 7 Process items; CLAUDE.md starts with `@AGENTS.md` context
  and has no double blank line when rendered with empty description; `.gitignore`
  contains `.claude/worktrees/`.
- **AC-10** (R-TPL-8) In a scaffolded project with spec.md, design.md and STATE.md
  deleted, `metaproject backfill` recreates all three blank in one call and lists the
  skipped existing files; `metaproject backfill HANDOFF.md` creates HANDOFF.md;
  `metaproject backfill spec.md` on an existing spec.md exits non-zero and writes nothing;
  with `CLAUDECODE=1` set it still runs; `--dry-run` writes nothing; no git command runs.
- **AC-11** (R-LRN-1) In a `learn` collect over a fixture where 3 projects add body text
  to STATE.md and 2 add a `## Risks` heading, evidence contains the heading and none of
  the body text; the synth prompt assembled for STATE.md contains no body text.
- **AC-11a** (R-LRN-1a/1b/3/4) Over a fixture: 3 of 4 projects removing
  `## Constraints` from intent.md yields a removal proposal; an empty or missing intent.md
  contributes no removal evidence; an applied heading addition lands after its nearest
  shared heading; a heading whose level changed yields one removal and one addition;
  drift boost for a working deliverable follows the structural review result; no
  governance deliverable ever gets a removal proposal.
- **AC-12** (R-DOC-2) The discovery doc exists, contains every bullet from the two
  archived sections, and the archive links to it.
- **AC-12a** (R-DOC-1) `skill/SKILL.md` and `references/documents.md` cover the 7 stages,
  deliverable classes, `.metaproject.json`, the blank rule and `backfill`;
  `references/commands.md` has a `backfill` section.
- **AC-13** (R-SK-1) `rg -n '^```markdown' skills/*/SKILL.md` finds no document templates.
- **AC-14** (R-SK-2a/3/4/5/6/7) Each SKILL.md relies on the session-start notice (no per-skill check), uses
  the blank rule and status vocabulary, and names its STATE.md Process item; wrapup
  specifies `Status: Complete`, archives STATE.md after appending to the long-lived docs,
  runs one `metaproject backfill` for the reset, and `metaproject backfill <file>` for a
  missing ARCHITECTURE.md or long-lived doc.
- **AC-14a** (R-SK-2) Running the hook script in: a project with `.metaproject.json` and
  metaproject 0.7.0 prints nothing and exits 0; a project without the file prints a
  notice containing `metaproject new . --dry-run`; a PATH without `metaproject`, or with a
  0.6.x stub, prints an install/upgrade notice; a subdirectory of a managed repo and a git
  worktree of it both pass. No case writes a file.
- **AC-15** (R-SK-8, R-NF-6) SDLC-skills README/AGENTS state the metaproject dependency;
  SDLC-skills has `.metaproject.json`; `metaproject review` on SDLC-skills (branch build)
  reports no working-document drift; the plugin installs and lists 7 skills.
- **AC-15a** (R-REL-2, R-NF-7) sdlc-skills `plugin.json` version is `0.0.2`; `make help`
  and `make test` succeed in SDLC-skills.
- **AC-16** (R-NF-1/2) On the branch: `make format && make lint && make test` pass and
  pre-existing invariant tests still pass.
- **AC-16a** (R-REL-1, R-NF-5) After merge: `main` is at 0.7.0 with tag `v0.7.0`; merge
  order metaproject → store refresh → sdlc-skills was followed.

## Flagged concerns

All resolved by John Fricker, 2026-09-14.

- **FC-1 — New agent-permitted write command (`metaproject backfill`).** `new .` on an
  existing project is refused in agent sessions, so skills need R-TPL-8's create-only
  command. **Approved**; named `backfill`, creates all missing files at once by default.
- **FC-2 — Existing projects become INCOMPLETE** once the new working deliverables are
  required. **Accepted**; the operator deploys them via the board.
- **FC-3 — Live store refresh.** `~/.metaproject/templates` won't have the new templates
  until refreshed, and `init --force` would clobber `learn apply` edits. **Deferred** to a
  future `metaproject doctor` command (not built in this cycle); until then the operator
  refreshes the store by hand after merge. Carried in STATE.md's open items.
- **FC-4 — Cross-repo coupling.** sdlc-skills hard-depends on metaproject ≥ 0.7.0 with no
  degraded mode. **Approved**; stated in sdlc-skills README (R-SK-8).

## Open questions

- Exact heading-list diff representation for `learn` evidence (unified diff of heading
  lines vs. structured added/removed headings). (Design.)
