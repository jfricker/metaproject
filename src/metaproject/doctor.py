"""`metaproject doctor` — diagnose and repair a stale installed environment.

Everything metaproject installs outside the package (live template store,
user config name and ``learn.targets``, per-project ``.metaproject/config.json``
anchors and their location, cycle documents, project skills and hook scripts) can lag
behind an upgraded package. Doctor checks each against the installed version and
repairs what's stale — behind one confirmation per check (per project, for the project
checks), never silently. Fixes always call the
module that owns the concern, so doctor and ``init``/``new`` cannot drift apart
(spec R-DR-11).

The checks, in order: template-store layout, template store, config file name, config,
orphaned global skill, project identity, project config, project docs, skills legacy link,
skills targets, project skills, project agents, skill shadowing, project hook scripts.
Layout runs first so a store whose cycle templates are still at the root is migrated, not
re-seeded beside them.

`run_checks(..., project=...)` scopes the run to one operator-named project: only
that project's identity, config, docs, skills and hook-script checks run, and none of the
environment-wide ones.
"""

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from rich.console import Console

from metaproject import (
    __version__,
    bridges,
    catalog,
    config,
    db,
    deliverables,
    git,
    hooks,
    identity,
    skills,
    subagents,
    templates,
)
from metaproject.config import Config
from metaproject.exceptions import MetaProjectError
from metaproject.extras import LazyModule

questionary = LazyModule("questionary", "Doctor's confirmations")

STORE_LAYOUT_COMMIT = (
    "chore(templates): relocate doc templates to .metaproject.template/docs.template/"
)

_STORE_GITKEEP_MOVES: Tuple[Tuple[str, str], ...] = (
    (
        ".metaproject.template/docs.template/.gitkeep",
        "docs.template/.gitkeep",
    ),
    (
        ".metaproject.template/docs.template/archive.template/.gitkeep",
        "docs.template/archive.template/.gitkeep",
    ),
)


@dataclass(frozen=True)
class _MigrationPlan:
    moves: List[Tuple[str, str]] = field(default_factory=list)
    removals: List[str] = field(default_factory=list)
    mkdirs: List[str] = field(default_factory=list)
    empty_subdirs: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)


@dataclass
class CheckResult:
    """One doctor check's diagnosis and fix outcome.

    ``fixed`` is None when no fix was attempted (dry-run, or the operator declined);
    False/True record an attempted fix's outcome.
    """

    name: str
    healthy: bool
    findings: List[str] = field(default_factory=list)
    fix_summary: str = ""
    fixed: Optional[bool] = None
    # Findings no fix resolves (a move conflict, a stale skill): reported, never acted on.
    report_only: List[str] = field(default_factory=list)


def _relative_files(root: Path) -> set[Path]:
    """Junk-filtered set of file paths under root, relative to it.

    Skips OS/editor junk via the shared rule and `.git` (the live store is a git
    repository; its internals are not template content).
    """
    if not root.exists():
        return set()
    return {
        rel
        for item in root.rglob("*")
        if item.is_file()
        and ".git" not in (rel := item.relative_to(root)).parts
        and not any(templates.is_junk_file_name(p) for p in rel.parts)
    }


def check_templates(cfg: Config) -> tuple[List[str], str]:
    """Missing bundle templates in the live store; extras reported, never touched.

    The store is git-backed and user-mutable via `learn apply`, so the fix only ever
    *adds* missing templates (spec R-DR-2).
    """
    store = Path(cfg.templates_dir)
    bundled = _relative_files(templates.get_bundled_templates_dir())
    live = _relative_files(store)
    # A template still at its legacy location is the layout check's finding, not missing;
    # seeding it here would put a blank copy beside the real one (or flag a redundant .gitkeep).
    plan = _store_plan(store)
    relocating = {Path(dest) for dest, _ in plan.moves}
    legacy = {Path(src) for _, src in plan.moves} | {Path(src) for src in plan.removals}
    missing = sorted(bundled - live - relocating)
    extras = sorted(live - bundled - legacy)

    findings = [f"missing from store: {p}" for p in missing]
    findings += [f"extra in store (kept, learned or hand-added): {p}" for p in extras]
    fix_summary = f"seed {len(missing)} missing template(s) via seed_templates (no overwrites)"
    return findings, fix_summary


def _is_extra_note(finding: str) -> bool:
    """Extras are information, not a defect: the store is the operator's to grow."""
    return finding.startswith("extra in store")


def fix_templates(cfg: Config) -> None:
    templates.seed_templates(Path(cfg.templates_dir), force=False)


def _migrated_targets(targets: Sequence[str]) -> List[str]:
    """`targets` with legacy paths rewritten to `.metaproject/docs/`, order kept, de-duplicated."""
    return list(dict.fromkeys(deliverables.LEGACY_LEARN_TARGETS.get(t, t) for t in targets))


