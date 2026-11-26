"""The bundled project skills: their installation, inspection and update in a project.

Two kinds of skill ship as package data: the metaproject skill (`skill/`), which teaches
an agent to drive this CLI, and the SDLC cycle skills (`sdlc_skills/<name>/`). They are
not installed globally. `metaproject new`, `backfill` and `adopt` copy each one into the
project's own `.agents/skills/<name>/` (the source), and they are committed with the
project. The source is always installed; nothing about `.claude/skills` can refuse it.

Claude Code reads only `.claude/skills/`, so after the source pass a bridge pass
(`bridges.py`, the only writer there) adds one entry per bundled skill at
`.claude/skills/<name>`: a relative symlink to the source, or a copy. There is no
directory symlink; the user's own skills in `.claude/skills` are never touched. The
entries the pass owns are recorded in the manifest under `bridges`.

Every pass records what it wrote in an install manifest,
`.agents/skills/.metaproject-skills.json`: per skill, the release that wrote it and the
sha256 of each of its files. That record is what makes an update safe. A skill whose
files still hash to its recorded manifest (or to a known earlier release, from the
`skill_history.json` ledger) is a pristine copy and may be replaced; anything else is the
project's own edit and is never touched unless the operator names it with `--force`.

A sub-project whose `.metaproject/config.json` declares `"skills": {"location": "root"}` keeps
no copy of its own: its skills (and the manifest) live in its home — the nearest ancestor
project that does not itself declare `"root"`, else the git root — and its
`.claude/skills/<name>` entries are bridges up to the home's `.agents/skills/<name>`,
recorded in the home's manifest under the sub-project's relative path.

`new`, `backfill` and `adopt` stay create-only (`update=False`); `metaproject skills
sync` and doctor's fix also replace outdated, unmodified skills. This module is the only
one that writes under `.agents/skills/<name>/`, through one write path.
"""

import hashlib
import importlib.resources
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

from metaproject import bridges as bridge_ops
from metaproject.exceptions import MetaProjectError
from metaproject.treeops import (  # noqa: F401  (re-exported for callers and tests)
    NON_REGULAR,
    _copy_tree,
    _fingerprint,
    _record_tree,
    _remove,
    file_map,
    hash_content,
    recover_staging,
    swap_tree,
)

if TYPE_CHECKING:
    from metaproject.scaffold import TransactionalTracker

SKILL_NAME = "metaproject"

MANIFEST_NAME = ".metaproject-skills.json"
MANIFEST_VERSION = 2
# Staging lives beside `.agents/skills`, never inside it, so a half-built copy is never
# discoverable as a skill.
STAGING_NAME = ".metaproject-skills-tmp"
HISTORY_RESOURCE = "skill_history.json"

# Per-skill states (the state of the project before any write).
CURRENT = "current"  # the installed copy matches this release's bundle
OUTDATED = "outdated"  # a pristine copy of an earlier release; safe to replace
MODIFIED = "modified"  # differs from every known release; the project's own edit
MISSING = "missing"  # not installed

# Actions one pass took (or, under dry_run, would take) per skill.
INSTALLED = "installed"  # nothing was there; the skill was written
UPDATED = "updated"  # an outdated copy was replaced
FORCED = "forced"  # a copy was replaced because the operator named it with --force
KEPT = "kept"  # left as it was
RECORDED = "recorded"  # left as it was, and its manifest entry (re)written

# Manifest load states.
MANIFEST_PRESENT = "present"
MANIFEST_ABSENT = "absent"
MANIFEST_UNREADABLE = "unreadable"
MANIFEST_NEWER = "newer"


@dataclass(frozen=True)
class BundledSkill:
    """One skill shipped in the wheel: its name and the directory holding its files."""

    name: str
    source_dir: Path


