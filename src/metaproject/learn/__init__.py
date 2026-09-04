"""The `metaproject learn` proposal pipeline (spec.md §5.4).

`learn` observes drift across many projects, uses a model to synthesize generalizable
template changes, records them as durable ranked proposals with provenance, and applies
them only after operator review. A scan never mutates a template.

Implemented so far (plan.md phases):

- Phase 1 — `collect` (render-and-diff evidence) and `guard` (egress filtering,
  redaction, send manifest). Both deterministic; no model is involved.

The public API — `scan()`, `review()`, `apply_proposal()`, `reject_proposal()` — arrives
with the later phases, alongside `score`, `store`, `synth`, `apply`, and `tui`.
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

__all__ = [
    "EvidenceRecord",
    "GitignoreMatcher",
    "GuardResult",
    "SendManifest",
    "build_manifest",
    "collect_project",
    "collect_workspace",
    "confirm_send",
    "contains_secret",
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
