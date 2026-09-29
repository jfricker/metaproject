"""The bundled project skills, and their create-only installation into a project.

Two kinds of skill ship as package data: the metaproject skill (`skill/`), which teaches
an agent to drive this CLI, and the SDLC cycle skills (`sdlc_skills/<name>/`). They are
not installed globally. `metaproject new` and `backfill` copy each one into the
project's own `.agents/skills/<name>/`, where the `.claude/skills` symlink makes them
visible to Claude Code by bare name, and they are committed with the project.

Installation is create-only: a skill directory that already exists is never written
into, only compared (`current` or `stale`). Picking up a newer release's copy means
deleting the directory and running `backfill` again.
"""

import filecmp
import importlib.resources
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from metaproject.exceptions import MetaProjectError

if TYPE_CHECKING:
    from metaproject.scaffold import TransactionalTracker

SKILL_NAME = "metaproject"

# Install states reported back to the caller.
INSTALLED = "installed"  # nothing was there; the skill was written
CURRENT = "current"  # the installed copy already matches the bundled one
STALE = "stale"  # the installed copy differs; left untouched
MISSING = "missing"  # not installed (a state of the project, before any write)


@dataclass(frozen=True)
class BundledSkill:
    """One skill shipped in the wheel: its name and the directory holding its files."""

    name: str
    source_dir: Path


@dataclass(frozen=True)
class SkillsTarget:
    """Where a project's skills go, or why none may be written there (R-SKL-5)."""

    path: Path
    refusal: Optional[str] = None


@dataclass(frozen=True)
class SkillsReport:
    """What one install pass did, or would do under `dry_run`, per skill name."""

    target: Path
    states: Dict[str, str] = field(default_factory=dict)
    notice: Optional[str] = None

    def named(self, state: str) -> List[str]:
        """The skills that ended in `state`, in declaration order."""
        return [name for name, value in self.states.items() if value == state]


def _package_dir(name: str) -> Path:
    try:
        return Path(str(importlib.resources.files("metaproject").joinpath(name)))
    except Exception as exc:
        raise MetaProjectError(f"Failed to access bundled {name} resources: {exc}") from exc


def get_bundled_skill_dir() -> Path:
    """Return the filesystem path to the metaproject skill shipped inside this package."""
    return _package_dir("skill")


def get_bundled_sdlc_skills_dir() -> Path:
    """Return the filesystem path to the SDLC cycle skills shipped inside this package."""
    return _package_dir("sdlc_skills")


def bundled_skills() -> Tuple[BundledSkill, ...]:
    """The single declaration of the project skills (R-SKL-1), sorted by name.

    `metaproject` from `skill/`, plus every `sdlc_skills/<name>/` that has a `SKILL.md`.
    """
    found = [BundledSkill(SKILL_NAME, get_bundled_skill_dir())]
    sdlc_dir = get_bundled_sdlc_skills_dir()
    if sdlc_dir.is_dir():
        for child in sdlc_dir.iterdir():
            if child.is_dir() and (child / "SKILL.md").is_file():
                found.append(BundledSkill(child.name, child))
    return tuple(sorted(found, key=lambda skill: skill.name))


def legacy_global_skill_dir() -> Path:
    """Where `init` used to install the metaproject skill. Only `doctor` still looks.

    Computed at call time so tests can point `HOME` somewhere harmless.
    """
    return Path.home() / ".claude" / "skills" / SKILL_NAME


def _bundled_files(source_dir: Path) -> List[Path]:
    from metaproject.templates import is_junk_file_name

    return sorted(
        item
        for item in source_dir.rglob("*")
        if item.is_file()
        and not any(is_junk_file_name(part) for part in item.relative_to(source_dir).parts)
    )


def is_skill_current(source_dir: Path, target_dir: Path) -> bool:
    """Report whether target_dir already holds a byte-identical copy of the skill."""
    if not target_dir.exists():
        return False
    for item in _bundled_files(source_dir):
        dest = target_dir / item.relative_to(source_dir)
        if not dest.is_file() or not filecmp.cmp(item, dest, shallow=False):
            return False
    return True


def skill_state(skill: BundledSkill, dest: Path) -> str:
    """`missing`, `current` (byte-identical) or `stale` (differs) for one installed skill."""
    if not dest.exists() and not dest.is_symlink():
        return MISSING
    return CURRENT if is_skill_current(skill.source_dir, dest) else STALE


def project_skills_dir(project_dir: Path) -> SkillsTarget:
    """The project's `.agents/skills`, or a refusal when Claude Code would not see it.

    `.claude/skills` must be absent or a symlink resolving to this project's own
    `.agents/skills`. A real directory there, or a link elsewhere, means skills written
    to `.agents/skills` would be invisible, so nothing is written (R-SKL-5).
    """
    project_dir = Path(project_dir)
    agents_skills = project_dir / ".agents" / "skills"
    claude_skills = project_dir / ".claude" / "skills"

    if claude_skills.is_symlink():
        if claude_skills.resolve() != agents_skills.resolve():
            return SkillsTarget(
                agents_skills,
                f"{claude_skills} is a symlink to {claude_skills.resolve()}, not this "
                "project's .agents/skills; project skills were not installed.",
            )
    elif claude_skills.exists():
        return SkillsTarget(
            agents_skills,
            f"{claude_skills} is a real directory, not a symlink to .agents/skills; "
            "project skills were not installed.",
        )
    return SkillsTarget(agents_skills)


def install_project_skills(
    project_dir: Path,
    dry_run: bool = False,
    tracker: "Optional[TransactionalTracker]" = None,
) -> SkillsReport:
    """Copy every declared skill whose directory is absent into the project.

    Create-only (R-SKL-3/4): an existing skill directory is never written into; it is
    reported `current` or `stale`. Directories and files created are recorded on
    `tracker` so a failed `new` rolls them back. `dry_run` reports `installed` for what
    would be written and writes nothing.
    """
    target = project_skills_dir(project_dir)
    if target.refusal is not None:
        return SkillsReport(target=target.path, notice=target.refusal)

    states: Dict[str, str] = {}
    for skill in bundled_skills():
        dest = target.path / skill.name
        state = skill_state(skill, dest)
        if state != MISSING:
            states[skill.name] = state
            continue
        if not dry_run:
            _copy_skill(skill, dest, tracker)
        states[skill.name] = INSTALLED
    return SkillsReport(target=target.path, states=states)


def _copy_skill(skill: BundledSkill, dest: Path, tracker: "Optional[TransactionalTracker]") -> None:
    for item in _bundled_files(skill.source_dir):
        out = dest / item.relative_to(skill.source_dir)
        missing_parents = [p for p in reversed(out.parents) if not p.exists()]
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, out)
        if tracker is not None:
            for directory in missing_parents:
                tracker.record_created_dir(directory)
            tracker.record_created_file(out)
