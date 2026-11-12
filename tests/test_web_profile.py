"""The web profile (Claude Code on the web) and `init`'s identity options (#3)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from metaproject import config as config_module
from metaproject.cli import app
from metaproject.config import (
    Config,
    detect_git_user_name,
    get_config_dir,
    get_config_file_path,
    load_config,
    save_config,
)
from metaproject.scaffold import scaffold_project
from metaproject.session import is_web_profile, web_profile_reason
from metaproject.variables import resolve_author

NOTICE = "not available in web sessions"


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh Claude Code on the web container: remote, agent-driven, no config."""
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    monkeypatch.delenv("METAPROJECT_AGENT", raising=False)
    monkeypatch.setenv("CLAUDECODE", "1")


def git_user(monkeypatch: pytest.MonkeyPatch, name: str, user: str = "root") -> None:
    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["git", "config", "user.name"]:
            return SimpleNamespace(returncode=0, stdout=f"{name}\n", stderr="")
        raise AssertionError(f"unexpected subprocess: {cmd}")

    monkeypatch.setattr(config_module.subprocess, "run", fake_run)
    monkeypatch.setenv("USER", user)


# ------------------------------------------------------------------- detection


def test_profile_detection_precedence(tmp_path: Path) -> None:
    missing = tmp_path / "none.json"
    assert web_profile_reason({}, missing) is None
    assert "CLAUDE_CODE_REMOTE" in web_profile_reason({"CLAUDE_CODE_REMOTE": "true"}, missing)
    assert web_profile_reason({"CLAUDE_CODE_REMOTE": "false"}, missing) is None
    assert web_profile_reason({"METAPROJECT_PROFILE": "web"}, missing) is not None
    # Explicit profile wins in both directions.
    assert not is_web_profile(
        {"CLAUDE_CODE_REMOTE": "true", "METAPROJECT_PROFILE": "local"}, missing
    )

    # An existing config without a profile is a local machine, whatever the env says.
    local_cfg = tmp_path / "local.json"
    local_cfg.write_text(json.dumps({"author": "x"}), encoding="utf-8")
    assert not is_web_profile({"CLAUDE_CODE_REMOTE": "true"}, local_cfg)

    # A config `init` wrote in the web profile keeps it.
    web_cfg = tmp_path / "web.json"
    web_cfg.write_text(json.dumps({"profile": "web"}), encoding="utf-8")
    assert is_web_profile({}, web_cfg)


# ------------------------------------------------------------------- commands


@pytest.mark.parametrize(
    "args",
    [
        ["universe"],
        ["universe", "summary"],
        ["universe", "--list", "--no-tui"],
        ["learn"],
        ["learn", "list"],
        ["learn", "scan", "--yes"],
        ["doctor"],
        ["doctor", "--dry-run"],
    ],
)
def test_web_profile_commands_print_one_line_notice_and_exit_zero(
    runner: CliRunner, web, args: list
) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert NOTICE in result.output
    assert len(result.output.strip().splitlines()) == 1


def test_web_profile_review_prints_board_with_notice(
    runner: CliRunner, tmp_path: Path, web
) -> None:
    proj = tmp_path / "proj"
    scaffold_project("proj", output=proj, no_git=True)

    result = runner.invoke(app, ["review", str(proj)])

    assert result.exit_code == 0, result.output
    assert NOTICE in result.output
    assert "proj" in result.output


def test_web_profile_review_no_tui_works_normally(runner: CliRunner, tmp_path: Path, web) -> None:
    proj = tmp_path / "proj"
    scaffold_project("proj", output=proj, no_git=True)

    result = runner.invoke(app, ["review", str(proj), "--no-tui"])

    assert result.exit_code == 0, result.output
    assert NOTICE not in result.output


def test_web_profile_backfill_and_version_work(runner: CliRunner, tmp_path: Path, web) -> None:
    assert runner.invoke(app, ["--version"]).exit_code == 0
    proj = tmp_path / "proj"
    proj.mkdir()
    result = runner.invoke(app, ["backfill", "--dir", str(proj)])
    assert result.exit_code == 0, result.output
    assert (proj / "docs" / "INTENT.md").is_file()


def test_web_init_writes_minimal_config_and_skips_scan(
    runner: CliRunner, web, monkeypatch: pytest.MonkeyPatch
) -> None:
    git_user(monkeypatch, "Claude")

    def no_scan(*args, **kwargs):
        raise AssertionError("init scanned the universe in the web profile")

    monkeypatch.setattr("metaproject.universe.scan_universe", no_scan)

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0, result.output
    config_file = get_config_file_path()
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["profile"] == "web"
    assert data["author"] != "Claude"
    assert not (get_config_dir() / "templates").exists()
    assert not (get_config_dir() / "universe.db").exists()

    # The profile outlives the config `init` just wrote.
    monkeypatch.delenv("CLAUDE_CODE_REMOTE")
    after = runner.invoke(app, ["universe"])
    assert after.exit_code == 0
    assert NOTICE in after.output


def test_web_init_author_flag(runner: CliRunner, web) -> None:
    result = runner.invoke(app, ["init", "--non-interactive", "--author", "Jane Doe"])
    assert result.exit_code == 0, result.output
    assert load_config().author == "Jane Doe"


def test_local_init_non_interactive_author_never_prompts(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_prompt(*args, **kwargs):
        raise AssertionError("init prompted under --non-interactive")

    monkeypatch.setattr("metaproject.cli.questionary.text", no_prompt)
    home = tmp_path / "home"
    home.mkdir()

    result = runner.invoke(
        app,
        ["init", "--non-interactive", "--author", "Jane Doe", "--project-home", str(home)],
    )

    assert result.exit_code == 0, result.output
    cfg = load_config()
    assert cfg.author == "Jane Doe"
    assert cfg.profile == "local"
    assert (get_config_dir() / "templates").is_dir()


# ------------------------------------------------------------------- identity


def test_detected_container_identity_is_never_an_author(monkeypatch: pytest.MonkeyPatch) -> None:
    git_user(monkeypatch, "Claude", user="root")
    assert detect_git_user_name() == "Developer"

    git_user(monkeypatch, "Claude", user="jane")
    assert detect_git_user_name() == "jane"

    git_user(monkeypatch, "Jane Doe")
    assert detect_git_user_name() == "Jane Doe"


def test_explicit_claude_author_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    """'Claude' is fine when it is the configured author, not a detected one."""
    git_user(monkeypatch, "Somebody")
    assert resolve_author("Claude") == "Claude"
    save_config(Config(author="Claude"))
    assert resolve_author(None, load_config()) == "Claude"
