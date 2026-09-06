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
from metaproject.variables import titlecase

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


def is_project_root(path: Path) -> bool:
    """Determine if a directory represents a project root boundary."""
    if not path.is_dir():
        return False

    # 1. Git repository root
    if (path / ".git").exists():
        return True

    # 2. SDLC root indicators
    if (path / "AGENTS.md").exists() or (path / "intent.md").exists():
        return True

    # 3. Standard build/package manifests
    for manifest in PROJECT_MANIFESTS:
        if (path / manifest).exists():
            return True

    return False


def is_archived_path(path: Path) -> bool:
    """Check if any folder in the path hierarchy is named 'Archive' or 'archive'."""
    for part in path.parts:
        if part.lower() == "archive":
            return True
    return False


def extract_title(project_dir: Path) -> str:
    """Extract project title from README.md, intent.md, or directory name."""
    readme_path = project_dir / "README.md"
    if readme_path.exists():
        try:
            for line in readme_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                clean = line.strip()
                if clean.startswith("# "):
                    return clean[2:].strip()
        except Exception:
            pass

    intent_path = project_dir / "intent.md"
    if intent_path.exists():
        try:
            for line in intent_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                clean = line.strip()
                if clean.startswith("# "):
                    title_part = clean[2:].split("-")[0].strip()
                    if title_part:
                        return title_part
        except Exception:
            pass

    return titlecase(project_dir.name)


def extract_description(project_dir: Path) -> str:
    """Extract one-line description from intent.md, README.md, or empty string."""
    intent_path = project_dir / "intent.md"
    if intent_path.exists():
        try:
            lines = intent_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            for i, line in enumerate(lines):
                if line.strip().startswith("## Problem") and i + 1 < len(lines):
                    desc = lines[i + 1].strip()
                    if desc and not desc.startswith("#"):
                        return desc
        except Exception:
            pass

    readme_path = project_dir / "README.md"
    if readme_path.exists():
        try:
            lines = readme_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            found_header = False
            in_code_fence = False
            for line in lines:
                clean = line.strip()
                if clean.startswith("```"):
                    # Track the fence rather than only skipping its delimiters, or the
                    # first shell command in a Quick Start block becomes the description.
                    in_code_fence = not in_code_fence
                    continue
                if in_code_fence:
                    continue
                if clean.startswith("# "):
                    found_header = True
                    continue
                if found_header and clean and not clean.startswith("#"):
                    return clean
        except Exception:
            pass

    return ""


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
                "has_intent_md": 1 if (current / "intent.md").exists() else 0,
                "has_state_md": 1 if (current / "STATE.md").exists() else 0,
                "has_handoff_md": 1 if (current / "HANDOFF.md").exists() else 0,
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
