"""The proposal ledger (spec.md §5.4.7, §5.4.8). The only module that touches SQLite.

`learn` is worth using only if it remembers. A rejection that evaporates on the next
scan turns the queue into the same nagging list every week, which is precisely the
failure the legacy harvester had. So three things persist here:

* **Proposals**, identified by `content_hash` and upserted on it, so a rescan updates a
  candidate rather than duplicating it.
* **Evidence**, one row per contributing project with its weight, replaced wholesale on
  every scan because evidence describes the workspace *now*.
* **Runs**, the audit trail of what a scan looked at and how it ended.

**Rejection is "not yet", not "never"** (spec.md §5.4.7). Rejecting records the score at
the time of rejection; the candidate stays suppressed until its evidence *strictly*
exceeds `rejected_score * learn.resurface_factor`. `--forget` deletes the record, so the
next scan meets the candidate as if for the first time.

**Hashing (plan.md risk R3).** Two hash domains are offered, both over *normalized*
content and never over raw model prose:

* `content_hash(target_file, body, kind)` — the normalized proposal body. Primary
  identity once Phase 3 exists, and what the schema's `content_hash` column stores.
* `evidence_hash(target_file, excerpts, kind)` — the normalized, deduplicated, sorted
  evidence set. Wording-independent by construction, and stable as projects join a
  candidate (the set is of distinct excerpts, not of contributors), so it is the
  fallback R3 names if generated bodies prove too unstable to hash.

Both normalize through `normalize_for_hash`, so indentation, blank lines, and CRLF
churn cannot mint a new identity and resurface a suppressed candidate as "new".
"""

import datetime
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

import sqlite_utils

from metaproject.learn.collect import normalize_text

DEFAULT_RESURFACE_FACTOR = 2.0

STATUS_PENDING = "pending"
STATUS_APPLIED = "applied"
STATUS_REJECTED = "rejected"

RUN_OK = "ok"
RUN_PARTIAL = "partial"
RUN_FAILED = "failed"

_HASH_VERSION = "1"


@dataclass(frozen=True)
class ProposalDraft:
    """A proposal as a scan produces it, before it meets the ledger."""

    content_hash: str
    target_file: str
    kind: str
    title: str
    rationale: str
    proposed_body: str
    evidence_count: int
    evidence_score: float
    template_path: Optional[str] = None
    target_section: Optional[str] = None


@dataclass(frozen=True)
class EvidenceDraft:
    """One project's contribution to a proposal, as stored in `learn_evidence`."""

    project_path: str
    excerpt: str
    weight: float
    project_id: Optional[int] = None


