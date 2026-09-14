"""Tests for the single declaration of deliverable classes (spec.md R-CLS-1, R-LRN-3)."""

from metaproject.deliverables import (
    DELIVERABLES,
    Deliverable,
    DeliverableClass,
    classify,
    learn_targets,
    scaffolded,
)

GOVERNANCE_PATHS = {"AGENTS.md", "CLAUDE.md", "README.md", ".gitignore"}
WORKING_PATHS = {
    "intent.md",
    "spec.md",
    "design.md",
    "plan.md",
    "STATE.md",
    "ARCHITECTURE.md",
    "docs/DESIGN-INVARIANTS.md",
    "docs/VERIFIED-FACTS.md",
}
ON_DEMAND_PATHS = {"HANDOFF.md"}
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
    assert "HANDOFF.md" not in result
    assert result == ALL_PATHS - ON_DEMAND_PATHS


def test_learn_targets_is_governance_plus_working() -> None:
    """learn_targets() = governance + working paths, nothing else."""
    result = set(learn_targets())
    assert result == GOVERNANCE_PATHS | WORKING_PATHS
    assert "HANDOFF.md" not in result
    assert "docs" not in result
    assert "docs/archive" not in result


def test_docs_archive_is_directory() -> None:
    """docs/archive is declared as a DIRECTORY deliverable."""
    assert classify("docs/archive") is DeliverableClass.DIRECTORY
    assert classify("docs") is DeliverableClass.DIRECTORY
