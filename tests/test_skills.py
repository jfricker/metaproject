"""Tests for bundled skill discovery, installation, and the `init` wiring."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.skills import (
    CURRENT,
    INSTALLED,
    STALE,
    UPDATED,
    get_bundled_skill_dir,
    get_skill_install_dir,
    install_skill,
    is_skill_current,
)


def test_bundled_skill_ships_with_the_package() -> None:
    """The skill is package data, so a plain install carries it."""
    skill_dir = get_bundled_skill_dir()
    assert (skill_dir / "SKILL.md").is_file()
    assert (skill_dir / "references" / "commands.md").is_file()
    assert (skill_dir / "references" / "documents.md").is_file()


def test_bundled_skill_declares_required_frontmatter() -> None:
    """Claude Code discovers a skill by its name and description frontmatter."""
    body = (get_bundled_skill_dir() / "SKILL.md").read_text(encoding="utf-8")
    assert body.startswith("---\n")
    frontmatter = body.split("---", 2)[1]
    assert "name: metaproject" in frontmatter
    assert "description:" in frontmatter


def test_skill_install_dir_honours_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The install location is overridable so nothing has to touch a real ~/.claude."""
    override = tmp_path / "somewhere" / "metaproject"
    monkeypatch.setenv("METAPROJECT_SKILL_DIR", str(override))
    assert get_skill_install_dir() == override.resolve()

    monkeypatch.delenv("METAPROJECT_SKILL_DIR")
    assert get_skill_install_dir() == (Path.home() / ".claude" / "skills" / "metaproject").resolve()


def test_install_skill_writes_then_reports_current(tmp_path: Path) -> None:
    """A first install writes every file; a second run recognises it is already current."""
    target = tmp_path / "skills" / "metaproject"

    first = install_skill(target_dir=target)
    assert first["state"] == INSTALLED
    assert (target / "SKILL.md").is_file()
    assert (target / "references" / "commands.md").is_file()
    assert len(first["files"]) >= 3

    second = install_skill(target_dir=target)
    assert second["state"] == CURRENT
    assert second["files"] == []
    assert is_skill_current(get_bundled_skill_dir(), target) is True


def test_install_skill_refuses_to_clobber_a_divergent_copy(tmp_path: Path) -> None:
    """An edited or outdated copy is the operator's to overwrite, not init's."""
    target = tmp_path / "skills" / "metaproject"
    install_skill(target_dir=target)
    (target / "SKILL.md").write_text("# hand-edited\n", encoding="utf-8")

    stale = install_skill(target_dir=target)
    assert stale["state"] == STALE
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "# hand-edited\n"

    forced = install_skill(target_dir=target, force=True)
    assert forced["state"] == UPDATED
    assert "name: metaproject" in (target / "SKILL.md").read_text(encoding="utf-8")


def test_cli_init_installs_the_skill(runner: CliRunner, tmp_path: Path) -> None:
    """`metaproject init` lands the skill where Claude Code will find it."""
    config_dir = tmp_path / ".metaproject"
    skill_dir = tmp_path / ".claude" / "skills" / "metaproject"

    result = runner.invoke(
        app,
        ["init", "--config-dir", str(config_dir), "--force"],
        env={"METAPROJECT_SKILL_DIR": str(skill_dir)},
    )

    assert result.exit_code == 0, result.output
    assert (skill_dir / "SKILL.md").is_file()
    assert "skill" in result.output.lower()


def test_cli_init_no_skill_opts_out(runner: CliRunner, tmp_path: Path) -> None:
    """--no-skill leaves the skill directory alone."""
    config_dir = tmp_path / ".metaproject"
    skill_dir = tmp_path / ".claude" / "skills" / "metaproject"

    result = runner.invoke(
        app,
        ["init", "--config-dir", str(config_dir), "--force", "--no-skill"],
        env={"METAPROJECT_SKILL_DIR": str(skill_dir)},
    )

    assert result.exit_code == 0, result.output
    assert not skill_dir.exists()