def check_config(cfg: Config) -> tuple[List[str], str]:
    """Legacy cycle-doc paths in learn.targets, and core targets missing from it (R-DRX-2)."""
    legacy = [t for t in cfg.learn.targets if t in deliverables.LEGACY_LEARN_TARGETS]
    migrated = _migrated_targets(cfg.learn.targets)
    missing = [t for t in deliverables.learn_targets() if t not in migrated]
    findings = [
        f"learn.targets legacy path: {t} → {deliverables.LEGACY_LEARN_TARGETS[t]}" for t in legacy
    ]
    findings += [f"learn.targets missing core target: {t}" for t in missing]
    fix_summary = (
        f"rewrite {len(legacy)} legacy path(s) in place and append {len(missing)} missing "
        "core target(s) (order kept, no duplicates)"
    )
    return findings, fix_summary


def fix_config(cfg: Config, config_file: Path) -> None:
    migrated = _migrated_targets(cfg.learn.targets)
    missing = [t for t in deliverables.learn_targets() if t not in migrated]
    targets = [*migrated, *missing]
    if targets != list(cfg.learn.targets):
        cfg.learn.targets = targets
        config.save_config(cfg, config_file)


# --------------------------------------------------------------- legacy file pairs

PAIR_NONE = "none"  # no legacy file
PAIR_LEGACY = "legacy"  # only the legacy file: move it
PAIR_IDENTICAL = "identical"  # both, same content: remove the legacy one
PAIR_DIFFER = "differ"  # both, different: report, change nothing


def _parse_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _pair_state(legacy: Path, new: Path) -> str:
    """How a legacy file relates to its new location (R-CFG-7, R-STORE-3).

    Identical means equal parsed JSON, or equal bytes when either side is unparseable.
    """
    if not legacy.is_file():
        return PAIR_NONE
    if not new.is_file():
        return PAIR_LEGACY
    old_data, new_data = _parse_json(legacy), _parse_json(new)
    if old_data is not None and new_data is not None:
        return PAIR_IDENTICAL if old_data == new_data else PAIR_DIFFER
    try:
        return PAIR_IDENTICAL if legacy.read_bytes() == new.read_bytes() else PAIR_DIFFER
    except OSError:
        return PAIR_DIFFER


def _differing_keys(legacy: Path, new: Path) -> List[str]:
    old_data, new_data = _parse_json(legacy), _parse_json(new)
    if not (isinstance(old_data, dict) and isinstance(new_data, dict)):
        return []
    keys = set(old_data) | set(new_data)
    return sorted(k for k in keys if old_data.get(k, ...) != new_data.get(k, ...))


def _pair_findings(
    state: str, legacy_label: str, new_label: str, legacy: Path, new: Path
) -> tuple[List[str], List[str]]:
    """(findings, report_only) for one legacy/new file pair."""
    if state == PAIR_LEGACY:
        return [f"move {legacy_label} → {new_label}"], []
    if state == PAIR_IDENTICAL:
        return [f"remove redundant {legacy_label} (identical to {new_label})"], []
    if state == PAIR_DIFFER:
        keys = _differing_keys(legacy, new)
        detail = f" (keys: {', '.join(keys)})" if keys else ""
        conflict = (
            f"conflict: {legacy_label} and {new_label} differ{detail}; "
            f"merge by hand and delete {legacy_label}"
        )
        return [conflict], [conflict]
    return [], []


def check_store_file(config_dir: Path) -> tuple[List[str], List[str], str]:
    """The user config still under its legacy name `config.json` (R-STORE-3)."""
    legacy = config_dir / config.LEGACY_CONFIG_FILENAME
    new = config_dir / config.CONFIG_FILENAME
    state = _pair_state(legacy, new)
    findings, report_only = _pair_findings(state, str(legacy), str(new), legacy, new)
    action = "remove the legacy file" if state == PAIR_IDENTICAL else "rename"
    fix_summary = f"{action}: {config.LEGACY_CONFIG_FILENAME} → {config.CONFIG_FILENAME}"
    return findings, report_only, fix_summary


def fix_store_file(config_dir: Path) -> None:
    legacy = config_dir / config.LEGACY_CONFIG_FILENAME
    new = config_dir / config.CONFIG_FILENAME
    state = _pair_state(legacy, new)
    if state == PAIR_LEGACY:
        os.rename(legacy, new)
    elif state == PAIR_IDENTICAL:
        legacy.unlink()


def check_project_config(project_dir: Path) -> tuple[List[str], List[str], str]:
    """A legacy root `.metaproject.json` (R-CFG-7)."""
    root = Path(project_dir)
    legacy = root / identity.LEGACY_IDENTITY_FILE
    new = root / identity.IDENTITY_FILE
    state = _pair_state(legacy, new)
    findings, report_only = _pair_findings(
        state, identity.LEGACY_IDENTITY_FILE, identity.IDENTITY_FILE, legacy, new
    )
    if state == PAIR_IDENTICAL:
        fix_summary = f"remove {identity.LEGACY_IDENTITY_FILE} (git rm when tracked; never commits)"
    else:
        fix_summary = (
            f"move {identity.LEGACY_IDENTITY_FILE} → {identity.IDENTITY_FILE} "
            "(git mv when tracked; never commits)"
        )
    return findings, report_only, fix_summary


def fix_project_config(project_dir: Path) -> None:
    root = Path(project_dir)
    legacy = root / identity.LEGACY_IDENTITY_FILE
    new = root / identity.IDENTITY_FILE
    state = _pair_state(legacy, new)
    git_repo = git.is_git_repository(root)
    if state == PAIR_LEGACY:
        _relocate(root, identity.LEGACY_IDENTITY_FILE, identity.IDENTITY_FILE, git_repo)
    elif state == PAIR_IDENTICAL:
        _remove_file(root, identity.LEGACY_IDENTITY_FILE, git_repo)


