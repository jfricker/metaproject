"""Project identity (`.metaproject.json`) — read, write, and manifest fallback (R-ID-1…4).

`identity.py` intentionally imports nothing from `universe.py` (and only reaches into
`variables.py` via a deferred, in-function import) so that `variables.project_variables`
can import this module at call time without creating an import cycle.
"""

import json
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional, Tuple

IDENTITY_FILE = ".metaproject.json"


@dataclass(frozen=True)
class Identity:
    """A project's scaffolded identity, as recorded in `.metaproject.json`."""

    title: str
    description: str
    author: str
    created: date
    metaproject_version: str


def _strip_placeholder(text: object) -> str:
    """Treat an unfilled `{Placeholder}` or `<Placeholder>` value as absent.

    Mirrors the tolerance a freshly scaffolded template still carries (e.g.
    `{Problem description}` or `<Title>`) so it is never fed back in as real content.
    """
    if not isinstance(text, str):
        return ""
    clean = text.strip()
    if clean.startswith("{") and clean.endswith("}"):
        return ""
    if clean.startswith("<") and clean.endswith(">"):
        return ""
    return clean


def read_identity(project_dir: Path) -> Optional[Identity]:
    """Read `.metaproject.json`. Tolerant: a missing file or invalid content is None.

    Never raises — a corrupt or hand-edited identity file degrades to "no identity",
    not a crash.
    """
    path = Path(project_dir) / IDENTITY_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        title = data["title"]
        description = data["description"]
        author = data["author"]
        created_raw = data["created"]
        metaproject_version = data["metaproject_version"]
        if not all(
            isinstance(value, str)
            for value in (title, description, author, created_raw, metaproject_version)
        ):
            return None
        created = date.fromisoformat(created_raw)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None

    return Identity(
        title=title,
        description=description,
        author=author,
        created=created,
        metaproject_version=metaproject_version,
    )


def write_identity(project_dir: Path, identity: Identity) -> Path:
    """Write `.metaproject.json` as pretty, sorted-key JSON with a trailing newline."""
    path = Path(project_dir) / IDENTITY_FILE
    data = {
        "title": identity.title,
        "description": identity.description,
        "author": identity.author,
        "created": identity.created.isoformat(),
        "metaproject_version": identity.metaproject_version,
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _from_readme(path: Path) -> Tuple[str, str]:
    """First `# ` heading (title, never truncated) and the paragraph directly under it.

    The description search stops at the next heading: a `README.md` whose title is
    immediately followed by a subsection (no body paragraph of its own) has no
    description, rather than picking up a paragraph from somewhere further down the
    file.
    """
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return "", ""

    title = ""
    title_index: Optional[int] = None
    in_code_fence = False
    for index, line in enumerate(lines):
        clean = line.strip()
        if clean.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if clean.startswith("# "):
            candidate = _strip_placeholder(clean[2:].strip())
            if candidate:
                title = candidate
                title_index = index
                break

    if title_index is None:
        return "", ""

    description = ""
    in_code_fence = False
    for line in lines[title_index + 1 :]:
        clean = line.strip()
        if not clean:
            continue
        if clean.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if clean.startswith("#"):
            break
        description = _strip_placeholder(clean)
        break

    return title, description


def _titlecase(name: str) -> str:
    """Title-case a slug-like identifier without importing `variables` at module scope."""
    from metaproject.variables import titlecase

    return titlecase(name)


def _from_pyproject(path: Path) -> Tuple[str, str]:
    """`[project]` `name`/`description` from `pyproject.toml`."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return "", ""

    project = data.get("project") if isinstance(data, dict) else None
    if not isinstance(project, dict):
        return "", ""

    name = _strip_placeholder(project.get("name"))
    description = _strip_placeholder(project.get("description"))
    title = _titlecase(name) if name else ""
    return title, description


def _from_package_json(path: Path) -> Tuple[str, str]:
    """`name`/`description` from `package.json`."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "", ""

    if not isinstance(data, dict):
        return "", ""

    name = _strip_placeholder(data.get("name"))
    description = _strip_placeholder(data.get("description"))
    title = _titlecase(name) if name else ""
    return title, description


def fallback_identity(project_dir: Path) -> Tuple[str, str]:
    """Title/description fallback when no `.metaproject.json` exists (R-ID-3).

    Order: `README.md` (first `# ` heading / first paragraph) -> `pyproject.toml`
    `[project]` -> `package.json` -> title-cased directory name. `intent.md` is never
    read. A title is used only when non-empty and not an unfilled placeholder.
    """
    project_dir = Path(project_dir)

    readme = project_dir / "README.md"
    if readme.is_file():
        title, description = _from_readme(readme)
        if title:
            return title, description

    pyproject = project_dir / "pyproject.toml"
    if pyproject.is_file():
        title, description = _from_pyproject(pyproject)
        if title:
            return title, description

    package_json = project_dir / "package.json"
    if package_json.is_file():
        title, description = _from_package_json(package_json)
        if title:
            return title, description

    return _titlecase(project_dir.name), ""
