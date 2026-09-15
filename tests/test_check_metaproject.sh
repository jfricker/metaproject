#!/bin/sh
# Test suite for hooks/check-metaproject.sh (AC-14a).
# POSIX sh. Exits 0 only if every case passes; non-zero on any failure.

set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
HOOK="$REPO_ROOT/hooks/check-metaproject.sh"

WORK=$(mktemp -d "${TMPDIR:-/tmp}/sdlc-check-metaproject.XXXXXX")
FAIL=0

cleanup() {
    rm -rf "$WORK"
}
trap cleanup EXIT

pass() {
    echo "PASS: $1"
}

fail() {
    echo "FAIL: $1"
    FAIL=1
}

# --- Build stub metaproject executables -------------------------------

make_stub() {
    # $1 = directory to create the stub in; $2 = version string to report
    dir="$1"
    ver="$2"
    mkdir -p "$dir"
    cat > "$dir/metaproject" <<EOF
#!/bin/sh
if [ "\$1" = "--version" ]; then
    echo "┌─────────┬─────────┐"
    echo "│ Version │ $ver    │"
    echo "└─────────┴─────────┘"
fi
exit 0
EOF
    chmod +x "$dir/metaproject"
}

STUB_070="$WORK/stub-070"
STUB_061="$WORK/stub-061"
make_stub "$STUB_070" "0.7.0"
make_stub "$STUB_061" "0.6.1"

# System-only PATH: just enough for git/sh/coreutils used by the hook and
# this test harness, and deliberately excluding any stub dir.
SYS_PATH="/usr/bin:/bin"

# --- Helper: build a managed git repo ----------------------------------

make_managed_repo() {
    # $1 = path to create
    repo="$1"
    mkdir -p "$repo"
    (
        cd "$repo" || exit 1
        git init -q
        git -c user.name=t -c user.email=t@t.test commit -q --allow-empty -m "init" 2>/dev/null || {
            # allow-empty may need config set globally too on some git versions
            git -c user.name=t -c user.email=t@t.test commit --allow-empty -m "init"
        }
        echo '{"created": "2026-01-01"}' > .metaproject.json
        git -c user.name=t -c user.email=t@t.test add .metaproject.json
        git -c user.name=t -c user.email=t@t.test commit -q -m "add .metaproject.json"
    )
}

# ------------------------------------------------------------------------
# Case a: managed repo + .metaproject.json + stub 0.7.0 -> empty, exit 0
# ------------------------------------------------------------------------
REPO_A="$WORK/repo-a"
make_managed_repo "$REPO_A"

before=$(cd "$REPO_A" && git status --porcelain)
out=$(cd "$REPO_A" && env -u CLAUDE_PROJECT_DIR PATH="$STUB_070:$SYS_PATH" sh "$HOOK")
code=$?
after=$(cd "$REPO_A" && git status --porcelain)

if [ -z "$out" ] && [ "$code" -eq 0 ]; then
    pass "a: managed repo, metaproject 0.7.0 -> silent, exit 0"
else
    fail "a: managed repo, metaproject 0.7.0 -> got output [$out] exit $code"
fi
if [ "$before" = "$after" ]; then
    pass "a: no files written"
else
    fail "a: git status changed ($before -> $after)"
fi

# ------------------------------------------------------------------------
# Case b: repo without .metaproject.json -> dry-run notice, exit 0
# ------------------------------------------------------------------------
REPO_B="$WORK/repo-b"
mkdir -p "$REPO_B"
(cd "$REPO_B" && git init -q && git -c user.name=t -c user.email=t@t.test commit -q --allow-empty -m init)

before=$(cd "$REPO_B" && git status --porcelain)
out=$(cd "$REPO_B" && env -u CLAUDE_PROJECT_DIR PATH="$STUB_070:$SYS_PATH" sh "$HOOK")
code=$?
after=$(cd "$REPO_B" && git status --porcelain)

case "$out" in
    *"metaproject new . --dry-run"*)
        pass "b: missing .metaproject.json -> mentions dry-run command"
        ;;
    *)
        fail "b: missing .metaproject.json -> notice missing dry-run text: [$out]"
        ;;
esac
if [ "$code" -eq 0 ]; then
    pass "b: exit 0"
else
    fail "b: exit code $code (expected 0)"
fi
if [ "$before" = "$after" ]; then
    pass "b: no files written"
else
    fail "b: git status changed ($before -> $after)"
fi

# ------------------------------------------------------------------------
# Case c: PATH without metaproject -> install notice, exit 0
# ------------------------------------------------------------------------
# The hook runs with PATH="$SYS_PATH" only, so a metaproject the caller has installed
# elsewhere (e.g. ~/.local/bin) is irrelevant. The precondition is that the system
# PATH itself has none.
if PATH="$SYS_PATH" command -v metaproject >/dev/null 2>&1; then
    found=$(PATH="$SYS_PATH" command -v metaproject)
    fail "c: precondition — a metaproject exists on the system PATH ($SYS_PATH): $found"
fi

REPO_C="$WORK/repo-c"
make_managed_repo "$REPO_C"

