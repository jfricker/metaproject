"""Workspace scanner, boundary heuristics, activity classifier, and metadata extractor."""

import datetime
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import questionary
import sqlite_utils

from metaproject.db import get_db, reconcile_missing_projects, upsert_project
from metaproject.git import (
    get_current_branch,
    get_last_commit_timestamp,
    has_uncommitted_changes,
    is_git_repository,
)
from metaproject.identity import fallback_identity, read_identity

IGNORED_DIRECTORIES = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    "build",
    "__pycache__",
    ".gemini",
    ".cargo",
    ".idea",
    ".vscode",
}

PROJECT_MANIFESTS = {
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "Makefile",
}


class UniverseScopeError(Exception):
    """A requested scan root lies outside the configured `project_home` (R-UNV-1)."""


def resolve_scan_root(target_dir: Optional[str], project_home: str | Path) -> Path:
    """Hard-scope the universe scan root to `project_home` (R-UNV-1).

    No target scans `project_home` itself. A target is accepted only if, after
    `expanduser().resolve()`, it equals `project_home` or lies inside it — the
    check runs on the resolved path so a symlinked alias pointing outside is
    refused, not followed.
    """
    home = Path(project_home).expanduser().resolve()
    if target_dir is None:
        return home
    resolved = Path(target_dir).expanduser().resolve()
    if resolved == home or home in resolved.parents:
        return resolved
    raise UniverseScopeError(
        f"{resolved} is outside project_home ({home}). "
        "metaproject universe only scans inside the configured project_home."
    )


def is_project_root(path: Path) -> bool:
    """Determine if a directory represents a project root boundary."""
    if not path.is_dir():
        return False

    # 1. Git repository root
    if (path / ".git").exists():
        return True

    # 2. SDLC root indicators. Root `intent.md` stays a marker so an unmigrated project
    # is still recognised (R-DOC-6).
    for marker in ("AGENTS.md", "docs/INTENT.md", "intent.md"):
        if (path / marker).exists():
            return True

    # 3. Standard build/package manifests
    for manifest in PROJECT_MANIFESTS:
        if (path / manifest).exists():
            return True

    return False


def _has_doc(project_dir: Path, *locations: str) -> int:
    """1 when a cycle document exists at its `docs/` path or its legacy root name."""
    return 1 if any((project_dir / rel).exists() for rel in locations) else 0


def is_archived_path(path: Path) -> bool:
    """Check if any folder in the path hierarchy is named 'Archive' or 'archive'."""
    for part in path.parts:
        if part.lower() == "archive":
            return True
    return False


def extract_title(project_dir: Path) -> str:
    """Extract project title: `.metaproject.json` first, else manifest fallback (R-ID-3).

    `docs/INTENT.md` is never consulted and a hyphenated title is never truncated.
    """
    identity = read_identity(project_dir)
    if identity is not None:
        return identity.title
    title, _description = fallback_identity(project_dir)
    return title


def extract_description(project_dir: Path) -> str:
    """Extract project description: `.metaproject.json` first, else manifest fallback.

    `docs/INTENT.md` is never consulted (R-ID-3).
    """
    identity = read_identity(project_dir)
    if identity is not None:
        return identity.description
    _title, description = fallback_identity(project_dir)
    return description


def get_newest_mtime_in_dir(path: Path, max_files: int = 500) -> float:
    """Find maximum mtime among non-ignored files within a directory."""
    newest = 0.0
    count = 0
    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRECTORIES]
            for file in files:
                file_path = Path(root) / file
                try:
                    mtime = file_path.stat().st_mtime
                    if mtime > newest:
                        newest = mtime
                except Exception:
                    pass
                count += 1
                if count >= max_files:
                    return newest
    except Exception:
        pass
    return newest or path.stat().st_mtime


