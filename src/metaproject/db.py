"""SQLite persistence, WAL configuration, project cataloging, and reconciliation queries."""

from pathlib import Path
from typing import Any, Dict, List, Optional

import sqlite_utils

from metaproject.config import DEFAULT_UNIVERSE_DB, load_config
from metaproject.exceptions import ScannerError


def get_default_db_path() -> Path:
    """Resolve default path to universe.db from config or default location."""
    try:
        cfg = load_config()
        return Path(cfg.universe_db).resolve()
    except Exception:
        return DEFAULT_UNIVERSE_DB.resolve()


def get_db(db_path: Optional[str | Path] = None) -> sqlite_utils.Database:
    """Connect to SQLite database with WAL mode and busy timeout configured."""
    target_path = Path(db_path).expanduser().resolve() if db_path else get_default_db_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite_utils.Database(target_path)
    # Configure WAL mode and busy timeout for high concurrency & reliability
    db.conn.execute("PRAGMA journal_mode=WAL;")
    db.conn.execute("PRAGMA busy_timeout=5000;")
    init_schema(db)
    return db


def init_schema(db: sqlite_utils.Database) -> None:
    """Ensure projects table and indexing exist per spec.md §5.5."""
    if "projects" not in db.table_names():
        db["projects"].create(
            {
                "id": int,
                "name": str,
                "path": str,
                "relative_path": str,
                "title": str,
                "description": str,
                "last_modified": str,
                "last_modified_ts": float,
                "classification": str,
                "is_git": int,
                "git_branch": str,
                "has_agents_md": int,
                "has_intent_md": int,
                "has_state_md": int,
                "has_handoff_md": int,
                "has_readme_md": int,
                "scanned_at": str,
                "scan_root": str,
                "missing_since": str,
            },
            pk="id",
            not_null={
                "name",
                "path",
                "relative_path",
                "last_modified",
                "last_modified_ts",
                "classification",
                "is_git",
                "scanned_at",
                "scan_root",
            },
        )
        # Create indices
        db["projects"].create_index(["path"], unique=True)
        db["projects"].create_index(["classification"])
        db["projects"].create_index(["last_modified_ts"])
        db["projects"].create_index(["scan_root"])
    else:
        # Ensure unique index exists on path
        try:
            db["projects"].create_index(["path"], unique=True, if_not_exists=True)
            db["projects"].create_index(["classification"], if_not_exists=True)
            db["projects"].create_index(["last_modified_ts"], if_not_exists=True)
            db["projects"].create_index(["scan_root"], if_not_exists=True)
        except Exception:
            pass

    if "learn_proposals" not in db.table_names():
        db["learn_proposals"].create(
            {
                "id": int,
                "content_hash": str,
                "target_file": str,
                "template_path": str,
                "kind": str,
                "title": str,
                "rationale": str,
                "proposed_body": str,
                "edited_body": str,
                "target_section": str,
                "evidence_count": int,
                "evidence_score": float,
                "status": str,
                "rejected_score": float,
                "created_at": str,
                "updated_at": str,
                "applied_commit": str,
            },
            pk="id",
        )
        db["learn_proposals"].create_index(["content_hash"], unique=True)
        db["learn_proposals"].create_index(["status", "evidence_score"])
        db["learn_proposals"].create_index(["target_file"])
    else:
        try:
            db["learn_proposals"].create_index(["content_hash"], unique=True, if_not_exists=True)
            db["learn_proposals"].create_index(["status", "evidence_score"], if_not_exists=True)
            db["learn_proposals"].create_index(["target_file"], if_not_exists=True)
        except Exception:
            pass

    if "learn_evidence" not in db.table_names():
        db["learn_evidence"].create(
            {
                "id": int,
                "proposal_id": int,
                "project_id": int,
                "project_path": str,
                "excerpt": str,
                "weight": float,
            },
            pk="id",
        )
        db["learn_evidence"].create_index(["proposal_id"])
    else:
        try:
            db["learn_evidence"].create_index(["proposal_id"], if_not_exists=True)
        except Exception:
            pass

    if "learn_runs" not in db.table_names():
        db["learn_runs"].create(
            {
                "id": int,
                "started_at": str,
                "finished_at": str,
                "root": str,
                "projects_scanned": int,
                "files_scanned": int,
                "model": str,
                "proposals_created": int,
                "status": str,
            },
            pk="id",
        )


