"""Tests for `metaproject new . --dry-run` previewing without a TTY, and for the
template store's OS/editor junk files never being treated as templates.

Bug 1: `--dry-run` must never prompt. Before this fix, scaffolding into an occupied
directory under `--dry-run` still ran variable collection interactively, which opens a
questionary prompt; with no TTY attached (as under `CliRunner` with no input, or an
agent session) that prompt aborts before any preview is shown.

Bug 2: a template store containing OS/editor junk (`.DS_Store`, AppleDouble `._*`
sidecars, `*~` backups, ...) must never have that junk copied into a scaffolded
project, listed as a "missing template", or otherwise treated as a template.
"""

from pathlib import Path
from typing import Dict

import pytest
from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.review import resolve_template_entry
from metaproject.templates import is_junk_file_name, seed_templates


def _snapshot(target: Path) -> Dict[str, str]:
    """A byte-for-byte snapshot of every file under `target`, keyed by relative path."""
    if not target.exists():
        return {}
    return {
        str(p.relative_to(target)): p.read_bytes().decode("utf-8", errors="replace")
        for p in sorted(target.rglob("*"))
        if p.is_file()
    }


def _occupied_dir(tmp_path: Path) -> Path:
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "main.py").write_text("print('hi')\n", encoding="utf-8")
    return target


# --------------------------------------------------------------------------- Bug 1


def test_dry_run_previews_without_prompting_when_stdin_is_not_a_tty(
    runner: CliRunner, tmp_path: Path
) -> None:
    """`CliRunner` supplies no input; a real run would need a confirmation, but
    `--dry-run` must preview instead of trying to prompt and aborting."""
    target = _occupied_dir(tmp_path)
    before = _snapshot(target)

    result = runner.invoke(
        app, ["new", ".", "--output", str(target) + "/", "--dry-run", "--no-git"]
    )

    assert result.exit_code == 0, result.output
    assert "Aborted" not in result.output
    assert "AGENTS.md" in result.output
    assert "would write .metaproject.json" in result.output
    assert _snapshot(target) == before
    assert sorted(p.name for p in target.iterdir()) == ["main.py"]


@pytest.mark.parametrize("marker", ["CLAUDECODE", "METAPROJECT_AGENT"])
def test_dry_run_previews_without_prompting_in_an_agent_session(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, marker: str
) -> None:
    """Same guarantee under an agent session (`CLAUDECODE=1` or `METAPROJECT_AGENT=1`):
    dry-run previews rather than prompting, and never aborts."""
    target = _occupied_dir(tmp_path)
    before = _snapshot(target)
    monkeypatch.setenv(marker, "1")

    result = runner.invoke(
        app, ["new", ".", "--output", str(target) + "/", "--dry-run", "--no-git"]
    )

    assert result.exit_code == 0, result.output
    assert "Aborted" not in result.output
    assert "AGENTS.md" in result.output
    assert "would write .metaproject.json" in result.output
    assert _snapshot(target) == before
    assert sorted(p.name for p in target.iterdir()) == ["main.py"]


def test_non_dry_run_backfill_still_refuses_without_confirmation(
    runner: CliRunner, tmp_path: Path
) -> None:
    """The dry-run fix must not loosen the real confirmation path: `new .` without
    `--dry-run`, `--yes`, or `--force` still refuses to write anything."""
    target = _occupied_dir(tmp_path)
    before = _snapshot(target)

    result = runner.invoke(app, ["new", ".", "--output", str(target) + "/", "--no-git"])

    assert result.exit_code == 1
    assert _snapshot(target) == before


# --------------------------------------------------------------------------- Bug 2


def _junky_store(tmp_path: Path) -> Path:
    """A minimal template store polluted with OS/editor junk files."""
    store = tmp_path / "templates"
    store.mkdir()
    (store / "AGENTS.template.md").write_text("# Agents\n", encoding="utf-8")
    (store / ".DS_Store").write_text("junk", encoding="utf-8")
    (store / "._foo").write_text("junk", encoding="utf-8")
    (store / "notes.md~").write_text("junk", encoding="utf-8")
    return store


def test_is_junk_file_name_matches_known_os_editor_junk() -> None:
    assert is_junk_file_name(".DS_Store")
    assert is_junk_file_name("Thumbs.db")
    assert is_junk_file_name("desktop.ini")
    assert is_junk_file_name("._foo")
    assert is_junk_file_name("notes.md~")
    assert is_junk_file_name(".notes.md.swp")
    assert not is_junk_file_name("AGENTS.md")
    assert not is_junk_file_name("AGENTS.template.md")


def test_new_does_not_create_junk_files_from_the_store(runner: CliRunner, tmp_path: Path) -> None:
    store = _junky_store(tmp_path)
    target = tmp_path / "demo"

    result = runner.invoke(
        app,
        [
            "new",
            "demo",
            "--output",
            str(target),
            "--templates",
            str(store),
            "--yes",
            "--no-git",
        ],
    )

    assert result.exit_code == 0, result.output
    assert not (target / ".DS_Store").exists()
    assert not (target / "._foo").exists()
    assert not (target / "notes.md~").exists()
    assert (target / "AGENTS.md").exists()


def test_seed_templates_does_not_copy_junk_files(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "AGENTS.template.md").write_text("# Agents\n", encoding="utf-8")
    (bundled / ".DS_Store").write_text("junk", encoding="utf-8")
    (bundled / "._foo").write_text("junk", encoding="utf-8")
    (bundled / "notes.md~").write_text("junk", encoding="utf-8")

    import metaproject.templates as templates_module

    original = templates_module.get_bundled_templates_dir
    templates_module.get_bundled_templates_dir = lambda: bundled
    try:
        dest = tmp_path / "seeded"
        copied = seed_templates(dest)
    finally:
        templates_module.get_bundled_templates_dir = original

    assert not (dest / ".DS_Store").exists()
    assert not (dest / "._foo").exists()
    assert not (dest / "notes.md~").exists()
    assert (dest / "AGENTS.md").exists() is False  # seed_templates does not transform names
    assert (dest / "AGENTS.template.md").exists()
    assert all(not is_junk_file_name(p.name) for p in copied)


def test_resolve_template_entry_never_resolves_junk(tmp_path: Path) -> None:
    store = _junky_store(tmp_path)
    assert resolve_template_entry(".DS_Store", store) is None
    assert resolve_template_entry("._foo", store) is None
    assert resolve_template_entry("notes.md~", store) is None
    assert resolve_template_entry("AGENTS.md", store) is not None


def test_dry_run_output_never_lists_junk_files(runner: CliRunner, tmp_path: Path) -> None:
    store = _junky_store(tmp_path)
    target = tmp_path / "demo_dry"

    result = runner.invoke(
        app,
        [
            "new",
            "demo_dry",
            "--output",
            str(target),
            "--templates",
            str(store),
            "--yes",
            "--no-git",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert ".DS_Store" not in result.output
    assert "._foo" not in result.output
    assert "notes.md~" not in result.output
    assert "AGENTS.md" in result.output
