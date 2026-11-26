"""Per-skill bridge entries that make `.agents/skills/<name>` visible to a harness.

metaproject installs bundled skills as real files in `<home>/.agents/skills/<name>/`
(the source). Claude Code reads only `.claude/skills/`, so for each bundled skill this
module writes one entry at `<project>/.claude/skills/<name>`: a relative symlink to the
source, or a copy. An entry is owned only when the caller's records list it. Records are
passed in and returned (the caller persists them in the skills manifest).

This is the only module that writes under `.claude/skills/<name>`. It imports nothing
from `skills`.
"""

import copy
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple

from metaproject.exceptions import MetaProjectError
from metaproject.git import read_only_query
from metaproject.identity import read_settings
from metaproject.treeops import _fingerprint, _remove, file_map, swap_tree

if TYPE_CHECKING:
    from metaproject.scaffold import TransactionalTracker


@dataclass(frozen=True)
class TargetSpec:
    dir: Path


TARGETS: Dict[str, TargetSpec] = {"claude": TargetSpec(dir=Path(".claude/skills"))}

CURRENT = "current"
MISSING = "missing"
OUTDATED = "outdated"
MODIFIED = "modified"
FOREIGN = "foreign"

SYMLINK = "symlink"
COPY = "copy"
AUTO = "auto"

ABSENT = "absent"
DIRECTORY = "directory"
LEGACY = "legacy"
FOREIGN_LINK = "foreign_link"
FOREIGN_FILE = "foreign_file"

STAGING_DIR = Path(".agents") / ".metaproject-skills-tmp"
DENIED_NOTICE = (
    "bridge entries not written (permission denied); run `metaproject skills sync` "
    "outside the sandbox"
)


@dataclass
class BridgeReport:
    target: str
    mode: str
    mode_reason: str
    notice: Optional[str] = None
    entries: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    removed: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    lost: List[str] = field(default_factory=list)


# ---------------------------------------------------------------- configuration


def configured_targets(project_dir: Path) -> Tuple[List[str], bool, List[str]]:
    """`(targets, recorded, warnings)` from `skills.targets`; absent means `["claude"]`."""
    skills = read_settings(Path(project_dir)).get("skills")
    raw = skills.get("targets") if isinstance(skills, dict) else None
    if raw is None:
        return ["claude"], False, []
    if not isinstance(raw, list):
        return ["claude"], True, ['skills.targets must be a list; using ["claude"]']
    targets: List[str] = []
    warnings: List[str] = []
    for item in raw:
        if isinstance(item, str) and item in TARGETS:
            if item not in targets:
                targets.append(item)
        else:
            warnings.append(f"unknown skills target {item!r} ignored")
    return targets, True, warnings


def configured_link_mode(project_dir: Path) -> Tuple[str, List[str]]:
    """`(mode, warnings)` from `skills.link_mode`; anything invalid is `auto`."""
    skills = read_settings(Path(project_dir)).get("skills")
    raw = skills.get("link_mode") if isinstance(skills, dict) else None
    if raw is None:
        return AUTO, []
    if raw in (AUTO, SYMLINK, COPY):
        return raw, []
    return AUTO, [f"unknown skills.link_mode {raw!r} ignored; using auto"]


def _is_windows() -> bool:
    """The single platform seam; tests patch this, never `os.name`."""
    return os.name == "nt"


_MODE_CACHE: Dict[str, Tuple[str, str]] = {}


def _clear_mode_cache() -> None:
    _MODE_CACHE.clear()


def resolve_link_mode(project_dir: Path) -> Tuple[str, str]:
    """`(mode, reason)`: an explicit `link_mode`, else detected from the platform and git."""
    project_dir = Path(project_dir)
    explicit, _ = configured_link_mode(project_dir)
    if explicit in (SYMLINK, COPY):
        return explicit, "skills.link_mode"
    key = str(project_dir.resolve())
    if key not in _MODE_CACHE:
        if _is_windows():
            _MODE_CACHE[key] = (COPY, "Windows")
        else:
            value = read_only_query(project_dir, "core.symlinks")
            if value is not None and value.lower() == "false":
                _MODE_CACHE[key] = (COPY, "core.symlinks=false")
            else:
                _MODE_CACHE[key] = (SYMLINK, "default")
    return _MODE_CACHE[key]


# ---------------------------------------------------------------- shapes and states


