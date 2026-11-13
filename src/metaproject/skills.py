"""The bundled project skills: their installation, inspection and update in a project.

Two kinds of skill ship as package data: the metaproject skill (`skill/`), which teaches
an agent to drive this CLI, and the SDLC cycle skills (`sdlc_skills/<name>/`). They are
not installed globally. `metaproject new`, `backfill` and `adopt` copy each one into the
project's own `.agents/skills/<name>/`, where the `.claude/skills` symlink makes them
visible to Claude Code by bare name, and they are committed with the project.

Every pass records what it wrote in an install manifest,
`.agents/skills/.metaproject-skills.json`: per skill, the release that wrote it and the
sha256 of each of its files. That record is what makes an update safe. A skill whose
files still hash to its recorded manifest (or to a known earlier release, from the
`skill_history.json` ledger) is a pristine copy and may be replaced; anything else is the
project's own edit and is never touched unless the operator names it with `--force`.

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

from metaproject.exceptions import MetaProjectError

if TYPE_CHECKING:
    from metaproject.scaffold import TransactionalTracker

SKILL_NAME = "metaproject"

MANIFEST_NAME = ".metaproject-skills.json"
MANIFEST_VERSION = 1
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

# The hash of anything inside a skill that is not a regular file. It matches no
# sha256 digest, so such a skill never classifies as pristine.
NON_REGULAR = "symlink"


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

    `notice` is set only for an R-SKL-5 refusal, in which case nothing was examined or
    written. `warnings` carries everything else worth saying (an unreadable manifest, a
    staging directory that could not be removed).
    """

    target: Path
    states: Dict[str, str] = field(default_factory=dict)
    notice: Optional[str] = None
    statuses: Tuple[SkillStatus, ...] = ()
    manifest_state: Optional[str] = None
    warnings: Tuple[str, ...] = ()

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


def hash_content(data: bytes) -> str:
    """sha256 of one file's bytes; text has `\\r\\n` normalised so autocrlf is not an edit."""
    if b"\0" not in data:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def file_map(directory: Path) -> Dict[str, str]:
    """`{posix relpath: sha256}` for every non-junk entry under `directory`, sorted.

    The same filter applies to the bundle and to an installed copy, so an extra file in
    the installed directory makes the maps differ. A symlink or other non-regular entry
    hashes as `NON_REGULAR`, which never matches. Symlinked directories are not entered.
    """
    from metaproject.templates import is_junk_file_name

    directory = Path(directory)
    out: Dict[str, str] = {}
    for root, dirs, files in os.walk(directory, followlinks=False):
        root_path = Path(root)
        rel_root = root_path.relative_to(directory)
        kept = []
        for name in dirs:
            if is_junk_file_name(name):
                continue
            if (root_path / name).is_symlink():
                out[(rel_root / name).as_posix()] = NON_REGULAR
                continue
            kept.append(name)
        dirs[:] = kept
        for name in files:
            if is_junk_file_name(name):
                continue
            path = root_path / name
            rel = (rel_root / name).as_posix()
            if path.is_symlink() or not path.is_file():
                out[rel] = NON_REGULAR
            else:
                out[rel] = hash_content(path.read_bytes())
    return dict(sorted(out.items()))


def skill_digest(files: Dict[str, str]) -> str:
    """One digest for a whole file map; used only for ledger lookups."""
    body = "\n".join(f"{rel}\t{digest}" for rel, digest in sorted(files.items()))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _fingerprint(dest: Path) -> Tuple:
    """What `dest` looks like now, for the classify-then-swap (TOCTOU) comparison."""
    if dest.is_symlink():
        return ("symlink", os.readlink(dest))
    if not dest.exists():
        return ("absent",)
    if not dest.is_dir():
        return ("other",)
    return ("dir", tuple(file_map(dest).items()))


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