@dataclass(frozen=True)
class SkillsTarget:
    """Where a project's skills go, or why none may be written there.

    `home` is the project whose `.agents/skills` is `path`: the project itself, or —
    for a sub-project declaring `"skills": {"location": "root"}` — the ancestor that
    keeps the one shared copy (`delegated`). `link` is always None (shim).
    """

    path: Path
    refusal: Optional[str] = None
    home: Optional[Path] = None
    delegated: bool = False
    link: Optional[str] = None
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillStatus:
    """One bundled skill as classified in one project, and what a pass did to it."""

    name: str
    state: str
    installed_release: Optional[str]
    basis: str  # manifest | history | bundle | none
    changed: Tuple[str, ...] = ()
    note: Optional[str] = None
    action: Optional[str] = None


@dataclass(frozen=True)
class SkillsReport:
    """What one pass found and did (or would do, under `dry_run`), per skill name.

    `notice` is set only for the no-home refusal, in which case nothing was examined or
    written. `bridges` holds the per-target bridge report and `shadowing` the skills a
    user-level or Copilot directory overrides. `warnings` carries everything else worth
    saying (an unreadable manifest, a staging directory that could not be removed).
    """

    target: Path
    states: Dict[str, str] = field(default_factory=dict)
    notice: Optional[str] = None
    statuses: Tuple[SkillStatus, ...] = ()
    manifest_state: Optional[str] = None
    warnings: Tuple[str, ...] = ()
    # `project` (the default) or `root` (skills kept by an ancestor; see SkillsTarget).
    location: str = "project"
    home: Optional[Path] = None
    # Shim: always None.
    link: Optional[str] = None
    bridges: Dict[str, "bridge_ops.BridgeReport"] = field(default_factory=dict)
    shadowing: List[str] = field(default_factory=list)

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


def skills_in(skill_dir: Path, sdlc_dir: Path) -> Tuple[BundledSkill, ...]:
    """The skills found in one `skill/` + `sdlc_skills/` layout, sorted by name.

    `metaproject` from `skill_dir` when that directory exists, plus every
    `sdlc_dir/<name>/` that has a `SKILL.md`. Shared with the ledger generator, which
    reads the same layout out of an archived release.
    """
    found: List[BundledSkill] = []
    if skill_dir.is_dir():
        found.append(BundledSkill(SKILL_NAME, skill_dir))
    if sdlc_dir.is_dir():
        for child in sdlc_dir.iterdir():
            if child.is_dir() and (child / "SKILL.md").is_file():
                found.append(BundledSkill(child.name, child))
    return tuple(sorted(found, key=lambda skill: skill.name))


def bundled_skills() -> Tuple[BundledSkill, ...]:
    """The single declaration of the project skills (R-SKL-1), sorted by name.

    `metaproject` from `skill/`, plus every `sdlc_skills/<name>/` that has a `SKILL.md`.
    """
    return skills_in(get_bundled_skill_dir(), get_bundled_sdlc_skills_dir())


def legacy_global_skill_dir() -> Path:
    """Where `init` used to install the metaproject skill. Only `doctor` still looks.

    Computed at call time so tests can point `HOME` somewhere harmless.
    """
    return Path.home() / ".claude" / "skills" / SKILL_NAME


# ------------------------------------------------------------------------- hashing


def _bundled_files(source_dir: Path) -> List[Path]:
    from metaproject.templates import is_junk_file_name

    return sorted(
        item
        for item in source_dir.rglob("*")
        if item.is_file()
        and not any(is_junk_file_name(part) for part in item.relative_to(source_dir).parts)
    )


def skill_digest(files: Dict[str, str]) -> str:
    """One digest for a whole file map; used only for ledger lookups."""
    body = "\n".join(f"{rel}\t{digest}" for rel, digest in sorted(files.items()))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------- release parsing


def running_release() -> str:
    """The release this process is, read at call time so tests can stand in for it."""
    import metaproject

    return metaproject.__version__


def _parse_release(value: object) -> Optional[Tuple[int, ...]]:
    if not isinstance(value, str):
        return None
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return None


