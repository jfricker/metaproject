"""Tests for agent-session detection and the guards built on it."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.learn.tui import tui_enabled
from metaproject.session import AGENT_OVERRIDE, agent_marker, is_agent_session, override_hint


class _Tty:
    """A stdout that claims to be a terminal, so the agent check is what decides."""

    @staticmethod
    def isatty() -> bool:
        return True


def test_agent_marker_names_the_signal() -> None:
    """Knowing which marker fired is what makes a refusal actionable."""
    assert agent_marker({"CLAUDECODE": "1"}) == "CLAUDECODE"
    assert agent_marker({"AI_AGENT": "1"}) == "AI_AGENT"
    assert agent_marker({"CI": "true"}) == "CI"
    assert agent_marker({}) is None
    assert agent_marker({"CI": "false"}) is None
    assert agent_marker({"CLAUDECODE": ""}) is None


def test_agent_override_wins_in_both_directions() -> None:
    """An operator inside a harness can opt back in; a harness without markers can opt in."""
    assert agent_marker({"CLAUDECODE": "1", AGENT_OVERRIDE: "0"}) is None
    assert agent_marker({AGENT_OVERRIDE: "1"}) == AGENT_OVERRIDE
    assert is_agent_session({"CLAUDECODE": "1"}) is True
    assert is_agent_session({}) is False


def test_override_hint_matches_the_marker() -> None:
    """The hint has to name the variable actually in play or it is noise."""
    assert AGENT_OVERRIDE in override_hint("CLAUDECODE")
    assert "CLAUDECODE" in override_hint("CLAUDECODE")
    assert "Unset" in override_hint(AGENT_OVERRIDE)


def test_tui_never_opens_in_an_agent_session() -> None:
    """A pty-allocating harness must not get a full-screen loop inside a tool call."""
    assert tui_enabled(stream=_Tty(), env={}) is True
    assert tui_enabled(stream=_Tty(), env={"CLAUDECODE": "1"}) is False
    assert tui_enabled(stream=_Tty(), env={"CI": "true"}) is False
    # The escape hatch still works for a person inside a harness.
    assert tui_enabled(stream=_Tty(), env={"CLAUDECODE": "1", AGENT_OVERRIDE: "0"}) is True
    # And the older triggers are untouched.
    assert tui_enabled(no_tui=True, stream=_Tty(), env={}) is False
    assert tui_enabled(stream=_Tty(), env={"TERM": "dumb"}) is False


def test_review_prints_the_board_and_says_why(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Degrading silently would let an agent report the board as the whole story."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "README.md").write_text("# proj\n", encoding="utf-8")
    monkeypatch.setenv("METAPROJECT_AGENT", "1")

    result = runner.invoke(app, ["review", str(project)])

    assert result.exit_code == 0, result.output
    assert "Agent session" in result.output
    assert "your own terminal" in result.output


def test_learn_scan_is_refused_in_an_agent_session(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scan spends money and egresses diffs; that is the operator's call to make."""
    monkeypatch.setenv("METAPROJECT_AGENT", "1")

    result = runner.invoke(app, ["learn", "scan", str(tmp_path)])

    assert result.exit_code == 1
    assert "needs an operator" in result.output
    assert "metaproject learn list" in result.output


def test_learn_default_mode_is_refused_too(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bare `learn [ROOT]` scans as well, so the guard cannot live only on the subcommand."""
    monkeypatch.setenv("METAPROJECT_AGENT", "1")

    result = runner.invoke(app, ["learn", str(tmp_path)])

    assert result.exit_code == 1
    assert "needs an operator" in result.output


def test_refused_scan_hands_back_a_runnable_command(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The point of the refusal is that the operator can paste what it prints."""
    monkeypatch.setenv("METAPROJECT_AGENT", "1")

    result = runner.invoke(app, ["learn", "scan", "--all", "--depth", "2", "--since", "7"])
    printed = " ".join(result.output.split())

    assert result.exit_code == 1
    assert "metaproject learn scan --all --depth 2 --since 7" in printed


def test_backfill_refuses_with_a_handover_in_an_agent_session(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An agent cannot answer the backfill prompts, so it is told who can."""
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "main.py").write_text("print('hi')\n", encoding="utf-8")
    monkeypatch.setenv("METAPROJECT_AGENT", "1")

    result = runner.invoke(app, ["new", ".", "--output", str(target) + "/"])
    printed = " ".join(result.output.split())

    assert result.exit_code == 1
    assert "agent session" in printed
    assert "--force" in printed
    assert not (target / "AGENTS.md").exists()


def test_dry_run_backfill_still_previews_for_an_agent(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Previewing writes nothing, so it stays available — it is how an agent reports."""
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "main.py").write_text("print('hi')\n", encoding="utf-8")
    monkeypatch.setenv("METAPROJECT_AGENT", "1")

    result = runner.invoke(
        app,
        [
            "new",
            ".",
            "--output",
            str(target) + "/",
            "--dry-run",
            "--title",
            "Occupied",
            "--description",
            "d",
            "--author",
            "A",
        ],
    )

    assert result.exit_code == 0, result.output
    assert not (target / "AGENTS.md").exists()
