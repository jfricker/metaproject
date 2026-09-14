"""Writing an accepted proposal into the template store (spec.md §5.4.1 stage 6).

This is the only module in `learn` that writes to a template, and it is deliberately
the smallest one that can be. Three properties are the whole point of it:

**Insertion is structural (acceptance case C12).** The legacy harvester appended every
harvested line to the end of the file under a comment banner, which is meaningless in
Markdown and produced templates nobody wanted to read. A proposal names a
`target_section`; the change lands at the end of that section's content, before the
next heading. A heading *addition* (`add_heading`, plan.md C3) is structural the same
way, one level up: it lands as a new sibling section immediately after its anchor
section ends, never inside the anchor's own content.

**A section that does not resolve is never faked (plan.md risk R7).** If the model
names a heading the template does not have, `splice`/`insert_heading` does not invent
it, does not guess at a near match, and does not quietly drop the change somewhere
plausible. It falls back to an append at end of file and *says so* in
`ApplyPlan.fallback_reason`, which the caller is expected to put in front of the
operator — a reviewed append, never a silent misplacement. `allow_fallback=False` is
how that review says no. A heading *removal* (`remove_heading`) has no such fallback:
an unresolved section, or a section whose child heading a contributor still relies on,
is an `ApplyError` raised out of `plan_apply` before any plan exists — deleting the
wrong thing has no safe "reviewed" version the way misplacing an addition does.

**Every accept is one commit (plan.md risk R6).** The template store is a git
repository, the worktree must be clean before a write, and each accepted proposal
becomes exactly one commit naming the proposal id and the contributing projects. A bad
accept is therefore undone by reverting one commit, and nothing else goes with it.
"""

import difflib
import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Sequence, Tuple

import sqlite_utils

from metaproject.config import Config, load_config
from metaproject.exceptions import ApplyError, GitError
from metaproject.git import get_git_identity, is_git_repository
from metaproject.learn.collect import normalize_text, resolve_template
from metaproject.learn.store import get_evidence, get_proposal, mark_applied, set_edited_body
from metaproject.learn.structure import KIND_ADD_HEADING, KIND_REMOVE_HEADING
from metaproject.markdown import (
    _FENCE_RE,
    _HEADING_RE,
    Heading,
    Section,
    heading_matches,
    headings,
    iter_sections,
    normalize_heading,
)

PLACEMENT_SECTION = "section"
PLACEMENT_APPEND = "append"
PLACEMENT_NEW_FILE = "new_file"
PLACEMENT_REMOVE = "remove"

# Kinds `plan_apply` cannot yet compute a write for. Empty for now: `add_heading` and
# `remove_heading` (plan.md C2's `structure.propose` output) both have handlers below.
# Kept, rather than deleted, as the one place a future unsupported kind gets refused
# cleanly instead of falling through to the `edit`/`new_template` branch by accident.
UNSUPPORTED_KINDS: frozenset = frozenset()

# Re-exported for callers that imported these from this module before they moved to
# `metaproject.markdown`; not used directly in this file.
__all__ = [
    "_FENCE_RE",
    "_HEADING_RE",
]


# --------------------------------------------------------------- document structure


def resolve_section(text: str, target_section: Optional[str]) -> Optional[Section]:
    """Find the section a proposal names, or None if the template has no such heading."""
    if not target_section or not target_section.strip():
        return None
    wanted = normalize_heading(target_section)
    if not wanted:
        return None
    for section in iter_sections(text):
        if normalize_heading(section.title) == wanted:
            return section
    return None


def _normalized_lines(text: str) -> List[str]:
    """Content lines with indentation and internal spacing collapsed."""
    return [" ".join(line.split()) for line in text.split("\n") if line.strip()]


def body_is_present(text: str, body: str) -> bool:
    """Does the document already carry every line of this body?

    Convergence, not cleverness: re-applying a proposal a template already satisfies
    must not duplicate its content (acceptance case C27's other half).
    """
    existing = set(_normalized_lines(text))
    wanted = _normalized_lines(body)
    return bool(wanted) and all(line in existing for line in wanted)


