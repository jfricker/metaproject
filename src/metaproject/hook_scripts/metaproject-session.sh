#!/usr/bin/env bash
# Claude Code SessionStart script installed by metaproject (scripts/metaproject-session.sh).
#
# Runs only in Claude Code on the web (CLAUDE_CODE_REMOTE=true), where every session is
# a fresh container with no metaproject CLI on PATH. It:
#
#   1. installs the CLI at the version pinned in .metaproject.json (`metaproject_version`)
#      with `uv tool install git+<repo>@v<version>`, falling back to pipx, then pip --user
#      (and to the default branch if the pinned tag cannot be installed); skipped when
#      `metaproject --version` already reports that version;
#   2. runs `metaproject skills sync` (installs missing skills, updates outdated,
#      unmodified ones, never touches a locally edited skill);
#   3. runs `metaproject templates fetch`, which refreshes the `templates.source` cache
#      when .metaproject.json declares one and is a no-op otherwise.
#
# Idempotent and quiet: all output goes to a log file ($METAPROJECT_SESSION_LOG, default
# ${TMPDIR:-/tmp}/metaproject-session.log). It ALWAYS exits 0 — offline, no uv, no
# python3, a malformed .metaproject.json: none of these may block a session.
#
# Environment overrides: METAPROJECT_REPO_URL (default the upstream repository).
#
# `metaproject backfill` installs this file create-only; delete it and re-run to take a
# newer release's copy.

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

install_cli() {
  echo "installing metaproject from $1"
  if command -v uv >/dev/null 2>&1 && uv tool install --force --quiet "$1"; then
    return 0
  fi
  if command -v pipx >/dev/null 2>&1 && pipx install --force "$1"; then
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 -m pip install --user --quiet --upgrade "$1" && return 0
    # PEP 668 ("externally managed") interpreters refuse --user installs without this.
    python3 -m pip install --user --quiet --upgrade --break-system-packages "$1" && return 0
  fi
  echo "could not install metaproject (no working uv, pipx or pip)"
  return 1
}

main() {
  set +e
  local project_dir="${CLAUDE_PROJECT_DIR:-$PWD}"
  cd "$project_dir" || return 0

  local repo="${METAPROJECT_REPO_URL:-https://github.com/jfricker/metaproject}"
  local bin_dir="$HOME/.local/bin"
  case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *) PATH="$bin_dir:$PATH"; export PATH ;;
  esac

  # The pinned version, validated so it can only ever be a version string.
  local version=""
  if command -v python3 >/dev/null 2>&1 && [ -f .metaproject.json ]; then
    version="$(python3 -c '
import json, re, sys
try:
    v = json.load(open(".metaproject.json", encoding="utf-8")).get("metaproject_version", "")
except Exception:
    v = ""
v = v.strip() if isinstance(v, str) else ""
v = v[1:] if v.startswith("v") else v
print(v if re.fullmatch(r"[0-9][0-9A-Za-z.+-]*", v) else "")
' 2>/dev/null)"
  fi

  local spec="git+$repo"
  [ -n "$version" ] && spec="git+$repo@v$version"

  local installed=""
  if command -v metaproject >/dev/null 2>&1; then
    installed="$(COLUMNS=200 metaproject --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z.+-]*' | head -n 1)"
  fi

  if [ -z "$installed" ] || { [ -n "$version" ] && [ "$installed" != "$version" ]; }; then
    install_cli "$spec" || {
      # A pinned version with no matching tag must not leave the session without a CLI.
      [ -n "$version" ] && echo "install of $spec failed; trying the default branch" \
        && install_cli "git+$repo"
    }
  else
    echo "metaproject $installed already installed"
  fi

  if ! command -v metaproject >/dev/null 2>&1; then
    echo "metaproject is not on PATH; skipping skills sync and template fetch"
    return 0
  fi

  # Persist PATH for the session's own Bash calls (Claude Code reads CLAUDE_ENV_FILE).
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    grep -qs "metaproject-session" "$CLAUDE_ENV_FILE" \
      || echo "export PATH=\"$bin_dir:\$PATH\"  # metaproject-session" >>"$CLAUDE_ENV_FILE"
  fi

  metaproject skills sync --dir "$project_dir"
  metaproject templates fetch --dir "$project_dir"
  return 0
}

log="${METAPROJECT_SESSION_LOG:-${TMPDIR:-/tmp}/metaproject-session.log}"
( : >>"$log" ) 2>/dev/null || log=/dev/null
{ main; } >>"$log" 2>&1 </dev/null || true
exit 0
