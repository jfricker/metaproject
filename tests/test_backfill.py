"""Tests for `review.backfill_missing` and the `metaproject backfill` CLI command.

Since D1 the bundled store templates every scaffolded deliverable, so these tests
scaffold against it directly rather than a purpose-built store.
"""

import os
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
    (proj / ".metaproject/docs/SPEC.md").unlink()
    (proj / ".metaproject/docs/TECH-DESIGN.md").unlink()
    (proj / ".metaproject/docs/STATE.md").unlink()

    result = backfill_missing(proj, templates_dir=templates)

    assert isinstance(result, BackfillResult)
    assert set(result.created) == {
        ".metaproject/docs/SPEC.md",
        ".metaproject/docs/TECH-DESIGN.md",
        ".metaproject/docs/STATE.md",
    }
    assert (proj / ".metaproject/docs/SPEC.md").exists()
    assert (proj / ".metaproject/docs/TECH-DESIGN.md").exists()
    assert (proj / ".metaproject/docs/STATE.md").exists()
    # Everything else scaffolded was already present, and is reported skipped rather than
    # silently ignored.
    assert "AGENTS.md" in result.skipped
    assert "README.md" in result.skipped
    assert ".metaproject/docs/INTENT.md" in result.skipped
    assert result.refused == []
    assert result.missing_template == []


def test_backfill_by_name_creates_on_demand_handoff(tmp_path: Path) -> None:
    """`backfill HANDOFF.md` creates the on-demand file `new` never scaffolds."""
    proj, templates = scaffolded_project(tmp_path)
    assert not (proj / ".metaproject/docs/HANDOFF.md").exists()

    result = backfill_missing(proj, files=[".metaproject/docs/HANDOFF.md"], templates_dir=templates)

    assert result.created == [".metaproject/docs/HANDOFF.md"]
    assert (proj / ".metaproject/docs/HANDOFF.md").exists()
    assert result.refused == []
    assert result.skipped == []
    assert result.missing_template == []


def test_backfill_named_existing_file_refuses_and_writes_nothing(tmp_path: Path) -> None:
    """A named file that already exists is refused; nothing at all is written."""
    proj, templates = scaffolded_project(tmp_path)
    before = (proj / ".metaproject/docs/SPEC.md").read_bytes()

    other_missing = proj / ".metaproject/docs/STATE.md"
    other_missing.unlink()

    result = backfill_missing(proj, files=[".metaproject/docs/SPEC.md"], templates_dir=templates)

    assert result.refused == [".metaproject/docs/SPEC.md"]
    assert result.created == []
    assert (proj / ".metaproject/docs/SPEC.md").read_bytes() == before
    # Nothing else got written either, even though STATE.md was itself missing.
    assert not other_missing.exists()


