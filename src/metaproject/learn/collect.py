"""Render-and-diff evidence gathering for the `learn` pipeline (spec.md §5.4.1 stage 1).

For each project and each target file, the corresponding template is rendered with that
project's own variables and diffed against the project's actual file. The *diff* is the
evidence unit. Rendering before diffing is what removes the placeholder-substitution
false positives that made the legacy line-diff harvester unusable.

This stage is entirely deterministic. No model is involved.
"""

import difflib
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from metaproject.config import Config, load_config
from metaproject.deliverables import DeliverableClass
from metaproject.deliverables import classify as classify_deliverable
from metaproject.exceptions import TemplateError
from metaproject.markdown import Heading, heading_matches, headings, missing_headings
from metaproject.templates import (
    is_binary_file,
    is_junk_file_name,
    render_template_string,
    transform_template_name,
)
from metaproject.universe import (
    IGNORED_DIRECTORIES,
    classify_project,
    is_project_root,
    resolve_project_timestamp,
)
from metaproject.variables import project_variables  # noqa: F401  (re-export)

DIFF_CONTEXT_LINES = 3


@dataclass(frozen=True)
class EvidenceRecord:
    """One project's deviation from one rendered template.

    `diff` is a unified diff from the rendered template to the project's file;
    `added_lines` are the non-blank lines the project adds, normalized. For governance
    and untemplated/config targets, removals are deliberately not represented: proposing
    deletions from templates is out of scope (spec.md §5.4.6), so an empty project file
    is never a deletion proposal.

    For a *working* deliverable (`kind == "structure"`), `added_lines`/`removed_lines`
    instead hold formatted (`"## Title"`) headings — the project adding a heading the
    template lacks, or a non-empty project file lacking a heading the template has
    (spec.md R-LRN-1/1b). Body text of working documents never appears in either tuple
    or in `diff`.
    """

    project_name: str
    project_path: str
    classification: Optional[str]
    target_file: str
    template_path: Optional[str]
    kind: str
    diff: str
    added_lines: Tuple[str, ...]
    removed_lines: Tuple[str, ...] = ()


def normalize_text(text: str) -> str:
    """Fold CRLF, strip per-line trailing whitespace, and end with exactly one newline.

    Without this, a CRLF-encoded project file differs from the rendered template on
    every single line and the whole document looks novel (acceptance case C23).
    """
    if not text:
        return ""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _drop_unfilled_placeholder(value: str) -> str:
    """Treat a still-unfilled `{Placeholder}` as absent rather than as real content.

    Kept for README fallbacks: a freshly scaffolded project's README can still carry a
    literal `{ProjectDescription}` if a template ever slips through unrendered, and
    feeding that back in as a variable would render the placeholder *into* the
    comparison text.
    """
    text = (value or "").strip()
    return "" if text.startswith("{") and text.endswith("}") else text


def resolve_template(rel_path: str, templates_dir: Path) -> Optional[Path]:
    """Find the template file backing a project-relative target path.

    Each path component is matched through `transform_template_name`, so
    `docs/guide.md` resolves to `docs.template/guide.template.md`. The template store's
    own `.git` directory is never traversed (see STATE.md design invariants).
    """
    current = Path(templates_dir)
    for part in PurePosixPath(rel_path).parts:
        if not current.is_dir():
            return None
        match: Optional[Path] = None
        for item in sorted(current.iterdir()):
            if item.name == ".git" or is_junk_file_name(item.name):
                continue
            if transform_template_name(item.name) == part:
                match = item
                break
        if match is None:
            return None
        current = match
    return current if current.is_file() else None


