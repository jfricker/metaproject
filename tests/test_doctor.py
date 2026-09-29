"""Tests for `metaproject doctor` — checks, fixes, dry-run, guards, exit codes.

Spec: acceptance criteria 1–7 of the metaproject-doctor cycle. The conftest autouse
fixture isolates METAPROJECT_CONFIG_DIR to a tmp dir and pins
METAPROJECT_AGENT=0, so these tests never touch the operator's real environment.
"""

from datetime import date
from pathlib import Path

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


def _make_env(tmp_path: Path, learn_targets: list[str] | None = None) -> tuple[Config, Path]:
    """An initialized-looking environment: config file and a seeded store."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    store = tmp_path / "store"
    templates.seed_templates(store)
    cfg = Config(
        author="Test Operator",
        templates_dir=str(store),
        universe_db=str(tmp_path / "universe.db"),
        learn=LearnConfig(targets=learn_targets or list(DEFAULT_LEARN_TARGETS)),
    )
    config_file = config_dir / "config.json"
    save_config(cfg, config_file)
    return cfg, config_file


def _check(results, name: str):
    """The one check result named `name` — lookups by name survive check reordering."""
    (match,) = [result for result in results if result.name == name]
    return match


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
    victim = store / "docs.template" / "INTENT.template.md"
    victim.unlink()
    extra = store / "learned-extra.template.md"
    extra.write_text("# learned content\n", encoding="utf-8")

    # Dry-run: findings reported, nothing written.
    results = run_checks(cfg, config_file, dry_run=True)
    templates_result = _check(results, "template store")
    assert templates_result.name == "template store"
    assert not templates_result.healthy
    assert any("docs.template/INTENT.template.md" in f for f in templates_result.findings)
    assert any("learned-extra.template.md" in f for f in templates_result.findings)
    assert not victim.exists()

    # Confirmed run: missing template restored, extra untouched, check healthy.
    results = run_checks(cfg, config_file, confirm=_all_yes)
    assert _check(results, "template store").healthy is True
    assert _check(results, "template store").fixed is True
    assert victim.is_file()
    assert extra.read_text(encoding="utf-8") == "# learned content\n"


# ------------------------------------------------------------------------ config


def test_config_migration_is_additive_and_preserves_pins(tmp_path: Path) -> None:
    """AC-2: missing core targets appended; existing pins kept in order."""
    pinned = ["AGENTS.md", "CLAUDE.md", "docs/", "Makefile", "my-custom-target"]
    cfg, config_file = _make_env(tmp_path, learn_targets=pinned)

    results = run_checks(cfg, config_file, confirm=_all_yes)
    config_result = _check(results, "config (learn.targets)")
    assert config_result.fixed is True

    reloaded = load_config(config_file)
    targets = reloaded.learn.targets
    assert targets[:5] == pinned  # pins untouched, order preserved
    for core in (
        "docs/INTENT.md",
        "docs/SPEC.md",
        "docs/STATE.md",
        "README.md",
        "docs/ARCHITECTURE.md",
    ):
        assert core in targets  # missing core targets appended


def test_config_check_healthy_when_current(tmp_path: Path) -> None:
    cfg, config_file = _make_env(tmp_path)
    results = run_checks(cfg, config_file, confirm=_fail_if_called)
    assert _check(results, "config (learn.targets)").healthy is True


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
    identity_result = _check(results, "project identity")
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
    assert not any("gone" in f for f in _check(results, "project identity").findings)


# ------------------------------------------------------------------- run behavior


def test_declined_fix_does_not_block_other_checks(tmp_path: Path) -> None:
    """R-DR-8: saying no to one check leaves the rest runnable and applied."""
    cfg, config_file = _make_env(tmp_path)
    (Path(cfg.templates_dir) / "docs.template" / "INTENT.template.md").unlink()
    pinned = ["AGENTS.md"]
    cfg.learn.targets = pinned
    save_config(cfg, config_file)

    calls: list[str] = []

    def confirm_first_only(message: str) -> bool:
        calls.append(message)
        return len(calls) == 1

    results = run_checks(cfg, config_file, confirm=confirm_first_only)

    assert (
        _check(results, "template store").fixed is True
    )  # templates fixed (first confirm accepted)
    assert _check(results, "config (learn.targets)").fixed is None  # config declined
    assert _check(results, "config (learn.targets)").healthy is False
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
    victim = Path(cfg.templates_dir) / "docs.template" / "INTENT.template.md"
    victim.unlink()

    result = runner.invoke(app, ["doctor", "--dry-run"], env=_cli_env(config_file))
    assert result.exit_code == 1
    assert "INTENT.template.md" in result.output
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


# ------------------------------------------------------------- relocation (R-DRX)

import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

import pytest  # noqa: E402

from metaproject.deliverables import LEGACY_NAMES, template_path  # noqa: E402
from metaproject.doctor import _relocate  # noqa: E402
from metaproject.git import init_repository  # noqa: E402
from metaproject.skills import bundled_skills, install_project_skills  # noqa: E402

_OLD_DOC_TEXT = {old: f"# {old} — the project's real content\n" for old in LEGACY_NAMES}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


def _legacy_store(cfg: Config) -> Path:
    """Put the seeded store's cycle templates back at the root under their old names, as
    a pre-docs/ store had them, and git-back it."""
    store = Path(cfg.templates_dir)
    for old, new in LEGACY_NAMES.items():
        (store / template_path(new)).rename(store / template_path(old))
    init_repository(store, commit_message="chore: legacy store")
    return store


def _legacy_project(cfg: Config, root: Path, name: str, git_repo: bool = True) -> Path:
    """A managed project with its cycle documents at the root under old names."""
    project = root / name
    project.mkdir(parents=True)
    write_identity(
        project,
        Identity(
            title=name,
            description="",
            author="T",
            created=date(2026, 9, 1),
            metaproject_version="0.8.0",
        ),
    )
    for old, text in _OLD_DOC_TEXT.items():
        (project / old).write_text(text, encoding="utf-8")
    if git_repo:
        init_repository(project, commit_message="chore: legacy project")
    _catalog_project(cfg, project)
    return project


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    return home_dir


def _full_fixture(tmp_path: Path, home: Path):
    """AC-9: legacy store, old learn.targets, a project with root docs, a project missing
    (and with one stale) skill, and an orphaned ~/.claude/skills/metaproject/."""
    cfg, config_file = _make_env(
        tmp_path, learn_targets=["AGENTS.md", "intent.md", "design.md", "docs/", "Makefile"]
    )
    store = _legacy_store(cfg)
    (store / "hand-notes.md").write_text("unrelated, uncommitted\n", encoding="utf-8")

    docs_project = _legacy_project(cfg, tmp_path / "projects", "docs_proj")

    skills_project = tmp_path / "projects" / "skills_proj"
    skills_project.mkdir(parents=True)
    write_identity(
        skills_project,
        Identity(
            title="skills_proj",
            description="",
            author="T",
            created=date(2026, 9, 1),
            metaproject_version="0.8.0",
        ),
    )
    install_project_skills(skills_project)
    shutil.rmtree(skills_project / ".agents" / "skills" / "generate-spec")
    stale = skills_project / ".agents" / "skills" / "wrapup" / "SKILL.md"
    stale.write_text("# locally edited wrapup\n", encoding="utf-8")
    _catalog_project(cfg, skills_project)

    orphan = home / ".claude" / "skills" / "metaproject"
    orphan.mkdir(parents=True)
    (orphan / "SKILL.md").write_text("old global copy\n", encoding="utf-8")
    (home / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")

    return cfg, config_file, store, docs_project, skills_project, stale, orphan


def _snapshot(*roots: Path) -> dict:
    out = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if ".git" in path.parts:
                continue
            out[path] = path.read_bytes() if path.is_file() else None
    return out


def test_ac9_dry_run_reports_every_finding_and_writes_nothing(tmp_path: Path, home: Path) -> None:
    cfg, config_file, store, docs_project, skills_project, _, orphan = _full_fixture(tmp_path, home)
    before = _snapshot(store, docs_project, skills_project, home, config_file.parent)
    store_head = _git(store, "rev-parse", "HEAD")

    results = run_checks(cfg, config_file, dry_run=True, confirm=_fail_if_called)
    by_name = {r.name: r for r in results}

    layout = by_name["template store layout"]
    assert "move intent.template.md → docs.template/INTENT.template.md" in layout.findings
    assert "move design.template.md → docs.template/TECH-DESIGN.template.md" in layout.findings
    # The layout owns these; the store check neither re-seeds nor calls them extras.
    assert by_name["template store"].findings == [
        "extra in store (kept, learned or hand-added): hand-notes.md"
    ]
    assert any(
        "intent.md → docs/INTENT.md" in f for f in by_name["config (learn.targets)"].findings
    )
    assert by_name["orphaned global skill"].findings
    docs = by_name[f"project docs: {docs_project}"]
    assert "move intent.md → docs/INTENT.md" in docs.findings
    assert "move design.md → docs/TECH-DESIGN.md" in docs.findings
    skills_result = by_name[f"project skills: {skills_project}"]
    assert "missing skill: generate-spec" in skills_result.findings
    assert any("stale skill" in f and "wrapup" in f for f in skills_result.findings)
    # docs_proj has no skills at all: every declared skill is missing.
    missing_all = by_name[f"project skills: {docs_project}"].findings
    assert len(missing_all) == len(bundled_skills())

    assert _snapshot(store, docs_project, skills_project, home, config_file.parent) == before
    assert _git(store, "rev-parse", "HEAD") == store_head


def test_ac9_confirmed_fixes_migrate_everything_and_second_run_is_clean(
    tmp_path: Path, home: Path
) -> None:
    cfg, config_file, store, docs_project, skills_project, stale, orphan = _full_fixture(
        tmp_path, home
    )
    stale_bytes = stale.read_bytes()
    commits_before = int(_git(store, "rev-list", "--count", "HEAD"))

    run_checks(cfg, config_file, confirm=_all_yes)

    # Store: moved with git mv, exactly one new commit, unrelated dirty file untouched.
    assert (store / "docs.template" / "INTENT.template.md").is_file()
    assert not (store / "intent.template.md").exists()
    assert int(_git(store, "rev-list", "--count", "HEAD")) == commits_before + 1
    changed = _git(store, "show", "--name-status", "--format=", "HEAD")
    assert "R100\tintent.template.md\tdocs.template/INTENT.template.md" in changed
    assert "hand-notes.md" not in changed
    assert "?? hand-notes.md" in _git(store, "status", "--porcelain")

    # Config: legacy targets rewritten in place, order kept, no duplicates.
    targets = load_config(config_file).learn.targets
    assert targets[:5] == [
        "AGENTS.md",
        "docs/INTENT.md",
        "docs/TECH-DESIGN.md",
        "docs/",
        "Makefile",
    ]
    assert len(targets) == len(set(targets))
    assert "intent.md" not in targets

    # Project docs: moved, content intact, history preserved (git mv), not committed.
    for old, new in LEGACY_NAMES.items():
        assert (docs_project / new).read_text(encoding="utf-8") == _OLD_DOC_TEXT[old]
        assert old not in os.listdir(docs_project)
    status = _git(docs_project, "status", "--porcelain")
    assert "R  intent.md -> docs/INTENT.md" in status
    assert int(_git(docs_project, "rev-list", "--count", "HEAD")) == 1

    # Skills: missing installed, stale left byte-identical.
    assert (skills_project / ".agents" / "skills" / "generate-spec" / "SKILL.md").is_file()
    assert stale.read_bytes() == stale_bytes
    assert (docs_project / ".agents" / "skills" / "write-intent" / "SKILL.md").is_file()

    # Orphan removed; nothing else under ~/.claude touched.
    assert not orphan.exists()
    assert (home / ".claude" / "settings.json").is_file()

    # Second run: only the stale skill remains, as a report-only finding (the store's
    # hand-added extra is information, not a defect), and nothing prompts.
    second = run_checks(cfg, config_file, confirm=_fail_if_called)
    unhealthy = [r for r in second if not r.healthy]
    assert [r.name for r in unhealthy] == [f"project skills: {skills_project}"]
    assert unhealthy[0].findings == unhealthy[0].report_only


def test_ac10_existing_docs_file_is_a_conflict_both_kept(tmp_path: Path) -> None:
    cfg, config_file = _make_env(tmp_path)
    project = _legacy_project(cfg, tmp_path / "projects", "clash", git_repo=False)
    (project / "docs").mkdir()
    (project / "docs" / "INTENT.md").write_text("# already migrated\n", encoding="utf-8")

    results = run_checks(cfg, config_file, confirm=_all_yes)
    docs = next(r for r in results if r.name == f"project docs: {project}")

    assert "conflict: intent.md kept; docs/INTENT.md already exists" in docs.findings
    assert docs.healthy is False
    assert (project / "intent.md").read_text(encoding="utf-8") == _OLD_DOC_TEXT["intent.md"]
    assert (project / "docs" / "INTENT.md").read_text(encoding="utf-8") == "# already migrated\n"
    # The rest still moved (plain rename: not a git project).
    assert (project / "docs" / "SPEC.md").is_file()


def test_declining_one_project_does_not_block_the_next(tmp_path: Path) -> None:
    """R-DRX-7: per-project confirmation."""
    cfg, config_file = _make_env(tmp_path)
    first = _legacy_project(cfg, tmp_path / "projects", "a_first", git_repo=False)
    second = _legacy_project(cfg, tmp_path / "projects", "b_second", git_repo=False)

    def decline_first(message: str) -> bool:
        return str(first) not in message

    run_checks(cfg, config_file, confirm=decline_first)

    assert (first / "intent.md").is_file()
    assert (second / "docs" / "INTENT.md").is_file()


def test_unmanaged_project_is_never_migrated(tmp_path: Path) -> None:
    """Only projects with `.metaproject.json` are in scope (R-DRX-3/4)."""
    cfg, config_file = _make_env(tmp_path)
    project = tmp_path / "projects" / "foreign"
    project.mkdir(parents=True)
    (project / "intent.md").write_text("x\n", encoding="utf-8")
    _catalog_project(cfg, project)

    # Declining the identity backfill keeps it unmanaged (accepting it would make it
    # managed, and then in scope for the project checks that follow).
    results = run_checks(cfg, config_file, confirm=lambda message: "identity" not in message)

    assert not any(str(project) in r.name for r in results)
    assert (project / "intent.md").is_file()


def test_relocate_case_only_rename_goes_through_an_interim_name(tmp_path: Path) -> None:
    """R-NFR-6: `docs/intent.md` → `docs/INTENT.md` really changes the entry's case."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "intent.md").write_text("mine\n", encoding="utf-8")

    assert _relocate(tmp_path, "docs/intent.md", "docs/INTENT.md", git_repo=False) is None

    assert os.listdir(tmp_path / "docs") == ["INTENT.md"]
    assert (tmp_path / "docs" / "INTENT.md").read_text(encoding="utf-8") == "mine\n"


