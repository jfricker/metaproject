"""`metaproject doctor` — diagnose and repair a stale installed environment.

Everything metaproject installs outside the package (live template store,
``config.json`` ``learn.targets``, per-project ``.metaproject.json`` anchors, cycle
documents and project skills) can lag behind an upgraded package. Doctor checks each
against the installed version and repairs what's stale — behind one confirmation per
check (per project, for the project checks), never silently. Fixes always call the
module that owns the concern, so doctor and ``init``/``new`` cannot drift apart
(spec R-DR-11).

The checks, in order: template-store layout, template store, config, orphaned global
skill, project identity, project docs, project skills. Layout runs first so a store
whose cycle templates are still at the root is migrated, not re-seeded beside them.
"""

import os
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import questionary

from metaproject import __version__, config, db, deliverables, git, identity, skills, templates
from metaproject.config import Config

STORE_LAYOUT_COMMIT = "chore(templates): relocate cycle templates to docs.template/"


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
    # A cycle template still at its legacy location is the layout check's finding, not a
    # missing one: seeding it here would put a blank copy beside the real one.
    moves = _store_moves(store)[0]
    relocating = {Path(dest) for dest, _ in moves}
    legacy = {Path(src) for _, src in moves}
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
    """`targets` with legacy root paths rewritten to `docs/`, order kept, de-duplicated."""
    return list(dict.fromkeys(deliverables.LEGACY_NAMES.get(t, t) for t in targets))


def check_config(cfg: Config) -> tuple[List[str], str]:
    """Legacy cycle-doc paths in learn.targets, and core targets missing from it (R-DRX-2)."""
    legacy = [t for t in cfg.learn.targets if t in deliverables.LEGACY_NAMES]
    migrated = _migrated_targets(cfg.learn.targets)
    missing = [t for t in deliverables.learn_targets() if t not in migrated]
    findings = [f"learn.targets legacy path: {t} → {deliverables.LEGACY_NAMES[t]}" for t in legacy]
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


# ------------------------------------------------------------------------ moves


def _move(root: Path, src_rel: str, dest_rel: str, use_git: bool) -> None:
    if use_git:
        git.git_mv(root, src_rel, dest_rel)
    else:
        os.rename(root / src_rel, root / dest_rel)