before=$(cd "$REPO_C" && git status --porcelain)
out=$(cd "$REPO_C" && env -u CLAUDE_PROJECT_DIR PATH="$SYS_PATH" sh "$HOOK")
code=$?
after=$(cd "$REPO_C" && git status --porcelain)

case "$out" in
    *"not installed"*|*"install"*)
        pass "c: no metaproject on PATH -> install notice"
        ;;
    *)
        fail "c: no metaproject on PATH -> unexpected output: [$out]"
        ;;
esac
if [ "$code" -eq 0 ]; then
    pass "c: exit 0"
else
    fail "c: exit code $code (expected 0)"
fi
if [ "$before" = "$after" ]; then
    pass "c: no files written"
else
    fail "c: git status changed ($before -> $after)"
fi

# ------------------------------------------------------------------------
# Case d: stub 0.6.1 -> upgrade notice mentioning 0.6.1, exit 0
# ------------------------------------------------------------------------
REPO_D="$WORK/repo-d"
make_managed_repo "$REPO_D"

before=$(cd "$REPO_D" && git status --porcelain)
out=$(cd "$REPO_D" && env -u CLAUDE_PROJECT_DIR PATH="$STUB_061:$SYS_PATH" sh "$HOOK")
code=$?
after=$(cd "$REPO_D" && git status --porcelain)

case "$out" in
    *"0.6.1"*)
        pass "d: metaproject 0.6.1 -> upgrade notice mentions 0.6.1"
        ;;
    *)
        fail "d: metaproject 0.6.1 -> notice missing version: [$out]"
        ;;
esac
if [ "$code" -eq 0 ]; then
    pass "d: exit 0"
else
    fail "d: exit code $code (expected 0)"
fi
if [ "$before" = "$after" ]; then
    pass "d: no files written"
else
    fail "d: git status changed ($before -> $after)"
fi

# ------------------------------------------------------------------------
# Case e: subdirectory of managed repo, CLAUDE_PROJECT_DIR unset -> passes
# ------------------------------------------------------------------------
REPO_E="$WORK/repo-e"
make_managed_repo "$REPO_E"
mkdir -p "$REPO_E/sub/dir"

before=$(cd "$REPO_E" && git status --porcelain)
out=$(cd "$REPO_E/sub/dir" && env -u CLAUDE_PROJECT_DIR PATH="$STUB_070:$SYS_PATH" sh "$HOOK")
code=$?
after=$(cd "$REPO_E" && git status --porcelain)

if [ -z "$out" ] && [ "$code" -eq 0 ]; then
    pass "e: subdirectory of managed repo -> silent, exit 0"
else
    fail "e: subdirectory of managed repo -> got output [$out] exit $code"
fi
if [ "$before" = "$after" ]; then
    pass "e: no files written"
else
    fail "e: git status changed ($before -> $after)"
fi

# ------------------------------------------------------------------------
# Case f: git worktree of managed repo -> passes
# ------------------------------------------------------------------------
REPO_F="$WORK/repo-f"
make_managed_repo "$REPO_F"
WORKTREE_F="$WORK/repo-f-worktree"
(cd "$REPO_F" && git branch wt-branch >/dev/null 2>&1; git worktree add -q "$WORKTREE_F" wt-branch) >/dev/null 2>&1

if [ -d "$WORKTREE_F" ]; then
    before=$(cd "$WORKTREE_F" && git status --porcelain)
    out=$(cd "$WORKTREE_F" && env -u CLAUDE_PROJECT_DIR PATH="$STUB_070:$SYS_PATH" sh "$HOOK")
    code=$?
    after=$(cd "$WORKTREE_F" && git status --porcelain)

    if [ -z "$out" ] && [ "$code" -eq 0 ]; then
        pass "f: git worktree of managed repo -> silent, exit 0"
    else
        fail "f: git worktree of managed repo -> got output [$out] exit $code"
    fi
    if [ "$before" = "$after" ]; then
        pass "f: no files written"
    else
        fail "f: git status changed ($before -> $after)"
    fi
else
    fail "f: could not create git worktree for test"
fi

# ------------------------------------------------------------------------
# Case g: CLAUDE_PROJECT_DIR set to managed repo, cwd elsewhere -> passes
# ------------------------------------------------------------------------
REPO_G="$WORK/repo-g"
make_managed_repo "$REPO_G"
ELSEWHERE="$WORK/elsewhere"
mkdir -p "$ELSEWHERE"

before=$(cd "$REPO_G" && git status --porcelain)
out=$(cd "$ELSEWHERE" && env CLAUDE_PROJECT_DIR="$REPO_G" PATH="$STUB_070:$SYS_PATH" sh "$HOOK")
code=$?
after=$(cd "$REPO_G" && git status --porcelain)

if [ -z "$out" ] && [ "$code" -eq 0 ]; then
    pass "g: CLAUDE_PROJECT_DIR points at managed repo -> silent, exit 0"
else
    fail "g: CLAUDE_PROJECT_DIR points at managed repo -> got output [$out] exit $code"
fi
if [ "$before" = "$after" ]; then
    pass "g: no files written in target repo"
else
    fail "g: git status changed ($before -> $after)"
fi

# ------------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------------
if [ "$FAIL" -eq 0 ]; then
    echo "All tests passed."
    exit 0
else
    echo "Some tests FAILED."
    exit 1
fi
