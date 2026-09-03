"""Unit tests for development version incrementing script (scripts/bump_version.py)."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

# Load scripts/bump_version.py dynamically as a module
scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
spec = importlib.util.spec_from_file_location("bump_version", scripts_dir / "bump_version.py")
bump_version = importlib.util.module_from_spec(spec)
sys.modules["bump_version"] = bump_version
spec.loader.exec_module(bump_version)


def test_parse_semver() -> None:
    """Verify parsing valid and invalid semver strings."""
    assert bump_version.parse_semver("0.1.2") == (0, 1, 2)
    assert bump_version.parse_semver("1.0.0") == (1, 0, 0)
    assert bump_version.parse_semver("2.14.35") == (2, 14, 35)

    with pytest.raises(ValueError):
        bump_version.parse_semver("invalid")


def test_compute_next_version() -> None:
    """Verify next version computation for major, minor, and patch."""
    # Standard increments
    assert bump_version.compute_next_version("1.2.3", "major") == "2.0.0"
    assert bump_version.compute_next_version("1.2.3", "minor") == "1.3.0"
    assert bump_version.compute_next_version("1.2.3", "patch") == "1.2.4"

    # From 0.x.x
    assert bump_version.compute_next_version("0.1.2", "minor") == "0.2.0"
    assert bump_version.compute_next_version("0.1.2", "patch") == "0.1.3"


def test_decide_bump_type_major_zero_policy(tmp_path: Path) -> None:
    """Verify major increments are downgraded to minor when major version is 0."""
    # Forced major when major is 0 -> downgraded to minor
    bump, expl = bump_version.decide_bump_type(tmp_path, current_major=0, force_type="major")
    assert bump == "minor"
    assert "downgraded" in expl

    # Forced major when major is 1 -> remains major
    bump1, expl1 = bump_version.decide_bump_type(tmp_path, current_major=1, force_type="major")
    assert bump1 == "major"


def test_diff_has_new_command() -> None:
    """Verify detection of new CLI command annotations in diff content."""
    diff_with_command = """
+@app.command(name="summary")
+def summary_cmd():
+    pass
"""
    assert bump_version.diff_has_new_command(diff_with_command) is True

    diff_fix_only = """
-    timeout = 10
+    timeout = 20
-    return None
+    return False
"""
    assert bump_version.diff_has_new_command(diff_fix_only) is False


def test_apply_version_bump(tmp_path: Path) -> None:
    """Verify updating version strings across all target files."""
    old_v = "0.1.2"
    new_v = "0.2.0"

    # Setup dummy repo structure
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[project]\nversion = "{old_v}"\n', encoding="utf-8")

    src_dir = tmp_path / "src" / "metaproject"
    src_dir.mkdir(parents=True)
    init_file = src_dir / "__init__.py"
    init_file.write_text(f'__version__ = "{old_v}"\n', encoding="utf-8")

    cli_file = src_dir / "cli.py"
    cli_file.write_text(f'meta = {{"version": "{old_v}"}}\n', encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    baseline = tests_dir / "test_baseline.py"
    baseline.write_text(
        f'assert __version__ == "{old_v}"\nassert "{old_v}" in out\n', encoding="utf-8"
    )

    readme = tmp_path / "README.md"
    readme.write_text(f"pip install metaproject=={old_v}\n", encoding="utf-8")

    # Run bump
    results = bump_version.apply_version_bump(tmp_path, old_v, new_v)
    assert all(results.values())

    # Verify contents
    assert f'version = "{new_v}"' in pyproject.read_text(encoding="utf-8")
    assert f'__version__ = "{new_v}"' in init_file.read_text(encoding="utf-8")
    assert f'"version": "{new_v}"' in cli_file.read_text(encoding="utf-8")
    assert f'assert __version__ == "{new_v}"' in baseline.read_text(encoding="utf-8")
    assert f'assert "{new_v}" in out' in baseline.read_text(encoding="utf-8")
    assert f"pip install metaproject=={new_v}" in readme.read_text(encoding="utf-8")


def test_cli_bump_script_execution() -> None:
    """Verify executing scripts/bump_version.py via subprocess."""
    script_path = scripts_dir / "bump_version.py"

    repo_root = bump_version.get_repo_root()
    curr_v = bump_version.get_current_version(repo_root)

    # 1. --current
    res_curr = subprocess.run(
        [sys.executable, str(script_path), "--current"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res_curr.stdout.strip() == curr_v

    # 2. --dry-run (heuristic)
    res_dry = subprocess.run(
        [sys.executable, str(script_path), "--dry-run"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert f"Current version: {curr_v}" in res_dry.stdout
    assert "Bump category:   Heuristic" in res_dry.stdout
    assert "Target version:" in res_dry.stdout
    assert "[Dry run]" in res_dry.stdout
    assert "[Heuristic]" in res_dry.stdout

    # 3. major --dry-run (milestone)
    res_major = subprocess.run(
        [sys.executable, str(script_path), "major", "--dry-run"],
        capture_output=True,
        text=True,
        check=True,
    )
    major_num, _, _ = bump_version.parse_semver(curr_v)
    expected_major = f"{major_num + 1}.0.0"
    assert "Bump category:   Milestone" in res_major.stdout
    assert "Increment type:  MAJOR" in res_major.stdout
    assert f"Target version:  {expected_major}" in res_major.stdout
    assert "chore(release): bump version to 1.0.0 [Milestone]" in res_major.stdout


def test_commit_version_files(tmp_path: Path) -> None:
    """Verify git commit is created specifically for version files with proper message."""
    # Initialize a temporary git repository
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=tmp_path, check=True)

    # Create dummy version file and an unrelated file
    pyproj = tmp_path / "pyproject.toml"
    pyproj.write_text('version = "0.1.2"\n', encoding="utf-8")
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("should not be committed\n", encoding="utf-8")

    # Initial commit of base repo
    subprocess.run(["git", "add", "pyproject.toml"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "chore: initial commit"], cwd=tmp_path, check=True)

    # Modify pyproject.toml
    pyproj.write_text('version = "0.2.0"\n', encoding="utf-8")

    # Commit via bump_version helper
    updated_files = {"pyproject.toml": True}
    title = bump_version.commit_version_files(
        repo_root=tmp_path,
        updated_files=updated_files,
        old_version="0.1.2",
        new_version="0.2.0",
        is_milestone=False,
        summary="New commands detected in cli.py",
    )
    assert title == "chore(release): bump version to 0.2.0 [Heuristic]"

    # Verify git log
    log_res = subprocess.run(
        ["git", "log", "-1", "--pretty=fuller"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "chore(release): bump version to 0.2.0 [Heuristic]" in log_res.stdout
    assert "Heuristic bump: 0.1.2 -> 0.2.0" in log_res.stdout
    assert "New commands detected in cli.py" in log_res.stdout

    # Verify unrelated file is still untracked
    status_res = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "?? unrelated.txt" in status_res.stdout
