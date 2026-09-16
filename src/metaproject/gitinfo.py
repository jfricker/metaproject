"""Live project inspection: bounded git subprocesses for the universe details views.

No Textual import lives here: the subprocess logic is unit-testable without a widget
framework, mirroring how `review.py`/`review_tui.py` split. Every git call is bounded
by `GIT_TIMEOUT_S` and every failure degrades to a placeholder field — an exception
never escapes this module's `inspect_*` boundary (R-UNV-6).
"""

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from metaproject.identity import read_identity

GIT_TIMEOUT_S = 5

# Staleness scoring table (design.md): age of HEAD's last commit and commits behind
# the base branch each contribute 0-2; the verdict is stale at a combined score of 3.
# Uncommitted changes contribute nothing to the score but always set the awareness
# flag. An undeterminable base (detached HEAD, unknown branch) scores behind as 0 and
# is marked neutral — verdict from age only.
STALE_AGE_TIERS = (7, 30)
STALE_BEHIND_TIER = 5
STALE_SCORE_THRESHOLD = 3


@dataclass
class WorktreeInfo:
    """One linked worktree's live state, with its staleness verdict and flag."""

    path: str
    branch: Optional[str]
    head_age_days: Optional[float]
    behind_count: int
    uncommitted_count: int
    stale: bool
    flag: bool
    neutral: bool = False
    ahead_count: int = 0
    base_branch: Optional[str] = None


@dataclass
class ProjectDetails:
    """A project's live state, fetched at selection time — never persisted."""

    path: str
    status_short: Optional[str] = None
    last_commit: Optional[str] = None
    worktrees: List[WorktreeInfo] = field(default_factory=list)
    metaproject_version: Optional[str] = None
    is_git: bool = False


