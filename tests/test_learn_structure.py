"""Deterministic heading-structure proposal tests (plan.md C2, spec.md R-LRN-1a/1c).

Acceptance case AC-11a is exercised here: a heading proposal needs at least
`min_evidence` distinct contributing projects; a level change is one removal plus one
addition; an addition anchors after the heading most contributors place it under.

Every fixture in this file is local to the test (four small projects built directly
under `tmp_path`), never the shared `learn_workspace` fixture, so nothing here can
perturb the acceptance-criteria workspace other tests rely on.

**No test in this file invokes a model.** `structure.propose` never reaches the guard,
a prompt, or a subprocess — that is the property under test.
"""

from pathlib import Path
from typing import Dict, Iterable, List

from metaproject.config import Config
from metaproject.learn import structure
from metaproject.learn.collect import EvidenceRecord, collect_project

_BODY = "\n".join(f"Body line {i}." for i in range(5))

_STATE_TEMPLATE = (
    "# STATE.md\n\n"
    f"## Process\n{_BODY}\n\n"
    f"## Implementation phases\n{_BODY}\n\n"
    f"## Open items\n{_BODY}\n"
)

_INTENT_TEMPLATE = (
    f"# intent.md\n\n## Overview\n{_BODY}\n\n## Constraints\n{_BODY}\n\n## Scope\n{_BODY}\n"
)


def _templates_dir(tmp_path: Path) -> Path:
    """A shared template store carrying STATE.md and intent.md templates only."""
    templates_dir = tmp_path / "templates"
    (templates_dir / "docs.template").mkdir(parents=True, exist_ok=True)
    (templates_dir / "docs.template" / "STATE.template.md").write_text(
        _STATE_TEMPLATE, encoding="utf-8"
    )
    (templates_dir / "docs.template" / "INTENT.template.md").write_text(
        _INTENT_TEMPLATE, encoding="utf-8"
    )
    return templates_dir


