"""`review` drift as a `learn` evidence signal (spec.md §5.4.9, plan.md Phase 6).

The gate is one sentence with two halves, and both are asserted here: drift that
`review` already reports **raises the corresponding pattern's score**, and does so
**rather than creating a parallel finding**. The second half is the load-bearing one —
a drift signal that minted its own candidates would double-count the same divergence
`collect` already saw, and would put rows in the queue nobody can accept.

No model is involved in this file: `collect_drift` is deterministic, and the one
end-to-end scan mocks the runner.
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from metaproject.config import Config
from metaproject.db import get_db
from metaproject.learn import scan, structure
from metaproject.learn.collect import EvidenceRecord, collect_project
from metaproject.learn.drift import (
    EMPTY_DRIFT,
    DriftSignal,
    added_lines,
    collect_drift,
    structure_keys,
)
from metaproject.learn.score import DRIFT_BOOST, drift_factor, group_candidates, weigh_project
from metaproject.learn.store import get_evidence, list_proposals
from tests.fixtures.learn_workspace.build import build_workspace


@pytest.fixture(autouse=True)
def no_model_ever(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make it impossible for a test in this file to reach the real `claude`."""
    real_run = subprocess.run

    def guarded_run(argv, *args, **kwargs):
        parts = argv if isinstance(argv, (list, tuple)) else [argv]
        if any("claude" in str(part) for part in parts):  # pragma: no cover
            raise AssertionError("a test tried to invoke `claude`; the model must be mocked")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded_run)


@pytest.fixture
def workspace(tmp_path: Path):
    """The acceptance workspace, narrowed to projects `review` reports drift for."""
    return build_workspace(tmp_path, only=["atlas", "kiln", "beacon"])


def record(
    project: str,
    target_file: str = "AGENTS.md",
    lines: Optional[List[str]] = None,
    classification: str = "Active Now",
) -> EvidenceRecord:
    """One evidence record, with only the fields scoring reads."""
    return EvidenceRecord(
        project_name=project,
        project_path=f"/w/{project}",
        classification=classification,
        target_file=target_file,
        template_path="/t/AGENTS.template.md",
        kind="edit",
        diff="",
        added_lines=tuple(lines or ["- Run `make check` before every commit."]),
    )


# ------------------------------------------------------------------ reading `review`


def test_added_lines_reads_only_insertions_from_a_unified_diff() -> None:
    """Removals are never evidence, and the `+++` header is not a line of content."""
    diff = (
        "--- templates/AGENTS.md\n"
        "+++ project/AGENTS.md\n"
        "@@ -1,2 +1,3 @@\n"
        " # AGENTS\n"
        "-- an old rule\n"
        "+- Run `make check` before every commit.\n"
        "+\n"
    )
    assert added_lines(diff) == ("- Run `make check` before every commit.",)


def test_collect_drift_records_what_review_reports(workspace) -> None:
    """The signal is keyed by (project path, target file) and carries review's lines."""
    projects = sorted(p for p in workspace.projects.iterdir() if p.is_dir())
    signal = collect_drift(projects, workspace.templates)

    assert signal.pairs, "review reports AGENTS.md drift for every fixture project"
    for project_path, target_file in signal.pairs:
        assert target_file == "AGENTS.md"
        assert Path(project_path).is_dir()

    atlas = workspace.projects / "atlas"
    assert signal.reports(str(atlas), "AGENTS.md", ["- Run `make check` before every commit."])


def test_collect_drift_records_missing_files_without_scoring_them(workspace) -> None:
    """A file a project *lacks* is review's finding, not a learn pattern to boost."""
    projects = sorted(p for p in workspace.projects.iterdir() if p.is_dir())
    signal = collect_drift(projects, workspace.templates)

    kiln = str(workspace.projects / "kiln")
    assert "CLAUDE.md" in signal.missing[kiln]
    # Missing files never become a scoreable pair: there is no evidence to attach to.
    assert (kiln, "CLAUDE.md") not in signal.pairs
    assert not signal.reports(kiln, "CLAUDE.md", ["anything at all"])