def splice(
    text: str,
    body: str,
    target_section: Optional[str],
) -> Tuple[str, str, Optional[str]]:
    """Insert `body` under `target_section`, or append it at end of file.

    Returns `(updated_text, placement, fallback_reason)`. `fallback_reason` is set only
    when a named section failed to resolve — the caller must surface it rather than
    claiming an insertion that did not happen (R7).
    """
    original = normalize_text(text)
    body_block = normalize_text(body).rstrip("\n")
    if not body_block.strip():
        return original, PLACEMENT_APPEND, None
    if body_is_present(original, body_block):
        return original, PLACEMENT_SECTION if target_section else PLACEMENT_APPEND, None

    body_lines = body_block.split("\n")
    lines = original.split("\n")
    section = resolve_section(original, target_section)

    if section is not None:
        insert_at = section.heading + 1
        for index in range(section.end - 1, section.heading, -1):
            if lines[index].strip():
                insert_at = index + 1
                break
        tail = lines[insert_at:]
        if tail and tail[0].strip():
            body_lines = body_lines + [""]
        updated = lines[:insert_at] + body_lines + tail
        return normalize_text("\n".join(updated)), PLACEMENT_SECTION, None

    reason = None
    if target_section and target_section.strip():
        reason = (
            f"section {target_section.strip()!r} does not exist in this template; "
            "appending at end of file instead"
        )

    trimmed = original.rstrip("\n")
    joined = (trimmed + "\n\n" + body_block) if trimmed else body_block
    return normalize_text(joined), PLACEMENT_APPEND, reason


# -------------------------------------------------------------- heading add / remove


def _parse_heading_line(line: str) -> Tuple[int, str]:
    """`(level, title)` from a `"#"*level + " " + title` line, or `(0, "")` if none."""
    match = _HEADING_RE.match(line.strip())
    if not match:
        return 0, ""
    return len(match.group(1)), match.group(2).strip()


def _heading_present(text: str, heading_line: str) -> bool:
    """Does the document already have a heading at this level with this title?

    The addition analogue of `body_is_present`: re-applying an `add_heading` proposal
    the template already satisfies must not duplicate the heading.
    """
    level, title = _parse_heading_line(heading_line)
    if level == 0:
        return False
    wanted = normalize_heading(title)
    return any(
        section.level == level and normalize_heading(section.title) == wanted
        for section in iter_sections(text)
    )


def _append_heading(text: str, heading_line: str) -> str:
    trimmed = text.rstrip("\n")
    joined = (trimmed + "\n\n" + heading_line) if trimmed else heading_line
    return normalize_text(joined)


def insert_heading(
    text: str,
    heading_line: str,
    target_section: Optional[str],
) -> Tuple[str, str, Optional[str]]:
    """Insert a *new* heading (`heading_line`) as a sibling section, or at end of file.

    Unlike `splice` (content landing inside an existing section), a heading addition
    lands *after* its anchor section ends — before the next heading of the same or a
    shallower level — never inside the anchor's own content (AC-11a). `target_section`
    of `None` means no contributor's copy resolved to an anchor at all (see
    `structure.propose`); that is not a failure to resolve a *named* section, so it
    appends silently, with no `fallback_reason`. A *named* section that does not exist
    in the template falls back to an append and says so, exactly like `splice` (R7).

    Returns `(updated_text, placement, fallback_reason)`.
    """
    original = normalize_text(text)
    heading = normalize_text(heading_line).rstrip("\n")
    if not heading.strip():
        return original, PLACEMENT_APPEND, None
    if _heading_present(original, heading):
        return original, PLACEMENT_SECTION if target_section else PLACEMENT_APPEND, None

    if target_section is None or not target_section.strip():
        return _append_heading(original, heading), PLACEMENT_APPEND, None

    section = resolve_section(original, target_section)
    if section is None:
        reason = (
            f"section {target_section.strip()!r} does not exist in this template; "
            "appending at end of file instead"
        )
        return _append_heading(original, heading), PLACEMENT_APPEND, reason

    lines = original.split("\n")
    insert_at = section.end
    before = lines[:insert_at]
    after = lines[insert_at:]
    block = [""] + [heading] if before and before[-1].strip() else [heading]
    if after and after[0].strip():
        block = block + [""]
    updated = before + block + after
    return normalize_text("\n".join(updated)), PLACEMENT_SECTION, None


def _section_children(text: str, section: Section) -> List[Heading]:
    """Headings nested anywhere inside `section`'s own extent (its whole subtree)."""
    return [
        Heading(level=candidate.level, title=candidate.title)
        for candidate in iter_sections(text)
        if section.heading < candidate.heading < section.end
    ]


def _format_heading(heading: Heading) -> str:
    return f"{'#' * heading.level} {heading.title}"


def _contributor_still_has(
    db: sqlite_utils.Database,
    proposal_id: int,
    target_file: str,
    child: Heading,
) -> Optional[str]:
    """A contributing project's name, if its own copy of `target_file` still carries
    a heading matching `child`. A missing file never counts as containing it."""
    for row in get_evidence(db, proposal_id):
        project_dir = Path(str(row["project_path"]))
        candidate = project_dir / target_file
        if not candidate.is_file():
            continue
        text = candidate.read_text(encoding="utf-8", errors="replace")
        for project_heading in headings(text):
            if heading_matches(child, project_heading):
                return project_dir.name
    return None


