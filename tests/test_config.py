"""Tests for configuration loading, saving, and template resource discovery."""

from pathlib import Path

import pytest

from metaproject.config import DEFAULT_LEARN_MODEL, Config, LearnConfig, load_config, save_config
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


def test_default_learn_config() -> None:
    """Verify Config carries learn defaults per spec.md §4.2."""
    cfg = Config()
    assert isinstance(cfg.learn, LearnConfig)
    assert cfg.learn.targets == [
        "README.md",
        "AGENTS.md",
        "CLAUDE.md",
        "intent.md",
        "STATE.md",
        "HANDOFF.md",
        ".gitignore",
        "docs/",
        "Makefile",
        "pyproject.toml",
    ]
    assert cfg.learn.resurface_factor == 2.0
    assert cfg.learn.model == DEFAULT_LEARN_MODEL
    assert cfg.learn.activity_weights == {
        "Active Now": 1.0,
        "Active Near": 0.8,
        "Active Far": 0.6,
        "Idle": 0.4,
        "Ancient": 0.2,
        "Archived": 0.1,
    }


def test_config_round_trip_without_learn_key(tmp_path: Path) -> None:
    """A config file written without a 'learn' key still loads and gets learn defaults."""
    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"author": "Bob", "default_branch": "main", "project_home": "'
        + str(tmp_path / "workspaces").replace("\\", "\\\\")
        + '"}',
        encoding="utf-8",
    )
    loaded = load_config(config_file)
    assert loaded.author == "Bob"
    assert isinstance(loaded.learn, LearnConfig)
    assert loaded.learn.resurface_factor == 2.0
    assert loaded.learn.targets[0] == "README.md"


def test_config_round_trip_with_learn_key(tmp_path: Path) -> None:
    """A config file written with a custom 'learn' key round-trips faithfully."""
    config_file = tmp_path / "config.json"
    cfg = Config(
        author="Carol",
        learn=LearnConfig(
            targets=["AGENTS.md"],
            resurface_factor=3.5,
            model="claude-opus",
            activity_weights={"Active Now": 1.0, "Archived": 0.05},
        ),
    )
    save_config(cfg, config_file)

    loaded = load_config(config_file)
    assert loaded.learn.targets == ["AGENTS.md"]
    assert loaded.learn.resurface_factor == 3.5
    assert loaded.learn.model == "claude-opus"
    assert loaded.learn.activity_weights == {"Active Now": 1.0, "Archived": 0.05}


def test_config_to_dict_serializes_learn_block(tmp_path: Path) -> None:
    """to_dict()/json round-trip includes the nested learn block as a plain dict."""
    cfg = Config()
    data = cfg.to_dict()
    assert "learn" in data
    assert isinstance(data["learn"], dict)
    assert data["learn"]["resurface_factor"] == 2.0


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
