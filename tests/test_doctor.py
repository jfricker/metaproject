"""Tests for `metaproject doctor` — checks, fixes, dry-run, guards, exit codes.

Spec: acceptance criteria 1–7 of the metaproject-doctor cycle. The conftest autouse
fixture isolates METAPROJECT_CONFIG_DIR and METAPROJECT_SKILL_DIR to tmp dirs and pins
METAPROJECT_AGENT=0, so these tests never touch the operator's real environment.
"""

from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from metaproject import db, templates
from metaproject.cli import app
from metaproject.config import (
    DEFAULT_LEARN_TARGETS,
    Config,
    LearnConfig,
    load_config,
    save_config,
)
from metaproject.doctor import run_checks
from metaproject.identity import Identity, read_identity, write_identity
from metaproject.skills import get_bundled_skill_dir, install_skill, is_skill_current


def _make_env(tmp_path: Path, learn_targets: list[str] | None = None) -> tuple[Config, Path]:
    """An initialized-looking environment: config file, seeded store, installed skill."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    store = tmp_path / "store"
    templates.seed_templates(store)
    install_skill()  # lands in the conftest-isolated METAPROJECT_SKILL_DIR
    cfg = Config(
        author="Test Operator",
        templates_dir=str(store),
        universe_db=str(tmp_path / "universe.db"),
        learn=LearnConfig(targets=learn_targets or list(DEFAULT_LEARN_TARGETS)),
    )
    config_file = config_dir / "config.json"
    save_config(cfg, config_file)
    return cfg, config_file


def _catalog_project(cfg: Config, project_dir: Path) -> None:
    """Insert a non-missing project row for project_dir into the catalog."""
    database = db.get_db(cfg.universe_db)
    db.upsert_project(
        database,
        {
            "name": project_dir.name,
            "path": str(project_dir),
            "relative_path": project_dir.name,
            "last_modified": "2026-09-15T00:00:00",
            "last_modified_ts": 1.0,
            "classification": "Active Now",
            "is_git": 0,
            "scanned_at": "2026-09-15T00:00:00",
            "scan_root": str(project_dir.parent),
        },
    )


def _all_yes(message: str) -> bool:
    return True


def _fail_if_called(message: str) -> bool:
    raise AssertionError(f"confirm prompted on a healthy environment: {message}")


# --------------------------------------------------------------------- templates


def test_missing_store_template_detected_restored_and_extra_kept(tmp_path: Path) -> None:
    """AC-1: dry-run reports without writing; confirmed run restores; extras survive."""
    cfg, config_file = _make_env(tmp_path)
    store = Path(cfg.templates_dir)
    victim = store / "intent.template.md"
    victim.unlink()
    extra = store / "learned-extra.template.md"
    extra.write_text("# learned content\n", encoding="utf-8")

    # Dry-run: findings reported, nothing written.
    results = run_checks(cfg, config_file, dry_run=True)
    templates_result = results[0]
    assert templates_result.name == "template store"
    assert not templates_result.healthy
    assert any("intent.template.md" in f for f in templates_result.findings)
    assert any("learned-extra.template.md" in f for f in templates_result.findings)
    assert not victim.exists()

    # Confirmed run: missing template restored, extra untouched, check healthy.
    results = run_checks(cfg, config_file, confirm=_all_yes)
    assert results[0].healthy is True
    assert results[0].fixed is True
    assert victim.is_file()
    assert extra.read_text(encoding="utf-8") == "# learned content\n"


# ------------------------------------------------------------------------ config


def test_config_migration_is_additive_and_preserves_pins(tmp_path: Path) -> None:
    """AC-2: missing core targets appended; existing pins kept in order."""
    pinned = ["AGENTS.md", "CLAUDE.md", "docs/", "Makefile", "my-custom-target"]
    cfg, config_file = _make_env(tmp_path, learn_targets=pinned)

    results = run_checks(cfg, config_file, confirm=_all_yes)
    config_result = results[1]
    assert config_result.fixed is True

    reloaded = load_config(config_file)
    targets = reloaded.learn.targets
    assert targets[:5] == pinned  # pins untouched, order preserved
    for core in ("intent.md", "spec.md", "STATE.md", "README.md", "ARCHITECTURE.md"):
        assert core in targets  # missing core targets appended


def test_config_check_healthy_when_current(tmp_path: Path) -> None:
    cfg, config_file = _make_env(tmp_path)
    results = run_checks(cfg, config_file, confirm=_fail_if_called)
    assert results[1].healthy is True


# -------------------------------------------------------------------------- skill


def test_stale_skill_refreshed_and_pruned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-3: divergent content rewritten, extra file pruned, bundled set restored."""
    skill_dir = tmp_path / "skills" / "metaproject"
    monkeypatch.setenv("METAPROJECT_SKILL_DIR", str(skill_dir))
    install_skill()
    (skill_dir / "SKILL.md").write_text("# hand-edited\n", encoding="utf-8")
    stray = skill_dir / "stray.md"
    stray.write_text("# not in the bundle\n", encoding="utf-8")

    cfg, config_file = _make_env(tmp_path)
    results = run_checks(cfg, config_file, confirm=_all_yes)

    assert results[2].fixed is True
    assert is_skill_current(get_bundled_skill_dir(), skill_dir) is True
    assert not stray.exists()


