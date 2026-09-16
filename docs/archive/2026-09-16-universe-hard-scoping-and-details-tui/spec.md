# Universe hard scoping and details TUI — Spec

**Author**: John Fricker.
**Derived from**: intent.md (2026-09-15).
**Last updated**: 2026-09-15.
**Status**: Approved.
**Approved by**: John Fricker (2026-09-15).

## Requirements

Requirement IDs use `R-UNV-<n>`. Design-level choices (staleness scoring weights,
Textual widget layout, module internals) are left to `design.md`.

### Functional

**R-UNV-1 — Scan root hard-scoped to `project_home`.**
- `metaproject universe` with no positional directory scans from the configured
  `project_home` (`config.py`), never `Path.cwd()`. `project_home` is the single
  source of truth for where universe operates.
- A positional directory is accepted only if, after `expanduser().resolve()`, it
  equals `project_home` or lies inside it. Anything outside (including `..`-escapes
  and symlinked aliases that resolve outside) is refused: exit non-zero, with an
  error naming the configured `project_home` so the operator sees the boundary.
- `--all` keeps its current meaning: DB-wide listing across all workspaces (it does
  not widen the *scan* root, only the output scope).
- `--summary` (and the `summary` positional word) behave exactly as today; the scan
  restriction does not apply to them.
- `--depth` continues to bound traversal from the (now fixed) root.

**R-UNV-2 — Interactive TUI is the default interface.**
- With no args and a TTY, `metaproject universe` opens a Textual app
  (`src/metaproject/universe_tui.py`): a project list drawn from `universe.db`
  (same `query_projects` scoping rules as the table view — `--filter` still applies
  via flag), keyboard navigation between rows, and selection opens a details view.
- Details are fetched **live at selection time** via bounded subprocess calls —
  never read from `universe.db`:
  1. brief git status (short format),
  2. the most recent commit line (hash + subject),
  3. worktrees with a staleness verdict (see R-UNV-3),
  4. the metaproject version recorded in the project's own metaproject metadata
     (`.metaproject.json`), or "unknown" when absent.
- A small in-session cache may serve repeat selections of the same project; the
  explicit refresh action (R-UNV-2g) invalidates it.
- The TUI **never scans on open**. It reads `universe.db` and offers an explicit
  refresh action that re-runs the scan (into `project_home`, per R-UNV-1) and
  reloads the list.
- The TUI is **read-only**: no writes to disk or DB, no editor launch, no `cd`, no
  `review` run. Keys that would act are absent, not stubbed.
- Worktree rows inside a project's details view are themselves selectable and open
  their own detail view (branch, path, age, ahead/behind, uncommitted state).

**R-UNV-3 — Staleness verdict for worktrees.**
- Staleness is a score over three signals: worktree age, commits behind its base
  branch, and uncommitted changes. Exact weights/thresholds are a `design.md`
  decision; the spec fixes only the contract: each worktree renders as active or
  stale, and **uncommitted changes always raise a separate awareness flag
  regardless of the score**.
- A worktree whose base branch cannot be determined (detached/unknown) degrades to
  a neutral verdict, not an error.

**R-UNV-4 — Scripting surfaces preserved.**
- `--list`, `--format table|json|csv`, `--summary`, `--quiet`, `--filter`,
  `--show-missing`, `--db` keep their current behavior and output shape. The static
  table remains what those flags print. The only behavior change outside the TUI is
  R-UNV-1's scan-root restriction.

**R-UNV-5 — Degradation.**
- The TUI does not open, and the static table prints instead (exit 0), when any of:
  `--no-tui`, output is not a TTY, `TERM=dumb`, or an agent session is detected
  (`session.py`), matching the `learn` reviewer's `tui_enabled` seam so all four
  triggers stay independently testable.

**R-UNV-6 — Git call failures degrade, never crash.**
- A project without git shows a "no git" detail section. A git subprocess that
  errors or exceeds its timeout renders a placeholder for that field only; the TUI
  and the process survive. Timeouts are bounded (single-digit seconds per call).

**R-UNV-7 — `universe.db` unchanged.**
- No schema changes; no git/worktree/version state is persisted at scan time. The
  TUI's live data is fetched on selection (with at most the in-session cache).

### Non-functional

- **Dependency**: Textual is added to `pyproject.toml` with an exact pin; no other
  new runtime dependencies. The `learn` and `review` TUIs are not migrated.
- **Testability**: TUI gating and degradation follow the `learn/tui.py` seam
  pattern (`tui_enabled`) so pytest can exercise every trigger; no test spawns a
  real Textual app for logic covered by pure functions.
- **Sandbox/test constraints** (from `docs/VERIFIED-FACTS.md`): tests must run with
  a `--basetemp` containing no `claude` path segment; git-writing tests run
  unsandboxed.
- **Quality gate**: `make format && make lint && make test` must pass; new module
  passes `ruff`.
- **NO_COLOR / piped output**: the degraded table must be legible without color,
  per the `review` board precedent.

## Acceptance criteria

1. Running `metaproject universe` from a directory outside `project_home` (no
   positional arg) scans `project_home` — the printed scan root is `project_home`,
   not cwd.
2. `metaproject universe /tmp` (or any path resolving outside `project_home`)
   exits non-zero with an error naming `project_home`; nothing is scanned or
   written to the DB.
3. `metaproject universe <subdir-of-project_home>` still works, and scopes output
   to that subdir as today.
4. With a TTY, `metaproject universe` opens the Textual app; arrow keys move
   selection, Enter opens the details view, Escape/Back returns to the list.
5. A details view shows: brief status, latest commit, worktrees (each labeled
   active or stale), and metaproject version — and re-fetches on selection (a
   git-state change made between opening the TUI and selecting is visible).
6. A worktree with uncommitted changes shows the awareness flag even when its age
   and behind-count would score it active.
7. Selecting a worktree row opens its detail view.
8. Opening the TUI does not modify `universe.db` mtime/content; the refresh key
   does re-scan and update the list.
9. The TUI performs no writes: running it (browse, select, close) leaves the
   project trees and `universe.db` byte-identical apart from the explicit refresh.
10. Each degradation trigger (`--no-tui`, piped stdout, `TERM=dumb`, agent-session
    env) prints the static table and exits 0.
11. `--list --format json` and `--format csv` output schemas are unchanged from
    today (field names and shapes).
12. A non-git project in the catalog opens a details view with a "no git"
    section; a simulated git failure (e.g. `GIT_DIR` pointing nowhere) yields a
    placeholder field, not a traceback.
13. `pytest` passes with the documented basetemp constraint; TUI gating is covered
    by unit tests of the `tui_enabled`-style seam for all four triggers.

## Flagged concerns

(all resolved 2026-09-15 by the product owner, John Fricker)

1. **Behavior change for existing muscle memory** — **Accepted** (owner decision
   2026-09-15): `metaproject universe` refusing positional paths outside
   `project_home` is the intent; no `--force-root` escape hatch.
2. **Textual pin** — **Accepted** (owner decision 2026-09-15): exact version
   chosen at implementation time (current stable).

## Open questions

(none — all intent questions resolved 2026-09-15; staleness weights and TUI
layout are deliberately deferred to `design.md`)
