"""Tests for universe cataloger, activity classification, SQLite persistence, and reconciliation."""

import json
import os
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.db import (
    get_db,
    get_universe_summary,
    query_projects,
    reconcile_missing_projects,
    upsert_project,
)
from metaproject.universe import (
    UniverseScopeError,
    classify_project,
    is_archived_path,
    is_project_root,
    resolve_scan_root,
    scan_universe,
)


def write_project_home(home: Path) -> None:
    """Point the test config's project_home at a fixture root (R-UNV-1 scoping)."""
    config_dir = Path(os.environ["METAPROJECT_CONFIG_DIR"])
    config_dir.mkdir(parents=True, exist_ok=True)
    config = json.dumps({"project_home": str(home)})
    (config_dir / "config.json").write_text(config, encoding="utf-8")


def test_is_project_root(tmp_path: Path) -> None:
    """Verify boundary detection heuristics."""
    generic_dir = tmp_path / "generic"
    generic_dir.mkdir()
    assert is_project_root(generic_dir) is False

    # With .git
    (generic_dir / ".git").mkdir()
    assert is_project_root(generic_dir) is True

    # With AGENTS.md
    sdlc_dir = tmp_path / "sdlc"
    sdlc_dir.mkdir()
    (sdlc_dir / "AGENTS.md").write_text("# Agents", encoding="utf-8")
    assert is_project_root(sdlc_dir) is True

    # With pyproject.toml
    python_dir = tmp_path / "python_pkg"
    python_dir.mkdir()
    (python_dir / "pyproject.toml").write_text("[project]", encoding="utf-8")
    assert is_project_root(python_dir) is True


def test_is_archived_path() -> None:
    """Verify Archive path detection."""
    assert is_archived_path(Path("/Users/dev/Archive/old_proj")) is True
    assert is_archived_path(Path("/Users/dev/archive/old_proj")) is True
    assert is_archived_path(Path("/Users/dev/Projects/Archive")) is True
    assert is_archived_path(Path("/Users/dev/Projects/active_proj")) is False


def test_classify_project_rules(tmp_path: Path) -> None:
    """Verify precedence of Archive rule and exact recency tiers."""
    now_ts = time.time()

    # 1. Archive precedence rule
    archive_dir = tmp_path / "Archive" / "super_recent"
    archive_dir.mkdir(parents=True)
    # Even if modified 5 minutes ago, archive precedence classifies as Archived
    assert classify_project(archive_dir, now_ts - 300) == "Archived"

    # 2. Active Now (<= 2 days)
    recent_dir = tmp_path / "recent"
    recent_dir.mkdir()
    assert classify_project(recent_dir, now_ts - 3600) == "Active Now"
    assert classify_project(recent_dir, now_ts - (1.5 * 86400)) == "Active Now"

    # 3. Active Near (> 2 days, <= 7 days)
    assert classify_project(recent_dir, now_ts - (4 * 86400)) == "Active Near"

    # 4. Active Far (> 7 days, <= 30 days)
    assert classify_project(recent_dir, now_ts - (14 * 86400)) == "Active Far"

    # 5. Idle (> 30 days, <= 180 days)
    assert classify_project(recent_dir, now_ts - (60 * 86400)) == "Idle"

    # 6. Ancient (> 180 days)
    assert classify_project(recent_dir, now_ts - (200 * 86400)) == "Ancient"


