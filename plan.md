# Make metaproject the source of truth for SDLC document templates — Implementation Plan

**Author**: Claude.
**Derived from**: spec.md, design.md (2026-09-14).
**Last updated**: 2026-09-14.
**Status**: Approved.
**Approved by**: John Fricker (2026-09-14, via plan-mode approval).

## Context

metaproject's templates and review/learn code don't fit the 7-stage SDLC that
sdlc-skills implements; sdlc-skills carries its own template copies, so two sources of
truth disagree. Approved intent/spec/design (metaproject worktree
`.claude/worktrees/template-source-of-truth`) make metaproject the single owner: document
classes, `.metaproject.json` identity, a create-only `backfill` command, full cycle
template set, heading-structure learning, and sdlc-skills rewired to use them with a
SessionStart check. Requirement IDs below refer to spec.md.

Work happens in two worktrees on branch `template-source-of-truth`:
- **MP** = `~/Projects/metaproject/.claude/worktrees/template-source-of-truth`
- **SK** = `~/Projects/SDLC-skills/.claude/worktrees/template-source-of-truth`

TDD throughout MP (AGENTS.md): each step writes failing tests first, then code, then
`make format && make lint && make test` before its commit. One commit per step.

## Steps

### Phase A — metaproject foundations

**A1. `deliverables.py`** (R-CLS-1, R-LRN-3)
- Tests `tests/test_deliverables.py`: every path has one class; `scaffolded()` excludes
  HANDOFF.md; `learn_targets()` = governance + working; `docs/archive` is DIRECTORY.
- Create module; `review.STANDARD_DELIVERABLES` becomes a derived alias;
  `config.DEFAULT_LEARN_TARGETS = list(learn_targets())`. Update `tests/test_config.py`
  expected list.

**A2. `markdown.py`** (R-CLS-3)
- Move `Section`, `iter_sections`, `normalize_heading`, `_HEADING_RE`, `_FENCE_RE` from
  `learn/apply.py`; re-export from `learn/apply.py` (existing `test_learn_apply.py`
  imports keep passing).
- Tests `tests/test_markdown.py`: `headings()` fence-aware; `heading_matches` (same level,
  prefix on normalized text, `<…>` wildcard, level mismatch fails); `missing_headings`
  one-to-one and order-insensitive; AC-2's rename/removal cases.

**A3. `identity.py` + variable resolution** (R-ID-1a/2/3)
- Tests `tests/test_identity.py`: round-trip write/read; bad JSON → None; fallback order
  README → pyproject → package.json → dir; hyphenated README title intact; `<Title>` /
  `{Problem description}` never used.
- `variables.collect_variables(created=...)`; move `project_variables` from
  `learn/collect.py` to `variables.py` (re-export in collect). `review.resolve_variables`
  keeps delegating.
- `universe.extract_title/extract_description` → identity/fallback; delete intent.md
  branches. Update `tests/test_universe.py` / `test_learn_collect.py` expectations that
  relied on intent.md (AC-6).

**A4. Placeholder warnings + render exclusions** (R-TPL-3, R-CLS-5)
- `templates.find_unknown_placeholders`; `render_template_tree(exclude=...)` returning
  `RenderReport(paths, warnings)`; update callers (`scaffold.py`, `review.deploy_entry`,
  `init`/seed paths untouched).
- Tests in `tests/test_templates.py` (AC-8 unit level).

### Phase B — metaproject behavior

**B1. Scaffold writes identity, skips on-demand** (R-ID-1, R-CLS-5)
- `scaffold_project`: `exclude` = on-demand paths; `write_identity` before
  `init_repository`, tracked by `TransactionalTracker`, skipped if present, listed in
  dry-run; return `warnings`.
- Tests `tests/test_scaffold.py`: identity fields (AC-5), rollback removes it, backfill
  keeps existing, no HANDOFF.md (AC-4), initial commit contains `.metaproject.json`
  (`tests/test_e2e.py`).

**B2. Review classes** (R-CLS-2…6, R-ID-4)
- `ReviewResult`: add `structure`, `notes`, `warnings`; `is_clean` includes `structure`;
  `from_mapping` accepts new keys.
- `review_project` iterates `DELIVERABLES`; working → `missing_headings`; identity note.
- `update_entry` raises for non-governance.
- Tests `tests/test_review.py`: AC-1, AC-2, AC-3, AC-4, AC-5 (fixed-clock via
  `monkeypatch` of `variables` date source, +1 day/+1 year), AC-5a; existing
  `test_review_scaffolded_project_reports_no_drift` and
  `test_deployed_files_do_not_immediately_report_as_drifted` must still pass.

**B3. `backfill_missing` + `metaproject backfill` CLI** (R-TPL-8)
- `review.backfill_missing` reusing `deploy_entry` and one `resolve_variables`.
- `cli.py` `backfill` command (`files`, `--dir/-d`, `--templates`, `--dry-run`), no agent
  guard, exit 1 on refusal/missing template.
