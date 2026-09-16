# Universe hard scoping and details TUI — Implementation Plan

**Author**: John Fricker.
**Derived from**: spec.md, design.md (2026-09-16).
**Last updated**: 2026-09-16.
**Status**: Approved.
**Approved by**: John Fricker (2026-09-16).

## Context

`metaproject universe` ignores the configured `project_home` (it scans cwd or an
arbitrary positional path) and its output is a static table with no way to inspect a
project's live state. This cycle hard-scopes the scan root to `project_home` and adds
a read-only Textual TUI (list → project detail → worktree detail) that fetches git
state live at selection time. Work happens in the cycle worktree
(`.claude/worktrees/universe-details-tui`, branch `universe-details-tui`).

## Steps

### 1. Scan-root hard scoping (R-UNV-1) — `universe.py`, `cli.py`, `tests/test_universe.py`

- Add to `src/metaproject/universe.py`:
  - `class UniverseScopeError(Exception)` whose message names the configured
    `project_home`.
  - `resolve_scan_root(target_dir: str | None, project_home: str | Path) -> Path`
    — `None` → `Path(project_home)`; a `target_dir` is `expanduser().resolve()`d
    and accepted only if it equals `project_home` or lies inside it (checked on the
    resolved path only, closing the symlink-escape hole); otherwise raise
    `UniverseScopeError`.
- `src/metaproject/cli.py` `universe_cmd` (~line 809): replace
  `start_path = (Path(target_dir) if target_dir else Path.cwd()).expanduser().resolve()`
  with a call to `resolve_scan_root(target_dir, cfg.project_home)` (cfg already
  loaded at line 758). Catch `UniverseScopeError` → print the error,
  `raise typer.Exit(1)`. The check runs **before** `get_db`/`scan_universe` so a
  refused path scans and writes nothing. Update the argument help text.
- Summary mode: untouched — it returns before start_path resolution today.
- Tests (`tests/test_universe.py`): unit tests for `resolve_scan_root` (None → home;
  equal; subdir; outside; `..`-escape; symlink resolving outside via `tmp_path`) and
  CLI tests: refusal exits 1 with `project_home` named and DB untouched; subdir
  still scopes output.
- **Existing-test fallout**: CLI tests invoke `universe` with tmp paths that now sit
  outside the default `project_home`. Set `project_home` to the fixture workspace
  root via the tmp `METAPROJECT_CONFIG_DIR` conftest already creates, and update
  `test_universe_path_scoping_and_single_project` etc. to the new contract.

### 2. Dependency — `pyproject.toml`

- Add `textual==<current stable at implementation time>` (exact pin, owner decision
  2026-09-15) to dependencies; nothing else added. Install into the worktree
  `.venv` with unsandboxed `uv` (per docs/VERIFIED-FACTS.md).

### 3. `src/metaproject/gitinfo.py` (new, R-UNV-3/6) — no Textual import

- `GIT_TIMEOUT_S = 5`; private `_git(path, *args) -> str | None`:
  `subprocess.run(["git", "-C", path, *args], capture_output=True, text=True,
  timeout=GIT_TIMEOUT_S, check=False)` wrapped in `try/except
  (TimeoutExpired, OSError)` → `None` (style mirrors `git.py:54-100`; timeout
  precedent is `learn/synth.run_claude`).
- `STALENESS` scoring table at module top, per design.md: age `<7d`→0 `<30d`→1
  `≥30d`→2; behind `0`→0 `≤5`→1 `>5`→2; uncommitted contributes 0 but always sets
  `flag=True`; `stale = score ≥ 3`; undeterminable base → behind 0, verdict from
  age only, `neutral=True`.
- Dataclasses: `WorktreeInfo(path, branch, head_age_days, behind_count,
  uncommitted_count, stale: bool, flag: bool, neutral: bool = False)` and
  `ProjectDetails(status_short, last_commit, worktrees: list[WorktreeInfo],
  metaproject_version)`.
- `score_worktree(head_age_days, behind_count, has_uncommitted, base_known=True)`
  as a **pure function** (the unit-test surface; no subprocess needed for scoring).
- `inspect_project(path, base_branch=None) -> ProjectDetails`:
  `status --porcelain` (short status + uncommitted count), `log -1 --format=%h %s`
  (last commit), `worktree list --porcelain` (worktrees; per-worktree base branch
  from its tracked upstream via `rev-parse @{upstream}`, falling back to the
  project default branch via `symbolic-ref refs/remotes/origin/HEAD`, then `main`),
  `rev-list --count HEAD..<base>`, `log -1 --format=%ct` (age). Version read from
  the project's own `.metaproject.json` (verify the exact version key as shipped by
  the doctor cycle; "unknown" when absent or unparsable).
- `inspect_worktree(info) -> WorktreeInfo` (detail-of-detail refresh) plus small
  helpers the worktree screen reuses: `uncommitted_files(path) -> list[str]` and
  `last_commit(path) -> str | None`.
- Non-git or failing git → placeholder fields (`None` / "no git"), never an
  exception past this module's boundary.

### 4. `src/metaproject/universe_tui.py` (new, R-UNV-2/5) — the Textual app