def is_newer_release(candidate: object, running: str) -> bool:
    """True when `candidate` parses as a release later than `running`; else False."""
    a, b = _parse_release(candidate), _parse_release(running)
    return a is not None and b is not None and a > b


# ------------------------------------------------------------------------ ledger


def parse_history(text: str) -> Dict[str, Dict[str, str]]:
    """`{skill name: {digest: release}}` from the ledger's JSON text."""
    data = json.loads(text)
    out: Dict[str, Dict[str, str]] = {}
    for name, entries in (data.get("skills") or {}).items():
        out[name] = {entry["digest"]: entry["release"] for entry in entries}
    return out


@lru_cache(maxsize=1)
def load_history() -> Dict[str, Dict[str, str]]:
    """The digests of every previously released skill, from package data."""
    try:
        text = (
            importlib.resources.files("metaproject")
            .joinpath(HISTORY_RESOURCE)
            .read_text(encoding="utf-8")
        )
        return parse_history(text)
    except Exception:
        return {}


# ---------------------------------------------------------------------- manifest


def manifest_path(target: Path) -> Path:
    return Path(target) / MANIFEST_NAME


def _valid_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    files = entry.get("files")
    return (
        isinstance(entry.get("release"), str)
        and isinstance(files, dict)
        and all(isinstance(k, str) and isinstance(v, str) for k, v in files.items())
    )


@dataclass(frozen=True)
class Manifest:
    """The install manifest as loaded: its state, per-skill entries and bridge entries."""

    state: str
    skills: Dict[str, Dict] = field(default_factory=dict)
    bridges: Dict[str, Dict] = field(default_factory=dict)


def load_manifest(target: Path) -> Manifest:
    """The manifest's load state and, when usable, its skill and bridge entries.

    `absent` (a legacy install) and `unreadable` (bad JSON or wrong shape) both yield no
    entries; `newer` (a format version above this release's) yields none either, so the
    caller falls back to legacy classification and never rewrites the file. A version 1
    file has no bridges.
    """
    path = manifest_path(target)
    if not path.exists() and not path.is_symlink():
        return Manifest(MANIFEST_ABSENT)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Manifest(MANIFEST_UNREADABLE)
    if not isinstance(data, dict):
        return Manifest(MANIFEST_UNREADABLE)
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        return Manifest(MANIFEST_UNREADABLE)
    if version > MANIFEST_VERSION:
        return Manifest(MANIFEST_NEWER)
    entries = data.get("skills")
    if not isinstance(entries, dict) or not all(_valid_entry(e) for e in entries.values()):
        return Manifest(MANIFEST_UNREADABLE)
    bridges: Dict[str, Dict] = {}
    if version >= 2:
        raw = data.get("bridges", {})
        if not isinstance(raw, dict):
            return Manifest(MANIFEST_UNREADABLE)
        bridges = {name: dict(b) if isinstance(b, dict) else b for name, b in raw.items()}
    return Manifest(
        MANIFEST_PRESENT, {name: dict(entry) for name, entry in entries.items()}, bridges
    )


def render_manifest(manifest: "Manifest | Dict[str, Dict]", bridges: Optional[Dict] = None) -> str:
    """Deterministic manifest text: sorted keys, indent 2, trailing newline."""
    if isinstance(manifest, Manifest):
        skills, kept = manifest.skills, manifest.bridges
    else:
        skills, kept = manifest, {}
    body = {
        "version": MANIFEST_VERSION,
        "skills": skills,
        "bridges": kept if bridges is None else bridges,
    }
    return json.dumps(body, indent=2, sort_keys=True) + "\n"


def _write_manifest(
    target: Path,
    entries: "Manifest | Dict[str, Dict]",
    tracker: "Optional[TransactionalTracker]",
) -> None:
    """Write the manifest atomically (temp file in the same directory, then replace)."""
    path = manifest_path(target)
    text = render_manifest(entries)
    existed = path.exists()
    if existed:
        try:
            if path.read_text(encoding="utf-8") == text:
                return
        except (OSError, ValueError):
            pass
        if tracker is not None:
            tracker.record_modified_file(path)
    target.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target, prefix=".metaproject-skills.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise
    if tracker is not None and not existed:
        tracker.record_created_file(path)


