#!/usr/bin/env bash
set -euo pipefail

# Resolve repository root directory
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Use project virtualenv python if available, otherwise python3
if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
else
    PYTHON_BIN="python3"
fi

exec "${PYTHON_BIN}" "${REPO_ROOT}/scripts/bump_version.py" "$@"
