"""Tests for the Claude Code hooks deliverable (issue #7).

`.claude/settings.json` is merged, never overwritten; the hook script is copied
create-only; `new`, `backfill` and `review` all see the same notion of "installed".
"""

import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.deliverables import DeliverableClass, canonical_path, classify
from metaproject.exceptions import MetaProjectError
from metaproject.hooks import (
    CURRENT,
    HOOK_SCRIPT_PATH,
    INSTALLED,
    MISSING,
    POST_EDIT_HOOK,
    PRE_BASH_HOOK,
    SETTINGS_PATH,
    STALE,
    HookConfig,
    HookEntry,
    SettingsError,
    get_bundled_hook_script,
    hook_script_state,
    hooks_installed,
    install_hooks,
    merge_hooks,
    missing_hooks,
    project_hook_entries,
    read_hook_config,
)
from metaproject.identity import IDENTITY_FILE, Identity, write_identity
from metaproject.review import (
    backfill_missing,
    deploy_entry,
    review_project,
    update_entry,
)
from metaproject.scaffold import TransactionalTracker, scaffold_project
from metaproject.templates import get_bundled_templates_dir

SESSION_START = HookEntry(event="SessionStart", command="echo session")

USER_SETTINGS = {
    "permissions": {"allow": ["Bash(make test)"]},
    "env": {"FOO": "bar"},
    "hooks": {
        "PostToolUse": [
            {"matcher": "Edit", "hooks": [{"type": "command", "command": "prettier --write"}]}
        ],
        "Stop": [{"hooks": [{"type": "command", "command": "say done"}]}],
    },
}


def write_settings(project: Path, data: object) -> Path:
    path = project / SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def commands_under(data: dict, event: str) -> list:
    return [hook["command"] for group in data["hooks"][event] for hook in group["hooks"]]


def scaffolded(tmp_path: Path, name: str = "proj") -> Path:
    proj = tmp_path / name
    scaffold_project(
        project_name=name,
        output=proj,
        templates_dir=get_bundled_templates_dir(),
        interactive=False,
        no_git=True,
    )
    return proj


# ------------------------------------------------------------------------- declaration


def test_settings_is_declared_as_its_own_class() -> None:
    assert classify(SETTINGS_PATH) is DeliverableClass.SETTINGS
    assert canonical_path("settings.json") == SETTINGS_PATH


def test_project_hook_entries_match_the_issue() -> None:
    assert POST_EDIT_HOOK.event == "PostToolUse" and POST_EDIT_HOOK.matcher == "Edit|Write"
    assert PRE_BASH_HOOK.event == "PreToolUse" and PRE_BASH_HOOK.matcher == "Bash"
    for entry in (POST_EDIT_HOOK, PRE_BASH_HOOK):
        assert HOOK_SCRIPT_PATH in entry.command
    for entry in project_hook_entries():
        assert "$CLAUDE_PROJECT_DIR" in entry.command


