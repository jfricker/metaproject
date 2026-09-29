"""Render-and-diff evidence gathering tests (plan.md Phase 1, spec.md §5.4.1).

Acceptance cases exercised here: C1, C11, C18, C19, C23, C26, C28.
No model is involved anywhere in this module.
"""

from pathlib import Path

import pytest

from metaproject.config import Config
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

_LOTS_OF_BODY_TEXT = "\n".join(
    f"Body paragraph {i} with unrelated project prose." for i in range(20)
)

_STATE_TEMPLATE = (
    "# STATE.md\n\n"
    "## Process\n"
    "{Placeholder process text.}\n\n"
    "## Open items\n"
    "{Placeholder open items text.}\n"
)


def _structure_workspace(tmp_path: Path, project_state_md: str, template: str = _STATE_TEMPLATE):
    """A minimal project + template store scoped to STATE.md, for structure-evidence tests."""
    project_dir = tmp_path / "proj"
    (project_dir / "docs").mkdir(parents=True)
    (project_dir / "docs" / "STATE.md").write_text(project_state_md, encoding="utf-8")

    templates_dir = tmp_path / "templates"
    (templates_dir / "docs.template").mkdir(parents=True)
    (templates_dir / "docs.template" / "STATE.template.md").write_text(template, encoding="utf-8")

    return project_dir, templates_dir


def _collect_state(project_dir: Path, templates_dir: Path):
    records = collect_project(
        project_dir,
        templates_dir,
        targets=["docs/STATE.md"],
        config=Config(),
        classification="Active",
    )
    return [r for r in records if r.target_file == "docs/STATE.md"]


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


# --------------------------------------------------------------------------- structural evidence


def test_working_target_extra_heading_yields_one_structure_record(tmp_path: Path) -> None:
    """AC-11: an extra heading in a body-heavy working doc is the only evidence, and no
    body text appears anywhere in the record, including the diff."""
    project_state_md = (
        "# STATE.md\n\n"
        "## Process\n"
        f"{_LOTS_OF_BODY_TEXT}\n\n"
        "## Open items\n"
        f"{_LOTS_OF_BODY_TEXT}\n\n"
        "## Risks\n"
        "Some risk text that must never leak into evidence.\n"
    )
    project_dir, templates_dir = _structure_workspace(tmp_path, project_state_md)

    records = _collect_state(project_dir, templates_dir)
    assert len(records) == 1
    record = records[0]

    assert record.kind == "structure"
    assert record.added_lines == ("## Risks",)
    assert record.removed_lines == ()
    assert "Body paragraph" not in record.diff
    assert "risk text" not in record.diff
    for line in record.added_lines + record.removed_lines:
        assert "Body paragraph" not in line


def test_working_target_removed_heading_from_nonempty_file_is_removal_evidence(
    tmp_path: Path,
) -> None:
    """R-LRN-1b: a non-empty project file lacking a template heading yields removed_lines."""
    project_state_md = f"# STATE.md\n\n## Process\n{_LOTS_OF_BODY_TEXT}\n"
    project_dir, templates_dir = _structure_workspace(tmp_path, project_state_md)

    records = _collect_state(project_dir, templates_dir)
    assert len(records) == 1
    record = records[0]

    assert record.kind == "structure"
    assert record.removed_lines == ("## Open items",)
    assert record.added_lines == ()


def test_empty_working_file_is_never_removal_evidence(tmp_path: Path) -> None:
    """R-LRN-1b: an empty STATE.md contributes no removal evidence (no record at all)."""
    project_dir, templates_dir = _structure_workspace(tmp_path, "   \n")
    assert _collect_state(project_dir, templates_dir) == []


