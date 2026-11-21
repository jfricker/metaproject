"""Project config at `.metaproject/config.json` and the user store at `settings.json`:
legacy fallback, doctor migrations, review reporting and CLI warnings (R-CFG, R-STORE,
R-HOOK-2)."""

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from metaproject import catalog, doctor, hooks, templates
from metaproject.cli import app
from metaproject.config import (
    CONFIG_FILENAME,
    DEFAULT_LEARN_TARGETS,
    LEGACY_CONFIG_FILENAME,
    Config,
    LearnConfig,
    get_config_dir,
    get_config_file_path,
    load_config,
    save_config,
)
from metaproject.identity import IDENTITY_FILE, LEGACY_IDENTITY_FILE, read_settings
from metaproject.review import review_project
from metaproject.scaffold import adopt_project
from metaproject.universe import is_project_root

IDENTITY = {
    "title": "Proj",
    "description": "d",
    "author": "Ada",
    "created": "2026-01-02",
    "metaproject_version": "0.9.1",
}


def _legacy(path: Path, data: dict | None = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data or IDENTITY, indent=2) + "\n"
    (path / LEGACY_IDENTITY_FILE).write_text(text, encoding="utf-8")
    return path


def _new(path: Path, data: dict | None = None) -> Path:
    (path / ".metaproject").mkdir(parents=True, exist_ok=True)
    (path / IDENTITY_FILE).write_text(json.dumps(data or IDENTITY) + "\n", encoding="utf-8")
    return path


def _git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True, check=True
    ).stdout


def _git_init(path: Path) -> None:
    _git(path, "init", "-q")
    _git(path, "-c", "user.name=T", "-c", "user.email=t@e", "add", "-A")
    _git(path, "-c", "user.name=T", "-c", "user.email=t@e", "commit", "-qm", "init")


def _yes(_message: str) -> bool:
    return True


# ------------------------------------------------------------------ project config


def test_adopt_writes_the_new_path_only(tmp_path: Path) -> None:
    """AC-1: a fresh adopt creates `.metaproject/config.json` and no legacy file."""
    adopt_project(tmp_path, author="Ada", templates_dir=templates.get_bundled_templates_dir())
    assert (tmp_path / IDENTITY_FILE).is_file()
    assert not (tmp_path / LEGACY_IDENTITY_FILE).exists()


def test_adopt_keeps_a_legacy_config_where_it_is(tmp_path: Path) -> None:
    """Only doctor moves the legacy file."""
    _legacy(tmp_path)
    adopt_project(tmp_path, author="Ada", templates_dir=templates.get_bundled_templates_dir())
    assert (tmp_path / LEGACY_IDENTITY_FILE).is_file()
    assert not (tmp_path / IDENTITY_FILE).exists()


def test_legacy_only_project_is_managed_and_a_universe_root(tmp_path: Path) -> None:
    """AC-2."""
    proj = _legacy(tmp_path / "p")
    assert catalog.is_managed(proj)
    assert is_project_root(proj)
    assert read_settings(proj)["title"] == "Proj"


def test_bare_dot_metaproject_is_not_a_universe_root(tmp_path: Path) -> None:
    """AC-4."""
    proj = tmp_path / "p"
    (proj / ".metaproject" / "docs").mkdir(parents=True)
    assert not is_project_root(proj)
    assert not catalog.is_managed(proj)


def test_doctor_moves_a_legacy_config_byte_for_byte(tmp_path: Path) -> None:
    """AC-6: legacy only → move, content preserved."""
    proj = _legacy(tmp_path / "p", {**IDENTITY, "commands": {"lint": "make lint"}})
    before = (proj / LEGACY_IDENTITY_FILE).read_bytes()
    findings, report_only, _ = doctor.check_project_config(proj)
    assert findings == [f"move {LEGACY_IDENTITY_FILE} → {IDENTITY_FILE}"]
    assert report_only == []
    doctor.fix_project_config(proj)
    assert not (proj / LEGACY_IDENTITY_FILE).exists()
    assert (proj / IDENTITY_FILE).read_bytes() == before
    assert doctor.check_project_config(proj)[0] == []


def test_doctor_move_uses_git_mv_when_tracked(tmp_path: Path) -> None:
    proj = _legacy(tmp_path / "p")
    _git_init(proj)
    doctor.fix_project_config(proj)
    status = _git(proj, "status", "--porcelain")
    assert f"R  {LEGACY_IDENTITY_FILE} -> {IDENTITY_FILE}" in status


def test_doctor_removes_an_identical_legacy_copy(tmp_path: Path) -> None:
    proj = _new(_legacy(tmp_path / "p"))
    findings, report_only, _ = doctor.check_project_config(proj)
    assert findings and "remove redundant" in findings[0]
    assert report_only == []
    doctor.fix_project_config(proj)
    assert not (proj / LEGACY_IDENTITY_FILE).exists()
    assert json.loads((proj / IDENTITY_FILE).read_text(encoding="utf-8")) == IDENTITY


def test_doctor_reports_a_differing_pair_and_changes_nothing(tmp_path: Path) -> None:
    proj = _new(_legacy(tmp_path / "p"), {**IDENTITY, "title": "Other", "e2e_port": 1})
    legacy_bytes = (proj / LEGACY_IDENTITY_FILE).read_bytes()
    new_bytes = (proj / IDENTITY_FILE).read_bytes()
    findings, report_only, _ = doctor.check_project_config(proj)
    assert findings == report_only
    assert "differ (keys: e2e_port, title)" in findings[0]
    result = doctor._apply("project config", findings, "", lambda: None, False, _yes, report_only)
    assert result.fixed is None and not result.healthy
    assert (proj / LEGACY_IDENTITY_FILE).read_bytes() == legacy_bytes
    assert (proj / IDENTITY_FILE).read_bytes() == new_bytes