def _project(tmp_path: Path, name: str, files: Dict[str, str]) -> Path:
    """A minimal project directory carrying exactly the given files."""
    project_dir = tmp_path / name
    project_dir.mkdir()
    for rel, content in files.items():
        (project_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (project_dir / rel).write_text(content, encoding="utf-8")
    return project_dir


def _collect(project_dir: Path, templates_dir: Path, target_file: str) -> List[EvidenceRecord]:
    return collect_project(
        project_dir,
        templates_dir,
        targets=[target_file],
        config=Config(),
        classification="Active",
    )


def _weights(records: Iterable[EvidenceRecord]) -> Dict[str, float]:
    """One flat weight per contributing project, so evidence count alone gates emission."""
    return {r.project_path: 1.0 for r in records}


class _StubDrift:
    """A minimal `DriftLookup`: corroborates evidence from exactly one project path."""

    def __init__(self, boosted_path: str) -> None:
        self.boosted_path = boosted_path

    def reports(self, project_path, target_file, keys) -> bool:
        return str(project_path) == self.boosted_path


# --------------------------------------------------------------------------- removal


def test_three_of_four_projects_removing_heading_yields_one_remove_proposal(
    tmp_path: Path,
) -> None:
    """3 of 4 projects removing `## Constraints` from intent.md yields exactly one
    `remove_heading` proposal with 3 contributors; the compliant 4th project contributes
    nothing (its structure matches the template, so `collect` produces no evidence)."""
    templates_dir = _templates_dir(tmp_path)
    records: List[EvidenceRecord] = []
    for name in ("proj1", "proj2", "proj3"):
        project_dir = _project(
            tmp_path,
            name,
            {"docs/INTENT.md": f"# intent.md\n\n## Overview\n{_BODY}\n\n## Scope\n{_BODY}\n"},
        )
        records += _collect(project_dir, templates_dir, "docs/INTENT.md")

    compliant = _project(tmp_path, "proj4", {"docs/INTENT.md": _INTENT_TEMPLATE})
    compliant_records = _collect(compliant, templates_dir, "docs/INTENT.md")
    assert compliant_records == []
    records += compliant_records

    proposals = structure.propose(records, _weights(records), min_evidence=2)

    remove_proposals = [p for p in proposals if p.kind == "remove_heading"]
    assert len(remove_proposals) == 1
    proposal = remove_proposals[0]
    assert proposal.target_file == "docs/INTENT.md"
    assert proposal.proposed_body == "## Constraints"
    assert proposal.target_section == "Constraints"
    assert proposal.source_lines == ("## Constraints",)
    assert len(proposal.contributing_paths) == 3
    assert len(set(proposal.contributing_paths)) == 3


# --------------------------------------------------------------------------- addition


def test_two_projects_adding_heading_anchor_after_shared_heading(tmp_path: Path) -> None:
    """2 projects adding `## Risks` to STATE.md, both directly after `## Implementation
    phases`, yields one `add_heading` proposal anchored there."""
    templates_dir = _templates_dir(tmp_path)
    records: List[EvidenceRecord] = []
    for name in ("alpha", "beta"):
        project_dir = _project(
            tmp_path,
            name,
            {
                "docs/STATE.md": (
                    f"# STATE.md\n\n## Process\n{_BODY}\n\n"
                    f"## Implementation phases\n{_BODY}\n\n"
                    f"## Risks\n{_BODY}\n\n"
                    f"## Open items\n{_BODY}\n"
                )
            },
        )
        records += _collect(project_dir, templates_dir, "docs/STATE.md")

    proposals = structure.propose(records, _weights(records), min_evidence=2)

    add_proposals = [p for p in proposals if p.kind == "add_heading"]
    assert len(add_proposals) == 1
    proposal = add_proposals[0]
    assert proposal.target_file == "docs/STATE.md"
    assert proposal.proposed_body == "## Risks"
    assert proposal.target_section == "Implementation phases"
    assert len(proposal.contributing_paths) == 2


# --------------------------------------------------------------------------- gating


def test_single_project_heading_yields_no_proposal_by_default(tmp_path: Path) -> None:
    """A heading only one project has never reaches the default (2-project) gate."""
    templates_dir = _templates_dir(tmp_path)
    project_dir = _project(
        tmp_path,
        "solo",
        {
            "docs/STATE.md": (
                f"# STATE.md\n\n## Process\n{_BODY}\n\n"
                f"## Implementation phases\n{_BODY}\n\n"
                f"## OnlyMine\n{_BODY}\n\n"
                f"## Open items\n{_BODY}\n"
            )
        },
    )
    records = _collect(project_dir, templates_dir, "docs/STATE.md")

    assert structure.propose(records, _weights(records)) == []


def test_min_evidence_one_lets_a_single_project_proposal_through(tmp_path: Path) -> None:
    """`min_evidence=1` (a pinned `learn.min_structure_evidence`) admits a lone project."""
    templates_dir = _templates_dir(tmp_path)
    project_dir = _project(
        tmp_path,
        "solo",
        {
            "docs/STATE.md": (
                f"# STATE.md\n\n## Process\n{_BODY}\n\n"
                f"## Implementation phases\n{_BODY}\n\n"
                f"## OnlyMine\n{_BODY}\n\n"
                f"## Open items\n{_BODY}\n"
            )
        },
    )
    records = _collect(project_dir, templates_dir, "docs/STATE.md")

    proposals = structure.propose(records, _weights(records), min_evidence=1)
    assert len(proposals) == 1
    assert proposals[0].kind == "add_heading"
    assert proposals[0].proposed_body == "## OnlyMine"
    assert len(proposals[0].contributing_paths) == 1


# --------------------------------------------------------------------------- level change


def test_level_change_in_two_projects_yields_one_remove_and_one_add(tmp_path: Path) -> None:
    """A heading whose level changed in 2 projects is one removal plus one addition
    (R-LRN-3), never a rename."""
    templates_dir = _templates_dir(tmp_path)
    records: List[EvidenceRecord] = []
    for name in ("gamma", "delta"):
        project_dir = _project(
            tmp_path,
            name,
            {
                "docs/STATE.md": (
                    f"# STATE.md\n\n### Process\n{_BODY}\n\n"
                    f"## Implementation phases\n{_BODY}\n\n"
                    f"## Open items\n{_BODY}\n"
                )
            },
        )
        records += _collect(project_dir, templates_dir, "docs/STATE.md")

    proposals = structure.propose(records, _weights(records), min_evidence=2)

    assert sorted(p.kind for p in proposals) == ["add_heading", "remove_heading"]
    remove_proposal = next(p for p in proposals if p.kind == "remove_heading")
    add_proposal = next(p for p in proposals if p.kind == "add_heading")
    assert remove_proposal.proposed_body == "## Process"
    assert add_proposal.proposed_body == "### Process"
    assert len(remove_proposal.contributing_paths) == 2
    assert len(add_proposal.contributing_paths) == 2


# --------------------------------------------------------------------------- drift


def test_drift_boost_raises_the_score_of_a_corroborated_removal(tmp_path: Path) -> None:
    """A `review` drift report for one contributor raises that removal's evidence_score
    over the same removal scored without drift (spec.md §5.4.9, R-LRN-4 groundwork)."""
    templates_dir = _templates_dir(tmp_path)
    records: List[EvidenceRecord] = []
    for name in ("proj1", "proj2", "proj3"):
        project_dir = _project(
            tmp_path,
            name,
            {"docs/INTENT.md": f"# intent.md\n\n## Overview\n{_BODY}\n\n## Scope\n{_BODY}\n"},
        )
        records += _collect(project_dir, templates_dir, "docs/INTENT.md")

    weights = _weights(records)
    boosted_path = records[0].project_path

    baseline = structure.propose(records, weights, min_evidence=2)[0]
    boosted = structure.propose(records, weights, drift=_StubDrift(boosted_path), min_evidence=2)[0]

    assert baseline.kind == "remove_heading"
    assert boosted.kind == "remove_heading"
    assert boosted.evidence_score > baseline.evidence_score
