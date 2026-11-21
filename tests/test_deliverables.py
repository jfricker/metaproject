"""Tests for the single declaration of deliverable classes (spec.md R-CLS-1, R-LRN-3)."""

from pathlib import Path

import pytest

from metaproject.deliverables import (
    DELIVERABLES,
    LEGACY_DIR_NAMES,
    LEGACY_LEARN_TARGETS,
    LEGACY_NAMES,
    LEGACY_ROOT_NAMES,
    Deliverable,
    DeliverableClass,
    canonical_path,
    classify,
    exact_exists,
    learn_targets,
    legacy_locations,
    scaffolded,
)

GOVERNANCE_PATHS = {"AGENTS.md", "CLAUDE.md", "README.md", ".gitignore"}
WORKING_PATHS = {
    ".metaproject/docs/INTENT.md",
    ".metaproject/docs/SPEC.md",
    ".metaproject/docs/TECH-DESIGN.md",
    ".metaproject/docs/PLAN.md",
    ".metaproject/docs/STATE.md",
    ".metaproject/docs/ARCHITECTURE.md",
    ".metaproject/docs/DESIGN-INVARIANTS.md",
    ".metaproject/docs/VERIFIED-FACTS.md",
}
ON_DEMAND_PATHS = {".metaproject/docs/HANDOFF.md", ".metaproject/docs/TODO.md"}
DIRECTORY_PATHS = {".metaproject/docs", ".metaproject/docs/archive"}
SETTINGS_PATHS = {".claude/settings.json"}
ALL_PATHS = GOVERNANCE_PATHS | WORKING_PATHS | ON_DEMAND_PATHS | DIRECTORY_PATHS | SETTINGS_PATHS


def test_every_declared_path_has_exactly_one_class() -> None:
    """Each path in DELIVERABLES appears exactly once and matches its expected class."""
    paths = [d.path for d in DELIVERABLES]
    assert len(paths) == len(set(paths)), "duplicate path in DELIVERABLES"
    assert set(paths) == ALL_PATHS

    by_path = {d.path: d.cls for d in DELIVERABLES}
    for path in GOVERNANCE_PATHS:
        assert by_path[path] is DeliverableClass.GOVERNANCE
    for path in WORKING_PATHS:
        assert by_path[path] is DeliverableClass.WORKING
    for path in ON_DEMAND_PATHS:
        assert by_path[path] is DeliverableClass.ON_DEMAND
    for path in DIRECTORY_PATHS:
        assert by_path[path] is DeliverableClass.DIRECTORY
    for path in SETTINGS_PATHS:
        assert by_path[path] is DeliverableClass.SETTINGS


def test_deliverable_is_frozen() -> None:
    """Deliverable is an immutable dataclass."""
    d = Deliverable(path="README.md", cls=DeliverableClass.GOVERNANCE)
    try:
        d.path = "other.md"  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("Deliverable should be frozen")


def test_classify_known_paths() -> None:
    """classify() returns the declared class for every known path."""
    for d in DELIVERABLES:
        assert classify(d.path) is d.cls


def test_classify_unknown_path_is_none() -> None:
    """classify() of a path never declared returns None."""
    assert classify("does-not-exist.md") is None
    assert classify("Makefile") is None
    assert classify("pyproject.toml") is None


def test_scaffolded_excludes_only_on_demand() -> None:
    """scaffolded() is every path except ON_DEMAND ones (HANDOFF.md, TODO.md excluded)."""
    result = set(scaffolded())
    assert ".metaproject/docs/HANDOFF.md" not in result
    assert ".metaproject/docs/TODO.md" not in result
    assert result == ALL_PATHS - ON_DEMAND_PATHS


def test_learn_targets_is_governance_plus_working() -> None:
    """learn_targets() = governance + working paths, nothing else."""
    result = set(learn_targets())
    assert result == GOVERNANCE_PATHS | WORKING_PATHS
    assert ".metaproject/docs/HANDOFF.md" not in result
    assert ".metaproject/docs" not in result
    assert ".metaproject/docs/archive" not in result
    assert ".claude/settings.json" not in result


