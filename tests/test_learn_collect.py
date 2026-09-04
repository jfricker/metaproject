"""Render-and-diff evidence gathering tests (plan.md Phase 1, spec.md §5.4.1).

Acceptance cases exercised here: C1, C11, C18, C19, C23, C26, C28.
No model is involved anywhere in this module.
"""

from pathlib import Path

import pytest

from metaproject.learn.collect import (
    EvidenceRecord,
    collect_project,
    collect_workspace,
    iter_project_dirs,
    iter_target_files,
    normalize_text,
    project_variables,
    resolve_template,
)
from tests.fixtures.learn_workspace.build import build_workspace

C2_LINE = "- Run `make check` before every commit."


@pytest.fixture
def workspace(tmp_path: Path):
    """Materialize the learn acceptance workspace."""
    return build_workspace(tmp_path)


# --------------------------------------------------------------------------- normalization


def test_normalize_text_folds_crlf_and_trailing_whitespace() -> None:
    """CRLF, trailing whitespace, and a missing final newline all normalize away."""
    assert normalize_text("a  \r\nb\t\r\n") == "a\nb\n"
    assert normalize_text("a\nb") == "a\nb\n"
    assert normalize_text("") == ""


def test_normalize_text_preserves_non_ascii() -> None:
    """Normalization must not mangle legitimate non-ASCII content (C23)."""
    assert normalize_text("- Diagrams use → and ✓ glyphs\r\n") == (
        "- Diagrams use → and ✓ glyphs\n"
    )


# --------------------------------------------------------------------------- C1


def test_pristine_project_yields_zero_evidence(workspace) -> None:
    """C1: a project whose files match the rendered template produces no evidence at all."""
    records = collect_project(workspace.project("orbit"), workspace.templates)
    assert records == []


def test_rendered_placeholders_are_not_reported_as_additions(workspace) -> None:
    """C1 regression: substituted {ProjectTitle}/{ProjectDescription} are not novel lines."""
    variables = project_variables(workspace.project("orbit"))
    assert variables["ProjectTitle"] == "Orbit"
    assert variables["ProjectDescription"] == "Satellite telemetry ingest."

    records = collect_project(workspace.project("orbit"), workspace.templates)
    added = [line for rec in records for line in rec.added_lines]
    assert not any("Orbit" in line for line in added)


def test_unrendered_comparison_would_have_produced_evidence(workspace) -> None:
    """The control for C1: diffing against the raw template does flag the placeholder line.

    This asserts the fixture actually exercises the false-positive class, so C1 passing
    means rendering suppressed it rather than the file being trivially identical.
    """
    raw = (workspace.templates / "README.template.md").read_text(encoding="utf-8")
    project = (workspace.project("orbit") / "README.md").read_text(encoding="utf-8")
    assert "{ProjectTitle}" in raw
    assert "{ProjectTitle}" not in project


# --------------------------------------------------------------------------- C18, C19


def test_degenerate_project_produces_no_evidence(workspace) -> None:
    """C18: a zero-byte AGENTS.md yields no evidence and no deletion proposal."""
    records = collect_project(workspace.project("husk"), workspace.templates)
    assert records == []


def test_empty_file_is_never_a_removal(workspace) -> None:
    """C18: nothing collected is a removal; every record carries added lines."""
    records = collect_workspace(workspace.projects, workspace.templates)
    assert records
    assert all(rec.added_lines for rec in records)


def test_non_project_directories_are_skipped(workspace) -> None:
    """C19: `notes` carries C2's line but is not a project root, so it contributes nothing."""
    discovered = {p.name for p in iter_project_dirs(workspace.projects)}
    assert "notes" not in discovered

    records = collect_workspace(workspace.projects, workspace.templates)
    assert not any("notes" in rec.project_path.split("/") for rec in records)


def test_project_discovery_finds_every_fixture_project(workspace) -> None:
    """Discovery matches expectations.json: fifteen project roots, `notes` excluded."""
    expected = {
        name.split("/")[-1]
        for name, meta in workspace.expectations["projects"].items()
        if meta["classification"] is not None
    }
    discovered = {p.name for p in iter_project_dirs(workspace.projects)}
    assert discovered == expected


# --------------------------------------------------------------------------- C23


def test_crlf_project_contributes_the_normalized_line(workspace) -> None:
    """C23: lattice is CRLF with trailing whitespace; it must contribute the C2 line."""
    records = collect_project(workspace.project("lattice"), workspace.templates)
    agents = [r for r in records if r.target_file == "AGENTS.md"]
    assert len(agents) == 1
    assert C2_LINE in agents[0].added_lines


def test_crlf_project_does_not_make_every_line_novel(workspace) -> None:
    """C23: an unnormalized CRLF file would report the whole document as new."""
    records = collect_project(workspace.project("lattice"), workspace.templates)
    agents = [r for r in records if r.target_file == "AGENTS.md"][0]
    assert len(agents.added_lines) == 2
    assert any("glyphs" in line for line in agents.added_lines)


# --------------------------------------------------------------------------- C11, C26