def test_an_injected_reviewer_may_answer_with_a_plain_mapping(workspace) -> None:
    """The boundary `ReviewResult.from_mapping` exists for: a stand-in returning a dict.

    `review` returns a `ReviewResult`, but `reviewer` is injectable precisely so a caller
    can substitute something cheaper, and a dict of the same shape must not be silently
    read as no findings at all.
    """
    atlas = workspace.projects / "atlas"

    def dict_reviewer(project_dir, templates_dir=None):
        return {
            "project_path": str(project_dir),
            "missing_files": ["CLAUDE.md"],
            "diffs": {"AGENTS.md": "+++ a/AGENTS.md\n+- Run `make check` before every commit.\n"},
        }

    signal = collect_drift([atlas], workspace.templates, reviewer=dict_reviewer)

    assert signal.missing[str(atlas)] == frozenset({"CLAUDE.md"})
    assert signal.reports(str(atlas), "AGENTS.md", ["- Run `make check` before every commit."])


def test_a_reviewer_answering_with_neither_shape_is_skipped(workspace) -> None:
    """Anything that is not a result is dropped, on the same terms an exception is."""
    projects = sorted(p for p in workspace.projects.iterdir() if p.is_dir())
    signal = collect_drift(projects, workspace.templates, reviewer=lambda *_: "not a result")
    assert signal.pairs == frozenset()
    assert not signal.missing


def test_a_failing_review_is_not_fatal_to_a_scan(workspace) -> None:
    """`learn` must not lose a whole scan because one project could not be reviewed."""

    def exploding_reviewer(project_dir, templates_dir=None):
        raise OSError("unreadable project")

    projects = sorted(p for p in workspace.projects.iterdir() if p.is_dir())
    signal = collect_drift(projects, workspace.templates, reviewer=exploding_reviewer)
    assert signal.pairs == frozenset()


# ------------------------------------------------------- structural (working document) drift

_BODY = "\n".join(f"Body line {i}." for i in range(5))

_INTENT_TEMPLATE = (
    f"# intent.md\n\n## Overview\n{_BODY}\n\n## Constraints\n{_BODY}\n\n## Scope\n{_BODY}\n"
)

_STATE_TEMPLATE = (
    "# STATE.md\n\n"
    f"## Process\n{_BODY}\n\n"
    f"## Implementation phases\n{_BODY}\n\n"
    f"## Open items\n{_BODY}\n"
)


def _structure_templates_dir(tmp_path: Path) -> Path:
    """A shared template store carrying intent.md and STATE.md templates only."""
    templates_dir = tmp_path / "structure_templates"
    templates_dir.mkdir(exist_ok=True)
    (templates_dir / "intent.template.md").write_text(_INTENT_TEMPLATE, encoding="utf-8")
    (templates_dir / "STATE.template.md").write_text(_STATE_TEMPLATE, encoding="utf-8")
    return templates_dir


def _structure_project(tmp_path: Path, name: str, files: Dict[str, str]) -> Path:
    project_dir = tmp_path / name
    project_dir.mkdir()
    for rel, content in files.items():
        (project_dir / rel).write_text(content, encoding="utf-8")
    return project_dir


def _structure_collect(
    project_dir: Path, templates_dir: Path, target_file: str
) -> List[EvidenceRecord]:
    return collect_project(
        project_dir,
        templates_dir,
        targets=[target_file],
        config=Config(),
        classification="Active",
    )


def test_structure_keys_normalizes_headings_like_added_lines_normalizes_diff_content() -> None:
    """Indentation/spacing quirks in a heading line still key the same (score.candidate_key)."""
    assert structure_keys(["##  Constraints  "]) == ("## Constraints",)
    assert structure_keys([]) == ()
    assert structure_keys(["   "]) == ()