def test_docs_archive_is_directory() -> None:
    """`.metaproject/docs` and `.metaproject/docs/archive` are declared DIRECTORY deliverables."""
    assert classify(".metaproject/docs/archive") is DeliverableClass.DIRECTORY
    assert classify(".metaproject/docs") is DeliverableClass.DIRECTORY


def test_legacy_names_map_every_relocated_document_into_metaproject_docs() -> None:
    """R-LEG-1: root and `docs/` legacy mappings point to declared `.metaproject/docs/` paths."""
    assert LEGACY_ROOT_NAMES == {
        "intent.md": ".metaproject/docs/INTENT.md",
        "spec.md": ".metaproject/docs/SPEC.md",
        "design.md": ".metaproject/docs/TECH-DESIGN.md",
        "plan.md": ".metaproject/docs/PLAN.md",
        "STATE.md": ".metaproject/docs/STATE.md",
        "HANDOFF.md": ".metaproject/docs/HANDOFF.md",
        "ARCHITECTURE.md": ".metaproject/docs/ARCHITECTURE.md",
    }
    # Files born in `docs/` must never claim root-level files (e.g. a project's own TODO.md).
    for born_in_docs in ("TODO.md", "DESIGN-INVARIANTS.md", "VERIFIED-FACTS.md"):
        assert born_in_docs not in LEGACY_ROOT_NAMES
        assert f"docs/{born_in_docs}" in LEGACY_NAMES

    declared = {d.path for d in DELIVERABLES}
    assert set(LEGACY_NAMES.values()) <= declared
    assert set(LEGACY_DIR_NAMES.values()) <= declared
    assert LEGACY_LEARN_TARGETS["docs/"] == ".metaproject/docs/"


def test_no_cycle_document_is_declared_at_the_root() -> None:
    """R-LOC-1: only governance files stay at the project root."""
    root_level = {d.path for d in DELIVERABLES if "/" not in d.path}
    assert root_level == GOVERNANCE_PATHS


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (".metaproject/docs/INTENT.md", ".metaproject/docs/INTENT.md"),
        ("docs/INTENT.md", ".metaproject/docs/INTENT.md"),
        ("INTENT.md", ".metaproject/docs/INTENT.md"),
        ("intent.md", ".metaproject/docs/INTENT.md"),
        ("Intent.MD", ".metaproject/docs/INTENT.md"),
        ("docs/intent.md", ".metaproject/docs/INTENT.md"),
        ("design.md", ".metaproject/docs/TECH-DESIGN.md"),
        ("docs/design.md", ".metaproject/docs/TECH-DESIGN.md"),
        ("TECH-DESIGN.md", ".metaproject/docs/TECH-DESIGN.md"),
        ("HANDOFF.md", ".metaproject/docs/HANDOFF.md"),
        ("docs/HANDOFF.md", ".metaproject/docs/HANDOFF.md"),
        ("TODO.md", ".metaproject/docs/TODO.md"),
        ("docs/TODO.md", ".metaproject/docs/TODO.md"),
        ("STATE.md", ".metaproject/docs/STATE.md"),
        ("ARCHITECTURE.md", ".metaproject/docs/ARCHITECTURE.md"),
        ("DESIGN-INVARIANTS.md", ".metaproject/docs/DESIGN-INVARIANTS.md"),
        ("docs/DESIGN-INVARIANTS.md", ".metaproject/docs/DESIGN-INVARIANTS.md"),
        ("AGENTS.md", "AGENTS.md"),
        ("docs", ".metaproject/docs"),
        ("docs/", ".metaproject/docs"),
        ("docs/archive", ".metaproject/docs/archive"),
        (".metaproject/docs", ".metaproject/docs"),
        ("Makefile", "Makefile"),
        ("custom/notes.md", "custom/notes.md"),
    ],
)
def test_canonical_path_aliases(name: str, expected: str) -> None:
    """R-LOC-4: new path, prior `docs/` path, bare new name, and root old name resolve."""
    assert canonical_path(name) == expected