def _stale_hook_scripts(project_dir: Path) -> List[Tuple[str, Path]]:
    """Installed hook scripts that predate `.metaproject/config.json` (R-HOOK-2).

    A copy that does not mention the new path cannot find a migrated project's config.
    Missing scripts, and copies that already know the path, are not findings.
    """
    stale: List[Tuple[str, Path]] = []
    for rel_path, bundled in hooks._script_pairs():
        dest = Path(project_dir) / rel_path
        if not dest.is_file() or dest.is_symlink():
            continue
        try:
            text = dest.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if ".metaproject/config.json" not in text:
            stale.append((rel_path, bundled))
    return stale


def check_project_hooks(project_dir: Path) -> tuple[List[str], List[str], str]:
    stale = _stale_hook_scripts(project_dir)
    findings = [f"{rel} predates .metaproject/config.json" for rel, _ in stale]
    fix_summary = f"replace {len(stale)} hook script(s) with the bundled copy (overwrites edits)"
    return findings, [], fix_summary


def fix_project_hooks(project_dir: Path) -> None:
    root = Path(project_dir)
    for rel_path, bundled in _stale_hook_scripts(root):
        hooks._copy_script(root, rel_path, bundled, None)


# ------------------------------------------------------------------------ moves


def _move(root: Path, src_rel: str, dest_rel: str, use_git: bool) -> None:
    if use_git:
        git.git_mv(root, src_rel, dest_rel)
    else:
        os.rename(root / src_rel, root / dest_rel)


def _relocate(root: Path, src_rel: str, dest_rel: str, git_repo: bool) -> Optional[str]:
    """Move one file to its new path; return a conflict message instead of overwriting.

    `git mv` when `root` is a git work tree and the source is tracked, a plain rename
    otherwise. A case-only rename (`.metaproject/docs/intent.md` →
    `.metaproject/docs/INTENT.md`) goes through an intermediate name so APFS cannot turn
    it into a no-op (R-NFR-1). Each move stands alone, so an interrupted run can re-run.
    """
    root = Path(root)
    if deliverables.exact_exists(root / dest_rel):
        return f"conflict: {src_rel} kept; {dest_rel} already exists"
    (root / dest_rel).parent.mkdir(parents=True, exist_ok=True)
    use_git = git_repo and git.is_tracked(root, src_rel)
    if src_rel.casefold() == dest_rel.casefold():
        interim = f"{dest_rel}.metaproject-tmp"
        _move(root, src_rel, interim, use_git)
        _move(root, interim, dest_rel, use_git)
    else:
        _move(root, src_rel, dest_rel, use_git)
    return None


def _planned_moves(
    root: Path, template_suffix: bool = False
) -> Tuple[List[Tuple[str, str]], List[str]]:
    """(dest, src) moves for every relocated document under `root`, plus conflicts.

    The first legacy copy of a document moves when its declared path is free; every
    other copy — and every copy when the declared path is taken — is a conflict.
    """
    moves: List[Tuple[str, str]] = []
    conflicts: List[str] = []
    for new in deliverables.RELOCATED_FILES:
        dest = deliverables.template_path(new) if template_suffix else new
        candidates = deliverables.legacy_candidates(root, new, template_suffix=template_suffix)
        if not candidates:
            continue
        if not deliverables.exact_exists(Path(root) / dest):
            moves.append((dest, candidates[0]))
            candidates = candidates[1:]
        conflicts += [f"conflict: {src} kept; {dest} already exists" for src in candidates]
    return moves, conflicts


def _move_findings(moves: Sequence[Tuple[str, str]]) -> List[str]:
    return [f"move {src} → {dest}" for dest, src in moves]


def _apply_moves(root: Path, moves: Sequence[Tuple[str, str]]) -> List[str]:
    """Run planned moves; return the (source, destination) paths that actually moved."""
    git_repo = git.is_git_repository(root)
    moved: List[str] = []
    for dest, src in moves:
        if _relocate(root, src, dest, git_repo) is None:
            moved += [src, dest]
    return moved


def _bundled_gitkeep_bytes() -> Tuple[bytes, ...]:
    bundled = templates.get_bundled_templates_dir() / ".metaproject.template" / "docs.template"
    samples: List[bytes] = []
    for candidate in (bundled / ".gitkeep", bundled / "archive.template" / ".gitkeep"):
        if candidate.is_file():
            samples.append(candidate.read_bytes())
    return tuple(samples)


def _is_redundant_gitkeep(src: Path, dest: Path) -> bool:
    """True when `src` is an empty/default/duplicate `.gitkeep` beside an existing `dest`."""
    if not src.is_file():
        return False
    src_bytes = src.read_bytes()
    if not src_bytes.strip():
        return True
    if dest.is_file() and not dest.is_symlink() and src_bytes == dest.read_bytes():
        return True
    return src_bytes in _bundled_gitkeep_bytes()