@pytest.mark.parametrize("entry", project_hook_entries(), ids=lambda e: e.event)
def test_hook_command_is_a_no_op_when_the_script_is_absent(tmp_path: Path, entry) -> None:
    """`python3 <missing file>` exits 2, which blocks a PreToolUse call; the guard must not."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    result = subprocess.run(
        ["/bin/sh", "-c", entry.command],
        input=json.dumps({"tool_input": {"command": "npx playwright test"}}),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_hook_command_runs_the_script_when_present(tmp_path: Path) -> None:
    proj = scaffolded(tmp_path)
    (proj / IDENTITY_FILE).write_text(
        json.dumps({"commands": {"lint": "echo lint-broke; exit 3"}}), encoding="utf-8"
    )
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj)}
    result = subprocess.run(
        ["/bin/sh", "-c", POST_EDIT_HOOK.command],
        input=json.dumps(EDIT_PAYLOAD),
        capture_output=True,
        text=True,
        env=env,
        cwd=proj,
        timeout=60,
    )
    assert result.returncode == 2
    assert "lint-broke" in result.stderr


# ------------------------------------------------------------------------------ merging


def test_merge_creates_an_absent_file(tmp_path: Path) -> None:
    path = tmp_path / ".claude" / "settings.json"
    added = merge_hooks(path, project_hook_entries())
    assert added == list(project_hook_entries())
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hooks"]["PostToolUse"] == [POST_EDIT_HOOK.as_group()]
    assert data["hooks"]["PreToolUse"] == [PRE_BASH_HOOK.as_group()]
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_merge_is_idempotent(tmp_path: Path) -> None:
    path = write_settings(tmp_path, USER_SETTINGS)
    merge_hooks(path, project_hook_entries())
    before = path.read_bytes()
    mtime = path.stat().st_mtime_ns
    time.sleep(0.01)

    assert merge_hooks(path, project_hook_entries()) == []
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime
    data = json.loads(before)
    assert commands_under(data, "PostToolUse").count(POST_EDIT_HOOK.command) == 1


def test_merge_preserves_every_user_key_and_hook_in_order(tmp_path: Path) -> None:
    path = write_settings(tmp_path, USER_SETTINGS)
    merge_hooks(path, project_hook_entries())
    data = json.loads(path.read_text(encoding="utf-8"))

    assert list(data) == ["permissions", "env", "hooks"]
    assert data["permissions"] == USER_SETTINGS["permissions"]
    assert data["env"] == USER_SETTINGS["env"]
    assert data["hooks"]["Stop"] == USER_SETTINGS["hooks"]["Stop"]
    assert commands_under(data, "PostToolUse") == ["prettier --write", POST_EDIT_HOOK.command]
    assert commands_under(data, "PreToolUse") == [PRE_BASH_HOOK.command]


def test_merge_keys_entries_by_command_not_matcher(tmp_path: Path) -> None:
    """An operator who re-scoped the matcher keeps their version; no duplicate is added."""
    group = {"matcher": "Write", "hooks": [{"type": "command", "command": POST_EDIT_HOOK.command}]}
    path = write_settings(tmp_path, {"hooks": {"PostToolUse": [group]}})
    assert merge_hooks(path, [POST_EDIT_HOOK]) == []
    assert json.loads(path.read_text(encoding="utf-8"))["hooks"]["PostToolUse"] == [group]


def test_merge_accepts_a_matcherless_entry_for_later_hooks(tmp_path: Path) -> None:
    """The extension point a SessionStart hook will use."""
    path = write_settings(tmp_path, USER_SETTINGS)
    assert merge_hooks(path, [SESSION_START]) == [SESSION_START]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hooks"]["SessionStart"] == [
        {"hooks": [{"type": "command", "command": "echo session"}]}
    ]
    assert merge_hooks(path, [SESSION_START]) == []


def test_merge_dry_run_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    assert merge_hooks(path, project_hook_entries(), dry_run=True) == list(project_hook_entries())
    assert not path.exists()


@pytest.mark.parametrize(
    "content",
    [
        '{"permissions": {',  # truncated
        "// comment\n{}",  # JSONC is not JSON
        "[1, 2]",  # not an object
        '{"hooks": []}',  # hooks not an object
        '{"hooks": {"PostToolUse": {}}}',  # event not a list
    ],
)
def test_merge_refuses_unmergeable_files_and_leaves_them_untouched(
    tmp_path: Path, content: str
) -> None:
    path = write_settings(tmp_path, content)
    with pytest.raises(SettingsError):
        merge_hooks(path, project_hook_entries())
    with pytest.raises(SettingsError):
        missing_hooks(path, project_hook_entries())
    assert path.read_text(encoding="utf-8") == content


def test_empty_settings_file_is_treated_as_empty_object(tmp_path: Path) -> None:
    path = write_settings(tmp_path, "")
    assert merge_hooks(path, [POST_EDIT_HOOK]) == [POST_EDIT_HOOK]
    assert json.loads(path.read_text(encoding="utf-8"))["hooks"]["PostToolUse"]


# ------------------------------------------------------------------------- installation


def test_install_hooks_writes_script_and_settings(tmp_path: Path) -> None:
    report = install_hooks(tmp_path)
    assert report.script == INSTALLED
    assert report.settings_created
    assert report.added == list(project_hook_entries())
    script = tmp_path / HOOK_SCRIPT_PATH
    assert script.read_bytes() == get_bundled_hook_script().read_bytes()
    assert os.access(script, os.X_OK)
    assert hooks_installed(tmp_path)
    assert hook_script_state(tmp_path) == CURRENT

    again = install_hooks(tmp_path)
    assert again.script == CURRENT and again.added == [] and not again.wrote


def test_install_hooks_never_writes_into_an_existing_script(tmp_path: Path) -> None:
    script = tmp_path / HOOK_SCRIPT_PATH
    script.parent.mkdir(parents=True)
    script.write_text("# my edits\n", encoding="utf-8")
    report = install_hooks(tmp_path)
    assert report.script == STALE
    assert script.read_text(encoding="utf-8") == "# my edits\n"
    assert hooks_installed(tmp_path)


def test_install_hooks_refuses_invalid_settings_and_writes_nothing(tmp_path: Path) -> None:
    path = write_settings(tmp_path, "{nope")
    report = install_hooks(tmp_path)
    assert report.notice is not None and "not valid JSON" in report.notice
    assert path.read_text(encoding="utf-8") == "{nope"
    assert hook_script_state(tmp_path) == MISSING
    assert not hooks_installed(tmp_path)


def test_rollback_restores_a_merged_settings_file(tmp_path: Path) -> None:
    path = write_settings(tmp_path, USER_SETTINGS)
    original = path.read_bytes()
    tracker = TransactionalTracker()
    tracker.record_existing(tmp_path)
    install_hooks(tmp_path, tracker=tracker)
    assert path.read_bytes() != original

    tracker.rollback()
    assert path.read_bytes() == original
    assert not (tmp_path / HOOK_SCRIPT_PATH).exists()


def test_rollback_removes_a_created_settings_file(tmp_path: Path) -> None:
    tracker = TransactionalTracker()
    tracker.record_existing(tmp_path)
    install_hooks(tmp_path, tracker=tracker)
    tracker.rollback()
    assert not (tmp_path / ".claude").exists()


# ------------------------------------------------------------------ new / backfill / review


def test_new_installs_hooks_and_review_is_clean(tmp_path: Path) -> None:
    proj = scaffolded(tmp_path)
    assert hooks_installed(proj)
    result = review_project(proj, get_bundled_templates_dir())
    assert SETTINGS_PATH not in result.missing_files
    assert result.is_compliant


def test_new_into_an_existing_directory_merges_the_operators_settings(tmp_path: Path) -> None:
    proj = tmp_path / "occupied"
    path = write_settings(proj, USER_SETTINGS)
    result = scaffold_project(
        project_name="occupied",
        output=proj,
        templates_dir=get_bundled_templates_dir(),
        interactive=False,
        no_git=True,
        backfill=True,
    )
    assert result["hooks"].added == list(project_hook_entries())
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["permissions"] == USER_SETTINGS["permissions"]
    assert commands_under(data, "PostToolUse")[0] == "prettier --write"


def test_new_with_invalid_settings_reports_and_still_scaffolds(
    runner: CliRunner, tmp_path: Path
) -> None:
    proj = tmp_path / "occupied"
    write_settings(proj, "{bad")
    result = runner.invoke(app, ["new", ".", "--output", str(proj), "--yes", "--no-git", "--force"])
    assert result.exit_code == 0, result.output
    assert "not valid JSON" in " ".join(result.output.split())
    assert (proj / SETTINGS_PATH).read_text(encoding="utf-8") == "{bad"
    assert (proj / "AGENTS.md").exists()


def test_review_reports_settings_missing_and_deployable(tmp_path: Path) -> None:
    proj = scaffolded(tmp_path)
    (proj / SETTINGS_PATH).unlink()
    result = review_project(proj, get_bundled_templates_dir())
    assert SETTINGS_PATH in result.missing_files
    assert SETTINGS_PATH in result.deployable
    assert not result.is_compliant

    written = deploy_entry(proj, SETTINGS_PATH, get_bundled_templates_dir())
    assert written == [proj / SETTINGS_PATH]
    assert hooks_installed(proj)
    with pytest.raises(MetaProjectError):
        deploy_entry(proj, SETTINGS_PATH, get_bundled_templates_dir())


def test_review_reports_a_settings_file_without_our_hooks_missing(tmp_path: Path) -> None:
    proj = scaffolded(tmp_path)
    write_settings(proj, USER_SETTINGS)
    result = review_project(proj, get_bundled_templates_dir())
    assert SETTINGS_PATH in result.missing_files
    assert SETTINGS_PATH in result.deployable


def test_review_reports_invalid_settings_missing_but_not_deployable(tmp_path: Path) -> None:
    proj = scaffolded(tmp_path)
    write_settings(proj, "{bad")
    result = review_project(proj, get_bundled_templates_dir())
    assert SETTINGS_PATH in result.missing_files
    assert SETTINGS_PATH not in result.deployable
    assert any("not valid JSON" in warning for warning in result.warnings)


def test_review_notes_a_stale_hook_script(tmp_path: Path) -> None:
    proj = scaffolded(tmp_path)
    (proj / HOOK_SCRIPT_PATH).write_text("# local\n", encoding="utf-8")
    result = review_project(proj, get_bundled_templates_dir())
    assert SETTINGS_PATH not in result.missing_files
    assert any(HOOK_SCRIPT_PATH in note for note in result.notes)


def test_update_refuses_the_settings_file(tmp_path: Path) -> None:
    proj = scaffolded(tmp_path)
    with pytest.raises(MetaProjectError, match="merged"):
        update_entry(proj, SETTINGS_PATH, get_bundled_templates_dir())


def test_backfill_merges_into_existing_settings_then_skips(tmp_path: Path) -> None:
    proj = scaffolded(tmp_path)
    path = write_settings(proj, USER_SETTINGS)

    first = backfill_missing(proj, templates_dir=get_bundled_templates_dir())
    assert SETTINGS_PATH in first.created
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["env"] == {"FOO": "bar"}
    assert POST_EDIT_HOOK.command in commands_under(data, "PostToolUse")

    second = backfill_missing(proj, templates_dir=get_bundled_templates_dir())
    assert SETTINGS_PATH in second.skipped


def test_backfill_refuses_invalid_settings(runner: CliRunner, tmp_path: Path) -> None:
    proj = scaffolded(tmp_path)
    write_settings(proj, "{bad")

    result = backfill_missing(proj, templates_dir=get_bundled_templates_dir())
    assert result.refused == [SETTINGS_PATH]
    assert result.hooks_notice and "not valid JSON" in result.hooks_notice

    cli = runner.invoke(app, ["backfill", "--dir", str(proj)])
    output = " ".join(cli.output.split())
    assert cli.exit_code == 1
    assert "not valid JSON" in output
    assert "hooks not installed" in output
    assert "already exists, nothing written" not in output
    assert (proj / SETTINGS_PATH).read_text(encoding="utf-8") == "{bad"


def test_backfill_named_settings(tmp_path: Path) -> None:
    proj = scaffolded(tmp_path)
    shutil.rmtree(proj / ".claude" / "hooks")
    (proj / SETTINGS_PATH).unlink()

    result = backfill_missing(proj, files=["settings.json"], templates_dir=None)
    assert result.created == [SETTINGS_PATH]
    assert hooks_installed(proj)

    again = backfill_missing(proj, files=[SETTINGS_PATH])
    assert again.refused == [SETTINGS_PATH]


def test_backfill_named_invalid_settings_is_refused(tmp_path: Path) -> None:
    proj = scaffolded(tmp_path)
    write_settings(proj, "[")
    result = backfill_missing(proj, files=[SETTINGS_PATH])
    assert result.refused == [SETTINGS_PATH]
    assert result.hooks_notice is not None


def test_backfill_cli_hints_when_no_lint_command(runner: CliRunner, tmp_path: Path) -> None:
    proj = scaffolded(tmp_path)
    (proj / SETTINGS_PATH).unlink()
    result = runner.invoke(app, ["backfill", "--dir", str(proj)])
    assert result.exit_code == 0, result.output
    assert "post-edit hook is idle" in " ".join(result.output.split())


# ------------------------------------------------------------------------ project config


def test_read_hook_config(tmp_path: Path) -> None:
    assert read_hook_config(tmp_path) == HookConfig()
    (tmp_path / IDENTITY_FILE).write_text(
        json.dumps({"commands": {"lint": " make lint ", "typecheck": ""}, "e2e_port": "4173"}),
        encoding="utf-8",
    )
    config = read_hook_config(tmp_path)
    assert config == HookConfig(lint="make lint", typecheck=None, e2e_port=4173)
    assert config.has_commands

    (tmp_path / IDENTITY_FILE).write_text('{"e2e_port": true, "commands": []}', encoding="utf-8")
    assert read_hook_config(tmp_path) == HookConfig()


def test_write_identity_keeps_commands_and_e2e_port(tmp_path: Path) -> None:
    (tmp_path / IDENTITY_FILE).write_text(
        json.dumps({"commands": {"lint": "make lint"}, "e2e_port": 4173, "title": "Old"}),
        encoding="utf-8",
    )
    write_identity(tmp_path, Identity("New", "d", "a", date(2026, 1, 2), "0.8.0"))
    data = json.loads((tmp_path / IDENTITY_FILE).read_text(encoding="utf-8"))
    assert data["title"] == "New"
    assert data["commands"] == {"lint": "make lint"}
    assert data["e2e_port"] == 4173


# --------------------------------------------------------------------------- hook script


def run_hook(project: Path, mode: str, payload: dict) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    return subprocess.run(
        [sys.executable, str(get_bundled_hook_script()), mode],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def configure(project: Path, **data: object) -> None:
    (project / IDENTITY_FILE).write_text(json.dumps(data), encoding="utf-8")


EDIT_PAYLOAD = {"tool_name": "Edit", "tool_input": {"file_path": "x.py"}}


def test_post_edit_is_silent_without_config(tmp_path: Path) -> None:
    result = run_hook(tmp_path, "post-edit", EDIT_PAYLOAD)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_post_edit_is_silent_without_a_lint_command(tmp_path: Path) -> None:
    configure(tmp_path, title="t", commands={"test": "false"})
    result = run_hook(tmp_path, "post-edit", EDIT_PAYLOAD)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_post_edit_is_silent_when_lint_passes(tmp_path: Path) -> None:
    configure(tmp_path, commands={"lint": "echo all good", "typecheck": "true"})
    result = run_hook(tmp_path, "post-edit", EDIT_PAYLOAD)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_post_edit_reports_a_failure_truncated_with_exit_2(tmp_path: Path) -> None:
    configure(
        tmp_path,
        commands={
            "lint": "for i in $(seq 1 50); do echo line$i; done; exit 3",
            "typecheck": "true",
        },
    )
    result = run_hook(tmp_path, "post-edit", EDIT_PAYLOAD)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "lint failed (exit 3)" in result.stderr
    assert "line20" in result.stderr
    assert "line21" not in result.stderr
    assert "30 more lines" in result.stderr


def test_post_edit_runs_lint_and_typecheck_in_the_project_dir(tmp_path: Path) -> None:
    configure(tmp_path, commands={"lint": "touch linted", "typecheck": "pwd; exit 1"})
    result = run_hook(tmp_path, "post-edit", EDIT_PAYLOAD)
    assert (tmp_path / "linted").exists()
    assert result.returncode == 2
    assert "typecheck failed (exit 1)" in result.stderr
    assert str(tmp_path.resolve()) in result.stderr or str(tmp_path) in result.stderr


def test_unknown_mode_and_garbage_input_exit_0(tmp_path: Path) -> None:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    for args, stdin in ((["nope"], "{}"), (["pre-bash"], "not json"), ([], "")):
        result = subprocess.run(
            [sys.executable, str(get_bundled_hook_script()), *args],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def load_script_module():
    spec = importlib.util.spec_from_file_location("metaproject_hook", get_bundled_hook_script())
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_post_edit_timeout_kills_the_command(tmp_path: Path, monkeypatch, capsys) -> None:
    module = load_script_module()
    monkeypatch.setattr(module, "COMMAND_TIMEOUT", 1)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    configure(tmp_path, commands={"lint": "sleep 30"})
    started = time.monotonic()
    assert module.post_edit({}) == 2
    assert time.monotonic() - started < 15
    assert "timed out" in capsys.readouterr().err


def test_e2e_port_validation() -> None:
    module = load_script_module()
    assert module.e2e_port({"e2e_port": 4173}) == 4173
    assert module.e2e_port({"e2e_port": "4173"}) == 4173
    for bad in (None, True, 0, 70000, "abc", -1):
        assert module.e2e_port({"e2e_port": bad}) is None


def test_pre_bash_ignores_commands_without_playwright(tmp_path: Path, monkeypatch) -> None:
    module = load_script_module()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    configure(tmp_path, e2e_port=4173)
    calls = []
    monkeypatch.setattr(module, "listening_pids", lambda port: calls.append(port) or [])
    assert module.pre_bash({"tool_input": {"command": "npm test"}}) == 0
    assert calls == []
    assert module.pre_bash({"tool_input": {"command": "npx Playwright test"}}) == 0
    assert calls == [4173]


def test_pre_bash_without_a_port_does_nothing(tmp_path: Path, monkeypatch) -> None:
    module = load_script_module()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(module, "listening_pids", lambda port: pytest.fail("looked up"))
    assert module.pre_bash({"tool_input": {"command": "npx playwright test"}}) == 0


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.skipif(shutil.which("lsof") is None, reason="lsof not available")
def test_pre_bash_stops_a_stale_listener_on_the_port(tmp_path: Path) -> None:
    try:
        port = _free_port()
    except OSError:
        pytest.skip("cannot bind a local port here")
    server = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import socket,time;s=socket.socket();"
            "s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);"
            f"s.bind(('127.0.0.1',{port}));s.listen();print('ready',flush=True);time.sleep(60)",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert server.stdout is not None and server.stdout.readline().strip() == "ready"
        configure(tmp_path, e2e_port=port)
        result = run_hook(
            tmp_path, "pre-bash", {"tool_input": {"command": "npx playwright test --reporter=line"}}
        )
        assert result.returncode == 0
        assert f"port {port}" in result.stdout
        assert server.wait(timeout=10) is not None
    finally:
        if server.poll() is None:
            server.kill()
            server.wait()


def test_wheel_ships_the_hook_script(tmp_path: Path) -> None:
    import zipfile

    from hatchling.builders.wheel import WheelBuilder

    repo_root = Path(__file__).resolve().parents[1]
    wheel = Path(next(WheelBuilder(str(repo_root)).build(directory=str(tmp_path))))
    assert "metaproject/hook_scripts/metaproject_hook.py" in zipfile.ZipFile(wheel).namelist()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_unwritable_claude_dir_is_reported_not_raised(runner: CliRunner, tmp_path: Path) -> None:
    """Claude Code blocks agent writes under `.claude/`; backfill reports, never crashes."""
    proj = scaffolded(tmp_path)
    shutil.rmtree(proj / ".claude" / "hooks")
    (proj / SETTINGS_PATH).unlink()
    claude_dir = proj / ".claude"
    claude_dir.chmod(0o555)
    try:
        report = install_hooks(proj)
        assert report.notice is not None and "Could not write" in report.notice

        result = backfill_missing(proj)
        assert result.refused == []
        assert result.not_written == [SETTINGS_PATH]
        assert "Could not write" in (result.hooks_notice or "")
        assert "AGENTS.md" in result.skipped

        # Default mode is the agent-safe path (wrapup's reset step): a sandbox-denied
        # hooks install is a notice, exit 0, never "already exists".
        cli = runner.invoke(app, ["backfill", "--dir", str(proj)])
        output = " ".join(cli.output.split())
        assert cli.exit_code == 0, cli.output
        assert "Could not write" in output
        assert "already exists, nothing written" not in output
        assert "Not written" in output

        # Naming the settings file explicitly is still a failure.
        named = backfill_missing(proj, files=[SETTINGS_PATH])
        assert named.refused == [SETTINGS_PATH] and named.created == []
        cli = runner.invoke(app, ["backfill", "--dir", str(proj), SETTINGS_PATH])
        output = " ".join(cli.output.split())
        assert cli.exit_code == 1
        assert "hooks not installed" in output
        assert "already exists, nothing written" not in output
    finally:
        claude_dir.chmod(0o755)


# --------------------------------------------------------------------------- playwright lock


def _fresh_env(monkeypatch, tmp_path: Path) -> Path:
    shared = tmp_path / "shared-browsers"
    shared.mkdir()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(shared))
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    return shared


def test_pre_bash_advises_when_the_install_lock_is_held(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = load_script_module()
    shared = _fresh_env(monkeypatch, tmp_path)
    (shared / "__dirlock").mkdir()
    monkeypatch.setattr(module, "install_process_running", lambda: False)
    assert module.pre_bash({"tool_input": {"command": "npx playwright test"}}) == 0
    out = json.loads(capsys.readouterr().out)
    context = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert ".playwright-browsers" in context and "Do not wait" in context
    assert not (tmp_path / "proj" / ".playwright-browsers").exists()  # advice only
    assert (shared / "__dirlock").exists()  # never removes the lock


def test_pre_bash_advises_when_an_install_process_runs(tmp_path: Path, monkeypatch, capsys) -> None:
    module = load_script_module()
    _fresh_env(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "install_process_running", lambda: True)
    assert module.pre_bash({"tool_input": {"command": "npx playwright test"}}) == 0
    assert "lock" in capsys.readouterr().out


def test_pre_bash_is_silent_without_a_lock(tmp_path: Path, monkeypatch, capsys) -> None:
    module = load_script_module()
    _fresh_env(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "install_process_running", lambda: False)
    assert module.pre_bash({"tool_input": {"command": "npx playwright test"}}) == 0
    assert capsys.readouterr().out == ""


def test_pre_bash_skips_advice_when_already_worktree_local(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = load_script_module()
    _fresh_env(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "install_process_running", lambda: True)
    command = "PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers npx playwright test"
    assert module.pre_bash({"tool_input": {"command": command}}) == 0
    assert capsys.readouterr().out == ""
    local = tmp_path / "proj" / ".playwright-browsers"
    local.mkdir()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(local))
    assert module.pre_bash({"tool_input": {"command": "npx playwright test"}}) == 0
    assert capsys.readouterr().out == ""


def test_pre_bash_ignores_the_lock_for_non_playwright_commands(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = load_script_module()
    shared = _fresh_env(monkeypatch, tmp_path)
    (shared / "__dirlock").mkdir()
    assert module.pre_bash({"tool_input": {"command": "make test"}}) == 0
    assert capsys.readouterr().out == ""


def test_pre_bash_survives_a_failing_lock_probe(tmp_path: Path, monkeypatch) -> None:
    module = load_script_module()
    _fresh_env(monkeypatch, tmp_path)

    def boom():
        raise RuntimeError("ps exploded")

    monkeypatch.setattr(module, "install_process_running", boom)
    monkeypatch.setattr(sys, "stdin", None)
    assert module.main(["x", "pre-bash"]) == 0


def test_browsers_path_defaults_and_override() -> None:
    module = load_script_module()
    assert module.browsers_path({"PLAYWRIGHT_BROWSERS_PATH": "/x"}) == "/x"
    assert module.browsers_path({}).endswith("ms-playwright")


def test_execute_tests_skill_and_ignore_template_cover_the_lock() -> None:
    from metaproject.skills import get_bundled_sdlc_skills_dir

    text = (get_bundled_sdlc_skills_dir() / "execute-tests" / "SKILL.md").read_text("utf-8")
    for needle in ("__dirlock", "PLAYWRIGHT_BROWSERS_PATH", ".playwright-browsers", "--project"):
        assert needle in text
    template = get_bundled_templates_dir() / ".gitignore.template"
    assert ".playwright-browsers/" in template.read_text("utf-8")