def load_manifest(target: Path) -> Tuple[str, Dict[str, Dict]]:
    """The manifest's load state and, when usable, its per-skill entries.

    `absent` (a legacy install) and `unreadable` (bad JSON or wrong shape) both yield no
    entries; `newer` (a format version above this release's) yields none either, so the
    caller falls back to legacy classification and never rewrites the file.
    """
    path = manifest_path(target)
    if not path.exists() and not path.is_symlink():
        return MANIFEST_ABSENT, {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return MANIFEST_UNREADABLE, {}
    if not isinstance(data, dict):
        return MANIFEST_UNREADABLE, {}
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        return MANIFEST_UNREADABLE, {}
    if version > MANIFEST_VERSION:
        return MANIFEST_NEWER, {}
    entries = data.get("skills")
    if not isinstance(entries, dict) or not all(_valid_entry(e) for e in entries.values()):
        return MANIFEST_UNREADABLE, {}
    return MANIFEST_PRESENT, {name: dict(entry) for name, entry in entries.items()}


def render_manifest(entries: Dict[str, Dict]) -> str:
    """Deterministic manifest text: sorted keys, indent 2, trailing newline."""
    body = {"version": MANIFEST_VERSION, "skills": entries}
    return json.dumps(body, indent=2, sort_keys=True) + "\n"


def _write_manifest(
    target: Path, entries: Dict[str, Dict], tracker: "Optional[TransactionalTracker]"
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


def inspect_project_skills(project_dir: Path) -> SkillsReport:
    """Classify every bundled skill in a project. Read-only: writes nothing at all."""
    target = project_skills_dir(project_dir)
    if target.refusal is not None:
        return SkillsReport(target=target.path, notice=target.refusal)
    manifest_state, entries = load_manifest(target.path)
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
    return SkillsReport(
        target=target.path,
        states={status.name: status.state for status in statuses},
        statuses=statuses,
        manifest_state=manifest_state,
        warnings=(warning,) if warning else (),
    )


# --------------------------------------------------------------------- writing


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _copy_tree(source_dir: Path, dest: Path) -> None:
    for item in _bundled_files(source_dir):
        out = dest / item.relative_to(source_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, out)


def _recover_staging(target: Path) -> None:
    """Undo a crash mid-swap: restore `<name>.old` whose destination is gone, then clean."""
    staging = target.parent / STAGING_NAME
    if not staging.exists():
        return
    for old in staging.glob("*.old"):
        dest = target / old.name[: -len(".old")]
        if not dest.exists() and not dest.is_symlink():
            target.mkdir(parents=True, exist_ok=True)
            os.rename(old, dest)
    shutil.rmtree(staging, ignore_errors=True)


def _record_tree(dest: Path, tracker: "TransactionalTracker") -> None:
    tracker.record_created_dir(dest)
    for item in sorted(dest.rglob("*")):
        if item.is_dir():
            tracker.record_created_dir(item)
        else:
            tracker.record_created_file(item)


def _replace_skill(
    skill: BundledSkill,
    dest: Path,
    bundle: Dict[str, str],
    snapshot: Tuple,
    staging: Path,
    tracker: "Optional[TransactionalTracker]",
    warnings: List[str],
) -> bool:
    """Swap the bundled copy into `dest` atomically. False when `dest` changed meanwhile.

    The new copy is built and verified in staging, the old one is renamed aside, the
    new one renamed in; a failed rename puts the old one back and raises.
    """
    staging.mkdir(parents=True, exist_ok=True)
    new = staging / f"{skill.name}.new"
    old = staging / f"{skill.name}.old"
    for leftover in (new, old):
        if leftover.exists() or leftover.is_symlink():
            _remove(leftover)
    _copy_tree(skill.source_dir, new)
    if file_map(new) != bundle:
        _remove(new)
        raise MetaProjectError(f"the staged copy of skill {skill.name} does not match the bundle")

    if _fingerprint(dest) != snapshot:
        _remove(new)
        return False
    existed = dest.exists() or dest.is_symlink()
    if existed:
        os.rename(dest, old)
    try:
        os.rename(new, dest)
    except OSError as exc:
        if existed:
            try:
                os.rename(old, dest)
            except OSError:
                pass
        raise MetaProjectError(f"could not replace skill {skill.name}: {exc}") from exc
    if existed:
        try:
            _remove(old)
        except OSError as exc:
            warnings.append(f"could not remove the previous copy of {skill.name}: {exc}")
    if tracker is not None and not existed:
        _record_tree(dest, tracker)
    return True


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
    writes nothing (no manifest, no staging directory). An R-SKL-5 refusal writes
    nothing at all. Raises `MetaProjectError` for an unknown `force` name (before any
    write), for a manifest written by a newer metaproject when `update` is set, and for
    an I/O failure after rolling the failing skill back.
    """
    target = project_skills_dir(project_dir)
    if target.refusal is not None:
        return SkillsReport(target=target.path, notice=target.refusal)

    declared = bundled_skills()
    names = {skill.name for skill in declared}
    unknown = sorted(set(force) - names)
    if unknown:
        raise MetaProjectError(
            "unknown skill name(s) for --force: "
            + ", ".join(unknown)
            + f" (bundled: {', '.join(sorted(names))})"
        )

    manifest_state, entries = load_manifest(target.path)
    if manifest_state == MANIFEST_NEWER and update:
        raise MetaProjectError(
            f"{manifest_path(target.path)} was written by a newer metaproject; upgrade "
            "metaproject before syncing skills (the file was left untouched)."
        )
    history = load_history()
    running = running_release()
    warnings: List[str] = []
    warning = _manifest_warning(manifest_state, writing=not dry_run)
    if warning:
        warnings.append(warning)

    staging = target.path.parent / STAGING_NAME
    new_entries: Dict[str, Dict] = {name: dict(entry) for name, entry in entries.items()}
    statuses: List[SkillStatus] = []
    states: Dict[str, str] = {}
    forced = set(force)

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
    finally:
        if not dry_run:
            try:
                if manifest_state != MANIFEST_NEWER and (
                    new_entries != entries or manifest_state == MANIFEST_UNREADABLE
                ):
                    if new_entries or manifest_path(target.path).exists():
                        _write_manifest(target.path, new_entries, tracker)
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
                    if staging.exists():
                        warnings.append(f"could not remove {staging}")

    return SkillsReport(
        target=target.path,
        states=states,
        statuses=tuple(statuses),
        manifest_state=manifest_state,
        warnings=tuple(warnings),
    )


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
