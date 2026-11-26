"""`metaproject skills status|sync`, the install manifest, and the skill ledger (#3, 3b)."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from metaproject import skills as skills_module
from metaproject import treeops
from metaproject.cli import app
from metaproject.doctor import check_project_skills, fix_project_skills
from metaproject.exceptions import MetaProjectError
from metaproject.review import backfill_missing
from metaproject.scaffold import TransactionalTracker, adopt_project, scaffold_project
from metaproject.skills import (
    CURRENT,
    FORCED,
    INSTALLED,
    KEPT,
    MANIFEST_NAME,
    MISSING,
    MODIFIED,
    OUTDATED,
    RECORDED,
    STAGING_NAME,
    UPDATED,
    bundled_skills,
    inspect_project_skills,
    load_manifest,
    render_manifest,
    running_release,
    skill_digest,
    sync_project_skills,
)
from metaproject.treeops import file_map, hash_content

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------------ helpers


def _scaffold(tmp_path: Path, name: str = "demo") -> Path:
    proj = tmp_path / name
    scaffold_project(project_name=name, output=proj, interactive=False, no_git=True)
    return proj


def _skills_root(proj: Path) -> Path:
    return proj / ".agents" / "skills"


def _manifest(proj: Path) -> dict:
    return json.loads((_skills_root(proj) / MANIFEST_NAME).read_text(encoding="utf-8"))


def _write_manifest(proj: Path, entries: dict, version: int = 1) -> None:
    body = {"version": version, "skills": entries}
    (_skills_root(proj) / MANIFEST_NAME).write_text(json.dumps(body), encoding="utf-8")


def _tree(path: Path) -> dict:
    """Every entry under `path` with its bytes (files) or its link target."""
    out = {}
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            out[item.relative_to(path).as_posix()] = ("link", os.readlink(item))
        elif item.is_file():
            out[item.relative_to(path).as_posix()] = item.read_bytes()
        else:
            out[item.relative_to(path).as_posix()] = "dir"
    return out


def _make_outdated_via_manifest(proj: Path, name: str = "wrapup") -> Path:
    """Turn `name` into a pristine copy of a fictional earlier release."""
    dest = _skills_root(proj) / name
    (dest / "SKILL.md").write_text("# wrapup from release 0.1.0\n", encoding="utf-8")
    data = _manifest(proj)
    data["skills"][name] = {"release": "0.1.0", "files": file_map(dest)}
    (_skills_root(proj) / MANIFEST_NAME).write_text(json.dumps(data), encoding="utf-8")
    return dest


def _state(report, name: str):
    return next(status for status in report.statuses if status.name == name)


# ------------------------------------------------------------------------ hashing


def test_file_map_skips_junk_and_normalises_crlf(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        (d / "references").mkdir(parents=True)
    (a / "SKILL.md").write_bytes(b"line one\nline two\n")
    (b / "SKILL.md").write_bytes(b"line one\r\nline two\r\n")
    (a / "references" / "x.md").write_text("x", encoding="utf-8")
    (b / "references" / "x.md").write_text("x", encoding="utf-8")
    for junk in (".DS_Store", "._SKILL.md", "SKILL.md~"):
        (b / junk).write_text("junk", encoding="utf-8")

    assert file_map(a) == file_map(b)
    assert list(file_map(a)) == ["SKILL.md", "references/x.md"]

    (b / "extra.md").write_text("more", encoding="utf-8")
    assert file_map(a) != file_map(b)


def test_binary_content_is_not_normalised() -> None:
    assert hash_content(b"\0a\r\nb") != hash_content(b"\0a\nb")
    assert hash_content(b"a\r\nb") == hash_content(b"a\nb")


def test_symlink_inside_skill_never_matches(tmp_path: Path) -> None:
    d = tmp_path / "s"
    d.mkdir()
    (d / "real.md").write_text("x", encoding="utf-8")
    os.symlink(d / "real.md", d / "link.md")
    assert file_map(d)["link.md"] == treeops.NON_REGULAR


# ------------------------------------------------------------------ install paths


def test_new_writes_manifest_for_every_skill(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    data = _manifest(proj)
    assert data["version"] == 2
    assert set(data["skills"]) == {skill.name for skill in bundled_skills()}
    for skill in bundled_skills():
        entry = data["skills"][skill.name]
        assert entry["release"] == running_release()
        assert entry["files"] == file_map(skill.source_dir)
    text = (_skills_root(proj) / MANIFEST_NAME).read_text(encoding="utf-8")
    assert text == render_manifest(data["skills"], data["bridges"])
    assert not (proj / ".agents" / STAGING_NAME).exists()


def test_new_dry_run_writes_no_manifest(tmp_path: Path) -> None:
    proj = tmp_path / "dry"
    scaffold_project(project_name="dry", output=proj, interactive=False, no_git=True, dry_run=True)
    assert not proj.exists()


def test_rollback_removes_manifest_and_skills(tmp_path: Path) -> None:
    proj = tmp_path / "rb"
    proj.mkdir()
    tracker = TransactionalTracker()
    tracker.record_existing(proj)
    sync_project_skills(proj, update=False, tracker=tracker)
    assert (_skills_root(proj) / MANIFEST_NAME).is_file()
    tracker.rollback()
    assert list(proj.iterdir()) == []


def test_adopt_records_manifest_and_second_run_changes_nothing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Repo\n", encoding="utf-8")
    adopt_project(repo)
    manifest = _skills_root(repo) / MANIFEST_NAME
    assert set(_manifest(repo)["skills"]) == {s.name for s in bundled_skills()}
    before = (manifest.read_bytes(), manifest.stat().st_mtime_ns)

    adopt_project(repo)

    assert (manifest.read_bytes(), manifest.stat().st_mtime_ns) == before


def test_backfill_records_manifest_for_a_legacy_install(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    manifest = _skills_root(proj) / MANIFEST_NAME
    manifest.unlink()

    result = backfill_missing(proj)

    assert set(result.skills.values()) == {CURRENT}
    assert set(_manifest(proj)["skills"]) == {s.name for s in bundled_skills()}
    before = (manifest.read_bytes(), manifest.stat().st_mtime_ns)
    backfill_missing(proj)
    assert (manifest.read_bytes(), manifest.stat().st_mtime_ns) == before


def test_backfill_with_named_files_touches_neither_skills_nor_manifest(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    manifest = _skills_root(proj) / MANIFEST_NAME
    manifest.unlink()
    shutil.rmtree(_skills_root(proj) / "write-intent")
    (proj / ".metaproject" / "docs" / "HANDOFF.md").unlink(missing_ok=True)

    result = backfill_missing(proj, files=["HANDOFF.md"])

    assert result.skills == {}
    assert not manifest.exists()
    assert not (_skills_root(proj) / "write-intent").exists()


def test_backfill_does_not_update_outdated_skills(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    dest = _make_outdated_via_manifest(proj)
    before = _tree(dest)

    result = backfill_missing(proj)

    assert result.skills["wrapup"] == OUTDATED
    assert _tree(dest) == before


# --------------------------------------------------------------------- states


def test_states_missing_current_outdated_and_modified(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    root = _skills_root(proj)
    shutil.rmtree(root / "write-intent")
    _make_outdated_via_manifest(proj, "wrapup")
    (root / "generate-spec" / "SKILL.md").write_text("# mine\n", encoding="utf-8")
    (root / "generate-plan" / "notes.md").write_text("added\n", encoding="utf-8")
    (root / "metaproject" / "references" / "commands.md").unlink()

    report = inspect_project_skills(proj)

    assert report.manifest_state == "present"
    assert report.states["write-intent"] == MISSING
    assert report.states["backlog-new"] == CURRENT
    assert _state(report, "wrapup").state == OUTDATED
    assert _state(report, "wrapup").basis == "manifest"
    assert _state(report, "wrapup").installed_release == "0.1.0"
    assert _state(report, "wrapup").changed == ("SKILL.md",)
    for name, changed in (
        ("generate-spec", ("SKILL.md",)),
        ("generate-plan", ("notes.md",)),
        ("metaproject", ("references/commands.md",)),
    ):
        assert _state(report, name).state == MODIFIED
        assert _state(report, name).changed == changed


def test_status_is_read_only(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    (_skills_root(proj) / MANIFEST_NAME).unlink()
    shutil.rmtree(_skills_root(proj) / "wrapup")
    before = _tree(proj)
    inspect_project_skills(proj)
    assert _tree(proj) == before


def test_legacy_identical_is_current_and_sync_records(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    (_skills_root(proj) / MANIFEST_NAME).unlink()

    report = inspect_project_skills(proj)
    assert report.manifest_state == "absent"
    assert set(report.states.values()) == {CURRENT}
    assert {s.basis for s in report.statuses} == {"bundle"}

    synced = sync_project_skills(proj)
    assert {s.action for s in synced.statuses} == {RECORDED}
    assert set(_manifest(proj)["skills"]) == {s.name for s in bundled_skills()}


def test_legacy_ledger_match_is_outdated_and_sync_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = _scaffold(tmp_path)
    (_skills_root(proj) / MANIFEST_NAME).unlink()
    dest = _skills_root(proj) / "wrapup"
    (dest / "SKILL.md").write_text("# wrapup as shipped in 0.0.1\n", encoding="utf-8")
    ledger = {"wrapup": {skill_digest(file_map(dest)): "0.0.1"}}
    monkeypatch.setattr(skills_module, "load_history", lambda: ledger)

    status = _state(inspect_project_skills(proj), "wrapup")
    assert (status.state, status.basis, status.installed_release) == (OUTDATED, "history", "0.0.1")

    synced = sync_project_skills(proj)
    assert _state(synced, "wrapup").action == UPDATED
    skill = next(s for s in bundled_skills() if s.name == "wrapup")
    assert file_map(dest) == file_map(skill.source_dir)


def test_legacy_no_match_is_modified_and_kept(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    (_skills_root(proj) / MANIFEST_NAME).unlink()
    dest = _skills_root(proj) / "wrapup"
    (dest / "SKILL.md").write_text("# my wrapup\n", encoding="utf-8")
    before = _tree(dest)

    synced = sync_project_skills(proj)

    status = _state(synced, "wrapup")
    assert (status.state, status.basis, status.action) == (MODIFIED, "none", KEPT)
    assert _tree(dest) == before
    assert "wrapup" not in _manifest(proj)["skills"]


def test_newer_release_guard_never_downgrades(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    dest = _skills_root(proj) / "wrapup"
    (dest / "SKILL.md").write_text("# wrapup from the future\n", encoding="utf-8")
    data = _manifest(proj)
    data["skills"]["wrapup"] = {"release": "99.0.0", "files": file_map(dest)}
    (_skills_root(proj) / MANIFEST_NAME).write_text(json.dumps(data), encoding="utf-8")
    before = _tree(dest)

    status = _state(sync_project_skills(proj), "wrapup")

    assert status.state == CURRENT
    assert status.note == "installed by newer release 99.0.0"
    assert status.action == KEPT
    assert _tree(dest) == before
    assert _manifest(proj)["skills"]["wrapup"]["release"] == "99.0.0"


# ----------------------------------------------------------------------- sync CLI


@pytest.mark.parametrize(
    "env",
    [{"CLAUDECODE": "1"}, {"CLAUDE_CODE_REMOTE": "true", "CLAUDECODE": "1"}],
    ids=["agent", "web"],
)
def test_sync_installs_updates_keeps_and_exits_zero(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: dict
) -> None:
    """Acceptance: install missing, update outdated, keep modified byte-identical, exit 0."""
    proj = _scaffold(tmp_path)
    root = _skills_root(proj)
    shutil.rmtree(root / "write-intent")
    _make_outdated_via_manifest(proj, "wrapup")
    mine = root / "generate-spec" / "SKILL.md"
    mine.write_text("# my spec skill\n", encoding="utf-8")
    mine_bytes = mine.read_bytes()
    monkeypatch.delenv("METAPROJECT_AGENT", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    result = runner.invoke(app, ["skills", "sync", "--dir", str(proj)])

    assert result.exit_code == 0, result.output
    assert "not available" not in result.output
    out = " ".join(result.output.split())
    assert "generate-spec" in out and "modified" in out
    assert (root / "write-intent" / "SKILL.md").is_file()
    wrapup = next(s for s in bundled_skills() if s.name == "wrapup")
    assert file_map(root / "wrapup") == file_map(wrapup.source_dir)
    assert mine.read_bytes() == mine_bytes
    assert _manifest(proj)["skills"]["wrapup"]["release"] == running_release()
    assert not (proj / ".agents" / STAGING_NAME).exists()


def test_force_replaces_only_the_named_skill(runner: CliRunner, tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    root = _skills_root(proj)
    for name in ("generate-spec", "generate-plan"):
        (root / name / "SKILL.md").write_text(f"# my {name}\n", encoding="utf-8")
    plan_before = _tree(root / "generate-plan")

    result = runner.invoke(
        app, ["skills", "sync", "--dir", str(proj), "--force", "generate-spec", "-f", "json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    actions = {s["name"]: s["action"] for s in payload["skills"]}
    assert actions["generate-spec"] == FORCED
    assert actions["generate-plan"] == KEPT
    spec = next(s for s in bundled_skills() if s.name == "generate-spec")
    assert file_map(root / "generate-spec") == file_map(spec.source_dir)
    assert _tree(root / "generate-plan") == plan_before


def test_force_unknown_name_exits_one_and_writes_nothing(runner: CliRunner, tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    shutil.rmtree(_skills_root(proj) / "wrapup")
    before = _tree(proj)

    result = runner.invoke(app, ["skills", "sync", "--dir", str(proj), "--force", "nope"])

    assert result.exit_code == 1
    assert "nope" in result.output
    assert _tree(proj) == before


def test_dry_run_reports_actions_and_writes_nothing(runner: CliRunner, tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    root = _skills_root(proj)
    shutil.rmtree(root / "write-intent")
    _make_outdated_via_manifest(proj, "wrapup")
    (root / MANIFEST_NAME).unlink()
    # Without a manifest wrapup would be modified; give it back as a recorded release.
    _write_manifest(proj, {"wrapup": {"release": "0.1.0", "files": file_map(root / "wrapup")}})
    before = _tree(proj)

    dry = sync_project_skills(proj, dry_run=True)

    assert _tree(proj) == before
    assert not (proj / ".agents" / STAGING_NAME).exists()
    actions = {s.name: s.action for s in dry.statuses}
    assert actions["write-intent"] == INSTALLED
    assert actions["wrapup"] == UPDATED
    assert actions["backlog-new"] == RECORDED

    real = sync_project_skills(proj)
    assert {s.name: s.action for s in real.statuses} == actions

    result = runner.invoke(app, ["skills", "sync", "--dir", str(proj), "--dry-run"])
    assert result.exit_code == 0, result.output


def test_dry_run_on_legacy_install_writes_no_manifest(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    (_skills_root(proj) / MANIFEST_NAME).unlink()
    sync_project_skills(proj, dry_run=True)
    assert not (_skills_root(proj) / MANIFEST_NAME).exists()


def test_failed_swap_restores_original_and_records_earlier_skills(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = _scaffold(tmp_path)
    root = _skills_root(proj)
    _make_outdated_via_manifest(proj, "generate-design")
    _make_outdated_via_manifest(proj, "wrapup")
    wrapup_before = _tree(root / "wrapup")
    real_rename = os.rename

    def failing_rename(src, dst):
        if Path(src).name == "wrapup.new":
            raise OSError("disk full")
        return real_rename(src, dst)

    monkeypatch.setattr(skills_module.os, "rename", failing_rename)

    result = runner.invoke(app, ["skills", "sync", "--dir", str(proj)])

    assert result.exit_code == 1
    assert "disk full" in result.output
    assert _tree(root / "wrapup") == wrapup_before
    assert not (proj / ".agents" / STAGING_NAME).exists()
    data = _manifest(proj)
    assert data["skills"]["generate-design"]["release"] == running_release()
    assert data["skills"]["wrapup"]["release"] == "0.1.0"


def test_crash_recovery_restores_old_copy(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    root = _skills_root(proj)
    staging = proj / ".agents" / STAGING_NAME
    staging.mkdir()
    os.rename(root / "wrapup", staging / "wrapup.old")
    (staging / "wrapup.new").mkdir()

    report = sync_project_skills(proj)

    assert _state(report, "wrapup").state == CURRENT
    assert (root / "wrapup" / "SKILL.md").is_file()
    assert not staging.exists()


def test_skill_changed_between_classify_and_swap_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = _scaffold(tmp_path)
    dest = _make_outdated_via_manifest(proj, "wrapup")
    real_copy = treeops._copy_tree

    def copy_then_edit(source_dir, out):
        real_copy(source_dir, out)
        if out.name == "wrapup.new":
            (dest / "SKILL.md").write_text("# edited mid-sync\n", encoding="utf-8")

    monkeypatch.setattr(treeops, "_copy_tree", copy_then_edit)

    status = _state(sync_project_skills(proj), "wrapup")

    assert (status.state, status.action) == (MODIFIED, KEPT)
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "# edited mid-sync\n"
    assert _manifest(proj)["skills"]["wrapup"]["release"] == "0.1.0"


def test_symlinked_skill_is_modified_and_force_replaces_the_link(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    root = _skills_root(proj)
    elsewhere = tmp_path / "shared-wrapup"
    shutil.copytree(root / "wrapup", elsewhere)
    shutil.rmtree(root / "wrapup")
    os.symlink(elsewhere, root / "wrapup")
    shared_before = _tree(elsewhere)

    assert _state(inspect_project_skills(proj), "wrapup").state == MODIFIED
    assert _state(sync_project_skills(proj), "wrapup").action == KEPT
    assert (root / "wrapup").is_symlink()

    forced = sync_project_skills(proj, force=["wrapup"])

    assert _state(forced, "wrapup").action == FORCED
    assert not (root / "wrapup").is_symlink() and (root / "wrapup").is_dir()
    assert _tree(elsewhere) == shared_before


@pytest.mark.parametrize("command", ["status", "sync"])
def test_refusals_exit_one_and_write_nothing(
    runner: CliRunner, tmp_path: Path, command: str
) -> None:
    """The only refusal left: `skills.location: root` with no ancestor project or git root."""
    proj = _scaffold(tmp_path, "nohome")
    cfg_path = proj / ".metaproject" / "config.json"
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    data["skills"] = {"location": "root"}
    cfg_path.write_text(json.dumps(data), encoding="utf-8")
    shutil.rmtree(_skills_root(proj))
    shutil.rmtree(proj / ".claude" / "skills")

    before = _tree(proj)
    result = runner.invoke(app, ["skills", command, "--dir", str(proj)])
    assert result.exit_code == 1, result.output
    assert _tree(proj) == before
    json_result = runner.invoke(app, ["skills", command, "--dir", str(proj), "-f", "json"])
    assert json_result.exit_code == 1
    payload = json.loads(json_result.stdout)
    assert payload["refusal"] and payload["skills"] == []
    assert _tree(proj) == before


@pytest.mark.parametrize("kind", ["dir", "foreign"])
def test_real_dir_or_foreign_link_no_longer_refuses_sync(
    runner: CliRunner, tmp_path: Path, kind: str
) -> None:
    proj = _scaffold(tmp_path, kind)
    skills_link = proj / ".claude" / "skills"
    shutil.rmtree(skills_link)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    if kind == "dir":
        skills_link.mkdir()
    else:
        os.symlink(elsewhere, skills_link)
    shutil.rmtree(_skills_root(proj) / "wrapup")
    result = runner.invoke(app, ["skills", "sync", "--dir", str(proj)])
    assert result.exit_code == 0, result.output
    assert (_skills_root(proj) / "wrapup" / "SKILL.md").is_file()
    assert list(elsewhere.iterdir()) == []
    assert (skills_link.is_symlink()) == (kind == "foreign")


def test_unreadable_manifest_is_noticed_and_rewritten(runner: CliRunner, tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    (_skills_root(proj) / MANIFEST_NAME).write_text("{not json", encoding="utf-8")

    status = runner.invoke(app, ["skills", "status", "--dir", str(proj)])
    assert status.exit_code == 0
    assert "could not be read" in " ".join(status.output.split())

    synced = runner.invoke(app, ["skills", "sync", "--dir", str(proj)])
    assert synced.exit_code == 0, synced.output
    assert load_manifest(_skills_root(proj)).state == "present"


def test_newer_manifest_status_works_sync_refuses(runner: CliRunner, tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    manifest = _skills_root(proj) / MANIFEST_NAME
    manifest.write_text(json.dumps({"version": 3, "skills": {"wrapup": "?"}}), encoding="utf-8")
    before = manifest.read_bytes()

    status = runner.invoke(app, ["skills", "status", "--dir", str(proj), "-f", "json"])
    assert status.exit_code == 0
    payload = json.loads(status.stdout)
    assert payload["manifest"] == "newer"
    assert {s["state"] for s in payload["skills"]} == {CURRENT}

    synced = runner.invoke(app, ["skills", "sync", "--dir", str(proj)])
    assert synced.exit_code == 1
    assert "newer metaproject" in " ".join(synced.output.split())
    assert manifest.read_bytes() == before

    # The create-only path still installs a missing skill and leaves the file alone.
    shutil.rmtree(_skills_root(proj) / "wrapup")
    assert backfill_missing(proj).skills["wrapup"] == INSTALLED
    assert manifest.read_bytes() == before


def test_retired_manifest_entries_are_preserved(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    retired = _skills_root(proj) / "old-skill"
    retired.mkdir()
    (retired / "SKILL.md").write_text("# retired\n", encoding="utf-8")
    data = _manifest(proj)
    data["skills"]["old-skill"] = {"release": "0.1.0", "files": file_map(retired)}
    (_skills_root(proj) / MANIFEST_NAME).write_text(json.dumps(data), encoding="utf-8")
    shutil.rmtree(_skills_root(proj) / "wrapup")

    sync_project_skills(proj)

    assert _manifest(proj)["skills"]["old-skill"]["release"] == "0.1.0"
    assert (retired / "SKILL.md").is_file()


def test_status_json_is_pure_and_table_has_glyphs(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = _scaffold(tmp_path)
    shutil.rmtree(_skills_root(proj) / "wrapup")
    (_skills_root(proj) / "generate-spec" / "SKILL.md").write_text("# mine\n", encoding="utf-8")

    result = runner.invoke(app, ["skills", "status", "--dir", str(proj), "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["target"] == ".agents/skills"
    assert payload["release"] == running_release()
    assert payload["manifest"] == "present"
    assert payload["dry_run"] is False and payload["refusal"] is None
    by_name = {s["name"]: s for s in payload["skills"]}
    assert by_name["wrapup"]["state"] == MISSING
    assert by_name["generate-spec"]["changed"] == ["SKILL.md"]
    assert all(s["action"] is None for s in payload["skills"])

    monkeypatch.setenv("NO_COLOR", "1")
    table = runner.invoke(app, ["skills", "status", "--dir", str(proj)])
    assert table.exit_code == 0
    assert "! missing" in table.output
    assert "~ modified" in table.output
    assert "✓ current" in table.output


def test_sync_json_reports_pre_pass_state_and_action(runner: CliRunner, tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    shutil.rmtree(_skills_root(proj) / "wrapup")
    result = runner.invoke(app, ["skills", "sync", "--dir", str(proj), "-f", "json"])
    assert result.exit_code == 0
    wrapup = next(s for s in json.loads(result.stdout)["skills"] if s["name"] == "wrapup")
    assert (wrapup["state"], wrapup["action"]) == (MISSING, INSTALLED)


def test_unmanaged_directory_exits_one_with_adopt_hint(runner: CliRunner, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    for command in ("status", "sync"):
        result = runner.invoke(app, ["skills", command, "--dir", str(plain)])
        assert result.exit_code == 1
        assert "metaproject adopt" in " ".join(result.output.split())
    assert list(plain.iterdir()) == []


def test_sync_without_claude_skills_creates_bridge_entries(
    runner: CliRunner, tmp_path: Path
) -> None:
    proj = _scaffold(tmp_path)
    shutil.rmtree(proj / ".claude" / "skills")
    result = runner.invoke(app, ["skills", "sync", "--dir", str(proj)])
    assert result.exit_code == 0
    entry = proj / ".claude" / "skills" / "wrapup"
    assert entry.is_symlink() and entry.resolve() == (_skills_root(proj) / "wrapup").resolve()
    assert not (proj / ".claude" / "skills").is_symlink()


def test_skills_is_its_own_group_not_a_learn_path(runner: CliRunner) -> None:
    result = runner.invoke(app, ["skills", "--help"])
    assert result.exit_code == 0
    assert "status" in result.output and "sync" in result.output


# ------------------------------------------------------------------------- ledger


def test_ledger_loads_from_package_and_covers_every_current_skill() -> None:
    import importlib.resources

    text = importlib.resources.files("metaproject").joinpath("skill_history.json").read_text()
    ledger = skills_module.parse_history(text)
    for skill in bundled_skills():
        digest = skill_digest(file_map(skill.source_dir))
        assert digest in ledger.get(skill.name, {}), (
            f"{skill.name} changed since the ledger was generated; run `make skill-history`"
        )


def test_ledger_generator_is_idempotent(tmp_path: Path) -> None:
    ledger = tmp_path / "skill_history.json"
    shutil.copy(ROOT / "src" / "metaproject" / "skill_history.json", ledger)
    before = ledger.read_bytes()
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_skill_history.py"), "--ledger", str(ledger)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert ledger.read_bytes() == before


# ------------------------------------------------------------------------- doctor


def test_doctor_fixes_outdated_and_reports_modified(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    root = _skills_root(proj)
    _make_outdated_via_manifest(proj, "wrapup")
    mine = root / "generate-spec" / "SKILL.md"
    mine.write_text("# mine\n", encoding="utf-8")
    shutil.rmtree(root / "write-intent")

    findings, report_only, summary = check_project_skills(proj)

    assert "missing skill: write-intent" in findings
    assert any("outdated skill" in f and "wrapup" in f for f in findings)
    modified = [f for f in findings if "modified skill" in f]
    assert len(modified) == 1 and "generate-spec" in modified[0]
    assert report_only == modified
    assert "1 missing" in summary and "1 outdated" in summary

    fix_project_skills(proj)

    findings, report_only, _ = check_project_skills(proj)
    assert findings == report_only == modified
    assert mine.read_text(encoding="utf-8") == "# mine\n"


def test_doctor_manifest_recording_alone_is_not_a_finding(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    (_skills_root(proj) / MANIFEST_NAME).unlink()
    findings, _, _ = check_project_skills(proj)
    assert findings == []


def test_doctor_dry_run_writes_nothing(tmp_path: Path) -> None:
    from metaproject.config import load_config
    from metaproject.doctor import run_checks

    proj = _scaffold(tmp_path)
    _make_outdated_via_manifest(proj, "wrapup")
    before = _tree(proj)

    def never(_message: str) -> bool:
        raise AssertionError("dry run must not prompt")

    results = run_checks(load_config(), Path("unused"), dry_run=True, confirm=never, project=proj)

    skills_result = next(r for r in results if r.name.startswith("project skills"))
    assert any("outdated skill" in f for f in skills_result.findings)
    assert _tree(proj) == before


def test_sync_api_rejects_unknown_force_before_any_write(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    (_skills_root(proj) / MANIFEST_NAME).unlink()
    with pytest.raises(MetaProjectError, match="unknown skill"):
        sync_project_skills(proj, force=["ghost"])
    assert not (_skills_root(proj) / MANIFEST_NAME).exists()


# ------------------------------------------------------------------ manifest v2


def test_v1_manifest_loads_without_bridges_and_sync_rewrites_as_v2(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    path = _skills_root(proj) / MANIFEST_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(
        json.dumps({"version": 1, "skills": data["skills"]}, indent=2) + "\n", encoding="utf-8"
    )
    loaded = load_manifest(_skills_root(proj))
    assert loaded.state == "present"
    assert loaded.bridges == {}
    sync_project_skills(proj)
    rewritten = json.loads(path.read_text(encoding="utf-8"))
    assert rewritten["version"] == 2
    assert rewritten["bridges"] == {}
    assert rewritten["skills"] == data["skills"]


def test_version_3_manifest_is_newer(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    path = _skills_root(proj) / MANIFEST_NAME
    path.write_text(json.dumps({"version": 3, "skills": {}}), encoding="utf-8")
    assert load_manifest(_skills_root(proj)).state == skills_module.MANIFEST_NEWER


def test_sync_preserves_existing_bridges(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    root = _skills_root(proj)
    path = root / MANIFEST_NAME
    bridges = {".claude/skills": {"kind": "symlink", "target": "../.agents/skills"}}
    data = json.loads(path.read_text(encoding="utf-8"))
    data["bridges"] = bridges
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    shutil.rmtree(root / "wrapup")
    sync_project_skills(proj)
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["bridges"] == bridges
    assert "wrapup" in after["skills"]
    assert load_manifest(root).bridges == bridges


# ------------------------------------------------------------ bridge pass (R-BRG)


def _bare(tmp_path: Path, name: str = "proj", skills: dict | None = None) -> Path:
    proj = tmp_path / name
    (proj / ".metaproject").mkdir(parents=True)
    body = {"skills": skills} if skills is not None else {}
    (proj / ".metaproject" / "config.json").write_text(json.dumps(body), encoding="utf-8")
    return proj


def _skills_dir(proj: Path) -> Path:
    return proj / ".claude" / "skills"


def _bridge_records(proj: Path, key: str = ".") -> dict:
    return _manifest(proj)["bridges"][key]["claude"]


def _age_skill(proj: Path, name: str) -> None:
    """Make `name` a pristine copy of an older release (source and manifest agree)."""
    dest = _skills_root(proj) / name
    (dest / "SKILL.md").write_text("old release\n", encoding="utf-8")
    manifest = _manifest(proj)
    manifest["skills"][name] = {"release": "0.0.1", "files": file_map(dest)}
    (_skills_root(proj) / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")


def test_real_claude_skills_dir_keeps_user_skills_and_skips_foreign_bundled(
    tmp_path: Path,
) -> None:
    proj = _bare(tmp_path)
    (_skills_dir(proj) / "my-skill").mkdir(parents=True)
    (_skills_dir(proj) / "my-skill" / "SKILL.md").write_text("mine\n", encoding="utf-8")
    (_skills_dir(proj) / "shipit").mkdir()
    (_skills_dir(proj) / "shipit" / "SKILL.md").write_text("foreign\n", encoding="utf-8")
    user_before = _tree(_skills_dir(proj) / "my-skill")
    foreign_before = _tree(_skills_dir(proj) / "shipit")

    report = sync_project_skills(proj)

    assert report.notice is None
    assert {s.action for s in report.statuses} == {INSTALLED}
    bridge = report.bridges["claude"]
    assert bridge.entries["shipit"]["action"] == "skipped"
    assert any("shipit" in w and "not managed" in w for w in bridge.warnings)
    for skill in bundled_skills():
        if skill.name != "shipit":
            assert (_skills_dir(proj) / skill.name).is_symlink()
    assert not (_skills_dir(proj) / "shipit").is_symlink()
    assert _tree(_skills_dir(proj) / "my-skill") == user_before
    assert _tree(_skills_dir(proj) / "shipit") == foreign_before
    assert "shipit" not in _bridge_records(proj)["entries"]

    forced = sync_project_skills(proj, force=["shipit"])
    assert forced.bridges["claude"].entries["shipit"]["action"] == "updated"
    assert (_skills_dir(proj) / "shipit").is_symlink()
    assert "shipit" in _bridge_records(proj)["entries"]
    assert _tree(_skills_dir(proj) / "my-skill") == user_before


def test_force_unknown_name_raises_before_any_write(tmp_path: Path) -> None:
    proj = _bare(tmp_path)
    with pytest.raises(MetaProjectError):
        sync_project_skills(proj, force=["nope"])
    assert not (proj / ".agents").exists() and not (proj / ".claude").exists()


@pytest.mark.parametrize("kind", ["symlink", "file"])
def test_foreign_claude_skills_symlink_or_file_installs_sources_only(
    tmp_path: Path, kind: str
) -> None:
    proj = _bare(tmp_path)
    (proj / ".claude").mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    if kind == "symlink":
        os.symlink(elsewhere, _skills_dir(proj))
    else:
        _skills_dir(proj).write_text("not a directory\n", encoding="utf-8")

    report = sync_project_skills(proj)

    assert report.notice is None
    assert {s.action for s in report.statuses} == {INSTALLED}
    assert report.bridges["claude"].notice
    assert report.bridges["claude"].removed == []
    assert list(elsewhere.iterdir()) == []
    if kind == "file":
        assert _skills_dir(proj).read_text(encoding="utf-8") == "not a directory\n"
    assert "bridges" not in _manifest(proj) or not _manifest(proj)["bridges"]


def test_delegating_subproject_records_bridges_in_the_home_manifest(tmp_path: Path) -> None:
    root = tmp_path / "mono"
    (root / ".git").mkdir(parents=True)
    (root / ".metaproject").mkdir()
    (root / ".metaproject" / "config.json").write_text("{}", encoding="utf-8")
    sub = _bare(root / "packages", "a", {"location": "root"})

    report = sync_project_skills(sub)

    assert report.location == "root" and report.home == root.resolve()
    assert not (sub / ".agents").exists()
    for skill in bundled_skills():
        entry = _skills_dir(sub) / skill.name
        assert entry.is_symlink()
        assert entry.resolve() == (root / ".agents" / "skills" / skill.name).resolve()
    records = _bridge_records(root, "packages/a")
    assert set(records["entries"]) == {s.name for s in bundled_skills()}
    assert "." not in _manifest(root)["bridges"]


def test_update_replaces_copy_entries_and_leaves_symlink_entries(tmp_path: Path) -> None:
    sym = _bare(tmp_path, "sym")
    cp = _bare(tmp_path, "cp", {"link_mode": "copy"})
    for proj in (sym, cp):
        sync_project_skills(proj)
        _age_skill(proj, "wrapup")
    # The copy entry is a pristine copy of the old source, as its record says.
    old = _skills_root(cp) / "wrapup"
    shutil.rmtree(_skills_dir(cp) / "wrapup")
    shutil.copytree(old, _skills_dir(cp) / "wrapup")
    manifest = _manifest(cp)
    manifest["bridges"]["."]["claude"]["entries"]["wrapup"]["files"] = file_map(old)
    (_skills_root(cp) / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    link_before = os.readlink(_skills_dir(sym) / "wrapup")

    for proj in (sym, cp):
        report = sync_project_skills(proj)
        assert report.states["wrapup"] == UPDATED

    bundled = file_map(next(s.source_dir for s in bundled_skills() if s.name == "wrapup"))
    assert os.readlink(_skills_dir(sym) / "wrapup") == link_before
    assert file_map(_skills_root(sym) / "wrapup") == bundled
    assert file_map(_skills_dir(cp) / "wrapup") == bundled
    assert not (_skills_dir(cp) / "wrapup").is_symlink()


def test_newer_manifest_version_writes_no_bridges(tmp_path: Path) -> None:
    proj = _bare(tmp_path)
    _skills_root(proj).mkdir(parents=True)
    manifest = _skills_root(proj) / MANIFEST_NAME
    manifest.write_text(json.dumps({"version": 3, "skills": {}}), encoding="utf-8")
    before = manifest.read_bytes()

    report = sync_project_skills(proj, update=False)

    assert report.bridges["claude"].notice and "newer" in report.bridges["claude"].notice
    assert not _skills_dir(proj).exists()
    assert manifest.read_bytes() == before
    inspected = inspect_project_skills(proj)
    assert "newer" in inspected.bridges["claude"].notice


def test_permission_error_on_symlink_is_a_notice_not_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = _bare(tmp_path)

    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(os, "symlink", denied)
    report = sync_project_skills(proj)

    assert report.notice is None
    assert {s.action for s in report.statuses} == {INSTALLED}
    for skill in bundled_skills():
        assert (_skills_root(proj) / skill.name / "SKILL.md").is_file()
    assert "permission denied" in report.bridges["claude"].notice
    assert not any(
        (_skills_dir(proj) / s.name).exists() or (_skills_dir(proj) / s.name).is_symlink()
        for s in bundled_skills()
    )


def test_second_sync_writes_nothing_and_manifest_bytes_are_identical(tmp_path: Path) -> None:
    proj = _bare(tmp_path)
    sync_project_skills(proj)
    manifest = _skills_root(proj) / MANIFEST_NAME
    before_bytes = manifest.read_bytes()
    before_tree = _tree(proj)

    report = sync_project_skills(proj)

    assert manifest.read_bytes() == before_bytes
    assert _tree(proj) == before_tree
    assert {e["action"] for e in report.bridges["claude"].entries.values()} == {None}
    assert {s.action for s in report.statuses} == {KEPT}


def test_dry_run_writes_no_bridges_or_manifest(tmp_path: Path) -> None:
    proj = _bare(tmp_path)
    before = _tree(proj)
    sync_project_skills(proj, dry_run=True)
    assert _tree(proj) == before
    sync_project_skills(proj)
    after = _tree(proj)
    (_skills_dir(proj) / "wrapup").unlink()
    sync_project_skills(proj, dry_run=True)
    assert not (_skills_dir(proj) / "wrapup").exists()
    assert _tree(proj) != after


def test_empty_targets_removes_recorded_entries(tmp_path: Path) -> None:
    proj = _bare(tmp_path)
    sync_project_skills(proj)
    assert (_skills_dir(proj) / "wrapup").is_symlink()
    (proj / ".metaproject" / "config.json").write_text(
        json.dumps({"skills": {"targets": []}}), encoding="utf-8"
    )

    report = sync_project_skills(proj)

    assert "wrapup" in report.bridges["claude"].removed
    assert not (_skills_dir(proj) / "wrapup").exists()
    assert not (_skills_dir(proj) / "wrapup").is_symlink()
    assert "bridges" not in _manifest(proj) or "." not in _manifest(proj)["bridges"]
    assert (_skills_root(proj) / "wrapup" / "SKILL.md").is_file()


def test_shadowing_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "home"
    (fake_home / ".claude" / "skills" / "wrapup").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    proj = _bare(tmp_path)

    assert any("wrapup" in line for line in inspect_project_skills(proj).shadowing)
    report = sync_project_skills(proj)
    assert report.shadowing == [
        "~/.claude/skills/wrapup overrides the project's wrapup in Claude Code"
    ]


# ------------------------------------------------------- CLI reporting (R-BRG-27/28/29)


def _flat(output: str) -> str:
    return " ".join(output.split())


def test_status_text_shows_bridge_states_and_mode_line(runner: CliRunner, tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    result = runner.invoke(app, ["skills", "status", "--dir", str(proj)])
    assert result.exit_code == 0, result.output
    out = _flat(result.output)
    assert "Bridge (claude)" in out
    assert "bridge claude: mode" in out
    assert "current" in out


def test_status_json_has_bridges_and_shadowing_and_no_link(
    runner: CliRunner, tmp_path: Path
) -> None:
    proj = _scaffold(tmp_path)
    result = runner.invoke(app, ["skills", "status", "--dir", str(proj), "-f", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "link" not in payload
    assert payload["refusal"] is None
    assert isinstance(payload["shadowing"], list)
    claude = payload["bridges"]["claude"]
    assert set(claude) == {"mode", "mode_reason", "notice", "entries"}
    assert {s.name for s in bundled_skills()} == set(claude["entries"])
    assert all(set(e) == {"state", "action"} for e in claude["entries"].values())
    assert {e["state"] for e in claude["entries"].values()} == {CURRENT}


def test_status_reports_modified_copy_note(runner: CliRunner, tmp_path: Path) -> None:
    proj = _bare(tmp_path, skills={"link_mode": "copy"})
    sync = runner.invoke(app, ["skills", "sync", "--dir", str(proj)])
    assert sync.exit_code == 0, sync.output
    assert (_skills_dir(proj) / "wrapup").is_dir()
    (_skills_dir(proj) / "wrapup" / "SKILL.md").write_text("edited\n", encoding="utf-8")
    result = runner.invoke(app, ["skills", "status", "--dir", str(proj)])
    assert result.exit_code == 0, result.output
    assert "differs from .agents/skills" in _flat(result.output)


def test_unknown_target_warns_once(runner: CliRunner, tmp_path: Path) -> None:
    proj = _bare(tmp_path, skills={"targets": ["claude", "bogus"]})
    result = runner.invoke(app, ["skills", "status", "--dir", str(proj)])
    assert result.exit_code == 0, result.output
    assert _flat(result.output).count("unknown skills target 'bogus' ignored") == 1


def test_sync_text_shows_bridge_action(runner: CliRunner, tmp_path: Path) -> None:
    proj = _bare(tmp_path)
    result = runner.invoke(app, ["skills", "sync", "--dir", str(proj)])
    assert result.exit_code == 0, result.output
    assert "created" in _flat(result.output)


def test_exit_zero_for_foreign_entry(runner: CliRunner, tmp_path: Path) -> None:
    proj = _bare(tmp_path)
    (_skills_dir(proj) / "wrapup").mkdir(parents=True)
    (_skills_dir(proj) / "wrapup" / "SKILL.md").write_text("mine\n", encoding="utf-8")
    for command in ("status", "sync"):
        result = runner.invoke(app, ["skills", command, "--dir", str(proj)])
        assert result.exit_code == 0, result.output
    assert (_skills_dir(proj) / "wrapup" / "SKILL.md").read_text() == "mine\n"


def test_exit_zero_for_legacy_link_with_doctor_hint(runner: CliRunner, tmp_path: Path) -> None:
    proj = _bare(tmp_path)
    (proj / ".claude").mkdir()
    os.symlink(Path("..") / ".agents" / "skills", _skills_dir(proj))
    _skills_root(proj).mkdir(parents=True)
    for command in ("status", "sync"):
        result = runner.invoke(app, ["skills", command, "--dir", str(proj)])
        assert result.exit_code == 0, result.output
        assert "metaproject doctor" in _flat(result.output)
    assert _skills_dir(proj).is_symlink()


def test_exit_zero_for_foreign_claude_skills_symlink(runner: CliRunner, tmp_path: Path) -> None:
    proj = _bare(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (proj / ".claude").mkdir()
    os.symlink(elsewhere, _skills_dir(proj))
    for command in ("status", "sync"):
        result = runner.invoke(app, ["skills", command, "--dir", str(proj)])
        assert result.exit_code == 0, result.output
    assert list(elsewhere.iterdir()) == []


def test_exit_zero_when_symlink_denied(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = _bare(tmp_path)

    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(os, "symlink", denied)
    result = runner.invoke(app, ["skills", "sync", "--dir", str(proj)])
    assert result.exit_code == 0, result.output
    assert "permission denied" in _flat(result.output)


def test_exit_one_for_unknown_force_newer_manifest_and_no_home(
    runner: CliRunner, tmp_path: Path
) -> None:
    proj = _scaffold(tmp_path)
    forced = runner.invoke(app, ["skills", "sync", "--dir", str(proj), "--force", "nope"])
    assert forced.exit_code == 1

    (_skills_root(proj) / MANIFEST_NAME).write_text(
        json.dumps({"version": 3, "skills": {}}), encoding="utf-8"
    )
    newer = runner.invoke(app, ["skills", "sync", "--dir", str(proj)])
    assert newer.exit_code == 1

    nohome = _bare(tmp_path, "nohome", skills={"location": "root"})
    for command in ("status", "sync"):
        result = runner.invoke(app, ["skills", command, "--dir", str(nohome)])
        assert result.exit_code == 1, result.output
