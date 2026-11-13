"""Detection of who is driving this invocation: a person, or an agent.

Some of what the CLI does is only meaningful with a human at the keyboard. A full-screen
TUI blocks forever on keystrokes that never arrive when it is opened inside a tool call,
and `learn scan` spends money and sends data off the machine, which is an operator's
decision rather than an agent's. Both need to know which kind of session they are in, so
the question is answered in one place instead of guessed at twice.

The detection is deliberately conservative: it only reads environment markers that
agent harnesses set, and every guard built on it degrades to something useful (a printed
board, an explanatory refusal) rather than failing obscurely. A person misdetected as an
agent loses interactivity, never work, and `METAPROJECT_AGENT=0` gives it back.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# Environment variables agent harnesses set on the processes they spawn. None of them is
# set by an ordinary login shell.
AGENT_ENV_MARKERS = (
    "CLAUDECODE",  # Claude Code
    "CLAUDE_CODE",
    "AI_AGENT",  # generic marker several harnesses set
    "CI",  # a build runner has no operator either
)

# Explicit override, in both directions: "0"/"false" forces human mode even inside a
# harness, anything else truthy forces agent mode even without a marker.
AGENT_OVERRIDE = "METAPROJECT_AGENT"

_FALSEY = {"", "0", "false", "no", "off"}


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() not in _FALSEY


def agent_marker(env: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Name the signal that says an agent is driving, or None for a human session.

    Returning the marker's name rather than a bare bool lets the guards tell the operator
    *why* they were treated as an agent, which is the difference between a confusing
    refusal and an actionable one.
    """
    env = os.environ if env is None else env

    if AGENT_OVERRIDE in env:
        return AGENT_OVERRIDE if _truthy(env.get(AGENT_OVERRIDE)) else None

    for marker in AGENT_ENV_MARKERS:
        if _truthy(env.get(marker)):
            return marker
    return None


def is_agent_session(env: Optional[Dict[str, str]] = None) -> bool:
    """Is a non-human driving this invocation?"""
    return agent_marker(env) is not None


def override_hint(marker: str) -> str:
    """The one-line escape hatch to show alongside a refusal."""
    if marker == AGENT_OVERRIDE:
        return f"Unset {AGENT_OVERRIDE} (or set it to 0) to run this interactively."
    return f"Set {AGENT_OVERRIDE}=0 to override ({marker} is set in this environment)."


def stdout_is_a_terminal(stream: Optional[Any] = None) -> bool:
    """Is output going to a terminal? A separate seam so `TERM=dumb` is testable alone."""
    stream = sys.stdout if stream is None else stream
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def tui_enabled(
    no_tui: bool = False,
    stream: Optional[Any] = None,
    env: Optional[Dict[str, str]] = None,
    is_terminal: Optional[Callable[[Optional[Any]], bool]] = None,
) -> bool:
    """Should an interactive loop be opened at all?

    Four triggers, all of them non-errors: `--no-tui`, an agent session, `TERM=dumb`,
    and stdout not being a TTY. It lives here rather than in `learn.tui` so `review`
    can ask without importing the `learn` package (and through it `sqlite-utils`, which
    a core install does not carry). `learn.tui.tui_enabled` delegates to this, passing
    its own `stdout_is_a_terminal` seam as `is_terminal`.
    """
    if no_tui:
        return False

    env = os.environ if env is None else env
    if agent_marker(env) is not None:
        return False

    if str(env.get("TERM", "") or "").strip().lower() == "dumb":
        return False

    return (is_terminal or stdout_is_a_terminal)(stream)


# --------------------------------------------------------------------- web profile
#
# Claude Code on the web runs every session in a fresh container: no `~/.metaproject`,
# no project home to catalog, and never a human at the prompt. The *web profile* names
# that situation so the commands that only make sense on a long-lived machine
# (`universe`, `learn`, the review TUI, `doctor`) can say so in one line and exit 0,
# while `backfill`, `adopt`, `review --no-tui` and `--version` work as usual.

PROFILE_ENV = "METAPROJECT_PROFILE"
REMOTE_ENV = "CLAUDE_CODE_REMOTE"
WEB_PROFILE = "web"
LOCAL_PROFILE = "local"


def _configured_profile(config_file: Path) -> Optional[str]:
    """The `profile` recorded in config.json, "local" for a config without one, or None
    when there is no readable config at all.

    Read directly rather than through `config.load_config`, which fills defaults (and
    shells out to git for the author) that this question does not need.
    """
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return LOCAL_PROFILE
    if not isinstance(data, dict):
        return LOCAL_PROFILE
    return str(data.get("profile") or LOCAL_PROFILE).strip().lower()


def web_profile_reason(
    env: Optional[Dict[str, str]] = None,
    config_file: Optional[Path] = None,
) -> Optional[str]:
    """Why this invocation runs in the web profile, or None when it does not.

    Precedence: an explicit `METAPROJECT_PROFILE` wins in both directions; otherwise a
    config that exists decides (its `profile`, "local" when absent, so an initialized
    machine is never reclassified by an environment variable); otherwise
    `CLAUDE_CODE_REMOTE=true` with no config means a fresh web container.
    """
    env = os.environ if env is None else env

    explicit = str(env.get(PROFILE_ENV, "") or "").strip().lower()
    if explicit:
        return f"{PROFILE_ENV}={explicit}" if explicit == WEB_PROFILE else None

    if config_file is None:
        from metaproject.config import get_config_file_path

        config_file = get_config_file_path()
    configured = _configured_profile(Path(config_file))
    if configured is not None:
        return f"profile '{WEB_PROFILE}' in {config_file}" if configured == WEB_PROFILE else None

    if _truthy(env.get(REMOTE_ENV)):
        return f"{REMOTE_ENV}={env.get(REMOTE_ENV)} and no config"
    return None


def is_web_profile(
    env: Optional[Dict[str, str]] = None,
    config_file: Optional[Path] = None,
) -> bool:
    """Is this a Claude Code on the web session (the web profile)?"""
    return web_profile_reason(env, config_file) is not None
