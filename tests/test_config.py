"""Tests for configuration loading, saving, and template resource discovery."""

from pathlib import Path

import pytest

from metaproject.config import Config, load_config, save_config
from metaproject.exceptions import ConfigError
from metaproject.templates import get_bundled_templates_dir, seed_templates


def test_default_config() -> None:
    """Verify default Config instance fields."""
    cfg = Config()
    assert cfg.version == 1
    assert cfg.default_branch == "main"
    assert cfg.default_license == "MIT"
    assert cfg.auto_git_init is True
    assert cfg.author != ""


def test_save_and_load_config(tmp_path: Path) -> None:
    """Verify persisting and reloading config.json."""
    config_file = tmp_path / "custom_config.json"
    cfg = Config(
        author="Alice Tester",
        default_branch="trunk",
        project_home=str(tmp_path / "workspaces"),
    )
    saved_path = save_config(cfg, config_file)
    assert saved_path == config_file
    assert config_file.exists()

    loaded = load_config(config_file)
    assert loaded.author == "Alice Tester"
    assert loaded.default_branch == "trunk"
    assert loaded.project_home == str((tmp_path / "workspaces").resolve())


def test_load_corrupt_config(tmp_path: Path) -> None:
    """Verify ConfigError on invalid JSON content."""
    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_text("{ broken json", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(corrupt_file)


def test_bundled_templates_exist() -> None:
    """Verify bundled templates directory contains expected seed files."""
    bundled_dir = get_bundled_templates_dir()
    assert bundled_dir.exists()
    expected_files = [
        "AGENTS.template.md",
        "README.template.md",
        "intent.template.md",
        "STATE.template.md",
        "HANDOFF.template.md",
        "CLAUDE.template.md",
        ".gitignore.template",
    ]
    for expected in expected_files:
        assert (bundled_dir / expected).exists(), f"Missing template: {expected}"


def test_seed_templates(tmp_path: Path) -> None:
    """Verify seed_templates copies bundled templates to destination directory."""
    target_templates = tmp_path / "templates"
    copied = seed_templates(target_templates)
    assert len(copied) >= 7

    assert (target_templates / "AGENTS.template.md").exists()
    assert (target_templates / "README.template.md").exists()
    assert (target_templates / ".gitignore.template").exists()
    assert (target_templates / "docs.template").exists()
