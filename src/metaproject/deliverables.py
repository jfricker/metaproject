"""The single declaration of deliverable classes (spec.md R-CLS-1).

Every file (or directory) `metaproject` scaffolds, reviews, or learns from belongs to
exactly one of six classes, declared once here rather than re-decided by each caller:

- **governance** — `AGENTS.md`, `CLAUDE.md`, `README.md`, `.gitignore`. Rendered and
  diffed in full; offered for both Update and Deploy.
- **working** — `.metaproject/docs/INTENT.md`, `.metaproject/docs/SPEC.md`,
  `.metaproject/docs/TECH-DESIGN.md`, `.metaproject/docs/PLAN.md`,
  `.metaproject/docs/STATE.md`, `.metaproject/docs/ARCHITECTURE.md`,
  `.metaproject/docs/DESIGN-INVARIANTS.md`, `.metaproject/docs/VERIFIED-FACTS.md`.
  Checked for heading structure only, never diffed body-for-body, and never offered for
  Update.
- **on-demand** — `.metaproject/docs/HANDOFF.md`, `.metaproject/docs/TODO.md`. Never
  scaffolded by `new` and never reported missing by `review`; created only when asked for
  by name (`backfill HANDOFF.md`). `.metaproject/docs/TODO.md` is the operator's standing
  manual-verification list, appended by `wrapup` and never archived.
- **directory** — `.metaproject/docs`, `.metaproject/docs/archive`. A presence check,
  nothing more.
- **settings** — `.claude/settings.json`. Never rendered from the template store and
  never overwritten: metaproject *merges* its hook entries into it (`hooks.py`), keeping
  every key the operator already has. Present means "the hook script is installed and
  every metaproject hook entry is merged"; never diffed, never offered for Update, never
  learn evidence.
- **subagent** — `.claude/agents/<name>.md` for each bundled project agent. Installed and
  updated only by `subagents.py`; not in `DELIVERABLES`, so `review`, `scaffolded()` and
  `learn_targets()` never see them.

`review.py`, `scaffold.py`, `config.py` and `learn/` all read this module rather than
import it from one another, so `learn` in particular never has to import `review` just
for a constant.
"""

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Tuple

DOCS_DIR = ".metaproject/docs"

# Metaproject-owned subdirectories relocated from `docs/` to `.metaproject/docs/` by
# `doctor` (SPEC.md R-DRX-4).
MIGRATABLE_SUBDIRS: Tuple[str, ...] = ("archive", "backlog", "discovery")


class DeliverableClass(Enum):
    """The classes a deliverable can belong to. See module docstring."""

    GOVERNANCE = "governance"
    WORKING = "working"
    ON_DEMAND = "on_demand"
    DIRECTORY = "directory"
    SETTINGS = "settings"
    SUBAGENT = "subagent"


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
    Deliverable(".metaproject/docs/INTENT.md", DeliverableClass.WORKING),
    Deliverable(".metaproject/docs/SPEC.md", DeliverableClass.WORKING),
    Deliverable(".metaproject/docs/TECH-DESIGN.md", DeliverableClass.WORKING),
    Deliverable(".metaproject/docs/PLAN.md", DeliverableClass.WORKING),
    Deliverable(".metaproject/docs/STATE.md", DeliverableClass.WORKING),
    Deliverable(".metaproject/docs/ARCHITECTURE.md", DeliverableClass.WORKING),
    Deliverable(".metaproject/docs/DESIGN-INVARIANTS.md", DeliverableClass.WORKING),
    Deliverable(".metaproject/docs/VERIFIED-FACTS.md", DeliverableClass.WORKING),
    # on-demand
    Deliverable(".metaproject/docs/HANDOFF.md", DeliverableClass.ON_DEMAND),
    Deliverable(".metaproject/docs/TODO.md", DeliverableClass.ON_DEMAND),
    # directory
    Deliverable(".metaproject/docs", DeliverableClass.DIRECTORY),
    Deliverable(".metaproject/docs/archive", DeliverableClass.DIRECTORY),
    # settings (merged, never rendered)
    Deliverable(".claude/settings.json", DeliverableClass.SETTINGS),
)