def test_missing_working_file_is_never_removal_evidence(tmp_path: Path) -> None:
    """R-LRN-1b: a missing STATE.md contributes no removal evidence (no record at all)."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    templates_dir = tmp_path / "templates"
    (templates_dir / "docs.template").mkdir(parents=True)
    (templates_dir / "docs.template" / "STATE.template.md").write_text(
        _STATE_TEMPLATE, encoding="utf-8"
    )

    assert _collect_state(project_dir, templates_dir) == []


def test_working_target_heading_level_change_is_one_removal_and_one_addition(
    tmp_path: Path,
) -> None:
    """A level change on a heading title counts as one removal plus one addition."""
    project_state_md = (
        f"# STATE.md\n\n### Process\n{_LOTS_OF_BODY_TEXT}\n\n## Open items\n{_LOTS_OF_BODY_TEXT}\n"
    )
    project_dir, templates_dir = _structure_workspace(tmp_path, project_state_md)

    records = _collect_state(project_dir, templates_dir)
    assert len(records) == 1
    record = records[0]

    assert record.removed_lines == ("## Process",)
    assert record.added_lines == ("### Process",)


def test_working_target_with_no_template_in_store_yields_no_record(tmp_path: Path) -> None:
    """A working target the store has no template for contributes no structural record
    (and is never treated as a `new_template` candidate)."""
    project_dir = tmp_path / "proj"
    (project_dir / "docs").mkdir(parents=True)
    (project_dir / "docs" / "STATE.md").write_text(
        f"# STATE.md\n\n## Risks\n{_LOTS_OF_BODY_TEXT}\n", encoding="utf-8"
    )
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()

    assert _collect_state(project_dir, templates_dir) == []


def test_working_target_matching_headings_yield_no_record(tmp_path: Path) -> None:
    """Body text alone, with matching headings, is not structural evidence (R-LRN-1)."""
    project_state_md = (
        f"# STATE.md\n\n## Process\n{_LOTS_OF_BODY_TEXT}\n\n## Open items\n{_LOTS_OF_BODY_TEXT}\n"
    )
    project_dir, templates_dir = _structure_workspace(tmp_path, project_state_md)
    assert _collect_state(project_dir, templates_dir) == []


def test_handoff_is_never_collected_even_when_configured(tmp_path: Path) -> None:
    """R-LRN-3/design.md: HANDOFF.md (on-demand) is never collected, even if a config
    explicitly lists it as a learn target."""
    project_dir = tmp_path / "proj"
    (project_dir / "docs").mkdir(parents=True)
    (project_dir / "docs" / "HANDOFF.md").write_text(
        "# Handoff\n\n## Extra section\nSome text.\n", encoding="utf-8"
    )
    templates_dir = tmp_path / "templates"
    (templates_dir / "docs.template").mkdir(parents=True)
    (templates_dir / "docs.template" / "HANDOFF.template.md").write_text(
        "# Handoff\n", encoding="utf-8"
    )

    records = collect_project(
        project_dir,
        templates_dir,
        targets=["docs/HANDOFF.md"],
        config=Config(),
        classification="Active",
    )
    assert records == []


def test_agents_md_behavior_is_unchanged_by_structure_evidence(workspace) -> None:
    """Governance targets (AGENTS.md) still produce body `edit` evidence, not structure."""
    records = collect_project(workspace.project("lattice"), workspace.templates)
    agents = [r for r in records if r.target_file == "AGENTS.md"][0]
    assert agents.kind == "edit"
    assert agents.removed_lines == ()
    assert C2_LINE in agents.added_lines


def test_skill_directories_are_never_collected_even_when_configured(tmp_path: Path) -> None:
    """AC-12 (R-SKL-8): nothing under `.agents/` or `.claude/` is a learn target, even if
    an operator lists it or a directory target would expand into it."""
    project_dir = tmp_path / "proj"
    skill = project_dir / ".agents" / "skills" / "write-intent"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    (project_dir / ".claude").mkdir()
    (project_dir / ".claude" / "notes.md").write_text("x\n", encoding="utf-8")
    (project_dir / "AGENTS.md").write_text("# a\n", encoding="utf-8")

    found = iter_target_files(
        project_dir,
        [
            "AGENTS.md",
            ".agents/skills/write-intent/SKILL.md",
            ".agents/",
            ".claude/",
            ".claude/notes.md",
        ],
    )
    assert found == ["AGENTS.md"]
