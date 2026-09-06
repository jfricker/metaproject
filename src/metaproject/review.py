"""Template drift auditing, project compliance verification, and remediation.

Three things live here, in the order the operator meets them:

1. **Auditing** — `review_project` / `review_workspace` answer *what is wrong*: which
   standard deliverables are missing, and which existing ones have drifted from their
   template.
2. **Remediation** — `deploy_entry` writes a missing deliverable into a project;
   `update_entry` rewrites a drifted one. These are what the board's **Deploy** and
   **Update** actions call.
3. **The ignore list** — `ignore_project` records a project the operator has decided may
   stay out of compliance, so it never appears in a review again.

**Render before diffing, always** (STATE.md design invariants). Every comparison here
goes through `learn.collect.render_template`, so a project's own name and description are
never mistaken for drift. `review` and `learn` therefore share one notion of "this file
has diverged" rather than two that can disagree.
"""

import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence

from metaproject.config import Config, get_config_dir, load_config
from metaproject.exceptions import MetaProjectError
from metaproject.templates import (
    get_bundled_templates_dir,
    render_template_tree,
    transform_template_name,
)
from metaproject.universe import is_project_root

STANDARD_DELIVERABLES = [
    "README.md",
    "AGENTS.md",
    "intent.md",
    "STATE.md",
    "HANDOFF.md",
    "CLAUDE.md",
    ".gitignore",
    "docs",
]

IGNORE_FILE_NAME = "review-ignore.json"


# ------------------------------------------------------------------------ ignore list


def get_ignore_file(config_dir: Optional[Path] = None) -> Path:
    """Path to the ignore ledger, inside the resolved config directory."""
    return (config_dir or get_config_dir()) / IGNORE_FILE_NAME


def load_ignored(config_dir: Optional[Path] = None) -> List[str]:
    """Absolute paths of projects excluded from review, oldest entry first.

    A malformed or unreadable ledger is treated as empty rather than raised: an operator
    who cannot parse their own ignore file should still be able to run a review.
    """
    path = get_ignore_file(config_dir)
    try:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    entries = data.get("projects") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return []
    return [str(item) for item in entries if isinstance(item, str) and item.strip()]


def _write_ignored(entries: Sequence[str], config_dir: Optional[Path] = None) -> Path:
    path = get_ignore_file(config_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"version": 1, "projects": list(entries)}, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        raise MetaProjectError(f"Failed to write ignore list to {path}: {exc}") from exc
    return path


def is_ignored(project_dir: Path, config_dir: Optional[Path] = None) -> bool:
    """Has this project been marked as allowed to stay out of compliance?"""
    resolved = str(Path(project_dir).expanduser().resolve())
    return resolved in set(load_ignored(config_dir))


def ignore_project(project_dir: Path, config_dir: Optional[Path] = None) -> bool:
    """Add a project to the ignore list. Returns False if it was already there."""
    resolved = str(Path(project_dir).expanduser().resolve())
    entries = load_ignored(config_dir)
    if resolved in entries:
        return False
    entries.append(resolved)
    _write_ignored(entries, config_dir)
    return True


def unignore_project(project_dir: Path, config_dir: Optional[Path] = None) -> bool:
    """Remove a project from the ignore list. Returns False if it was not on it."""
    resolved = str(Path(project_dir).expanduser().resolve())
    entries = load_ignored(config_dir)
    if resolved not in entries:
        return False
    _write_ignored([item for item in entries if item != resolved], config_dir)
    return True


# --------------------------------------------------------------------------- templates


def resolve_templates_dir(templates_dir: Optional[Path] = None) -> Path:
    """The template store to audit against: explicit path, configured store, or bundled."""
    if templates_dir:
        return Path(templates_dir).expanduser().resolve()
    try:
        cfg = load_config()
        tmpl_path = Path(cfg.templates_dir)
        if tmpl_path.exists() and any(tmpl_path.iterdir()):
            return tmpl_path.resolve()
    except (PermissionError, OSError):
        pass
    except MetaProjectError:
        pass
    return get_bundled_templates_dir()


def resolve_template_entry(rel_path: str, templates_dir: Path) -> Optional[Path]:
    """Find the template file *or directory* backing a project-relative path.

    The directory case is why this is not `learn.collect.resolve_template`: `docs` is a
    standard deliverable, and deploying it means rendering `docs.template/` as a tree.
    """
    current = Path(templates_dir)
    for part in PurePosixPath(rel_path).parts:
        if not current.is_dir():
            return None
        match: Optional[Path] = None
        for item in sorted(current.iterdir()):
            if item.name == ".git":
                continue
            if transform_template_name(item.name) == part:
                match = item
                break
        if match is None:
            return None
        current = match
    return current


def get_template_source(template_name: str, templates_dir: Path) -> Optional[Path]:
    """Find the top-level source template matching a target file name."""
    return resolve_template_entry(template_name, templates_dir)


