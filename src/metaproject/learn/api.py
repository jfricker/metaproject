"""The `learn` public API: `scan`, `review`, `apply_proposal`, `reject_proposal`.

`cli.py` and (from Phase 5) `tui.py` both call these and nothing below them, which is
what makes "one queue, two interfaces" true by construction rather than by discipline:
there is no TUI-only code path that can diverge from a subcommand.

`scan` runs stages 1–4 of spec.md §5.4.1 — collect, guard, synthesize, record — and
**never writes to the template store**. That separation is the primary safety property
of the whole feature (plan.md §1.3, acceptance case C14), so this module imports
nothing from `apply`: a scan cannot reach the write path even by mistake.
"""

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import sqlite_utils

from metaproject.config import Config, load_config
from metaproject.db import get_db
from metaproject.learn.collect import collect_project, iter_project_dirs
from metaproject.learn.drift import DriftSignal, collect_drift
from metaproject.learn.guard import SendManifest, confirm_send, guard_evidence
from metaproject.learn.score import drift_factor, project_age_days, weigh_project
from metaproject.learn.store import (
    RUN_FAILED,
    EvidenceDraft,
    ProposalDraft,
    list_proposals,
    upsert_proposal,
)
from metaproject.learn.store import reject_proposal as _reject_proposal
from metaproject.learn.store import start_run as _start_run
from metaproject.learn.synth import normalize_excerpt, synthesize
from metaproject.universe import resolve_project_timestamp

reject_proposal = _reject_proposal


@dataclass(frozen=True)
class ScanResult:
    """What one scan looked at, what it recorded, and how it ended."""

    run_id: int
    root: str
    projects_scanned: int
    files_scanned: int
    created: int
    proposal_ids: Tuple[int, ...]
    status: str
    skipped: Tuple[str, ...]
    manifest: Optional[SendManifest]
    aborted: bool = False


