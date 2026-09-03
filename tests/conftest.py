"""Common test fixtures for metaproject test suite."""

import pytest
from typer.testing import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    """Provide an isolated Typer CLI runner."""
    return CliRunner()