def link_text(entry: Path, source: Path) -> str:
    return os.path.relpath(Path(source).resolve(), Path(entry).parent.resolve())


def claude_skills_shape(project_dir: Path, home: Path) -> str:
    """What `<project>/.claude/skills` is: absent, a directory, a legacy link, or foreign."""
    project_dir, home = Path(project_dir), Path(home)
    path = project_dir / TARGETS["claude"].dir
    source_dir = home / ".agents" / "skills"
    if path.is_symlink():
        return LEGACY if path.resolve() == source_dir.resolve() else FOREIGN_LINK
    if not path.exists():
        return ABSENT
    if path.is_dir():
        return DIRECTORY
    expected = os.path.relpath(source_dir.resolve(), (project_dir / ".claude").resolve())
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return FOREIGN_FILE
    return LEGACY if text == expected else FOREIGN_FILE


def lost_user_skills(source_dir: Path, bundled_names: Iterable[str]) -> List[str]:
    """User skills in `source_dir` (non-dot dirs with a SKILL.md) that are not bundled."""
    source_dir = Path(source_dir)
    bundled = set(bundled_names)
    if not source_dir.is_dir():
        return []
    return sorted(
        child.name
        for child in source_dir.iterdir()
        if child.is_dir()
        and not child.name.startswith(".")
        and child.name not in bundled
        and (child / "SKILL.md").is_file()
    )


def _file_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None


def classify_entry(
    entry: Path,
    source: Path,
    record: Optional[Dict[str, Any]],
    resolved_mode: str,
    explicit_mode: Optional[str],
) -> Tuple[str, bool]:
    """`(state, identical)` for one bridge entry (R-BRG-9/11/12)."""
    entry, source = Path(entry), Path(source)
    present = entry.exists() or entry.is_symlink()
    if not record:
        if not present:
            return MISSING, False
        if entry.is_symlink():
            identical = entry.resolve() == source.resolve()
        elif entry.is_dir():
            identical = file_map(entry) == file_map(source)
        else:
            identical = False
        return FOREIGN, identical
    if not present:
        return MISSING, False
    if record.get("mode") == SYMLINK:
        link = record.get("link")
        if entry.is_symlink():
            text = os.readlink(entry)
            if text == link and text == link_text(entry, source) and entry.exists():
                return (OUTDATED if explicit_mode == COPY else CURRENT), False
            return OUTDATED, False
        if entry.is_file() and _file_text(entry) == link:
            return OUTDATED, False
        return MODIFIED, False
    if entry.is_symlink() or not entry.is_dir():
        return MODIFIED, False
    current = file_map(entry)
    if current == file_map(source):
        return (OUTDATED if explicit_mode == SYMLINK else CURRENT), False
    if current == record.get("files"):
        return OUTDATED, False
    return MODIFIED, False


def drift_note(state: str, mode: Optional[str]) -> Optional[str]:
    if state == MODIFIED and mode == COPY:
        return "differs from .agents/skills; Copilot loads .agents/skills instead"
    return None


def shadowing(project_dir: Path, names: Iterable[str]) -> List[str]:
    out: List[str] = []
    for name in names:
        if (Path.home() / ".claude" / "skills" / name).exists():
            out.append(f"~/.claude/skills/{name} overrides the project's {name} in Claude Code")
        if (Path(project_dir) / ".github" / "skills" / name).exists():
            out.append(f"{name}: .github/skills/{name} is loaded before .agents/skills by Copilot")
    return out


# ---------------------------------------------------------------- writing


def _project_key(project_dir: Path, home: Path) -> str:
    try:
        rel = Path(project_dir).resolve().relative_to(Path(home).resolve()).as_posix()
    except ValueError:
        rel = Path(project_dir).name
    return "_home" if rel in (".", "") else rel


def _write_copy(
    project_dir: Path,
    home: Path,
    name: str,
    entry: Path,
    source: Path,
    tracker: "Optional[TransactionalTracker]",
    warnings: List[str],
) -> Optional[Dict[str, Any]]:
    files = file_map(source)
    done = swap_tree(
        source,
        entry,
        files,
        _fingerprint(entry),
        staging=home / STAGING_DIR,
        key=f"bridges/{_project_key(project_dir, home)}/{name}",
        tracker=tracker,
        warnings=warnings,
        root=home,
    )
    if not done:
        warnings.append(f"{name}: bridge entry changed while writing; skipped")
        return None
    return {"mode": COPY, "files": files}