# -------------------------------------------------------------------- target dir


LOCATION_PROJECT = "project"
LOCATION_ROOT = "root"


def skills_location(project_dir: Path) -> Tuple[str, Optional[str]]:
    """`skills.location` from `.metaproject/config.json`, and a warning when it is invalid.

    An enum, never a path: absent, `"project"` or anything invalid is `"project"`
    (today's behaviour); an invalid value or shape also yields a warning, never raises.
    """
    from metaproject.identity import IDENTITY_FILE, read_settings

    settings = read_settings(project_dir).get("skills")
    if settings is None:
        return LOCATION_PROJECT, None
    if not isinstance(settings, dict):
        return LOCATION_PROJECT, f'{IDENTITY_FILE} "skills" is not an object; ignored.'
    value = settings.get("location", LOCATION_PROJECT)
    if value in (LOCATION_PROJECT, LOCATION_ROOT):
        return value, None
    return (
        LOCATION_PROJECT,
        f'{IDENTITY_FILE} skills.location {value!r} is not "project" or "root"; '
        "skills stay in this project.",
    )


def skills_home(project_dir: Path) -> Optional[Path]:
    """The directory whose `.agents/skills` holds this project's skills.

    Without `skills.location: "root"`, the project itself. With it, the nearest strict
    ancestor (up to and including the repository root) that has `.metaproject/config.json`
    and does not itself declare `"root"`; failing that, the repository root (which may
    be the project itself, making `"root"` at the top a no-op); failing that, None.
    """
    from metaproject.identity import find_repo_root, has_config

    project_dir = Path(project_dir).resolve()
    if skills_location(project_dir)[0] != LOCATION_ROOT:
        return project_dir
    repo_root = find_repo_root(project_dir)
    if repo_root is None:
        return None
    if repo_root != project_dir:
        for ancestor in project_dir.parents:
            if has_config(ancestor) and (skills_location(ancestor)[0] != LOCATION_ROOT):
                return ancestor
            if ancestor == repo_root:
                break
    return repo_root


def _link_refusal(owner_dir: Path, agents_skills: Path) -> Optional[str]:
    """Why `owner_dir/.claude/skills` would hide `agents_skills` from Claude Code (R-SKL-5).

    None when the link is absent or a symlink resolving to `agents_skills`.
    """
    claude_skills = Path(owner_dir) / ".claude" / "skills"
    if claude_skills.is_symlink():
        if claude_skills.resolve() != agents_skills.resolve():
            return (
                f"{claude_skills} is a symlink to {claude_skills.resolve()}, not this "
                "project's .agents/skills; project skills were not installed."
            )
    elif claude_skills.exists():
        return (
            f"{claude_skills} is a real directory, not a symlink to .agents/skills; "
            "project skills were not installed."
        )
    return None


def link_target(project_dir: Path, home: Path) -> str:
    """The relative `.claude/skills` link text from `project_dir` to `home/.agents/skills`.

    Both ends are resolved first, so a symlinked path component never skews it.
    """
    agents = (Path(home) / ".agents" / "skills").resolve()
    return os.path.relpath(agents, start=(Path(project_dir) / ".claude").resolve())


def _leftover_warning(project_dir: Path) -> Optional[str]:
    own = Path(project_dir) / ".agents" / "skills"
    names = [skill.name for skill in bundled_skills() if (own / skill.name).exists()]
    if not names:
        return None
    return (
        f"skills.location is root, but {own} still holds copies of: {', '.join(names)}; "
        "they are no longer used or updated (remove them yourself)."
    )


