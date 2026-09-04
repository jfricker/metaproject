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
- Phase 3 — `synth` (prompt assembly, per-target-file bundling, chunk-and-reduce, the
  `claude -p` invocation, and structured output parsing and validation). The only module
  that reaches a model, and the only one that treats its input as untrusted.
- Phase 4 — `apply` (structural splicing at a proposal's `target_section`, and one git
  commit per accept) and `api` (the public surface `cli.py` and `tui.py` call).
- Phase 5 — `tui` (the `rich` acceptance loop). Every keystroke delegates to the same
  function the equivalent subcommand calls, so there is no TUI-only code path.

The public API is `scan()`, `review()`, `apply_proposal()`, and `reject_proposal()`.
`scan` imports nothing from `apply`, so a scan cannot reach the write path even by
mistake.
"""

from metaproject.learn.api import (
    ScanResult,
    parse_since,
    reject_proposal,
    review,
    scan,
)
from metaproject.learn.apply import (
    ApplyPlan,
    ApplyResult,
    Section,
    apply_plan,
    apply_proposal,
    body_is_present,
    commit_message,
    ensure_clean_repository,
    iter_sections,
    normalize_heading,
    plan_apply,
    proposal_body,
    resolve_section,
    splice,
    template_destination,
)
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
from metaproject.learn.drift import (
    EMPTY_DRIFT,
    DriftSignal,
    added_lines,
    collect_drift,
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
    drift_factor,
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
    should_resurface,
    start_run,
    upsert_proposal,
)
from metaproject.learn.synth import (
    Bundle,
    Proposal,
    SynthResult,
    build_prompt,
    build_reduce_prompt,
    bundle_evidence,
    chunk_bundle,
    claude_command,
    parse_response,
    render_block,
    resolve_claude,
    run_claude,
    split_record,
    synthesize,
    validate_proposal,
)
from metaproject.learn.tui import (
    SessionResult,
    effective_view,
    open_in_editor,
    order_for_review,
    run_review,
    should_open_tui,
    tui_enabled,
)

__all__ = [
    "ApplyPlan",
    "SessionResult",
    "effective_view",
    "open_in_editor",
    "order_for_review",
    "run_review",
    "should_open_tui",
    "tui_enabled",
    "ApplyResult",
    "ScanResult",
    "Section",
    "apply_plan",
    "apply_proposal",
    "body_is_present",
    "commit_message",
    "ensure_clean_repository",
    "iter_sections",
    "normalize_heading",
    "parse_since",
    "plan_apply",
    "proposal_body",
    "resolve_section",
    "review",
    "scan",
    "splice",
    "template_destination",
    "Bundle",
    "Candidate",
    "Proposal",
    "SynthResult",
    "build_prompt",
    "build_reduce_prompt",
    "bundle_evidence",
    "chunk_bundle",
    "claude_command",
    "parse_response",
    "render_block",
    "resolve_claude",
    "run_claude",
    "split_record",
    "synthesize",
    "validate_proposal",
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
    "EMPTY_DRIFT",
    "DriftSignal",
    "activity_weight",
    "added_lines",
    "candidate_key",
    "collect_drift",
    "drift_factor",
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
