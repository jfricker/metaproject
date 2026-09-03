"""Tests for template harvesting, customization extraction, and learn CLI command."""

from pathlib import Path

from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.learn import (
    apply_learned_enhancement,
    extract_file_additions,
    learn_from_project,
)


def test_extract_file_additions(tmp_path: Path) -> None:
    """Verify extraction of new non-comment lines."""
    base_tmpl = tmp_path / "base.md"
    base_tmpl.write_text("# Base\nLine 1\nLine 2\n", encoding="utf-8")

    proj_file = tmp_path / "proj.md"
    proj_file.write_text(
        "# Project\nLine 1\nLine 2\nLine 3 (New Rule)\n# Comment\n", encoding="utf-8"
    )

    additions = extract_file_additions(proj_file, base_tmpl)
    assert len(additions) == 1
    assert additions[0] == "Line 3 (New Rule)"


def test_learn_from_project(tmp_path: Path) -> None:
    """Verify scanning a project detects additions against templates."""
    tmpl_dir = tmp_path / "templates"
    tmpl_dir.mkdir()
    (tmpl_dir / "AGENTS.template.md").write_text("# AGENTS\nStandard Rule 1\n", encoding="utf-8")
    (tmpl_dir / ".gitignore.template").write_text(".venv/\n*.pyc\n", encoding="utf-8")

    proj_dir = tmp_path / "custom_proj"
    proj_dir.mkdir()
    (proj_dir / "AGENTS.md").write_text(
        "# AGENTS\nStandard Rule 1\nCustom Rule 2\n", encoding="utf-8"
    )
    (proj_dir / ".gitignore").write_text(".venv/\n*.pyc\n*.secret\n", encoding="utf-8")

    results = learn_from_project(proj_dir, tmpl_dir)
    assert results["total_additions"] == 2
    assert len(results["candidates"]) == 2

    target_names = [c["target_file"] for c in results["candidates"]]
    assert "AGENTS.md" in target_names
    assert ".gitignore" in target_names


def test_apply_learned_enhancement(tmp_path: Path) -> None:
    """Verify appending new rules to template file idempotently."""
    tmpl = tmp_path / "AGENTS.template.md"
    tmpl.write_text("# Base\nRule 1\n", encoding="utf-8")

    added = apply_learned_enhancement(tmpl, ["Rule 2", "Rule 3"])
    assert added == 2

    content = tmpl.read_text(encoding="utf-8")
    assert "Rule 2" in content
    assert "Rule 3" in content
    assert "# Added via metaproject learn" in content

    # Repeated application of same rules should add 0
    second_added = apply_learned_enhancement(tmpl, ["Rule 2", "Rule 3"])
    assert second_added == 0


def test_cli_learn_command(runner: CliRunner, tmp_path: Path) -> None:
    """Verify running 'metaproject learn --yes' updates templates."""
    tmpl_dir = tmp_path / "templates"
    tmpl_dir.mkdir()
    target_tmpl = tmpl_dir / "AGENTS.template.md"
    target_tmpl.write_text("# Standard\nRule A\n", encoding="utf-8")

    proj_dir = tmp_path / "sample_proj"
    proj_dir.mkdir()
    (proj_dir / "AGENTS.md").write_text("# Standard\nRule A\nInnovative Rule B\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "learn",
            str(proj_dir),
            "--templates",
            str(tmpl_dir),
            "--yes",
        ],
    )
    assert result.exit_code == 0
    assert "Discovered 1 candidate additions" in result.output
    assert "Appended 1 new lines" in result.output

    updated_content = target_tmpl.read_text(encoding="utf-8")
    assert "Innovative Rule B" in updated_content