def iter_target_files(project_dir: Path, targets: Sequence[str]) -> List[str]:
    """Expand configured targets into concrete project-relative file paths.

    A target ending in `/` is a directory target and is expanded to the files inside
    it; it is never opened as a file. Symlinks are skipped entirely and symlinked
    directories are never traversed, so a self-referential link cannot be counted twice
    and a link pointing outside the project cannot be followed (acceptance case C26).
    """
    project_dir = Path(project_dir)
    found: List[str] = []

    for target in targets:
        if target.endswith("/"):
            base = project_dir / target.rstrip("/")
            if base.is_symlink() or not base.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
                current = Path(dirpath)
                dirnames[:] = [
                    d
                    for d in sorted(dirnames)
                    if d not in IGNORED_DIRECTORIES and not (current / d).is_symlink()
                ]
                for name in sorted(filenames):
                    path = current / name
                    if path.is_symlink() or not path.is_file():
                        continue
                    found.append(path.relative_to(project_dir).as_posix())
        else:
            path = project_dir / target
            if path.is_symlink() or not path.is_file():
                continue
            found.append(PurePosixPath(target).as_posix())

    return sorted(set(found))


def render_template(template_file: Path, variables: Dict[str, Any]) -> str:
    """Render a template with a project's variables, falling back to its raw text."""
    raw = template_file.read_text(encoding="utf-8", errors="replace")
    try:
        return render_template_string(raw, variables)
    except TemplateError:
        return raw


def _added_lines(template_text: str, project_text: str) -> Tuple[str, ...]:
    """Return the non-blank lines the project adds relative to the rendered template."""
    template_lines = template_text.splitlines()
    project_lines = project_text.splitlines()
    matcher = difflib.SequenceMatcher(None, template_lines, project_lines, autojunk=False)

    added: List[str] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            added.extend(line for line in project_lines[j1:j2] if line.strip())
    return tuple(added)


def _format_heading(heading: Heading) -> str:
    """Render a `Heading` back as the Markdown line it came from (e.g. `## Title`)."""
    return f"{'#' * heading.level} {heading.title}"


def _extra_headings(template_text: str, project_text: str) -> List[Heading]:
    """Project headings with no matching, unclaimed heading in the template text.

    The mirror of `markdown.missing_headings`: order-insensitive and one-to-one, using
    the same `heading_matches` rule, just with the two texts' roles reversed.
    """
    template_headings = headings(template_text)
    claimed = [False] * len(template_headings)
    extra: List[Heading] = []
    for project_heading in headings(project_text):
        matched = False
        for index, template_heading in enumerate(template_headings):
            if claimed[index]:
                continue
            if heading_matches(template_heading, project_heading):
                claimed[index] = True
                matched = True
                break
        if not matched:
            extra.append(project_heading)
    return extra


def _heading_lines(text: str) -> List[str]:
    """A document's heading lines only, formatted for a heading-only diff."""
    return [f"{_format_heading(heading)}\n" for heading in headings(text)]