- Tests `tests/test_backfill.py` via `CliRunner`: AC-10 (all-missing, HANDOFF by name,
  refuse existing writes nothing, `METAPROJECT_AGENT=1` still runs, dry-run, no git —
  assert `git.init_repository`/subprocess not called).

**B4. TUI + CLI surfaces**
- `review_tui.py`: drifted count = `diffs` + `structure`; working detail shows missing
  headings, no `u`. `cli.py` review prints notes/warnings; `new` prints warnings and
  "wrote .metaproject.json"; `new .` user-facing wording drops "backfill".
- Tests: extend `tests/test_review.py` board-render tests (non-TUI path).

### Phase C — metaproject learn

**C1. Structural evidence** (R-LRN-1, R-LRN-1b)
- `EvidenceRecord.removed_lines`; `collect_project` builds `kind="structure"` records for
  working targets; removal only from non-empty files; on-demand never collected.
- Tests `tests/test_learn_collect.py`: body text absent from records (AC-11 first half);
  empty/missing file → no removals.

**C2. `learn/structure.py` + api partition** (R-LRN-1a/1c, AC-11/11a)
- `structure.propose(records, weights, drift, min_evidence)`; `Config.learn.min_structure_evidence = 2`
  (`config.py`, `tests/test_config.py`).
- `api.scan` partitions before `guard_evidence`; `synth.bundle_evidence` ignores
  `structure`. Reuse `store.content_hash`, `score.weigh_project`, `upsert_proposal`.
- Tests `tests/test_learn_structure.py` + `tests/test_learn_synth.py`: fixture of 4
  projects — 3 remove `## Constraints` → one `remove_heading`; 2 add `## Risks` → one
  `add_heading` anchored after the most common shared heading; 1-project heading → no
  proposal; level change → remove + add; synth prompt for STATE.md has no body text; guard
  manifest excludes structural records. `no_model_ever` fixture stays autouse.

**C3. Apply heading proposals** (R-LRN-1a)
- `apply.plan_apply`: `add_heading` via `splice`; `remove_heading` via new `excise`;
  refuse removal when a child heading is still used by a contributor.
- Tests `tests/test_learn_apply.py`: insertion position, subtree excision, refusal, one
  commit per accept.

**C4. Drift signal for structure** (R-LRN-4)
- `drift.collect_drift` maps `result.structure` missing headings to removal keys.
- Tests `tests/test_learn_drift.py`: boost applies to removal, not addition; governance
  unchanged (AC-11a last clauses).

### Phase D — metaproject templates & docs

**D1. Templates** (R-TPL-1/2/4/5/6/7)
- Delete repo-root `templates/`. In `src/metaproject/templates/`: rewrite AGENTS, CLAUDE,
  README, STATE, HANDOFF, intent, `.gitignore`; add spec, design, plan, ARCHITECTURE,
  `docs.template/DESIGN-INVARIANTS.template.md`, `docs.template/VERIFIED-FACTS.template.md`,
  `docs.template/archive.template/.gitkeep`. AGENTS process section adapted from
  `SDLC-skills/AGENTS.md`.
- Tests `tests/test_bundled_templates.py` (R-NF-4, AC-7, AC-9): no unknown
  placeholders; every scaffolded deliverable has a template; cycle headers; blank rule;
  STATE 7 items; CLAUDE render with empty description has no double blank line;
  `.gitignore` has `.claude/worktrees/`; `new --dry-run` lists all R-TPL-4 files.
- Update `tests/test_scaffold.py:106`, `tests/test_review.py:702`, `test_e2e.py`
  expected file lists.

