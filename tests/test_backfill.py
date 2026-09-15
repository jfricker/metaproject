"""Tests for `review.backfill_missing` and the `metaproject backfill` CLI command.

Since D1 the bundled store templates every scaffolded deliverable, so these tests
scaffold against it directly rather than a purpose-built store.
"""

import shutil
from pathlib import Path
from typing import List

import pytest
from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.review import BackfillResult, backfill_missing
from metaproject.scaffold import scaffold_project
from metaproject.templates import get_bundled_templates_dir


def scaffolded_project(tmp_path: Path, name: str = "proj") -> tuple[Path, Path]:
    """A project scaffolded against the bundled store, plus that store's path."""
    templates = get_bundled_templates_dir()
    proj = tmp_path / name
    scaffold_project(
        project_name=name,
        output=proj,
        templates_dir=templates,
        interactive=False,
        no_git=True,
    )
    return proj, templates


def store_missing_a_template(tmp_path: Path, missing: str) -> Path:
    """A copy of the bundled store with one top-level template file removed.

    For exercising `missing_template` behaviour now that the real bundled store (since
    D1) templates every deliverable — that path needs a store deliberately incomplete.
    """
    store = tmp_path / "incomplete_templates"
    shutil.copytree(get_bundled_templates_dir(), store)
    (store / missing).unlink()
    return store


# ------------------------------------------------------------------------ backfill_missing


def test_ac10_backfill_recreates_deleted_files_and_lists_skipped(tmp_path: Path) -> None:
    """AC-10: deleting spec/design/STATE and backfilling recreates all three in one call."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / "spec.md").unlink()
    (proj / "design.md").unlink()
    (proj / "STATE.md").unlink()

    result = backfill_missing(proj, templates_dir=templates)

    assert isinstance(result, BackfillResult)
    assert set(result.created) == {"spec.md", "design.md", "STATE.md"}
    assert (proj / "spec.md").exists()
    assert (proj / "design.md").exists()
    assert (proj / "STATE.md").exists()
    # Everything else scaffolded was already present, and is reported skipped rather than
    # silently ignored.
    assert "AGENTS.md" in result.skipped
    assert "README.md" in result.skipped
    assert "intent.md" in result.skipped
    assert result.refused == []
    assert result.missing_template == []


def test_backfill_by_name_creates_on_demand_handoff(tmp_path: Path) -> None:
    """`backfill HANDOFF.md` creates the on-demand file `new` never scaffolds."""
    proj, templates = scaffolded_project(tmp_path)
    assert not (proj / "HANDOFF.md").exists()

    result = backfill_missing(proj, files=["HANDOFF.md"], templates_dir=templates)

    assert result.created == ["HANDOFF.md"]
    assert (proj / "HANDOFF.md").exists()
    assert result.refused == []
    assert result.skipped == []
    assert result.missing_template == []


def test_backfill_named_existing_file_refuses_and_writes_nothing(tmp_path: Path) -> None:
    """A named file that already exists is refused; nothing at all is written."""
    proj, templates = scaffolded_project(tmp_path)
    before = (proj / "spec.md").read_bytes()

    other_missing = proj / "STATE.md"
    other_missing.unlink()

    result = backfill_missing(proj, files=["spec.md"], templates_dir=templates)

    assert result.refused == ["spec.md"]
    assert result.created == []
    assert (proj / "spec.md").read_bytes() == before
    # Nothing else got written either, even though STATE.md was itself missing.
    assert not other_missing.exists()


def test_backfill_missing_template_named_file_writes_nothing(tmp_path: Path) -> None:
    """A named file with no template anywhere in the store is reported, nothing written."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / "STATE.md").unlink()

    result = backfill_missing(
        proj, files=["STATE.md", "no-such-template.md"], templates_dir=templates
    )

    assert result.missing_template == ["no-such-template.md"]
    assert result.created == []
    assert not (proj / "STATE.md").exists()