def test_collect_drift_records_a_missing_heading_as_a_removal_key(tmp_path: Path) -> None:
    """A working deliverable's missing heading (`result.structure`) becomes a drift key
    for the matching `remove_heading` evidence, using the same normalization as a
    template heading line (R-LRN-4)."""
    templates_dir = _structure_templates_dir(tmp_path)
    project_dir = _structure_project(
        tmp_path,
        "proj1",
        {"intent.md": f"# intent.md\n\n## Overview\n{_BODY}\n\n## Scope\n{_BODY}\n"},
    )

    signal = collect_drift([project_dir], templates_dir)

    assert signal.reports(project_dir, "intent.md", ["## Constraints"])


def test_collect_drift_records_no_key_for_an_extra_heading(tmp_path: Path) -> None:
    """Additions get no drift boost: `review` never reports an extra heading as
    missing, so there is nothing for `collect_drift` to record for it (R-LRN-4)."""
    templates_dir = _structure_templates_dir(tmp_path)
    project_dir = _structure_project(
        tmp_path,
        "alpha",
        {
            "STATE.md": (
                f"# STATE.md\n\n## Process\n{_BODY}\n\n"
                f"## Implementation phases\n{_BODY}\n\n"
                f"## Risks\n{_BODY}\n\n"
                f"## Open items\n{_BODY}\n"
            )
        },
    )

    signal = collect_drift([project_dir], templates_dir)

    assert (str(project_dir), "STATE.md") not in signal.lines
    assert not signal.reports(project_dir, "STATE.md", ["## Risks"])


def test_drift_for_a_file_review_saw_but_collect_gathered_no_evidence_for_is_inert(
    tmp_path: Path,
) -> None:
    """The same invariant `added_lines`-based drift has: a signal entry for a
    (project, file) pair `collect` never produced evidence for contributes nothing to
    `structure.propose` — a drift report never creates a candidate."""
    templates_dir = _structure_templates_dir(tmp_path)
    records: List[EvidenceRecord] = []
    project_dirs: List[Path] = []
    for name in ("proj1", "proj2", "proj3"):
        project_dir = _structure_project(
            tmp_path,
            name,
            {"intent.md": f"# intent.md\n\n## Overview\n{_BODY}\n\n## Scope\n{_BODY}\n"},
        )
        project_dirs.append(project_dir)
        records += _structure_collect(project_dir, templates_dir, "intent.md")

    weights = {r.project_path: 1.0 for r in records}
    # A phantom structural finding for a file none of the `intent.md`-only records
    # carry evidence for. `review` really could report this (a compliant STATE.md
    # contributes nothing, but an out-of-band STATE.md finding is simulated here to
    # isolate the invariant without depending on a second real project).
    phantom = DriftSignal(
        lines={(str(project_dirs[0]), "STATE.md"): frozenset({"## Risks"})},
        missing={},
    )

    proposals = structure.propose(records, weights, drift=phantom, min_evidence=2)

    assert proposals, "the intent.md removal must still be proposed"
    assert {p.target_file for p in proposals} == {"intent.md"}