def project_skills_dir(project_dir: Path) -> SkillsTarget:
    """The project's skills directory (the source), or why there is none.

    Ordinarily the project's own `.agents/skills`; with `skills.location: "root"` the
    home's (see `skills_home`). The only refusal is `root` with no ancestor project or
    git root. `.claude/skills` never refuses an install; the bridge pass copes with it.
    """
    project_dir = Path(project_dir)
    own = project_dir / ".agents" / "skills"
    location, invalid = skills_location(project_dir)
    warnings: Tuple[str, ...] = (invalid,) if invalid else ()
    if location != LOCATION_ROOT:
        return SkillsTarget(own, None, project_dir, warnings=warnings)

    home = skills_home(project_dir)
    if home is None:
        return SkillsTarget(
            own,
            'skills.location is "root" but there is no ancestor project or git root; '
            "project skills were not installed.",
            None,
            True,
        )
    if home == project_dir.resolve():
        return SkillsTarget(own, None, project_dir, warnings=warnings)

    leftover = _leftover_warning(project_dir)
    if leftover:
        warnings += (leftover,)
    return SkillsTarget(home / ".agents" / "skills", None, home, True, None, warnings)


def ensure_skills_link(
    project_dir: Path,
    home: Path,
    dry_run: bool = False,
    tracker: "Optional[TransactionalTracker]" = None,
) -> Optional[str]:
    """Point a delegating sub-project's `.claude/skills` at `home/.agents/skills`.

    Creates the link when absent, or re-points the default link to the sub-project's
    own `.agents/skills`. Never touches a real directory or a link anywhere else.
    Returns what was (or, under `dry_run`, would be) done, or None when nothing was.
    """
    project_dir = Path(project_dir)
    claude_dir = project_dir / ".claude"
    claude_skills = claude_dir / "skills"
    own = project_dir / ".agents" / "skills"
    wanted = link_target(project_dir, home)
    if claude_skills.is_symlink():
        if claude_skills.resolve() != own.resolve():
            return None
        verb = "re-pointed"
    elif claude_skills.exists():
        return None
    else:
        verb = "created"
    if dry_run:
        return f"would be {verb}: {claude_skills} -> {wanted}"
    if not claude_dir.exists():
        claude_dir.mkdir(parents=True, exist_ok=True)
        if tracker is not None:
            tracker.record_created_dir(claude_dir)
    if verb == "re-pointed":
        claude_skills.unlink()
    claude_skills.symlink_to(wanted)
    if tracker is not None and verb == "created":
        tracker.record_created_file(claude_skills)
    return f"{verb}: {claude_skills} -> {wanted}"


def _target_report(target: SkillsTarget, **kwargs) -> SkillsReport:
    return SkillsReport(
        target=target.path,
        location=LOCATION_ROOT if target.delegated else LOCATION_PROJECT,
        home=target.home,
        **kwargs,
    )


# ---------------------------------------------------------------- classification


def classify_skill(
    skill: BundledSkill,
    dest: Path,
    entry: Optional[Dict],
    history: Dict[str, str],
    running: str,
    bundle: Optional[Dict[str, str]] = None,
) -> SkillStatus:
    """The state of one installed skill, evaluated in the design's fixed order.

    1. absent → missing. 2. installed == bundle → current. 3. installed == its recorded
    manifest and that release is newer than this one → current (never downgraded).
    4. installed == its recorded manifest, or its digest is a known release → outdated.
    5. anything else → modified.
    """
    bundle = file_map(skill.source_dir) if bundle is None else bundle
    if not dest.exists() and not dest.is_symlink():
        return SkillStatus(skill.name, MISSING, None, "none", tuple(sorted(bundle)))
    recorded = entry.get("files") if entry else None
    recorded_release = entry.get("release") if entry else None
    if dest.is_symlink():
        return SkillStatus(
            skill.name,
            MODIFIED,
            recorded_release,
            "manifest" if entry else "none",
            (),
            f"skill directory is a symlink to {os.readlink(dest)}",
        )
    if not dest.is_dir():
        return SkillStatus(
            skill.name,
            MODIFIED,
            recorded_release,
            "manifest" if entry else "none",
            (),
            "not a directory",
        )
    installed = file_map(dest)
    changed = tuple(
        sorted(rel for rel in set(bundle) | set(installed) if bundle.get(rel) != installed.get(rel))
    )
    if installed == bundle:
        if recorded == bundle:
            return SkillStatus(skill.name, CURRENT, recorded_release, "manifest")
        return SkillStatus(skill.name, CURRENT, running, "bundle")
    if recorded is not None and installed == recorded:
        if is_newer_release(recorded_release, running):
            return SkillStatus(
                skill.name,
                CURRENT,
                recorded_release,
                "manifest",
                changed,
                f"installed by newer release {recorded_release}",
            )
        return SkillStatus(skill.name, OUTDATED, recorded_release, "manifest", changed)
    known = history.get(skill_digest(installed))
    if known is not None:
        return SkillStatus(skill.name, OUTDATED, known, "history", changed)
    return SkillStatus(
        skill.name, MODIFIED, recorded_release, "manifest" if entry else "none", changed
    )


