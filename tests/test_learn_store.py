"""Proposal ledger tests: hashing, upsert, provenance, suppression, resurfacing, runs.

plan.md Phase 2 gate and spec.md §5.4.7/§5.4.8. Acceptance case: C15.
`store` is the only module that touches SQLite, so this file is the only place the
`learn_proposals` / `learn_evidence` / `learn_runs` tables are exercised.
"""

from pathlib import Path

import pytest

from metaproject.db import get_db
from metaproject.learn.collect import collect_workspace
from metaproject.learn.guard import guard_evidence
from metaproject.learn.score import group_candidates
from metaproject.learn.store import (
    EvidenceDraft,
    ProposalDraft,
    content_hash,
    evidence_hash,
    finish_run,
    get_evidence,
    get_proposal,
    get_proposal_by_hash,
    get_run,
    is_suppressed,
    latest_run,
    list_proposals,
    mark_applied,
    normalize_for_hash,
    reject_proposal,
    should_resurface,
    start_run,
    upsert_proposal,
)
from tests.fixtures.learn_workspace.build import build_workspace

C2_LINE = "- Run `make check` before every commit."


@pytest.fixture
def db(tmp_path: Path):
    """A fresh universe.db with the Phase 0 learn schema."""
    return get_db(tmp_path / "universe.db")


def draft(**overrides) -> ProposalDraft:
    """A proposal draft with sensible defaults; override what a test cares about."""
    body = overrides.pop("proposed_body", "- Run `make check` before every commit.")
    target_file = overrides.pop("target_file", "AGENTS.md")
    kind = overrides.pop("kind", "edit")
    fields = {
        "content_hash": content_hash(target_file, body, kind=kind),
        "target_file": target_file,
        "template_path": "/t/AGENTS.template.md",
        "kind": kind,
        "title": "Require make check before committing",
        "rationale": "Eleven projects add the same pre-commit instruction.",
        "proposed_body": body,
        "target_section": "## Testing instructions",
        "evidence_count": 11,
        "evidence_score": 8.4,
    }
    fields.update(overrides)
    return ProposalDraft(**fields)


# --------------------------------------------------------------------------- hashing (R3)


def test_normalize_for_hash_folds_whitespace_and_line_endings() -> None:
    """Hash normalized content, never raw prose (plan.md R3)."""
    assert normalize_for_hash("- Run   make check\r\n\n") == normalize_for_hash("- Run make check")


def test_normalize_for_hash_drops_blank_lines_and_indentation() -> None:
    """Re-indentation and blank-line churn must not mint a new identity."""
    a = "## Release process\n\nTag the release.\n"
    b = "   ## Release process\n      Tag the release.   \n\n\n"
    assert normalize_for_hash(a) == normalize_for_hash(b)


def test_content_hash_is_stable_for_equivalent_bodies() -> None:
    """The same content re-worded only in whitespace hashes identically."""
    assert content_hash("AGENTS.md", "- a\n- b\n") == content_hash("AGENTS.md", "  - a\n\n  - b  ")


def test_content_hash_separates_target_files_and_kinds() -> None:
    """Identical text for a different file, or a different kind, is a different proposal."""
    body = "- a"
    assert content_hash("AGENTS.md", body) != content_hash("README.md", body)
    assert content_hash("AGENTS.md", body) != content_hash("AGENTS.md", body, kind="new_template")


def test_content_hash_changes_when_the_content_changes() -> None:
    """Different wording is a different proposal, which is exactly R3's failure mode."""
    assert content_hash("AGENTS.md", "- a") != content_hash("AGENTS.md", "- b")


def test_evidence_hash_is_deterministic_and_order_independent() -> None:
    """R3 fallback: hashing the evidence set is stable regardless of model wording."""
    excerpts = ["- b line", "- a line"]
    assert evidence_hash("AGENTS.md", excerpts) == evidence_hash(
        "AGENTS.md", list(reversed(excerpts))
    )
    assert evidence_hash("AGENTS.md", excerpts) == evidence_hash("AGENTS.md", excerpts + excerpts)


def test_evidence_hash_differs_from_content_hash_for_the_same_text() -> None:
    """The two hash domains are namespaced so they can never collide."""
    assert evidence_hash("AGENTS.md", ["- a"]) != content_hash("AGENTS.md", "- a")