def test_review_structure_drift_raises_a_removal_score_over_the_same_removal_unboosted(
    tmp_path: Path,
) -> None:
    """End to end with the real `review_project` reviewer: 3 projects removing
    `## Constraints` from intent.md, corroborated by `review`'s structural result,
    score higher than the identical, otherwise-unboosted removal — and an addition
    proposal (`review` never reports extra headings) is unaffected. `evidence_count`
    (contributing_paths) is unchanged either way — a drift report never creates a
    candidate or adds a contributor (module docstring)."""
    templates_dir = _structure_templates_dir(tmp_path)

    removal_records: List[EvidenceRecord] = []
    addition_records: List[EvidenceRecord] = []
    project_dirs: List[Path] = []

    for name in ("proj1", "proj2", "proj3"):
        project_dir = _structure_project(
            tmp_path,
            name,
            {"intent.md": f"# intent.md\n\n## Overview\n{_BODY}\n\n## Scope\n{_BODY}\n"},
        )
        project_dirs.append(project_dir)
        removal_records += _structure_collect(project_dir, templates_dir, "intent.md")

    for name in ("alpha", "beta"):
        project_dir = _structure_project(
            tmp_path,
            name,
            {
                "STATE.md": (
                    f"# STATE.md\n\n## Process\n{_BODY}\n\n"
                    f"## Implementation phases\n{_BODY}\n\n"
                    f"## Risks\n{_BODY}\n\n"
                    f"## Open items\n{_BODY}\n"
                )
            },
        )
        project_dirs.append(project_dir)
        addition_records += _structure_collect(project_dir, templates_dir, "STATE.md")

    records = removal_records + addition_records
    weights = {r.project_path: 1.0 for r in records}

    # The real reviewer: every removal contributor's own intent.md really is missing
    # `## Constraints`, so `review` really does corroborate all three.
    signal = collect_drift(project_dirs, templates_dir)

    baseline = structure.propose(records, weights, min_evidence=2)
    boosted = structure.propose(records, weights, drift=signal, min_evidence=2)

    baseline_removal = next(p for p in baseline if p.kind == "remove_heading")
    boosted_removal = next(p for p in boosted if p.kind == "remove_heading")
    baseline_addition = next(p for p in baseline if p.kind == "add_heading")
    boosted_addition = next(p for p in boosted if p.kind == "add_heading")

    assert boosted_removal.evidence_score > baseline_removal.evidence_score
    assert boosted_removal.evidence_score == pytest.approx(
        baseline_removal.evidence_score * (1.0 + DRIFT_BOOST)
    )
    assert boosted_addition.evidence_score == pytest.approx(baseline_addition.evidence_score)

    assert len(boosted_removal.contributing_paths) == len(baseline_removal.contributing_paths)
    assert len(boosted_addition.contributing_paths) == len(baseline_addition.contributing_paths)


# ------------------------------------------------------------------- the boost itself


def test_drift_factor_is_a_bounded_multiplier() -> None:
    """Corroboration by `review` nudges; it never replaces frequency."""
    assert drift_factor(False) == 1.0
    assert drift_factor(True) == pytest.approx(1.0 + DRIFT_BOOST)
    assert 0.0 < DRIFT_BOOST < 1.0


def test_weigh_project_multiplies_rather_than_adds_a_second_contribution() -> None:
    """The same project's weight goes up; it does not become two contributions."""
    base = weigh_project("Active Now", age_days=0.0)
    boosted = weigh_project("Active Now", age_days=0.0, drift=True)
    assert boosted == pytest.approx(base * (1.0 + DRIFT_BOOST))


def test_review_drift_raises_the_matching_candidates_score_only() -> None:
    """The boost lands on the pattern review reports, and on no other."""
    line = "- Run `make check` before every commit."
    other = "- Ship on Fridays."
    records = [
        record("atlas", lines=[line, other]),
        record("kiln", lines=[line, other]),
    ]
    ages = {"/w/atlas": 0.0, "/w/kiln": 0.0}

    plain = {c.key: c.evidence_score for c in group_candidates(records, ages=ages)}
    signal = DriftSignal(lines={("/w/atlas", "AGENTS.md"): frozenset({line})}, missing={})
    boosted = {c.key: c.evidence_score for c in group_candidates(records, ages=ages, drift=signal)}

    assert boosted[line] > plain[line]
    assert boosted[other] == pytest.approx(plain[other])


def test_review_drift_creates_no_candidate_of_its_own() -> None:
    """A drift report for a project with no collected evidence contributes nothing."""
    records = [record("atlas")]
    ages = {"/w/atlas": 0.0}
    signal = DriftSignal(
        lines={
            ("/w/atlas", "AGENTS.md"): frozenset({"- Run `make check` before every commit."}),
            ("/w/ghost", "AGENTS.md"): frozenset({"- A rule only review ever saw."}),
            ("/w/atlas", "CLAUDE.md"): frozenset({"- Another rule entirely."}),
        },
        missing={"/w/atlas": frozenset({"CLAUDE.md"})},
    )

    plain = group_candidates(records, ages=ages)
    boosted = group_candidates(records, ages=ages, drift=signal)

    assert {c.key for c in boosted} == {c.key for c in plain}
    assert {(c.target_file, c.evidence_count) for c in boosted} == {
        (c.target_file, c.evidence_count) for c in plain
    }
    assert all(c.project_paths == ("/w/atlas",) for c in boosted)


