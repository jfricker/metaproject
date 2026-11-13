"""The core install works without the optional `tui` extra (#3).

Each command runs in a fresh interpreter whose import system refuses `textual`,
`questionary` and `sqlite_utils`, which is what a `pip install metaproject` without
`[tui]` looks like to the package.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from metaproject.exceptions import MissingExtraError
from metaproject.extras import LazyModule, require

BLOCKED = ("textual", "questionary", "sqlite_utils")

RUNNER = textwrap.dedent(
    """
    import sys

    BLOCKED = {blocked!r}

    class Block:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in BLOCKED:
                raise ImportError(f"blocked for this test: {{name}}")
            return None

    sys.meta_path.insert(0, Block())
    from metaproject.cli import app

    try:
        app(args=sys.argv[1:], prog_name="metaproject")
    finally:
        leaked = sorted(m for m in sys.modules if m.split(".")[0] in BLOCKED)
        if leaked:
            print("LEAKED:", leaked)
    """
).format(blocked=BLOCKED)


def run_core(args, tmp_path: Path, extra_env=None) -> subprocess.CompletedProcess:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("METAPROJECT_AGENT", "CLAUDE_CODE_REMOTE", "METAPROJECT_PROFILE")
    }
    env["METAPROJECT_CONFIG_DIR"] = str(tmp_path / "cfg")
    env["CLAUDECODE"] = "1"
    env["COLUMNS"] = "200"
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-c", RUNNER, *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=120,
    )


@pytest.mark.parametrize("args", [["--version"], ["--help"]])
def test_version_and_help_without_extra(tmp_path: Path, args) -> None:
    result = run_core(args, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "LEAKED" not in result.stdout


def test_adopt_backfill_review_without_extra(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Repo\n", encoding="utf-8")

    adopt = run_core(["adopt", "--dir", str(repo)], tmp_path)
    assert adopt.returncode == 0, adopt.stdout + adopt.stderr
    assert (repo / ".metaproject.json").is_file()
    assert (repo / ".agents" / "skills" / "metaproject" / "SKILL.md").is_file()

    (repo / "docs" / "SPEC.md").unlink()
    backfill = run_core(["backfill", "--dir", str(repo)], tmp_path)
    assert backfill.returncode == 0, backfill.stdout + backfill.stderr
    assert (repo / "docs" / "SPEC.md").is_file()

    for args in (["review", str(repo), "--no-tui"], ["review", str(repo)]):
        review = run_core(args, tmp_path)
        assert review.returncode == 0, review.stdout + review.stderr

    for result in (adopt, backfill, review):
        assert "LEAKED" not in result.stdout


@pytest.mark.parametrize("args", [["universe", "--no-tui"], ["learn", "list"]])
def test_extra_commands_name_the_install_command(tmp_path: Path, args) -> None:
    result = run_core(args, tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "metaproject[tui]" in result.stdout
    assert "Traceback" not in result.stderr


def test_web_profile_notice_needs_no_extra(tmp_path: Path) -> None:
    result = run_core(["universe"], tmp_path, {"CLAUDE_CODE_REMOTE": "true"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "not available in web sessions" in result.stdout


def test_require_and_lazy_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "questionary", None)
    with pytest.raises(MissingExtraError, match=r"metaproject\[tui\]"):
        require("questionary", "Prompts")
    with pytest.raises(MissingExtraError):
        LazyModule("questionary", "Prompts").confirm  # noqa: B018
    assert require("json", "JSON").dumps([]) == "[]"
