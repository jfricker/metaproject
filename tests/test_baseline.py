"""Baseline tests verifying environment, package structure, and CLI runner."""

from typer.testing import CliRunner

import metaproject
from metaproject.cli import app


def test_package_version() -> None:
    """Verify metaproject package exposes expected version."""
    assert metaproject.__version__ == "0.1.0"


def test_cli_help(runner: CliRunner) -> None:
    """Verify metaproject CLI responds to --help."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "metaproject" in result.output