def _plan_destination(
    root: Path,
    src_rel: str,
    dest_rel: str,
    moves: List[Tuple[str, str]],
    removals: List[str],
    conflicts: List[str],
    *,
    allow_redundant_gitkeep: bool = False,
) -> None:
    if not deliverables.exact_exists(root / dest_rel):
        moves.append((dest_rel, src_rel))
    elif allow_redundant_gitkeep and _is_redundant_gitkeep(root / src_rel, root / dest_rel):
        removals.append(src_rel)
    else:
        conflicts.append(f"conflict: {src_rel} kept; {dest_rel} already exists")


def _remove_file(root: Path, rel_path: str, git_repo: bool) -> bool:
    target = Path(root) / rel_path
    if not (deliverables.exact_exists(target) and target.is_file() and not target.is_symlink()):
        return False
    if git_repo and git.is_tracked(root, rel_path):
        git.git_rm(root, rel_path)
    else:
        target.unlink()
    return True


def _prune_single_dir(root: Path, dir_path: Path, git_repo: bool) -> bool:
    """Unlink untracked OS junk in `dir_path` and rmdir it if nothing else remains."""
    try:
        entries = list(dir_path.iterdir())
    except OSError:
        return False
    junk: List[Path] = []
    for entry in entries:
        if entry.is_symlink() or entry.is_dir() or not entry.is_file():
            return False
        if not templates.is_junk_file_name(entry.name):
            return False
        rel = entry.relative_to(root).as_posix()
        if git_repo and git.is_tracked(root, rel):
            return False
        junk.append(entry)
    for item in junk:
        item.unlink()
    try:
        dir_path.rmdir()
    except OSError:
        return False
    return True


def _prune_dir_if_junk_only(
    root: Path, rel_dir: str, git_repo: bool, *, recursive: bool = False
) -> None:
    """Remove an emptied legacy directory, unlinking untracked OS junk if that is all left."""
    root = Path(root)
    base = root / rel_dir
    if not (deliverables.exact_exists(base) and base.is_dir() and not base.is_symlink()):
        return
    if recursive:
        dirs = [p for p in base.rglob("*") if p.is_dir() and not p.is_symlink()]
        dirs.sort(key=lambda p: len(p.parts), reverse=True)
        for sub in [*dirs, base]:
            _prune_single_dir(root, sub, git_repo)
    else:
        _prune_single_dir(root, base, git_repo)


# ------------------------------------------------------------------ store layout


def _store_plan(store: Path) -> _MigrationPlan:
    if not store.is_dir():
        return _MigrationPlan()
    moves, conflicts = _planned_moves(store, template_suffix=True)
    removals: List[str] = []
    for dest, src in _STORE_GITKEEP_MOVES:
        src_path = store / src
        if deliverables.exact_exists(src_path) and src_path.is_file() and not src_path.is_symlink():
            _plan_destination(
                store,
                src,
                dest,
                moves,
                removals,
                conflicts,
                allow_redundant_gitkeep=True,
            )
    return _MigrationPlan(moves=moves, removals=removals, conflicts=conflicts)


def _store_moves(store: Path) -> Tuple[List[Tuple[str, str]], List[str]]:
    plan = _store_plan(store)
    return plan.moves, plan.conflicts


def check_store_layout(cfg: Config) -> tuple[List[str], List[str], str]:
    """Templates still at the store root or under `docs.template/` (R-DRX-1)."""
    plan = _store_plan(Path(cfg.templates_dir))
    findings = _move_findings(plan.moves) + [f"remove redundant {r}" for r in plan.removals]
    findings += plan.conflicts
    parts = []
    if plan.moves:
        parts.append(f"move {len(plan.moves)} template(s)")
    if plan.removals:
        parts.append(f"remove {len(plan.removals)} redundant placeholder(s)")
    action = ", ".join(parts) if parts else "migrate layout"
    fix_summary = f"{action} into .metaproject.template/docs.template/ (one commit in store repo)"
    return findings, plan.conflicts, fix_summary


def fix_store_layout(cfg: Config) -> None:
    store = Path(cfg.templates_dir)
    plan = _store_plan(store)
    git_repo = git.is_git_repository(store)
    changed = _apply_moves(store, plan.moves)
    for rel in plan.removals:
        was_tracked = git_repo and git.is_tracked(store, rel)
        if _remove_file(store, rel, git_repo) and was_tracked:
            changed.append(rel)
    if plan.moves or plan.removals:
        _prune_dir_if_junk_only(store, "docs.template/archive.template", git_repo, recursive=True)
        _prune_dir_if_junk_only(store, "docs.template", git_repo, recursive=False)
    if changed and git_repo:
        git.commit_paths(store, STORE_LAYOUT_COMMIT, changed)


# ----------------------------------------------------------------- global skill


def check_global_skill() -> tuple[List[str], str]:
    """The skill `init` used to install into ~/.claude, now orphaned (R-DRX-6)."""
    orphan = skills.legacy_global_skill_dir()
    if not (orphan.exists() or orphan.is_symlink()):
        return [], ""
    return (
        [f"orphaned global skill (project skills replace it): {orphan}"],
        f"remove {orphan} (nothing else under ~/.claude is touched)",
    )


def fix_global_skill() -> None:
    orphan = skills.legacy_global_skill_dir()
    if orphan.is_symlink() or orphan.is_file():
        orphan.unlink()
    elif orphan.is_dir():
        shutil.rmtree(orphan)