def test_exact_exists_compares_real_directory_entries(tmp_path: Path) -> None:
    """R-NFR-1: on APFS `Path.exists()` would call `.metaproject/docs/INTENT.md` present."""
    (tmp_path / ".metaproject" / "docs").mkdir(parents=True)
    (tmp_path / ".metaproject" / "docs" / "intent.md").write_text("x", encoding="utf-8")
    assert exact_exists(tmp_path / ".metaproject" / "docs" / "intent.md")
    assert not exact_exists(tmp_path / ".metaproject" / "docs" / "INTENT.md")
    assert not exact_exists(tmp_path / "nope" / "INTENT.md")


def test_legacy_locations_finds_root_docs_and_wrong_case_documents(tmp_path: Path) -> None:
    """A relocated doc is legacy in `docs/`, at root, or wrong-case in `.metaproject/docs/`."""
    (tmp_path / ".metaproject" / "docs").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "intent.md").write_text("x", encoding="utf-8")
    (tmp_path / "STATE.md").write_text("x", encoding="utf-8")
    (tmp_path / "docs" / "design.md").write_text("x", encoding="utf-8")
    (tmp_path / "docs" / "PLAN.md").write_text("x", encoding="utf-8")
    (tmp_path / "SPEC.md").write_text("x", encoding="utf-8")
    (tmp_path / "docs" / "DESIGN-INVARIANTS.md").write_text("x", encoding="utf-8")
    (tmp_path / "TODO.md").write_text("project todo\n", encoding="utf-8")
    (tmp_path / ".metaproject" / "docs" / "verified-facts.md").write_text("x", encoding="utf-8")

    assert legacy_locations(tmp_path) == {
        ".metaproject/docs/INTENT.md": "intent.md",
        ".metaproject/docs/SPEC.md": "SPEC.md",
        ".metaproject/docs/TECH-DESIGN.md": "docs/design.md",
        ".metaproject/docs/PLAN.md": "docs/PLAN.md",
        ".metaproject/docs/STATE.md": "STATE.md",
        ".metaproject/docs/DESIGN-INVARIANTS.md": "docs/DESIGN-INVARIANTS.md",
        ".metaproject/docs/VERIFIED-FACTS.md": ".metaproject/docs/verified-facts.md",
    }


def test_legacy_locations_detects_v09_docs_directory_and_ignores_project_docs(
    tmp_path: Path,
) -> None:
    """A `docs/` layout flags `.metaproject/docs` + `archive`; project-owned `docs/` does not."""
    project_only = tmp_path / "project_only"
    (project_only / "docs").mkdir(parents=True)
    (project_only / "docs" / "index.md").write_text("# Docs site\n", encoding="utf-8")
    assert legacy_locations(project_only) == {}

    v09 = tmp_path / "v09"
    (v09 / "docs" / "archive").mkdir(parents=True)
    (v09 / "docs" / "INTENT.md").write_text("# Intent\n", encoding="utf-8")
    assert legacy_locations(v09) == {
        ".metaproject/docs/INTENT.md": "docs/INTENT.md",
        ".metaproject/docs/archive": "docs/archive",
        ".metaproject/docs": "docs",
    }


def test_legacy_locations_empty_once_migrated(tmp_path: Path) -> None:
    """A document at its exact new path is never legacy, even with a stray old copy."""
    (tmp_path / ".metaproject" / "docs").mkdir(parents=True)
    (tmp_path / ".metaproject" / "docs" / "INTENT.md").write_text("x", encoding="utf-8")
    (tmp_path / "intent.md").write_text("old", encoding="utf-8")
    assert legacy_locations(tmp_path) == {}
