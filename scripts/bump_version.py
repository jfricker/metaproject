#!/usr/bin/env python3
"""Automated semantic version incrementing based on git heuristics.

Heuristics:
1. If new files have been added -> Major version increment.
2. If files have been changed, a new command added to existing files -> Minor version increment.
3. If it's only bug fixes -> Patch version increment.
4. If the major version is 0 -> Only increment minor version or patch number (downgrade major to minor).
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

IGNORED_PATHS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".DS_Store",
    "dist",
    "build",
    "__pycache__",
    ".venv",
    ".idea",
    ".vscode",
    ".remember",
}


def get_repo_root() -> Path:
    """Resolve git repository root."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(res.stdout.strip())
    except Exception:
        return Path(__file__).resolve().parent.parent


def get_current_version(repo_root: Path) -> str:
    """Read current version from pyproject.toml."""
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject}")
    match = re.search(r'version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"))
    if not match:
        raise ValueError("Could not find version field in pyproject.toml")
    return match.group(1)


def parse_semver(version: str) -> Tuple[int, int, int]:
    """Parse semver string 'X.Y.Z' into integer tuple (major, minor, patch)."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise ValueError(f"Invalid semver version format: {version}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def is_ignored_file(rel_path: str) -> bool:
    """Check if file path belongs to ignored directory or cache."""
    parts = Path(rel_path).parts
    return any(p in IGNORED_PATHS or p.endswith(".egg-info") for p in parts)


def get_uncommitted_new_files(repo_root: Path) -> List[str]:
    """Get list of newly added or untracked files in working tree."""
    new_files = []
    res = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    for line in res.stdout.splitlines():
        if len(line) < 3:
            continue
        status = line[:2]
        file_path = line[3:].strip()
        if "?" in status or "A" in status:
            if not is_ignored_file(file_path):
                new_files.append(file_path)
    return new_files


def get_committed_new_files_in_head(repo_root: Path) -> List[str]:
    """Get list of new files added in the most recent commit."""
    try:
        res = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-status", "-r", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        new_files = []
        for line in res.stdout.splitlines():
            parts = line.split(maxsplit=1)
            if len(parts) == 2 and parts[0] == "A":
                if not is_ignored_file(parts[1]):
                    new_files.append(parts[1])
        return new_files
    except Exception:
        return []


def diff_has_new_command(diff_text: str) -> bool:
    """Check if diff adds a new CLI command or subcommand."""
    patterns = [
        r"^\+\s*@app\.command\(",
        r"^\+\s*@\w+\.command\(",
        r"^\+\s*@\w+\.callback\(",
        r"^\+\s*def\s+\w+_cmd\(",
        r"^\+\s*.*app\.add_typer\(",
    ]
    for line in diff_text.splitlines():
        for pat in patterns:
            if re.search(pat, line):
                return True
    return False


def get_diff_content(repo_root: Path) -> str:
    """Retrieve working tree diff or diff of the latest commit."""
    res_unstaged = subprocess.run(
        ["git", "diff"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    res_staged = subprocess.run(
        ["git", "diff", "--staged"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    diff = res_unstaged.stdout + "\n" + res_staged.stdout
    if diff.strip():
        return diff

    res_head = subprocess.run(
        ["git", "show", "--format=", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return res_head.stdout


def get_head_commit_message(repo_root: Path) -> str:
    """Get subject and body of latest commit."""
    res = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return res.stdout.strip()


def decide_bump_type(
    repo_root: Path,
    current_major: int,
    force_type: Optional[str] = None,
) -> Tuple[str, str]:
    """Heuristically decide whether to bump major, minor, or patch."""
    if force_type in {"major", "minor", "patch"}:
        decided = force_type
        explanation = f"Explicitly forced as '{force_type}'"
    else:
        # Heuristic 1: New files added -> Major
        uncommitted_new = get_uncommitted_new_files(repo_root)
        committed_new = get_committed_new_files_in_head(repo_root) if not uncommitted_new else []
        new_files = uncommitted_new or committed_new

        diff = get_diff_content(repo_root)
        commit_msg = get_head_commit_message(repo_root).lower()

        if new_files:
            decided = "major"
            explanation = f"New file(s) added: {', '.join(new_files[:3])}"
            if len(new_files) > 3:
                explanation += f" (+{len(new_files) - 3} more)"
        elif diff_has_new_command(diff) or "feat" in commit_msg or "command" in commit_msg:
            decided = "minor"
            explanation = "New command or feature detected in existing files"
        else:
            decided = "patch"
            explanation = "Only bug fixes or maintenance changes detected"

    # Heuristic 4: If major version is 0, only increment minor or patch
    if current_major == 0 and decided == "major":
        decided = "minor"
        explanation += " [Major version is 0; downgraded major -> minor increment per policy]"

    return decided, explanation


def compute_next_version(current: str, bump_type: str) -> str:
    """Compute incremented semver version string."""
    major, minor, patch = parse_semver(current)
    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    elif bump_type == "patch":
        return f"{major}.{minor}.{patch + 1}"
    else:
        raise ValueError(f"Unknown bump type: {bump_type}")


def update_version_in_file(path: Path, pattern: str, replacement: str) -> bool:
    """Update regex pattern in specified file if exists."""
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    new_content = re.sub(pattern, replacement, content)
    if new_content != content:
        path.write_text(new_content, encoding="utf-8")
        return True
    return False


def apply_version_bump(repo_root: Path, old_version: str, new_version: str) -> Dict[str, bool]:
    """Update version across pyproject.toml, package __init__, CLI, baseline tests, and README."""
    results = {}

    # 1. pyproject.toml
    pyproject = repo_root / "pyproject.toml"
    results["pyproject.toml"] = update_version_in_file(
        pyproject,
        rf'version\s*=\s*"{re.escape(old_version)}"',
        f'version = "{new_version}"',
    )

    # 2. src/metaproject/__init__.py
    init_py = repo_root / "src" / "metaproject" / "__init__.py"
    results["src/metaproject/__init__.py"] = update_version_in_file(
        init_py,
        rf'__version__\s*=\s*"{re.escape(old_version)}"',
        f'__version__ = "{new_version}"',
    )

    # 3. src/metaproject/cli.py
    cli_py = repo_root / "src" / "metaproject" / "cli.py"
    results["src/metaproject/cli.py"] = update_version_in_file(
        cli_py,
        rf'"version":\s*"{re.escape(old_version)}"',
        f'"version": "{new_version}"',
    )

    # 4. tests/test_baseline.py
    test_baseline = repo_root / "tests" / "test_baseline.py"
    if test_baseline.exists():
        c = test_baseline.read_text(encoding="utf-8")
        c = c.replace(f'"{old_version}"', f'"{new_version}"')
        test_baseline.write_text(c, encoding="utf-8")
        results["tests/test_baseline.py"] = True

    # 5. README.md
    readme = repo_root / "README.md"
    results["README.md"] = update_version_in_file(
        readme,
        rf'metaproject=={re.escape(old_version)}',
        f'metaproject=={new_version}',
    )

    return results


def commit_version_files(
    repo_root: Path,
    updated_files: Dict[str, bool],
    old_version: str,
    new_version: str,
    is_milestone: bool,
    summary: str,
) -> Optional[str]:
    """Stage modified version files and create a git commit."""
    files_to_commit = [file_path for file_path, modified in updated_files.items() if modified]
    if not files_to_commit:
        return None

    bump_category = "Milestone" if is_milestone else "Heuristic"
    commit_title = f"chore(release): bump version to {new_version} [{bump_category}]"
    commit_body = f"{bump_category} bump: {old_version} -> {new_version}\n\nSummary: {summary}"
    full_message = f"{commit_title}\n\n{commit_body}"

    try:
        subprocess.run(["git", "add"] + files_to_commit, cwd=repo_root, check=True)
        subprocess.run(
            ["git", "commit", "-m", full_message],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return commit_title
    except Exception as exc:
        print(f"Warning: Failed to create git commit: {exc}", file=sys.stderr)
        return None


def main() -> int:
    """Main entrypoint for version increment script."""
    parser = argparse.ArgumentParser(
        description="Semantic version incrementing with git heuristics or operator milestone command."
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=["major", "heuristic"],
        default="heuristic",
        help="Version increment command: 'major' forces a milestone major bump (zeroing minor and patch); 'heuristic' automatically determines bump type (default).",
    )
    parser.add_argument(
        "--major",
        action="store_true",
        help="Force a milestone major version bump (zeroing minor and patch).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview version increment decision without modifying files or committing.",
    )
    parser.add_argument(
        "--force",
        choices=["major", "minor", "patch"],
        help="Force a specific bump type, overriding heuristic detection.",
    )
    parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Do not commit version files after updating.",
    )
    parser.add_argument(
        "--current",
        action="store_true",
        help="Print current version and exit.",
    )

    args = parser.parse_args()
    repo_root = get_repo_root()

    try:
        current_version = get_current_version(repo_root)
    except Exception as exc:
        print(f"Error reading version: {exc}", file=sys.stderr)
        return 1

    if args.current:
        print(current_version)
        return 0

    major, _, _ = parse_semver(current_version)
    is_milestone = args.action == "major" or args.major

    if is_milestone:
        bump_type = "major"
        explanation = "Milestone release: operator forced major version increment (zeroed minor and patch)"
        next_version = compute_next_version(current_version, "major")
    else:
        bump_type, explanation = decide_bump_type(repo_root, major, force_type=args.force)
        next_version = compute_next_version(current_version, bump_type)

    bump_category = "Milestone" if is_milestone else "Heuristic"

    print(f"Current version: {current_version}")
    print(f"Bump category:   {bump_category}")
    print(f"Decision summary: {explanation}")
    print(f"Increment type:  {bump_type.upper()}")
    print(f"Target version:  {next_version}")

    if args.dry_run:
        print("\n[Dry run] No files were modified and no git commit was created.")
        print(f"[Dry run] Planned commit: chore(release): bump version to {next_version} [{bump_category}]")
        return 0

    results = apply_version_bump(repo_root, current_version, next_version)
    print("\nUpdated files:")
    for file_name, modified in results.items():
        status = "✓ updated" if modified else "— unchanged"
        print(f"  {status:12} {file_name}")

    print(f"\nSuccessfully incremented version: {current_version} -> {next_version}")

    if not args.no_commit:
        commit_title = commit_version_files(
            repo_root,
            results,
            current_version,
            next_version,
            is_milestone,
            explanation,
        )
        if commit_title:
            print(f"Git commit created: {commit_title}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