def rendered_template_text(
    template_file: Path,
    project_dir: Path,
    config: Optional[Config] = None,
) -> str:
    """A template rendered with the variables the project would have been scaffolded with."""
    from metaproject.learn.collect import project_variables, render_template

    return render_template(template_file, project_variables(project_dir, config))


# ----------------------------------------------------------------------------- auditing


@dataclass(frozen=True)
class ReviewResult:
    """One project's audit — the single declaration of what a review reports.

    Only what the scan *observed* is stored; every verdict below is derived. A stored
    verdict is a verdict that can be stored wrong, and `is_compliant` disagreeing with
    `missing_files` is not a state this audit should be able to express at all.

    The two verdicts are not synonyms. `is_compliant` is "nothing is missing", and it is
    the weaker claim: drift is reported but is not by itself non-compliance, because a
    project is *expected* to add to its templates and treating every local addition as a
    failure would make the column meaningless. `is_clean` is the stronger one — nothing
    missing *and* nothing drifted — and it is what the board's `CLEAN` state is drawn
    from; `is_compliant` alone only rules out `INCOMPLETE`.
    """

    project_name: str
    project_path: str
    templates_dir: str
    missing_files: List[str] = field(default_factory=list)
    deployable: List[str] = field(default_factory=list)
    diffs: Dict[str, str] = field(default_factory=dict)
    is_ignored: bool = False

    @property
    def updatable(self) -> List[str]:
        """The drifted deliverables — what **Update** can act on, in board order."""
        return sorted(self.diffs)

    @property
    def is_compliant(self) -> bool:
        """Nothing is missing. Says nothing about drift; that is `is_clean`."""
        return not self.missing_files

    @property
    def is_clean(self) -> bool:
        """Nothing missing and nothing drifted — the project matches its templates exactly."""
        return not self.missing_files and not self.diffs

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ReviewResult":
        """Adopt a result-shaped mapping. The boundary for a caller-injected reviewer.

        `learn.drift.collect_drift` takes a `reviewer` callable, and a stand-in for it
        returns a plain dict. Normalizing here is what lets everything downstream read
        one type instead of guarding every key. Derived fields in the mapping are
        ignored rather than trusted — they are derived here too.
        """
        return cls(
            project_name=str(data.get("project_name") or ""),
            project_path=str(data.get("project_path") or ""),
            templates_dir=str(data.get("templates_dir") or ""),
            missing_files=[str(name) for name in (data.get("missing_files") or [])],
            deployable=[str(name) for name in (data.get("deployable") or [])],
            diffs={str(name): str(diff) for name, diff in (data.get("diffs") or {}).items()},
            is_ignored=bool(data.get("is_ignored")),
        )


def _diff_against_template(
    project_file: Path,
    template_file: Path,
    project_dir: Path,
    label: str,
    config: Optional[Config] = None,
) -> Optional[str]:
    """A unified diff from the rendered template to the project's file, or None if equal."""
    from metaproject.learn.collect import normalize_text

    try:
        proj_text = normalize_text(project_file.read_text(encoding="utf-8", errors="ignore"))
        tmpl_text = normalize_text(rendered_template_text(template_file, project_dir, config))
    except Exception:
        return None

    diff = list(
        difflib.unified_diff(
            tmpl_text.splitlines(keepends=True),
            proj_text.splitlines(keepends=True),
            fromfile=f"templates/{label}",
            tofile=f"{project_dir.name}/{label}",
        )
    )
    return "".join(diff) if diff else None


def review_project(
    project_dir: Path,
    templates_dir: Optional[Path] = None,
    config: Optional[Config] = None,
    config_dir: Optional[Path] = None,
) -> ReviewResult:
    """Audit one project against the template store.

    The result separates the two remediations the board offers:

    - `deployable` — missing deliverables that a template can create (**Deploy**).
    - `updatable` — existing deliverables that have drifted (**Update**).

    See `ReviewResult` for what the two verdicts mean and why neither is stored.
    """
    resolved_proj = project_dir.expanduser().resolve()
    resolved_templates = resolve_templates_dir(templates_dir)
    cfg = config or load_config()

    missing_files: List[str] = []
    deployable: List[str] = []
    diffs: Dict[str, str] = {}

    for deliverable in STANDARD_DELIVERABLES:
        target_path = resolved_proj / deliverable
        template_entry = resolve_template_entry(deliverable, resolved_templates)

        if not target_path.exists():
            missing_files.append(deliverable)
            if template_entry is not None:
                deployable.append(deliverable)
            continue

        # Directory deliverables (e.g. `docs`) are a presence check only; diffing a tree
        # against a tree is `learn`'s job, not the compliance board's.
        if target_path.is_dir() or template_entry is None or not template_entry.is_file():
            continue

        diff = _diff_against_template(target_path, template_entry, resolved_proj, deliverable, cfg)
        if diff:
            diffs[deliverable] = diff

    return ReviewResult(
        project_name=resolved_proj.name,
        project_path=str(resolved_proj),
        templates_dir=str(resolved_templates),
        missing_files=missing_files,
        deployable=deployable,
        diffs=diffs,
        is_ignored=is_ignored(resolved_proj, config_dir),
    )