def test_evidence_hash_of_a_real_candidate_survives_a_rescan(tmp_path: Path) -> None:
    """The deterministic identity is reproducible from the workspace alone."""
    workspace = build_workspace(tmp_path)
    first = group_candidates(
        guard_evidence(collect_workspace(workspace.projects, workspace.templates)).records
    )
    second = group_candidates(
        guard_evidence(collect_workspace(workspace.projects, workspace.templates)).records
    )

    def hashes(candidates):
        return [
            evidence_hash(c.target_file, [x.excerpt for x in c.contributions], kind=c.kind)
            for c in candidates
        ]

    assert hashes(first) == hashes(second)


# --------------------------------------------------------------------------- upsert


def test_upsert_inserts_a_pending_proposal(db) -> None:
    """A new content hash becomes a pending row with timestamps."""
    proposal_id = upsert_proposal(db, draft())
    row = get_proposal(db, proposal_id)
    assert row["status"] == "pending"
    assert row["evidence_count"] == 11
    assert row["created_at"] and row["updated_at"]
    assert row["rejected_score"] is None


def test_upsert_by_content_hash_updates_rather_than_duplicates(db) -> None:
    """Phase 2 gate: proposals upsert by `content_hash`."""
    first = upsert_proposal(db, draft(evidence_score=4.0, evidence_count=5))
    second = upsert_proposal(db, draft(evidence_score=8.4, evidence_count=11))

    assert first == second
    assert len(list_proposals(db)) == 1
    row = get_proposal(db, first)
    assert row["evidence_score"] == pytest.approx(8.4)
    assert row["evidence_count"] == 11


def test_upsert_preserves_created_at_and_advances_updated_at(db) -> None:
    """The ledger remembers when a proposal first appeared."""
    proposal_id = upsert_proposal(db, draft())
    created = get_proposal(db, proposal_id)["created_at"]
    upsert_proposal(db, draft(evidence_score=9.9))
    assert get_proposal(db, proposal_id)["created_at"] == created


def test_upsert_preserves_an_operator_edit(db) -> None:
    """`edited_body` is the operator's, not the model's; a rescan must not clobber it."""
    proposal_id = upsert_proposal(db, draft())
    mark_applied(db, proposal_id, commit="abc123", edited_body="- Run `make verify` first.")
    upsert_proposal(db, draft(evidence_score=12.0))
    row = get_proposal(db, proposal_id)
    assert row["edited_body"] == "- Run `make verify` first."


def test_upsert_does_not_reopen_an_applied_proposal(db) -> None:
    """An applied change stays applied no matter how much evidence accrues."""
    proposal_id = upsert_proposal(db, draft())
    mark_applied(db, proposal_id, commit="abc123")
    upsert_proposal(db, draft(evidence_score=99.0))
    assert get_proposal(db, proposal_id)["status"] == "applied"


def test_get_proposal_by_hash_round_trips(db) -> None:
    """Suppression is keyed by hash, so hash lookup must be a first-class operation."""
    d = draft()
    proposal_id = upsert_proposal(db, d)
    assert get_proposal_by_hash(db, d.content_hash)["id"] == proposal_id
    assert get_proposal_by_hash(db, "nope") is None


# --------------------------------------------------------------------------- evidence rows


def test_upsert_records_per_project_evidence_with_weights(db) -> None:
    """Provenance is stored per contributing project, weight included (C10)."""
    evidence = [
        EvidenceDraft(project_path="/w/atlas", excerpt=C2_LINE, weight=1.5),
        EvidenceDraft(project_path="/w/relic", excerpt=C2_LINE, weight=0.2),
    ]
    proposal_id = upsert_proposal(db, draft(), evidence=evidence)
    rows = get_evidence(db, proposal_id)
    assert {r["project_path"] for r in rows} == {"/w/atlas", "/w/relic"}
    assert {r["weight"] for r in rows} == {1.5, 0.2}


def test_rescanning_replaces_evidence_instead_of_appending(db) -> None:
    """Evidence describes the current scan; stale rows would inflate the count forever."""
    proposal_id = upsert_proposal(
        db, draft(), evidence=[EvidenceDraft(project_path="/w/atlas", excerpt=C2_LINE, weight=1.5)]
    )
    upsert_proposal(
        db, draft(), evidence=[EvidenceDraft(project_path="/w/kiln", excerpt=C2_LINE, weight=1.2)]
    )
    rows = get_evidence(db, proposal_id)
    assert len(rows) == 1
    assert rows[0]["project_path"] == "/w/kiln"


def test_evidence_is_removed_when_the_proposal_is_forgotten(db) -> None:
    """`--forget` clears the record entirely, provenance included."""
    proposal_id = upsert_proposal(
        db, draft(), evidence=[EvidenceDraft(project_path="/w/atlas", excerpt=C2_LINE, weight=1.5)]
    )
    reject_proposal(db, proposal_id, forget=True)
    assert get_evidence(db, proposal_id) == []


