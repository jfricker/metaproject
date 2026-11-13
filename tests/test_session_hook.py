"""Tests for the SessionStart hook and `scripts/metaproject-session.sh` (issue #3 part 3c).

The script is run for real under bash, with `uv`, `pipx`, `python3 -m pip` and the
`metaproject` it installs replaced by stubs that only record their arguments, so no
test installs anything or reaches the network.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from metaproject.hooks import (
    CURRENT,
    INSTALLED,
    SESSION_SCRIPT_PATH,
    SESSION_START_HOOK,
    SETTINGS_PATH,
    STALE,
    get_bundled_session_script,
    hooks_installed,
    install_hooks,
    merge_hooks,
    project_hook_entries,
    session_script_state,
)
from metaproject.review import backfill_missing, deploy_entry, review_project
from metaproject.templates import get_bundled_templates_dir

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


# ------------------------------------------------------------------------ the hook


def test_session_start_entry_goes_through_merge_hooks(tmp_path: Path) -> None:
    assert SESSION_START_HOOK in project_hook_entries()
    assert SESSION_START_HOOK.event == "SessionStart" and SESSION_START_HOOK.matcher is None
    assert SESSION_SCRIPT_PATH in SESSION_START_HOOK.command
    settings = tmp_path / SETTINGS_PATH
    settings.parent.mkdir()
    user = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}
    settings.write_text(json.dumps(user), encoding="utf-8")

    assert merge_hooks(settings, [SESSION_START_HOOK]) == [SESSION_START_HOOK]
    data = json.loads(settings.read_text(encoding="utf-8"))
    commands = [h["command"] for g in data["hooks"]["SessionStart"] for h in g["hooks"]]
    assert commands == ["echo hi", SESSION_START_HOOK.command]
    before = settings.read_bytes()
    assert merge_hooks(settings, [SESSION_START_HOOK]) == []
    assert settings.read_bytes() == before


def run_hook_command(project: Path, **env: str) -> subprocess.CompletedProcess:
    base = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_REMOTE"}
    return subprocess.run(
        ["/bin/sh", "-c", SESSION_START_HOOK.command],
        capture_output=True,
        text=True,
        env={**base, "CLAUDE_PROJECT_DIR": str(project), **env},
        timeout=30,
    )


def plant_marker_script(project: Path) -> Path:
    script = project / SESSION_SCRIPT_PATH
    script.parent.mkdir(parents=True, exist_ok=True)
    marker = project / "ran"
    script.write_text(f'touch "{marker}"\nexit 7\n', encoding="utf-8")
    return marker


def test_hook_command_is_a_no_op_without_the_script(tmp_path: Path) -> None:
    result = run_hook_command(tmp_path, CLAUDE_CODE_REMOTE="true")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_hook_command_skips_the_script_outside_the_web(tmp_path: Path) -> None:
    marker = plant_marker_script(tmp_path)
    assert run_hook_command(tmp_path).returncode == 0
    assert run_hook_command(tmp_path, CLAUDE_CODE_REMOTE="false").returncode == 0
    assert not marker.exists()


def test_hook_command_runs_the_script_on_the_web_and_always_exits_0(tmp_path: Path) -> None:
    marker = plant_marker_script(tmp_path)
    result = run_hook_command(tmp_path, CLAUDE_CODE_REMOTE="true")
    assert result.returncode == 0 and marker.exists()


# -------------------------------------------------------------------- installation


def test_install_hooks_copies_the_session_script_create_only(tmp_path: Path) -> None:
    report = install_hooks(tmp_path)
    assert report.session_script == INSTALLED
    assert SESSION_SCRIPT_PATH in report.installed_scripts
    script = tmp_path / SESSION_SCRIPT_PATH
    assert script.read_bytes() == get_bundled_session_script().read_bytes()
    assert os.access(script, os.X_OK)
    assert session_script_state(tmp_path) == CURRENT

    script.write_text("# mine\n", encoding="utf-8")
    again = install_hooks(tmp_path)
    assert again.session_script == STALE and not again.wrote
    assert script.read_text(encoding="utf-8") == "# mine\n"


def test_missing_session_script_makes_settings_deployable(tmp_path: Path) -> None:
    install_hooks(tmp_path)
    (tmp_path / SESSION_SCRIPT_PATH).unlink()
    assert not hooks_installed(tmp_path)
    result = review_project(tmp_path, get_bundled_templates_dir())
    assert SETTINGS_PATH in result.deployable
    written = deploy_entry(tmp_path, SETTINGS_PATH)
    assert written == [tmp_path / SESSION_SCRIPT_PATH]
    assert hooks_installed(tmp_path)


def test_backfill_installs_the_session_hook(tmp_path: Path) -> None:
    result = backfill_missing(tmp_path, templates_dir=get_bundled_templates_dir())
    assert SETTINGS_PATH in result.created
    data = json.loads((tmp_path / SETTINGS_PATH).read_text(encoding="utf-8"))
    assert data["hooks"]["SessionStart"][0]["hooks"][0]["command"] == SESSION_START_HOOK.command
    assert (tmp_path / SESSION_SCRIPT_PATH).is_file()


def test_review_notes_a_stale_session_script(tmp_path: Path) -> None:
    install_hooks(tmp_path)
    (tmp_path / SESSION_SCRIPT_PATH).write_text("# edited\n", encoding="utf-8")
    result = review_project(tmp_path, get_bundled_templates_dir())
    assert SETTINGS_PATH not in result.missing_files
    assert any(SESSION_SCRIPT_PATH in note for note in result.notes)


# ---------------------------------------------------------------------- the script


def write_stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


METAPROJECT_STUB = """echo "metaproject $*" >> "$CALLS"
if [ "$1" = "--version" ]; then echo "Package Manifest — metaproject v$STUB_VERSION"; fi
exit 0
"""


@pytest.fixture
def sandbox(tmp_path: Path) -> dict:
    """A fake container: HOME, a project, a bin of stubs, and a call log."""
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy(get_bundled_session_script(), project / "session.sh")
    calls = tmp_path / "calls.log"
    calls.write_text("", encoding="utf-8")
    # python3: the real interpreter for `-c`, a recorded failure for `-m pip`.
    write_stub(
        stubs / "python3",
        f'if [ "$1" = "-m" ]; then echo "python3 $*" >> "$CALLS"; exit 1; fi\n'
        f'exec "{sys.executable}" "$@"\n',
    )
    # pipx: shadow any real one so nothing can install from the network.
    write_stub(stubs / "pipx", 'echo "pipx $*" >> "$CALLS"; exit 1\n')
    return {"home": home, "stubs": stubs, "project": project, "calls": calls, "tmp": tmp_path}


def add_uv(sandbox: dict, succeed: bool = True, version: str = "1.2.3") -> None:
    install = (
        f"cat > \"$HOME/.local/bin/metaproject\" <<'EOF'\n#!/bin/bash\n{METAPROJECT_STUB}EOF\n"
        'chmod +x "$HOME/.local/bin/metaproject"\nexit 0\n'
        if succeed
        else "exit 1\n"
    )
    write_stub(sandbox["stubs"] / "uv", 'echo "uv $*" >> "$CALLS"\n' + install)


def set_pin(sandbox: dict, version: str) -> None:
    (sandbox["project"] / ".metaproject.json").write_text(
        json.dumps({"title": "P", "metaproject_version": version}), encoding="utf-8"
    )


def run_script(sandbox: dict, remote: str = "true", version: str = "1.2.3"):
    env = {
        "PATH": f"{sandbox['stubs']}:/usr/bin:/bin",
        "HOME": str(sandbox["home"]),
        "CALLS": str(sandbox["calls"]),
        "STUB_VERSION": version,
        "CLAUDE_PROJECT_DIR": str(sandbox["project"]),
        "CLAUDE_ENV_FILE": str(sandbox["tmp"] / "env-file"),
        "METAPROJECT_SESSION_LOG": str(sandbox["tmp"] / "session.log"),
        "METAPROJECT_REPO_URL": "https://example.invalid/metaproject",
        "TMPDIR": str(sandbox["tmp"]),
    }
    if remote:
        env["CLAUDE_CODE_REMOTE"] = remote
    result = subprocess.run(
        ["bash", str(sandbox["project"] / "session.sh")],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    calls = sandbox["calls"].read_text(encoding="utf-8").splitlines()
    return result, calls


def test_script_does_nothing_outside_the_web(sandbox: dict) -> None:
    add_uv(sandbox)
    result, calls = run_script(sandbox, remote="")
    assert (result.returncode, result.stdout, result.stderr, calls) == (0, "", "", [])


def test_script_installs_the_pinned_version_then_syncs(sandbox: dict) -> None:
    add_uv(sandbox)
    set_pin(sandbox, "1.2.3")
    result, calls = run_script(sandbox)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    project = str(sandbox["project"])
    assert calls == [
        "uv tool install --force --quiet git+https://example.invalid/metaproject@v1.2.3",
        "metaproject skills --help",
        f"metaproject skills sync --dir {project}",
        f"metaproject templates fetch --dir {project}",
    ]
    env_file = (sandbox["tmp"] / "env-file").read_text(encoding="utf-8")
    assert ".local/bin" in env_file


def test_script_is_idempotent(sandbox: dict) -> None:
    add_uv(sandbox)
    set_pin(sandbox, "1.2.3")
    run_script(sandbox)
    sandbox["calls"].write_text("", encoding="utf-8")
    result, calls = run_script(sandbox)
    assert result.returncode == 0
    assert not any(call.startswith("uv ") for call in calls)
    assert calls[0] == "metaproject --version"
    env_file = (sandbox["tmp"] / "env-file").read_text(encoding="utf-8")
    assert env_file.count("metaproject-session") == 1


def test_script_reinstalls_when_the_pin_changes(sandbox: dict) -> None:
    add_uv(sandbox)
    set_pin(sandbox, "1.2.3")
    run_script(sandbox, version="1.2.3")
    set_pin(sandbox, "v1.3.0")
    sandbox["calls"].write_text("", encoding="utf-8")
    _, calls = run_script(sandbox, version="1.2.3")
    assert "uv tool install --force --quiet git+https://example.invalid/metaproject@v1.3.0" in calls


def test_script_ignores_a_pin_that_is_not_a_version(sandbox: dict) -> None:
    add_uv(sandbox)
    set_pin(sandbox, "1.0; rm -rf /")
    _, calls = run_script(sandbox)
    assert calls[0] == "uv tool install --force --quiet git+https://example.invalid/metaproject"


def test_script_falls_back_to_the_default_branch_when_the_pin_fails(sandbox: dict) -> None:
    write_stub(
        sandbox["stubs"] / "uv",
        'echo "uv $*" >> "$CALLS"\ncase "$*" in *@v*) exit 1;; esac\n'
        f"cat > \"$HOME/.local/bin/metaproject\" <<'EOF'\n#!/bin/bash\n{METAPROJECT_STUB}EOF\n"
        'chmod +x "$HOME/.local/bin/metaproject"\n',
    )
    set_pin(sandbox, "9.9.9")
    result, calls = run_script(sandbox)
    assert result.returncode == 0
    assert calls[-4] == "uv tool install --force --quiet git+https://example.invalid/metaproject"
    assert calls[-2].startswith("metaproject skills sync")


def test_script_exits_0_when_nothing_can_install(sandbox: dict) -> None:
    add_uv(sandbox, succeed=False)
    set_pin(sandbox, "1.2.3")
    result, calls = run_script(sandbox)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert any(call.startswith("python3 -m pip install --user") for call in calls)
    assert not any(call.startswith("metaproject") for call in calls)
    log = (sandbox["tmp"] / "session.log").read_text(encoding="utf-8")
    assert "not on PATH" in log


def test_script_exits_0_without_uv_or_metadata(sandbox: dict) -> None:
    result, calls = run_script(sandbox)
    assert result.returncode == 0
    assert calls and all(call.startswith(("pipx ", "python3 -m pip")) for call in calls)


# A CLI from before `skills`/`templates` existed (<= 0.9.1): Typer's usage error, exit 2.
OLD_METAPROJECT_STUB = """echo "metaproject $*" >> "$CALLS"
if [ "$1" = "--version" ]; then echo "Package Manifest — metaproject v$STUB_VERSION"; exit 0; fi
case "$1" in skills|templates) echo "Error: No such command '$1'." >&2; exit 2;; esac
exit 0
"""


def add_skewed_uv(sandbox: dict, default_branch_ok: bool = True) -> None:
    """uv whose pinned (@v) install yields a pre-`skills` CLI; the default branch a current one."""
    current = METAPROJECT_STUB if default_branch_ok else OLD_METAPROJECT_STUB
    write_stub(
        sandbox["stubs"] / "uv",
        'echo "uv $*" >> "$CALLS"\n'
        'case "$*" in\n'
        f"  *@v*) cat > \"$HOME/.local/bin/metaproject\" <<'EOF'\n#!/bin/bash\n"
        f"{OLD_METAPROJECT_STUB}EOF\n;;\n"
        f"  *) cat > \"$HOME/.local/bin/metaproject\" <<'EOF'\n#!/bin/bash\n{current}EOF\n;;\n"
        "esac\n"
        'chmod +x "$HOME/.local/bin/metaproject"\nexit 0\n',
    )


def test_script_takes_the_default_branch_when_the_pin_predates_skills(sandbox: dict) -> None:
    add_skewed_uv(sandbox)
    set_pin(sandbox, "0.9.1")
    result, calls = run_script(sandbox, version="0.9.1")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    project = str(sandbox["project"])
    assert calls == [
        "uv tool install --force --quiet git+https://example.invalid/metaproject@v0.9.1",
        "metaproject skills --help",
        "uv tool install --force --quiet git+https://example.invalid/metaproject",
        "metaproject skills --help",
        f"metaproject skills sync --dir {project}",
        f"metaproject templates fetch --dir {project}",
    ]
    log = (sandbox["tmp"] / "session.log").read_text(encoding="utf-8")
    assert "no 'skills' command" in log


def test_script_repairs_an_installed_cli_that_matches_the_pin_but_lacks_skills(
    sandbox: dict,
) -> None:
    """`--version` equal to the pin must not stop the script from noticing the skew."""
    old = sandbox["home"] / ".local" / "bin" / "metaproject"
    write_stub(old, OLD_METAPROJECT_STUB)
    add_skewed_uv(sandbox)
    set_pin(sandbox, "0.9.1")
    result, calls = run_script(sandbox, version="0.9.1")
    assert result.returncode == 0
    assert calls[:3] == [
        "metaproject --version",
        "metaproject skills --help",
        "uv tool install --force --quiet git+https://example.invalid/metaproject",
    ]
    assert calls[-2].startswith("metaproject skills sync")


def test_script_exits_0_when_no_cli_has_skills(sandbox: dict) -> None:
    add_skewed_uv(sandbox, default_branch_ok=False)
    set_pin(sandbox, "0.9.1")
    result, calls = run_script(sandbox, version="0.9.1")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert not any(
        c.startswith(("metaproject skills sync", "metaproject templates")) for c in calls
    )
    log = (sandbox["tmp"] / "session.log").read_text(encoding="utf-8")
    assert "still has no 'skills' command" in log
