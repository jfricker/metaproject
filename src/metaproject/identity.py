"""Project identity (`.metaproject/config.json`) — read, write, and manifest fallback (R-ID-1…4).

The project config lives at `.metaproject/config.json` (`IDENTITY_FILE`). The legacy
root `.metaproject.json` (`LEGACY_IDENTITY_FILE`) is still read when the new file is
absent; only `metaproject doctor` moves it (R-CFG-2, R-CFG-7).

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

IDENTITY_FILE = ".metaproject/config.json"
LEGACY_IDENTITY_FILE = ".metaproject.json"


def _is_store_dir(project_dir: Path) -> bool:
    """Is `project_dir/.metaproject` the user-global store directory (R-CFG-4)?

    The store (`~/.metaproject`, or `METAPROJECT_CONFIG_DIR`) holds a user-level config,
    never a project's, so it must not anchor `$HOME` as a project.
    """
    from metaproject.config import get_config_dir

    try:
        return (Path(project_dir) / ".metaproject").resolve() == get_config_dir()
    except OSError:
        return False


def _has_new(project_dir: Path) -> bool:
    return (Path(project_dir) / IDENTITY_FILE).is_file() and not _is_store_dir(project_dir)


def legacy_config(project_dir: Path) -> Optional[Path]:
    """The legacy root `.metaproject.json` when it is a regular file, else None."""
    path = Path(project_dir) / LEGACY_IDENTITY_FILE
    return path if path.is_file() else None


def has_config(project_dir: Path) -> bool:
    """Does `project_dir` carry a project config, at the new path or the legacy one?

    A `.metaproject/` directory without `config.json` does not count (R-CFG-3).
    """
    return _has_new(project_dir) or legacy_config(project_dir) is not None


def config_path(project_dir: Path) -> Path:
    """The project config to read or update (R-CFG-2): `.metaproject/config.json` when it
    exists, else an existing legacy `.metaproject.json`, else the new path (absent)."""
    if _has_new(project_dir):
        return Path(project_dir) / IDENTITY_FILE
    return legacy_config(project_dir) or Path(project_dir) / IDENTITY_FILE


def is_legacy_only(project_dir: Path) -> bool:
    """Only the legacy `.metaproject.json` is present (what doctor migrates)."""
    return legacy_config(project_dir) is not None and not _has_new(project_dir)


@dataclass(frozen=True)
class Identity:
    """A project's scaffolded identity, as recorded in `.metaproject/config.json`."""

    title: str
    description: str
    author: str
    created: date
    metaproject_version: str


def find_repo_root(start: Path) -> Optional[Path]:
    """The nearest ancestor-or-self holding a `.git` entry (a directory, or a file for a
    worktree or submodule), or None outside any repository. Never runs git."""
    current = Path(start).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists() or (candidate / ".git").is_symlink():
            return candidate
    return None


def find_project_root(start: Path) -> Optional[Path]:
    """The nearest ancestor-or-self holding a project config (`has_config`).

    The walk stops at the git boundary, inclusive: the first directory holding `.git`
    is the last one examined, so a stray project config above a repository never
    captures it. Outside any repository the walk runs to the filesystem root. Presence
    is the test, not validity: a corrupt nearest file still anchors the root.
    """
    current = Path(start).resolve()
    for candidate in (current, *current.parents):
        if has_config(candidate):
            return candidate
        if (candidate / ".git").exists() or (candidate / ".git").is_symlink():
            return None
    return None


def resolve_project_dir(explicit: Optional[Path], cwd: Optional[Path] = None) -> Path:
    """The project a command acts on: an explicit path as given, else the nearest anchor.

    An explicit `--dir`/`PROJECT` always wins and is never walked upward. Without one,
    the nearest project config above `cwd` (default: the current directory) is the
    project; when there is none, `cwd` itself, exactly as before nested projects.
    """
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    here = Path(cwd if cwd is not None else Path.cwd()).resolve()
    return find_project_root(here) or here


def read_settings(project_dir: Path) -> dict:
    """The raw project config object, or {} when absent, unreadable or not an object."""
    try:
        data = json.loads(config_path(project_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


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
    """Read the project config. Tolerant: a missing file or invalid content is None.

    Never raises — a corrupt or hand-edited identity file degrades to "no identity",
    not a crash.
    """
    path = config_path(project_dir)
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
    """Write the project config as pretty, sorted-key JSON with a trailing newline.

    Written where `config_path` points: a new project gets `.metaproject/config.json`;
    an existing legacy file is updated in place, never moved (R-CFG-5). Keys the
    identity does not own (`commands`, `e2e_port`, anything an operator added) are kept
    from an existing, parseable file; only the identity fields are replaced.
    """
    path = config_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        existing = {}
    data = existing if isinstance(existing, dict) else {}
    data |= {
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
    """Title/description fallback when no project config exists (R-ID-3).

    Order: `README.md` (first `# ` heading / first paragraph) -> `pyproject.toml`
    `[project]` -> `package.json` -> title-cased directory name. `.metaproject/docs/INTENT.md`
    (or legacy `docs/INTENT.md` / `intent.md`) is never read. A title is used only when non-empty
    and not an unfilled placeholder.
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


def update_settings(project_dir: Path, keys: tuple[str, ...], value: object) -> Optional[str]:
    """Set a nested key in the project config only when it is absent; never overwrite.

    Written where `config_path` points (a legacy file is updated in place). Returns a
    warning string, writing nothing, when the file is missing, unreadable, not a JSON
    object, or an intermediate key is not an object; None otherwise (including when the
    final key is already present, which is left as it is).
    """
    path = config_path(project_dir)
    if not path.is_file():
        return f"{path} does not exist; nothing was written."
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return f"{path} could not be read as JSON; nothing was written."
    if not isinstance(data, dict):
        return f"{path} is not a JSON object; nothing was written."
    node = data
    for key in keys[:-1]:
        child = node.get(key)
        if child is None and key not in node:
            break
        if not isinstance(child, dict):
            return f"{path}: '{key}' is not an object; nothing was written."
        node = child
    else:
        if keys[-1] in node:
            return None
    node = data
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return None