def _write_entry(
    project_dir: Path,
    home: Path,
    name: str,
    entry: Path,
    source: Path,
    mode: str,
    tracker: "Optional[TransactionalTracker]",
    warnings: List[str],
) -> Optional[Dict[str, Any]]:
    """Write one entry in `mode`; PermissionError propagates to stop the pass."""
    if mode == COPY:
        return _write_copy(project_dir, home, name, entry, source, tracker, warnings)
    existed = entry.exists() or entry.is_symlink()
    text = link_text(entry, source)
    if existed:
        _remove(entry)
    try:
        os.symlink(text, entry)
    except PermissionError:
        raise
    except OSError as exc:
        warnings.append(f"{name}: could not create a symlink ({exc}); wrote a copy instead")
        return _write_copy(project_dir, home, name, entry, source, tracker, warnings)
    if tracker is not None and not existed:
        tracker.record_created_file(entry)
    return {"mode": SYMLINK, "link": text}


def _ensure_skills_dir(
    project_dir: Path, new: Dict[str, Any], tracker: "Optional[TransactionalTracker]"
) -> bool:
    """Create `.claude/skills` (and `.claude`) when absent; True when anything changed."""
    skills_dir = project_dir / TARGETS["claude"].dir
    if skills_dir.is_dir():
        return False
    changed = False
    claude = project_dir / ".claude"
    made_claude = not claude.exists()
    if made_claude:
        claude.mkdir()
        if tracker is not None:
            tracker.record_created_dir(claude)
    skills_dir.mkdir()
    if tracker is not None:
        tracker.record_created_dir(skills_dir)
    for item in (".claude/skills", ".claude") if made_claude else (".claude/skills",):
        if item not in new["created"]:
            new["created"].append(item)
            changed = True
    return changed


def _safe_name(name: Any) -> bool:
    """True only for a plain single-component entry name (manifest data is untrusted)."""
    if not isinstance(name, str) or not name or name in (".", ".."):
        return False
    if name.startswith(".") or "\0" in name or "/" in name or "\\" in name:
        return False
    if os.sep in name or (os.altsep and os.altsep in name):
        return False
    return Path(name).name == name


def _confined(entry: Path, skills_dir: Path) -> bool:
    """The entry's parent must really be `skills_dir` (the entry itself may be a link)."""
    try:
        return entry.parent.resolve() == skills_dir.resolve()
    except (OSError, RuntimeError):
        return False


def _outside_project(project_dir: Path, skills: bool = True) -> Optional[str]:
    """A notice when `.claude` (or `.claude/skills`) resolves outside the project."""
    root = Path(project_dir).resolve()
    paths = [Path(project_dir) / ".claude"]
    if skills:
        paths.append(Path(project_dir) / TARGETS["claude"].dir)
    for path in paths:
        try:
            inside = path.resolve().is_relative_to(root)
        except (OSError, RuntimeError):
            inside = False
        if not inside:
            return (
                f".claude/skills resolves outside the project ({path}); bridge entries not changed"
            )
    return None


def _unsafe_warning(name: Any) -> str:
    return f"ignored unsafe bridge entry name {name!r} in the skills manifest"


def _rmdir_if_created(path: Path, rel: str, new: Dict[str, Any]) -> bool:
    if rel not in new["created"]:
        return False
    if path.is_dir() and not path.is_symlink() and not any(path.iterdir()):
        path.rmdir()
        new["created"].remove(rel)
        return True
    return False