# --------------------------------------------------------------------------- listing


def test_list_proposals_orders_by_score_descending(db) -> None:
    """Queue ordering (spec.md §5.4.2), served straight from the index."""
    upsert_proposal(db, draft(proposed_body="- low", evidence_score=1.0, evidence_count=1))
    upsert_proposal(db, draft(proposed_body="- high", evidence_score=8.0, evidence_count=11))
    upsert_proposal(db, draft(proposed_body="- mid", evidence_score=4.0, evidence_count=3))
    scores = [r["evidence_score"] for r in list_proposals(db)]
    assert scores == [8.0, 4.0, 1.0]


def test_list_proposals_filters_by_status_target_and_min_score(db) -> None:
    """`learn list --status`, `--target`, and `review --min-score` share one query."""
    low = upsert_proposal(db, draft(proposed_body="- low", evidence_score=1.0))
    upsert_proposal(
        db, draft(target_file="README.md", proposed_body="- readme", evidence_score=5.0)
    )
    reject_proposal(db, low)

    assert [r["id"] for r in list_proposals(db, status="rejected")] == [low]
    assert all(r["target_file"] == "README.md" for r in list_proposals(db, target_file="README.md"))
    assert all(r["evidence_score"] >= 2.0 for r in list_proposals(db, min_score=2.0))


# --------------------------------------------------------------------------- rejection


def test_reject_records_the_score_at_rejection_time(db) -> None:
    """`rejected_score` is the bar the evidence must later clear (spec.md §5.4.7)."""
    proposal_id = upsert_proposal(db, draft(evidence_score=4.0))
    reject_proposal(db, proposal_id)
    row = get_proposal(db, proposal_id)
    assert row["status"] == "rejected"
    assert row["rejected_score"] == pytest.approx(4.0)


def test_should_resurface_requires_strictly_exceeding_the_factor() -> None:
    """The boundary is exclusive: equal is not stronger evidence."""
    assert not should_resurface(rejected_score=4.0, evidence_score=8.0, resurface_factor=2.0)
    assert should_resurface(rejected_score=4.0, evidence_score=8.001, resurface_factor=2.0)
    assert not should_resurface(rejected_score=4.0, evidence_score=7.9, resurface_factor=2.0)


def test_rejected_proposal_stays_suppressed_across_rescans(db) -> None:
    """Phase 2 gate: a rejected hash stays suppressed across scans."""
    d = draft(evidence_score=4.0)
    proposal_id = upsert_proposal(db, d)
    reject_proposal(db, proposal_id)

    for score in (4.0, 5.0, 7.9):
        upsert_proposal(db, draft(evidence_score=score))
        assert get_proposal(db, proposal_id)["status"] == "rejected"
        assert proposal_id not in [r["id"] for r in list_proposals(db, status="pending")]
        assert is_suppressed(db, d.content_hash, score)


def test_rejected_proposal_resurfaces_once_evidence_doubles(db) -> None:
    """Phase 2 gate: it resurfaces exactly when score > rejected_score * resurface_factor."""
    d = draft(evidence_score=4.0)
    proposal_id = upsert_proposal(db, d)
    reject_proposal(db, proposal_id)

    upsert_proposal(db, draft(evidence_score=8.0))
    assert get_proposal(db, proposal_id)["status"] == "rejected"

    upsert_proposal(db, draft(evidence_score=8.5))
    row = get_proposal(db, proposal_id)
    assert row["status"] == "pending"
    assert row["rejected_score"] is None
    assert not is_suppressed(db, d.content_hash, 8.5)


def test_resurface_factor_is_configurable(db) -> None:
    """`learn.resurface_factor` is config, not a constant (spec.md §4.2)."""
    d = draft(evidence_score=4.0)
    proposal_id = upsert_proposal(db, d)
    reject_proposal(db, proposal_id)

    upsert_proposal(db, draft(evidence_score=5.0), resurface_factor=10.0)
    assert get_proposal(db, proposal_id)["status"] == "rejected"

    upsert_proposal(db, draft(evidence_score=5.0), resurface_factor=1.0)
    assert get_proposal(db, proposal_id)["status"] == "pending"


def test_forget_clears_the_suppression_entirely(db) -> None:
    """Phase 2 gate: `--forget` clears it; the next scan sees a brand-new proposal."""
    d = draft(evidence_score=4.0)
    proposal_id = upsert_proposal(db, d)
    reject_proposal(db, proposal_id)
    assert is_suppressed(db, d.content_hash, 4.0)

    assert reject_proposal(db, proposal_id, forget=True) is True
    assert get_proposal(db, proposal_id) is None
    assert not is_suppressed(db, d.content_hash, 4.0)

    fresh = upsert_proposal(db, draft(evidence_score=4.0))
    assert get_proposal(db, fresh)["status"] == "pending"