def _structure_record_fields(
    template_text: str, project_text: str
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """`(added_lines, removed_lines)` for a working deliverable's heading structure.

    `project_text` must already be known non-empty (R-LRN-1b): the caller skips empty
    and missing files before reaching here, so every removal computed here is backed by
    a real, non-empty project file.
    """
    added = tuple(_format_heading(h) for h in _extra_headings(template_text, project_text))
    removed = tuple(_format_heading(h) for h in missing_headings(template_text, project_text))
    return added, removed


def classify(project_dir: Path) -> str:
    """Classify a project's activity the same way `universe` does, for later weighting."""
    _iso, timestamp = resolve_project_timestamp(project_dir)
    return classify_project(project_dir, timestamp, interactive=False)


def collect_project(
    project_dir: Path,
    templates_dir: Path,
    targets: Optional[Sequence[str]] = None,
    config: Optional[Config] = None,
    classification: Optional[str] = None,
) -> List[EvidenceRecord]:
    """Gather evidence for one project against the template store.

    Returns an empty list for a project that matches its rendered templates, for a
    project with only empty target files, and for a directory that carries no targets.
    """
    project_dir = Path(project_dir).expanduser().resolve()
    templates_dir = Path(templates_dir).expanduser().resolve()
    if config is None:
        config = load_config()
    if targets is None:
        targets = config.learn.targets

    variables = project_variables(project_dir, config)
    if classification is None:
        classification = classify(project_dir)

    records: List[EvidenceRecord] = []
    for rel in iter_target_files(project_dir, targets):
        path = project_dir / rel
        if is_binary_file(path):
            continue
        try:
            project_text = normalize_text(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if not project_text.strip():
            continue

        deliverable_class = classify_deliverable(rel)
        if deliverable_class is DeliverableClass.ON_DEMAND:
            # HANDOFF.md and any future on-demand deliverable: never collected, even if
            # a config explicitly lists it as a learn target.
            continue

        template_file = resolve_template(rel, templates_dir)

        if deliverable_class is DeliverableClass.WORKING:
            # Heading structure only, never body text (R-LRN-1). A working target with
            # no template in the store contributes nothing rather than a `new_template`
            # candidate: there is no rendered heading list to compare against.
            if template_file is None:
                continue
            template_text = normalize_text(render_template(template_file, variables))
            added, removed = _structure_record_fields(template_text, project_text)
            if not added and not removed:
                continue

            diff = "".join(
                difflib.unified_diff(
                    _heading_lines(template_text),
                    _heading_lines(project_text),
                    fromfile=f"template/{rel}",
                    tofile=f"{project_dir.name}/{rel}",
                    n=DIFF_CONTEXT_LINES,
                )
            )

            records.append(
                EvidenceRecord(
                    project_name=project_dir.name,
                    project_path=str(project_dir),
                    classification=classification,
                    target_file=rel,
                    template_path=str(template_file),
                    kind="structure",
                    diff=diff,
                    added_lines=added,
                    removed_lines=removed,
                )
            )
            continue

        if template_file is None:
            kind = "new_template"
            template_text = ""
        else:
            kind = "edit"
            template_text = normalize_text(render_template(template_file, variables))

        added = _added_lines(template_text, project_text)
        if not added:
            continue

        diff = "".join(
            difflib.unified_diff(
                template_text.splitlines(keepends=True),
                project_text.splitlines(keepends=True),
                fromfile=f"template/{rel}",
                tofile=f"{project_dir.name}/{rel}",
                n=DIFF_CONTEXT_LINES,
            )
        )

        records.append(
            EvidenceRecord(
                project_name=project_dir.name,
                project_path=str(project_dir),
                classification=classification,
                target_file=rel,
                template_path=str(template_file) if template_file else None,
                kind=kind,
                diff=diff,
                added_lines=added,
            )
        )

    return records


def iter_project_dirs(root: Path, max_depth: int = 4) -> Iterator[Path]:
    """Yield project roots beneath `root`, never descending into a discovered project.

    Discovery is by project boundary, not by file: a directory that merely contains a
    learnable-looking file is not a project and contributes nothing (acceptance case
    C19). Symlinked directories are never followed.
    """
    root = Path(root).expanduser().resolve()

    def walk(current: Path, depth: int) -> Iterator[Path]:
        if depth > max_depth or current.name in IGNORED_DIRECTORIES:
            return
        if is_project_root(current):
            yield current
            if current != root:
                return
        try:
            children = sorted(current.iterdir())
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.is_symlink():
                continue
            if child.name in IGNORED_DIRECTORIES:
                continue
            yield from walk(child, depth + 1)

    yield from walk(root, 0)


def collect_workspace(
    root: Path,
    templates_dir: Path,
    targets: Optional[Sequence[str]] = None,
    max_depth: int = 4,
    config: Optional[Config] = None,
) -> List[EvidenceRecord]:
    """Gather evidence for every project beneath `root`. Never writes anything."""
    if config is None:
        config = load_config()

    records: List[EvidenceRecord] = []
    for project_dir in iter_project_dirs(root, max_depth=max_depth):
        records.extend(collect_project(project_dir, templates_dir, targets=targets, config=config))
    return records