_BY_PATH = {d.path: d for d in DELIVERABLES}

RELOCATED_FILES: Tuple[str, ...] = tuple(
    d.path for d in DELIVERABLES if d.cls in (DeliverableClass.WORKING, DeliverableClass.ON_DEMAND)
)


def classify(path: str) -> Optional[DeliverableClass]:
    """The class declared for `path`, or None if it isn't a declared deliverable."""
    entry = _BY_PATH.get(path)
    return entry.cls if entry is not None else None


def scaffolded() -> Tuple[str, ...]:
    """Every declared path except on-demand ones — what `new` and `backfill` create."""
    return tuple(d.path for d in DELIVERABLES if d.cls is not DeliverableClass.ON_DEMAND)


def subagent_paths() -> Tuple[str, ...]:
    """`.claude/agents/<name>.md` for every bundled project agent (class SUBAGENT)."""
    from metaproject.subagents import bundled_agents  # lazy: avoids an import cycle

    return tuple(f".claude/agents/{agent.name}.md" for agent in bundled_agents())


def learn_targets() -> Tuple[str, ...]:
    """Governance and working paths — `learn`'s default targets (spec.md R-LRN-3)."""
    return tuple(
        d.path
        for d in DELIVERABLES
        if d.cls in (DeliverableClass.GOVERNANCE, DeliverableClass.WORKING)
    )


# Top-level directories that hold agent skills. Never learn evidence; the only deliverable
# under them is the merged `.claude/settings.json`.
SKILL_ROOTS: Tuple[str, ...] = (".agents", ".claude")


# v0.8 root-level name → declared `.metaproject/docs/` path. Only these seven ever lived
# at the project root (`DESIGN-INVARIANTS.md`, `VERIFIED-FACTS.md`, and `TODO.md` were
# born in `docs/` so a project's own root `TODO.md` is never mistaken for metaproject's).
LEGACY_ROOT_NAMES: Mapping[str, str] = {
    "intent.md": ".metaproject/docs/INTENT.md",
    "spec.md": ".metaproject/docs/SPEC.md",
    "design.md": ".metaproject/docs/TECH-DESIGN.md",
    "plan.md": ".metaproject/docs/PLAN.md",
    "STATE.md": ".metaproject/docs/STATE.md",
    "HANDOFF.md": ".metaproject/docs/HANDOFF.md",
    "ARCHITECTURE.md": ".metaproject/docs/ARCHITECTURE.md",
}

_OLD_ROOT_FOR = {new: old for old, new in LEGACY_ROOT_NAMES.items()}

# Every legacy file location (v0.8 root names, v0.9 `docs/` paths, and `docs/<old>`
# lowercase names) → declared `.metaproject/docs/` path (R-LEG-1).
LEGACY_NAMES: Mapping[str, str] = {
    **LEGACY_ROOT_NAMES,
    **{f"docs/{PurePosixPath(p).name}": p for p in RELOCATED_FILES},
    "docs/intent.md": ".metaproject/docs/INTENT.md",
    "docs/spec.md": ".metaproject/docs/SPEC.md",
    "docs/design.md": ".metaproject/docs/TECH-DESIGN.md",
    "docs/plan.md": ".metaproject/docs/PLAN.md",
}

LEGACY_DIR_NAMES: Mapping[str, str] = {
    "docs": ".metaproject/docs",
    "docs/archive": ".metaproject/docs/archive",
}

LEGACY_LEARN_TARGETS: Mapping[str, str] = {
    **LEGACY_NAMES,
    "docs/": ".metaproject/docs/",
}


