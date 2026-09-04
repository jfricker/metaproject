"""`review` findings as a corroboration signal for `learn` (spec.md §5.4.9).

`metaproject review` already audits a project against the template store and reports
where it diverges. That report is not a second opinion to be filed alongside `learn`'s
— it is the *same* divergence, seen by a second, independent code path. So it is used
here the only way it can be used without double-counting: as a **multiplier on evidence
that `collect` already gathered**, never as a finding of its own.

Three properties make that true, and each is asserted by a test:

**A drift report never creates a candidate.** `collect_drift` returns a lookup table
and nothing else. `score.group_candidates` and `api.scan` iterate over collected
evidence records; a project `review` flags but `collect` has no evidence for contributes
nothing, and a file `review` reports as *missing* has no evidence to attach to at all —
`missing` is recorded for explainability and is never scored.

**The boost is per (project, target file), applied at most once.** It multiplies that
project's single contribution weight rather than adding a term, so a project cannot
become two contributions and `evidence_count` is untouched.

**It is bounded** (`score.DRIFT_BOOST`), for the same reason recency is: corroboration by
one more code path should reorder within a class, never outrank frequency. One
drift-confirmed project must still rank below two projects that agree.

This module reads `review` and writes nothing. `review.py` itself is untouched.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from metaproject.learn.score import candidate_key

Reviewer = Callable[..., Mapping[str, Any]]

DriftKey = Tuple[str, str]
"""(absolute project path, project-relative target file)."""


def added_lines(diff: str) -> Tuple[str, ...]:
    """The non-blank lines a unified diff adds, normalized for candidate matching.

    Removals are never evidence (`collect` has the same rule), and the `+++` header is
    not a line of content.
    """
    out: List[str] = []
    for line in (diff or "").splitlines():
        if line.startswith("+++") or not line.startswith("+"):
            continue
        key = candidate_key(line[1:])
        if key:
            out.append(key)
    return tuple(out)


@dataclass(frozen=True)
class DriftSignal:
    """What `review` reports, in the shape scoring can consult.

    `lines` maps a (project path, target file) pair to the normalized lines `review`
    saw as drift. `missing` maps a project path to the deliverables it lacks: recorded
    so a caller can explain the signal, never consulted by scoring, because a file a
    project does not have produces no evidence for a proposal to be about.
    """

    lines: Mapping[DriftKey, FrozenSet[str]] = field(default_factory=dict)
    missing: Mapping[str, FrozenSet[str]] = field(default_factory=dict)

    @property
    def pairs(self) -> FrozenSet[DriftKey]:
        """Every (project, target file) pair `review` reports content drift for."""
        return frozenset(key for key, values in self.lines.items() if values)

    def reports(
        self,
        project_path: str | Path,
        target_file: str,
        keys: Iterable[str],
    ) -> bool:
        """Does `review` already report this project diverging in *this* way?

        `keys` are candidate lines (or raw evidence lines); they are normalized here so
        callers can pass either.
        """
        bucket = self.lines.get((str(project_path), target_file))
        if not bucket:
            return False
        return any(candidate_key(key) in bucket for key in keys)


EMPTY_DRIFT = DriftSignal()
"""The identity signal: scores exactly as consulting `review` not at all."""


def _review_project(project_dir: Path, templates_dir: Optional[Path]) -> Mapping[str, Any]:
    """Call `review` for one project. Imported late so `review` stays independent."""
    from metaproject.review import review_project

    return review_project(project_dir, templates_dir)


def collect_drift(
    project_dirs: Sequence[Path | str],
    templates_dir: Optional[Path | str] = None,
    reviewer: Optional[Reviewer] = None,
) -> DriftSignal:
    """Ask `review` about each project and reduce its findings to a scoring signal.

    A project `review` cannot audit is skipped rather than fatal: losing a whole scan
    because one directory is unreadable would be a poor trade for a bounded bonus.
    """
    run = reviewer or _review_project
    templates = Path(templates_dir).expanduser().resolve() if templates_dir else None

    lines: Dict[DriftKey, FrozenSet[str]] = {}
    missing: Dict[str, FrozenSet[str]] = {}

    for project_dir in project_dirs:
        path = Path(project_dir).expanduser().resolve()
        try:
            result = run(path, templates)
        except Exception:
            continue
        if not isinstance(result, Mapping):
            continue

        key_path = str(result.get("project_path") or path)
        absent = result.get("missing_files") or []
        if absent:
            missing[key_path] = frozenset(str(name) for name in absent)

        for target_file, diff in (result.get("diffs") or {}).items():
            found = added_lines(str(diff))
            if found:
                lines[(key_path, str(target_file))] = frozenset(found)

    return DriftSignal(lines=lines, missing=missing)
