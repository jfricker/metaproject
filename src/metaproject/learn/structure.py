"""Deterministic heading-structure proposals for the `learn` pipeline (spec.md R-LRN-1a/1c).

Structural evidence (`collect.EvidenceRecord.kind == "structure"`) is heading lines
only, never body text (R-LRN-1). This module turns that evidence directly into
proposals — no model, no prompt, no egress guard, no confirmation — because a heading
add or remove needs no judgment: either enough projects agree it belongs, or it does
not go in the queue at all (R-LRN-1c). `api.scan` calls `propose` on the structural
share of a scan's records *before* the rest reach `guard.guard_evidence`, which is what
keeps a heading's neighboring body text off the egress path entirely (STATE.md design
invariants).

**Grouping.** Evidence clusters by `(target_file, op, level, normalize_heading(title))`,
`op` in `{"add", "remove"}`. A heading whose level changed is naturally one removal
group and one addition group, never a rename — this mirrors R-LRN-3's "one removal plus
one addition" rule without any special-casing here. A proposal is emitted only when the
group has at least `min_evidence` **distinct contributing projects** (R-LRN-1c); this
gate is a plain count, not a weighted score, so a lone heavily-weighted project can
never buy its way past the threshold.

**Scoring.** `weights` and `drift` (the same shapes `api._project_weights` and
`drift.DriftSignal` already use) combine per contributing project exactly the way
`score.weigh_project`/`score.drift_factor` do, and the sum becomes `evidence_score` on
the returned `StructureProposal` — visible here so a test can observe the drift boost
directly, even though `api.scan`'s shared upsert loop recomputes the same number itself
from `contributing_paths` and `source_lines` (deliberately redundant: this module must
not be the only place that number exists). The weighted vote also breaks ties when more
than one anchor heading is contested for an addition (see below).

**Placement.** `add_heading`'s `target_section` is the heading most contributors place
the new heading directly after in their own file: for each contributor, walk backward
from its own copy of the new heading to the nearest preceding heading that matches a
template heading (`markdown.heading_matches`), and let that anchor's canonical template
title cast one weighted vote. Ties fall back to the anchor's position in the template
(earliest wins); no contributor resolving to an anchor at all means `target_section` is
`None`, i.e. append at end of file. `remove_heading` needs no such vote: its
`target_section` is simply the template heading being removed.

**Not here.** The optional one-line section comment (design.md resolved question 2) and
the child-heading refusal for `remove_heading` (plan.md C3's apply-time check) are both
deliberately absent from this module.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from metaproject.learn.collect import EvidenceRecord
from metaproject.learn.score import DriftLookup, drift_factor
from metaproject.learn.store import content_hash
from metaproject.markdown import Heading, heading_matches, headings, normalize_heading

DEFAULT_MIN_STRUCTURE_EVIDENCE = 2

ADD = "add"
REMOVE = "remove"

KIND_ADD_HEADING = "add_heading"
KIND_REMOVE_HEADING = "remove_heading"

GroupKey = Tuple[str, str, int, str]
"""(target_file, op, level, normalize_heading(title))."""

ProjectTextFn = Callable[[str, str], Optional[str]]
"""(project_path, target_file) -> the project's file text, or None if unreadable."""


@dataclass(frozen=True)
class StructureProposal:
    """A deterministic heading-structure proposal.

    Attribute-compatible with `synth.Proposal` — `api.scan`'s upsert loop reads
    `content_hash`, `target_file`, `kind`, `title`, `rationale`, `proposed_body`,
    `target_section`, `template_path`, `contributing_paths`, and `source_lines` off
    either without caring which module produced it — plus `evidence_score`, which only
    this module's own weighted vote computes (see module docstring).
    """

    content_hash: str
    target_file: str
    template_path: Optional[str]
    kind: str
    title: str
    rationale: str
    proposed_body: str
    target_section: Optional[str]
    source_lines: Tuple[str, ...]
    contributing_projects: Tuple[str, ...]
    contributing_paths: Tuple[str, ...]
    evidence_score: float


@dataclass(frozen=True)
class _Contribution:
    project_name: str
    line: str
    template_path: Optional[str]


def _parse_heading_line(line: str) -> Heading:
    """Parse a `"#"*level + " " + title` line, the exact shape `collect` formats."""
    stripped = line.strip()
    level = len(stripped) - len(stripped.lstrip("#"))
    title = stripped[level:].strip()
    return Heading(level=max(level, 1), title=title)


def _format_heading(heading: Heading) -> str:
    return f"{'#' * heading.level} {heading.title}"


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _project_file_text(
    project_path: str, target_file: str, project_text: Optional[ProjectTextFn]
) -> Optional[str]:
    if project_text is not None:
        return project_text(project_path, target_file)
    return _read_text(Path(project_path) / target_file)


def _template_file_text(template_path: Optional[str]) -> Optional[str]:
    if not template_path:
        return None
    return _read_text(Path(template_path))


def _find_heading_index(candidates: Sequence[Heading], target: Heading) -> Optional[int]:
    wanted = normalize_heading(target.title)
    for index, heading in enumerate(candidates):
        if heading.level == target.level and normalize_heading(heading.title) == wanted:
            return index
    return None


def _match_template_heading(
    heading: Heading, template_headings: Sequence[Heading]
) -> Optional[Heading]:
    for template_heading in template_headings:
        if heading_matches(template_heading, heading):
            return template_heading
    return None


