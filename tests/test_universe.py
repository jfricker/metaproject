"""Tests for universe cataloger, activity classification, SQLite persistence, and reconciliation."""

import time
from pathlib import Path

from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.db import get_db, query_projects, reconcile_missing_projects, upsert_project
from metaproject.universe import (
    classify_project,
    is_archived_path,
    is_project_root,
    scan_universe,
)


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


def test_scan_universe_and_cli(runner: CliRunner, tmp_path: Path) -> None:
    """Verify universe scanning across a directory tree and CLI invocation."""
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
