"""Nested sub-projects: the nearest `.metaproject.json` is the project root, and
`skills.location: "root"` keeps one copy of the skills per monorepo (#18)."""

import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.doctor import check_project_skills, fix_project_skills
from metaproject.hooks import get_bundled_hook_script, get_bundled_session_script
from metaproject.identity import IDENTITY_FILE, Identity, write_identity
from metaproject.scaffold import TransactionalTracker, adopt_project, link_agent_skills
from metaproject.skills import (
    CURRENT,
    INSTALLED,
    KEPT,
    MANIFEST_NAME,
    MODIFIED,
    OUTDATED,
    UPDATED,
    bundled_skills,
    inspect_project_skills,
    skills_home,
    sync_project_skills,
)
from metaproject.templates import get_bundled_templates_dir

IDENT = Identity("T", "d", "Jo F", date(2026, 1, 2), "0.9.1")
TEMPLATES = str(get_bundled_templates_dir())


def anchor(path: Path, **extra: object) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    write_identity(path, IDENT)
    if extra:
        data = json.loads((path / IDENTITY_FILE).read_text(encoding="utf-8"))
        data.update(extra)
        (path / IDENTITY_FILE).write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def mono(tmp_path: Path) -> dict:
    """A monorepo: a git root carrying an anchor, and `packages/a` carrying its own."""
    root = tmp_path / "mono"
    root.mkdir()
    (root / ".git").mkdir()
    anchor(root)
    sub = anchor(root / "packages" / "a")
    deep = sub / "src"
    deep.mkdir()
    return {"root": root.resolve(), "sub": sub.resolve(), "deep": deep.resolve()}


def skills_payload(result) -> dict:
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


# ------------------------------------------------------------------ CLI resolution