def parse_since(value: Optional[str], now: Optional[float] = None) -> Optional[float]:
    """Interpret `--since` as an ISO date or a number of days, returning an epoch bound.

    Both spellings are accepted because both are natural at a prompt: `--since
    2026-01-01` and `--since 30` (the last thirty days) mean the same kind of thing.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    reference = datetime.datetime.now(datetime.timezone.utc).timestamp() if now is None else now
    days_text = text[:-1] if text[-1:].lower() == "d" else text
    try:
        return reference - float(days_text) * 86400.0
    except ValueError:
        pass

    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"could not read --since {value!r}; use an ISO date (2026-01-01) or a number of days"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.timestamp()


def _project_id(db: sqlite_utils.Database, project_path: str) -> Optional[int]:
    """The `universe.db` project row for a path, when the workspace has been cataloged."""
    try:
        cursor = db.conn.execute("SELECT id FROM projects WHERE path = ?", [project_path])
    except Exception:
        return None
    row = cursor.fetchone()
    return int(row[0]) if row else None


def scan(
    root: Path | str,
    templates_dir: Optional[Path | str] = None,
    db: Optional[sqlite_utils.Database] = None,
    config: Optional[Config] = None,
    targets: Optional[Sequence[str]] = None,
    depth: int = 4,
    since: Optional[str] = None,
    yes: bool = False,
    model: Optional[str] = None,
    runner: Optional[Callable[..., str]] = None,
    confirm_fn: Optional[Callable[[str], bool]] = None,
    drift: Optional[DriftSignal] = None,
) -> ScanResult:
    """Run stages 1–4: collect, guard, synthesize, record. Writes no template, ever.

    `drift` is `review`'s findings for the scanned projects (spec.md §5.4.9); it is
    gathered from `review` when not supplied. It only ever raises the weight of a
    contribution collect already found — pass `drift.EMPTY_DRIFT` to score without it.
    """
    config = config or load_config()
    templates_dir = Path(templates_dir or config.templates_dir).expanduser().resolve()
    root = Path(root).expanduser().resolve()
    if db is None:
        db = get_db(config.universe_db)

    run_id = _start_run(db, str(root), model or config.learn.model)
    cutoff = parse_since(since)

    records = []
    projects: List[Path] = []
    for project_dir in iter_project_dirs(root, max_depth=depth):
        if cutoff is not None:
            _iso, timestamp = resolve_project_timestamp(project_dir)
            if timestamp < cutoff:
                continue
        projects.append(project_dir)
        records.extend(collect_project(project_dir, templates_dir, targets=targets, config=config))

    guarded = guard_evidence(records)
    files_scanned = len({(r.project_path, r.target_file) for r in guarded.records})

    if not confirm_send(guarded.manifest, assume_yes=yes, confirm_fn=confirm_fn):
        _finish(db, run_id, len(projects), files_scanned, 0, RUN_FAILED)
        return ScanResult(
            run_id=run_id,
            root=str(root),
            projects_scanned=len(projects),
            files_scanned=files_scanned,
            created=0,
            proposal_ids=(),
            status=RUN_FAILED,
            skipped=(),
            manifest=guarded.manifest,
            aborted=True,
        )

    result = synthesize(
        guarded.records,
        config=config,
        model=model,
        runner=runner,
    )

    # `review`'s own findings, gathered after the egress gate: they are read from the
    # local filesystem and never sent anywhere, and a declined scan should do no work.
    if drift is None:
        drift = collect_drift(projects, templates_dir)

    weights = _project_weights(guarded.records, config)
    lines_by_project = _lines_by_project(guarded.records)

    proposal_ids: List[int] = []
    for proposal in result.proposals:
        evidence: List[EvidenceDraft] = []
        score = 0.0
        for path in proposal.contributing_paths:
            # `review` agreeing about this very pattern raises this project's weight;
            # it never adds a contribution, so `evidence_count` and provenance are
            # exactly what `collect` found (spec.md §5.4.9).
            corroborated = drift.reports(path, proposal.target_file, proposal.source_lines)
            weight = weights.get(path, 0.0) * drift_factor(corroborated)
            score += weight
            excerpt = "\n".join(
                line for line in proposal.source_lines if line in lines_by_project.get(path, set())
            )
            evidence.append(
                EvidenceDraft(
                    project_path=path,
                    excerpt=excerpt or "\n".join(proposal.source_lines),
                    weight=weight,
                    project_id=_project_id(db, path),
                )
            )

        draft = ProposalDraft(
            content_hash=proposal.content_hash,
            target_file=proposal.target_file,
            kind=proposal.kind,
            title=proposal.title,
            rationale=proposal.rationale,
            proposed_body=proposal.proposed_body,
            evidence_count=len(proposal.contributing_paths),
            evidence_score=score,
            template_path=proposal.template_path,
            target_section=proposal.target_section,
        )
        proposal_ids.append(
            upsert_proposal(db, draft, evidence, resurface_factor=config.learn.resurface_factor)
        )

    _finish(db, run_id, len(projects), files_scanned, len(proposal_ids), result.status)
    return ScanResult(
        run_id=run_id,
        root=str(root),
        projects_scanned=len(projects),
        files_scanned=files_scanned,
        created=len(proposal_ids),
        proposal_ids=tuple(proposal_ids),
        status=result.status,
        skipped=result.skipped,
        manifest=guarded.manifest,
    )


def _finish(
    db: sqlite_utils.Database,
    run_id: int,
    projects_scanned: int,
    files_scanned: int,
    created: int,
    status: str,
) -> None:
    """Close the run row. Imported late so `store` stays the only SQLite surface."""
    from metaproject.learn.store import finish_run

    finish_run(
        db,
        run_id,
        projects_scanned=projects_scanned,
        files_scanned=files_scanned,
        proposals_created=created,
        status=status,
    )


def _project_weights(records, config: Config) -> Dict[str, float]:
    """One contribution weight per contributing project (spec.md §5.4.2)."""
    weights: Dict[str, float] = {}
    for record in records:
        if record.project_path in weights:
            continue
        age = project_age_days(record.project_path)
        weights[record.project_path] = weigh_project(
            record.classification, age, weights=config.learn.activity_weights
        )
    return weights


def _lines_by_project(records) -> Dict[str, set]:
    """Normalized evidence lines each project actually contributed."""
    by_project: Dict[str, set] = {}
    for record in records:
        bucket = by_project.setdefault(record.project_path, set())
        for line in record.added_lines:
            key = normalize_excerpt(line)
            if key:
                bucket.add(key)
    return by_project


def review(
    db: Optional[sqlite_utils.Database] = None,
    status: Optional[str] = "pending",
    target_file: Optional[str] = None,
    min_score: Optional[float] = None,
    config: Optional[Config] = None,
) -> List[Dict[str, Any]]:
    """The review queue, score descending — what `learn list`, `review`, and the TUI read."""
    if db is None:
        config = config or load_config()
        db = get_db(config.universe_db)
    return list_proposals(db, status=status, target_file=target_file, min_score=min_score)
