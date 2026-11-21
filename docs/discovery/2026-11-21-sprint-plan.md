# Sprint plan — 2026-11-21 (quick sprint, ~3–4 days)

**Status:** Draft — awaiting operator approval. Nothing implemented.

## Inputs

| Item | State | Size |
|---|---|---|
| #27 Add ToDo.md template | `docs.template/TODO.template.md` already exists (manual-verification log only). Missing: the **Carry over** section. | S |
| #26 Rename `docs/` → `.metaproject.docs/` | ~650 `docs/` references across 29 src/test files, plus skills, templates, hook scripts (stdlib path walk), `deliverables.LEGACY_NAMES`, doctor migration. A full cycle, not a sprint item. | L |
| #12 Skills & hooks review | Review done ([artifact](https://claude.ai/artifact/AV6DMyaL4Dk4hMUY7EGHc7)); 60 findings, only R1 resolved (`3cecd2e`). Rest undecided. | — |
| PR #2 `learn scan` per-file confirm | Untouched since 2026-09-13, mergeable state unknown, +366/−29. | — |
| `main` | 3 commits ahead of `origin/main`, unpushed. | — |

## Sprint goal

Make the hooks safe, make the cycle skills internally consistent, close #27, and get #26 to an approved INTENT.

## Backlog (priority order)

### 0. Housekeeping — operator, day 1
- Push `main` (`f99876c`).
- PR #2: rebase and merge, or close. Stale for two months.

### 1. Hooks safety — #12 H1, H2, H3, H9 (M)
Track A. Files: `hook_scripts/metaproject_hook.py`, `hooks.py`, tests.
- H1: match only `playwright test|show-report` (or `commands.e2e`), not any mention.
- H2: kill only listeners whose cwd is inside the project root; otherwise advise with PID/cmdline.
- H3: require adjacent `playwright install`; lock older than 10 min is stale.
- H9: atomic `settings.json` write (`os.replace`, `ensure_ascii=False`).
- Done: regression test per case; gate green.

### 2. Cycle-skill contradictions — #12 S1, S2, S3, S4, S5, S7, S8, S9, S10, S11 (M)
Track B. Files: `sdlc_skills/*/SKILL.md`, `skill/`, `STATE.template.md`, `skill_history.json`.
- S1 backfill PLAN.md after ExitPlanMode; S2/S3 implement-plan & execute-tests write STATE.md sections and phase checklist; S4 wrapup ticks item 7; S5 name the PR owner; S7 backlog-factory runs only shipit's cleanup step; S8/S9 shipit gates merge/push and remote branch delete; S10/S11 fix metaproject skill read-only list and `commands.md` gaps.
- Done: `make skill-history`, `metaproject skills sync` on this repo, gate green.

### 3. #27 TODO.md Carry over section (S) — after item 2 (shares `wrapup/SKILL.md`, `skill_history.json`)
- Add a `## Carry over` section to `TODO.template.md` above the append log.
- wrapup's "carry forward" open-item option appends there (dated, with cycle slug).
- Done: template test updated; wrapup skill text updated; gate green.

### 4. #26 write-intent only (S) — any time
- `/write-intent` for the rename. Open questions to settle: hidden dir vs. configurable `docs_dir` in `.metaproject.json`; doctor migration path reusing `LEGACY_NAMES`; impact on hook/session scripts and agents reading `docs/`.
- Implementation is next sprint.

### Stretch — #12 M1 (block force-push / `--no-verify` / `gh pr merge --admin`)
Track A after item 1 (same hook script).

## Parallelism

- Track A (items 1 → stretch) and Track B (items 2 → 3) touch disjoint files and can run in separate worktrees.
- Item 4 is docs-only, independent.

## Out of sprint
#12 remaining moves (M2–M11), improvements (H5–H11, I1–I19), nits — triage in the review artifact first. #26 implementation.

## Decisions needed
1. Accept the #12 subset above as the sprint's scope (default: verified bugs + S3/S5)?
2. PR #2: merge or close?
3. #26: confirm intent-only this sprint.