def _pass(
    project_dir: Path,
    home: Path,
    names: List[str],
    records: Dict[str, Any],
    manifest_newer: bool,
    update: bool,
    force: Iterable[str],
    dry_run: bool,
    tracker: "Optional[TransactionalTracker]",
    inspect: bool,
) -> Tuple[BridgeReport, Dict[str, Any]]:
    project_dir, home = Path(project_dir), Path(home)
    force = set(force)
    targets, _recorded, warnings = configured_targets(project_dir)
    explicit, mode_warnings = configured_link_mode(project_dir)
    explicit_mode = None if explicit == AUTO else explicit
    mode, reason = resolve_link_mode(project_dir)
    report = BridgeReport("claude", mode, reason, warnings=warnings + mode_warnings)
    if manifest_newer:
        report.notice = "skills manifest written by a newer metaproject; bridge entries not changed"
        return report, records
    shape = claude_skills_shape(project_dir, home)
    if shape == LEGACY:
        report.notice = (
            "legacy link: .claude/skills is a directory symlink; run `metaproject doctor`"
        )
        return report, records
    if shape in (FOREIGN_LINK, FOREIGN_FILE):
        report.notice = (
            f"{project_dir / TARGETS['claude'].dir} is not a metaproject-managed directory; "
            "bridge entries not written"
        )
        return report, records

    outside = _outside_project(project_dir)
    if outside is not None:
        report.notice = outside
        return report, records

    writing = not dry_run and not inspect
    new: Dict[str, Any] = copy.deepcopy(records) if records else {}
    changed = False
    if not isinstance(new.get("created"), list):
        new["created"] = []
    if not isinstance(new.get("entries"), dict):
        new["entries"] = {}
    kept_created = [c for c in new["created"] if c in (".claude/skills", ".claude")]
    if kept_created != new["created"]:
        new["created"] = kept_created
        changed = True
    for bad in [n for n in new["entries"] if not _safe_name(n)]:
        report.warnings.append(_unsafe_warning(bad))
        del new["entries"][bad]
        changed = True
    for key in [k for k, v in new["entries"].items() if not isinstance(v, dict)]:
        del new["entries"][key]
        changed = True
    safe_names: List[str] = []
    for name in names:
        if _safe_name(name):
            safe_names.append(name)
        else:
            msg = _unsafe_warning(name)
            if msg not in report.warnings:
                report.warnings.append(msg)
    names = safe_names
    source_dir = home / ".agents" / "skills"
    skills_dir = project_dir / TARGETS["claude"].dir

    if "claude" not in targets:
        for name, rec in list(new["entries"].items()):
            entry = skills_dir / name
            if not _confined(entry, skills_dir):
                report.warnings.append(
                    f"{name}: bridge entry resolves outside .claude/skills; skipped"
                )
                continue
            state, _ = classify_entry(entry, source_dir / name, rec, mode, explicit_mode)
            note = drift_note(state, rec.get("mode"))
            if state == MISSING:
                report.entries[name] = {"state": state, "action": None, "note": note}
                if writing:
                    del new["entries"][name]
                    changed = True
            elif state in (CURRENT, OUTDATED):
                action = None if inspect else "removed"
                if writing:
                    try:
                        _remove(entry)
                    except PermissionError:
                        report.notice = DENIED_NOTICE
                        break
                    del new["entries"][name]
                    changed = True
                if not inspect:
                    report.removed.append(name)
                report.entries[name] = {"state": state, "action": action, "note": note}
            else:
                if not inspect:
                    report.warnings.append(f"{name}: modified; left in place")
                report.entries[name] = {
                    "state": state,
                    "action": None if inspect else "skipped",
                    "note": note,
                }
        if writing and report.notice is None:
            if _rmdir_if_created(skills_dir, ".claude/skills", new):
                changed = True
            if _rmdir_if_created(project_dir / ".claude", ".claude", new):
                changed = True
        return report, (new if changed and writing else records)

    write_mode = explicit_mode or mode
    for name in names:
        source = source_dir / name
        entry = skills_dir / name
        rec = new["entries"].get(name)
        if not _confined(entry, skills_dir):
            report.warnings.append(f"{name}: bridge entry resolves outside .claude/skills; skipped")
            report.entries[name] = {"state": None, "action": "skipped", "note": None}
            continue
        state, identical = classify_entry(entry, source, rec, mode, explicit_mode)
        info: Dict[str, Any] = {
            "state": state,
            "action": None,
            "note": drift_note(state, rec.get("mode") if rec else None),
        }
        report.entries[name] = info
        record_only = False
        want = False
        if state == MISSING:
            want = True
        elif state == OUTDATED:
            want = update
        elif state == MODIFIED:
            want = name in force
        elif state == FOREIGN:
            if name in force and identical:
                record_only = True
            elif name in force:
                want = True
            else:
                if identical:
                    info["note"] = "identical"
                    report.warnings.append(
                        f"{name}: .claude/skills/{name} exists, is identical to the source "
                        f"and is not recorded; use --force {name} to record it"
                    )
                else:
                    report.warnings.append(
                        f"{name}: .claude/skills/{name} exists and is not managed by "
                        f"metaproject; skipped (--force {name} replaces it)"
                    )
                info["action"] = "skipped"
        if inspect or not (want or record_only):
            continue
        if record_only:
            info["action"] = "recorded"
            if writing:
                if entry.is_symlink():
                    new["entries"][name] = {"mode": SYMLINK, "link": os.readlink(entry)}
                else:
                    new["entries"][name] = {"mode": COPY, "files": file_map(entry)}
                changed = True
            continue
        action = "created" if state in (MISSING,) else "updated"
        if not source.is_dir():
            report.warnings.append(f"{name}: source missing under .agents/skills; skipped")
            info["action"] = "skipped"
            continue
        if dry_run:
            info["action"] = action
            continue
        try:
            if _ensure_skills_dir(project_dir, new, tracker):
                changed = True
            written = _write_entry(
                project_dir, home, name, entry, source, write_mode, tracker, report.warnings
            )
        except PermissionError:
            report.notice = DENIED_NOTICE
            info["action"] = None
            break
        if written is None:
            info["action"] = "skipped"
            continue
        new["entries"][name] = written
        changed = True
        info["action"] = action
    return report, (new if changed and writing else records)


