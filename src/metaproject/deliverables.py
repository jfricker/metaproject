"""The single declaration of deliverable classes (spec.md R-CLS-1).

Every file (or directory) `metaproject` scaffolds, reviews, or learns from belongs to
exactly one of four classes, declared once here rather than re-decided by each caller:

- **governance** — `AGENTS.md`, `CLAUDE.md`, `README.md`, `.gitignore`. Rendered and
  diffed in full; offered for both Update and Deploy.
- **working** — `intent.md`, `spec.md`, `design.md`, `plan.md`, `STATE.md`,
  `ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`, `docs/VERIFIED-FACTS.md`. Checked for
  heading structure only, never diffed body-for-body, and never offered for Update.
- **on-demand** — `HANDOFF.md`. Never scaffolded by `new` and never reported missing by
  `review`; created only when asked for by name (`backfill HANDOFF.md`).
- **directory** — `docs`, `docs/archive`. A presence check, nothing more.

`review.py`, `scaffold.py`, `config.py` and `learn/` all read this module rather than
import it from one another, so `learn` in particular never has to import `review` just
for a constant.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class DeliverableClass(Enum):
    """The four classes a deliverable can belong to. See module docstring."""

    GOVERNANCE = "governance"
    WORKING = "working"
    ON_DEMAND = "on_demand"
    DIRECTORY = "directory"


@dataclass(frozen=True)
class Deliverable:
    """One declared deliverable: its project-relative path and its class."""

    path: str
    cls: DeliverableClass


DELIVERABLES: Tuple[Deliverable, ...] = (
    # governance
    Deliverable("AGENTS.md", DeliverableClass.GOVERNANCE),
    Deliverable("CLAUDE.md", DeliverableClass.GOVERNANCE),
    Deliverable("README.md", DeliverableClass.GOVERNANCE),
    Deliverable(".gitignore", DeliverableClass.GOVERNANCE),
    # working
    Deliverable("intent.md", DeliverableClass.WORKING),
    Deliverable("spec.md", DeliverableClass.WORKING),
    Deliverable("design.md", DeliverableClass.WORKING),
    Deliverable("plan.md", DeliverableClass.WORKING),
    Deliverable("STATE.md", DeliverableClass.WORKING),
    Deliverable("ARCHITECTURE.md", DeliverableClass.WORKING),
    Deliverable("docs/DESIGN-INVARIANTS.md", DeliverableClass.WORKING),
    Deliverable("docs/VERIFIED-FACTS.md", DeliverableClass.WORKING),
    # on-demand
    Deliverable("HANDOFF.md", DeliverableClass.ON_DEMAND),
    # directory
    Deliverable("docs", DeliverableClass.DIRECTORY),
    Deliverable("docs/archive", DeliverableClass.DIRECTORY),
)

_BY_PATH = {d.path: d for d in DELIVERABLES}


def classify(path: str) -> Optional[DeliverableClass]:
    """The class declared for `path`, or None if it isn't a declared deliverable."""
    entry = _BY_PATH.get(path)
    return entry.cls if entry is not None else None


def scaffolded() -> Tuple[str, ...]:
    """Every declared path except on-demand ones — what `new` and `backfill` create."""
    return tuple(d.path for d in DELIVERABLES if d.cls is not DeliverableClass.ON_DEMAND)


def learn_targets() -> Tuple[str, ...]:
    """Governance and working paths — `learn`'s default targets (spec.md R-LRN-3)."""
    return tuple(
        d.path
        for d in DELIVERABLES
        if d.cls in (DeliverableClass.GOVERNANCE, DeliverableClass.WORKING)
    )