def review_workspace(
    root_dir: Path,
    templates_dir: Optional[Path] = None,
    max_depth: int = 1,
    include_ignored: bool = False,
    config_dir: Optional[Path] = None,
) -> List[ReviewResult]:
    """Audit all projects found within root_dir and its subdirectories.

    ``max_depth`` bounds how far below ``root_dir`` the scan descends; the default of 1
    covers only immediate subdirectories. Projects on the ignore list are omitted unless
    ``include_ignored`` is set — that is the whole point of the list.
    """
    resolved_root = root_dir.expanduser().resolve()
    ignored = set(load_ignored(config_dir))
    results: List[ReviewResult] = []

    def consider(path: Path) -> None:
        if not include_ignored and str(path) in ignored:
            return
        results.append(review_project(path, templates_dir, config_dir=config_dir))

    # If root_dir itself is a project root, include it
    if is_project_root(resolved_root):
        consider(resolved_root)

    # Scan subdirectories
    for current, dirs, _ in os_walk_with_depth(resolved_root, max_depth):
        if current != resolved_root and is_project_root(current):
            consider(current)

    return results


def os_walk_with_depth(root: Path, max_depth: int):
    """Walk directories limiting traversal depth and skipping cache/vendor dirs."""
    root_depth = len(root.parts)
    import os

    from metaproject.universe import IGNORED_DIRECTORIES

    for dirpath, dirnames, filenames in os.walk(root):
        curr_path = Path(dirpath)
        depth = len(curr_path.parts) - root_depth
        if depth >= max_depth:
            dirnames.clear()
        # Skip vendor/cache and hidden directories
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and d not in IGNORED_DIRECTORIES
        ]
        yield curr_path, dirnames, filenames


# -------------------------------------------------------------------------- remediation


def resolve_variables(project_dir: Path, config: Optional[Config] = None) -> Dict[str, Any]:
    """The variable set a whole remediation batch should render with.

    Resolved **once per batch, before the first write**. `extract_title` and
    `extract_description` read the project's own `README.md` and `intent.md`, so
    resolving per file would let a file written early in a batch change how the next one
    renders — and the board would then report the files it had just written as drifted.
    """
    from metaproject.learn.collect import project_variables

    return project_variables(Path(project_dir), config or load_config())


def deploy_entry(
    project_dir: Path,
    deliverable: str,
    templates_dir: Optional[Path] = None,
    config: Optional[Config] = None,
    variables: Optional[Dict[str, Any]] = None,
) -> List[Path]:
    """Write a *missing* deliverable into a project from its template.

    Refuses to overwrite: deploying onto an existing path is `update_entry`'s job, and
    conflating them is how a reviewed file gets silently clobbered.
    """
    from metaproject.templates import render_template_string

    resolved_proj = Path(project_dir).expanduser().resolve()
    resolved_templates = resolve_templates_dir(templates_dir)
    target = resolved_proj / deliverable

    if target.exists():
        raise MetaProjectError(
            f"{deliverable} already exists in {resolved_proj.name}; use update instead."
        )

    entry = resolve_template_entry(deliverable, resolved_templates)
    if entry is None:
        raise MetaProjectError(f"No template provides {deliverable} in {resolved_templates}.")

    resolved_vars = variables if variables is not None else resolve_variables(resolved_proj, config)

    if entry.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        written = render_template_tree(entry, target, resolved_vars)
        return [target, *[p for p in written if p.is_file()]]

    target.parent.mkdir(parents=True, exist_ok=True)
    raw = entry.read_text(encoding="utf-8", errors="replace")
    target.write_text(render_template_string(raw, resolved_vars), encoding="utf-8")
    return [target]


def update_entry(
    project_dir: Path,
    deliverable: str,
    templates_dir: Optional[Path] = None,
    config: Optional[Config] = None,
    variables: Optional[Dict[str, Any]] = None,
) -> Path:
    """Rewrite an *existing, drifted* deliverable from its rendered template.

    This is destructive by design — it is the operator's answer to "the template is
    right, this project is not" — so it only ever runs on a file the board has already
    shown a diff for.
    """
    from metaproject.templates import render_template_string

    resolved_proj = Path(project_dir).expanduser().resolve()
    resolved_templates = resolve_templates_dir(templates_dir)
    target = resolved_proj / deliverable

    if not target.exists():
        raise MetaProjectError(
            f"{deliverable} does not exist in {resolved_proj.name}; use deploy instead."
        )
    if target.is_dir():
        raise MetaProjectError(f"{deliverable} is a directory; only files can be updated.")

    entry = resolve_template_entry(deliverable, resolved_templates)
    if entry is None or not entry.is_file():
        raise MetaProjectError(f"No template file provides {deliverable} in {resolved_templates}.")

    resolved_vars = variables if variables is not None else resolve_variables(resolved_proj, config)
    raw = entry.read_text(encoding="utf-8", errors="replace")
    target.write_text(render_template_string(raw, resolved_vars), encoding="utf-8")
    return target
