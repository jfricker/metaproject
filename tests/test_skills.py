"""Tests for the bundled project skills, their create-only install, and `init`."""

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.review import backfill_missing
from metaproject.scaffold import TransactionalTracker, scaffold_project
from metaproject.skills import (
    CURRENT,
    INSTALLED,
    MISSING,
    STALE,
    bundled_skills,
    get_bundled_skill_dir,
    install_project_skills,
    is_skill_current,
    legacy_global_skill_dir,
    project_skills_dir,
    skill_state,
)

SDLC_SKILLS = {
    "backlog-new",
    "write-intent",
    "generate-spec",
    "generate-design",
    "generate-plan",
    "implement-plan",
    "execute-tests",
    "wrapup",
}
ALL_SKILLS = SDLC_SKILLS | {"metaproject"}


def _scaffold(tmp_path: Path, name: str = "demo") -> Path:
    proj = tmp_path / name
    scaffold_project(project_name=name, output=proj, interactive=False, no_git=True)
    return proj


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


def test_bundled_skills_is_the_single_declaration_of_nine() -> None:
    """R-SKL-1: the metaproject skill plus the eight SDLC skills, sorted by name."""
    declared = bundled_skills()
    names = [skill.name for skill in declared]
    assert set(names) == ALL_SKILLS
    assert names == sorted(names)
    for skill in declared:
        assert (skill.source_dir / "SKILL.md").is_file()


def test_legacy_global_skill_dir_follows_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert legacy_global_skill_dir() == tmp_path / ".claude" / "skills" / "metaproject"


# ------------------------------------------------------------------------------- new


def test_ac3_new_installs_every_skill_reachable_through_claude_skills(tmp_path: Path) -> None:
    """AC-3 (R-SKL-2): all nine skills under .agents/skills, visible via .claude/skills."""
    proj = tmp_path / "demo"
    result = scaffold_project(project_name="demo", output=proj, interactive=False, no_git=True)

    assert result["skills"].states == {name: INSTALLED for name in sorted(ALL_SKILLS)}
    for name in ALL_SKILLS:
        assert (proj / ".agents" / "skills" / name / "SKILL.md").is_file()
        assert (proj / ".claude" / "skills" / name / "SKILL.md").is_file()
    for skill in bundled_skills():
        assert is_skill_current(skill.source_dir, proj / ".agents" / "skills" / skill.name)


def test_new_dry_run_lists_skills_and_writes_nothing(tmp_path: Path) -> None:
    """R-SKL-2: `--dry-run` reports what would be installed and writes nothing."""
    proj = tmp_path / "dry"
    result = scaffold_project(
        project_name="dry", output=proj, interactive=False, no_git=True, dry_run=True
    )
    assert set(result["skills"].named(INSTALLED)) == ALL_SKILLS
    assert not proj.exists()


