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
    file_map,
    hash_content,
    inspect_project_skills,
    load_manifest,
    render_manifest,
    running_release,
    skill_digest,
    sync_project_skills,
)

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
    assert file_map(d)["link.md"] == skills_module.NON_REGULAR


# ------------------------------------------------------------------ install paths


def test_new_writes_manifest_for_every_skill(tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    data = _manifest(proj)
    assert data["version"] == 1
    assert set(data["skills"]) == {skill.name for skill in bundled_skills()}
    for skill in bundled_skills():
        entry = data["skills"][skill.name]
        assert entry["release"] == running_release()
        assert entry["files"] == file_map(skill.source_dir)
    text = (_skills_root(proj) / MANIFEST_NAME).read_text(encoding="utf-8")
    assert text == render_manifest(data["skills"])
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
    (proj / "docs" / "HANDOFF.md").unlink(missing_ok=True)

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
    real_copy = skills_module._copy_tree

    def copy_then_edit(source_dir, out):
        real_copy(source_dir, out)
        if out.name == "wrapup.new":
            (dest / "SKILL.md").write_text("# edited mid-sync\n", encoding="utf-8")

    monkeypatch.setattr(skills_module, "_copy_tree", copy_then_edit)

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
    real_dir = _scaffold(tmp_path, "realdir")
    (real_dir / ".claude" / "skills").unlink()
    (real_dir / ".claude" / "skills").mkdir()
    (_skills_root(real_dir) / MANIFEST_NAME).unlink()
    shutil.rmtree(_skills_root(real_dir) / "wrapup")

    linked = _scaffold(tmp_path, "linked")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (linked / ".claude" / "skills").unlink()
    os.symlink(elsewhere, linked / ".claude" / "skills")
    (_skills_root(linked) / MANIFEST_NAME).unlink()

    for proj in (real_dir, linked):
        before = _tree(proj)
        result = runner.invoke(app, ["skills", command, "--dir", str(proj)])
        assert result.exit_code == 1, result.output
        assert _tree(proj) == before
        json_result = runner.invoke(app, ["skills", command, "--dir", str(proj), "-f", "json"])
        assert json_result.exit_code == 1
        payload = json.loads(json_result.stdout)
        assert payload["refusal"] and payload["skills"] == []
        assert _tree(proj) == before
    assert list(elsewhere.iterdir()) == []


def test_unreadable_manifest_is_noticed_and_rewritten(runner: CliRunner, tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    (_skills_root(proj) / MANIFEST_NAME).write_text("{not json", encoding="utf-8")

    status = runner.invoke(app, ["skills", "status", "--dir", str(proj)])
    assert status.exit_code == 0
    assert "could not be read" in " ".join(status.output.split())

    synced = runner.invoke(app, ["skills", "sync", "--dir", str(proj)])
    assert synced.exit_code == 0, synced.output
    assert load_manifest(_skills_root(proj))[0] == "present"


def test_newer_manifest_status_works_sync_refuses(runner: CliRunner, tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    manifest = _skills_root(proj) / MANIFEST_NAME
    manifest.write_text(json.dumps({"version": 2, "skills": {"wrapup": "?"}}), encoding="utf-8")
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


def test_sync_without_claude_skills_link_points_at_adopt(runner: CliRunner, tmp_path: Path) -> None:
    proj = _scaffold(tmp_path)
    (proj / ".claude" / "skills").unlink()
    result = runner.invoke(app, ["skills", "sync", "--dir", str(proj)])
    assert result.exit_code == 0
    assert "metaproject adopt" in " ".join(result.output.split())
    assert not (proj / ".claude" / "skills").exists()


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
