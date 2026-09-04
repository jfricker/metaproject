"""Corroboration scoring for the `learn` pipeline (spec.md §5.4.2).

Candidates are **ranked, not gated**. A line seen in one project still reaches the
review queue; it simply sits below one that eleven projects agree on. Three signals
combine, and all three are deterministic — no model is involved:

*Frequency* is the number of **distinct** contributing projects. A line repeated a
thousand times inside one generated file is one project's opinion, not a thousand.

*Activity* is the project's `universe.db` classification, mapped through
`learn.activity_weights` (spec.md §4.2). `Active Now` counts fully; `Ancient` and
`Archived` count fractionally. This is what makes a live convention outweigh a
convention abandoned three years ago.

*Recency* modulates **within** an activity class rather than competing with it. It is a
bounded bonus (at most `RECENCY_BONUS` of the activity weight, decaying by half every
`RECENCY_HALF_LIFE_DAYS`), so a freshly-touched `Ancient` project can never outweigh a
stale `Active Now` one. Classification is already coarsely recency-derived; letting
recency also scale freely would double-count it.

The score accumulates: `evidence_score` is the plain sum of per-project weights, so the
number is always explainable by pointing at the provenance list. That also means
fractional weights mean what they say — ten `Archived` projects (0.1 each) carry about
as much weight as one `Active Now` project, which is the intent of "fractionally".
"""

import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from metaproject.config import DEFAULT_ACTIVITY_WEIGHTS, Config
from metaproject.learn.collect import EvidenceRecord
from metaproject.universe import resolve_project_timestamp

# Weight for a project whose classification is unknown or unrecognized. `Idle` is the
# midpoint of the configured table: an unclassified project is neither trusted like a
# live one nor discounted like an abandoned one.
DEFAULT_ACTIVITY_WEIGHT = DEFAULT_ACTIVITY_WEIGHTS["Idle"]

# Recency decays by half every this many days.
RECENCY_HALF_LIFE_DAYS = 30.0

# The most recency can add, as a fraction of the activity weight. Bounded on purpose:
# see the module docstring.
RECENCY_BONUS = 0.5


@dataclass(frozen=True)
class ProjectWeight:
    """One project's contribution to one candidate, with the arithmetic left visible."""

    project_name: str
    project_path: str
    classification: Optional[str]
    excerpt: str
    activity: float
    recency: float
    age_days: float
    weight: float


@dataclass(frozen=True)
class Candidate:
    """A corroboration cluster: one piece of content, and every project that shows it.

    This is the pre-synthesis unit. It exists so that frequency, recency, and activity
    can be measured deterministically before a model ever sees the evidence, and so a
    proposal's score can be recomputed from the ledger without re-running the model.
    """

    key: str
    target_file: str
    kind: str
    content: str
    template_path: Optional[str]
    contributions: Tuple[ProjectWeight, ...] = field(default=())

    @property
    def evidence_count(self) -> int:
        """Distinct contributing projects (spec.md §5.4.8 `evidence_count`)."""
        return len(self.contributions)

    @property
    def evidence_score(self) -> float:
        """Accumulated, activity-weighted, recency-modulated score."""
        return sum(c.weight for c in self.contributions)

    @property
    def project_paths(self) -> Tuple[str, ...]:
        """Absolute paths of the contributing projects, for `learn show`."""
        return tuple(c.project_path for c in self.contributions)