def test_new_commits_skills_and_never_gitignores_them(tmp_path: Path) -> None:
    """R-SKL-6: skills are ordinary project files, included in `new`'s initial commit."""
    import subprocess

    proj = tmp_path / "gitproj"
    result = scaffold_project(project_name="gitproj", output=proj, interactive=False)
    assert result["git_initialized"] is True

    tracked = subprocess.run(
        ["git", "ls-files", ".agents/skills"],
        cwd=proj,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    for name in ALL_SKILLS:
        assert f".agents/skills/{name}/SKILL.md" in tracked
    assert ".agents" not in (proj / ".gitignore").read_text(encoding="utf-8")


def test_rollback_removes_installed_skills(tmp_path: Path) -> None:
    """Every skill file and directory written is recorded for rollback."""
    proj = tmp_path / "rb"
    proj.mkdir()
    tracker = TransactionalTracker()
    tracker.record_existing(proj)
    install_project_skills(proj, tracker=tracker)
    assert (proj / ".agents" / "skills" / "wrapup" / "SKILL.md").is_file()

    tracker.rollback()

    assert list(proj.iterdir()) == []


# -------------------------------------------------------------------------- backfill


def test_ac4_backfill_recreates_only_a_deleted_skill_then_is_idempotent(tmp_path: Path) -> None:
    """AC-4 (R-SKL-3/4): first run recreates just the deleted skill; second writes nothing;
    an edited skill is stale and left byte-identical."""
    import shutil

    proj = _scaffold(tmp_path)
    skills_root = proj / ".agents" / "skills"
    shutil.rmtree(skills_root / "write-intent")
    edited = skills_root / "wrapup" / "SKILL.md"
    edited.write_text("# my local wrapup\n", encoding="utf-8")
    edited_bytes = edited.read_bytes()

    first = backfill_missing(proj)
    assert first.skills["write-intent"] == INSTALLED
    assert first.skills["wrapup"] == STALE
    assert [name for name, state in first.skills.items() if state == INSTALLED] == ["write-intent"]
    assert (skills_root / "write-intent" / "SKILL.md").is_file()
    assert edited.read_bytes() == edited_bytes

    snapshot = {p: p.read_bytes() for p in skills_root.rglob("*") if p.is_file()}
    second = backfill_missing(proj)
    assert INSTALLED not in second.skills.values()
    assert second.skills["write-intent"] == CURRENT
    assert {p: p.read_bytes() for p in skills_root.rglob("*") if p.is_file()} == snapshot


def test_backfill_never_adds_files_inside_an_existing_skill(tmp_path: Path) -> None:
    """A skill directory missing one of its files is stale, and is not topped up."""
    proj = _scaffold(tmp_path)
    ref = proj / ".agents" / "skills" / "metaproject" / "references" / "commands.md"
    ref.unlink()

    result = backfill_missing(proj)

    assert result.skills["metaproject"] == STALE
    assert not ref.exists()


def test_backfill_named_files_never_implies_skills(tmp_path: Path) -> None:
    """R-SKL-3: naming files touches only those files."""
    import shutil

    proj = _scaffold(tmp_path)
    shutil.rmtree(proj / ".agents" / "skills" / "write-intent")
    (proj / "docs" / "HANDOFF.md").unlink(missing_ok=True)

    result = backfill_missing(proj, files=["HANDOFF.md"])

    assert result.skills == {}
    assert not (proj / ".agents" / "skills" / "write-intent").exists()


def test_cli_backfill_reports_skills(runner: CliRunner, tmp_path: Path) -> None:
    import shutil

    proj = _scaffold(tmp_path)
    shutil.rmtree(proj / ".agents" / "skills" / "generate-plan")
    result = runner.invoke(app, ["backfill", "--dir", str(proj)])
    assert result.exit_code == 0, result.output
    assert "generate-plan" in result.output
    assert (proj / ".agents" / "skills" / "generate-plan" / "SKILL.md").is_file()


# ------------------------------------------------------------------ R-SKL-5 refusals


def test_ac5_real_claude_skills_directory_refuses_skills_not_deliverables(
    runner: CliRunner, tmp_path: Path
) -> None:
    """AC-5: `.claude/skills` as a real directory — no skill written, one notice, the
    other deliverables still created."""
    proj = tmp_path / "occupied"
    (proj / ".claude" / "skills").mkdir(parents=True)
    (proj / "README.md").write_text("# Occupied\n", encoding="utf-8")

    result = runner.invoke(app, ["backfill", "--dir", str(proj)])

    assert result.exit_code == 0, result.output
    assert "real directory" in result.output
    assert not (proj / ".agents" / "skills").exists()
    assert (proj / "docs" / "INTENT.md").is_file()
    assert list((proj / ".claude" / "skills").iterdir()) == []


def test_ac5_new_dot_with_real_claude_skills_still_scaffolds(tmp_path: Path) -> None:
    """`new .` into a project whose `.claude/skills` is a real directory."""
    proj = tmp_path / "existing"
    (proj / ".claude" / "skills").mkdir(parents=True)
    (proj / "main.py").write_text("print()\n", encoding="utf-8")

    result = scaffold_project(
        project_name=".", output=str(proj) + "/", interactive=False, backfill=True, no_git=True
    )

    assert result["skills"].states == {}
    assert "real directory" in result["skills"].notice
    assert not (proj / ".agents" / "skills" / "wrapup").exists()
    assert (proj / "docs" / "STATE.md").is_file()


def test_symlink_elsewhere_is_refused(tmp_path: Path) -> None:
    proj = tmp_path / "linked"
    elsewhere = tmp_path / "shared-skills"
    elsewhere.mkdir()
    (proj / ".claude").mkdir(parents=True)
    os.symlink(elsewhere, proj / ".claude" / "skills")

    target = project_skills_dir(proj)
    assert target.refusal is not None and "symlink" in target.refusal
    report = install_project_skills(proj)
    assert report.states == {} and report.notice
    assert list(elsewhere.iterdir()) == []


def test_skill_state_reports_missing_current_stale(tmp_path: Path) -> None:
    skill = next(s for s in bundled_skills() if s.name == "write-intent")
    dest = tmp_path / "write-intent"
    assert skill_state(skill, dest) == MISSING
    install_project_skills(tmp_path / "p")
    installed = tmp_path / "p" / ".agents" / "skills" / "write-intent"
    assert skill_state(skill, installed) == CURRENT
    (installed / "SKILL.md").write_text("x", encoding="utf-8")
    assert skill_state(skill, installed) == STALE


# ------------------------------------------------------------------------------ init


def test_ac6_init_writes_nothing_under_claude(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-6 (R-INI-1/2): `init` in a temp HOME creates no `~/.claude` entry."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    config_dir = home / ".metaproject"

    result = runner.invoke(app, ["init", "--config-dir", str(config_dir), "--force"])

    assert result.exit_code == 0, result.output
    assert not (home / ".claude").exists()


def test_ac6_init_rejects_no_skill(runner: CliRunner, tmp_path: Path) -> None:
    """`--no-skill` is gone: an unknown option."""
    result = runner.invoke(
        app, ["init", "--config-dir", str(tmp_path / "cfg"), "--force", "--no-skill"]
    )
    assert result.exit_code == 2
    assert "No such option" in result.output


def test_skill_docs_cover_the_7_stage_cycle_and_classes() -> None:
    """spec.md R-DOC-1, AC-12a: SKILL.md and documents.md name the required concepts."""
    skill_dir = get_bundled_skill_dir()
    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    documents_md = (skill_dir / "references" / "documents.md").read_text(encoding="utf-8")

    required_terms = [
        "write-intent",
        "wrapup",
        "working",
        "governance",
        ".metaproject.json",
        "<Title>",
        "metaproject backfill",
    ]
    for term in required_terms:
        assert term in skill_md, f"SKILL.md missing {term!r}"
        assert term in documents_md, f"documents.md missing {term!r}"

    commands_md = (skill_dir / "references" / "commands.md").read_text(encoding="utf-8")
    assert "## backfill" in commands_md