- Three screens per the approved mockup (`universe-tui-mockup.html`):
  - `UniverseListScreen` — DataTable with the same columns as the static table
    (Classification / Project / Path / Last Modified / Git / SDLC), rows from
    `query_projects(db, path_prefix=str(project_home), classification=filter,
    include_missing=False)`. **No scan on open** (the mockup's git-branch column is
    fed from the DB's `git_branch`, never a subprocess).
  - `ProjectDetailScreen` — sections: Status (short), Last commit, Worktrees table
    (Branch / Age / Behind / Uncommitted ⚠ / Verdict), Metaproject version. Details
    fetched live via `gitinfo.inspect_project` inside a Textual `@work` worker;
    results cached in a dict on the app keyed by project path.
  - `WorktreeDetailScreen` — branch, path, age, ahead/behind, verdict + visible
    score line, uncommitted file list, last commit (via `inspect_worktree` +
    the `gitinfo` helpers).
- Bindings: `↑↓/j/k` navigate, `Enter` select, `Escape/Backspace` back, `r`
  refresh (clears cache, re-runs `scan_universe(project_home, …)` — the same call
  the CLI uses — then re-queries), `q` quit.
- Read-only: the app holds no DB write handles; no editor, no `cd`, no review run.
- Entry point `run_tui(...)` called by the CLI; keep screen-content builders
  (row construction, verdict labels, score line) as pure functions importable
  without instantiating the app, for unit tests.

### 5. CLI wiring (R-UNV-2/4/5) — `cli.py`

- Add `no_tui: bool = typer.Option(False, "--no-tui", ...)` to `universe_cmd`
  (same wording as `review`'s flag, line 908).
- Default invocation (no `--list`, no `--format` override from `table`, no
  `--summary`, not `--quiet`) with `tui_enabled(no_tui=no_tui)` true → open the TUI
  **instead of** the current scan-then-table flow (the TUI never scans on open).
- Otherwise the existing behavior is preserved unchanged: table path still scans
  then prints (this is also the degraded output for all four triggers), and
  `--list/--format/--summary/--quiet/--filter/--show-missing/--db/--all/--depth`
  keep today's shapes. Reuse `tui_enabled` from `learn/tui.py` and
  `print_agent_degradation_notice` (cli.py:201) as `review` does (lines 981-989).
- Textual is imported lazily inside the TUI branch so degradation never imports it.

### 6. Tests — `tests/test_gitinfo.py` (new), `tests/test_universe_tui.py` (new)

- **gitinfo**: real git fixtures mirroring `tests/fixtures/learn_workspace/build.py`'s
  `_git` helper (a repo, a second worktree, an old commit via `GIT_AUTHOR_DATE`/
  `GIT_COMMITTER_DATE`, dirty file for the flag, detached HEAD for the neutral
  case). Pure `score_worktree` table tests; `inspect_project` happy path;
  degradation (nonexistent path / `GIT_DIR` pointing nowhere → placeholders, no
  raise).
- **universe TUI gating**: all four triggers via `CliRunner` — `--no-tui`, piped
  stdout (CliRunner is inherently non-TTY), `TERM=dumb`, agent env — each prints
  the static table and exits 0. Screen-content pure functions unit-tested without
  launching Textual; `run_tui` itself is exercised only through the gate mock, per
  the "no test spawns a real Textual app" NFR.
- Reuse conftest's `runner` fixture and `METAPROJECT_CONFIG_DIR` tmp config
  (conftest pins `METAPROJECT_AGENT=0`).

## Files touched

- `src/metaproject/universe.py` (modified — `UniverseScopeError`, `resolve_scan_root`)
- `src/metaproject/cli.py` (modified — `universe_cmd` scope check, `--no-tui`, TUI branch)
- `src/metaproject/gitinfo.py` (new)
- `src/metaproject/universe_tui.py` (new)
- `pyproject.toml` (modified — exact `textual` pin)
- `tests/test_universe.py` (modified), `tests/test_gitinfo.py` (new),
  `tests/test_universe_tui.py` (new)
- STATE.md (process ticks as steps land)

## Sequencing

1 → 2 can land together; 3 is independent of 2; 4 depends on 2+3; 5 depends on 1-4;
6 is written alongside each step (step-wise, not at the end). Quality gate at the
end: `make format && make lint && make test`.

## Risks / rollback

- **Worktree + sandbox test traps** (docs/VERIFIED-FACTS.md): run the suite with
  `--basetemp=/private/tmp/mp-gate-<lane>` (no `claude` path segment anywhere) and
  unsandboxed for git-writing tests; `uv` commands unsandboxed.
- **Existing universe CLI tests break** with the scope change — expected and
  handled in step 1; each updated assertion maps to an R-UNV requirement.
- **Textual API drift** — mitigated by the exact pin; pin chosen at implementation.
- **`.metaproject.json` version key** — verify the actual key shipped by the doctor
  cycle before wiring; absent file → "unknown" (already the contract).
- Rollback: each step is a small commit on `universe-details-tui`; the scope check
  and the TUI branch are independently revertible.

## Acceptance mapping

Spec criteria 1-3 → step 1 tests; 4-9 → steps 3-5 (TUI behavior, live fetch, flag,
read-only); 10 → step 6 gating tests; 11 → untouched format paths (no changes
shipped there); 12 → gitinfo degradation tests; 13 → gate run with the documented
basetemp constraint plus the four-trigger seam tests.

## Verification plan

- `make format && make lint && make test` green (basetemp + unsandboxed per above).
- Manual: from `~/` run `metaproject universe` (degraded table, scans
  `project_home`), `metaproject universe /tmp` (exit 1, boundary named),
  `metaproject universe` in a real TTY (browse → detail → worktree detail → `r`
  refresh → `q`), confirming no `universe.db` writes without refresh and no writes
  to project trees at all.
