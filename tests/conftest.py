"""Common test fixtures for metaproject test suite."""

import pytest
from typer.testing import CliRunner


@pytest.fixture(autouse=True)
def isolate_test_environment(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Isolate METAPROJECT_CONFIG_DIR for all tests to avoid touching user home dir."""
    test_config_dir = tmp_path_factory.mktemp("metaproject_cfg")
    monkeypatch.setenv("METAPROJECT_CONFIG_DIR", str(test_config_dir))
    # Pin the session kind. The suite is run both by people and by agents, and the
    # agent guards would otherwise make identical tests behave differently depending on
    # who invoked pytest. Tests that exercise the guards set this themselves.
    monkeypatch.setenv("METAPROJECT_AGENT", "0")
    # Keep skill installation out of the operator's real ~/.claude during tests.
    monkeypatch.setenv(
        "METAPROJECT_SKILL_DIR", str(tmp_path_factory.mktemp("claude_skills") / "metaproject")
    )


@pytest.fixture
def runner() -> CliRunner:
    """Provide an isolated Typer CLI runner."""
    return CliRunner()