**D2. Skill docs + README** (R-DOC-1)
- `skill/SKILL.md`, `skill/references/documents.md`, `skill/references/commands.md`
  (`backfill` section), repo `README.md` (backfill section; rename "Backfilling a
  Directory…" heading to scaffold-into-existing wording), repo `AGENTS.md`.
- Test in `tests/test_skills.py`: AC-12a keyword coverage.

**D3. Discovery doc** (R-DOC-2)
- `docs/discovery/2026-09-04-learn-cycle-open-observations.md` copied verbatim from
  archived STATE.md's two sections, struck items marked "resolved in cycle";
  `docs/archive/2026-09-04-improve-learn-command/README.md` index + link. AC-12 checked by
  a small script in verification (not a pytest).

### Phase E — sdlc-skills (SK)

**E1. Hook + Makefile** (R-SK-2, R-NF-6/7)
- `hooks/hooks.json` (SessionStart → `${CLAUDE_PLUGIN_ROOT}/hooks/check-metaproject.sh`).
  Script: root = `$CLAUDE_PROJECT_DIR` if set, else `git rev-parse --show-toplevel`, else
  `pwd`; `command -v metaproject`; version from the `Version` line of
  `metaproject --version`, compared via `sort -V` with 0.7.0; `.metaproject.json`
  presence; silent on success, always exit 0.
- `tests/test_check_metaproject.sh` with stub `metaproject` executables on `PATH` (AC-14a
  cases incl. subdirectory and `git worktree`); `Makefile` `help` + `test`.

**E2. Skills** (R-SK-1…7)
- All 7 `skills/*/SKILL.md`: delete "Blank template" blocks; add identical preamble
  (session assumption, `metaproject backfill <file>`, blank rule, status/Approved by,
  tick STATE item N). wrapup process rewritten per R-SK-7; remove its inline
  ARCHITECTURE/long-lived templates; write-intent precondition uses blank rule.
- Also fix `write-intent` stray `(\`docs\`/\`AGENTS.md\`)`.

**E3. Repo docs + identity + version** (R-SK-8, R-REL-2)
- `README.md`, `AGENTS.md`: metaproject ≥ 0.7.0 required, owns templates, merge order.
- Root intent/spec/design/plan/STATE re-headed to new templates (intent mirror kept).
- `.claude-plugin/plugin.json` version `0.0.2`.
- `.metaproject.json`: **operator** runs `metaproject new .` in SK after agent shows
  `metaproject new . --dry-run` (needs MP branch installed: `uv tool install --force MP`
  — operator step, since it changes the PATH binary).

### Phase F — release (after merge, on `main`)
- Merge MP → `main`; on `main` run `make bump-version` (expect 0.7.0; if heuristic
  differs, operator decides) and update `tests/test_baseline.py`; operator refreshes
  `~/.metaproject/templates` by hand; then merge SK → `main`. Belongs to `wrapup`
  hand-off, listed here for sequencing.

## Files touched

MP new: `src/metaproject/{deliverables,markdown,identity}.py`,
`src/metaproject/learn/structure.py`, templates listed in D1, `docs/discovery/…`,
`docs/archive/2026-09-04-improve-learn-command/README.md`, tests
`test_{deliverables,markdown,identity,backfill,learn_structure,bundled_templates}.py`.
MP changed: `variables.py`, `universe.py`, `templates.py`, `scaffold.py`, `review.py`,
`review_tui.py`, `cli.py`, `config.py`, `learn/{collect,api,apply,drift,synth}.py`,
`skill/SKILL.md`, `skill/references/{documents,commands}.md`, `README.md`, `AGENTS.md`,
existing tests noted per step. MP deleted: `templates/`.
SK new: `hooks/hooks.json`, `hooks/check-metaproject.sh`, `tests/test_check_metaproject.sh`,
`Makefile`, `.metaproject.json` (operator). SK changed: `skills/*/SKILL.md`, `README.md`,
`AGENTS.md`, root cycle docs, `.claude-plugin/plugin.json`.

## Sequencing

A1 → A2 → A3 → A4 → B1 → B2 → B3 → B4 → C1 → C2 → C3 → C4 → D1 → D2 → D3 → E1 → E2 → E3 → F.
- A before B/C: classes, headings, identity are shared.
- B2 before C4 (drift reads `structure`); C1 before C2 before C3.
- D1 after B/C so template tests exercise final behavior; D1 before E (skills reference
  templates that must exist).
- E3's `.metaproject.json` needs MP installed from the branch.
- F only after `execute-tests` and operator confirmation.

## Risks / rollback

- Each step is one commit on the branch; revert per step. Nothing touches `main`,
  `~/.metaproject/`, or other projects until Phase F.
- Moved helpers (`project_variables`, heading helpers) keep re-exports to avoid breaking
  imports mid-sequence.
- Template rewrite (D1) changes review results for fixtures; failing expectations are
  updated deliberately in the same commit, not loosened.
- Hook script is read-only and exits 0 always; a bug degrades to a missing/incorrect
  notice, never a blocked session.
- Installing the branch build globally (E3) replaces the operator's `metaproject`; revert
  with `uv tool install --force ~/Projects/metaproject` from `main`.

## Verification plan

- MP: `make format && make lint && make test` green after every step (AC-16); acceptance
  tests named per step map to AC-1…AC-12a.
- MP end-to-end in a temp dir: `metaproject new demo --yes --no-git`; fill cycle docs
  keeping headings → `metaproject review demo --no-tui` CLEAN; delete spec.md/STATE.md →
  `metaproject backfill --dir demo` recreates; re-run refuses named existing file;
  `CLAUDECODE=1 metaproject backfill --dry-run --dir demo` runs.
- AC-12: `rg -c` the discovery doc against archived STATE.md bullet count.
- SK: `make test` (AC-14a), `rg -n '^```markdown' skills/*/SKILL.md` empty (AC-13),
  review each SKILL.md preamble (AC-14), `claude plugin validate` or install from SK and
  confirm 7 skills + SessionStart notice in a scratch project without
  `.metaproject.json` (AC-15, R-NF-6).
- AC-15: `metaproject review` on SK (branch build) shows no working-document drift.
- AC-16a (post-merge): `git tag --points-at main` = `v0.7.0`.