def test_the_boost_cannot_outrank_corroboration() -> None:
    """One drift-confirmed project still ranks below two agreeing projects."""
    line = "- One project's rule."
    corroborated = "- Two projects' rule."
    records = [
        record("solo", lines=[line]),
        record("atlas", lines=[corroborated]),
        record("kiln", lines=[corroborated]),
    ]
    ages = {"/w/solo": 0.0, "/w/atlas": 0.0, "/w/kiln": 0.0}
    signal = DriftSignal(lines={("/w/solo", "AGENTS.md"): frozenset({line})}, missing={})

    ranked = group_candidates(records, ages=ages, drift=signal)
    assert ranked[0].key == corroborated


def test_empty_drift_is_the_identity(workspace) -> None:
    """`EMPTY_DRIFT` scores exactly as no drift signal at all."""
    records = [record("atlas"), record("kiln")]
    ages = {"/w/atlas": 0.0, "/w/kiln": 0.0}
    assert [c.evidence_score for c in group_candidates(records, ages=ages, drift=EMPTY_DRIFT)] == [
        c.evidence_score for c in group_candidates(records, ages=ages)
    ]


# ------------------------------------------------------- the gate, end to end (§5.4.9)


C2_LINE = "- Run `make check` before every commit."

C2_PAYLOAD = {
    "proposals": [
        {
            "title": "Require a green check before every commit",
            "rationale": "Several projects state the same pre-commit convention.",
            "proposed_body": C2_LINE,
            "target_section": "## Testing instructions",
            "source_lines": [C2_LINE],
        }
    ]
}


def fixed_runner(payload):
    """A `claude` stand-in returning one fixed structured response."""

    def runner(prompt: str, model: Optional[str] = None) -> str:
        return json.dumps(payload)

    return runner


def summarize(db):
    """Every proposal as (content_hash, evidence_count, contributing paths, score)."""
    out = {}
    for row in list_proposals(db, status=None):
        paths = tuple(sorted(str(e["project_path"]) for e in get_evidence(db, int(row["id"]))))
        out[str(row["content_hash"])] = (
            int(row["evidence_count"]),
            paths,
            float(row["evidence_score"]),
        )
    return out


def test_review_drift_raises_the_score_rather_than_creating_a_parallel_finding(
    workspace, tmp_path: Path
) -> None:
    """The Phase 6 gate, asserted through the real pipeline on both halves.

    Two scans of the same workspace differing only in whether `review`'s findings are
    consulted: the queue is row-for-row identical — same proposals, same evidence rows,
    same contributing projects — and the corroborated pattern simply scores higher.
    """
    runner = fixed_runner(C2_PAYLOAD)

    without = get_db(tmp_path / "without.db")
    scan(
        workspace.projects,
        templates_dir=workspace.templates,
        db=without,
        yes=True,
        runner=runner,
        drift=EMPTY_DRIFT,
    )

    with_review = get_db(tmp_path / "with.db")
    scan(
        workspace.projects,
        templates_dir=workspace.templates,
        db=with_review,
        yes=True,
        runner=runner,
    )

    plain, boosted = summarize(without), summarize(with_review)
    assert plain, "the fixed payload must produce at least one proposal"

    # No parallel finding: identical rows, identical provenance.
    assert set(boosted) == set(plain)
    for content_hash, (count, paths, score) in plain.items():
        b_count, b_paths, b_score = boosted[content_hash]
        assert (b_count, b_paths) == (count, paths)
        # Exactly one boost per contributing project: the score is the unboosted score
        # scaled once, not a score with extra terms added to it.
        assert b_score == pytest.approx(score * (1.0 + DRIFT_BOOST), rel=1e-3)
        assert b_score > score

    # And no evidence row for a project that only `review` had anything to say about.
    for _content_hash, (_c, paths, _s) in boosted.items():
        for path in paths:
            assert (Path(path) / "AGENTS.md").is_file()