def excise(text: str, section: Section) -> str:
    """Remove `section` (heading and its whole subtree), collapsing extra blank runs.

    Purely mechanical: whether the removal is *safe* — no contributor still has one of
    the section's child headings — is decided by the caller (`plan_apply`) before this
    is reached, using the same evidence rows that produced the proposal.
    """
    original = normalize_text(text)
    lines = original.split("\n")
    remaining = lines[: section.heading] + lines[section.end :]
    collapsed = re.sub(r"\n{3,}", "\n\n", "\n".join(remaining))
    return normalize_text(collapsed)


# ------------------------------------------------------------------ template targets


def template_name(name: str) -> str:
    """Inverse of `templates.transform_template_name` for one path component."""
    if name.startswith(".") and "." not in name[1:]:
        return f"{name}.template"
    if "." in name:
        stem, _dot, extension = name.rpartition(".")
        return f"{stem}.template.{extension}"
    return f"{name}.template"


def template_destination(target_file: str, templates_dir: Path) -> Path:
    """Where a `new_template` proposal for `target_file` would be written."""
    parts = [template_name(part) for part in PurePosixPath(target_file).parts]
    return Path(templates_dir).joinpath(*parts)


# ------------------------------------------------------------------------- the plan


@dataclass(frozen=True)
class ApplyPlan:
    """Exactly what an accept would write, computed before anything is written."""

    proposal_id: int
    target_file: str
    template_file: Path
    kind: str
    target_section: Optional[str]
    placement: str
    body: str
    original: str
    updated: str
    fallback_reason: Optional[str]
    contributing_projects: Tuple[str, ...]
    title: str
    rationale: str
    content_hash: str

    @property
    def changed(self) -> bool:
        """Would this write anything at all?"""
        return self.updated != self.original

    def diff(self) -> str:
        """The unified diff the operator reviews before confirming."""
        return "".join(
            difflib.unified_diff(
                self.original.splitlines(keepends=True),
                self.updated.splitlines(keepends=True),
                fromfile=f"a/{self.template_file.name}",
                tofile=f"b/{self.template_file.name}",
                n=3,
            )
        )


@dataclass(frozen=True)
class ApplyResult:
    """The outcome of an accept: what was written, and the commit that carries it."""

    plan: ApplyPlan
    changed: bool
    commit: Optional[str]


def proposal_body(row: Dict[str, Any], edited_body: Optional[str] = None) -> str:
    """The text to write: an explicit edit, then a stored edit, then the proposal.

    `edited_body` takes precedence over `proposed_body` (spec.md §5.4.5); the operator
    is the last word on what lands in a template.
    """
    if edited_body is not None and edited_body.strip():
        return edited_body
    stored = row.get("edited_body")
    if stored is not None and str(stored).strip():
        return str(stored)
    return str(row.get("proposed_body") or "")


def evidence_project_names(db: sqlite_utils.Database, proposal_id: int) -> Tuple[str, ...]:
    """Names of the projects whose evidence produced a proposal, for the commit trailer."""
    names: List[str] = []
    for row in get_evidence(db, proposal_id):
        name = Path(str(row["project_path"])).name
        if name and name not in names:
            names.append(name)
    return tuple(names)


def resolve_template_file(row: Dict[str, Any], templates_dir: Path) -> Path:
    """Locate the template a proposal edits, or the file a new one would create."""
    target_file = str(row["target_file"])
    kind = str(row["kind"] or "edit")
    templates_dir = Path(templates_dir).expanduser().resolve()

    resolved = resolve_template(target_file, templates_dir)
    if resolved is not None:
        return resolved

    stored = row.get("template_path")
    if stored and Path(str(stored)).is_file():
        candidate = Path(str(stored)).resolve()
        try:
            candidate.relative_to(templates_dir)
        except ValueError:
            raise ApplyError(
                f"recorded template path {candidate} is outside the template store "
                f"{templates_dir}; refusing to write"
            ) from None
        return candidate

    if kind == "new_template":
        return template_destination(target_file, templates_dir)

    raise ApplyError(
        f"no template backs {target_file!r} in {templates_dir}; nothing to patch. "
        "Re-scan, or apply this as a new template."
    )


