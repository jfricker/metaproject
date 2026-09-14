#!/bin/sh
# SessionStart hook: checks that metaproject >= 0.7.0 is installed and that
# this project is metaproject-managed. Read-only. ALWAYS exits 0 — a
# failure here must never block a session, only add a context notice.

MIN_VERSION="0.7.0"

# Resolve project root: $CLAUDE_PROJECT_DIR if set and a directory, else the
# git top-level of the cwd, else the cwd itself.
if [ -n "$CLAUDE_PROJECT_DIR" ] && [ -d "$CLAUDE_PROJECT_DIR" ]; then
    root="$CLAUDE_PROJECT_DIR"
elif root=$(git rev-parse --show-toplevel 2>/dev/null) && [ -n "$root" ]; then
    :
else
    root=$(pwd)
fi

if ! command -v metaproject >/dev/null 2>&1; then
    echo "[sdlc-skills] metaproject is not installed (requires >= $MIN_VERSION)."
    echo "[sdlc-skills] Install it, then restart this session. Skills will stop until then."
    exit 0
fi

version_line=$(metaproject --version 2>/dev/null | grep -i "Version" | head -n 1)
version=$(printf '%s\n' "$version_line" | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1)

if [ -z "$version" ]; then
    echo "[sdlc-skills] Could not determine the installed metaproject version."
    echo "[sdlc-skills] Requires >= $MIN_VERSION. Upgrade metaproject, then restart this session."
    exit 0
fi

lowest=$(printf '%s\n' "$MIN_VERSION" "$version" | sort -V | head -n 1)
if [ "$lowest" != "$MIN_VERSION" ]; then
    echo "[sdlc-skills] metaproject $version is installed but sdlc-skills requires >= $MIN_VERSION."
    echo "[sdlc-skills] Upgrade metaproject, then restart this session. Skills will stop until then."
    exit 0
fi

if [ ! -f "$root/.metaproject.json" ]; then
    echo "[sdlc-skills] This project isn't metaproject-managed (no .metaproject.json)."
    echo "[sdlc-skills] Preview with: metaproject new . --dry-run"
    echo "[sdlc-skills] Then have the operator run: metaproject new ."
    echo "[sdlc-skills] Skills will stop until then."
    exit 0
fi

exit 0