def inspect_bridges(
    project_dir: Path,
    home: Path,
    bridged_names: Iterable[str],
    records: Dict[str, Any],
    manifest_newer: bool,
) -> BridgeReport:
    """The state of every bridge entry; writes nothing."""
    report, _ = _pass(
        project_dir,
        home,
        list(bridged_names),
        records,
        manifest_newer,
        False,
        (),
        False,
        None,
        True,
    )
    return report


def sync_bridges(
    project_dir: Path,
    home: Path,
    bridged_names: Iterable[str],
    records: Dict[str, Any],
    *,
    manifest_newer: bool,
    update: bool,
    force: Iterable[str] = (),
    dry_run: bool = False,
    tracker: "Optional[TransactionalTracker]" = None,
) -> Tuple[BridgeReport, Dict[str, Any]]:
    """Create/rewrite/remove bridge entries; returns the report and the new records."""
    return _pass(
        project_dir,
        home,
        list(bridged_names),
        records,
        manifest_newer,
        update,
        force,
        dry_run,
        tracker,
        False,
    )


def migrate_legacy_link(
    project_dir: Path,
    home: Path,
    bundled_names: Iterable[str],
    *,
    tracker: "Optional[TransactionalTracker]" = None,
) -> Tuple[BridgeReport, Dict[str, Any]]:
    """Replace a legacy `.claude/skills` link with a real directory of bridge entries.

    On any failure the created directory is removed and the original link (or file) is
    restored exactly, then a `MetaProjectError` is raised.
    """
    project_dir, home = Path(project_dir), Path(home)
    names = list(bundled_names)
    if claude_skills_shape(project_dir, home) != LEGACY:
        raise MetaProjectError(f"{project_dir / TARGETS['claude'].dir} is not a legacy link")
    outside = _outside_project(project_dir, skills=False)
    if outside is not None:
        raise MetaProjectError(outside)
    lost = lost_user_skills(home / ".agents" / "skills", names)
    path = project_dir / TARGETS["claude"].dir
    link_snapshot: Optional[str] = None
    bytes_snapshot: Optional[bytes] = None
    if path.is_symlink():
        link_snapshot = os.readlink(path)
    else:
        bytes_snapshot = path.read_bytes()
    try:
        path.unlink()
        path.mkdir()
        if tracker is not None:
            tracker.record_created_dir(path)
        report, records = sync_bridges(
            project_dir,
            home,
            names,
            {"created": [".claude/skills"], "entries": {}},
            manifest_newer=False,
            update=True,
            tracker=tracker,
        )
        if report.notice is not None:
            raise MetaProjectError(report.notice)
    except Exception as exc:
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            elif path.exists() or path.is_symlink():
                path.unlink()
            if link_snapshot is not None:
                os.symlink(link_snapshot, path)
            else:
                path.write_bytes(bytes_snapshot or b"")
        except OSError as restore_exc:
            raise MetaProjectError(
                f"could not migrate {path} ({exc}) and could not restore it: {restore_exc}"
            ) from exc
        raise MetaProjectError(f"could not migrate {path}: {exc}") from exc
    report.lost = lost
    return report, records