def plan_apply(
    db: sqlite_utils.Database,
    proposal_id: int,
    templates_dir: Optional[Path] = None,
    config: Optional[Config] = None,
    edited_body: Optional[str] = None,
) -> ApplyPlan:
    """Compute the write without performing it. Never touches the filesystem's contents."""
    row = get_proposal(db, proposal_id)
    if row is None:
        raise ApplyError(f"no proposal with id {proposal_id}")

    kind = str(row.get("kind") or "edit")
    if kind in UNSUPPORTED_KINDS:
        raise ApplyError(
            f"proposal {proposal_id} is a {kind!r} proposal; applying it is not supported."
        )

    if templates_dir is None:
        config = config or load_config()
        templates_dir = Path(config.templates_dir)
    templates_dir = Path(templates_dir).expanduser().resolve()

    target_file = str(row["target_file"])
    target_section = row.get("target_section")
    template_file = resolve_template_file(row, templates_dir)
    body = proposal_body(row, edited_body)
    if not body.strip():
        raise ApplyError(f"proposal {proposal_id} has an empty body; nothing to apply")

    if kind == KIND_REMOVE_HEADING:
        # No fallback here (module docstring): an unresolved section, or one a
        # contributor still relies on, is an error raised before any plan exists.
        if not template_file.exists():
            raise ApplyError(
                f"proposal {proposal_id} would remove a heading from {template_file}, "
                "but that template does not exist."
            )
        original = normalize_text(template_file.read_text(encoding="utf-8"))
        section = resolve_section(original, target_section)
        if section is None:
            raise ApplyError(
                f"proposal {proposal_id} names section {target_section!r} to remove from "
                f"{target_file}, but the template has no such heading; refusing rather "
                "than guessing what was meant to be removed."
            )
        for child in _section_children(original, section):
            offender = _contributor_still_has(db, proposal_id, target_file, child)
            if offender is not None:
                raise ApplyError(
                    f"proposal {proposal_id} would remove {target_section!r} from "
                    f"{target_file}, but {offender} still has its child heading "
                    f"{_format_heading(child)!r}; refusing to remove a section a "
                    "contributor still relies on."
                )
        updated = excise(original, section)
        placement, reason = PLACEMENT_REMOVE, None
    elif kind == KIND_ADD_HEADING:
        if template_file.exists():
            original = normalize_text(template_file.read_text(encoding="utf-8"))
        else:
            original = ""
        updated, placement, reason = insert_heading(original, body, target_section)
    elif template_file.exists():
        original = normalize_text(template_file.read_text(encoding="utf-8"))
        updated, placement, reason = splice(original, body, target_section)
    else:
        original = ""
        updated = normalize_text(body)
        placement, reason = PLACEMENT_NEW_FILE, None

    return ApplyPlan(
        proposal_id=int(row["id"]),
        target_file=target_file,
        template_file=template_file,
        kind=kind,
        target_section=target_section,
        placement=placement,
        body=body,
        original=original,
        updated=updated,
        fallback_reason=reason,
        contributing_projects=evidence_project_names(db, int(row["id"])),
        title=str(row["title"] or ""),
        rationale=str(row["rationale"] or ""),
        content_hash=str(row["content_hash"] or ""),
    )


# ---------------------------------------------------------------------- git plumbing