def _is_newer_guard(status: SkillStatus) -> bool:
    return status.state == CURRENT and status.basis == "manifest" and status.note is not None


def _manifest_warning(state: str, writing: bool) -> Optional[str]:
    if state == MANIFEST_UNREADABLE:
        tail = "it will be rewritten" if writing else "skills were classified without it"
        return f"{MANIFEST_NAME} could not be read; {tail}."
    if state == MANIFEST_NEWER:
        return (
            f"{MANIFEST_NAME} was written by a newer metaproject; skills were classified "
            "without it and it was left untouched."
        )
    return None


def _project_key(project_dir: Path, home: Path) -> str:
    """The manifest key for a project's bridges: its path under the home, `.` for the home."""
    try:
        rel = Path(project_dir).resolve().relative_to(Path(home).resolve()).as_posix()
    except ValueError:
        return Path(project_dir).name
    return rel or "."


def _bridge_records(manifest: Manifest, key: str) -> Dict:
    entry = manifest.bridges.get(key)
    records = entry.get("claude") if isinstance(entry, dict) else None
    return records if isinstance(records, dict) else {}


def inspect_project_skills(project_dir: Path) -> SkillsReport:
    """Classify every bundled skill in a project. Read-only: writes nothing at all."""
    target = project_skills_dir(project_dir)
    if target.refusal is not None:
        return _target_report(target, notice=target.refusal, warnings=target.warnings)
    loaded = load_manifest(target.path)
    manifest_state, entries = loaded.state, loaded.skills
    history = load_history()
    running = running_release()
    statuses = tuple(
        classify_skill(
            skill,
            target.path / skill.name,
            entries.get(skill.name),
            history.get(skill.name, {}),
            running,
        )
        for skill in bundled_skills()
    )
    warning = _manifest_warning(manifest_state, writing=False)
    warnings = target.warnings + ((warning,) if warning else ())
    names = [skill.name for skill in bundled_skills()]
    home = target.home if target.home is not None else Path(project_dir)
    records = _bridge_records(loaded, _project_key(Path(project_dir), home))
    bridge_report = bridge_ops.inspect_bridges(
        Path(project_dir), home, names, records, manifest_state == MANIFEST_NEWER
    )
    return _target_report(
        target,
        states={status.name: status.state for status in statuses},
        statuses=statuses,
        manifest_state=manifest_state,
        warnings=warnings,
        bridges={"claude": bridge_report},
        shadowing=bridge_ops.shadowing(Path(project_dir), names),
    )


# --------------------------------------------------------------------- writing


def _recover_staging(target: Path) -> None:
    """Undo a crash mid-swap: restore `<name>.old` whose destination is gone, then clean."""
    recover_staging(target.parent / STAGING_NAME, target, target.parent.parent)


