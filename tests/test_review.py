"""Tests for template drift auditing, missing deliverable detection, and review CLI command."""

from pathlib import Path

from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.review import review_project, review_workspace
from metaproject.scaffold import scaffold_project


def test_review_compliant_project(tmp_path: Path) -> None:
    """Verify that a freshly scaffolded project reports 100% compliance."""
    proj = tmp_path / "compliant_proj"
    scaffold_project(
        project_name="compliant_proj",
        output=proj,
        interactive=False,
        no_git=True,
    )

    review = review_project(proj)
    assert review["is_compliant"] is True
    assert len(review["missing_files"]) == 0
    assert len(review["recommendations"]) == 0


def test_review_missing_files_and_drift(tmp_path: Path) -> None:
    """Verify detection of missing deliverables and template content drift."""
    proj = tmp_path / "drifting_proj"
    proj.mkdir()

    # Create only README.md and modified AGENTS.md
    (proj / "README.md").write_text("# Drifting Proj", encoding="utf-8")
    (proj / "AGENTS.md").write_text("# Custom rules\nNever use make!", encoding="utf-8")

    review = review_project(proj)
    assert review["is_compliant"] is False
    assert "HANDOFF.md" in review["missing_files"]
    assert "STATE.md" in review["missing_files"]
    assert "CLAUDE.md" in review["missing_files"]
    assert ".gitignore" in review["missing_files"]
    assert "docs" in review["missing_files"]

    # AGENTS.md should report content drift
    assert "AGENTS.md" in review["diffs"]
    assert len(review["recommendations"]) > 0


def test_review_workspace_and_cli(runner: CliRunner, tmp_path: Path) -> None:
    """Verify multi-project workspace review and CLI command output."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Project 1: valid scaffolded
    proj1 = workspace / "app_one"
    scaffold_project(
        project_name="app_one",
        output=proj1,
        interactive=False,
        no_git=True,
    )

    # Project 2: minimal git repo missing SDLC files
    proj2 = workspace / "app_two"
    proj2.mkdir()
    (proj2 / ".git").mkdir()
    (proj2 / "main.py").write_text("print('hello')", encoding="utf-8")

    results = review_workspace(workspace)
    assert len(results) == 2

    # CLI invocation with --all
    cli_result = runner.invoke(
        app,
        ["review", str(workspace), "--all"],
    )
    assert cli_result.exit_code == 0
    assert "PASS" in cli_result.output
    assert "DRIFT" in cli_result.output
    assert "app_one" in cli_result.output
    assert "app_two" in cli_result.output


def test_review_all_descends_nested_subdirs_when_root_is_project(
    runner: CliRunner, tmp_path: Path
) -> None:
    """Verify that 'review --all' descends into subdirectories even when root is a project."""
    parent_repo = tmp_path / "ParentProject"
    parent_repo.mkdir()
    (parent_repo / ".git").mkdir()
    (parent_repo / "README.md").write_text("# Parent", encoding="utf-8")

    # Create nested subproject inside ParentProject
    nested_proj = parent_repo / "subproject"
    nested_proj.mkdir()
    (nested_proj / ".git").mkdir()
    (nested_proj / "README.md").write_text("# Nested Project", encoding="utf-8")

    results = review_workspace(parent_repo)
    project_names = [r["project_name"] for r in results]
    assert "ParentProject" in project_names
    assert "subproject" in project_names

    cli_result = runner.invoke(app, ["review", str(parent_repo), "--all"])
    assert cli_result.exit_code == 0
    assert "ParentProject" in cli_result.output
    assert "subproject" in cli_result.output