def _now() -> str:
    """UTC ISO 8601, the same shape `universe` writes."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def normalize_for_hash(text: str) -> str:
    """Reduce content to the form its identity is computed over.

    Line endings, indentation, internal whitespace runs, and blank lines are all
    discarded. Case and word choice are not: a differently-worded proposal genuinely is
    a different proposal.
    """
    lines = [" ".join(line.split()) for line in normalize_text(text or "").split("\n")]
    return "\n".join(line for line in lines if line)


def content_hash(target_file: str, body: str, kind: str = "edit") -> str:
    """Stable identity for a proposal body within a target file."""
    payload = "\0".join([_HASH_VERSION, "body", kind, target_file, normalize_for_hash(body)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def evidence_hash(target_file: str, excerpts: Iterable[str], kind: str = "edit") -> str:
    """Wording-independent identity derived from the evidence set alone (R3 fallback)."""
    normalized = sorted({normalize_for_hash(excerpt) for excerpt in excerpts} - {""})
    payload = "\0".join([_HASH_VERSION, "evidence", kind, target_file, "\n".join(normalized)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def should_resurface(
    rejected_score: Optional[float],
    evidence_score: float,
    resurface_factor: float = DEFAULT_RESURFACE_FACTOR,
) -> bool:
    """Has the evidence strengthened enough to overturn a rejection?

    The comparison is strict: evidence merely equal to the bar is not stronger.
    """
    bar = max(0.0, float(rejected_score or 0.0)) * float(resurface_factor)
    return float(evidence_score) > bar


def _row(db: sqlite_utils.Database, sql: str, params: Sequence[Any]) -> Optional[Dict[str, Any]]:
    """Run a query and return the first row as a dict, or None."""
    cursor = db.conn.cursor()
    cursor.execute(sql, list(params))
    fetched = cursor.fetchone()
    if fetched is None:
        return None
    columns = [c[0] for c in cursor.description]
    return dict(zip(columns, fetched))


def _rows(db: sqlite_utils.Database, sql: str, params: Sequence[Any]) -> List[Dict[str, Any]]:
    """Run a query and return every row as a dict."""
    cursor = db.conn.cursor()
    cursor.execute(sql, list(params))
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_proposal(db: sqlite_utils.Database, proposal_id: int) -> Optional[Dict[str, Any]]:
    """Fetch one proposal by id."""
    return _row(db, "SELECT * FROM learn_proposals WHERE id = ?", [proposal_id])


def get_proposal_by_hash(db: sqlite_utils.Database, proposal_hash: str) -> Optional[Dict[str, Any]]:
    """Fetch one proposal by content hash. Suppression lookups go through here."""
    return _row(db, "SELECT * FROM learn_proposals WHERE content_hash = ?", [proposal_hash])


def get_evidence(db: sqlite_utils.Database, proposal_id: int) -> List[Dict[str, Any]]:
    """Every contributing project for a proposal, heaviest first."""
    return _rows(
        db,
        "SELECT * FROM learn_evidence WHERE proposal_id = ? ORDER BY weight DESC, project_path",
        [proposal_id],
    )


def list_proposals(
    db: sqlite_utils.Database,
    status: Optional[str] = None,
    target_file: Optional[str] = None,
    min_score: Optional[float] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """The review queue: score descending, then evidence count, then id.

    Backs `learn list`, `learn review --min-score`, and the TUI alike, so the three can
    never disagree about what is next.
    """
    clauses: List[str] = []
    params: List[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if target_file:
        clauses.append("target_file = ?")
        params.append(target_file)
    if min_score is not None:
        clauses.append("evidence_score >= ?")
        params.append(float(min_score))

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        f"SELECT * FROM learn_proposals {where} "
        "ORDER BY evidence_score DESC, evidence_count DESC, id ASC"
    )
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    return _rows(db, sql, params)


def is_suppressed(
    db: sqlite_utils.Database,
    proposal_hash: str,
    evidence_score: float,
    resurface_factor: float = DEFAULT_RESURFACE_FACTOR,
) -> bool:
    """Would this candidate be withheld from the queue at this score?

    True only for a rejected hash whose evidence has not yet cleared the resurfacing
    bar. An unknown hash is never suppressed, and neither is an applied one.
    """
    row = get_proposal_by_hash(db, proposal_hash)
    if row is None or row["status"] != STATUS_REJECTED:
        return False
    return not should_resurface(row["rejected_score"], evidence_score, resurface_factor)


def replace_evidence(
    db: sqlite_utils.Database,
    proposal_id: int,
    evidence: Sequence[EvidenceDraft],
) -> None:
    """Swap in the current scan's provenance, discarding the previous scan's."""
    db.conn.execute("DELETE FROM learn_evidence WHERE proposal_id = ?", [proposal_id])
    for item in evidence:
        db.conn.execute(
            "INSERT INTO learn_evidence (proposal_id, project_id, project_path, excerpt, weight) "
            "VALUES (?, ?, ?, ?, ?)",
            [proposal_id, item.project_id, item.project_path, item.excerpt, float(item.weight)],
        )
    db.conn.commit()


def upsert_proposal(
    db: sqlite_utils.Database,
    draft: ProposalDraft,
    evidence: Optional[Sequence[EvidenceDraft]] = None,
    resurface_factor: float = DEFAULT_RESURFACE_FACTOR,
) -> int:
    """Insert or update a proposal by `content_hash`, and return its id.

    Status is the ledger's, not the scan's. A rescan refreshes the content, the counts,
    and the score, but it can neither reopen an applied proposal nor overturn a
    rejection — except by producing evidence strong enough to clear the resurfacing bar,
    which is the one path back to `pending`.
    """
    existing = get_proposal_by_hash(db, draft.content_hash)
    timestamp = _now()

    if existing is None:
        cursor = db.conn.cursor()
        cursor.execute(
            """
            INSERT INTO learn_proposals (
                content_hash, target_file, template_path, kind, title, rationale,
                proposed_body, edited_body, target_section, evidence_count,
                evidence_score, status, rejected_score, created_at, updated_at,
                applied_commit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, NULL, ?, ?, NULL)
            """,
            [
                draft.content_hash,
                draft.target_file,
                draft.template_path,
                draft.kind,
                draft.title,
                draft.rationale,
                draft.proposed_body,
                draft.target_section,
                int(draft.evidence_count),
                float(draft.evidence_score),
                STATUS_PENDING,
                timestamp,
                timestamp,
            ],
        )
        db.conn.commit()
        proposal_id = int(cursor.lastrowid)
    else:
        proposal_id = int(existing["id"])
        status = existing["status"]
        rejected_score = existing["rejected_score"]
        if status == STATUS_REJECTED and should_resurface(
            rejected_score, draft.evidence_score, resurface_factor
        ):
            status = STATUS_PENDING
            rejected_score = None

        db.conn.execute(
            """
            UPDATE learn_proposals SET
                target_file = ?, template_path = ?, kind = ?, title = ?, rationale = ?,
                proposed_body = ?, target_section = ?, evidence_count = ?,
                evidence_score = ?, status = ?, rejected_score = ?, updated_at = ?
            WHERE id = ?
            """,
            [
                draft.target_file,
                draft.template_path,
                draft.kind,
                draft.title,
                draft.rationale,
                draft.proposed_body,
                draft.target_section,
                int(draft.evidence_count),
                float(draft.evidence_score),
                status,
                rejected_score,
                timestamp,
                proposal_id,
            ],
        )
        db.conn.commit()

    if evidence is not None:
        replace_evidence(db, proposal_id, evidence)
    return proposal_id


def reject_proposal(
    db: sqlite_utils.Database,
    proposal_id: int,
    forget: bool = False,
) -> bool:
    """Suppress a proposal, or with `forget` erase it. False if there was nothing to do.

    Rejecting stamps `rejected_score` with the current evidence score: that number is
    the bar the candidate must later clear to come back.
    """
    existing = get_proposal(db, proposal_id)
    if existing is None:
        return False

    if forget:
        db.conn.execute("DELETE FROM learn_evidence WHERE proposal_id = ?", [proposal_id])
        db.conn.execute("DELETE FROM learn_proposals WHERE id = ?", [proposal_id])
        db.conn.commit()
        return True

    db.conn.execute(
        "UPDATE learn_proposals SET status = ?, rejected_score = ?, updated_at = ? WHERE id = ?",
        [STATUS_REJECTED, float(existing["evidence_score"] or 0.0), _now(), proposal_id],
    )
    db.conn.commit()
    return True


def forget_proposal_by_hash(db: sqlite_utils.Database, proposal_hash: str) -> bool:
    """`learn reject --forget` addressed by hash rather than by id."""
    existing = get_proposal_by_hash(db, proposal_hash)
    if existing is None:
        return False
    return reject_proposal(db, int(existing["id"]), forget=True)


def mark_applied(
    db: sqlite_utils.Database,
    proposal_id: int,
    commit: Optional[str] = None,
    edited_body: Optional[str] = None,
) -> bool:
    """Record that a proposal was written into the template store.

    `edited_body` is the operator's text and takes precedence over `proposed_body` at
    apply time (spec.md §5.4.5), so it is stored separately and never overwritten by a
    later scan.
    """
    if get_proposal(db, proposal_id) is None:
        return False
    if edited_body is None:
        db.conn.execute(
            "UPDATE learn_proposals SET status = ?, applied_commit = ?, updated_at = ? "
            "WHERE id = ?",
            [STATUS_APPLIED, commit, _now(), proposal_id],
        )
    else:
        db.conn.execute(
            "UPDATE learn_proposals SET status = ?, applied_commit = ?, edited_body = ?, "
            "updated_at = ? WHERE id = ?",
            [STATUS_APPLIED, commit, edited_body, _now(), proposal_id],
        )
    db.conn.commit()
    return True


def set_edited_body(db: sqlite_utils.Database, proposal_id: int, edited_body: str) -> bool:
    """Store the operator's edit without changing status (`learn edit` before apply)."""
    if get_proposal(db, proposal_id) is None:
        return False
    db.conn.execute(
        "UPDATE learn_proposals SET edited_body = ?, updated_at = ? WHERE id = ?",
        [edited_body, _now(), proposal_id],
    )
    db.conn.commit()
    return True


