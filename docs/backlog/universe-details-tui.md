# Universe: hard-scope to project_home + interactive details TUI

**Captured**: 2026-09-15, backlog-new brainstorm session
**Status**: backlog — not specced, not scheduled.
**Target**: MetaProject (`src/metaproject/cli.py` `universe` command, `src/metaproject/universe.py`, new TUI module)

## Goal

Make `metaproject universe` trustworthy about *where* it operates and useful for
*inspecting* projects. Today it scans from wherever the user happens to be (cwd),
which risks cataloging directories outside the real projects root, and its output is
a static table that answers "what projects exist" but nothing about their current
state. Users should get an interactive view they can navigate to per-project detail:
git status, recent log, worktrees, metaproject version.

## Current behavior (verified 2026-09-15)

- `config.py:81` defines `project_home` (default `~/Projects`, normalized on load,
  already persisted in config.json) — but `universe_cmd` in `cli.py` ignores it:
  `start_path = Path(target_dir) if target_dir else Path.cwd()`. Scan root is cwd
  or an arbitrary positional path; nothing ties scanning to `project_home`.
- Output is a static rich table (or json/csv via `--format`); `--list` skips
  scanning, `--summary` prints DB stats. No interactivity.
- `universe.db` stores classification (Active Now / Archived / …), last-seen, and
  missing-project reconciliation. No git status, git log, worktree, or metaproject
  version data per project.
- Existing TUI precedent: the `learn` acceptance TUI (`learn/tui.py`) is a rich
  keystroke loop, deliberately not a widget framework. Textual is **not** currently
  a dependency.

## Proposed direction

Two changes, decided in this session:

1. **Hard-scope to `project_home` (single source of truth).**
   - Default scan root becomes the configured `project_home`, never cwd.
   - An explicit positional directory is allowed only if it resolves *inside*
     `project_home`; otherwise error (or warn-and-refuse) rather than scanning.
   - Single root only — no multiple-roots support foreseen.
   - Universe performs operations only on this main projects directory containing
     the individual projects.

2. **Interactive Textual TUI as the default interface.**
   - `metaproject universe` (no args) opens a Textual app: arrow between project
     rows, select a project to open a details view.
   - Today's static table moves behind `--list` / `--format table|json|csv` for
     scripting; summary flag unchanged.
   - Textual becomes a new dependency (accepted decision — richer scrolling/panes
     than the rich keystroke-loop approach used by `learn`).
   - **Details data is fetched live on selection** (option 1 from the session):
     git status (brief), most recent git log, worktrees (active vs stale),
     metaproject version — via subprocess at selection time, possibly with a small
     in-session cache. `universe.db` keeps only what it already stores; no git
     state persisted at scan time.

Rationale: git status and worktree state are exactly the things that must be
current when inspected, so live-on-selection beats scan-time capture despite the
per-selection subprocess cost.

## Open questions

- Nested details ("details of details"): should a worktree row inside a project's
  details view itself be selectable for its own detail? Only worth building if
  there's enough to show — decide in spec.
- Definition of a "stale" worktree (age threshold? ahead/behind? uncommitted
  changes?).
- Should `--summary` / scanning still run automatically on TUI open, or does the
  TUI read the DB and offer an explicit refresh action?
- Any actions from the TUI (open in editor, `cd` hint, run `review`) or is it
  read-only for v1?
- Textual version pinning and whether the TUI lives in a new module (e.g.
  `universe_tui.py`) alongside the learn TUI precedent.
