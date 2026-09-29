"""The single declaration of deliverable classes (spec.md R-CLS-1).

Every file (or directory) `metaproject` scaffolds, reviews, or learns from belongs to
exactly one of four classes, declared once here rather than re-decided by each caller:

- **governance** — `AGENTS.md`, `CLAUDE.md`, `README.md`, `.gitignore`. Rendered and
  diffed in full; offered for both Update and Deploy.
- **working** — `docs/INTENT.md`, `docs/SPEC.md`, `docs/TECH-DESIGN.md`, `docs/PLAN.md`,
  `docs/STATE.md`, `docs/ARCHITECTURE.md`, `docs/DESIGN-INVARIANTS.md`,
  `docs/VERIFIED-FACTS.md`. Checked for heading structure only, never diffed
  body-for-body, and never offered for Update.
- **on-demand** — `docs/HANDOFF.md`. Never scaffolded by `new` and never reported missing
  by `review`; created only when asked for by name (`backfill HANDOFF.md`).
- **directory** — `docs`, `docs/archive`. A presence check, nothing more.

`review.py`, `scaffold.py`, `config.py` and `learn/` all read this module rather than
import it from one another, so `learn` in particular never has to import `review` just
for a constant.
"""

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Tuple


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
    Deliverable("docs/INTENT.md", DeliverableClass.WORKING),
    Deliverable("docs/SPEC.md", DeliverableClass.WORKING),
    Deliverable("docs/TECH-DESIGN.md", DeliverableClass.WORKING),
    Deliverable("docs/PLAN.md", DeliverableClass.WORKING),
    Deliverable("docs/STATE.md", DeliverableClass.WORKING),
    Deliverable("docs/ARCHITECTURE.md", DeliverableClass.WORKING),
    Deliverable("docs/DESIGN-INVARIANTS.md", DeliverableClass.WORKING),
    Deliverable("docs/VERIFIED-FACTS.md", DeliverableClass.WORKING),
    # on-demand
    Deliverable("docs/HANDOFF.md", DeliverableClass.ON_DEMAND),
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


# Top-level directories that hold agent skills. Never a deliverable, never learn evidence.
SKILL_ROOTS: Tuple[str, ...] = (".agents", ".claude")


# Old root-level name → declared path, for every relocated deliverable (R-DOC-0).
LEGACY_NAMES: Mapping[str, str] = {
    "intent.md": "docs/INTENT.md",
    "spec.md": "docs/SPEC.md",
    "design.md": "docs/TECH-DESIGN.md",
    "plan.md": "docs/PLAN.md",
    "STATE.md": "docs/STATE.md",
    "HANDOFF.md": "docs/HANDOFF.md",
    "ARCHITECTURE.md": "docs/ARCHITECTURE.md",
}

_OLD_NAME_FOR = {new: old for old, new in LEGACY_NAMES.items()}


def canonical_path(name: str) -> str:
    """The declared path a name refers to, matched case-insensitively (R-DOC-4).

    A declared path (`docs/INTENT.md`), the basename of a declared *file*
    (`INTENT.md`), or a legacy name (`intent.md`, `design.md`) all resolve to the
    declared path. Anything else is returned unchanged, so `backfill` still accepts any
    path the template store has a template for.
    """
    posix = PurePosixPath(name.strip()).as_posix()
    folded = posix.casefold()
    for d in DELIVERABLES:
        if d.path.casefold() == folded:
            return d.path
    for old, new in LEGACY_NAMES.items():
        if old.casefold() == folded:
            return new
    for d in DELIVERABLES:
        if d.cls is DeliverableClass.DIRECTORY:
            continue
        if PurePosixPath(d.path).name.casefold() == folded:
            return d.path
    return posix


def exact_exists(path: Path) -> bool:
    """Does `path` exist under exactly this name?

    `Path.exists()` is case-insensitive on APFS, so it would call `docs/INTENT.md`
    present when only `docs/intent.md` is (R-NFR-6). This compares the final component
    against the parent's actual directory entries.
    """
    path = Path(path)
    try:
        return path.name in os.listdir(path.parent)
    except OSError:
        return False


def legacy_candidates(root: Path, new: str, template_suffix: bool = False) -> List[str]:
    """Every legacy copy of one relocated document present under `root`, in move order.

    Candidates are the root under the old name, the root under the new name, and
    `docs/` under the old name; the declared path itself is never one. With
    `template_suffix` the same rule is applied to a template store (`intent.template.md`,
    `docs.template/intent.template.md`). Presence is exact-name (`exact_exists`).
    """
    old = _OLD_NAME_FOR[new]
    names = [old, PurePosixPath(new).name, f"docs/{old}"]
    if template_suffix:
        names = [template_path(name) for name in names]
        new = template_path(new)
    root = Path(root)
    return [
        rel
        for rel in dict.fromkeys(names)
        if rel != new and exact_exists(root / rel) and (root / rel).is_file()
    ]


def template_path(path: str) -> str:
    """The template-store path that renders to project path `path`.

    `docs/INTENT.md` → `docs.template/INTENT.template.md`; the inverse of
    `templates.transform_template_name` applied per component.
    """
    parts = PurePosixPath(path).parts
    dirs = [f"{part}.template" for part in parts[:-1]]
    stem, dot, suffix = parts[-1].rpartition(".")
    leaf = f"{stem}.template.{suffix}" if dot and stem else f"{parts[-1]}.template"
    return PurePosixPath(*dirs, leaf).as_posix()


def legacy_locations(project_dir: Path) -> Dict[str, str]:
    """Declared path → the legacy file actually present, for unmigrated documents.

    A relocated document is legacy when it is absent at its exact declared path and
    present at the root (under its old or new name) or in `docs/` under its old name.
    """
    root = Path(project_dir)
    found: Dict[str, str] = {}
    for new in LEGACY_NAMES.values():
        if exact_exists(root / new):
            continue
        candidates = legacy_candidates(root, new)
        if candidates:
            found[new] = candidates[0]
    return found