def _identity_findings(anchorless: Sequence[Path]) -> tuple[List[str], str]:
    findings = [f"no {identity.IDENTITY_FILE} anchor: {p}" for p in anchorless]
    fix_summary = f"backfill identity for {len(anchorless)} project(s)"
    return findings, fix_summary


def check_identity(cfg: Config) -> tuple[List[str], str, List[Path]]:
    """Cataloged projects with no readable project config."""
    database = db.get_db(cfg.universe_db)
    projects = db.query_projects(database)  # non-missing rows only
    anchorless: List[Path] = []
    for row in projects:
        project_dir = Path(row["path"])
        if not project_dir.is_dir():
            continue
        if identity.read_identity(project_dir) is None:
            anchorless.append(project_dir)

    findings, fix_summary = _identity_findings(anchorless)
    return findings, fix_summary, anchorless


def check_project_identity(project_dir: Path) -> tuple[List[str], str, List[Path]]:
    """Identity scoped to one operator-named project.

    The full run only notices cataloged projects; here the operator pointed doctor
    at the directory, so catalog membership is not required.
    """
    anchorless: List[Path] = []
    if project_dir.is_dir() and identity.read_identity(project_dir) is None:
        anchorless.append(project_dir)
    findings, fix_summary = _identity_findings(anchorless)
    return findings, fix_summary, anchorless


def fix_identity(cfg: Config, projects: List[Path]) -> None:
    for project_dir in projects:
        title, description = identity.fallback_identity(project_dir)
        identity.write_identity(
            project_dir,
            identity.Identity(
                title=title,
                description=description,
                author=cfg.author,
                created=date.today(),
                metaproject_version=__version__,
            ),
        )


# ------------------------------------------------------------------- projects


# The managed set is declared once, in `catalog`, and shared with `skills sync --all`.
_is_managed = catalog.is_managed
_managed_projects = catalog.managed_projects


def _project_doc_plan(project_dir: Path) -> _MigrationPlan:
    root = Path(project_dir)
    moves, conflicts = _planned_moves(root)
    removals: List[str] = []
    mkdirs: List[str] = []
    empty_subdirs: List[str] = []

    for sub in deliverables.MIGRATABLE_SUBDIRS:
        src_dir_rel = f"docs/{sub}"
        dest_dir_rel = f".metaproject/docs/{sub}"
        src_dir = root / src_dir_rel
        if not (
            deliverables.exact_exists(src_dir) and src_dir.is_dir() and not src_dir.is_symlink()
        ):
            continue
        subdir_files: List[Path] = []
        for walk_root, dir_names, file_names in os.walk(src_dir, followlinks=False):
            dir_names[:] = sorted(
                d for d in dir_names if d != ".git" and not templates.is_junk_file_name(d)
            )
            for fname in sorted(file_names):
                if templates.is_junk_file_name(fname):
                    continue
                candidate = Path(walk_root) / fname
                if candidate.is_file() and not candidate.is_symlink():
                    subdir_files.append(candidate)
        if not subdir_files:
            if not deliverables.exact_exists(root / dest_dir_rel):
                mkdirs.append(dest_dir_rel)
            empty_subdirs.append(src_dir_rel)
            continue
        for file_path in subdir_files:
            rel = file_path.relative_to(src_dir).as_posix()
            src_rel = f"{src_dir_rel}/{rel}"
            dest_rel = f"{dest_dir_rel}/{rel}"
            _plan_destination(
                root,
                src_rel,
                dest_rel,
                moves,
                removals,
                conflicts,
                allow_redundant_gitkeep=(file_path.name == ".gitkeep"),
            )

    docs_gitkeep = root / "docs" / ".gitkeep"
    if (
        deliverables.exact_exists(root / "docs")
        and deliverables.exact_exists(docs_gitkeep)
        and docs_gitkeep.is_file()
        and not docs_gitkeep.is_symlink()
    ):
        _plan_destination(
            root,
            "docs/.gitkeep",
            ".metaproject/docs/.gitkeep",
            moves,
            removals,
            conflicts,
            allow_redundant_gitkeep=True,
        )

    return _MigrationPlan(
        moves=moves,
        removals=removals,
        mkdirs=mkdirs,
        empty_subdirs=empty_subdirs,
        conflicts=conflicts,
    )


def check_project_docs(project_dir: Path) -> tuple[List[str], List[str], str]:
    """Cycle docs, metaproject subdirs, or `.gitkeep` at root/`docs/` locations (R-DRX-3..5)."""
    plan = _project_doc_plan(project_dir)
    findings = _move_findings(plan.moves)
    findings += [f"remove redundant {r}" for r in plan.removals]
    for sub_rel in plan.empty_subdirs:
        dest_sub = f".metaproject/{sub_rel}"
        if dest_sub in plan.mkdirs:
            findings.append(f"move empty directory {sub_rel}/ → {dest_sub}/")
        else:
            findings.append(f"remove empty legacy directory {sub_rel}/")
    findings += plan.conflicts
    parts = []
    if plan.moves:
        parts.append(f"move {len(plan.moves)} file(s)")
    if plan.removals:
        parts.append(f"remove {len(plan.removals)} redundant placeholder(s)")
    if plan.empty_subdirs:
        parts.append(f"relocate {len(plan.empty_subdirs)} empty dir(s)")
    action = ", ".join(parts) if parts else "migrate docs"
    fix_summary = f"{action} into .metaproject/docs/ (git mv when tracked; never commits)"
    return findings, plan.conflicts, fix_summary


