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

import importlib
from typing import Any

# Public name -> the submodule that defines it. Resolved on first access (PEP 562)
# rather than at import, so importing one submodule (`review` uses
# `metaproject.learn.collect`) never drags in `store`/`api`, and with them
# `sqlite-utils`, which ships only in the optional `tui` extra.
_EXPORTS = {
    "ScanResult": "api",
    "parse_since": "api",
    "reject_proposal": "api",
    "review": "api",
    "scan": "api",
    "ApplyPlan": "apply",
    "ApplyResult": "apply",
    "Section": "apply",
    "apply_plan": "apply",
    "apply_proposal": "apply",
    "body_is_present": "apply",
    "commit_message": "apply",
    "ensure_clean_repository": "apply",
    "iter_sections": "apply",
    "normalize_heading": "apply",
    "plan_apply": "apply",
    "proposal_body": "apply",
    "resolve_section": "apply",
    "splice": "apply",
    "template_destination": "apply",
    "EvidenceRecord": "collect",
    "collect_project": "collect",
    "collect_workspace": "collect",
    "iter_project_dirs": "collect",
    "iter_target_files": "collect",
    "normalize_text": "collect",
    "project_variables": "collect",
    "resolve_template": "collect",
    "EMPTY_DRIFT": "drift",
    "DriftSignal": "drift",
    "added_lines": "drift",
    "collect_drift": "drift",
    "GitignoreMatcher": "guard",
    "GuardResult": "guard",
    "SendManifest": "guard",
    "build_manifest": "guard",
    "confirm_send": "guard",
    "contains_secret": "guard",
    "exclusion_reason": "guard",
    "filter_paths": "guard",
    "guard_evidence": "guard",
    "is_denylisted": "guard",
    "redact": "guard",
    "Candidate": "score",
    "ProjectWeight": "score",
    "activity_weight": "score",
    "candidate_key": "score",
    "drift_factor": "score",
    "group_candidates": "score",
    "order_queue": "score",
    "rank_candidates": "score",
    "recency_factor": "score",
    "weigh_project": "score",
    "EvidenceDraft": "store",
    "ProposalDraft": "store",
    "content_hash": "store",
    "evidence_hash": "store",
    "finish_run": "store",
    "get_evidence": "store",
    "get_proposal": "store",
    "get_proposal_by_hash": "store",
    "is_suppressed": "store",
    "list_proposals": "store",
    "mark_applied": "store",
    "should_resurface": "store",
    "start_run": "store",
    "upsert_proposal": "store",
    "Bundle": "synth",
    "Proposal": "synth",
    "SynthResult": "synth",
    "build_prompt": "synth",
    "build_reduce_prompt": "synth",
    "bundle_evidence": "synth",
    "chunk_bundle": "synth",
    "claude_command": "synth",
    "parse_response": "synth",
    "render_block": "synth",
    "resolve_claude": "synth",
    "run_claude": "synth",
    "split_record": "synth",
    "synthesize": "synth",
    "validate_proposal": "synth",
    "SessionResult": "tui",
    "effective_view": "tui",
    "open_in_editor": "tui",
    "order_for_review": "tui",
    "run_review": "tui",
    "should_open_tui": "tui",
    "tui_enabled": "tui",
}

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


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value


def __dir__() -> list:
    return sorted(set(globals()) | set(_EXPORTS))