def test_relocate_case_only_rename_in_git(tmp_path: Path) -> None:
    project = tmp_path / "gitcase"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "intent.md").write_text("mine\n", encoding="utf-8")
    init_repository(project)

    assert _relocate(project, "docs/intent.md", "docs/INTENT.md", git_repo=True) is None

    assert os.listdir(project / "docs") == ["INTENT.md"]
    assert "docs/INTENT.md" in _git(project, "ls-files")


def test_orphaned_global_skill_symlink_is_unlinked_not_followed(tmp_path: Path, home: Path) -> None:
    cfg, config_file = _make_env(tmp_path)
    real = tmp_path / "elsewhere"
    real.mkdir()
    (real / "SKILL.md").write_text("keep me\n", encoding="utf-8")
    link = home / ".claude" / "skills" / "metaproject"
    link.parent.mkdir(parents=True)
    link.symlink_to(real)

    run_checks(cfg, config_file, confirm=_all_yes)

    assert not link.is_symlink() and not link.exists()
    assert (real / "SKILL.md").read_text(encoding="utf-8") == "keep me\n"


def test_default_confirm_asks_and_respects_no(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the default confirm must *ask* the question. `questionary.confirm`
    returns a (truthy) Question object, so calling it without `.ask()` applied every
    fix unprompted (R-NFR-2)."""
    import questionary

    cfg, config_file = _make_env(tmp_path)
    victim = Path(cfg.templates_dir) / "docs.template" / "INTENT.template.md"
    victim.unlink()
    asked: list[str] = []

    class _Declined:
        def ask(self) -> bool:
            return False

    def fake_confirm(message: str, **kwargs):
        asked.append(message)
        return _Declined()

    monkeypatch.setattr(questionary, "confirm", fake_confirm)

    run_checks(cfg, config_file)

    assert asked, "doctor must prompt before fixing"
    assert not victim.exists()
