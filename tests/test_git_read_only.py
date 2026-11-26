"""git.read_only_query: allow-listed, bounded, never raises on git failure."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from metaproject import git


def _patch(monkeypatch: pytest.MonkeyPatch, fn) -> list:
    calls: list = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return fn(cmd, **kwargs)

    monkeypatch.setattr(git.subprocess, "run", run)
    return calls


def test_disallowed_key_raises() -> None:
    with pytest.raises(ValueError):
        git.read_only_query(None, "core.editor")


def test_success_strips_and_passes_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _patch(monkeypatch, lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="Ada\n"))
    assert git.read_only_query(tmp_path, "user.name") == "Ada"
    cmd, kwargs = calls[0]
    assert cmd == ["git", "-C", str(tmp_path), "config", "--get", "user.name"]
    assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert kwargs["timeout"] == 5


def test_no_cwd_omits_dash_c(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch(monkeypatch, lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="x"))
    git.read_only_query(None, "user.email")
    assert calls[0][0] == ["git", "config", "--get", "user.email"]


def test_nonzero_and_empty_return_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="x\n"))
    assert git.read_only_query(None, "user.name") is None
    _patch(monkeypatch, lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="  \n"))
    assert git.read_only_query(None, "user.name") is None


@pytest.mark.parametrize(
    "exc", [subprocess.TimeoutExpired("git", 5), FileNotFoundError("git"), OSError("x")]
)
def test_failures_return_none(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    def boom(cmd, **kw):
        raise exc

    _patch(monkeypatch, boom)
    assert git.read_only_query(None, "core.symlinks") is None
