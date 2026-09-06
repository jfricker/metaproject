"""Installation of the bundled Claude Code skill into the operator's skill directory.

The skill teaches an agent to drive this CLI. It ships as package data so a plain
`pip install metaproject` carries it, and `metaproject init` copies it into
`~/.claude/skills/metaproject/` where Claude Code discovers it.
"""

import filecmp
import importlib.resources
import os
import shutil
from pathlib import Path
from typing import Dict, List

from metaproject.exceptions import MetaProjectError

SKILL_NAME = "metaproject"

# Install states reported back to the caller.
INSTALLED = "installed"  # nothing was there; the skill was written
UPDATED = "updated"  # an older or edited copy was overwritten
CURRENT = "current"  # the installed copy already matches the bundled one
STALE = "stale"  # the installed copy differs and --force was withheld


def get_bundled_skill_dir() -> Path:
    """Return the filesystem path to the skill shipped inside this package."""
    try:
        traversable = importlib.resources.files("metaproject").joinpath("skill")
        return Path(str(traversable))
    except Exception as exc:
        raise MetaProjectError(f"Failed to access bundled skill resources: {exc}") from exc


def get_skill_install_dir() -> Path:
    """Return where the skill should be installed.

    `METAPROJECT_SKILL_DIR` overrides the default so tests and unusual setups never have
    to write into the operator's real `~/.claude`.
    """
    override = os.environ.get("METAPROJECT_SKILL_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".claude" / "skills" / SKILL_NAME).resolve()


def _bundled_files(source_dir: Path) -> List[Path]:
    return sorted(item for item in source_dir.rglob("*") if item.is_file())


def is_skill_current(source_dir: Path, target_dir: Path) -> bool:
    """Report whether target_dir already holds a byte-identical copy of the skill."""
    if not target_dir.exists():
        return False
    for item in _bundled_files(source_dir):
        dest = target_dir / item.relative_to(source_dir)
        if not dest.is_file() or not filecmp.cmp(item, dest, shallow=False):
            return False
    return True


def install_skill(target_dir: Path | None = None, force: bool = False) -> Dict[str, object]:
    """Install the bundled skill, refusing to clobber a divergent copy without force.

    A divergent copy is usually just an older release, but it may be the operator's own
    edit, so overwriting it is their call rather than a silent side effect of `init`.
    Returns the install state and the files written.
    """
    source_dir = get_bundled_skill_dir()
    if not source_dir.exists():
        raise MetaProjectError(f"Bundled skill directory does not exist: {source_dir}")

    destination = (target_dir or get_skill_install_dir()).expanduser()
    existed = destination.exists()

    if is_skill_current(source_dir, destination):
        return {"state": CURRENT, "target_dir": destination, "files": []}

    if existed and not force:
        return {"state": STALE, "target_dir": destination, "files": []}

    written: List[Path] = []
    for item in _bundled_files(source_dir):
        dest = destination / item.relative_to(source_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)
        written.append(dest)

    return {
        "state": UPDATED if existed else INSTALLED,
        "target_dir": destination,
        "files": written,
    }
