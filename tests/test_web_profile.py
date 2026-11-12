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
    ],
)
def test_web_profile_commands_print_one_line_notice_and_exit_zero(
    runner: CliRunner, web, args: list
) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert NOTICE in result.output
    assert len(result.output.strip().splitlines()) == 1


def test_web_profile_universe_json_stays_json(runner: CliRunner, web) -> None:
    """A JSON consumer gets a JSON envelope on stdout; the notice goes to stderr."""
    result = runner.invoke(app, ["universe", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["available"] is False
    assert payload["profile"] == "web"
    assert NOTICE in result.stderr


def test_web_profile_universe_csv_keeps_stdout_empty(runner: CliRunner, web) -> None:
    result = runner.invoke(app, ["universe", "--format", "csv"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == ""
    assert NOTICE in result.stderr


def test_web_profile_doctor_skips_environment_checks_but_runs_project_checks(
    runner: CliRunner, tmp_path: Path, web, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = tmp_path / "proj"
    scaffold_project("proj", output=proj, no_git=True)
    monkeypatch.chdir(proj)

    result = runner.invoke(app, ["doctor", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert NOTICE in result.output
    for check in ("project identity", "project docs", "project skills"):
        assert check in result.output
    for check in ("template store", "config (learn.targets)", "orphaned global skill"):
        assert check not in result.output
    # No `init` ran: the project checks need no config and write none.
    assert not get_config_file_path().exists()


def test_web_profile_doctor_reports_project_findings(
    runner: CliRunner, tmp_path: Path, web, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = tmp_path / "bare"
    proj.mkdir()
    monkeypatch.chdir(proj)

    result = runner.invoke(app, ["doctor", "--dry-run"])

    assert result.exit_code == 1, result.output
    assert NOTICE in result.output
    assert "no .metaproject.json anchor" in result.output
    assert not (proj / ".metaproject.json").exists()


def test_web_profile_doctor_fix_still_needs_an_operator(
    runner: CliRunner, tmp_path: Path, web, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = tmp_path / "bare"
    proj.mkdir()
    monkeypatch.chdir(proj)

    refused = runner.invoke(app, ["doctor"])
    assert refused.exit_code == 1
    assert "Doctor Refused" in refused.output

    # With the agent override cleared and the operator confirming, the project fix runs.
    monkeypatch.setenv("METAPROJECT_AGENT", "0")
    monkeypatch.setattr("metaproject.doctor._confirm_with_questionary", lambda message: True)
    fixed = runner.invoke(app, ["doctor"])
    assert NOTICE in fixed.output
    assert (proj / ".metaproject.json").is_file()


def test_fallback_author_placeholder_is_never_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git_user(monkeypatch, "Claude", user="root")
    config_file = tmp_path / "config.json"
    save_config(Config(), config_file)
    assert json.loads(config_file.read_text(encoding="utf-8"))["author"] == ""

    # A real identity configured later wins, because nothing stale outranks it.
    git_user(monkeypatch, "Jane Doe")
    assert load_config(config_file).author == "Jane Doe"
    assert resolve_author(config=load_config(config_file)) == "Jane Doe"


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
    # Nothing real was detected, so no placeholder is persisted to outrank git later.
    assert data["author"] == ""
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
