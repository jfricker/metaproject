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

import os
from typing import Dict, Optional

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