def _relocate(root: Path, src_rel: str, dest_rel: str, git_repo: bool) -> Optional[str]:
    """Move one file to its new path; return a conflict message instead of overwriting.

    `git mv` when `root` is a git work tree and the source is tracked, a plain rename
    otherwise. A case-only rename (`docs/intent.md` → `docs/INTENT.md`) goes through an
    intermediate name so a case-insensitive filesystem cannot turn it into a no-op
    (R-NFR-6). Each move stands alone, so an interrupted run can simply be re-run.
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
    for new in deliverables.LEGACY_NAMES.values():
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


# ------------------------------------------------------------------ store layout


def _store_moves(store: Path) -> Tuple[List[Tuple[str, str]], List[str]]:
    if not store.is_dir():
        return [], []
    return _planned_moves(store, template_suffix=True)


def check_store_layout(cfg: Config) -> tuple[List[str], List[str], str]:
    """Cycle templates still at the store root or under old names (R-DRX-1)."""
    moves, conflicts = _store_moves(Path(cfg.templates_dir))
    fix_summary = (
        f"move {len(moves)} cycle template(s) into docs.template/ with their new names "
        "(one commit in the store repository)"
    )
    return _move_findings(moves) + conflicts, conflicts, fix_summary


def fix_store_layout(cfg: Config) -> None:
    store = Path(cfg.templates_dir)
    moves, _ = _store_moves(store)
    moved = _apply_moves(store, moves)
    if moved and git.is_git_repository(store):
        git.commit_paths(store, STORE_LAYOUT_COMMIT, moved)


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


def check_identity(cfg: Config) -> tuple[List[str], str, List[Path]]:
    """Cataloged projects whose `.metaproject.json` anchor is absent."""
    database = db.get_db(cfg.universe_db)
    projects = db.query_projects(database)  # non-missing rows only
    anchorless: List[Path] = []
    for row in projects:
        project_dir = Path(row["path"])
        if not project_dir.is_dir():
            continue
        if identity.read_identity(project_dir) is None:
            anchorless.append(project_dir)

    findings = [f"no .metaproject.json anchor: {p}" for p in anchorless]
    fix_summary = f"backfill identity for {len(anchorless)} project(s)"
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


def _managed_projects(cfg: Config) -> List[Path]:
    """Cataloged projects that exist and carry `.metaproject.json` (R-DRX-3/4)."""
    database = db.get_db(cfg.universe_db)
    found: List[Path] = []
    for row in db.query_projects(database):
        project_dir = Path(row["path"])
        if project_dir.is_dir() and (project_dir / identity.IDENTITY_FILE).is_file():
            found.append(project_dir)
    return found


def check_project_docs(project_dir: Path) -> tuple[List[str], List[str], str]:
    """Cycle documents at the root or under old names in one project (R-DRX-3)."""
    moves, conflicts = _planned_moves(project_dir)
    fix_summary = f"move {len(moves)} document(s) into docs/ (git mv when tracked; never commits)"
    return _move_findings(moves) + conflicts, conflicts, fix_summary


def fix_project_docs(project_dir: Path) -> None:
    moves, _ = _planned_moves(project_dir)
    _apply_moves(project_dir, moves)


def check_project_skills(project_dir: Path) -> tuple[List[str], List[str], str]:
    """Missing and stale declared skills in one project (R-DRX-4).

    Only missing skills are fixable; a stale copy may be the project's own edit and is
    reported, never overwritten (FC-4). An R-SKL-5 refusal is reported the same way.
    """
    target = skills.project_skills_dir(project_dir)
    if target.refusal is not None:
        return [target.refusal], [target.refusal], ""
    states: Dict[str, str] = {
        skill.name: skills.skill_state(skill, target.path / skill.name)
        for skill in skills.bundled_skills()
    }
    missing = [name for name, state in states.items() if state == skills.MISSING]
    stale = [
        f"stale skill (differs from this release; left untouched): {name}"
        for name, state in states.items()
        if state == skills.STALE
    ]
    findings = [f"missing skill: {name}" for name in missing] + stale
    return findings, stale, f"install {len(missing)} missing skill(s) into .agents/skills/"


def fix_project_skills(project_dir: Path) -> None:
    skills.install_project_skills(project_dir)


# --------------------------------------------------------------------- running


def _confirm_with_questionary(message: str) -> bool:
    return bool(questionary.confirm(message, default=False).ask())


def run_checks(
    cfg: Config,
    config_file: Path,
    dry_run: bool = False,
    confirm: Optional[Callable[[str], bool]] = None,
) -> List[CheckResult]:
    """Run every check in order, fixing behind per-check (per-project) confirmation.

    Declining one fix never blocks the remaining checks (spec R-DR-8, R-DRX-7).
    """
    if confirm is None:
        confirm = _confirm_with_questionary
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

    # 3. Config
    findings, fix_summary = check_config(cfg)
    results.append(
        _apply(
            "config (learn.targets)",
            findings,
            fix_summary,
            lambda: fix_config(cfg, config_file),
            dry_run,
            confirm,
        )
    )

    # 4. Orphaned global skill
    findings, fix_summary = check_global_skill()
    results.append(
        _apply("orphaned global skill", findings, fix_summary, fix_global_skill, dry_run, confirm)
    )

    # 5. Project identity
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

    # 6–7. Per project, one confirmation each: declining one project never blocks the next.
    projects = _managed_projects(cfg)
    for project_dir in projects:
        findings, report_only, fix_summary = check_project_docs(project_dir)
        if findings:
            results.append(
                _apply(
                    f"project docs: {project_dir}",
                    findings,
                    fix_summary,
                    lambda p=project_dir: fix_project_docs(p),
                    dry_run,
                    confirm,
                    report_only,
                )
            )
    for project_dir in projects:
        findings, report_only, fix_summary = check_project_skills(project_dir)
        if findings:
            results.append(
                _apply(
                    f"project skills: {project_dir}",
                    findings,
                    fix_summary,
                    lambda p=project_dir: fix_project_skills(p),
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
    fix()
    result.fixed = True
    # Healthy at end of run once every fixable finding is fixed (spec R-DR-1); findings
    # no fix resolves keep the check unhealthy.
    result.healthy = not report_only
    return result