def test_sqlite_db_and_reconciliation(tmp_path: Path) -> None:
    """Verify SQLite WAL mode, upsert, and reconciliation pass for missing projects."""
    db_file = tmp_path / "test_universe.db"
    db = get_db(db_file)

    # Verify WAL journal mode
    res = db.conn.execute("PRAGMA journal_mode;").fetchone()
    assert res[0].lower() == "wal"

    # Insert a project record
    record1 = {
        "name": "project_one",
        "path": "/path/to/project_one",
        "relative_path": "project_one",
        "title": "Project One",
        "description": "First project",
        "last_modified": "2026-09-01T12:00:00Z",
        "last_modified_ts": 1725192000.0,
        "classification": "Active Now",
        "is_git": 1,
        "git_branch": "main",
        "has_agents_md": 1,
        "has_intent_md": 1,
        "has_state_md": 1,
        "has_handoff_md": 0,
        "has_readme_md": 1,
        "scanned_at": "2026-09-01T12:00:00Z",
        "scan_root": "/path/to",
    }
    upsert_project(db, record1)

    projects = query_projects(db)
    assert len(projects) == 1
    assert projects[0]["name"] == "project_one"
    assert projects[0]["missing_since"] is None

    # Run reconciliation pass with newer scan time: project_one should be marked missing
    later_time = "2026-09-02T12:00:00Z"
    marked_count = reconcile_missing_projects(db, "/path/to", later_time)
    assert marked_count == 1

    # Normal query excludes missing
    assert len(query_projects(db, include_missing=False)) == 0

    # Query with include_missing=True returns the project
    missing_projects = query_projects(db, include_missing=True)
    assert len(missing_projects) == 1
    assert missing_projects[0]["missing_since"] is not None


def test_resolve_scan_root_rules(tmp_path: Path) -> None:
    """Verify the hard scoping of the universe scan root to project_home (R-UNV-1)."""
    home = tmp_path / "Projects"
    home.mkdir()
    sub = home / "proj"
    sub.mkdir()

    # No target scans project_home itself
    assert resolve_scan_root(None, home) == home.resolve()
    # Equal and inside targets are accepted
    assert resolve_scan_root(str(home), home) == home.resolve()
    assert resolve_scan_root(str(sub), home) == sub.resolve()
    # ..-escapes that stay inside resolve to a real inside path
    assert resolve_scan_root(str(home / ".." / "Projects" / "proj"), home) == sub.resolve()

    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(UniverseScopeError):
        resolve_scan_root(str(outside), home)

    # A symlinked alias resolving outside is refused, not followed
    link = tmp_path / "link"
    link.symlink_to(outside)
    with pytest.raises(UniverseScopeError):
        resolve_scan_root(str(link), home)


def test_cli_universe_defaults_to_project_home(runner: CliRunner, tmp_path: Path) -> None:
    """With no positional directory the scan root is project_home, not cwd (R-UNV-1)."""
    home = tmp_path / "Projects"
    home.mkdir()
    proj = home / "in_proj"
    proj.mkdir()
    (proj / ".git").mkdir()
    (proj / "README.md").write_text("# Home Project\nLives in project_home", encoding="utf-8")
    write_project_home(home)

    db_path = tmp_path / "universe.db"
    result = runner.invoke(app, ["universe", "--db", str(db_path), "--format", "json"])
    assert result.exit_code == 0
    # Rich may wrap long fixture paths, so compare with the wrap newlines removed
    unwrapped = result.output.replace("\n", "")
    # The printed scan root is project_home even though cwd is elsewhere
    assert f"Scanning universe from: {home.resolve()}" in unwrapped
    assert "Home Project" in result.output


def test_cli_universe_refuses_outside_project_home(runner: CliRunner, tmp_path: Path) -> None:
    """A target outside project_home exits non-zero, names the boundary, writes nothing."""
    home = tmp_path / "Projects"
    home.mkdir()
    write_project_home(home)

    outside = tmp_path / "elsewhere"
    outside.mkdir()
    db_path = tmp_path / "universe.db"

    result = runner.invoke(app, ["universe", str(outside), "--db", str(db_path)])
    assert result.exit_code == 1
    assert "Refusing to scan" in result.output
    # The error names the project_home boundary (long fixture paths may be wrapped)
    assert str(home.resolve()) in result.output.replace("\n", "")
    # Nothing was scanned or written to the DB
    assert not db_path.exists()