def _replace_skill(
    skill: BundledSkill,
    dest: Path,
    bundle: Dict[str, str],
    snapshot: Tuple,
    staging: Path,
    tracker: "Optional[TransactionalTracker]",
    warnings: List[str],
) -> bool:
    """Swap the bundled copy into `dest` atomically. False when `dest` changed meanwhile."""
    return swap_tree(
        skill.source_dir,
        dest,
        bundle,
        snapshot,
        staging,
        skill.name,
        tracker,
        warnings,
        staging.parent.parent,
    )


def _ensure_target(target: Path, tracker: "Optional[TransactionalTracker]") -> None:
    missing = [p for p in reversed([target, *target.parents]) if not p.exists()]
    target.mkdir(parents=True, exist_ok=True)
    if tracker is not None:
        for directory in missing:
            tracker.record_created_dir(directory)


def sync_project_skills(
    project_dir: Path,
    *,
    update: bool = True,
    force: Sequence[str] = (),
    dry_run: bool = False,
    tracker: "Optional[TransactionalTracker]" = None,
) -> SkillsReport:
    """Install missing skills and, with `update`, replace outdated unmodified ones.

    Modified skills are never touched unless named in `force`. The manifest is recorded
    for every skill written or already current. `dry_run` reports the same actions and
    writes nothing (no manifest, no staging directory). The no-home refusal writes
    nothing at all. Raises `MetaProjectError` for an unknown `force` name (before any
    write), for a manifest written by a newer metaproject when `update` is set, and for
    an I/O failure after rolling the failing skill back.
    """
    target = project_skills_dir(project_dir)
    if target.refusal is not None:
        return _target_report(target, notice=target.refusal, warnings=target.warnings)

    declared = bundled_skills()
    names = {skill.name for skill in declared}
    unknown = sorted(set(force) - names)
    if unknown:
        raise MetaProjectError(
            "unknown skill name(s) for --force: "
            + ", ".join(unknown)
            + f" (bundled: {', '.join(sorted(names))})"
        )

    loaded = load_manifest(target.path)
    manifest_state, entries = loaded.state, loaded.skills
    if manifest_state == MANIFEST_NEWER and update:
        raise MetaProjectError(
            f"{manifest_path(target.path)} was written by a newer metaproject; upgrade "
            "metaproject before syncing skills (the file was left untouched)."
        )
    history = load_history()
    running = running_release()
    warnings: List[str] = list(target.warnings)
    warning = _manifest_warning(manifest_state, writing=not dry_run)
    if warning:
        warnings.append(warning)

    staging = target.path.parent / STAGING_NAME
    new_entries: Dict[str, Dict] = {name: dict(entry) for name, entry in entries.items()}
    statuses: List[SkillStatus] = []
    states: Dict[str, str] = {}
    forced = set(force)
    bridge_report: Optional["bridge_ops.BridgeReport"] = None
    new_bridges: Dict[str, Dict] = {
        k: dict(v) if isinstance(v, dict) else v for k, v in loaded.bridges.items()
    }
    names_list = [skill.name for skill in declared]
    home = target.home if target.home is not None else Path(project_dir)
    key = _project_key(Path(project_dir), home)

    if not dry_run:
        _recover_staging(target.path)
    try:
        for skill in declared:
            dest = target.path / skill.name
            bundle = file_map(skill.source_dir)
            snapshot = _fingerprint(dest)
            status = classify_skill(
                skill,
                dest,
                entries.get(skill.name),
                history.get(skill.name, {}),
                running,
                bundle,
            )
            plain_current = status.state == CURRENT and not _is_newer_guard(status)
            if status.state == MISSING:
                action = INSTALLED
            elif skill.name in forced and not plain_current:
                action = FORCED
            elif status.state == OUTDATED and update:
                action = UPDATED
            elif plain_current:
                recorded = entries.get(skill.name, {}).get("files")
                action = KEPT if recorded == bundle else RECORDED
            else:
                action = KEPT

            if action in (INSTALLED, UPDATED, FORCED) and not dry_run:
                _ensure_target(target.path, tracker)
                swapped = _replace_skill(skill, dest, bundle, snapshot, staging, tracker, warnings)
                if not swapped:
                    status = replace(
                        status, state=MODIFIED, note="changed during sync; left untouched"
                    )
                    action = KEPT
            if action in (INSTALLED, UPDATED, FORCED, RECORDED):
                new_entries[skill.name] = {"release": running, "files": bundle}

            statuses.append(replace(status, action=action))
            if action == INSTALLED:
                states[skill.name] = INSTALLED
            elif action in (UPDATED, FORCED):
                states[skill.name] = UPDATED
            else:
                states[skill.name] = status.state
        bridge_report, new_records = bridge_ops.sync_bridges(
            Path(project_dir),
            home,
            names_list,
            _bridge_records(loaded, key),
            manifest_newer=manifest_state == MANIFEST_NEWER,
            update=update,
            force=force,
            dry_run=dry_run,
            tracker=tracker,
        )
        if not dry_run and manifest_state != MANIFEST_NEWER:
            slot = dict(new_bridges.get(key) or {})
            if new_records and (new_records.get("entries") or new_records.get("created")):
                slot["claude"] = new_records
            else:
                slot.pop("claude", None)
            if slot:
                new_bridges[key] = slot
            else:
                new_bridges.pop(key, None)
    finally:
        if not dry_run:
            try:
                if manifest_state != MANIFEST_NEWER:
                    if new_entries or new_bridges or manifest_path(target.path).exists():
                        _write_manifest(
                            target.path,
                            Manifest(MANIFEST_PRESENT, new_entries, new_bridges),
                            tracker,
                        )
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
                    if staging.exists():
                        warnings.append(f"could not remove {staging}")

    return _target_report(
        target,
        states=states,
        statuses=tuple(statuses),
        manifest_state=manifest_state,
        warnings=tuple(warnings),
        bridges={"claude": bridge_report} if bridge_report is not None else {},
        shadowing=bridge_ops.shadowing(Path(project_dir), names_list),
    )