def upsert_project(db: sqlite_utils.Database, record: Dict[str, Any]) -> None:
    """Upsert project record using path as unique key."""
    try:
        cleaned_record = dict(record)
        cleaned_record["missing_since"] = None
        # Remove id if None or not set so autoincrement handles it
        if "id" in cleaned_record and cleaned_record["id"] is None:
            del cleaned_record["id"]

        columns = list(cleaned_record.keys())
        placeholders = ", ".join("?" for _ in columns)
        update_clause = ", ".join(
            f'"{col}" = excluded."{col}"' for col in columns if col not in {"id", "path"}
        )
        quoted_cols = ", ".join(f'"{c}"' for c in columns)

        sql = f"""
        INSERT INTO "projects" ({quoted_cols})
        VALUES ({placeholders})
        ON CONFLICT("path") DO UPDATE SET {update_clause};
        """
        db.conn.execute(sql, [cleaned_record[col] for col in columns])
        db.conn.commit()
    except Exception as exc:
        raise ScannerError(f"Failed to upsert project record: {exc}") from exc


def reconcile_missing_projects(
    db: sqlite_utils.Database,
    scan_root: str,
    scan_start_time: str,
) -> int:
    """Mark records under scan_root not seen in the current scan as missing_since.

    Returns the number of projects marked missing.
    """
    cursor = db.conn.cursor()
    cursor.execute(
        """
        UPDATE projects
        SET missing_since = CURRENT_TIMESTAMP
        WHERE scan_root = ?
          AND scanned_at < ?
          AND missing_since IS NULL
        """,
        (str(scan_root), str(scan_start_time)),
    )
    db.conn.commit()
    return cursor.rowcount


def query_projects(
    db: sqlite_utils.Database,
    path_prefix: Optional[str] = None,
    classification: Optional[str] = None,
    include_missing: bool = False,
) -> List[Dict[str, Any]]:
    """Query cataloged projects with optional path prefix and classification filter."""
    where_clauses: List[str] = []
    params: List[Any] = []

    if not include_missing:
        where_clauses.append("missing_since IS NULL")

    if classification:
        where_clauses.append("classification = ?")
        params.append(classification)

    if path_prefix:
        norm_prefix = str(Path(path_prefix).expanduser().resolve())
        where_clauses.append("(path = ? OR path LIKE ? OR scan_root = ?)")
        params.extend([norm_prefix, f"{norm_prefix}/%", norm_prefix])

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    query = f"SELECT * FROM projects {where_sql} ORDER BY last_modified_ts DESC"

    cursor = db.conn.cursor()
    cursor.execute(query, params)
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_universe_summary(db: sqlite_utils.Database) -> Dict[str, Any]:
    """Compute status summary metrics for the universe database."""
    if "projects" not in db.table_names():
        return {
            "total_projects": 0,
            "active_now": 0,
            "last_run": "Never",
            "missing_projects": 0,
        }

    cursor = db.conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM projects WHERE missing_since IS NULL")
    total_projects = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM projects "
        "WHERE classification = 'Active Now' AND missing_since IS NULL"
    )
    active_now = cursor.fetchone()[0]

    cursor.execute("SELECT MAX(scanned_at) FROM projects")
    row = cursor.fetchone()
    last_run = row[0] if (row and row[0]) else "Never"

    cursor.execute("SELECT COUNT(*) FROM projects WHERE missing_since IS NOT NULL")
    missing_projects = cursor.fetchone()[0]

    return {
        "total_projects": total_projects,
        "active_now": active_now,
        "last_run": last_run,
        "missing_projects": missing_projects,
    }