def test_is_suppressed_is_false_for_an_unknown_hash(db) -> None:
    """A never-seen candidate is never suppressed."""
    assert not is_suppressed(db, "unseen", 100.0)


def test_reject_a_missing_proposal_is_a_no_op(db) -> None:
    """Rejecting an id that is gone must not raise; the CLI passes user input here."""
    assert reject_proposal(db, 4242) is False
    assert reject_proposal(db, 4242, forget=True) is False


# --------------------------------------------------------------------------- apply bookkeeping


def test_mark_applied_records_the_commit(db) -> None:
    """One commit per accept; the ledger stores which one (spec.md §5.4.5)."""
    proposal_id = upsert_proposal(db, draft())
    mark_applied(db, proposal_id, commit="deadbeef")
    row = get_proposal(db, proposal_id)
    assert row["status"] == "applied"
    assert row["applied_commit"] == "deadbeef"


# --------------------------------------------------------------------------- runs


def test_start_and_finish_run_records_the_scan(db) -> None:
    """`learn_runs` is the audit trail for a scan (spec.md §5.4.8)."""
    run_id = start_run(db, root="/w", model="claude-opus")
    open_row = get_run(db, run_id)
    assert open_row["started_at"]
    assert open_row["finished_at"] is None

    finish_run(db, run_id, projects_scanned=16, files_scanned=41, proposals_created=7)
    row = get_run(db, run_id)
    assert row["status"] == "ok"
    assert row["projects_scanned"] == 16
    assert row["files_scanned"] == 41
    assert row["proposals_created"] == 7
    assert row["finished_at"]


def test_finish_run_can_mark_a_partial_or_failed_run(db) -> None:
    """A malformed model response makes the run `partial`, not silently `ok`."""
    run_id = start_run(db, root="/w")
    finish_run(db, run_id, status="partial")
    assert get_run(db, run_id)["status"] == "partial"


def test_latest_run_returns_the_most_recent(db) -> None:
    """The TUI header and `learn list` need the last scan without a full table read."""
    first = start_run(db, root="/w")
    finish_run(db, first)
    second = start_run(db, root="/w2")
    assert latest_run(db)["id"] == second


def test_latest_run_is_none_on_a_fresh_database(db) -> None:
    """No scans yet is a normal state, not an error."""
    assert latest_run(db) is None


# --------------------------------------------------------------------------- end to end


def test_c15_reject_rescan_and_resurface_over_a_real_workspace(tmp_path: Path) -> None:
    """C15: reject the corroborated proposal, rescan (suppressed), strengthen (resurfaces).

    The score change is driven by widening the workspace — two contributing projects,
    then all eleven — never by editing the ledger directly.
    """
    narrow = ["atlas", "relic"]
    workspace = build_workspace(tmp_path, only=narrow)
    db = get_db(tmp_path / "universe.db")

    def scan() -> int:
        records = guard_evidence(collect_workspace(workspace.projects, workspace.templates)).records
        candidates = group_candidates(records)
        target = next(c for c in candidates if c.content.strip() == C2_LINE)
        return upsert_proposal(
            db,
            ProposalDraft(
                content_hash=evidence_hash(
                    target.target_file,
                    [x.excerpt for x in target.contributions],
                    kind=target.kind,
                ),
                target_file=target.target_file,
                template_path=target.template_path,
                kind=target.kind,
                title="Require make check",
                rationale="Corroborated across the workspace.",
                proposed_body=target.content,
                target_section=None,
                evidence_count=target.evidence_count,
                evidence_score=target.evidence_score,
            ),
            evidence=[
                EvidenceDraft(project_path=c.project_path, excerpt=c.excerpt, weight=c.weight)
                for c in target.contributions
            ],
        )

    proposal_id = scan()
    rejected_at = get_proposal(db, proposal_id)["evidence_score"]
    reject_proposal(db, proposal_id)

    # Re-scanning the unchanged workspace must not resurface it.
    assert scan() == proposal_id
    assert get_proposal(db, proposal_id)["status"] == "rejected"
    assert proposal_id not in [r["id"] for r in list_proposals(db, status="pending")]

    # Strengthen the evidence by extending the workspace, not by editing the ledger.
    workspace = build_workspace(tmp_path)

    assert scan() == proposal_id
    row = get_proposal(db, proposal_id)
    assert row["evidence_score"] > rejected_at * 2.0
    assert row["status"] == "pending"