def test_binary_files_are_skipped_not_decoded(workspace) -> None:
    """C11: vault/logo.png never appears in evidence and raises no UnicodeDecodeError."""
    records = collect_project(workspace.project("vault"), workspace.templates)
    assert not any(rec.target_file.endswith(".png") for rec in records)


def test_symlinks_are_not_followed(workspace) -> None:
    """C26: beacon's self-referential and escaping symlinks never become evidence."""
    records = collect_project(workspace.project("beacon"), workspace.templates)
    targets = {rec.target_file for rec in records}
    assert "AGENTS.link.md" not in targets
    assert "outside.link" not in targets


def test_directory_target_expansion_skips_symlinks(tmp_path: Path) -> None:
    """C26: a directory target enumerates real files only, never symlinks."""
    project = tmp_path / "proj"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "real.md").write_text("# Real\n", encoding="utf-8")
    (project / "docs" / "loop.md").symlink_to("real.md")

    found = iter_target_files(project, ["docs/"])
    assert found == ["docs/real.md"]


def test_symlinked_directory_is_not_traversed(tmp_path: Path) -> None:
    """C26: a symlinked directory inside a target directory does not escape the project."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leaked.md").write_text("secret-ish\n", encoding="utf-8")

    project = tmp_path / "proj"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "escape").symlink_to(outside, target_is_directory=True)

    assert iter_target_files(project, ["docs/"]) == []


# --------------------------------------------------------------------------- C28


def test_directory_target_is_not_read_as_a_file(workspace) -> None:
    """C28: `docs/` is a directory target; it expands rather than being opened."""
    records = collect_project(workspace.project("spire"), workspace.templates)
    targets = {rec.target_file for rec in records}
    assert "docs/" not in targets
    assert "docs/architecture.md" in targets


def test_config_shaped_target_collected(workspace) -> None:
    """C28: pyproject.toml is a default target and collects without a template."""
    records = collect_project(workspace.project("spire"), workspace.templates)
    pyproject = [r for r in records if r.target_file == "pyproject.toml"]
    assert len(pyproject) == 1
    assert pyproject[0].kind == "new_template"
    assert pyproject[0].template_path is None


def test_full_workspace_collect_completes(workspace) -> None:
    """Every fixture project scans without raising, including the degenerate ones."""
    records = collect_workspace(workspace.projects, workspace.templates)
    assert isinstance(records[0], EvidenceRecord)
    contributors = {
        Path(rec.project_path).name
        for rec in records
        if rec.target_file == "AGENTS.md" and C2_LINE in rec.added_lines
    }
    assert "husk" not in contributors
    assert "orbit" not in contributors
    assert {"atlas", "kiln", "beacon", "relic", "vault", "lattice"} <= contributors


# --------------------------------------------------------------------------- template resolution


def test_resolve_template_matches_transformed_names(workspace) -> None:
    """Targets resolve to their `.template`-suffixed source files."""
    assert resolve_template("AGENTS.md", workspace.templates).name == "AGENTS.template.md"
    assert resolve_template(".gitignore", workspace.templates).name == ".gitignore.template"
    assert resolve_template("Makefile", workspace.templates) is None


def test_untemplated_target_is_a_new_template_candidate(workspace) -> None:
    """A recurring file with no template yields kind == 'new_template' (C9 groundwork)."""
    records = collect_project(workspace.project("kiln"), workspace.templates)
    makefile = [r for r in records if r.target_file == "Makefile"]
    assert len(makefile) == 1
    assert makefile[0].kind == "new_template"


def test_edit_candidates_carry_their_template_path(workspace) -> None:
    """A templated target yields kind == 'edit' with the resolved template path."""
    records = collect_project(workspace.project("kiln"), workspace.templates)
    agents = [r for r in records if r.target_file == "AGENTS.md"][0]
    assert agents.kind == "edit"
    assert agents.template_path is not None
    assert agents.template_path.endswith("AGENTS.template.md")


def test_records_carry_activity_classification(workspace) -> None:
    """Evidence carries the project's universe classification for Phase 2 weighting."""
    records = collect_project(workspace.project("relic"), workspace.templates)
    assert records
    assert records[0].classification == "Ancient"


def test_collect_never_writes_to_the_template_store(workspace) -> None:
    """Scan-never-writes: collecting leaves every template byte-identical (C14 groundwork)."""
    before = {
        p.relative_to(workspace.templates): p.read_bytes()
        for p in sorted(workspace.templates.rglob("*"))
        if p.is_file()
    }
    collect_workspace(workspace.projects, workspace.templates)
    after = {
        p.relative_to(workspace.templates): p.read_bytes()
        for p in sorted(workspace.templates.rglob("*"))
        if p.is_file()
    }
    assert before == after


def test_diff_is_unified_and_not_the_whole_file(workspace) -> None:
    """The evidence unit is a diff, not a whole project file (spec.md §7.4)."""
    records = collect_project(workspace.project("lattice"), workspace.templates)
    agents = [r for r in records if r.target_file == "AGENTS.md"][0]
    assert agents.diff.startswith("---")
    assert "+++" in agents.diff
    assert "@@" in agents.diff
    assert "### STATE.md" not in agents.diff
