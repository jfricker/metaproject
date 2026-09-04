"""Baseline tests verifying environment, package structure, and CLI runner."""

from typer.testing import CliRunner

import metaproject
from metaproject.cli import app


def test_package_version() -> None:
    """Verify metaproject package exposes expected version."""
    assert metaproject.__version__ == "0.6.0"


def test_cli_help(runner: CliRunner) -> None:
    """Verify metaproject CLI responds to --help."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "metaproject" in result.output
    assert "--version" in result.output
    assert "-v" in result.output


def test_cli_version_flag(runner: CliRunner) -> None:
    """Verify metaproject CLI responds to -v and --version with manifest info."""
    for flag in ["--version", "-v"]:
        result = runner.invoke(app, [flag])
        assert result.exit_code == 0
        assert "Package Manifest" in result.output
        assert "metaproject" in result.output
        assert "0.6.0" in result.output
        assert "Author" in result.output
        assert "License" in result.output
        assert "Dependencies" in result.output
        assert "CLI Entrypoint" in result.output
