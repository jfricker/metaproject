"""`metaproject adopt`: agent-safe, create-only adoption of an existing repository (#3)."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from metaproject import config as config_module
from metaproject.cli import app
from metaproject.identity import IDENTITY_FILE, read_identity
from metaproject.scaffold import adopt_project
from metaproject.skills import bundled_skills


@pytest.fixture
def agent_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run as Claude Code does: CLAUDECODE=1 and no human override."""
    monkeypatch.delenv("METAPROJECT_AGENT", raising=False)
    monkeypatch.setenv("CLAUDECODE", "1")


@pytest.fixture
def no_git(monkeypatch: pytest.MonkeyPatch) -> list:
    """Fail loudly if anything runs git through `metaproject.git`."""
    calls: list = []

    def refuse(*args, **kwargs):
        calls.append(args)
        raise AssertionError(f"adopt ran git: {args}")

    monkeypatch.setattr("metaproject.git.subprocess.run", refuse)
    return calls


@pytest.fixture
def container_git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """A web container: `git config user.name` is "Claude" and $USER is root."""

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["git", "config", "user.name"]:
            return SimpleNamespace(returncode=0, stdout="Claude\n", stderr="")
        raise AssertionError(f"unexpected subprocess: {cmd}")

    monkeypatch.setattr(config_module.subprocess, "run", fake_run)
    monkeypatch.setenv("USER", "root")