def test_backfill_no_files_missing_template_lists_it_others_still_created(
    tmp_path: Path,
) -> None:
    """In no-files mode, a deliverable with no template is listed but others are created.

    Since D1 the real bundled store templates every deliverable, so this deliberately
    uses a store missing one (`spec.template.md`) to exercise the `missing_template`
    path.
    """
    templates = store_missing_a_template(tmp_path, "spec.template.md")
    proj = tmp_path / "incomplete_proj"
    proj.mkdir()
    (proj / "README.md").write_text("# incomplete_proj\n", encoding="utf-8")

    result = backfill_missing(proj, templates_dir=templates)

    assert "spec.md" in result.missing_template
    # Deliverables the store *does* template are still created.
    assert "AGENTS.md" in result.created
    assert (proj / "AGENTS.md").exists()
    assert "design.md" in result.created
    assert (proj / "design.md").exists()


def test_backfill_dry_run_writes_nothing(tmp_path: Path) -> None:
    """`--dry-run` computes the same lists but writes nothing to disk."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / "spec.md").unlink()
    (proj / "design.md").unlink()

    before_listing = sorted(p.relative_to(proj) for p in proj.rglob("*"))

    result = backfill_missing(proj, templates_dir=templates, dry_run=True)

    assert set(result.created) == {"spec.md", "design.md"}
    after_listing = sorted(p.relative_to(proj) for p in proj.rglob("*"))
    assert before_listing == after_listing
    assert not (proj / "spec.md").exists()
    assert not (proj / "design.md").exists()


def test_backfill_dry_run_named_refusal_writes_nothing(tmp_path: Path) -> None:
    """`--dry-run` on a named, already-existing file still reports refused and writes nothing."""
    proj, templates = scaffolded_project(tmp_path)
    before = (proj / "spec.md").read_bytes()

    result = backfill_missing(proj, files=["spec.md"], templates_dir=templates, dry_run=True)

    assert result.refused == ["spec.md"]
    assert (proj / "spec.md").read_bytes() == before


def test_backfill_never_runs_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`backfill_missing` never shells out to git, in any mode."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / "spec.md").unlink()
    (proj / "design.md").unlink()
    (proj / "STATE.md").unlink()

    import subprocess

    def _forbidden(*args, **kwargs):
        raise AssertionError("backfill_missing must never invoke a subprocess (git)")

    monkeypatch.setattr(subprocess, "run", _forbidden)

    result = backfill_missing(proj, templates_dir=templates)
    assert set(result.created) == {"spec.md", "design.md", "STATE.md"}

    result_named = backfill_missing(proj, files=["HANDOFF.md"], templates_dir=templates)
    assert result_named.created == ["HANDOFF.md"]


def test_backfill_resolves_variables_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One `resolve_variables` call per batch, before the first write."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / "spec.md").unlink()
    (proj / "design.md").unlink()
    (proj / "STATE.md").unlink()

    from metaproject import review as review_module

    calls = {"count": 0}
    original = review_module.resolve_variables

    def counting_wrapper(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(review_module, "resolve_variables", counting_wrapper)

    result = backfill_missing(proj, templates_dir=templates)

    assert set(result.created) == {"spec.md", "design.md", "STATE.md"}
    assert calls["count"] == 1


# ---------------------------------------------------------------------------------- CLI


def test_cli_backfill_ac10_all_missing_in_one_call(runner: CliRunner, tmp_path: Path) -> None:
    proj, templates = scaffolded_project(tmp_path)
    (proj / "spec.md").unlink()
    (proj / "design.md").unlink()
    (proj / "STATE.md").unlink()

    result = runner.invoke(
        app,
        ["backfill", "--dir", str(proj), "--templates", str(templates)],
    )

    assert result.exit_code == 0, result.output
    assert "spec.md" in result.output
    assert "design.md" in result.output
    assert "STATE.md" in result.output
    assert (proj / "spec.md").exists()
    assert (proj / "design.md").exists()
    assert (proj / "STATE.md").exists()
    # Skipped (already-present) files are listed too.
    assert "AGENTS.md" in result.output


def test_cli_backfill_by_name_creates_handoff(runner: CliRunner, tmp_path: Path) -> None:
    proj, templates = scaffolded_project(tmp_path)

    result = runner.invoke(
        app,
        ["backfill", "HANDOFF.md", "--dir", str(proj), "--templates", str(templates)],
    )

    assert result.exit_code == 0, result.output
    assert (proj / "HANDOFF.md").exists()


def test_cli_backfill_named_existing_exits_nonzero_and_writes_nothing(
    runner: CliRunner, tmp_path: Path
) -> None:
    proj, templates = scaffolded_project(tmp_path)
    before = (proj / "spec.md").read_bytes()

    result = runner.invoke(
        app,
        ["backfill", "spec.md", "--dir", str(proj), "--templates", str(templates)],
    )

    assert result.exit_code == 1
    assert (proj / "spec.md").read_bytes() == before


def test_cli_backfill_runs_in_agent_session(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`backfill` is not agent-guarded (unlike the TUI/scan guards)."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / "spec.md").unlink()

    monkeypatch.setenv("METAPROJECT_AGENT", "1")
    monkeypatch.setenv("CLAUDECODE", "1")

    result = runner.invoke(
        app,
        ["backfill", "--dir", str(proj), "--templates", str(templates)],
    )

    assert result.exit_code == 0, result.output
    assert (proj / "spec.md").exists()


def test_cli_backfill_dry_run_writes_nothing(runner: CliRunner, tmp_path: Path) -> None:
    proj, templates = scaffolded_project(tmp_path)
    (proj / "spec.md").unlink()
    (proj / "design.md").unlink()

    before_listing: List[Path] = sorted(p.relative_to(proj) for p in proj.rglob("*"))

    result = runner.invoke(
        app,
        ["backfill", "--dir", str(proj), "--templates", str(templates), "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    after_listing = sorted(p.relative_to(proj) for p in proj.rglob("*"))
    assert before_listing == after_listing
    assert not (proj / "spec.md").exists()
    assert not (proj / "design.md").exists()


def test_cli_backfill_no_git_ever(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj, templates = scaffolded_project(tmp_path)
    (proj / "spec.md").unlink()

    import subprocess

    def _forbidden(*args, **kwargs):
        raise AssertionError("backfill CLI must never invoke a subprocess (git)")

    monkeypatch.setattr(subprocess, "run", _forbidden)

    result = runner.invoke(
        app,
        ["backfill", "--dir", str(proj), "--templates", str(templates)],
    )

    assert result.exit_code == 0, result.output
    assert (proj / "spec.md").exists()


def test_cli_backfill_missing_template_named_file(runner: CliRunner, tmp_path: Path) -> None:
    proj, templates = scaffolded_project(tmp_path)

    result = runner.invoke(
        app,
        ["backfill", "no-such-template.md", "--dir", str(proj), "--templates", str(templates)],
    )

    assert result.exit_code == 1
    assert "no-such-template.md" in result.output
    assert not (proj / "no-such-template.md").exists()


def test_cli_backfill_missing_template_no_files_mode_lists_and_creates_others(
    runner: CliRunner, tmp_path: Path
) -> None:
    """Since D1 the real bundled store templates every deliverable, so this deliberately
    uses a store missing one (`spec.template.md`) to exercise the `missing_template`
    path."""
    templates = store_missing_a_template(tmp_path, "spec.template.md")
    proj = tmp_path / "incomplete_proj"
    proj.mkdir()
    (proj / "README.md").write_text("# incomplete_proj\n", encoding="utf-8")

    result = runner.invoke(app, ["backfill", "--dir", str(proj), "--templates", str(templates)])

    assert result.exit_code == 1
    assert "spec.md" in result.output
    assert (proj / "AGENTS.md").exists()