def fix_project_docs(project_dir: Path) -> None:
    root = Path(project_dir)
    plan = _project_doc_plan(root)
    git_repo = git.is_git_repository(root)
    _apply_moves(root, plan.moves)
    for rel in plan.removals:
        _remove_file(root, rel, git_repo)
    for dir_rel in plan.mkdirs:
        (root / dir_rel).mkdir(parents=True, exist_ok=True)
    for sub in deliverables.MIGRATABLE_SUBDIRS:
        sub_rel = f"docs/{sub}"
        if (
            any(src.startswith(f"{sub_rel}/") for _, src in plan.moves)
            or any(r.startswith(f"{sub_rel}/") for r in plan.removals)
            or sub_rel in plan.empty_subdirs
        ):
            _prune_dir_if_junk_only(root, sub_rel, git_repo, recursive=True)
    if (
        any(src.startswith("docs/") for _, src in plan.moves)
        or any(r.startswith("docs/") for r in plan.removals)
        or plan.empty_subdirs
    ):
        _prune_dir_if_junk_only(root, "docs", git_repo, recursive=False)


def _skills_home(project_dir: Path) -> Optional[Path]:
    """The project whose `.agents/skills` holds the sources, or None when there is none."""
    target = skills.project_skills_dir(project_dir)
    if target.refusal is not None:
        return None
    return target.home if target.home is not None else Path(project_dir)


def _is_legacy_link(project_dir: Path) -> bool:
    home = _skills_home(project_dir)
    return home is not None and bridges.claude_skills_shape(project_dir, home) == bridges.LEGACY


def _console() -> Console:
    return Console(markup=False, highlight=False, soft_wrap=True)


def check_skills_legacy_link(project_dir: Path) -> tuple[List[str], List[str], str]:
    """A whole-directory `.claude/skills` link (R-BRG-19/20): fixable, with lost user skills.

    The lost-skill lines are warnings only: they never make the fix unavailable.
    """
    if not _is_legacy_link(project_dir):
        return [], [], ""
    home = _skills_home(project_dir) or Path(project_dir)
    names = [skill.name for skill in skills.bundled_skills()]
    findings = [".claude/skills is a whole-directory link to .agents/skills (legacy layout)"]
    for name in bridges.lost_user_skills(home / ".agents" / "skills", names):
        findings.append(
            f"user skill {name} will no longer be visible to Claude Code after migration "
            f"(add your own .claude/skills/{name} entry)"
        )
    summary = "replace the link with a real .claude/skills/ holding one entry per bundled skill"
    return findings, [], summary


def fix_skills_legacy_link(project_dir: Path) -> None:
    report = skills.migrate_legacy_skills_link(project_dir)
    out = _console()
    if report.lost:
        out.print("User skills Claude Code will no longer see through .claude/skills:")
        for name in report.lost:
            out.print(f"  {name}")
        out.print("Add a .claude/skills/<name> entry for any skill Claude Code should still see.")
    out.print("Commit .claude/skills.")


def check_skills_targets(project_dir: Path) -> tuple[List[str], List[str], str]:
    """`skills.targets` absent from the project config (R-BRG-5): behaves as `["claude"]`."""
    _targets, recorded, _warnings = bridges.configured_targets(project_dir)
    if recorded:
        return [], [], ""
    return (
        ['skills.targets is not recorded (behaves as ["claude"])'],
        [],
        'record skills.targets = ["claude"] in the project config',
    )


def fix_skills_targets(project_dir: Path) -> None:
    warning = identity.update_settings(project_dir, ("skills", "targets"), ["claude"])
    if warning:
        raise MetaProjectError(warning)


def check_skill_shadowing(project_dir: Path) -> tuple[List[str], List[str], str]:
    """Same-named skills that take precedence over the project's (R-BRG-23); report-only."""
    names = [skill.name for skill in skills.bundled_skills()]
    findings = bridges.shadowing(project_dir, names)
    return findings, list(findings), ""


def fix_skill_shadowing(project_dir: Path) -> None:
    """Nothing to repair: shadowing is the operator's to resolve."""


