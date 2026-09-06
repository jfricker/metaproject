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
from typing import List, Optional

import pytest

from metaproject.db import get_db
from metaproject.learn import scan
from metaproject.learn.collect import EvidenceRecord
from metaproject.learn.drift import (
    EMPTY_DRIFT,
    DriftSignal,
    added_lines,
    collect_drift,
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