def start_run(
    db: sqlite_utils.Database,
    root: str,
    model: Optional[str] = None,
) -> int:
    """Open a `learn_runs` row. Closed by `finish_run`, even on failure."""
    cursor = db.conn.cursor()
    cursor.execute(
        "INSERT INTO learn_runs (started_at, finished_at, root, projects_scanned, "
        "files_scanned, model, proposals_created, status) "
        "VALUES (?, NULL, ?, 0, 0, ?, 0, NULL)",
        [_now(), str(root), model],
    )
    db.conn.commit()
    return int(cursor.lastrowid)


def finish_run(
    db: sqlite_utils.Database,
    run_id: int,
    projects_scanned: int = 0,
    files_scanned: int = 0,
    proposals_created: int = 0,
    status: str = RUN_OK,
) -> bool:
    """Close a run with its counts and outcome (`ok` | `partial` | `failed`)."""
    if get_run(db, run_id) is None:
        return False
    db.conn.execute(
        "UPDATE learn_runs SET finished_at = ?, projects_scanned = ?, files_scanned = ?, "
        "proposals_created = ?, status = ? WHERE id = ?",
        [
            _now(),
            int(projects_scanned),
            int(files_scanned),
            int(proposals_created),
            status,
            run_id,
        ],
    )
    db.conn.commit()
    return True


def get_run(db: sqlite_utils.Database, run_id: int) -> Optional[Dict[str, Any]]:
    """Fetch one run by id."""
    return _row(db, "SELECT * FROM learn_runs WHERE id = ?", [run_id])


def latest_run(db: sqlite_utils.Database) -> Optional[Dict[str, Any]]:
    """The most recently started run, or None on a database that has never scanned."""
    return _row(db, "SELECT * FROM learn_runs ORDER BY id DESC LIMIT 1", [])
