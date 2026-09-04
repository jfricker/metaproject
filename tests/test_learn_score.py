"""Scoring tests: frequency, recency, activity weighting, and queue ordering.

plan.md Phase 2 gate and spec.md §5.4.2. Acceptance cases: C2, C3, C4, C10, C22.
No model is involved: every number here is derived deterministically from collected
evidence and `universe` classifications.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from metaproject.config import DEFAULT_ACTIVITY_WEIGHTS, Config, LearnConfig
from metaproject.learn.collect import EvidenceRecord, collect_workspace
from metaproject.learn.guard import guard_evidence
from metaproject.learn.score import (
    RECENCY_BONUS,
    RECENCY_HALF_LIFE_DAYS,
    Candidate,
    ProjectWeight,
    activity_weight,
    candidate_key,
    group_candidates,
    order_queue,
    rank_candidates,
    recency_factor,
    weigh_project,
)
from tests.fixtures.learn_workspace.build import build_workspace

C2_LINE = "- Run `make check` before every commit."
C3_HEADING = "## Release process"
C4_LINE = "- Always benchmark the tokenizer against the 2019 corpus before merging."


@pytest.fixture
def workspace(tmp_path: Path):
    """Materialize the learn acceptance workspace."""
    return build_workspace(tmp_path)


@pytest.fixture
def candidates(workspace):
    """Guarded evidence for the whole fixture workspace, grouped and ranked."""
    records = collect_workspace(workspace.projects, workspace.templates)
    guarded = guard_evidence(records)
    return group_candidates(guarded.records)


def find(candidates, target_file: str, line: str) -> Candidate:
    """Return the single candidate carrying `line` for `target_file`."""
    matches = [
        c for c in candidates if c.target_file == target_file and c.key == candidate_key(line)
    ]
    assert len(matches) == 1, f"expected exactly one candidate for {line!r}, got {len(matches)}"
    return matches[0]


def _record(
    project: str,
    classification: str,
    line: str,
    target_file: str = "AGENTS.md",
) -> EvidenceRecord:
    """Build a synthetic evidence record for weighting tests."""
    return EvidenceRecord(
        project_name=project,
        project_path=f"/w/{project}",
        classification=classification,
        target_file=target_file,
        template_path=f"/t/{target_file}",
        kind="edit",
        diff="",
        added_lines=(line,),
    )


# --------------------------------------------------------------------------- activity weights


def test_activity_weight_uses_the_configured_table() -> None:
    """Every classification spec.md §4.2 names resolves to its configured weight."""
    for classification, expected in DEFAULT_ACTIVITY_WEIGHTS.items():
        assert activity_weight(classification) == expected


def test_activity_weight_orders_active_now_above_ancient_and_archived() -> None:
    """C10/C22: Active Now counts fully; Ancient and Archived count fractionally."""
    assert activity_weight("Active Now") == 1.0
    assert activity_weight("Ancient") == 0.2
    assert activity_weight("Archived") == 0.1
    assert activity_weight("Archived") < activity_weight("Ancient") < activity_weight("Active Now")


def test_activity_weight_honors_a_custom_weight_table() -> None:
    """The weights are configuration, not constants (spec.md §4.2: 'provisional')."""
    learn = LearnConfig(activity_weights={"Active Now": 3.0, "Archived": 0.5})
    assert activity_weight("Active Now", weights=learn.activity_weights) == 3.0
    assert activity_weight("Archived", weights=learn.activity_weights) == 0.5


def test_activity_weight_falls_back_for_an_unknown_classification() -> None:
    """An unclassified project still contributes, at a documented fallback weight."""
    weight = activity_weight(None)
    assert 0.0 < weight <= 1.0
    assert activity_weight("Not A Classification") == weight


def test_archived_projects_are_scanned_but_weighted_at_the_floor() -> None:
    """C22: the answer to 'scan archived at all?' is yes-but-barely."""
    floor = min(DEFAULT_ACTIVITY_WEIGHTS.values())
    assert activity_weight("Archived") == floor


# --------------------------------------------------------------------------- recency


def test_recency_factor_is_one_for_a_project_touched_today() -> None:
    """A change made now carries the full recency bonus."""
    assert recency_factor(0.0) == pytest.approx(1.0)


def test_recency_factor_halves_over_the_half_life() -> None:
    """Recency decays with a documented half-life rather than a cliff."""
    assert recency_factor(RECENCY_HALF_LIFE_DAYS) == pytest.approx(0.5)
    assert recency_factor(2 * RECENCY_HALF_LIFE_DAYS) == pytest.approx(0.25)


def test_recency_factor_is_monotonically_decreasing() -> None:
    """Older is never worth more than newer."""
    ages = [0.0, 1.0, 5.0, 30.0, 90.0, 400.0]
    factors = [recency_factor(age) for age in ages]
    assert factors == sorted(factors, reverse=True)
    assert all(f > 0.0 for f in factors)


def test_recency_factor_clamps_a_negative_age() -> None:
    """A file stamped in the future must not exceed a freshly-edited one."""
    assert recency_factor(-100.0) == pytest.approx(1.0)


# --------------------------------------------------------------------------- combination


def test_weigh_project_combines_activity_and_recency() -> None:
    """The per-project weight is activity-weighted, with recency as a bounded bonus."""
    assert weigh_project("Active Now", age_days=0.0) == pytest.approx(1.0 * (1 + RECENCY_BONUS))
    assert weigh_project("Archived", age_days=0.0) == pytest.approx(0.1 * (1 + RECENCY_BONUS))


def test_recency_never_lets_a_stale_project_outweigh_its_activity_class() -> None:
    """Recency modulates within a class; it cannot promote Ancient above Active Now."""
    fresh_ancient = weigh_project("Ancient", age_days=0.0)
    stale_active = weigh_project("Active Now", age_days=10_000.0)
    assert fresh_ancient < stale_active


def test_recency_orders_two_projects_of_the_same_activity_class() -> None:
    """Frequency and activity being equal, the more recent project weighs more."""
    recent = weigh_project("Active Now", age_days=0.5)
    older = weigh_project("Active Now", age_days=2.0)
    assert recent > older


# --------------------------------------------------------------------------- grouping


def test_group_candidates_deduplicates_projects_within_a_candidate() -> None:
    """A line repeated inside one project is one contribution, not many."""
    record = _record("atlas", "Active Now", C2_LINE)
    twice = replace(record, added_lines=(C2_LINE, f"  {C2_LINE}  ", C2_LINE))
    grouped = group_candidates([twice], ages={"/w/atlas": 0.0})
    assert len(grouped) == 1
    assert grouped[0].evidence_count == 1
    assert grouped[0].evidence_score == pytest.approx(weigh_project("Active Now", 0.0))


def test_group_candidates_keys_ignore_whitespace_and_indentation() -> None:
    """C23: a CRLF/indented copy of the same line is the same candidate."""
    records = [
        _record("atlas", "Active Now", C2_LINE),
        _record("lattice", "Active Now", f"   {C2_LINE}   "),
    ]
    grouped = group_candidates(records, ages={"/w/atlas": 0.0, "/w/lattice": 0.0})
    assert len(grouped) == 1
    assert grouped[0].evidence_count == 2


def test_group_candidates_separates_the_same_line_in_different_target_files() -> None:
    """A Makefile line and an AGENTS.md line are never the same proposal."""
    records = [
        _record("atlas", "Active Now", "check: lint test", target_file="AGENTS.md"),
        _record("atlas", "Active Now", "check: lint test", target_file="Makefile"),
    ]
    grouped = group_candidates(records, ages={"/w/atlas": 0.0})
    assert {c.target_file for c in grouped} == {"AGENTS.md", "Makefile"}


def test_group_candidates_carries_provenance_for_every_contributor() -> None:
    """Each contribution keeps its project path, classification, and weight."""
    records = [
        _record("atlas", "Active Now", C2_LINE),
        _record("relic", "Ancient", C2_LINE),
    ]
    grouped = group_candidates(records, ages={"/w/atlas": 0.0, "/w/relic": 400.0})
    contributions = {c.project_name: c for c in grouped[0].contributions}
    assert set(contributions) == {"atlas", "relic"}
    assert contributions["relic"].classification == "Ancient"
    assert contributions["relic"].project_path == "/w/relic"
    assert isinstance(contributions["atlas"], ProjectWeight)


# --------------------------------------------------------------------------- the gate


def test_corroborated_candidate_outranks_a_single_project_candidate(candidates) -> None:
    """Phase 2 gate: a single-project candidate surfaces and ranks below a corroborated one."""
    corroborated = find(candidates, "AGENTS.md", C2_LINE)
    one_off = find(candidates, "AGENTS.md", C4_LINE)

    assert one_off.evidence_count == 1
    assert corroborated.evidence_count == 11
    assert corroborated.evidence_score > one_off.evidence_score
    assert candidates.index(corroborated) < candidates.index(one_off)


def test_single_project_candidate_is_ranked_not_gated(candidates) -> None:
    """C4: the one-off must still appear in the queue. Candidates are ranked, not gated."""
    one_off = find(candidates, "AGENTS.md", C4_LINE)
    assert one_off.evidence_score > 0.0
    assert one_off in candidates


def test_c2_contributing_projects_are_exactly_the_eleven_expected(workspace, candidates) -> None:
    """C2: eleven projects, spanning six activity classes, corroborate the same line."""
    expected = set(workspace.case("C2")["projects"])
    corroborated = find(candidates, "AGENTS.md", C2_LINE)
    contributed = {
        str(Path(c.project_path).relative_to(workspace.projects))
        for c in corroborated.contributions
    }
    assert contributed == expected


def test_c3_new_markdown_section_is_a_three_project_candidate(candidates) -> None:
    """C3: a heading is learnable evidence, corroborated by exactly three projects."""
    heading = find(candidates, "AGENTS.md", C3_HEADING)
    assert heading.evidence_count == 3
    assert heading.content.strip() == C3_HEADING


def test_c3_outranks_the_one_off_but_not_the_eleven_project_candidate(candidates) -> None:
    """C4: the one-off ranks strictly below both C2 and C3."""
    corroborated = find(candidates, "AGENTS.md", C2_LINE)
    heading = find(candidates, "AGENTS.md", C3_HEADING)
    one_off = find(candidates, "AGENTS.md", C4_LINE)
    assert corroborated.evidence_score > heading.evidence_score > one_off.evidence_score


def test_c10_activity_weighting_is_visible_per_contribution(candidates) -> None:
    """C10: assert on the per-evidence weight, not only on the total."""
    corroborated = find(candidates, "AGENTS.md", C2_LINE)
    by_name = {c.project_name: c for c in corroborated.contributions}

    atlas = by_name["atlas"]
    relic = by_name["relic"]
    derelict = by_name["derelict"]

    assert atlas.classification == "Active Now"
    assert relic.classification == "Ancient"
    assert derelict.classification == "Archived"
    assert relic.weight < atlas.weight
    assert derelict.weight < atlas.weight
    assert derelict.weight < relic.weight


def test_c22_archived_project_contributes_at_the_floor_weight(candidates) -> None:
    """C22: Archive/derelict is scanned, classified Archived, and weighted 0.1."""
    corroborated = find(candidates, "AGENTS.md", C2_LINE)
    derelict = next(c for c in corroborated.contributions if c.project_name == "derelict")
    assert derelict.activity == 0.1
    assert derelict.weight > 0.0


def test_evidence_score_is_the_sum_of_contribution_weights(candidates) -> None:
    """The score accumulates (spec.md §5.4.2), so provenance explains the number."""
    corroborated = find(candidates, "AGENTS.md", C2_LINE)
    total = sum(c.weight for c in corroborated.contributions)
    assert corroborated.evidence_score == pytest.approx(total)


# --------------------------------------------------------------------------- ordering stability


def test_ranking_is_descending_by_score(candidates) -> None:
    """The queue is ordered by score descending (spec.md §5.4.2)."""
    scores = [c.evidence_score for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_ranking_is_stable_across_repeated_grouping(workspace) -> None:
    """The same evidence must always produce the same ordering, run to run."""
    records = collect_workspace(workspace.projects, workspace.templates)
    guarded = guard_evidence(records)
    ages = {r.project_path: 3.0 for r in guarded.records}

    first = group_candidates(guarded.records, ages=ages)
    second = group_candidates(list(reversed(guarded.records)), ages=ages)

    assert [(c.target_file, c.key) for c in first] == [(c.target_file, c.key) for c in second]
    assert [c.evidence_score for c in first] == [c.evidence_score for c in second]


def test_rank_candidates_breaks_score_ties_deterministically() -> None:
    """Equal scores fall back to evidence count, then target file, then key."""
    records = [
        _record("atlas", "Active Now", "- beta line", target_file="AGENTS.md"),
        _record("kiln", "Active Now", "- alpha line", target_file="AGENTS.md"),
    ]
    ages = {"/w/atlas": 1.0, "/w/kiln": 1.0}
    ranked = rank_candidates(group_candidates(records, ages=ages))
    assert ranked[0].evidence_score == pytest.approx(ranked[1].evidence_score)
    assert [c.content for c in ranked] == ["- alpha line", "- beta line"]


def test_order_queue_sorts_stored_rows_by_score_then_count(candidates) -> None:
    """`learn list` ordering uses the same rule as in-memory ranking."""
    rows = [
        {"id": 1, "evidence_score": 1.0, "evidence_count": 1, "target_file": "AGENTS.md"},
        {"id": 2, "evidence_score": 9.0, "evidence_count": 11, "target_file": "AGENTS.md"},
        {"id": 3, "evidence_score": 1.0, "evidence_count": 4, "target_file": "AGENTS.md"},
    ]
    assert [r["id"] for r in order_queue(rows)] == [2, 3, 1]


def test_group_candidates_reads_weights_from_a_config(workspace) -> None:
    """A custom config weight table changes the score, proving it is not hard-coded."""
    records = [
        _record("atlas", "Active Now", C2_LINE),
        _record("derelict", "Archived", C2_LINE),
    ]
    ages = {"/w/atlas": 0.0, "/w/derelict": 0.0}
    config = Config(learn=LearnConfig(activity_weights={"Active Now": 1.0, "Archived": 1.0}))

    default = group_candidates(records, ages=ages)[0]
    flattened = group_candidates(records, ages=ages, config=config)[0]

    assert flattened.evidence_score > default.evidence_score
    weights = {c.project_name: c.activity for c in flattened.contributions}
    assert weights == {"atlas": 1.0, "derelict": 1.0}


def test_group_candidates_resolves_ages_from_the_filesystem(workspace) -> None:
    """With no injected ages, recency comes from the project's own timestamp."""
    records = collect_workspace(workspace.project("quarry"), workspace.templates)
    grouped = group_candidates(records)
    assert grouped
    for candidate in grouped:
        for contribution in candidate.contributions:
            assert contribution.age_days > 0.0
            assert 0.0 < contribution.recency <= 1.0


def test_empty_evidence_produces_an_empty_queue() -> None:
    """A workspace that matches its templates yields nothing to review."""
    assert group_candidates([]) == []
    assert rank_candidates([]) == []
    assert order_queue([]) == []
