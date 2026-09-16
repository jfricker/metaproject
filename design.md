# Universe hard scoping and details TUI — Design

**Author**: John Fricker.
**Derived from**: spec.md (2026-09-15).
**Last updated**: 2026-09-16.
**Status**: Approved.
**Approved by**: John Fricker (2026-09-16) — TUI mockup (`universe-tui-mockup.html`) and design approved together.

## Affected components

- **`src/metaproject/cli.py` — `universe_cmd`** (modified): scan-root resolution via
  `universe.resolve_scan_root`; new `--no-tui` flag; TUI branch replaces the default
  table branch when `tui_enabled` passes and no display/format flag forces text.
  `--list`/`--format`/`--summary`/`--quiet`/`--filter` code paths unchanged.
- **`src/metaproject/universe.py`** (modified): new `resolve_scan_root(target_dir,
  project_home) -> Path` raising `UniverseScopeError` (message names `project_home`);
  nothing else about scanning changes.
- **`src/metaproject/gitinfo.py`** (new): subprocess-based project inspection, no
  Textual import. Dataclasses `WorktreeInfo` (path, branch, head_age_days,
  behind_count, uncommitted_count, stale: bool, flag: bool) and `ProjectDetails`
  (status_short, last_commit, worktrees: list[WorktreeInfo], metaproject_version).
  Functions: `inspect_project(path, base_branch=None) -> ProjectDetails` and
  `inspect_worktree(info) -> WorktreeInfo` (detail-of-detail), each git call bounded
  by a `GIT_TIMEOUT_S = 5` per-call timeout; failures yield `None`/placeholder
  fields, never exceptions past the boundary.
- **`src/metaproject/universe_tui.py`** (new): the Textual app. Screens:
  `UniverseListScreen` (DataTable of projects), `ProjectDetailScreen`,
  `WorktreeDetailScreen`. Key bindings: arrows/j-k navigate, Enter select,
  Escape/BackSpace back, `r` refresh, `q` quit. No writes anywhere — the app holds
  no `db` write handles; refresh re-runs `scan_universe(project_home, …)` through
  the same call the CLI uses, then re-queries.
- **`pyproject.toml`** (modified): `textual==<pinned current stable>` added to
  dependencies; nothing else added.
- **`universe.db`** (unchanged): no schema or query-shape changes; `query_projects`
  consumed as today.

## Data flow / interfaces

1. **CLI → scope check**: `universe_cmd` loads config, calls
   `resolve_scan_root(target_dir, project_home)`. Error → print message, `raise
   typer.Exit(1)`. Success → `start_path` as today.
2. **CLI → TUI gate**: default invocation (no `--list`, no `--format` override, no
   `--summary`, not `--quiet`) passes `tui_enabled(no_tui=…)` — the existing seam in
   `learn/tui.py`, already shared with `review`. Fails → existing table path.
3. **TUI list**: opens with `query_projects(db, path_prefix=str(project_home),
   classification=filter, include_missing=False)`. No scan on open.
4. **Selection → details**: row select calls `gitinfo.inspect_project` in a worker
   (Textual `@work`), renders sections; results cached in a dict on the app keyed
   by project path; `r` clears the cache, re-scans, re-queries, redraws.
5. **Worktree selection**: the worktree row's `WorktreeInfo` feeds
   `inspect_worktree` for the detail-of-detail view (branch, path, age, ahead /
   behind, uncommitted file count).
6. **Staleness scoring** (in `gitinfo.py`, one `STALENESS` table at module top):
   - age of HEAD's last commit: `<7d`→0, `<30d`→1, `≥30d`→2
   - behind base branch (`rev-list --count HEAD..<base>`): `0`→0, `≤5`→1, `>5`→2
   - uncommitted (`status --porcelain` non-empty): contributes **0** to the score
     but always sets `flag=True`
   - verdict: `stale = score ≥ 3` (`active` otherwise); `flag` renders as a
     separate ⚠ marker, never folded into the verdict.
   - undeterminable base (detached HEAD, unknown branch): behind counts as 0, verdict
     from age only, marked neutral in the detail view.
   - base branch per worktree: the branch it tracks (from `worktree list --porcelain`
     + `rev-parse @{upstream}`), falling back to the project's default branch.

## Alternatives considered

- **Rich keystroke loop (learn TUI style)** — rejected: spec already decided
  Textual; three stacked screens (list → detail → worktree detail) need scrolling
  panes and workers a hand-rolled loop doesn't give for free.
- **Git inspection inside `universe_tui.py`** — rejected: spec's testability NFR
  wants the subprocess logic unit-testable without importing Textual;
  `gitinfo.py` keeps that boundary (mirrors how `review.py`/`review_tui.py` split).
- **Persisting git state at scan time into `universe.db`** — rejected by spec
  (R-UNV-7): status/behind are exactly the fields that go stale between scans.
- **Scanning on TUI open** — rejected by spec: DB-read + explicit refresh keeps
  open instant and makes the refresh action the single scan trigger in interactive
  use.
- **`--force-root` escape hatch** — rejected by owner: the restriction *is* the
  intent.

## Trade-offs and risks

- **Per-selection subprocess cost** (~3-6 git calls, each ≤5s worst case): accepted
  by spec; the in-session cache covers reselections. Risk: large worktree lists in
  one project — bounded because calls are per-selection, not per-scan.
- **New dependency (Textual)**: pins a fast-moving library; exact pin (not range)
  keeps upgrades deliberate. Risk of API drift addressed by pinning.
- **Behavior break** (refusing roots outside `project_home`): accepted by owner;
  error message is the mitigation (names the boundary).
- **Symlink escapes**: `resolve()` before the inside-check closes the classic
  `~/Projects/link → /elsewhere` hole; the check runs on the resolved path only.
- **`tui_enabled` import from `learn/tui.py`**: continues the existing `review`
  precedent; if it ever needs moving, that's a mechanical relocation, not a
  redesign.

## Open questions

(none — spec approved with all concerns resolved; staleness thresholds above are
the design's concrete proposal, adjustable at plan review)
