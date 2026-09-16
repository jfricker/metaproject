# Universe hard scoping and details TUI

**Author**: John Fricker.
**Last updated**: 2026-09-15.
**Status**: Approved.
**Approved by**: John Fricker (2026-09-15).

## Problem

`metaproject universe` is untrustworthy about *where* it operates and of no use for
*inspecting* projects. The configured `project_home` (`config.py:81`, default
`~/Projects`, normalized on load and persisted in `config.json`) is ignored by
`universe_cmd`: the scan root is the current working directory or an arbitrary
positional path (`cli.py:809`), so a scan can catalog directories far outside the
real projects root depending on where the operator happens to be standing. And the
output is a static table (or json/csv): it answers "what projects exist" but says
nothing about their current state — git status, recent activity, worktrees, or the
metaproject version a project was scaffolded with. `universe.db` stores
classification and last-seen data only.

## Proposed outcome

Once this cycle ships:

- `metaproject universe` always operates on the configured `project_home` — the
  single source of truth for where projects live. The default scan root is
  `project_home`, never cwd; an explicit positional directory is accepted only if
  it resolves *inside* `project_home`, and refused (with a clear error) otherwise.
- With no args, `metaproject universe` opens an interactive Textual TUI: navigate
  between project rows, select a project to open a details view showing git status
  (brief), the most recent git log entry, worktrees (active vs stale), and the
  metaproject version — all fetched live at selection time.
- Scripting surfaces are preserved: today's static table moves behind `--list` /
  `--format table|json|csv`; `--summary` behaves as today.

## Affected users and systems

- Operators of `metaproject universe` (interactive inspection workflow is new).
- `src/metaproject/cli.py` (`universe_cmd` and its flags), `src/metaproject/universe.py`
  (scan-root contract), and a new TUI module alongside the `learn` TUI precedent
  (e.g. `src/metaproject/universe_tui.py`).
- New dependency: Textual. The `learn` TUI stays a rich keystroke loop — it is not
  migrated.
- `universe.db` is unchanged: no git state is persisted at scan time; details are
  read live on selection.

## Scope

### In Scope (v1)

- Hard-scoping `universe` to `project_home`: default root = `project_home`;
  positional directories allowed only inside it; clear error when refused.
- Textual TUI as the default interface (`metaproject universe`, no args): project
  list → per-project details view (git status brief, latest log line, worktrees
  active vs stale, metaproject version), fetched live via subprocess on selection,
  with a small in-session cache if needed.
- Nested details: a worktree row inside a project's details view is itself
  selectable and opens its own detail view.
- Keeping `--list` / `--format` and `--summary` as the non-interactive path.
- A definition of "stale" worktree sufficient to label rows active vs stale.
- No-TTY / `TERM=dumb` / `--no-tui` degradation consistent with the `review` and
  `learn` TUI precedents (printed table, header included).

### Out of Scope (v1)

- Multiple scan roots.
- Persisting git/worktree state into `universe.db` at scan time.
- Migrating the `learn` or `review` TUIs to Textual.
- Mutating actions from the TUI (open in editor, running `review`, writes of any
  kind) — v1 is read-only.

## Resolved decisions

- **`project_home` is the single source of truth** for the scan root (decided in the
  2026-09-15 backlog session): scanning wherever cwd happens to be is the defect.
- **Textual over a rich keystroke loop** for this TUI: richer scrolling/panes are
  needed for the list→details flow; accepted as a new dependency.
- **Live-on-selection details** (option 1 in the backlog session): git status and
  worktree state must be current when inspected, so fetch at selection time despite
  per-selection subprocess cost; `universe.db` keeps only what it already stores.
- **Stale worktree = a score over three signals** (decided 2026-09-15): worktree age,
  how far behind its base branch it is, and uncommitted changes. The exact scoring
  weights and thresholds are a spec decision, but uncommitted changes always raise a
  flag for awareness regardless of the staleness score.
- **TUI reads the DB; refresh is explicit** (decided 2026-09-15): opening the TUI
  does not scan. It reads `universe.db` and offers an explicit refresh action; the
  non-interactive path scans as today.
- **Read-only for v1** (decided 2026-09-15): no actions from the TUI — no open in
  editor, no `cd` hint, no run `review`, no writes of any kind.
- **Module and pin confirmed** (decided 2026-09-15): the TUI lives in
  `src/metaproject/universe_tui.py` alongside the learn TUI precedent; Textual is
  pinned in `pyproject.toml` (exact version chosen at spec/implementation time).
- **Nested details are in** (decided 2026-09-15): a worktree row inside a project's
  details view is itself selectable and opens its own detail view.

## Constraints

- Python 3.11+, Typer/Rich CLI conventions; Textual joins as the one new TUI
  dependency.
- TUI degradation rules (no TTY, `TERM=dumb`, `--no-tui`, agent-session guard via
  `session.py`) must match the existing `review`/`learn` precedent.
- Textual version pinned in `pyproject.toml`.
- Tests must run with a `--basetemp` containing no `claude` path segment and
  git-writing tests unsandboxed (see `docs/VERIFIED-FACTS.md`).

## Open questions

(none — all resolved 2026-09-15, see Resolved decisions)

1. ~~Nested details~~ — **Resolved 2026-09-15**: worktree rows are selectable and
   open their own detail view.
2. ~~Definition of "stale" worktree~~ — **Resolved 2026-09-15**: staleness scored from
   age + distance behind + uncommitted changes; uncommitted changes always raise an
   awareness flag. Exact weights/thresholds land in spec.
3. ~~Scan on TUI open~~ — **Resolved 2026-09-15**: the TUI reads `universe.db` and
   offers an explicit refresh action; no scan on open.
4. ~~TUI actions~~ — **Resolved 2026-09-15**: read-only for v1.
5. ~~Textual pin + module location~~ — **Resolved 2026-09-15**: `universe_tui.py`
   alongside the learn TUI; Textual pinned in `pyproject.toml`.