def existing_repo(tmp_path: Path) -> Path:
    """An already-cloned repository with its own README and AGENTS.md."""
    repo = tmp_path / "cloned-repo"
    repo.mkdir()
    (repo / ".git").mkdir()  # a clone; adopt must not touch it
    (repo / "README.md").write_text("# Game Workshop\n\nBoard games.\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("# My own agent notes\n", encoding="utf-8")
    return repo


def test_adopt_in_agent_session_creates_identity_docs_and_skills(
    runner: CliRunner, tmp_path: Path, agent_session, no_git, container_git_identity
) -> None:
    """AC: under CLAUDECODE=1, creates .metaproject.json, docs and skills, overwrites
    nothing, runs no git, and never takes 'Claude' as the author."""
    repo = existing_repo(tmp_path)
    git_before = sorted(p.name for p in (repo / ".git").iterdir())

    result = runner.invoke(app, ["adopt", "--dir", str(repo), "--author", "Jo F"])

    assert result.exit_code == 0, result.output
    identity = read_identity(repo)
    assert identity is not None
    assert identity.title == "Game Workshop"
    assert identity.description == "Board games."
    assert identity.author != "Claude"
    assert "Claude" not in (repo / "docs" / "INTENT.md").read_text(encoding="utf-8")

    # Never overwrites.
    assert (repo / "README.md").read_text(encoding="utf-8") == "# Game Workshop\n\nBoard games.\n"
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == "# My own agent notes\n"

    # Every missing deliverable and skill, plus the .claude/skills link.
    assert (repo / "docs" / "INTENT.md").is_file()
    assert (repo / "CLAUDE.md").is_file()
    for skill in bundled_skills():
        assert (repo / ".agents" / "skills" / skill.name / "SKILL.md").is_file()
    link = repo / ".claude" / "skills"
    assert link.is_symlink()
    assert link.resolve() == (repo / ".agents" / "skills").resolve()

    # No git.
    assert no_git == []
    assert sorted(p.name for p in (repo / ".git").iterdir()) == git_before


def test_adopt_title_flag_wins(runner: CliRunner, tmp_path: Path) -> None:
    repo = existing_repo(tmp_path)
    result = runner.invoke(app, ["adopt", "--dir", str(repo), "--title", "Workshop"])
    assert result.exit_code == 0, result.output
    assert read_identity(repo).title == "Workshop"


def test_adopt_title_falls_back_to_directory_name(tmp_path: Path) -> None:
    repo = tmp_path / "nine-mens-morris"
    repo.mkdir()
    result = adopt_project(repo)
    assert result.identity.title == "Nine Mens Morris"
    assert result.identity_written


def test_adopt_is_idempotent(runner: CliRunner, tmp_path: Path) -> None:
    repo = existing_repo(tmp_path)
    assert runner.invoke(app, ["adopt", "--dir", str(repo)]).exit_code == 0
    identity_text = (repo / IDENTITY_FILE).read_text(encoding="utf-8")

    second = runner.invoke(app, ["adopt", "--dir", str(repo)])

    assert second.exit_code == 0, second.output
    assert "already present" in second.output
    assert (repo / IDENTITY_FILE).read_text(encoding="utf-8") == identity_text
    assert "Created" not in second.output


def test_adopt_keeps_existing_identity_and_renders_its_author(
    runner: CliRunner, tmp_path: Path
) -> None:
    """Author precedence: .metaproject.json wins over config.json."""
    from metaproject.config import Config, save_config

    save_config(Config(author="Config Author"))
    repo = tmp_path / "anchored"
    repo.mkdir()
    (repo / IDENTITY_FILE).write_text(
        json.dumps(
            {
                "title": "Anchored",
                "description": "",
                "author": "Identity Author",
                "created": "2026-01-02",
                "metaproject_version": "0.8.0",
            }
        ),
        encoding="utf-8",
    )
    before = (repo / IDENTITY_FILE).read_text(encoding="utf-8")

    result = runner.invoke(app, ["adopt", "--dir", str(repo), "--author", "Flag Author"])

    assert result.exit_code == 0, result.output
    assert (repo / IDENTITY_FILE).read_text(encoding="utf-8") == before
    intent = (repo / "docs" / "INTENT.md").read_text(encoding="utf-8")
    assert "Identity Author" in intent
    assert "Config Author" not in intent


def test_adopt_author_prefers_config_over_git(tmp_path: Path, container_git_identity) -> None:
    from metaproject.config import Config, save_config

    save_config(Config(author="Jane Doe"))
    repo = tmp_path / "repo"
    repo.mkdir()
    assert adopt_project(repo).identity.author == "Jane Doe"


def test_adopt_refuses_a_placeholder_author_in_a_web_container(
    runner: CliRunner,
    tmp_path: Path,
    container_git_identity,
    agent_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No config, git user "Claude", USER=root, no --author: nothing is written.

    `.metaproject.json` is create-only and top of the author precedence, so recording
    the "Developer" placeholder would outrank every real author set afterwards.
    """
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    assert not config_module.get_config_file_path().exists()
    repo = existing_repo(tmp_path)
    before = sorted(p.relative_to(repo) for p in repo.rglob("*"))

    result = runner.invoke(app, ["adopt", "--dir", str(repo)])

    assert result.exit_code == 1, result.output
    assert "--author" in result.output
    assert not (repo / IDENTITY_FILE).exists()
    assert sorted(p.relative_to(repo) for p in repo.rglob("*")) == before


def test_adopt_with_author_flag_in_a_web_container(
    runner: CliRunner,
    tmp_path: Path,
    container_git_identity,
    agent_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    repo = existing_repo(tmp_path)

    result = runner.invoke(app, ["adopt", "--dir", str(repo), "--author", "Jo F"])

    assert result.exit_code == 0, result.output
    data = json.loads((repo / IDENTITY_FILE).read_text(encoding="utf-8"))
    assert data["author"] == "Jo F"
    assert config_module.FALLBACK_AUTHOR not in (repo / "docs" / "SPEC.md").read_text(
        encoding="utf-8"
    )


def test_adopt_refuses_to_overwrite_an_invalid_identity_file(
    runner: CliRunner, tmp_path: Path
) -> None:
    repo = tmp_path / "broken"
    repo.mkdir()
    (repo / IDENTITY_FILE).write_text("{not json", encoding="utf-8")

    result = runner.invoke(app, ["adopt", "--dir", str(repo)])

    assert result.exit_code == 1
    assert (repo / IDENTITY_FILE).read_text(encoding="utf-8") == "{not json"
    assert not (repo / "docs").exists()


def test_adopt_dry_run_writes_nothing(runner: CliRunner, tmp_path: Path) -> None:
    repo = existing_repo(tmp_path)
    before = sorted(p.relative_to(repo) for p in repo.rglob("*"))

    result = runner.invoke(app, ["adopt", "--dir", str(repo), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "would write .metaproject.json" in result.output
    assert sorted(p.relative_to(repo) for p in repo.rglob("*")) == before


def test_adopt_leaves_a_real_git_repository_untouched(tmp_path: Path) -> None:
    """End to end against real git: HEAD and the index are exactly as they were."""
    repo = tmp_path / "real"
    repo.mkdir()
    (repo / "README.md").write_text("# Real\n", encoding="utf-8")
    env_git = ["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*env_git, "add", "README.md"], check=True)
    subprocess.run([*env_git, "commit", "-q", "-m", "init"], check=True)
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout

    adopt_project(repo)

    assert (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout
        == head
    )
    staged = subprocess.run(
        ["git", "-C", str(repo), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
    ).stdout
    assert staged == ""
    assert (repo / IDENTITY_FILE).is_file()


def test_new_dot_is_still_refused_in_agent_session(
    runner: CliRunner, tmp_path: Path, agent_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interactive `new .` keeps its semantics; adopt is the agent path."""
    repo = existing_repo(tmp_path)
    monkeypatch.chdir(repo)
    result = runner.invoke(app, ["new", "."])
    assert result.exit_code == 1
    assert not (repo / IDENTITY_FILE).exists()


def anchored_repo(tmp_path: Path, author: str) -> Path:
    repo = tmp_path / "anchored"
    repo.mkdir()
    (repo / IDENTITY_FILE).write_text(
        json.dumps(
            {
                "title": "Anchored",
                "description": "",
                "author": author,
                "created": "2026-01-02",
                "metaproject_version": "0.8.0",
            }
        ),
        encoding="utf-8",
    )
    return repo


def test_backfill_author_comes_from_identity_before_config_and_git(
    runner: CliRunner, tmp_path: Path, container_git_identity, agent_session
) -> None:
    """Author precedence for `backfill`: .metaproject.json -> config -> git."""
    from metaproject.config import Config, save_config

    save_config(Config(author="Config Author"))
    repo = anchored_repo(tmp_path, "Identity Author")

    result = runner.invoke(app, ["backfill", "--dir", str(repo)])

    assert result.exit_code == 0, result.output
    intent = (repo / "docs" / "INTENT.md").read_text(encoding="utf-8")
    assert "Identity Author" in intent
    assert "Config Author" not in intent
    assert "Claude" not in intent


def test_backfill_author_falls_back_to_config_not_container_git(
    runner: CliRunner, tmp_path: Path, container_git_identity, agent_session
) -> None:
    """No identity file: config wins, and the container's `Claude` never appears."""
    from metaproject.config import Config, save_config

    save_config(Config(author="Config Author"))
    repo = tmp_path / "plain"
    repo.mkdir()

    result = runner.invoke(app, ["backfill", "--dir", str(repo)])

    assert result.exit_code == 0, result.output
    intent = (repo / "docs" / "INTENT.md").read_text(encoding="utf-8")
    assert "Config Author" in intent
    assert "Claude" not in intent