def resolve_project_timestamp(project_dir: Path) -> Tuple[str, float]:
    """Resolve last modified ISO 8601 string and POSIX timestamp float."""
    if is_git_repository(project_dir):
        # If uncommitted modifications exist, working tree mtime is newer
        if has_uncommitted_changes(project_dir):
            mtime = get_newest_mtime_in_dir(project_dir)
            iso = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc).isoformat()
            return iso, mtime

        # Clean git repo: use commit timestamp
        commit_iso = get_last_commit_timestamp(project_dir)
        if commit_iso:
            try:
                dt = datetime.datetime.fromisoformat(commit_iso)
                return commit_iso, dt.timestamp()
            except Exception:
                pass

    # Non-git directory
    mtime = get_newest_mtime_in_dir(project_dir)
    iso = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc).isoformat()
    return iso, mtime


def classify_project(
    project_dir: Path,
    last_modified_ts: float,
    interactive: bool = False,
) -> str:
    """Classify project based on Archive precedence rule and recency thresholds."""
    # Precedence rule: Archive path
    if is_archived_path(project_dir):
        if interactive:
            confirm = questionary.confirm(
                f"Path '{project_dir.name}' contains 'Archive'. Classify as Archived?",
                default=True,
            ).ask()
            if confirm:
                return "Archived"
        else:
            return "Archived"

    now_ts = time.time()
    diff_seconds = max(0.0, now_ts - last_modified_ts)
    days = diff_seconds / 86400.0

    if days <= 2.0:
        return "Active Now"
    if days <= 7.0:
        return "Active Near"
    if days <= 30.0:
        return "Active Far"
    if days <= 180.0:
        return "Idle"
    return "Ancient"


def scan_universe(
    scan_root: Path,
    max_depth: int = 4,
    interactive: bool = False,
    db: Optional[sqlite_utils.Database] = None,
) -> List[Dict[str, Any]]:
    """Recursively scan scan_root, classify projects, and persist catalog into universe.db."""
    resolved_root = scan_root.expanduser().resolve()
    target_db = db or get_db()
    scan_start_iso = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()

    discovered_projects: List[Dict[str, Any]] = []

    def walk_dirs(current: Path, depth: int) -> None:
        if depth > max_depth or current.name in IGNORED_DIRECTORIES:
            return

        # Check if current is a project root
        is_root = is_project_root(current)

        if is_root:
            iso_time, ts = resolve_project_timestamp(current)
            classification = classify_project(current, ts, interactive=interactive)
            rel_path = "." if current == resolved_root else str(current.relative_to(resolved_root))

            is_git = 1 if is_git_repository(current) else 0
            branch = get_current_branch(current) if is_git else None

            record = {
                "name": current.name,
                "path": str(current),
                "relative_path": rel_path,
                "title": extract_title(current),
                "description": extract_description(current),
                "last_modified": iso_time,
                "last_modified_ts": ts,
                "classification": classification,
                "is_git": is_git,
                "git_branch": branch,
                "has_agents_md": 1 if (current / "AGENTS.md").exists() else 0,
                "has_intent_md": _has_doc(current, "docs/INTENT.md", "intent.md"),
                "has_state_md": _has_doc(current, "docs/STATE.md", "STATE.md"),
                "has_handoff_md": _has_doc(current, "docs/HANDOFF.md", "HANDOFF.md"),
                "has_readme_md": 1 if (current / "README.md").exists() else 0,
                "scanned_at": scan_start_iso,
                "scan_root": str(resolved_root),
            }

            upsert_project(target_db, record)
            discovered_projects.append(record)

            # If current is not the root, do not traverse into child directories
            # unless it contains a nested git repository
            if current != resolved_root:
                try:
                    for child in current.iterdir():
                        if (
                            child.is_dir()
                            and child.name not in IGNORED_DIRECTORIES
                            and is_git_repository(child)
                        ):
                            walk_dirs(child, depth + 1)
                except Exception:
                    pass
                return

        # If not a project root OR current == resolved_root: traverse subdirectories
        try:
            for child in current.iterdir():
                if child.is_dir() and child.name not in IGNORED_DIRECTORIES:
                    walk_dirs(child, depth + 1)
        except Exception:
            pass

    walk_dirs(resolved_root, depth=0)

    # Reconcile missing projects under scan_root
    reconcile_missing_projects(target_db, str(resolved_root), scan_start_iso)

    return discovered_projects
