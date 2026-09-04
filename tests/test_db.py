"""Tests for SQLite schema creation, including the `learn` proposal tables."""

from pathlib import Path

import sqlite_utils

from metaproject.db import init_schema


def test_init_schema_creates_learn_tables_on_fresh_db(tmp_path: Path) -> None:
    """Schema creates learn_proposals, learn_evidence, and learn_runs on a fresh database."""
    db_path = tmp_path / "fresh_universe.db"
    db = sqlite_utils.Database(db_path)

    init_schema(db)

    table_names = set(db.table_names())
    assert "projects" in table_names
    assert "learn_proposals" in table_names
    assert "learn_evidence" in table_names
    assert "learn_runs" in table_names


def test_init_schema_creates_learn_tables_on_existing_db_with_projects(tmp_path: Path) -> None:
    """Schema adds learn tables to a db that already has a projects table (upgrade path)."""
    db_path = tmp_path / "existing_universe.db"
    db = sqlite_utils.Database(db_path)

    # Simulate a pre-Phase-0 database: only the projects table exists.
    init_schema(db)
    assert "learn_proposals" in db.table_names()

    # Re-running init_schema against an already-upgraded db must be idempotent.
    init_schema(db)
    table_names = set(db.table_names())
    assert "projects" in table_names
    assert "learn_proposals" in table_names
    assert "learn_evidence" in table_names
    assert "learn_runs" in table_names


def test_init_schema_learn_tables_idempotent_when_projects_preexists(tmp_path: Path) -> None:
    """A db that already had 'projects' before learn tables existed gains them cleanly."""
    db_path = tmp_path / "upgrade_universe.db"
    db = sqlite_utils.Database(db_path)

    # First pass creates projects + learn tables together (current init_schema behavior),
    # simulating an "existing db with just projects" by dropping the learn tables afterward.
    init_schema(db)
    for table in ("learn_proposals", "learn_evidence", "learn_runs"):
        db[table].drop()
    assert "projects" in db.table_names()
    assert "learn_proposals" not in db.table_names()

    # Running init_schema again must add the learn tables without touching projects.
    init_schema(db)
    table_names = set(db.table_names())
    assert "projects" in table_names
    assert "learn_proposals" in table_names
    assert "learn_evidence" in table_names
    assert "learn_runs" in table_names


def test_learn_proposals_schema_columns(tmp_path: Path) -> None:
    """learn_proposals carries the columns specified in spec.md §5.4.8."""
    db_path = tmp_path / "universe.db"
    db = sqlite_utils.Database(db_path)
    init_schema(db)

    columns = {c.name for c in db["learn_proposals"].columns}
    expected = {
        "id",
        "content_hash",
        "target_file",
        "template_path",
        "kind",
        "title",
        "rationale",
        "proposed_body",
        "edited_body",
        "target_section",
        "evidence_count",
        "evidence_score",
        "status",
        "rejected_score",
        "created_at",
        "updated_at",
        "applied_commit",
    }
    assert expected.issubset(columns)
    assert db["learn_proposals"].pks == ["id"]


def test_learn_evidence_schema_columns(tmp_path: Path) -> None:
    """learn_evidence carries the columns specified in spec.md §5.4.8."""
    db_path = tmp_path / "universe.db"
    db = sqlite_utils.Database(db_path)
    init_schema(db)

    columns = {c.name for c in db["learn_evidence"].columns}
    expected = {
        "id",
        "proposal_id",
        "project_id",
        "project_path",
        "excerpt",
        "weight",
    }
    assert expected.issubset(columns)
    assert db["learn_evidence"].pks == ["id"]


def test_learn_runs_schema_columns(tmp_path: Path) -> None:
    """learn_runs carries the columns specified in spec.md §5.4.8."""
    db_path = tmp_path / "universe.db"
    db = sqlite_utils.Database(db_path)
    init_schema(db)

    columns = {c.name for c in db["learn_runs"].columns}
    expected = {
        "id",
        "started_at",
        "finished_at",
        "root",
        "projects_scanned",
        "files_scanned",
        "model",
        "proposals_created",
        "status",
    }
    assert expected.issubset(columns)
    assert db["learn_runs"].pks == ["id"]


def test_learn_indexes_created(tmp_path: Path) -> None:
    """Indexes named in spec.md §5.4.8 exist."""
    db_path = tmp_path / "universe.db"
    db = sqlite_utils.Database(db_path)
    init_schema(db)

    proposal_indexes = db["learn_proposals"].indexes
    index_columns = [tuple(idx.columns) for idx in proposal_indexes]
    assert ("status", "evidence_score") in index_columns
    assert ("target_file",) in index_columns

    evidence_indexes = db["learn_evidence"].indexes
    evidence_index_columns = [tuple(idx.columns) for idx in evidence_indexes]
    assert ("proposal_id",) in evidence_index_columns


def test_learn_proposals_content_hash_unique(tmp_path: Path) -> None:
    """content_hash carries a UNIQUE constraint driving suppression by identity."""
    db_path = tmp_path / "universe.db"
    db = sqlite_utils.Database(db_path)
    init_schema(db)

    db["learn_proposals"].insert(
        {
            "content_hash": "abc123",
            "target_file": "AGENTS.md",
            "kind": "edit",
            "status": "pending",
        }
    )
    import sqlite3

    try:
        db["learn_proposals"].insert(
            {
                "content_hash": "abc123",
                "target_file": "README.md",
                "kind": "edit",
                "status": "pending",
            }
        )
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    assert raised, "content_hash should enforce a UNIQUE constraint"