def activity_weight(
    classification: Optional[str],
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """Map a `universe` classification to its configured weight (spec.md §4.2)."""
    table = weights if weights is not None else DEFAULT_ACTIVITY_WEIGHTS
    if classification is None:
        return float(table.get("Idle", DEFAULT_ACTIVITY_WEIGHT))
    return float(table.get(classification, table.get("Idle", DEFAULT_ACTIVITY_WEIGHT)))


def recency_factor(age_days: float, half_life_days: float = RECENCY_HALF_LIFE_DAYS) -> float:
    """Decay in `(0, 1]`: 1.0 for a change made today, 0.5 after one half-life.

    A negative age (a file stamped in the future) clamps to 1.0 rather than exceeding
    it, so a bad mtime cannot buy rank.
    """
    if half_life_days <= 0:
        return 1.0
    age = max(0.0, float(age_days))
    return float(math.pow(0.5, age / half_life_days))


def weigh_project(
    classification: Optional[str],
    age_days: float,
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """Combine activity and recency into one project's contribution weight."""
    activity = activity_weight(classification, weights=weights)
    return activity * (1.0 + RECENCY_BONUS * recency_factor(age_days))


def project_age_days(project_path: Path | str, now: Optional[float] = None) -> float:
    """Days since the project was last modified, resolved the way `universe` does."""
    reference = time.time() if now is None else now
    try:
        _iso, timestamp = resolve_project_timestamp(Path(project_path))
    except OSError:
        return 0.0
    return max(0.0, (reference - timestamp) / 86400.0)


def candidate_key(line: str) -> str:
    """Identity of a candidate line, insensitive to indentation and internal spacing.

    Without this, `lattice`'s CRLF-and-trailing-whitespace copy of a line and
    `cipher`'s indented copy would each look like a separate one-project candidate
    instead of corroborating the same convention (acceptance case C23).
    """
    return " ".join(line.split())


def group_candidates(
    records: Sequence[EvidenceRecord],
    config: Optional[Config] = None,
    weights: Optional[Dict[str, float]] = None,
    ages: Optional[Dict[str, float]] = None,
    now: Optional[float] = None,
) -> List[Candidate]:
    """Cluster evidence into ranked candidates by target file and normalized content.

    `ages` maps a project path to its age in days; anything absent is resolved from the
    filesystem. Passing it keeps a test's arithmetic independent of the wall clock.
    """
    if weights is None:
        weights = config.learn.activity_weights if config is not None else None

    resolved_ages: Dict[str, float] = dict(ages or {})
    # (target_file, key) -> {project_path: ProjectWeight}
    clusters: Dict[Tuple[str, str], Dict[str, ProjectWeight]] = {}
    meta: Dict[Tuple[str, str], Tuple[str, str, Optional[str]]] = {}

    for record in records:
        for line in record.added_lines:
            key = candidate_key(line)
            if not key:
                continue
            group = (record.target_file, key)
            if group not in meta:
                meta[group] = (record.kind, line.strip(), record.template_path)
                clusters[group] = {}
            if record.project_path in clusters[group]:
                continue

            path = record.project_path
            if path not in resolved_ages:
                resolved_ages[path] = project_age_days(path, now=now)
            age = resolved_ages[path]
            activity = activity_weight(record.classification, weights=weights)
            clusters[group][path] = ProjectWeight(
                project_name=record.project_name,
                project_path=path,
                classification=record.classification,
                excerpt=line.strip(),
                activity=activity,
                recency=recency_factor(age),
                age_days=age,
                weight=weigh_project(record.classification, age, weights=weights),
            )

    candidates = [
        Candidate(
            key=key,
            target_file=target_file,
            kind=meta[(target_file, key)][0],
            content=meta[(target_file, key)][1],
            template_path=meta[(target_file, key)][2],
            contributions=tuple(
                sorted(contributors.values(), key=lambda c: (-c.weight, c.project_path))
            ),
        )
        for (target_file, key), contributors in clusters.items()
    ]
    return rank_candidates(candidates)


def rank_candidates(candidates: Sequence[Candidate]) -> List[Candidate]:
    """Order the queue by score descending, with deterministic tie-breaking.

    Ties fall back to evidence count, then target file, then the candidate key, so the
    same evidence always produces the same queue regardless of walk order.
    """
    return sorted(
        candidates,
        key=lambda c: (-c.evidence_score, -c.evidence_count, c.target_file, c.key),
    )


def order_queue(rows: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    """Order stored proposal rows the way `rank_candidates` orders in-memory ones.

    `learn list`, `learn review`, and the TUI must agree on ordering; they agree by
    calling this rather than by each writing an ORDER BY.
    """

    def sort_key(row: Dict[str, object]):
        return (
            -float(row.get("evidence_score") or 0.0),
            -int(row.get("evidence_count") or 0),
            str(row.get("target_file") or ""),
            int(row.get("id") or 0),
        )

    return sorted(rows, key=sort_key)
