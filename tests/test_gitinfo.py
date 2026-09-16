"""Tests for live project inspection: staleness scoring, bounded git calls, degradation."""

import json
import subprocess
import time
from pathlib import Path

import pytest

from metaproject.gitinfo import (
    GIT_TIMEOUT_S,
    WorktreeInfo,
    inspect_project,
    inspect_worktree,
    last_commit,
    score_worktree,
    uncommitted_files,
)


def git(cwd: Path, *args: str) -> None:
    """Run a real git command as a fixture builder (mirrors learn_workspace/build.py)."""
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
        env={
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "HOME": str(cwd),  # keep global config out of fixture behavior
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


def make_repo(root: Path, name: str = "proj", old_commit_days: int = 0) -> Path:
    """A real git repo with one commit, `old_commit_days` in the past when nonzero."""
    repo = root / name
    repo.mkdir()
    git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    git(repo, "add", ".")
    if old_commit_days:
        old_date = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - old_commit_days * 86400)
        )
        env_date = f"{old_date} +0000"
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "old commit"],
            capture_output=True,
            text=True,
            check=True,
            env={
                "GIT_AUTHOR_NAME": "Fixture",
                "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "Fixture",
                "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
                "GIT_AUTHOR_DATE": env_date,
                "GIT_COMMITTER_DATE": env_date,
                "HOME": str(repo),
                "PATH": "/usr/bin:/bin:/usr/local/bin",
            },
        )
    else:
        git(repo, "commit", "-m", "fresh commit")
    return repo


class TestScoreWorktree:
    """Pure scoring table (R-UNV-3) — no subprocess involved."""

    def test_fresh_and_current_is_active(self) -> None:
        stale, flag = score_worktree(2, 0, False)
        assert (stale, flag) == (False, False)

    def test_old_age_alone_can_stale(self) -> None:
        # 30d age (2) + 2 behind (1) = 3
        stale, _flag = score_worktree(31, 2, False)
        assert stale is True

    def test_old_age_alone_under_threshold(self) -> None:
        # 30d age (2) + 0 behind (0) = 2
        stale, _flag = score_worktree(40, 0, False)
        assert stale is False

    def test_far_behind_alone_can_stale(self) -> None:
        # 10d age (1) + 6 behind (2) = 3
        stale, _flag = score_worktree(10, 6, False)
        assert stale is True

    def test_uncommitted_flag_rises_without_verdict(self) -> None:
        # Fresh and current, but dirty: active verdict, awareness flag (AC-6)
        stale, flag = score_worktree(1, 0, True)
        assert (stale, flag) == (False, True)

    def test_unknown_base_is_neutral_scoring(self) -> None:
        # Detached/unknown base: behind scores 0, so an unknown-base worktree is
        # never scored stale — it degrades to the neutral marker (design.md)
        stale, _flag = score_worktree(10, 50, False, base_known=False)
        assert stale is False
        stale, _flag = score_worktree(40, 50, False, base_known=False)
        assert stale is False

    def test_unknown_age_scores_zero(self) -> None:
        stale, _flag = score_worktree(None, 0, False)
        assert stale is False


