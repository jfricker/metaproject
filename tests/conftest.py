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


@pytest.fixture
def runner() -> CliRunner:
    """Provide an isolated Typer CLI runner."""
    return CliRunner()