def test_scan_universe_and_cli(runner: CliRunner, tmp_path: Path) -> None:
    """Verify universe scanning across a directory tree and CLI invocation."""
    write_project_home(tmp_path)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    # Project 1: active git repo
    proj1 = workspace_root / "proj_alpha"
    proj1.mkdir()
    (proj1 / ".git").mkdir()
    (proj1 / "README.md").write_text("# Project Alpha\nAlpha description", encoding="utf-8")

    # Project 2: archived project
    archive_parent = workspace_root / "Archive"
    archive_parent.mkdir()
    proj2 = archive_parent / "proj_legacy"
    proj2.mkdir()
    (proj2 / "pyproject.toml").write_text("[project]\nname='legacy'", encoding="utf-8")

    # Generic subfolder without project indicator (should not be cataloged)
    (workspace_root / "some_random_folder").mkdir()

    db_path = tmp_path / "universe.db"
    db = get_db(db_path)

    discovered = scan_universe(workspace_root, max_depth=3, interactive=False, db=db)
    assert len(discovered) == 2

    # CLI verification
    result = runner.invoke(
        app,
        [
            "universe",
            str(workspace_root),
            "--db",
            str(db_path),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0
    assert "Project Alpha" in result.output
    assert "proj_legacy" in result.output
    assert "Archived" in result.output


def test_universe_path_scoping_and_single_project(runner: CliRunner, tmp_path: Path) -> None:
    """Verify that universe scopes query results to target_dir and catalogs single project roots."""
    write_project_home(tmp_path)
    db_path = tmp_path / "universe.db"
    db = get_db(db_path)

    # Insert an external project into the db
    upsert_project(
        db,
        {
            "name": "external_proj",
            "path": str(tmp_path / "external_proj"),
            "relative_path": ".",
            "title": "External Project",
            "description": "Not in target dir",
            "last_modified": "2026-09-02T12:00:00Z",
            "last_modified_ts": time.time(),
            "classification": "Active Now",
            "is_git": 1,
            "git_branch": "main",
            "has_agents_md": 1,
            "has_intent_md": 1,
            "has_state_md": 1,
            "has_handoff_md": 1,
            "has_readme_md": 1,
            "scanned_at": "2026-09-02T12:00:00Z",
            "scan_root": str(tmp_path / "external_proj"),
        },
    )

    # Create target project that is directly scanned
    target_proj = tmp_path / "my_target_project"
    target_proj.mkdir()
    (target_proj / ".git").mkdir()
    (target_proj / "README.md").write_text("# Target Project\nScoped project", encoding="utf-8")

    # Run universe with path parameter pointing directly to target_proj
    result = runner.invoke(
        app,
        [
            "universe",
            str(target_proj),
            "--db",
            str(db_path),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0
    assert "Target Project" in result.output
    # Must NOT include the external project
    assert "external_proj" not in result.output

    # Run universe with --all and verify external project is included
    all_result = runner.invoke(
        app,
        [
            "universe",
            str(target_proj),
            "--db",
            str(db_path),
            "--all",
            "--format",
            "json",
        ],
    )
    assert all_result.exit_code == 0
    assert "Target Project" in all_result.output
    assert "external_proj" in all_result.output


def test_get_universe_summary(tmp_path: Path) -> None:
    """Verify get_universe_summary metric calculations."""
    db_path = tmp_path / "test_summary.db"
    db = get_db(db_path)

    # Empty database
    empty_summary = get_universe_summary(db)
    assert empty_summary["total_projects"] == 0
    assert empty_summary["active_now"] == 0
    assert empty_summary["last_run"] == "Never"
    assert empty_summary["missing_projects"] == 0

    # Add active now project
    upsert_project(
        db,
        {
            "name": "active_proj",
            "path": str(tmp_path / "active_proj"),
            "relative_path": "active_proj",
            "title": "Active Project",
            "description": "Active desc",
            "last_modified": "2026-09-03T10:00:00Z",
            "last_modified_ts": time.time(),
            "classification": "Active Now",
            "is_git": 1,
            "git_branch": "main",
            "has_agents_md": 1,
            "has_intent_md": 1,
            "has_state_md": 1,
            "has_handoff_md": 1,
            "has_readme_md": 1,
            "scanned_at": "2026-09-03T10:00:00Z",
            "scan_root": str(tmp_path),
        },
    )
    # Add idle project
    upsert_project(
        db,
        {
            "name": "idle_proj",
            "path": str(tmp_path / "idle_proj"),
            "relative_path": "idle_proj",
            "title": "Idle Project",
            "description": "Idle desc",
            "last_modified": "2026-08-01T10:00:00Z",
            "last_modified_ts": time.time() - 3600 * 24 * 40,
            "classification": "Idle",
            "is_git": 0,
            "git_branch": None,
            "has_agents_md": 0,
            "has_intent_md": 0,
            "has_state_md": 0,
            "has_handoff_md": 0,
            "has_readme_md": 1,
            "scanned_at": "2026-09-03T10:05:00Z",
            "scan_root": str(tmp_path),
        },
    )

    populated_summary = get_universe_summary(db)
    assert populated_summary["total_projects"] == 2
    assert populated_summary["active_now"] == 1
    assert populated_summary["last_run"] == "2026-09-03T10:05:00Z"
    assert populated_summary["missing_projects"] == 0


def test_cli_universe_summary(runner: CliRunner, tmp_path: Path) -> None:
    """Verify running 'metaproject universe summary' through CLI."""
    import json

    db_path = tmp_path / "summary_cli.db"
    db = get_db(db_path)

    upsert_project(
        db,
        {
            "name": "super_proj",
            "path": str(tmp_path / "super_proj"),
            "relative_path": "super_proj",
            "title": "Super Project",
            "description": "Super desc",
            "last_modified": "2026-09-03T10:00:00Z",
            "last_modified_ts": time.time(),
            "classification": "Active Now",
            "is_git": 1,
            "git_branch": "main",
            "has_agents_md": 1,
            "has_intent_md": 1,
            "has_state_md": 1,
            "has_handoff_md": 1,
            "has_readme_md": 1,
            "scanned_at": "2026-09-03T10:00:00Z",
            "scan_root": str(tmp_path),
        },
    )

    # 1. Summary command 2-line format
    res = runner.invoke(app, ["universe", "summary", "--db", str(db_path)])
    assert res.exit_code == 0
    lines = [line.strip() for line in res.output.strip().splitlines() if line.strip()]
    assert len(lines) == 2
    assert "Universe DB status" in lines[0]
    assert "1 projects" in lines[0]
    assert "1 active now" in lines[0]
    assert "Last update to the db: 2026-09-03T10:00:00Z" in lines[1]

    # 2. Summary command json format
    res_json = runner.invoke(app, ["universe", "summary", "--db", str(db_path), "--format", "json"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.output)
    assert data["total_projects"] == 1
    assert data["active_now"] == 1
    assert data["last_run"] == "2026-09-03T10:00:00Z"

    # 3. Via --summary flag
    res_flag = runner.invoke(app, ["universe", "--summary", "--db", str(db_path)])
    assert res_flag.exit_code == 0
    flag_lines = [line.strip() for line in res_flag.output.strip().splitlines() if line.strip()]
    assert len(flag_lines) == 2
    assert "1 projects" in flag_lines[0]
    assert "Last update to the db" in flag_lines[1]


def test_is_project_root_recognises_both_intent_locations(tmp_path: Path) -> None:
    """R-DOC-6: `docs/INTENT.md` is a marker, and an unmigrated root `intent.md` still is."""
    migrated = tmp_path / "migrated"
    (migrated / "docs").mkdir(parents=True)
    (migrated / "docs" / "INTENT.md").write_text("# x", encoding="utf-8")
    assert is_project_root(migrated) is True

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "intent.md").write_text("# x", encoding="utf-8")
    assert is_project_root(legacy) is True


def test_has_doc_columns_count_either_location(tmp_path: Path) -> None:
    """`has_*_md` is true for the `docs/` path or the legacy root name (R-DOC-3)."""
    root = tmp_path / "ws"
    migrated = root / "migrated"
    (migrated / "docs").mkdir(parents=True)
    for name in ("INTENT.md", "STATE.md", "HANDOFF.md"):
        (migrated / "docs" / name).write_text("# x", encoding="utf-8")
    legacy = root / "legacy"
    legacy.mkdir()
    for name in ("intent.md", "STATE.md"):
        (legacy / name).write_text("# x", encoding="utf-8")

    records = {
        r["name"]: r
        for r in scan_universe(root, max_depth=2, interactive=False, db=get_db(tmp_path / "u.db"))
    }
    assert records["migrated"]["has_intent_md"] == 1
    assert records["migrated"]["has_state_md"] == 1
    assert records["migrated"]["has_handoff_md"] == 1
    assert records["legacy"]["has_intent_md"] == 1
    assert records["legacy"]["has_state_md"] == 1
    assert records["legacy"]["has_handoff_md"] == 0
