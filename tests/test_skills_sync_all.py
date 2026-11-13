"""`metaproject skills status|sync --all` over the cataloged, managed projects (#4)."""

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from metaproject import catalog, db, doctor
from metaproject.cli import app
from metaproject.config import Config, save_config
from metaproject.scaffold import scaffold_project
from metaproject.skills import MANIFEST_NAME, file_map
from tests.test_extras import run_core
from tests.test_skills_sync import _tree

# ------------------------------------------------------------------------ helpers


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    """A config in its own dir with a universe.db beside it; the CLI resolves to it."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config = Config(
        author="Test Operator",
        templates_dir=str(tmp_path / "store"),
        universe_db=str(config_dir / "universe.db"),
    )
    save_config(config, config_dir / "config.json")
    monkeypatch.setenv("METAPROJECT_CONFIG_DIR", str(config_dir))
    return config


def _catalog(cfg: Config, project_dir: Path) -> None:
    database = db.get_db(cfg.universe_db)
    db.upsert_project(
        database,
        {
            "name": project_dir.name,
            "path": str(project_dir),
            "relative_path": project_dir.name,
            "last_modified": "2026-11-01T00:00:00",
            "last_modified_ts": 1.0,
            "classification": "Active",
            "is_git": 0,
            "scanned_at": "2026-11-01T00:00:00",
            "scan_root": str(project_dir.parent),
        },
    )


def _project(cfg: Config, root: Path, name: str, outdated: bool = True) -> Path:
    """A scaffolded, cataloged project whose `wrapup` skill is a pristine old copy."""
    proj = root / name
    scaffold_project(project_name=name, output=proj, interactive=False, no_git=True)
    if outdated:
        skills_root = proj / ".agents" / "skills"
        dest = skills_root / "wrapup"
        (dest / "SKILL.md").write_text("# wrapup from release 0.1.0\n", encoding="utf-8")
        manifest = json.loads((skills_root / MANIFEST_NAME).read_text(encoding="utf-8"))
        manifest["skills"]["wrapup"] = {"release": "0.1.0", "files": file_map(dest)}
        (skills_root / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    _catalog(cfg, proj)
    return proj


def _wrapup(proj: Path) -> str:
    return (proj / ".agents" / "skills" / "wrapup" / "SKILL.md").read_text(encoding="utf-8")


def _flat(output: str) -> str:
    return " ".join(output.split())


# ----------------------------------------------------------------- sync --all


def test_sync_all_updates_outdated_skill_in_every_managed_project(
    runner: CliRunner, cfg: Config, tmp_path: Path
) -> None:
    a = _project(cfg, tmp_path, "alpha")
    b = _project(cfg, tmp_path, "beta")

    result = runner.invoke(app, ["skills", "sync", "--all", "--yes"])

    assert result.exit_code == 0, result.output
    for proj in (a, b):
        assert "release 0.1.0" not in _wrapup(proj)
    out = _flat(result.output)
    assert "updated 1" in out
    assert "Total: 2 project(s) updated 2" in out


def test_sync_all_skips_unmanaged_and_vanished_projects(
    runner: CliRunner, cfg: Config, tmp_path: Path
) -> None:
    managed = _project(cfg, tmp_path, "managed")
    unmanaged = tmp_path / "unmanaged"
    unmanaged.mkdir()
    _catalog(cfg, unmanaged)
    _catalog(cfg, tmp_path / "gone")

    assert catalog.managed_projects(cfg) == [managed]
    result = runner.invoke(app, ["skills", "sync", "--all", "--yes"])

    assert result.exit_code == 0, result.output
    assert "1 project(s)" in _flat(result.output)
    assert list(unmanaged.iterdir()) == []
    assert not (tmp_path / "gone").exists()


def test_sync_all_keeps_a_modified_skill_byte_identical(
    runner: CliRunner, cfg: Config, tmp_path: Path
) -> None:
    proj = _project(cfg, tmp_path, "alpha", outdated=False)
    edited = proj / ".agents" / "skills" / "wrapup" / "SKILL.md"
    edited.write_text("# my own wrapup\n", encoding="utf-8")
    before = edited.read_bytes()

    result = runner.invoke(app, ["skills", "sync", "--all", "--yes"])

    assert result.exit_code == 0, result.output
    assert edited.read_bytes() == before
    assert "kept-modified 1" in _flat(result.output)


def test_sync_all_dry_run_writes_nothing(runner: CliRunner, cfg: Config, tmp_path: Path) -> None:
    a = _project(cfg, tmp_path, "alpha")
    b = _project(cfg, tmp_path, "beta")
    before = (_tree(a), _tree(b))

    result = runner.invoke(app, ["skills", "sync", "--all", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert (_tree(a), _tree(b)) == before
    assert "(dry run)" in result.output


def test_sync_all_web_profile_is_a_notice(
    runner: CliRunner, cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = _project(cfg, tmp_path, "alpha")
    before = _tree(proj)
    monkeypatch.setenv("METAPROJECT_PROFILE", "web")

    for args in (["sync", "--all", "--yes"], ["status", "--all"]):
        result = runner.invoke(app, ["skills", *args])
        assert result.exit_code == 0, result.output
        assert "not available in web sessions" in _flat(result.output)
    assert _tree(proj) == before


def test_sync_all_in_agent_session_reports_until_yes(
    runner: CliRunner, cfg: Config, tmp_path: Path
) -> None:
    proj = _project(cfg, tmp_path, "alpha")
    before = _tree(proj)
    agent = {"METAPROJECT_AGENT": "1"}

    reported = runner.invoke(app, ["skills", "sync", "--all"], env=agent)
    assert reported.exit_code == 0, reported.output
    assert _tree(proj) == before
    assert "metaproject skills sync --all --yes" in _flat(reported.output)

    applied = runner.invoke(app, ["skills", "sync", "--all", "--yes"], env=agent)
    assert applied.exit_code == 0, applied.output
    assert "release 0.1.0" not in _wrapup(proj)


def test_sync_all_at_a_terminal_asks_once(runner: CliRunner, cfg: Config, tmp_path: Path) -> None:
    proj = _project(cfg, tmp_path, "alpha")
    before = _tree(proj)

    declined = runner.invoke(app, ["skills", "sync", "--all"], input="n\n")
    assert declined.exit_code == 0, declined.output
    assert "Sync skills in 1 project(s)?" in declined.output
    assert _tree(proj) == before

    accepted = runner.invoke(app, ["skills", "sync", "--all"], input="y\n")
    assert accepted.exit_code == 0, accepted.output
    assert "release 0.1.0" not in _wrapup(proj)


@pytest.mark.parametrize(
    "args",
    [
        ["skills", "sync", "--all", "--dir", "."],
        ["skills", "sync", "--all", "--force", "wrapup"],
        ["skills", "status", "--all", "--dir", "."],
    ],
)
def test_all_with_a_single_project_option_is_a_usage_error(
    runner: CliRunner, cfg: Config, args
) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 2, result.output


def test_sync_all_empty_catalog(runner: CliRunner, cfg: Config) -> None:
    for command in ("sync", "status"):
        result = runner.invoke(app, ["skills", command, "--all"])
        assert result.exit_code == 0, result.output
        assert "No cataloged projects" in result.output
    assert not Path(cfg.universe_db).exists()


def test_one_refused_project_does_not_stop_the_rest(
    runner: CliRunner, cfg: Config, tmp_path: Path
) -> None:
    broken = _project(cfg, tmp_path, "alpha")
    good = _project(cfg, tmp_path, "beta")
    link = broken / ".claude" / "skills"
    link.unlink()
    link.mkdir()
    broken_before = _tree(broken / ".agents")

    result = runner.invoke(app, ["skills", "sync", "--all", "--yes"])

    assert result.exit_code == 1, result.output
    out = _flat(result.output)
    assert "refused" in out
    assert "failed 1" in out
    assert _tree(broken / ".agents") == broken_before
    assert "release 0.1.0" not in _wrapup(good)


def test_one_raising_project_does_not_stop_the_rest(
    runner: CliRunner, cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from metaproject import skills

    bad = _project(cfg, tmp_path, "alpha")
    good = _project(cfg, tmp_path, "beta")
    real = skills.sync_project_skills

    def flaky(project, **kwargs):
        if Path(project) == bad:
            raise OSError("disk on fire")
        return real(project, **kwargs)

    monkeypatch.setattr(skills, "sync_project_skills", flaky)
    result = runner.invoke(app, ["skills", "sync", "--all", "--yes"])

    assert result.exit_code == 1, result.output
    assert "disk on fire" in _flat(result.output)
    assert "release 0.1.0" not in _wrapup(good)


def test_sync_all_never_runs_git(runner: CliRunner, cfg: Config, tmp_path: Path) -> None:
    proj = _project(cfg, tmp_path, "alpha")
    git = ["git", "-C", str(proj)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run(
        [*git, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
        check=True,
    )
    head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout

    result = runner.invoke(app, ["skills", "sync", "--all", "--yes"])

    assert result.exit_code == 0, result.output
    after = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    assert after == head
    staged = subprocess.run(
        [*git, "diff", "--cached", "--name-only"], capture_output=True, text=True
    )
    assert staged.stdout == ""
    assert "release 0.1.0" not in _wrapup(proj)


def test_sync_all_without_tui_extra(tmp_path: Path) -> None:
    for command in ("sync", "status"):
        result = run_core(["skills", command, "--all"], tmp_path)
        assert result.returncode == 1, result.stdout + result.stderr
        out = _flat(result.stdout + result.stderr)
        assert "sqlite-utils" in out and "tui" in out
        assert "Traceback" not in out


def test_sync_all_json(runner: CliRunner, cfg: Config, tmp_path: Path) -> None:
    _project(cfg, tmp_path, "alpha")
    result = runner.invoke(app, ["skills", "sync", "--all", "--yes", "--format", "json"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["totals"]["updated"] == 1
    assert body["failed"] == 0
    assert len(body["projects"]) == 1


# --------------------------------------------------------------- status --all


def test_status_all_one_row_per_project_read_only_in_agent_session(
    runner: CliRunner, cfg: Config, tmp_path: Path
) -> None:
    a = _project(cfg, tmp_path, "alpha")
    b = _project(cfg, tmp_path, "beta")
    before = (_tree(a), _tree(b))

    result = runner.invoke(
        app,
        ["skills", "status", "--all", "--format", "json"],
        env={"METAPROJECT_AGENT": "1"},
    )

    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)["projects"]
    assert sorted(row["project"] for row in rows) == sorted([str(a), str(b)])
    assert (_tree(a), _tree(b)) == before

    table = runner.invoke(app, ["skills", "status", "--all"], env={"COLUMNS": "200"})
    assert table.exit_code == 0, table.output
    assert "2 managed project(s)" in table.output


# ------------------------------------------------------------- shared catalog


def test_doctor_and_skills_share_the_managed_set(cfg: Config, tmp_path: Path) -> None:
    managed = _project(cfg, tmp_path, "managed", outdated=False)
    plain = tmp_path / "plain"
    plain.mkdir()
    _catalog(cfg, plain)

    assert catalog.managed_projects(cfg) == [managed]
    assert doctor._managed_projects(cfg) == catalog.managed_projects(cfg)
    assert catalog.is_managed(managed) and not catalog.is_managed(plain)


def test_managed_projects_does_not_create_a_missing_catalog(tmp_path: Path) -> None:
    config = Config(templates_dir=str(tmp_path / "s"), universe_db=str(tmp_path / "u.db"))
    assert catalog.managed_projects(config) == []
    assert not (tmp_path / "u.db").exists()