class TestInspectProject:
    def test_happy_path_with_worktrees(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        git(repo, "worktree", "add", "-b", "feature/wt", str(tmp_path / "wt"), "main")
        # Make the linked worktree dirty: the flag must rise there, not on main
        (tmp_path / "wt" / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")

        details = inspect_project(repo)
        assert details.is_git is True
        assert details.last_commit is not None
        assert "fresh commit" in details.last_commit
        assert details.metaproject_version == "unknown"

        assert len(details.worktrees) == 1
        wt = details.worktrees[0]
        assert wt.branch == "feature/wt"
        assert wt.uncommitted_count == 1
        assert wt.flag is True
        assert wt.stale is False  # fresh, not behind
        assert wt.base_branch is not None

    def test_version_from_metaproject_json(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        # read_identity requires the full schema; a partial file degrades to unknown
        full_identity = {
            "title": "Fixture",
            "description": "Fixture project",
            "author": "Fixture",
            "created": "2026-09-15",
            "metaproject_version": "0.7.0",
        }
        (repo / ".metaproject.json").write_text(json.dumps(full_identity), encoding="utf-8")
        details = inspect_project(repo)
        assert details.metaproject_version == "0.7.0"

    def test_partial_metaproject_json_degrades_to_unknown(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        (repo / ".metaproject.json").write_text(
            json.dumps({"metaproject_version": "0.7.0"}), encoding="utf-8"
        )
        details = inspect_project(repo)
        assert details.metaproject_version == "unknown"

    def test_old_stale_worktree(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        git(repo, "worktree", "add", "-b", "stale/wt", str(tmp_path / "wt"), "main")
        # Age the worktree's HEAD with an ancient commit, then advance main twice so
        # the worktree is also behind: age(2) + behind(1) = stale
        (tmp_path / "wt" / "note.txt").write_text("old\n", encoding="utf-8")
        git(tmp_path / "wt", "add", ".")
        old_date = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 200 * 86400)
        )
        subprocess.run(
            ["git", "-C", str(tmp_path / "wt"), "commit", "-m", "ancient"],
            capture_output=True,
            text=True,
            check=True,
            env={
                "GIT_AUTHOR_NAME": "Fixture",
                "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "Fixture",
                "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
                "GIT_AUTHOR_DATE": f"{old_date} +0000",
                "GIT_COMMITTER_DATE": f"{old_date} +0000",
                "HOME": str(tmp_path),
                "PATH": "/usr/bin:/bin:/usr/local/bin",
            },
        )
        (repo / "a.txt").write_text("a\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-m", "advance one")
        (repo / "b.txt").write_text("b\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-m", "advance two")

        details = inspect_project(repo)
        assert len(details.worktrees) == 1
        wt = details.worktrees[0]
        assert wt.behind_count == 2
        assert wt.stale is True
        assert wt.flag is False

    def test_detached_worktree_is_neutral(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        git(repo, "worktree", "add", "--detach", str(tmp_path / "wt"), "HEAD")

        details = inspect_project(repo)
        wt = details.worktrees[0]
        assert wt.branch is None
        assert wt.neutral is True
        assert wt.stale is False  # verdict degrades to age only

    def test_non_git_project_degrades(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        details = inspect_project(plain)
        assert details.is_git is False
        assert details.status_short is None
        assert details.last_commit is None
        assert details.worktrees == []
        assert details.metaproject_version == "unknown"

    def test_broken_git_degrades_not_raises(self, tmp_path: Path, monkeypatch) -> None:
        repo = make_repo(tmp_path)
        # A broken git environment must yield placeholders, never a traceback (AC-12)
        monkeypatch.setenv("GIT_DIR", str(tmp_path / "nowhere"))
        details = inspect_project(repo)
        assert details.is_git is False or details.status_short is None
        assert details.last_commit is None


class TestHelpers:
    def test_uncommitted_files_and_last_commit(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        assert uncommitted_files(repo) == []
        (repo / "new.txt").write_text("dirty\n", encoding="utf-8")
        files = uncommitted_files(repo)
        assert len(files) == 1
        assert "new.txt" in files[0]

        commit = last_commit(repo)
        assert commit is not None
        assert "fresh commit" in commit
        assert len(commit.split(" ", 1)[0]) == 7  # short hash

    def test_helpers_degrade(self, tmp_path: Path) -> None:
        assert uncommitted_files(tmp_path / "missing") == []
        assert last_commit(tmp_path / "missing") is None

    def test_inspect_worktree_refreshes(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        git(repo, "worktree", "add", "-b", "feature/wt", str(tmp_path / "wt"), "main")
        details = inspect_project(repo)
        before = details.worktrees[0]

        (tmp_path / "wt" / "dirty.txt").write_text("x\n", encoding="utf-8")
        after = inspect_worktree(before)
        assert isinstance(after, WorktreeInfo)
        assert after.uncommitted_count == before.uncommitted_count + 1
        assert after.flag is True

    def test_timeout_constant_is_bounded(self) -> None:
        # Single-digit seconds per call (R-UNV-6)
        assert 0 < GIT_TIMEOUT_S < 10


@pytest.fixture(autouse=True)
def _sane_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the operator's git config out of scoring paths that don't pass env."""
    monkeypatch.delenv("GIT_DIR", raising=False)