def ensure_clean_repository(templates_dir: Path) -> None:
    """Refuse to write into a template store that is not a clean git repository.

    Both halves matter (R6): without a repository there is nothing to revert, and with
    uncommitted changes an accept's commit would sweep up unrelated edits, so a revert
    would undo more than one decision.
    """
    templates_dir = Path(templates_dir)
    if not is_git_repository(templates_dir):
        raise ApplyError(
            f"template store {templates_dir} is not a git repository, so an applied "
            "proposal could not be reverted. Run `metaproject init` first."
        )
    status = subprocess.run(
        ["git", "-C", str(templates_dir), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        raise ApplyError(f"could not read git status for {templates_dir}: {status.stderr.strip()}")
    if status.stdout.strip():
        raise ApplyError(
            f"template repository {templates_dir} has uncommitted changes. "
            "Commit or stash them before applying a proposal."
        )


def commit_message(
    proposal_id: int,
    title: str,
    target_file: str,
    rationale: str,
    projects: Sequence[str],
    content_hash: str = "",
    placement: str = PLACEMENT_SECTION,
    target_section: Optional[str] = None,
    kind: str = "edit",
    body: str = "",
) -> str:
    """The commit that carries one accept, and the provenance a revert reads."""
    if kind == KIND_REMOVE_HEADING and body.strip():
        subject = f'learn: remove "{body.strip()}" from {target_file} (proposal #{proposal_id})'
    elif kind == KIND_ADD_HEADING and body.strip():
        subject = f'learn: add "{body.strip()}" to {target_file} (proposal #{proposal_id})'
    else:
        subject = f"learn: {title}".rstrip()

    where = (
        f" under {target_section.strip()!r}"
        if placement == PLACEMENT_SECTION and target_section and kind != KIND_REMOVE_HEADING
        else ""
    )
    lines = [
        subject,
        "",
        f"Applies learn proposal #{proposal_id} to the {target_file} template{where}.",
    ]
    if placement == PLACEMENT_APPEND and target_section:
        lines.append(
            f"Section {target_section.strip()!r} was not present; appended at end of file."
        )
    if rationale.strip():
        lines.extend(["", rationale.strip()])
    if projects:
        lines.extend(["", f"Contributing projects: {', '.join(projects)}"])
    if content_hash:
        lines.append(f"Proposal-Hash: {content_hash}")
    return "\n".join(lines) + "\n"


def _git(templates_dir: Path, *args: str) -> subprocess.CompletedProcess:
    """Run one git command inside the template store."""
    return subprocess.run(
        ["git", "-C", str(templates_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def commit_file(templates_dir: Path, path: Path, message: str) -> str:
    """Stage exactly one file and commit it. Returns the new commit sha."""
    templates_dir = Path(templates_dir)
    add = _git(templates_dir, "add", "--", str(path))
    if add.returncode != 0:
        raise GitError(f"failed to stage {path}: {add.stderr.strip()}")

    args: List[str] = []
    name, email = get_git_identity(templates_dir)
    if not name:
        args += ["-c", "user.name=Metaproject Learn"]
    if not email:
        args += ["-c", "user.email=learn@metaproject.local"]

    commit = _git(templates_dir, *args, "commit", "-m", message)
    if commit.returncode != 0:
        raise GitError(f"failed to commit {path}: {(commit.stderr or commit.stdout).strip()}")

    head = _git(templates_dir, "rev-parse", "HEAD")
    return head.stdout.strip()


# ----------------------------------------------------------------------- the accept


def apply_plan(
    db: sqlite_utils.Database,
    plan: ApplyPlan,
    templates_dir: Path,
    allow_fallback: bool = True,
    edited_body: Optional[str] = None,
) -> ApplyResult:
    """Write one plan into the template store and commit it. One accept, one commit."""
    if plan.fallback_reason and not allow_fallback:
        raise ApplyError(plan.fallback_reason)

    ensure_clean_repository(templates_dir)

    if not plan.changed:
        # The template already says this. Record the decision, commit nothing: an
        # empty commit would be a lie in the history.
        mark_applied(db, plan.proposal_id, commit=None, edited_body=edited_body)
        return ApplyResult(plan=plan, changed=False, commit=None)

    plan.template_file.parent.mkdir(parents=True, exist_ok=True)
    plan.template_file.write_text(plan.updated, encoding="utf-8")

    message = commit_message(
        proposal_id=plan.proposal_id,
        title=plan.title,
        target_file=plan.target_file,
        rationale=plan.rationale,
        projects=plan.contributing_projects,
        content_hash=plan.content_hash,
        kind=plan.kind,
        body=plan.body,
        placement=plan.placement,
        target_section=plan.target_section,
    )
    commit = commit_file(templates_dir, plan.template_file, message)
    mark_applied(db, plan.proposal_id, commit=commit, edited_body=edited_body)
    return ApplyResult(plan=plan, changed=True, commit=commit)


def apply_proposal(
    db: sqlite_utils.Database,
    proposal_id: int,
    templates_dir: Optional[Path] = None,
    config: Optional[Config] = None,
    edited_body: Optional[str] = None,
    allow_fallback: bool = True,
    contributing_projects: Optional[Sequence[str]] = None,
) -> ApplyResult:
    """Accept one proposal: patch its template at `target_section` and commit.

    `contributing_projects` overrides the provenance rows, for a caller that already
    knows them; normally they are read from `learn_evidence`.
    """
    if templates_dir is None:
        config = config or load_config()
        templates_dir = Path(config.templates_dir)
    templates_dir = Path(templates_dir).expanduser().resolve()

    plan = plan_apply(
        db, proposal_id, templates_dir=templates_dir, config=config, edited_body=edited_body
    )
    if contributing_projects:
        plan = replace(plan, contributing_projects=tuple(contributing_projects))

    if edited_body is not None and edited_body.strip():
        set_edited_body(db, proposal_id, edited_body)

    return apply_plan(
        db,
        plan,
        templates_dir,
        allow_fallback=allow_fallback,
        edited_body=edited_body if edited_body and edited_body.strip() else None,
    )
