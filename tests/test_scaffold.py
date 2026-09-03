"""Tests for scaffolding engine, path resolution, git integration, rollback, and CLI commands."""

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.config import Config
from metaproject.exceptions import CollisionError
from metaproject.scaffold import is_directory_empty, resolve_output, scaffold_project


def test_resolve_output(tmp_path: Path) -> None:
    """Verify output resolution semantics per spec.md §5.2."""
    base_dir = tmp_path / "workspace"
    base_dir.mkdir()

    # 1. No output -> ./<name>
    res1 = resolve_output(None, "my_app", base_dir=base_dir)
    assert res1 == base_dir / "my_app"

    # 2. output is existing dir -> <output>/<name>
    existing_sub = tmp_path / "sub"
    existing_sub.mkdir()
    res2 = resolve_output(existing_sub, "my_app", base_dir=base_dir)
    assert res2 == existing_sub / "my_app"

    # 3. output does not exist -> exact root
    exact_path = tmp_path / "custom_location"
    res3 = resolve_output(exact_path, "my_app", base_dir=base_dir)
    assert res3 == exact_path

    # 4. output ends with trailing slash -> exact root
    res4 = resolve_output(str(tmp_path / "trailing") + "/", "my_app", base_dir=base_dir)
    assert res4 == tmp_path / "trailing"


def test_is_directory_empty(tmp_path: Path) -> None:
    """Verify empty check allows non-existent, empty, and solitary .git or .DS_Store."""
    # Non-existent
    assert is_directory_empty(tmp_path / "does_not_exist") is True

    # Empty directory
    test_dir = tmp_path / "test_empty"
    test_dir.mkdir()
    assert is_directory_empty(test_dir) is True

    # Solitary .git directory
    git_dir = test_dir / ".git"
    git_dir.mkdir()
    assert is_directory_empty(test_dir) is True

    # Solitary .DS_Store
    (test_dir / ".DS_Store").write_text("dummy", encoding="utf-8")
    assert is_directory_empty(test_dir) is True

    # Non-hidden regular file -> not empty
    (test_dir / "hello.txt").write_text("content", encoding="utf-8")
    assert is_directory_empty(test_dir) is False


def test_scaffold_dry_run(tmp_path: Path) -> None:
    """Verify dry_run previews without creating directory or files."""
    target = tmp_path / "dry_run_proj"
    res = scaffold_project(
        project_name="dry_run_proj",
        output=target,
        dry_run=True,
        interactive=False,
    )
    assert res["dry_run"] is True
    assert not target.exists()
    assert len(res["rendered_files"]) >= 7


def test_scaffold_project_success(tmp_path: Path) -> None:
    """Verify scaffolding creates all 8 standard files and initializes git."""
    target = tmp_path / "new_proj"
    cfg = Config(author="Jane Dev", default_branch="main")

    res = scaffold_project(
        project_name="new_proj",
        output=target,
        title="New Project",
        description="Scaffolding test project",
        config=cfg,
        interactive=False,
        no_git=False,
    )

    assert target.exists()
    assert res["git_initialized"] is True

    # Verify all standard files exist
    expected_files = [
        "README.md",
        "AGENTS.md",
        "intent.md",
        "STATE.md",
        "HANDOFF.md",
        "CLAUDE.md",
        ".gitignore",
        "docs",
    ]
    for expected in expected_files:
        assert (target / expected).exists(), f"Missing expected deliverable: {expected}"

    # Verify content substitution
    readme_content = (target / "README.md").read_text(encoding="utf-8")
    assert "# New Project" in readme_content
    assert "Scaffolding test project" in readme_content

    # Verify git repository
    assert (target / ".git").exists()
    git_log = subprocess.run(
        ["git", "-C", str(target), "log", "-1", "--oneline"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "chore: initial scaffold from metaproject" in git_log.stdout


def test_scaffold_collision_guard(tmp_path: Path) -> None:
    """Verify collision error when target directory is not empty without --force."""
    target = tmp_path / "colliding_proj"
    target.mkdir()
    (target / "existing.txt").write_text("already here", encoding="utf-8")

    # Pass with trailing slash to specify exact directory root
    exact_target = str(target) + "/"

    with pytest.raises(CollisionError):
        scaffold_project(
            project_name="colliding_proj",
            output=exact_target,
            interactive=False,
            force=False,
        )

    # With force=True, scaffolding should succeed
    res = scaffold_project(
        project_name="colliding_proj",
        output=exact_target,
        interactive=False,
        force=True,
        no_git=True,
    )
    assert res["target_dir"] == target
    assert (target / "existing.txt").exists()  # Non-template file preserved!
    assert (target / "README.md").exists()


def test_cli_new_command(runner: CliRunner, tmp_path: Path) -> None:
    """Verify running 'metaproject new' through the CLI runner."""
    target = tmp_path / "cli_created_proj"
    result = runner.invoke(
        app,
        [
            "new",
            "cli_created_proj",
            "--output",
            str(target),
            "--title",
            "CLI App",
            "--description",
            "Built with Typer",
            "--yes",
            "--no-git",
        ],
    )
    assert result.exit_code == 0
    assert "Successfully scaffolded project" in result.output
    assert (target / "README.md").exists()
    assert (target / "AGENTS.md").exists()


def test_cli_init_command(runner: CliRunner, tmp_path: Path) -> None:
    """Verify running 'metaproject init' through the CLI runner."""
    config_dir = tmp_path / ".metaproject"
    dummy_home = tmp_path / "dummy_workspaces"
    dummy_home.mkdir()
    result = runner.invoke(
        app,
        [
            "init",
            "--config-dir",
            str(config_dir),
            "--project-home",
            str(dummy_home),
            "--force",
        ],
    )
    assert result.exit_code == 0
    assert "Metaproject Initialized Successfully" in result.output
    assert (config_dir / "config.json").exists()
    assert (config_dir / "templates" / "AGENTS.template.md").exists()
