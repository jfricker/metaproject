"""The `metaproject learn` proposal pipeline (spec.md §5.4).

`learn` observes drift across many projects, uses a model to synthesize generalizable
template changes, records them as durable ranked proposals with provenance, and applies
them only after operator review. A scan never mutates a template.

Implemented so far (plan.md phases):

- Phase 1 — `collect` (render-and-diff evidence) and `guard` (egress filtering,
  redaction, send manifest). Both deterministic; no model is involved.
- Phase 2 — `score` (frequency, recency, and activity weighting; queue ordering) and
  `store` (the proposal ledger: upsert by content hash, provenance, suppression and
  resurfacing, run records). Also deterministic, and `store` is the only module that
  touches SQLite.

The public API — `scan()`, `review()`, `apply_proposal()`, `reject_proposal()` — arrives
with the later phases, alongside `synth`, `apply`, and `tui`.
"""

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
from metaproject.learn.guard import (
    GitignoreMatcher,
    GuardResult,
    SendManifest,
    build_manifest,
    confirm_send,
    contains_secret,
    exclusion_reason,
    filter_paths,
    guard_evidence,
    is_denylisted,
    redact,
)
from metaproject.learn.score import (
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
from metaproject.learn.store import (
    EvidenceDraft,
    ProposalDraft,
    content_hash,
    evidence_hash,
    finish_run,
    get_evidence,
    get_proposal,
    get_proposal_by_hash,
    is_suppressed,
    list_proposals,
    mark_applied,
    reject_proposal,
    should_resurface,
    start_run,
    upsert_proposal,
)

__all__ = [
    "Candidate",
    "EvidenceDraft",
    "EvidenceRecord",
    "ProjectWeight",
    "ProposalDraft",
    "GitignoreMatcher",
    "GuardResult",
    "SendManifest",
    "build_manifest",
    "collect_project",
    "collect_workspace",
    "activity_weight",
    "candidate_key",
    "confirm_send",
    "contains_secret",
    "content_hash",
    "evidence_hash",
    "finish_run",
    "get_evidence",
    "get_proposal",
    "get_proposal_by_hash",
    "group_candidates",
    "is_suppressed",
    "list_proposals",
    "mark_applied",
    "order_queue",
    "rank_candidates",
    "recency_factor",
    "reject_proposal",
    "should_resurface",
    "start_run",
    "upsert_proposal",
    "weigh_project",
    "exclusion_reason",
    "filter_paths",
    "guard_evidence",
    "is_denylisted",
    "iter_project_dirs",
    "iter_target_files",
    "normalize_text",
    "project_variables",
    "redact",
    "resolve_template",
]
