# Make metaproject the source of truth for SDLC document templates

**Author**: John Fricker.
**Last updated**: 2026-09-14.
**Status**: Approved.
**Approved by**: John Fricker (2026-09-14).

## Problem

metaproject owns the governance/SDLC document templates, but those templates, and the
code that renders and audits them, no longer fit the agent-centered SDLC they serve. The
`sdlc-skills` plugin (`~/Projects/SDLC-skills`) implements that SDLC as a 7-stage cycle
(write-intent → generate-spec → generate-design → generate-plan → implement-plan →
execute-tests → wrapup), and has worked around the gaps by carrying its own copies of
templates. The result is two sources of truth that already disagree.

For the operator and for agents working in metaproject-managed projects, this means:

- **`review` reports every active project as DRIFTED, and Update destroys working
  documents.** `intent.md`, `STATE.md` and `HANDOFF.md` are full-text diffed like
  boilerplate, so any project actually using them drifts; the board's Update rewrites a
  live STATE.md/intent.md from the blank template; `learn` treats cycle content as
  recurring drift.
- **`{Date}` drifts the day after scaffolding** — review renders templates with today's
  date.
- **Project identity is read from `intent.md`**, which is per-change and reset each cycle
  (title becomes `<Title>`; `split("-")[0]` truncates hyphenated titles).