def test_backfill_missing_template_named_file_writes_nothing(tmp_path: Path) -> None:
    """A named file with no template anywhere in the store is reported, nothing written."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / ".metaproject/docs/STATE.md").unlink()

    result = backfill_missing(
        proj, files=[".metaproject/docs/STATE.md", "no-such-template.md"], templates_dir=templates
    )

    assert result.missing_template == ["no-such-template.md"]
    assert result.created == []
    assert not (proj / ".metaproject/docs/STATE.md").exists()


def test_backfill_no_files_missing_template_lists_it_others_still_created(
    tmp_path: Path,
) -> None:
    """In no-files mode, a deliverable with no template is listed but others are created.

    Since D1 the real bundled store templates every deliverable, so this deliberately
    uses a store missing one (`spec.template.md`) to exercise the `missing_template`
    path.
    """
    templates = store_missing_a_template(
        tmp_path, ".metaproject.template/docs.template/SPEC.template.md"
    )
    proj = tmp_path / "incomplete_proj"
    proj.mkdir()
    (proj / "README.md").write_text("# incomplete_proj\n", encoding="utf-8")

    result = backfill_missing(proj, templates_dir=templates)

    assert ".metaproject/docs/SPEC.md" in result.missing_template
    # Deliverables the store *does* template are still created.
    assert "AGENTS.md" in result.created
    assert (proj / "AGENTS.md").exists()
    assert ".metaproject/docs/TECH-DESIGN.md" in result.created
    assert (proj / ".metaproject/docs/TECH-DESIGN.md").exists()


def test_backfill_dry_run_writes_nothing(tmp_path: Path) -> None:
    """`--dry-run` computes the same lists but writes nothing to disk."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / ".metaproject/docs/SPEC.md").unlink()
    (proj / ".metaproject/docs/TECH-DESIGN.md").unlink()

    before_listing = sorted(p.relative_to(proj) for p in proj.rglob("*"))

    result = backfill_missing(proj, templates_dir=templates, dry_run=True)

    assert set(result.created) == {".metaproject/docs/SPEC.md", ".metaproject/docs/TECH-DESIGN.md"}
    after_listing = sorted(p.relative_to(proj) for p in proj.rglob("*"))
    assert before_listing == after_listing
    assert not (proj / ".metaproject/docs/SPEC.md").exists()
    assert not (proj / ".metaproject/docs/TECH-DESIGN.md").exists()


def test_backfill_dry_run_named_refusal_writes_nothing(tmp_path: Path) -> None:
    """`--dry-run` on a named, already-existing file still reports refused and writes nothing."""
    proj, templates = scaffolded_project(tmp_path)
    before = (proj / ".metaproject/docs/SPEC.md").read_bytes()

    result = backfill_missing(
        proj, files=[".metaproject/docs/SPEC.md"], templates_dir=templates, dry_run=True
    )

    assert result.refused == [".metaproject/docs/SPEC.md"]
    assert (proj / ".metaproject/docs/SPEC.md").read_bytes() == before


def test_backfill_never_runs_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`backfill_missing` never shells out to git, in any mode."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / ".metaproject/docs/SPEC.md").unlink()
    (proj / ".metaproject/docs/TECH-DESIGN.md").unlink()
    (proj / ".metaproject/docs/STATE.md").unlink()

    import subprocess

    def _forbidden(*args, **kwargs):
        raise AssertionError("backfill_missing must never invoke a subprocess (git)")

    monkeypatch.setattr(subprocess, "run", _forbidden)

    result = backfill_missing(proj, templates_dir=templates)
    assert set(result.created) == {
        ".metaproject/docs/SPEC.md",
        ".metaproject/docs/TECH-DESIGN.md",
        ".metaproject/docs/STATE.md",
    }

    result_named = backfill_missing(
        proj, files=[".metaproject/docs/HANDOFF.md"], templates_dir=templates
    )
    assert result_named.created == [".metaproject/docs/HANDOFF.md"]