# ----------------------------------------------------------------------- identity


def test_identity_backfill_only_when_anchor_absent(tmp_path: Path) -> None:
    """AC-4: anchorless project gets identity; anchored project is never touched."""
    cfg, config_file = _make_env(tmp_path)
    anchorless = tmp_path / "projects" / "anchorless"
    anchored = tmp_path / "projects" / "anchored"
    anchorless.mkdir(parents=True)
    anchored.mkdir(parents=True)
    (anchorless / "README.md").write_text("# Anchorless\nA project.\n", encoding="utf-8")
    (anchored / "README.md").write_text("# Anchored\nExisting.\n", encoding="utf-8")
    write_identity(
        anchored,
        Identity(
            title="Kept",
            description="existing",
            author="whoever",
            created=date(2026, 1, 1),
            metaproject_version="0.6.0",
        ),
    )
    _catalog_project(cfg, anchorless)
    _catalog_project(cfg, anchored)

    results = run_checks(cfg, config_file, confirm=_all_yes)
    identity_result = results[3]
    assert identity_result.fixed is True

    new_identity = read_identity(anchorless)
    assert new_identity is not None
    assert new_identity.title == "Anchorless"
    assert new_identity.author == "Test Operator"
    kept = read_identity(anchored)
    assert kept is not None and kept.title == "Kept" and kept.metaproject_version == "0.6.0"


def test_identity_check_skips_vanished_project_dirs(tmp_path: Path) -> None:
    cfg, config_file = _make_env(tmp_path)
    vanished = tmp_path / "projects" / "gone"
    _catalog_project(cfg, vanished)  # cataloged but never created on disk

    results = run_checks(cfg, config_file, dry_run=True)
    assert not any("gone" in f for f in results[3].findings)


# ------------------------------------------------------------------- run behavior


def test_declined_fix_does_not_block_other_checks(tmp_path: Path) -> None:
    """R-DR-8: saying no to one check leaves the rest runnable and applied."""
    cfg, config_file = _make_env(tmp_path)
    (Path(cfg.templates_dir) / "intent.template.md").unlink()
    pinned = ["AGENTS.md"]
    cfg.learn.targets = pinned
    save_config(cfg, config_file)

    calls: list[str] = []

    def confirm_first_only(message: str) -> bool:
        calls.append(message)
        return len(calls) == 1

    results = run_checks(cfg, config_file, confirm=confirm_first_only)

    assert results[0].fixed is True  # templates fixed (first confirm accepted)
    assert results[1].fixed is None  # config declined
    assert results[1].healthy is False
    assert load_config(config_file).learn.targets == pinned


def test_healthy_environment_exits_zero_without_prompts(tmp_path: Path) -> None:
    """AC-5: fully current environment — exit 0, no prompts (run_checks-level check)."""
    cfg, config_file = _make_env(tmp_path)
    results = run_checks(cfg, config_file, confirm=_fail_if_called)
    assert all(r.healthy for r in results)


# ------------------------------------------------------------------- CLI surface


def _cli_env(config_file: Path) -> dict[str, str]:
    """Env pointing the CLI's config resolution at the test's config dir."""
    return {"METAPROJECT_CONFIG_DIR": str(config_file.parent)}


def test_cli_doctor_requires_initialization(runner: CliRunner, tmp_path: Path) -> None:
    """No config.json → error pointing at init, exit 1."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    result = runner.invoke(
        app, ["doctor", "--dry-run"], env={"METAPROJECT_CONFIG_DIR": str(empty_dir)}
    )
    assert result.exit_code == 1
    assert "init" in result.output


def test_cli_doctor_dry_run_reports_and_exits_nonzero(runner: CliRunner, tmp_path: Path) -> None:
    """R-DR-1/R-DR-7: dry-run writes nothing, exit 1 when findings exist."""
    cfg, config_file = _make_env(tmp_path)
    victim = Path(cfg.templates_dir) / "intent.template.md"
    victim.unlink()

    result = runner.invoke(app, ["doctor", "--dry-run"], env=_cli_env(config_file))
    assert result.exit_code == 1
    assert "intent.template.md" in result.output
    assert not victim.exists()


def test_cli_doctor_agent_session_rules(runner: CliRunner, tmp_path: Path) -> None:
    """R-DR-8: interactive doctor refuses in an agent session; dry-run still runs."""
    _, config_file = _make_env(tmp_path)

    refused = runner.invoke(
        app, ["doctor"], env={**_cli_env(config_file), "METAPROJECT_AGENT": "1"}
    )
    assert refused.exit_code == 1
    assert "needs an operator" in refused.output

    dry = runner.invoke(
        app, ["doctor", "--dry-run"], env={**_cli_env(config_file), "METAPROJECT_AGENT": "1"}
    )
    assert dry.exit_code == 0, dry.output  # healthy env: dry-run completes
    assert "Doctor" in dry.output


def test_cli_doctor_healthy_exit_zero(runner: CliRunner, tmp_path: Path) -> None:
    _, config_file = _make_env(tmp_path)
    result = runner.invoke(app, ["doctor", "--dry-run"], env=_cli_env(config_file))
    assert result.exit_code == 0, result.output