def test_backfill_from_a_subdirectory_acts_on_the_sub_project(
    runner: CliRunner, mono: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(mono["deep"])
    result = runner.invoke(app, ["backfill", "docs/HANDOFF.md", "--templates", TEMPLATES])
    assert result.exit_code == 0, result.output
    assert f"project: {mono['sub']}" in result.output
    assert (mono["sub"] / "docs" / "HANDOFF.md").is_file()
    assert not (mono["deep"] / "docs").exists()
    assert not (mono["root"] / "docs").exists()


def test_skills_status_and_sync_resolve_to_the_sub_project(
    runner: CliRunner, mono: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(mono["deep"])
    status = skills_payload(runner.invoke(app, ["skills", "status", "--format", "json"]))
    assert status["project"] == str(mono["sub"])
    assert status["location"] == "project"
    assert status["home"] == str(mono["sub"])

    result = runner.invoke(app, ["skills", "sync"])
    assert result.exit_code == 0, result.output
    for skill in bundled_skills():
        assert (mono["sub"] / ".agents" / "skills" / skill.name).is_dir()
    assert not (mono["root"] / ".agents").exists()
    assert not (mono["deep"] / ".agents").exists()


def test_an_explicit_dir_wins_over_the_nearest_anchor(
    runner: CliRunner, mono: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(mono["deep"])
    result = runner.invoke(
        app, ["skills", "status", "--format", "json", "--dir", str(mono["root"])]
    )
    assert skills_payload(result)["project"] == str(mono["root"])
    assert "project:" not in result.stderr


def test_review_resolves_upward_but_all_keeps_the_cwd(
    runner: CliRunner, mono: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(mono["deep"])
    single = runner.invoke(app, ["review", "--no-tui", "--templates", TEMPLATES])
    assert f"project: {mono['sub']}" in single.output

    every = runner.invoke(app, ["review", "--all", "--no-tui", "--templates", TEMPLATES])
    assert "project:" not in every.output


def test_templates_fetch_resolves_upward(
    runner: CliRunner, mono: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = mono["sub"] / "tpl"
    shutil.copytree(TEMPLATES, store)
    data = json.loads((mono["sub"] / IDENTITY_FILE).read_text(encoding="utf-8"))
    data["templates"] = {"source": "tpl"}
    (mono["sub"] / IDENTITY_FILE).write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.chdir(mono["deep"])
    result = runner.invoke(app, ["templates", "fetch"])
    assert result.exit_code == 0, result.output
    assert "templates.source is a path" in result.output


def test_web_doctor_defaults_to_the_nearest_anchor(
    runner: CliRunner, mono: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    monkeypatch.chdir(mono["deep"])
    result = runner.invoke(app, ["doctor", "--dry-run"])
    assert f"project: {mono['sub']}" in result.output
    assert "project skills" in result.output


def test_adopt_without_dir_reuses_the_anchor_and_dir_dot_creates_one(
    runner: CliRunner, mono: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(mono["deep"])
    reused = runner.invoke(app, ["adopt", "--author", "Jo F", "--templates", TEMPLATES])
    assert reused.exit_code == 0, reused.output
    assert "already present" in reused.output
    assert not (mono["deep"] / IDENTITY_FILE).exists()

    created = runner.invoke(
        app, ["adopt", "--dir", ".", "--author", "Jo F", "--templates", TEMPLATES]
    )
    assert created.exit_code == 0, created.output
    assert (mono["deep"] / IDENTITY_FILE).is_file()


def test_single_project_root_behaviour_is_unchanged(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = anchor(tmp_path / "solo")
    (proj / ".git").mkdir()
    monkeypatch.chdir(proj)
    result = runner.invoke(app, ["skills", "status", "--format", "json"])
    assert skills_payload(result)["project"] == str(proj.resolve())
    assert "project:" not in result.stderr

    # No anchor anywhere: the current directory, and the same error as before.
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / ".git").mkdir()
    monkeypatch.chdir(bare)
    missing = runner.invoke(app, ["skills", "status"])
    assert missing.exit_code == 1
    assert "run metaproject adopt first" in " ".join(missing.output.split())


# ------------------------------------------------------------------- skills_home


def test_skills_home_follows_the_location_setting(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    (root / ".git").mkdir()
    plain = anchor(root / "plain")
    assert skills_home(plain) == plain.resolve()

    # No ancestor project: the git root, even without an anchor of its own.
    delegating = anchor(root / "a", skills={"location": "root"})
    assert skills_home(delegating) == root.resolve()

    # An ancestor project that does not delegate wins; a delegating one is skipped.
    anchor(root / "p")
    mid = anchor(root / "p" / "mid", skills={"location": "root"})
    leaf = anchor(root / "p" / "mid" / "leaf", skills={"location": "root"})
    assert skills_home(mid) == (root / "p").resolve()
    assert skills_home(leaf) == (root / "p").resolve()
    plain_mid = anchor(root / "q" / "mid")
    assert skills_home(anchor(plain_mid / "leaf", skills={"location": "root"})) == (
        plain_mid.resolve()
    )

    # "root" at the top is a no-op; no git root at all is None.
    top = anchor(tmp_path / "top", skills={"location": "root"})
    (top / ".git").mkdir()
    assert skills_home(top) == top.resolve()
    assert skills_home(anchor(tmp_path / "nogit", skills={"location": "root"})) is None


def test_an_invalid_location_warns_and_keeps_project_behaviour(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    (root / ".git").mkdir()
    proj = anchor(root / "a", skills={"location": "../../elsewhere"})
    assert skills_home(proj) == proj.resolve()
    report = sync_project_skills(proj)
    assert any('not "project" or "root"' in w for w in report.warnings)
    assert (proj / ".agents" / "skills" / "metaproject").is_dir()


def test_root_location_without_any_home_is_a_refusal(tmp_path: Path) -> None:
    proj = anchor(tmp_path / "nogit", skills={"location": "root"})
    report = sync_project_skills(proj)
    assert report.notice is not None and "no ancestor project or git root" in report.notice
    assert not (proj / ".agents").exists()
    assert not (proj / ".claude").exists()


# ------------------------------------------------------------- root-mode sync


@pytest.fixture
def delegating(mono: dict) -> dict:
    anchor(mono["sub"], skills={"location": "root"})
    other = anchor(mono["root"] / "packages" / "b", skills={"location": "root"})
    return {**mono, "other": other.resolve()}


def test_root_mode_sync_keeps_one_copy_at_the_home(delegating: dict) -> None:
    root, sub = delegating["root"], delegating["sub"]
    report = sync_project_skills(sub)
    assert report.location == "root" and report.home == root
    assert set(report.states.values()) == {INSTALLED}
    assert (root / ".agents" / "skills" / MANIFEST_NAME).is_file()
    for skill in bundled_skills():
        assert (root / ".agents" / "skills" / skill.name).is_dir()
    assert not (sub / ".agents").exists()
    link = sub / ".claude" / "skills"
    assert os.readlink(link) == "../../../.agents/skills"
    assert link.resolve() == (root / ".agents" / "skills").resolve()

    # A second sub-project sharing the home finds everything already there.
    second = sync_project_skills(delegating["other"])
    assert {s.action for s in second.statuses} == {KEPT}
    assert set(second.states.values()) == {CURRENT}


def test_root_mode_updates_outdated_and_keeps_modified_at_the_home(delegating: dict) -> None:
    root, sub = delegating["root"], delegating["sub"]
    sync_project_skills(sub)
    home = root / ".agents" / "skills"
    manifest = json.loads((home / MANIFEST_NAME).read_text(encoding="utf-8"))
    # wrapup: an earlier release's pristine copy (it still matches its manifest entry).
    (home / "wrapup" / "SKILL.md").write_text("old release\n", encoding="utf-8")
    entry = manifest["skills"]["wrapup"]
    entry["release"] = "0.0.1"
    entry["files"] = dict(entry["files"])
    from metaproject.skills import hash_content

    entry["files"]["SKILL.md"] = hash_content(b"old release\n")
    (home / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    # shipit: a local edit.
    (home / "shipit" / "SKILL.md").write_text("mine\n", encoding="utf-8")

    status = inspect_project_skills(sub)
    assert status.states["wrapup"] == OUTDATED and status.states["shipit"] == MODIFIED

    report = sync_project_skills(sub)
    assert report.states["wrapup"] == UPDATED
    assert report.states["shipit"] == MODIFIED
    assert (home / "shipit" / "SKILL.md").read_text(encoding="utf-8") == "mine\n"


def test_root_mode_repoints_the_default_link(delegating: dict) -> None:
    sub = delegating["sub"]
    (sub / ".claude").mkdir()
    (sub / ".claude" / "skills").symlink_to(Path("..") / ".agents" / "skills")
    pending = inspect_project_skills(sub)
    assert pending.notice is None and pending.link and "re-point" in pending.link
    sync_project_skills(sub)
    assert os.readlink(sub / ".claude" / "skills") == "../../../.agents/skills"


@pytest.mark.parametrize("kind", ["dir", "foreign"])
def test_root_mode_refuses_a_real_dir_or_foreign_link(
    delegating: dict, tmp_path: Path, kind: str
) -> None:
    sub, root = delegating["sub"], delegating["root"]
    (sub / ".claude").mkdir()
    if kind == "dir":
        (sub / ".claude" / "skills").mkdir()
    else:
        (sub / ".claude" / "skills").symlink_to(tmp_path)
    report = sync_project_skills(sub)
    assert report.notice is not None
    assert not (root / ".agents").exists()


def test_root_mode_dry_run_writes_nothing(delegating: dict) -> None:
    sub, root = delegating["sub"], delegating["root"]
    report = sync_project_skills(sub, dry_run=True)
    assert report.link and report.link.startswith("would be created")
    assert not (root / ".agents").exists()
    assert not (sub / ".claude").exists()


def test_root_mode_reports_but_keeps_leftover_copies(delegating: dict) -> None:
    sub = delegating["sub"]
    leftover = sub / ".agents" / "skills" / "wrapup"
    leftover.mkdir(parents=True)
    (leftover / "SKILL.md").write_text("x\n", encoding="utf-8")
    report = sync_project_skills(sub)
    assert any("still holds copies of: wrapup" in w for w in report.warnings)
    assert leftover.is_dir()


def test_root_mode_cli_payload_and_doctor(
    runner: CliRunner, delegating: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub, root = delegating["sub"], delegating["root"]
    findings, report_only, summary = check_project_skills(sub)
    assert any("link pending" in f for f in findings)
    assert not any("link pending" in f for f in report_only)
    assert str(root / ".agents" / "skills") in summary
    fix_project_skills(sub)
    assert check_project_skills(sub)[0] == []

    monkeypatch.chdir(sub)
    payload = skills_payload(runner.invoke(app, ["skills", "status", "--format", "json"]))
    assert payload["location"] == "root"
    assert payload["home"] == str(root)
    assert payload["target"] == str(root / ".agents" / "skills")


# ----------------------------------------------------------------- scaffold layout


def test_link_agent_skills_with_a_home_writes_no_sub_layout(delegating: dict) -> None:
    sub, root = delegating["sub"], delegating["root"]
    tracker = TransactionalTracker()
    tracker.record_existing(sub)
    link = link_agent_skills(sub, tracker, home=root)
    assert link == sub / ".claude" / "skills"
    assert os.readlink(link) == "../../../.agents/skills"
    assert not (sub / ".agents").exists()
    assert (root / ".agents" / "skills" / ".gitkeep").is_file()
    assert os.readlink(root / ".claude" / "skills") == "../.agents/skills"

    tracker.rollback()
    assert not (sub / ".claude").exists()
    assert not (root / ".agents" / "skills").exists()
    assert not (root / ".claude").exists()


def test_link_agent_skills_keeps_an_existing_home_link(delegating: dict, tmp_path: Path) -> None:
    sub, root = delegating["sub"], delegating["root"]
    (root / ".claude").mkdir()
    (root / ".claude" / "skills").symlink_to(tmp_path)
    link_agent_skills(sub, TransactionalTracker(), home=root)
    assert os.readlink(root / ".claude" / "skills") == str(tmp_path)


def test_adopt_a_delegating_sub_project(delegating: dict) -> None:
    sub, root = delegating["sub"], delegating["root"]
    result = adopt_project(sub, templates_dir=Path(TEMPLATES))
    assert result.skills_link == sub / ".claude" / "skills"
    assert not (sub / ".agents").exists()
    assert (root / ".agents" / "skills" / "metaproject").is_dir()
    assert result.backfill.skills_target == root / ".agents" / "skills"


# --------------------------------------------------------------------- universe


def test_an_anchor_alone_marks_a_project_root(tmp_path: Path) -> None:
    from metaproject.universe import is_project_root

    proj = anchor(tmp_path / "only")
    assert is_project_root(proj)


# ------------------------------------------------------------------ hook script


def run_hook(session: Path, mode: str, payload: dict) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(session)}
    return subprocess.run(
        [sys.executable, str(get_bundled_hook_script()), mode],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def lint(project: Path, marker: Path) -> None:
    data = json.loads((project / IDENTITY_FILE).read_text(encoding="utf-8"))
    data["commands"] = {"lint": f'pwd > "{marker}"'}
    (project / IDENTITY_FILE).write_text(json.dumps(data), encoding="utf-8")


def test_post_edit_runs_the_owning_sub_projects_lint(mono: dict, tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    lint(mono["sub"], marker)
    edited = mono["deep"] / "x.py"
    run_hook(mono["root"], "post-edit", {"tool_input": {"file_path": str(edited)}})
    assert Path(marker.read_text().strip()).resolve() == mono["sub"]


def test_post_edit_never_leaves_the_session_project(mono: dict, tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    root_marker = tmp_path / "root-ran"
    lint(mono["root"], root_marker)
    elsewhere = anchor(tmp_path / "other")
    lint(elsewhere, marker)
    run_hook(mono["root"], "post-edit", {"tool_input": {"file_path": str(elsewhere / "f.py")}})
    assert not marker.exists()
    assert Path(root_marker.read_text().strip()).resolve() == mono["root"]


def test_post_edit_without_tool_input_uses_the_session_project(mono: dict, tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    lint(mono["root"], marker)
    result = run_hook(mono["root"], "post-edit", {})
    assert result.returncode == 0
    assert Path(marker.read_text().strip()).resolve() == mono["root"]


def test_pre_bash_uses_the_nearest_anchor_to_the_payload_cwd(mono: dict) -> None:
    # The sub-project's e2e_port is on a free port, so nothing is stopped; what matters is
    # that its config was read (a held lock note is not asserted here).
    data = json.loads((mono["sub"] / IDENTITY_FILE).read_text(encoding="utf-8"))
    data["e2e_port"] = "not-a-port"
    (mono["sub"] / IDENTITY_FILE).write_text(json.dumps(data), encoding="utf-8")
    result = run_hook(
        mono["root"],
        "pre-bash",
        {"cwd": str(mono["deep"]), "tool_input": {"command": "npx playwright test"}},
    )
    assert result.returncode == 0


def test_hook_project_dir_resolution(mono: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("mp_hook", get_bundled_hook_script())
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(mono["root"]))
    assert hook.project_dir({"cwd": str(mono["deep"])}) == str(mono["sub"])
    assert hook.project_dir({}) == str(mono["root"])
    bad = {"tool_input": {"file_path": 7}, "cwd": str(mono["root"])}
    assert hook.project_dir(bad, edited=True) == str(mono["root"])
    monkeypatch.delenv("CLAUDE_PROJECT_DIR")
    assert hook.project_dir({"cwd": str(mono["deep"])}) == str(mono["sub"])


# --------------------------------------------------------------- session script


def write_stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("with_anchor", [True, False])
def test_session_script_uses_the_nearest_anchor(tmp_path: Path, with_anchor: bool) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    sub = repo / "packages" / "a"
    start = sub / "src"
    start.mkdir(parents=True)
    if with_anchor:
        (sub / IDENTITY_FILE).write_text(
            json.dumps({"metaproject_version": "1.2.3"}), encoding="utf-8"
        )
        (repo / IDENTITY_FILE).write_text(json.dumps({"metaproject_version": "9.9.9"}))
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    calls = tmp_path / "calls.log"
    calls.write_text("", encoding="utf-8")
    write_stub(
        stubs / "metaproject",
        'echo "metaproject $*" >> "$CALLS"\n'
        'if [ "$1" = "--version" ]; then echo "metaproject v1.2.3"; fi\nexit 0\n',
    )
    write_stub(stubs / "python3", f'exec "{sys.executable}" "$@"\n')
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "PATH": f"{stubs}:/usr/bin:/bin",
        "HOME": str(home),
        "CALLS": str(calls),
        "CLAUDE_CODE_REMOTE": "true",
        "CLAUDE_PROJECT_DIR": str(start),
        "METAPROJECT_SESSION_LOG": str(tmp_path / "session.log"),
        "TMPDIR": str(tmp_path),
    }
    result = subprocess.run(
        ["bash", str(get_bundled_session_script())],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0
    lines = calls.read_text(encoding="utf-8").splitlines()
    # The stub reports 1.2.3: the sub-project's pin matches, so nothing is installed.
    expected = sub if with_anchor else start
    assert f"metaproject skills sync --dir {expected}" in lines
    assert f"metaproject templates fetch --dir {expected}" in lines
