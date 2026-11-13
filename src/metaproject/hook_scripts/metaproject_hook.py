#!/usr/bin/env python3
"""Claude Code hook installed by metaproject. Stdlib only; reads `.metaproject.json`.

    python3 .claude/hooks/metaproject_hook.py post-edit   # PostToolUse, Edit|Write
    python3 .claude/hooks/metaproject_hook.py pre-bash    # PreToolUse, Bash

post-edit runs `commands.lint` then `commands.typecheck` from `.metaproject.json`. Silent,
exit 0, when neither is set or every command passes. When one fails, its output
(truncated) goes to stderr and the exit code is 2, which Claude Code feeds back to the
agent; the edit itself has already happened and is not undone.

pre-bash: when the Bash command mentions playwright and `e2e_port` is set, any process
listening on that port is stopped (TERM, then KILL) so a stale preview server cannot
break the e2e run. It also notices a held Playwright install lock (a `__dirlock` under the
browsers path, or a running `playwright install`) and adds guidance for the agent to use a
worktree-local `PLAYWRIGHT_BROWSERS_PATH` instead of waiting. It only reports: it never
sets environment variables, installs, or deletes a lock, and it never blocks the command:
exit 0 always. Notes reach the agent as PreToolUse `additionalContext`.

Any problem in this script itself (unreadable config, no lsof, bad input) is silent and
exits 0: a hook must never get in the way of the work it is checking.

`metaproject backfill` installs this file create-only; delete it and re-run to take a
newer release's copy.
"""

import json
import os
import signal
import subprocess
import sys
import time

CONFIG_FILE = ".metaproject.json"
COMMAND_KEYS = ("lint", "typecheck")
COMMAND_TIMEOUT = 60  # seconds per configured command
MAX_LINES = 20
MAX_CHARS = 2000


def read_payload():
    """The hook input JSON from stdin, or {} when there is none."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def project_dir(payload):
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    return str(root)


def load_config(root):
    try:
        with open(os.path.join(root, CONFIG_FILE), encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def configured_commands(config):
    commands = config.get("commands")
    if not isinstance(commands, dict):
        return []
    found = []
    for key in COMMAND_KEYS:
        value = commands.get(key)
        if isinstance(value, str) and value.strip():
            found.append((key, value.strip()))
    return found


def truncate(text):
    lines = text.strip().splitlines()
    kept = lines[:MAX_LINES]
    out = "\n".join(kept)
    if len(out) > MAX_CHARS:
        out = out[:MAX_CHARS].rstrip() + " ..."
    if len(lines) > len(kept):
        out += "\n... ({} more lines)".format(len(lines) - len(kept))
    return out


def _kill_group(proc):
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except Exception:
        pass


def run_command(command, root):
    """(returncode, output); returncode None means it timed out."""
    proc = subprocess.Popen(
        command,
        shell=True,
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        output, _ = proc.communicate(timeout=COMMAND_TIMEOUT)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        return None, ""
    return proc.returncode, output.decode("utf-8", errors="replace")


def post_edit(payload):
    root = project_dir(payload)
    failures = []
    for name, command in configured_commands(load_config(root)):
        code, output = run_command(command, root)
        if code is None:
            failures.append("{} timed out after {}s: {}".format(name, COMMAND_TIMEOUT, command))
        elif code != 0:
            detail = truncate(output)
            failures.append(
                "{} failed (exit {}): {}".format(name, code, command)
                + ("\n" + detail if detail else "")
            )
    if not failures:
        return 0
    sys.stderr.write("metaproject post-edit check:\n" + "\n\n".join(failures) + "\n")
    return 2


def e2e_port(config):
    value = config.get("e2e_port")
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, int) and 0 < value < 65536:
        return value
    return None


def listening_pids(port):
    try:
        result = subprocess.run(
            ["lsof", "-nP", "-t", "-iTCP:{}".format(port), "-sTCP:LISTEN"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        return []
    own = {os.getpid(), os.getppid()}
    pids = []
    for token in result.stdout.decode("ascii", errors="ignore").split():
        if token.isdigit() and int(token) not in own and int(token) not in pids:
            pids.append(int(token))
    return pids


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def stop_pids(pids, grace=2.0):
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(_alive(pid) for pid in pids):
        time.sleep(0.1)
    for pid in pids:
        if _alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


LOCAL_BROWSERS_DIR = ".playwright-browsers"
LOCK_NAME = "__dirlock"


def browsers_path(env=None):
    """Where Playwright keeps its browsers (and its install lock)."""
    env = os.environ if env is None else env
    explicit = env.get("PLAYWRIGHT_BROWSERS_PATH")
    if explicit and explicit != "0":
        return explicit
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Caches", "ms-playwright")
    if sys.platform.startswith("win"):
        return os.path.join(env.get("LOCALAPPDATA") or home, "ms-playwright")
    return os.path.join(env.get("XDG_CACHE_HOME") or os.path.join(home, ".cache"), "ms-playwright")


def install_process_running():
    """True when a `playwright install` process (not this hook) is running."""
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        return False
    own = {os.getpid(), os.getppid()}
    for line in result.stdout.decode("utf-8", errors="ignore").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit() or int(parts[0]) in own:
            continue
        words = parts[1].lower().split()
        if "metaproject_hook.py" in parts[1]:
            continue
        if any("playwright" in w for w in words) and "install" in words:
            return True
    return False


def install_lock_held(path):
    """True when `path` holds Playwright's install lock or an install is running."""
    try:
        if os.path.exists(os.path.join(path, LOCK_NAME)):
            return True
    except Exception:
        pass
    return install_process_running()


def lock_guidance(root, command):
    """Advice when the shared browsers install is locked, or None."""
    path = browsers_path()
    try:
        inside = os.path.realpath(path).startswith(os.path.realpath(root) + os.sep)
    except Exception:
        inside = False
    if inside or "PLAYWRIGHT_BROWSERS_PATH" in command:
        return None  # already using a project-local browsers directory
    if not install_lock_held(path):
        return None
    return (
        "metaproject: a Playwright install lock looks held ({}). Do not wait for it. "
        "Prefix the command with PLAYWRIGHT_BROWSERS_PATH={}/{} (git-ignored), run "
        "`npx playwright install <engine>` for only the engines this run needs, and run "
        "only the affected project, e.g. `--project=<name>`."
    ).format(os.path.join(path, LOCK_NAME), root, LOCAL_BROWSERS_DIR)


def emit(notes):
    if not notes:
        return
    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": "\n".join(notes),
                }
            }
        )
        + "\n"
    )


def pre_bash(payload):
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or "playwright" not in command.lower():
        return 0
    root = project_dir(payload)
    notes = []
    port = e2e_port(load_config(root))
    if port is not None:
        pids = listening_pids(port)
        if pids:
            stop_pids(pids)
            notes.append(
                "metaproject: stopped {} stale listener(s) on port {}".format(len(pids), port)
            )
    try:
        advice = lock_guidance(root, command)
    except Exception:
        advice = None
    if advice:
        notes.append(advice)
    emit(notes)
    return 0


MODES = {"post-edit": post_edit, "pre-bash": pre_bash}


def main(argv):
    handler = MODES.get(argv[1]) if len(argv) > 1 else None
    if handler is None:
        return 0
    try:
        return handler(read_payload())
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
