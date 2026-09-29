"""Tests for the single declaration of deliverable classes (spec.md R-CLS-1, R-LRN-3)."""

from pathlib import Path

import pytest

from metaproject.deliverables import (
    DELIVERABLES,
    LEGACY_NAMES,
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
    "docs/INTENT.md",
    "docs/SPEC.md",
    "docs/TECH-DESIGN.md",
    "docs/PLAN.md",
    "docs/STATE.md",
    "docs/ARCHITECTURE.md",
    "docs/DESIGN-INVARIANTS.md",
    "docs/VERIFIED-FACTS.md",
}
ON_DEMAND_PATHS = {"docs/HANDOFF.md"}
DIRECTORY_PATHS = {"docs", "docs/archive"}
ALL_PATHS = GOVERNANCE_PATHS | WORKING_PATHS | ON_DEMAND_PATHS | DIRECTORY_PATHS


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
    """scaffolded() is every path except ON_DEMAND ones (HANDOFF.md excluded)."""
    result = set(scaffolded())
    assert "docs/HANDOFF.md" not in result
    assert result == ALL_PATHS - ON_DEMAND_PATHS


def test_learn_targets_is_governance_plus_working() -> None:
    """learn_targets() = governance + working paths, nothing else."""
    result = set(learn_targets())
    assert result == GOVERNANCE_PATHS | WORKING_PATHS
    assert "docs/HANDOFF.md" not in result
    assert "docs" not in result
    assert "docs/archive" not in result


def test_docs_archive_is_directory() -> None:
    """docs/archive is declared as a DIRECTORY deliverable."""
    assert classify("docs/archive") is DeliverableClass.DIRECTORY
    assert classify("docs") is DeliverableClass.DIRECTORY


def test_legacy_names_map_every_relocated_document_into_docs() -> None:
    """R-DOC-0/1: one old→new mapping; every target is a declared `docs/` path."""
    assert LEGACY_NAMES == {
        "intent.md": "docs/INTENT.md",
        "spec.md": "docs/SPEC.md",
        "design.md": "docs/TECH-DESIGN.md",
        "plan.md": "docs/PLAN.md",
        "STATE.md": "docs/STATE.md",
        "HANDOFF.md": "docs/HANDOFF.md",
        "ARCHITECTURE.md": "docs/ARCHITECTURE.md",
    }
    declared = {d.path for d in DELIVERABLES}
    assert set(LEGACY_NAMES.values()) <= declared


def test_no_cycle_document_is_declared_at_the_root() -> None:
    """R-DOC-1: only governance files stay at the root."""
    root_level = {d.path for d in DELIVERABLES if "/" not in d.path}
    assert root_level == GOVERNANCE_PATHS | {"docs"}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("docs/INTENT.md", "docs/INTENT.md"),
        ("INTENT.md", "docs/INTENT.md"),
        ("intent.md", "docs/INTENT.md"),
        ("Intent.MD", "docs/INTENT.md"),
        ("docs/intent.md", "docs/INTENT.md"),
        ("design.md", "docs/TECH-DESIGN.md"),
        ("TECH-DESIGN.md", "docs/TECH-DESIGN.md"),
        ("HANDOFF.md", "docs/HANDOFF.md"),
        ("STATE.md", "docs/STATE.md"),
        ("ARCHITECTURE.md", "docs/ARCHITECTURE.md"),
        ("DESIGN-INVARIANTS.md", "docs/DESIGN-INVARIANTS.md"),
        ("AGENTS.md", "AGENTS.md"),
        ("docs", "docs"),
        ("Makefile", "Makefile"),
        ("custom/notes.md", "custom/notes.md"),
    ],
)
def test_canonical_path_aliases(name: str, expected: str) -> None:
    """R-DOC-4: new path, bare new name and old name all resolve to the `docs/` path."""
    assert canonical_path(name) == expected


def test_exact_exists_compares_real_directory_entries(tmp_path: Path) -> None:
    """R-NFR-6: on APFS `Path.exists()` would call `docs/INTENT.md` present here."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "intent.md").write_text("x", encoding="utf-8")
    assert exact_exists(tmp_path / "docs" / "intent.md")
    assert not exact_exists(tmp_path / "docs" / "INTENT.md")
    assert not exact_exists(tmp_path / "nope" / "INTENT.md")


def test_legacy_locations_finds_root_and_lowercase_docs_documents(tmp_path: Path) -> None:
    """A relocated document is legacy at the root (old or new name) or as `docs/<old>`."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "intent.md").write_text("x", encoding="utf-8")
    (tmp_path / "STATE.md").write_text("x", encoding="utf-8")
    (tmp_path / "docs" / "design.md").write_text("x", encoding="utf-8")
    (tmp_path / "docs" / "PLAN.md").write_text("x", encoding="utf-8")
    (tmp_path / "SPEC.md").write_text("x", encoding="utf-8")

    assert legacy_locations(tmp_path) == {
        "docs/INTENT.md": "intent.md",
        "docs/SPEC.md": "SPEC.md",
        "docs/TECH-DESIGN.md": "docs/design.md",
        "docs/STATE.md": "STATE.md",
    }


def test_legacy_locations_empty_once_migrated(tmp_path: Path) -> None:
    """A document at its exact new path is never legacy, even with a stray old copy."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "INTENT.md").write_text("x", encoding="utf-8")
    (tmp_path / "intent.md").write_text("old", encoding="utf-8")
    assert legacy_locations(tmp_path) == {}