def _resolve_anchor(
    contributions: Mapping[str, _Contribution],
    weight_by_path: Mapping[str, float],
    target: Heading,
    target_file: str,
    project_text: Optional[ProjectTextFn],
) -> Optional[str]:
    """The anchor heading most (weighted) contributors place `target` directly after."""
    template_path = next((c.template_path for c in contributions.values() if c.template_path), None)
    template_text = _template_file_text(template_path)
    template_headings = headings(template_text) if template_text is not None else []
    template_order = {normalize_heading(h.title): i for i, h in enumerate(template_headings)}

    votes: Dict[str, float] = {}
    for project_path, contribution in contributions.items():
        text = _project_file_text(project_path, target_file, project_text)
        if text is None:
            continue
        project_headings = headings(text)
        index = _find_heading_index(project_headings, target)
        if index is None:
            continue

        anchor: Optional[Heading] = None
        for heading in reversed(project_headings[:index]):
            match = _match_template_heading(heading, template_headings)
            if match is not None:
                anchor = match
                break
        if anchor is None:
            continue
        votes[anchor.title] = votes.get(anchor.title, 0.0) + weight_by_path.get(project_path, 0.0)

    if not votes:
        return None

    ranked = sorted(
        votes.items(),
        key=lambda item: (
            -item[1],
            template_order.get(normalize_heading(item[0]), len(template_headings)),
        ),
    )
    return ranked[0][0]


def _project_weight(
    project_path: str,
    line: str,
    target_file: str,
    weights: Mapping[str, float],
    drift: Optional[DriftLookup],
) -> float:
    base = float(weights.get(project_path, 0.0))
    if drift is None:
        return base
    corroborated = drift.reports(project_path, target_file, [line])
    return base * drift_factor(corroborated)


def _build_proposal(
    key: GroupKey,
    contributions: Dict[str, _Contribution],
    weights: Mapping[str, float],
    drift: Optional[DriftLookup],
    project_text: Optional[ProjectTextFn],
) -> StructureProposal:
    target_file, op, _level, _normalized = key

    # The canonical wording is the first-seen contributor's exact text (deterministic:
    # `contributions` preserves the order `propose` walked the records in).
    first = next(iter(contributions.values()))
    heading = _parse_heading_line(first.line)
    body = _format_heading(heading)

    weight_by_path = {
        path: _project_weight(path, contribution.line, target_file, weights, drift)
        for path, contribution in contributions.items()
    }
    evidence_score = sum(weight_by_path.values())

    contributor_count = len(contributions)
    template_path = first.template_path

    if op == ADD:
        kind = KIND_ADD_HEADING
        title = f'Add "{body}" to {target_file}'
        rationale = (
            f"{contributor_count} projects independently added this heading to {target_file}."
        )
        target_section = _resolve_anchor(
            contributions, weight_by_path, heading, target_file, project_text
        )
    else:
        kind = KIND_REMOVE_HEADING
        title = f'Remove "{body}" from {target_file}'
        rationale = f"{contributor_count} projects no longer carry this heading in {target_file}."
        target_section = heading.title

    contributing_paths = tuple(contributions.keys())
    contributing_projects = tuple(c.project_name for c in contributions.values())

    return StructureProposal(
        content_hash=content_hash(target_file, body, kind),
        target_file=target_file,
        template_path=template_path,
        kind=kind,
        title=title,
        rationale=rationale,
        proposed_body=body,
        target_section=target_section,
        source_lines=(body,),
        contributing_projects=contributing_projects,
        contributing_paths=contributing_paths,
        evidence_score=evidence_score,
    )


def propose(
    records: Sequence[EvidenceRecord],
    weights: Mapping[str, float],
    drift: Optional[DriftLookup] = None,
    min_evidence: int = DEFAULT_MIN_STRUCTURE_EVIDENCE,
    project_text: Optional[ProjectTextFn] = None,
) -> List[StructureProposal]:
    """Turn structural evidence into gated, locally-scored heading proposals.

    `records` need not be pre-filtered to `kind == "structure"`; anything else is
    skipped defensively, the same posture `synth.bundle_evidence` takes.
    """
    groups: Dict[GroupKey, Dict[str, _Contribution]] = {}

    for record in records:
        if record.kind != "structure":
            continue
        for line in record.added_lines:
            heading = _parse_heading_line(line)
            key: GroupKey = (
                record.target_file,
                ADD,
                heading.level,
                normalize_heading(heading.title),
            )
            bucket = groups.setdefault(key, {})
            bucket.setdefault(
                record.project_path,
                _Contribution(
                    project_name=record.project_name,
                    line=line,
                    template_path=record.template_path,
                ),
            )
        for line in record.removed_lines:
            heading = _parse_heading_line(line)
            key = (
                record.target_file,
                REMOVE,
                heading.level,
                normalize_heading(heading.title),
            )
            bucket = groups.setdefault(key, {})
            bucket.setdefault(
                record.project_path,
                _Contribution(
                    project_name=record.project_name,
                    line=line,
                    template_path=record.template_path,
                ),
            )

    proposals = [
        _build_proposal(key, contributions, weights, drift, project_text)
        for key, contributions in groups.items()
        if len(contributions) >= min_evidence
    ]
    proposals.sort(key=lambda p: (-p.evidence_score, p.target_file, p.kind, p.title))
    return proposals