def canonical_path(name: str) -> str:
    """The declared path a name refers to, matched case-insensitively (R-LOC-4).

    A declared path (`.metaproject/docs/INTENT.md`), a prior `docs/` path
    (`docs/INTENT.md`, `docs/design.md`), the basename of a declared *file*
    (`INTENT.md`, `TODO.md`), or a v0.8 root name (`intent.md`, `design.md`) all resolve
    to the declared `.metaproject/docs/` path. Anything else is returned unchanged, so
    `backfill` still accepts any path the template store has a template for.
    """
    posix = PurePosixPath(name.strip()).as_posix()
    folded = posix.casefold()
    for d in DELIVERABLES:
        if d.path.casefold() == folded:
            return d.path
    for old, new in LEGACY_NAMES.items():
        if old.casefold() == folded:
            return new
    for old, new in LEGACY_DIR_NAMES.items():
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

    `Path.exists()` is case-insensitive on APFS, so it would call `.metaproject/docs/INTENT.md`
    present when only `.metaproject/docs/intent.md` is (R-NFR-1). This compares the final
    component against the parent's actual directory entries.
    """
    path = Path(path)
    try:
        return path.name in os.listdir(path.parent)
    except OSError:
        return False


def legacy_candidates(root: Path, new: str, template_suffix: bool = False) -> List[str]:
    """Every legacy copy of one relocated document present under `root`, in move order.

    Priority order: `docs/<NAME>.md` (v0.9), `docs/<old>` / `docs/<name>.md`, root `<old>`
    and `<NAME>.md` (for `LEGACY_ROOT_NAMES` only), then wrong-case copies under
    `.metaproject/docs/` (for APFS case-insensitivity). With `template_suffix=True` the
    same rule is applied to a template store. Presence is exact-name (`exact_exists`).
    """
    basename = PurePosixPath(new).name
    old_root = _OLD_ROOT_FOR.get(new)
    names: List[str] = [f"docs/{basename}"]
    if old_root is not None:
        names.append(f"docs/{old_root}")
    names.append(f"docs/{basename.lower()}")
    if old_root is not None:
        names.extend([old_root, basename])
        names.append(f".metaproject/docs/{old_root}")
    names.append(f".metaproject/docs/{basename.lower()}")
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

    `.metaproject/docs/INTENT.md` → `.metaproject.template/docs.template/INTENT.template.md`;
    the inverse of `templates.transform_template_name` applied per component.
    """
    parts = PurePosixPath(path).parts
    dirs = [f"{part}.template" for part in parts[:-1]]
    stem, dot, suffix = parts[-1].rpartition(".")
    leaf = f"{stem}.template.{suffix}" if dot and stem else f"{parts[-1]}.template"
    return PurePosixPath(*dirs, leaf).as_posix()


def legacy_locations(project_dir: Path) -> Dict[str, str]:
    """Declared path → the legacy file or directory actually present, for unmigrated items.

    A relocated file is legacy when absent at its exact `.metaproject/docs/` path and
    present at any candidate in `legacy_candidates`. Directory deliverables are legacy when
    absent at `.metaproject/docs/` and `docs/archive` exists or `docs/` holds any legacy
    metaproject artifact (`docs/*`, `docs/archive`, `docs/backlog`, `docs/discovery`,
    `docs/.gitkeep`). A project's own `docs/` (e.g. MkDocs) is never flagged.
    """
    root = Path(project_dir)
    found: Dict[str, str] = {}
    for new in RELOCATED_FILES:
        if exact_exists(root / new):
            continue
        candidates = legacy_candidates(root, new)
        if candidates:
            found[new] = candidates[0]
    if (
        not exact_exists(root / ".metaproject/docs/archive")
        and exact_exists(root / "docs/archive")
        and (root / "docs/archive").is_dir()
    ):
        found[".metaproject/docs/archive"] = "docs/archive"
    if (
        not exact_exists(root / ".metaproject/docs")
        and exact_exists(root / "docs")
        and (root / "docs").is_dir()
    ):
        has_legacy_docs_item = (
            any(where.startswith("docs/") for where in found.values())
            or ".metaproject/docs/archive" in found
            or (exact_exists(root / "docs/.gitkeep") and (root / "docs/.gitkeep").is_file())
            or any(
                exact_exists(root / "docs" / sub) and (root / "docs" / sub).is_dir()
                for sub in MIGRATABLE_SUBDIRS
            )
        )
        if has_legacy_docs_item:
            found[".metaproject/docs"] = "docs"
    return found
