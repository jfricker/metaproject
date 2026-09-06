"""Render-and-diff evidence gathering for the `learn` pipeline (spec.md §5.4.1 stage 1).

For each project and each target file, the corresponding template is rendered with that
project's own variables and diffed against the project's actual file. The *diff* is the
evidence unit. Rendering before diffing is what removes the placeholder-substitution
false positives that made the legacy line-diff harvester unusable.

This stage is entirely deterministic. No model is involved.
"""

import difflib
import functools
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from metaproject.config import Config, load_config
from metaproject.exceptions import TemplateError
from metaproject.templates import (
    is_binary_file,
    render_template_string,
    transform_template_name,
)
from metaproject.universe import (
    IGNORED_DIRECTORIES,
    classify_project,
    extract_description,
    extract_title,
    is_project_root,
    resolve_project_timestamp,
)
from metaproject.variables import collect_variables

DIFF_CONTEXT_LINES = 3


@dataclass(frozen=True)
class EvidenceRecord:
    """One project's deviation from one rendered template.

    `diff` is a unified diff from the rendered template to the project's file;
    `added_lines` are the non-blank lines the project adds, normalized. Removals are
    deliberately not represented: proposing deletions from templates is out of scope
    (spec.md §5.4.6), so an empty project file is never a deletion proposal.
    """

    project_name: str
    project_path: str
    classification: Optional[str]
    target_file: str
    template_path: Optional[str]
    kind: str
    diff: str
    added_lines: Tuple[str, ...]


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


@functools.lru_cache(maxsize=8)
def _resolved_author(config_author: str) -> str:
    """Resolve the author once per distinct configured value, not once per project."""
    from metaproject.variables import resolve_author

    return resolve_author(config_author or None, None)


def _drop_unfilled_placeholder(value: str) -> str:
    """Treat a still-unfilled `{Placeholder}` as absent rather than as real content.

    A freshly scaffolded project's `intent.md` still carries `{Problem description}`
    under `## Problem`, and `universe.extract_description` reads it literally. Feeding
    that back in as a variable renders the placeholder *into* the comparison text, so
    every such project appears to have drifted from the very template it came from.
    """
    text = (value or "").strip()
    return "" if text.startswith("{") and text.endswith("}") else text


def project_variables(project_dir: Path, config: Optional[Config] = None) -> Dict[str, Any]:
    """Resolve the template variables a project would have been scaffolded with.

    Title and description come from the project itself (`universe.extract_title` /
    `extract_description`), so rendering reproduces what `metaproject new` would have
    written for this project rather than a generic placeholder.
    """
    project_dir = Path(project_dir)
    author = _resolved_author(config.author if config else "")
    return collect_variables(
        project_name=project_dir.name,
        title=_drop_unfilled_placeholder(extract_title(project_dir)),
        description=_drop_unfilled_placeholder(extract_description(project_dir)),
        author=author,
        config=config,
        interactive=False,
    )


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
            if item.name == ".git":
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

        template_file = resolve_template(rel, templates_dir)
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
