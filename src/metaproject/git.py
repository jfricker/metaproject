"""Git integration, pre-flight verification, repository initialisation, and commit helpers."""

import subprocess
from pathlib import Path
from typing import Optional, Tuple

from metaproject.exceptions import GitError


def is_git_installed() -> bool:
    """Check if git CLI is accessible on system PATH."""
    try:
        res = subprocess.run(["git", "--version"], capture_output=True, check=False)
        return res.returncode == 0
    except Exception:
        return False


def get_git_identity(repo_dir: Optional[Path] = None) -> Tuple[Optional[str], Optional[str]]:
    """Retrieve configured git user.name and user.email."""
    cmd_name = ["git"]
    cmd_email = ["git"]
    if repo_dir:
        cmd_name.extend(["-C", str(repo_dir)])
        cmd_email.extend(["-C", str(repo_dir)])
    cmd_name.extend(["config", "user.name"])
    cmd_email.extend(["config", "user.email"])

    try:
        res_name = subprocess.run(cmd_name, capture_output=True, text=True, check=False)
        name = (
            res_name.stdout.strip()
            if res_name.returncode == 0 and res_name.stdout.strip()
            else None
        )

        res_email = subprocess.run(cmd_email, capture_output=True, text=True, check=False)
        email = (
            res_email.stdout.strip()
            if res_email.returncode == 0 and res_email.stdout.strip()
            else None
        )

        return name, email
    except Exception:
        return None, None


def is_git_repository(target_dir: Path) -> bool:
    """Check if target_dir is the root of a git repository."""
    return (target_dir / ".git").exists()


def get_current_branch(target_dir: Path) -> Optional[str]:
    """Return the name of the current active branch in target_dir."""
    try:
        res = subprocess.run(
            ["git", "-C", str(target_dir), "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None


def get_last_commit_timestamp(target_dir: Path) -> Optional[str]:
    """Return the ISO 8601 timestamp of the most recent git commit."""
    try:
        res = subprocess.run(
            ["git", "-C", str(target_dir), "log", "-1", "--format=%cI"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None


def has_uncommitted_changes(target_dir: Path) -> bool:
    """Check if target_dir contains modified or untracked files."""
    try:
        res = subprocess.run(
            ["git", "-C", str(target_dir), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        return res.returncode == 0 and bool(res.stdout.strip())
    except Exception:
        return False


def init_repository(
    target_dir: Path,
    branch: str = "main",
    commit_message: str = "chore: initial scaffold from metaproject",
    author_name: Optional[str] = None,
) -> bool:
    """Initialize a git repository in target_dir on specified branch and create initial commit.

    Pre-flights git identity; if missing, configures local repo identity using author_name
    to prevent aborts.
    """
    if not is_git_installed():
        raise GitError("git executable is not installed or not available on PATH.")

    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. Initialize repository with initial branch
    init_cmd = ["git", "init", "-b", branch]
    res = subprocess.run(init_cmd, cwd=target_dir, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        # Fallback for older git without -b flag
        fallback_res = subprocess.run(
            ["git", "init"], cwd=target_dir, capture_output=True, text=True, check=False
        )
        if fallback_res.returncode != 0:
            raise GitError(f"Failed to initialize git repository: {fallback_res.stderr.strip()}")
        subprocess.run(
            ["git", "checkout", "-b", branch], cwd=target_dir, capture_output=True, check=False
        )

    # 2. Check identity; if missing, configure local repo identity
    name, email = get_git_identity(target_dir)
    if not name:
        fallback_name = author_name or "Metaproject Developer"
        subprocess.run(["git", "config", "user.name", fallback_name], cwd=target_dir, check=False)
    if not email:
        subprocess.run(
            ["git", "config", "user.email", "dev@metaproject.local"], cwd=target_dir, check=False
        )

    # 3. Stage all files
    add_res = subprocess.run(
        ["git", "add", "."], cwd=target_dir, capture_output=True, text=True, check=False
    )
    if add_res.returncode != 0:
        raise GitError(f"Failed to stage files in {target_dir}: {add_res.stderr.strip()}")

    # 4. Initial commit
    commit_res = subprocess.run(
        ["git", "commit", "-m", commit_message],
        cwd=target_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if commit_res.returncode != 0:
        # If nothing to commit, that's acceptable
        if (
            "nothing to commit" not in commit_res.stdout
            and "nothing to commit" not in commit_res.stderr
        ):
            raise GitError(f"Failed to create initial commit: {commit_res.stderr.strip()}")

    return True