def test_scoped_doctor_migrates_a_legacy_project(tmp_path: Path) -> None:
    proj = _legacy(tmp_path / "p")
    results = doctor.run_checks(Config(), tmp_path / "settings.json", confirm=_yes, project=proj)
    config_check = next(r for r in results if r.name.startswith("project config"))
    assert config_check.fixed and config_check.healthy
    assert (proj / IDENTITY_FILE).is_file()
    assert not (proj / LEGACY_IDENTITY_FILE).exists()


def test_review_reports_the_legacy_config_as_out_of_date(tmp_path: Path) -> None:
    """AC-8."""
    proj = _legacy(tmp_path / "p")
    result = review_project(proj, templates_dir=templates.get_bundled_templates_dir())
    assert result.legacy[IDENTITY_FILE] == LEGACY_IDENTITY_FILE
    assert not result.is_current
    assert not result.is_clean


def test_review_of_a_migrated_project_has_no_config_legacy_entry(tmp_path: Path) -> None:
    proj = _new(tmp_path / "p")
    result = review_project(proj, templates_dir=templates.get_bundled_templates_dir())
    assert IDENTITY_FILE not in result.legacy


def test_cli_warns_once_about_a_legacy_project(tmp_path: Path) -> None:
    """R-CFG-6: a command resolving a legacy-only project points at doctor."""
    proj = _legacy(tmp_path / "p")
    result = CliRunner().invoke(app, ["skills", "status", "--dir", str(proj)])
    assert f"legacy {LEGACY_IDENTITY_FILE}" in result.output
    assert "metaproject doctor" in result.output


# ------------------------------------------------------------------- hook scripts


def test_doctor_refreshes_a_hook_script_that_predates_the_move(tmp_path: Path) -> None:
    """AC-9 / R-HOOK-2."""
    proj = _new(tmp_path / "p")
    old = proj / hooks.HOOK_SCRIPT_PATH
    old.parent.mkdir(parents=True)
    old.write_text('CONFIG_FILE = ".metaproject.json"\n', encoding="utf-8")
    findings, _, _ = doctor.check_project_hooks(proj)
    assert findings == [f"{hooks.HOOK_SCRIPT_PATH} predates .metaproject/config.json"]
    doctor.fix_project_hooks(proj)
    assert old.read_bytes() == hooks.get_bundled_hook_script().read_bytes()
    assert doctor.check_project_hooks(proj)[0] == []


def test_current_or_missing_hook_scripts_are_not_findings(tmp_path: Path) -> None:
    proj = _new(tmp_path / "p")
    assert doctor.check_project_hooks(proj)[0] == []
    hooks.install_hooks(proj)
    assert doctor.check_project_hooks(proj)[0] == []


# --------------------------------------------------------------------- user store


def test_new_store_file_is_settings_json(tmp_path: Path) -> None:
    assert CONFIG_FILENAME == "settings.json" and LEGACY_CONFIG_FILENAME == "config.json"
    assert get_config_file_path(tmp_path) == tmp_path / "settings.json"


def test_legacy_store_file_is_still_read(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(json.dumps({"author": "Old"}), encoding="utf-8")
    assert get_config_file_path(tmp_path) == tmp_path / "config.json"
    assert load_config(get_config_file_path(tmp_path)).author == "Old"
    (tmp_path / "settings.json").write_text(json.dumps({"author": "New"}), encoding="utf-8")
    assert get_config_file_path(tmp_path) == tmp_path / "settings.json"


def test_doctor_renames_the_legacy_store_file(tmp_path: Path) -> None:
    store = tmp_path / "store"
    templates.seed_templates(store)
    cfg = Config(
        templates_dir=str(store),
        universe_db=str(tmp_path / "u.db"),
        learn=LearnConfig(targets=list(DEFAULT_LEARN_TARGETS)),
    )
    config_dir = tmp_path / "cfg"
    save_config(cfg, config_dir / "config.json")
    results = doctor.run_checks(cfg, get_config_file_path(config_dir), confirm=_yes)
    check = next(r for r in results if r.name == "config file name")
    assert check.fixed and check.healthy
    assert (config_dir / "settings.json").is_file()
    assert not (config_dir / "config.json").exists()


def test_doctor_store_identical_and_differing_pairs(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text('{"author": "A"}', encoding="utf-8")
    (tmp_path / "settings.json").write_text('{"author":"A"}', encoding="utf-8")
    findings, report_only, _ = doctor.check_store_file(tmp_path)
    assert findings and report_only == []
    doctor.fix_store_file(tmp_path)
    assert not (tmp_path / "config.json").exists()

    (tmp_path / "config.json").write_text('{"author": "B"}', encoding="utf-8")
    findings, report_only, _ = doctor.check_store_file(tmp_path)
    assert findings == report_only and "keys: author" in findings[0]


def test_cli_warns_about_a_legacy_store_file(runner: CliRunner) -> None:
    """R-STORE-2."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    result = runner.invoke(app, ["universe", "summary"])
    assert "legacy user config name" in result.output
    assert "metaproject doctor" in result.output