def test_backfill_resolves_variables_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One `resolve_variables` call per batch, before the first write."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / ".metaproject/docs/SPEC.md").unlink()
    (proj / ".metaproject/docs/TECH-DESIGN.md").unlink()
    (proj / ".metaproject/docs/STATE.md").unlink()

    from metaproject import review as review_module

    calls = {"count": 0}
    original = review_module.resolve_variables

    def counting_wrapper(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(review_module, "resolve_variables", counting_wrapper)

    result = backfill_missing(proj, templates_dir=templates)

    assert set(result.created) == {
        ".metaproject/docs/SPEC.md",
        ".metaproject/docs/TECH-DESIGN.md",
        ".metaproject/docs/STATE.md",
    }
    assert calls["count"] == 1


# ---------------------------------------------------------------------------------- CLI


def test_cli_backfill_ac10_all_missing_in_one_call(runner: CliRunner, tmp_path: Path) -> None:
    proj, templates = scaffolded_project(tmp_path)
    (proj / ".metaproject/docs/SPEC.md").unlink()
    (proj / ".metaproject/docs/TECH-DESIGN.md").unlink()
    (proj / ".metaproject/docs/STATE.md").unlink()

    result = runner.invoke(
        app,
        ["backfill", "--dir", str(proj), "--templates", str(templates)],
    )

    assert result.exit_code == 0, result.output
    assert ".metaproject/docs/SPEC.md" in result.output
    assert ".metaproject/docs/TECH-DESIGN.md" in result.output
    assert ".metaproject/docs/STATE.md" in result.output
    assert (proj / ".metaproject/docs/SPEC.md").exists()
    assert (proj / ".metaproject/docs/TECH-DESIGN.md").exists()
    assert (proj / ".metaproject/docs/STATE.md").exists()
    # Skipped (already-present) files are listed too.
    assert "AGENTS.md" in result.output


def test_backfill_by_name_creates_on_demand_todo(tmp_path: Path) -> None:
    """`backfill .metaproject/docs/TODO.md` creates the on-demand file `new` never scaffolds."""
    proj, templates = scaffolded_project(tmp_path)
    assert not (proj / ".metaproject/docs/TODO.md").exists()

    result = backfill_missing(proj, files=[".metaproject/docs/TODO.md"], templates_dir=templates)

    assert result.created == [".metaproject/docs/TODO.md"]
    assert (proj / ".metaproject/docs/TODO.md").exists()
    assert result.refused == []


def test_cli_backfill_by_name_creates_todo(runner: CliRunner, tmp_path: Path) -> None:
    proj, templates = scaffolded_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "backfill",
            ".metaproject/docs/TODO.md",
            "--dir",
            str(proj),
            "--templates",
            str(templates),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (proj / ".metaproject/docs/TODO.md").exists()


def test_cli_backfill_by_name_creates_handoff(runner: CliRunner, tmp_path: Path) -> None:
    proj, templates = scaffolded_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "backfill",
            ".metaproject/docs/HANDOFF.md",
            "--dir",
            str(proj),
            "--templates",
            str(templates),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (proj / ".metaproject/docs/HANDOFF.md").exists()


def test_cli_backfill_named_existing_exits_nonzero_and_writes_nothing(
    runner: CliRunner, tmp_path: Path
) -> None:
    proj, templates = scaffolded_project(tmp_path)
    before = (proj / ".metaproject/docs/SPEC.md").read_bytes()

    result = runner.invoke(
        app,
        [
            "backfill",
            ".metaproject/docs/SPEC.md",
            "--dir",
            str(proj),
            "--templates",
            str(templates),
        ],
    )

    assert result.exit_code == 1
    assert (proj / ".metaproject/docs/SPEC.md").read_bytes() == before


def test_cli_backfill_runs_in_agent_session(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`backfill` is not agent-guarded (unlike the TUI/scan guards)."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / ".metaproject/docs/SPEC.md").unlink()

    monkeypatch.setenv("METAPROJECT_AGENT", "1")
    monkeypatch.setenv("CLAUDECODE", "1")

    result = runner.invoke(
        app,
        ["backfill", "--dir", str(proj), "--templates", str(templates)],
    )

    assert result.exit_code == 0, result.output
    assert (proj / ".metaproject/docs/SPEC.md").exists()


def test_cli_backfill_dry_run_writes_nothing(runner: CliRunner, tmp_path: Path) -> None:
    proj, templates = scaffolded_project(tmp_path)
    (proj / ".metaproject/docs/SPEC.md").unlink()
    (proj / ".metaproject/docs/TECH-DESIGN.md").unlink()

    before_listing: List[Path] = sorted(p.relative_to(proj) for p in proj.rglob("*"))

    result = runner.invoke(
        app,
        ["backfill", "--dir", str(proj), "--templates", str(templates), "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    after_listing = sorted(p.relative_to(proj) for p in proj.rglob("*"))
    assert before_listing == after_listing
    assert not (proj / ".metaproject/docs/SPEC.md").exists()
    assert not (proj / ".metaproject/docs/TECH-DESIGN.md").exists()


def test_cli_backfill_no_git_ever(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj, templates = scaffolded_project(tmp_path)
    (proj / ".metaproject/docs/SPEC.md").unlink()

    import subprocess

    def _forbidden(*args, **kwargs):
        raise AssertionError("backfill CLI must never invoke a subprocess (git)")

    monkeypatch.setattr(subprocess, "run", _forbidden)

    result = runner.invoke(
        app,
        ["backfill", "--dir", str(proj), "--templates", str(templates)],
    )

    assert result.exit_code == 0, result.output
    assert (proj / ".metaproject/docs/SPEC.md").exists()


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
    templates = store_missing_a_template(
        tmp_path, ".metaproject.template/docs.template/SPEC.template.md"
    )
    proj = tmp_path / "incomplete_proj"
    proj.mkdir()
    (proj / "README.md").write_text("# incomplete_proj\n", encoding="utf-8")

    result = runner.invoke(app, ["backfill", "--dir", str(proj), "--templates", str(templates)])

    assert result.exit_code == 1
    assert ".metaproject/docs/SPEC.md" in result.output
    assert (proj / "AGENTS.md").exists()


# ----------------------------------------------------------------- relocated doc aliases


@pytest.mark.parametrize(
    "name",
    ["intent.md", "INTENT.md", "docs/INTENT.md", ".metaproject/docs/INTENT.md", "Intent.md"],
)
def test_backfill_alias_creates_docs_intent_only(tmp_path: Path, name: str) -> None:
    """AC-2 (R-LOC-4): every spelling creates `.metaproject/docs/INTENT.md`, never root/docs."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / ".metaproject" / "docs" / "INTENT.md").unlink()

    result = backfill_missing(proj, files=[name], templates_dir=templates)

    assert result.created == [".metaproject/docs/INTENT.md"]
    assert "INTENT.md" in os.listdir(proj / ".metaproject" / "docs")
    root_md = {p.name for p in proj.iterdir() if p.suffix == ".md"}
    assert root_md == {"AGENTS.md", "CLAUDE.md", "README.md"}
    assert not (proj / "docs").exists()


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("design.md", ".metaproject/docs/TECH-DESIGN.md"),
        ("docs/design.md", ".metaproject/docs/TECH-DESIGN.md"),
        ("TODO.md", ".metaproject/docs/TODO.md"),
        ("docs/TODO.md", ".metaproject/docs/TODO.md"),
        ("docs/DESIGN-INVARIANTS.md", ".metaproject/docs/DESIGN-INVARIANTS.md"),
    ],
)
def test_backfill_legacy_aliases_map_to_dot_metaproject_docs(
    tmp_path: Path, alias: str, canonical: str
) -> None:
    """AC-2: legacy v0.8 and v0.9 spellings map to `.metaproject/docs/` without writing `docs/`."""
    proj, templates = scaffolded_project(tmp_path)
    target = proj / canonical
    if target.exists():
        target.unlink()

    result = backfill_missing(proj, files=[alias], templates_dir=templates)

    assert result.created == [canonical]
    assert target.is_file()
    assert not (proj / "docs").exists()


def test_backfill_design_md_creates_tech_design(tmp_path: Path) -> None:
    """AC-7: the old `design.md` name creates `.metaproject/docs/TECH-DESIGN.md`."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / ".metaproject" / "docs" / "TECH-DESIGN.md").unlink()

    result = backfill_missing(proj, files=["design.md"], templates_dir=templates)

    assert result.created == [".metaproject/docs/TECH-DESIGN.md"]
    assert (proj / ".metaproject" / "docs" / "TECH-DESIGN.md").is_file()
    assert not (proj / "design.md").exists()


def test_backfill_alias_refuses_when_the_new_path_exists(tmp_path: Path) -> None:
    """An alias for an existing document is refused under its declared path."""
    proj, templates = scaffolded_project(tmp_path)
    result = backfill_missing(proj, files=["intent.md"], templates_dir=templates)
    assert result.refused == [".metaproject/docs/INTENT.md"]


def test_backfill_lowercase_docs_file_does_not_count_as_present(tmp_path: Path) -> None:
    """R-NFR-6: on APFS a lowercase `.metaproject/docs/intent.md` must not mask a missing
    `.metaproject/docs/INTENT.md` — and no-args backfill skips it into `legacy`."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / ".metaproject" / "docs" / "INTENT.md").unlink()
    (proj / ".metaproject" / "docs" / "intent.md").write_text("legacy\n", encoding="utf-8")

    result = backfill_missing(proj, templates_dir=templates, dry_run=True)

    assert result.legacy == {".metaproject/docs/INTENT.md": ".metaproject/docs/intent.md"}
    assert ".metaproject/docs/INTENT.md" not in result.created


def test_docs_directory_deploy_never_creates_handoff(tmp_path: Path) -> None:
    """Deploying the `.metaproject/docs` directory excludes on-demand documents (R-CLS-5)."""
    templates = get_bundled_templates_dir()
    proj = tmp_path / "bare"
    proj.mkdir()

    result = backfill_missing(proj, templates_dir=templates)

    assert not (proj / ".metaproject" / "docs" / "HANDOFF.md").exists()
    assert ".metaproject/docs/HANDOFF.md" not in result.created
    for path in (
        ".metaproject/docs/INTENT.md",
        ".metaproject/docs/SPEC.md",
        ".metaproject/docs/TECH-DESIGN.md",
        ".metaproject/docs/STATE.md",
    ):
        assert path in result.created
        assert (proj / path).is_file()


def test_backfill_no_args_skips_v09_docs_layout_into_legacy(tmp_path: Path) -> None:
    """R-LOC-5 (FC-2): no-args backfill on an unmigrated `docs/` project skips legacy items."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / ".metaproject" / "docs").rename(proj / "docs")
    (proj / ".metaproject").rmdir()

    result = backfill_missing(proj, templates_dir=templates)

    assert result.refused == []
    assert ".metaproject/docs" in result.legacy
    assert ".metaproject/docs/archive" in result.legacy
    assert ".metaproject/docs/INTENT.md" in result.legacy
    assert ".metaproject/docs/STATE.md" in result.legacy
    assert not (proj / ".metaproject").exists()
    assert not any(p.startswith(".metaproject/docs") for p in result.created)


def test_cli_backfill_no_args_on_v09_docs_exits_zero_and_points_to_doctor(tmp_path: Path) -> None:
    """R-LOC-5 CLI: prints legacy table pointing to `metaproject doctor` and exits 0."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / ".metaproject" / "docs").rename(proj / "docs")
    (proj / ".metaproject").rmdir()

    res = CliRunner().invoke(
        app,
        ["backfill", "--dir", str(proj), "--templates", str(templates)],
        env={"HOME": str(tmp_path / "home"), "COLUMNS": "140"},
    )

    assert res.exit_code == 0
    assert "metaproject doctor" in res.output
    assert "docs/INTENT.md → .metaproject/docs/INTENT.md" in res.output
    assert not (proj / ".metaproject").exists()


def test_backfill_no_args_skips_v08_root_intent_without_duplicating(tmp_path: Path) -> None:
    """R-LOC-5: v0.8 root `intent.md` goes into `legacy` without duplicating `INTENT.md`."""
    proj, templates = scaffolded_project(tmp_path)
    (proj / ".metaproject" / "docs" / "INTENT.md").rename(proj / "intent.md")
    shutil.rmtree(proj / ".metaproject")

    result = backfill_missing(proj, templates_dir=templates)

    assert result.legacy == {".metaproject/docs/INTENT.md": "intent.md"}
    assert not (proj / ".metaproject" / "docs" / "INTENT.md").exists()
    assert ".metaproject/docs/SPEC.md" in result.created
    assert (proj / ".metaproject" / "docs" / "SPEC.md").is_file()