def _git(path: Path, *args: str) -> Optional[str]:
    """Run one bounded git command in `path`; None on any failure or timeout."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def score_worktree(
    head_age_days: Optional[float],
    behind_count: int,
    has_uncommitted: bool,
    base_known: bool = True,
) -> tuple:
    """Pure staleness scoring (R-UNV-3): returns `(stale, flag)`.

    Age `<7d`→0, `<30d`→1, `≥30d`→2 (unknown age → 0); behind `0`→0, `≤5`→1, `>5`→2.
    An unknown base contributes 0 for behind. The uncommitted flag never merges into
    the verdict.
    """
    if head_age_days is None:
        age_score = 0
    elif head_age_days < STALE_AGE_TIERS[0]:
        age_score = 0
    elif head_age_days < STALE_AGE_TIERS[1]:
        age_score = 1
    else:
        age_score = 2

    effective_behind = behind_count if base_known else 0
    if effective_behind == 0:
        behind_score = 0
    elif effective_behind <= STALE_BEHIND_TIER:
        behind_score = 1
    else:
        behind_score = 2

    stale = age_score + behind_score >= STALE_SCORE_THRESHOLD
    return stale, bool(has_uncommitted)


def _default_base_branch(project_path: Path) -> str:
    """The project's default branch: origin/HEAD when resolvable, else `main`."""
    head = _git(project_path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head and head.strip():
        return head.strip()
    return "main"


def _head_age_days(path: Path) -> Optional[float]:
    """Days since the last commit in `path`, or None when it cannot be determined."""
    commit_ts = _git(path, "log", "-1", "--format=%ct")
    if not commit_ts or not commit_ts.strip():
        return None
    try:
        return max(0.0, (time.time() - int(commit_ts.strip())) / 86400.0)
    except ValueError:
        return None


def _inspect_worktree_path(
    wt_path: Path,
    branch: Optional[str],
    base_branch: Optional[str],
) -> WorktreeInfo:
    """Build one WorktreeInfo from a worktree's directory, degrading per field."""
    status = _git(wt_path, "status", "--porcelain")
    status_lines = status.splitlines() if status is not None else []
    uncommitted_count = len(status_lines)

    head_age_days = _head_age_days(wt_path)

    # Base branch: a detached HEAD has no determinable base (design.md) — behind
    # scores 0 and the verdict degrades to age only, marked neutral. Otherwise the
    # worktree's tracked upstream, then the project's default branch.
    if branch is None:
        base: Optional[str] = None
        base_known = False
    else:
        upstream = _git(wt_path, "rev-parse", "--abbrev-ref", "@{upstream}")
        base = upstream.strip() if upstream and upstream.strip() else base_branch
        base_known = base is not None

    behind_count = 0
    ahead_count = 0
    if base_known:
        behind = _git(wt_path, "rev-list", "--count", f"HEAD..{base}")
        ahead = _git(wt_path, "rev-list", "--count", f"{base}..HEAD")
        try:
            behind_count = int(behind.strip()) if behind and behind.strip() else 0
            ahead_count = int(ahead.strip()) if ahead and ahead.strip() else 0
        except ValueError:
            base_known = False
            behind_count = 0
            ahead_count = 0

    stale, flag = score_worktree(head_age_days, behind_count, uncommitted_count > 0, base_known)
    return WorktreeInfo(
        path=str(wt_path),
        branch=branch,
        head_age_days=head_age_days,
        behind_count=behind_count,
        uncommitted_count=uncommitted_count,
        stale=stale,
        flag=flag,
        neutral=not base_known,
        ahead_count=ahead_count,
        base_branch=base,
    )


def _parse_worktrees(project_path: Path) -> List[tuple]:
    """Linked worktrees as (path, branch) pairs from `worktree list --porcelain`.

    The main worktree is not listed — the project row itself covers it, matching the
    approved mockup where only linked worktrees appear in the table.
    """
    raw = _git(project_path, "worktree", "list", "--porcelain")
    if not raw:
        return []

    blocks = [block for block in raw.split("\n\n") if block.strip()]
    worktrees: List[tuple] = []
    for block in blocks[1:]:  # the first block is the main worktree
        wt_path: Optional[str] = None
        wt_branch: Optional[str] = None
        for line in block.splitlines():
            if line.startswith("worktree "):
                wt_path = line[len("worktree ") :].strip()
            elif line.startswith("branch refs/heads/"):
                wt_branch = line[len("branch refs/heads/") :].strip()
        if wt_path:
            worktrees.append((wt_path, wt_branch))
    return worktrees


def inspect_project(path: Path | str, base_branch: Optional[str] = None) -> ProjectDetails:
    """Fetch a project's live state via bounded git calls, degrading per field (R-UNV-2d/6).

    `base_branch` overrides the fallback base for worktrees whose upstream cannot be
    resolved (the caller may pass the branch recorded in `universe.db`).
    """
    project_path = Path(path).expanduser().resolve()
    details = ProjectDetails(path=str(project_path))

    identity = read_identity(project_path)
    details.metaproject_version = identity.metaproject_version if identity else "unknown"

    status = _git(project_path, "status", "--porcelain")
    if status is None:
        # Not a repo (or git broken): the detail view renders a "no git" section.
        return details
    details.is_git = True
    details.status_short = status

    commit = _git(project_path, "log", "-1", "--format=%h %s")
    details.last_commit = commit.strip() if commit and commit.strip() else None

    default_base = base_branch or _default_base_branch(project_path)
    for wt_path, wt_branch in _parse_worktrees(project_path):
        details.worktrees.append(_inspect_worktree_path(Path(wt_path), wt_branch, default_base))

    return details


def inspect_worktree(info: WorktreeInfo, base_branch: Optional[str] = None) -> WorktreeInfo:
    """Re-fetch one worktree's live state for the detail-of-detail view (R-UNV-2h)."""
    wt_path = Path(info.path)
    base = base_branch or info.base_branch or _default_base_branch(wt_path)
    return _inspect_worktree_path(wt_path, info.branch, base)


def uncommitted_files(path: Path | str) -> List[str]:
    """The porcelain status lines behind the awareness flag, or [] when unavailable."""
    status = _git(Path(path), "status", "--porcelain")
    if not status:
        return []
    return [line for line in status.splitlines() if line.strip()]


def last_commit(path: Path | str) -> Optional[str]:
    """The `<short-hash> <subject>` line of the latest commit, or None."""
    commit = _git(Path(path), "log", "-1", "--format=%h %s")
    if not commit or not commit.strip():
        return None
    return commit.strip()