def migrate_legacy_skills_link(project_dir: Path) -> "bridge_ops.BridgeReport":
    """Replace a legacy whole-directory `.claude/skills` link with per-skill bridge entries.

    Records the created entries in the manifest. Raises `MetaProjectError` when the
    manifest was written by a newer metaproject or the migration fails (the link is
    then restored exactly).
    """
    target = project_skills_dir(project_dir)
    if target.refusal is not None:
        raise MetaProjectError(target.refusal)
    loaded = load_manifest(target.path)
    if loaded.state == MANIFEST_NEWER:
        raise MetaProjectError(
            f"{manifest_path(target.path)} was written by a newer metaproject; upgrade "
            "metaproject before migrating (the file was left untouched)."
        )
    home = target.home if target.home is not None else Path(project_dir)
    names = [skill.name for skill in bundled_skills()]
    report, records = bridge_ops.migrate_legacy_link(Path(project_dir), home, names)
    key = _project_key(Path(project_dir), home)
    new_bridges: Dict[str, Dict] = {
        k: dict(v) if isinstance(v, dict) else v for k, v in loaded.bridges.items()
    }
    slot = dict(new_bridges.get(key) or {})
    slot["claude"] = records
    new_bridges[key] = slot
    _write_manifest(target.path, Manifest(MANIFEST_PRESENT, loaded.skills, new_bridges), None)
    return report


def install_project_skills(
    project_dir: Path,
    dry_run: bool = False,
    tracker: "Optional[TransactionalTracker]" = None,
) -> SkillsReport:
    """Install every declared skill whose directory is absent (`new`, `backfill`, `adopt`).

    Create-only (R-SKL-3/4): an existing skill directory is never written into; it is
    reported `current`, `outdated` or `modified`. The manifest is recorded for installed
    and already-current skills. Directories and files created are recorded on `tracker`
    so a failed `new` rolls them back. `dry_run` writes nothing.
    """
    return sync_project_skills(project_dir, update=False, dry_run=dry_run, tracker=tracker)