- **Three divergent template copies**: `templates/` (unused, stale — hardcoded
  "Sentinel"), `src/metaproject/templates/` (bundled seed), `~/.metaproject/templates`
  (live). Unknown `{placeholders}` render silently as literal text (`{name}`, `{date}`
  in SDLC-skills' intent.md); four placeholder styles are in use.
- **The template set doesn't cover the cycle**: no spec.md, design.md, plan.md,
  ARCHITECTURE.md, docs/DESIGN-INVARIANTS.md, docs/VERIFIED-FACTS.md, docs/archive/.
  STATE.md's Process list has 3 steps instead of 7.
- **Template content is stale or contradictory**: AGENTS.template.md lags SDLC-skills'
  evolved AGENTS.md (design.md, optional PRs, long-lived docs, open-items gate), has
  typos and a wrong archive naming rule, no testing gate; intent status vocabularies
  differ across copies and docs; no approver field; HANDOFF.md is scaffolded with filler
  that looks like a real handoff; CLAUDE.md duplicates AGENTS.md; `references/documents.md`
  and `SKILL.md` describe a 4-step flow.

## Proposed outcome

metaproject is the single source of truth for every SDLC document template; sdlc-skills
uses those templates and holds no copies of its own. Observably:

1. `metaproject review` on a project mid-cycle reports CLEAN when its governance files
   match and its working documents have the required headings; it never offers Update on
   a working document.
2. A project scaffolded today and reviewed tomorrow is still CLEAN.
3. A project's title/description survive an intent.md reset.
4. One template tree exists in the repo; an unknown `{placeholder}` is reported, not
   silently rendered.
5. `metaproject new` produces every file the 7-stage cycle needs; `wrapup` can reset
   docs from the store rather than from its own inline templates.
6. Every sdlc-skills SKILL.md references metaproject's templates for document shapes and
   stops with a metaproject command when a template is missing.

## Affected users and systems

- **Operator** (John) — runs `new`, `review`, `learn` across all projects.
- **Agents** working in metaproject-managed projects, via the `metaproject` skill and the
  `sdlc-skills` plugin.
- **metaproject** (`~/Projects/metaproject`): `review.py`, `scaffold.py`,
  `templates.py`, `variables.py`, `universe.py`, `learn/collect.py`,
  `src/metaproject/templates/`, `templates/`, `skill/SKILL.md`,
  `skill/references/documents.md`, tests.
- **sdlc-skills** (`~/Projects/SDLC-skills`): all 7 `skills/*/SKILL.md`, `AGENTS.md`,
  `README.md`, root template docs.
- **Existing projects already scaffolded** — their review results change (fewer false
  DRIFTED) and they lack the new identity file until backfilled.

## Scope

### In Scope (v1)

**metaproject — tool behavior**
- Classify deliverables: *governance* (AGENTS.md, CLAUDE.md, README.md, .gitignore) keep
  full diff + Update; *working* (intent, spec, design, plan, STATE) get a required-headings
  check only, never Update; `learn` sees only their heading structure (below).
- HANDOFF.md: template stays in the store but is no longer scaffolded or reported missing.
- Identity file `.metaproject.json` written by `new` (title, description, scaffold
  date); review renders with it, so `{Date}` no longer drifts. Projects without it fall
  back to README.md / pyproject.toml / package.json, never intent.md.
- `learn` uses working documents' heading structure (not their content) as drift
  evidence.
- Minor version bump.
- Delete repo-root `templates/`; bundled `src/metaproject/templates/` is the only in-repo
  copy, with a test guarding it.
- Placeholder convention: `{Var}` = tool-rendered (whitelist), `<…>` = author-filled;
  unknown `{word}` placeholders are reported by review/render.

**metaproject — template content**
- Add templates: spec.md, design.md, plan.md, ARCHITECTURE.md, docs/DESIGN-INVARIANTS.md,
  docs/VERIFIED-FACTS.md, docs/archive/.gitkeep.
- STATE.md: 7-stage Process list; one-line guidance per section naming which stage writes it.
- AGENTS.md: promote SDLC-skills' evolved process section; state stage order and skills;
  fix typos and archive naming (`docs/archive/YYYY-MM-DD-<slug>/`); testing-gate
  placeholder; make Vibe Annotations conditional.
- intent.md: one status lifecycle (Draft → Approved → Complete; Cancelled / Deferred /
  Superseded) and an `Approved by` field, applied to all cycle templates.
- HANDOFF.md: replace filler; add branch/worktree, last commit, SDLC stage, command to re-run.
- CLAUDE.md: `@AGENTS.md` plus Claude-specific notes only; no blank line when description
  is empty.
- README.md: fix the "specs in docs/" pointer. `.gitignore`: add `.claude/worktrees/`.
- `skill/SKILL.md` and `references/documents.md`: describe the 7-stage cycle and the
  governance/working split.

**sdlc-skills**
- Remove inline blank templates from SKILL.md files (generate-spec/design/plan, wrapup);
  reference metaproject's templates instead. A project without `.metaproject.json` isn't
  metaproject-managed: the skill runs `metaproject new . --dry-run` and hands
  `metaproject new .` to the operator (backfill is refused in agent sessions).
- Align skills with the new conventions: status lifecycle + approver field, 7-item STATE.md
  Process list, template detection, HANDOFF.md created from template on interruption,
  wrapup marks intent Complete and resets from the store.
- Update SDLC-skills' `AGENTS.md`/`README.md` to state metaproject is required and owns
  templates.

**Discovery doc**
- Save the archived learn cycle's open items and "still open" observations to
  `docs/discovery/2026-09-04-learn-cycle-open-observations.md`, linked from the archive.

**This worktree**
- Old "improve learn command" cycle archived to
  `docs/archive/2026-09-04-improve-learn-command/` (done as part of opening this cycle).

### Out of Scope (v1)

- Editing `~/.metaproject/templates` directly — the operator refreshes the live store
  (re-seed or `learn apply`) after merge.
- Backfilling or migrating existing projects (identity file, new templates); `review`
  will report what's missing and the operator deploys.
- The broader sdlc-skills improvements from the first review not tied to templates
  (traceability IDs, trivial-change fast path, PR/commit ownership, execute-tests result
  recording, upstream-staleness checks) — candidates for a later cycle.
- Acting on the archived learn cycle's open items (drift signal UI, TUI paging, etc.) —
  recorded in a discovery doc only.
- Non-Python `.gitignore` variants.

## Resolved decisions

- **metaproject is the source of truth** for all SDLC document templates (operator,
  2026-09-13).
- **sdlc-skills requires metaproject**; no fallback copies in the plugin (operator).
- **HANDOFF.md is not scaffolded**; created from its template only on interruption
  (operator).
- **Identity stored at scaffold time** in a project file, with manifest fallback — also
  fixes `{Date}` drift (operator).
- **This intent lives in metaproject**; the old learn cycle was archived first. The
  archived STATE.md is kept whole rather than split into long-lived docs now (operator
  chose archive; agent kept it lossless).
- **Work happens in worktrees** `.claude/worktrees/template-source-of-truth` on branch
  `template-source-of-truth` in both repos (operator).

## Constraints

- metaproject quality gate: `make lint` and `make test` green (ruff; pytest, currently
  333 tests); TDD per AGENTS.md.
- Existing design invariants from the archived learn cycle still hold (render before
  diffing; template store's `.git` never scaffolded; no test invokes a model).
- Review/backfill never overwrite existing project files without the existing operator
  confirmations.
- sdlc-skills remains a valid Claude Code plugin; both repos land together (skills must
  not reference templates metaproject doesn't ship yet).

## Open questions

None open. Resolved 2026-09-14 by John Fricker:

1. Identity: `.metaproject.json`, created by `metaproject new`.
2. sdlc-skills: if the project has no `.metaproject.json`, call `metaproject new`
   (operator runs the backfill; the agent previews with `--dry-run`).
3. `learn` learns from working documents' heading structure.
4. Archived learn cycle's open observations go in a discovery doc.
5. Minor version bump.