def check_project_skills(project_dir: Path) -> tuple[List[str], List[str], str]:
    """Missing, outdated and modified declared skills in one project (R-DRX-4).

    The same classification as `metaproject skills status`. Missing and outdated
    (pristine copies of an earlier release) are fixable; a modified skill is the
    project's own edit and is reported, never overwritten (FC-4). The same holds for the
    `.claude/skills` bridge entries (R-BRG-20). A refusal, a bridge notice, or a manifest
    written by a newer metaproject is reported the same way; the legacy-link notice is
    left to its own check. A manifest that only needs recording is not a finding.
    """
    report = skills.inspect_project_skills(project_dir)
    if report.notice is not None:
        return [report.notice], [report.notice], ""
    missing = skills_named(report, skills.MISSING)
    outdated = skills_named(report, skills.OUTDATED)
    modified = [
        "modified skill (left untouched; `metaproject skills sync --force "
        f"{name}` to replace): {name}"
        for name in skills_named(report, skills.MODIFIED)
    ]
    findings = (
        [f"missing skill: {name}" for name in missing]
        + [f"outdated skill (unmodified copy of an earlier release): {name}" for name in outdated]
        + modified
    )
    report_only = list(modified)
    bridge = report.bridges.get("claude")
    bridge_fixable = 0
    if bridge is not None:
        newer = report.manifest_state == skills.MANIFEST_NEWER
        if bridge.notice is not None and not newer and not _is_legacy_link(project_dir):
            findings.append(bridge.notice)
            report_only.append(bridge.notice)
        wanted = "claude" in bridges.configured_targets(project_dir)[0]
        for name, entry in bridge.entries.items():
            state = entry.get("state")
            where = f".claude/skills/{name}"
            if state == bridges.MISSING and wanted:
                findings.append(f"missing bridge entry: {where}")
                bridge_fixable += 1
            elif state == bridges.OUTDATED and wanted:
                findings.append(f"outdated bridge entry: {where}")
                bridge_fixable += 1
            elif state == bridges.MODIFIED:
                note = entry.get("note")
                text = f"modified bridge entry (left untouched): {where}"
                if note:
                    text += f"; {note}"
                findings.append(text)
                report_only.append(text)
            elif state == bridges.FOREIGN and entry.get("note") != "identical":
                text = f"foreign entry (not created by metaproject; left untouched): {where}"
                findings.append(text)
                report_only.append(text)
    if report.manifest_state == skills.MANIFEST_NEWER and findings:
        newer_text = "skills manifest written by a newer metaproject; upgrade before syncing"
        findings.append(newer_text)
        report_only = list(findings)
    try:
        where = report.target.relative_to(project_dir).as_posix()
    except ValueError:
        where = str(report.target)
    summary = (
        f"install {len(missing)} missing, update {len(outdated)} outdated unmodified "
        f"skill(s) in {where}/"
    )
    if bridge_fixable:
        summary += f", and write {bridge_fixable} .claude/skills entr(ies)"
    return findings, report_only, summary


def skills_named(report: "skills.SkillsReport", state: str) -> List[str]:
    return [status.name for status in report.statuses if status.state == state]


def fix_project_skills(project_dir: Path) -> None:
    skills.sync_project_skills(project_dir, update=True)


def check_project_agents(project_dir: Path) -> tuple[List[str], List[str], str]:
    """Missing, outdated, modified and disabled bundled agents in one project (R-AGT-16).

    The same classification as `skills status`. Missing and outdated (pristine copies of
    an earlier release) are fixable; modified and disabled agents are reported, never
    changed. The no-home refusal is the project-skills check's to report.
    """
    report = subagents.inspect_project_agents(project_dir)
    if report.notice is not None:
        return [], [], ""
    missing = [s.name for s in report.statuses if s.state == skills.MISSING]
    outdated = [s.name for s in report.statuses if s.state == skills.OUTDATED]
    modified = [
        f"modified agent (left untouched; `metaproject skills sync --force {s.name}` to "
        f"replace): {s.name}"
        for s in report.statuses
        if s.state == skills.MODIFIED
    ]
    disabled = [
        f"disabled agent (kept; excluded by agents.enabled): {s.name}"
        for s in report.statuses
        if s.state == subagents.DISABLED
    ]
    findings = (
        [f"missing agent: {name}" for name in missing]
        + [f"outdated agent (unmodified copy of an earlier release): {name}" for name in outdated]
        + modified
        + disabled
    )
    report_only = modified + disabled
    if report.manifest_state == skills.MANIFEST_NEWER and (missing or outdated):
        text = "agents manifest written by a newer metaproject; upgrade before syncing"
        findings.append(text)
        report_only = list(findings)
    summary = (
        f"install {len(missing)} missing, update {len(outdated)} outdated unmodified "
        "agent(s) in .claude/agents/"
    )
    return findings, report_only, summary


def fix_project_agents(project_dir: Path) -> None:
    subagents.sync_project_agents(project_dir, update=True)


# --------------------------------------------------------------------- running


# Per-project checks after identity, in order. The config check runs first so later
# checks see a migrated layout.
_PROJECT_CHECKS: Tuple[
    Tuple[str, Callable[[Path], tuple[List[str], List[str], str]], Callable[[Path], None]], ...
] = (
    ("project config", check_project_config, fix_project_config),
    ("project docs", check_project_docs, fix_project_docs),
    ("skills legacy link", check_skills_legacy_link, fix_skills_legacy_link),
    ("skills targets", check_skills_targets, fix_skills_targets),
    ("project skills", check_project_skills, fix_project_skills),
    ("project agents", check_project_agents, fix_project_agents),
    ("skill shadowing", check_skill_shadowing, fix_skill_shadowing),
    ("project hook scripts", check_project_hooks, fix_project_hooks),
)


def _confirm_with_questionary(message: str) -> bool:
    return bool(questionary.confirm(message, default=False).ask())


def _project_checks(
    cfg: Config,
    project_dir: Path,
    dry_run: bool,
    confirm: Callable[[str], bool],
) -> List[CheckResult]:
    """The checks for one operator-named project, in the full run's order.

    Every check reports even when healthy — one project, so the board is small and
    the operator sees what was looked at. Identity runs first: accepting its backfill
    puts an anchorless project in scope for the config, docs, skills and hook checks,
    which need a project config exactly as the full run's project checks do (R-DRX-3/4).
    """
    results: List[CheckResult] = []
    findings, fix_summary, anchorless = check_project_identity(project_dir)
    results.append(
        _apply(
            "project identity",
            findings,
            fix_summary,
            lambda: fix_identity(cfg, anchorless),
            dry_run,
            confirm,
        )
    )
    if not _is_managed(project_dir):
        return results
    for name, check, fix in _PROJECT_CHECKS:
        findings, report_only, fix_summary = check(project_dir)
        results.append(
            _apply(
                f"{name}: {project_dir}",
                findings,
                fix_summary,
                lambda fix=fix, project_dir=project_dir: fix(project_dir),
                dry_run,
                confirm,
                report_only,
            )
        )
    return results


def run_checks(
    cfg: Config,
    config_file: Path,
    dry_run: bool = False,
    confirm: Optional[Callable[[str], bool]] = None,
    project: Optional[Path] = None,
) -> List[CheckResult]:
    """Run every check in order, fixing behind per-check (per-project) confirmation.

    Declining one fix never blocks the remaining checks (spec R-DR-8, R-DRX-7).
    With `project`, run only that project's checks — identity, then docs, then
    skills — and none of the environment-wide ones.
    """
    if confirm is None:
        confirm = _confirm_with_questionary
    if project is not None:
        return _project_checks(cfg, project, dry_run, confirm)
    results: List[CheckResult] = []

    # 1. Template-store layout — before the store check, so it is not re-seeded.
    findings, report_only, fix_summary = check_store_layout(cfg)
    results.append(
        _apply(
            "template store layout",
            findings,
            fix_summary,
            lambda: fix_store_layout(cfg),
            dry_run,
            confirm,
            report_only,
        )
    )

    # 2. Template store
    findings, fix_summary = check_templates(cfg)
    results.append(
        _apply(
            "template store",
            findings,
            fix_summary,
            lambda: fix_templates(cfg),
            dry_run,
            confirm,
            informational=[f for f in findings if _is_extra_note(f)],
        )
    )

    # 3. Config file name — before learn.targets, which then writes the resolved file.
    config_dir = Path(config_file).parent
    findings, report_only, fix_summary = check_store_file(config_dir)
    results.append(
        _apply(
            "config file name",
            findings,
            fix_summary,
            lambda: fix_store_file(config_dir),
            dry_run,
            confirm,
            report_only,
        )
    )

    # 4. Config (learn.targets)
    findings, fix_summary = check_config(cfg)
    results.append(
        _apply(
            "config (learn.targets)",
            findings,
            fix_summary,
            lambda: fix_config(cfg, config.get_config_file_path(config_dir)),
            dry_run,
            confirm,
        )
    )

    # 5. Orphaned global skill
    findings, fix_summary = check_global_skill()
    results.append(
        _apply("orphaned global skill", findings, fix_summary, fix_global_skill, dry_run, confirm)
    )

    # 6. Project identity
    findings, fix_summary, anchorless = check_identity(cfg)
    results.append(
        _apply(
            "project identity",
            findings,
            fix_summary,
            lambda: fix_identity(cfg, anchorless),
            dry_run,
            confirm,
        )
    )

    # 7–10. Per project, one confirmation each: declining one project never blocks the next.
    projects = _managed_projects(cfg)
    for name, check, fix in _PROJECT_CHECKS:
        for project_dir in projects:
            findings, report_only, fix_summary = check(project_dir)
            if findings:
                results.append(
                    _apply(
                        f"{name}: {project_dir}",
                        findings,
                        fix_summary,
                        lambda fix=fix, p=project_dir: fix(p),
                        dry_run,
                        confirm,
                        report_only,
                    )
                )

    return results


def _apply(
    name: str,
    findings: List[str],
    fix_summary: str,
    fix: Callable[[], None],
    dry_run: bool,
    confirm: Callable[[str], bool],
    report_only: Sequence[str] = (),
    informational: Sequence[str] = (),
) -> CheckResult:
    """Report a check and, unless dry-run, offer its fix behind one confirmation.

    `report_only` findings are defects no fix resolves (a conflict, a stale skill);
    `informational` findings are not defects at all (an extra template the operator
    added) and never make a check unhealthy.
    """
    actionable = [f for f in findings if f not in informational]
    healthy = not actionable
    result = CheckResult(
        name=name,
        healthy=healthy,
        findings=findings,
        fix_summary=fix_summary,
        report_only=list(report_only),
    )
    if healthy or dry_run:
        return result
    # Nothing a fix could change: report, and do not ask a question with no effect.
    if all(f in report_only for f in actionable):
        return result
    if not confirm(f"doctor: fix {name}? {fix_summary}"):
        return result
    try:
        fix()
    except MetaProjectError as exc:
        result.fixed = False
        result.findings = [*findings, f"fix failed: {exc}"]
        return result
    result.fixed = True
    # Healthy at end of run once every fixable finding is fixed (spec R-DR-1); findings
    # no fix resolves keep the check unhealthy.
    result.healthy = not report_only
    return result
