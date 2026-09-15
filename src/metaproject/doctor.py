"""`metaproject doctor` — diagnose and repair a stale installed environment.

Everything metaproject installs outside the package (live template store,
``config.json`` ``learn.targets``, the global Claude Code skill, and per-project
``.metaproject.json`` anchors) can lag behind an upgraded package. Doctor checks each
against the installed version and repairs what's stale — behind one confirmation per
check, never silently. Fixes always call the module that owns the concern, so doctor
and ``init`` cannot drift apart (spec R-DR-11).
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, List, Optional

import questionary

from metaproject import __version__, config, db, deliverables, identity, skills, templates
from metaproject.config import Config


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
    bundled = _relative_files(templates.get_bundled_templates_dir())
    live = _relative_files(Path(cfg.templates_dir))
    missing = sorted(bundled - live)
    extras = sorted(live - bundled)

    findings = [f"missing from store: {p}" for p in missing]
    findings += [f"extra in store (kept, learned or hand-added): {p}" for p in extras]
    fix_summary = f"seed {len(missing)} missing template(s) via seed_templates (no overwrites)"
    return findings, fix_summary


def fix_templates(cfg: Config) -> None:
    templates.seed_templates(Path(cfg.templates_dir), force=False)


def check_config(cfg: Config) -> tuple[List[str], str]:
    """Deliverable-derived learn targets missing from the pinned config list."""
    expected = deliverables.learn_targets()
    missing = [t for t in expected if t not in cfg.learn.targets]
    findings = [f"learn.targets missing core target: {t}" for t in missing]
    fix_summary = f"append {len(missing)} missing core target(s) to learn.targets (additive)"
    return findings, fix_summary


def fix_config(cfg: Config, config_file: Path) -> None:
    missing = [t for t in deliverables.learn_targets() if t not in cfg.learn.targets]
    if missing:
        cfg.learn.targets = [*cfg.learn.targets, *missing]
        config.save_config(cfg, config_file)


def check_skill() -> tuple[List[str], str]:
    """Global skill copy vs the bundled skill (content + extra files)."""
    bundled_dir = skills.get_bundled_skill_dir()
    install_dir = skills.get_skill_install_dir()

    findings: List[str] = []
    if not skills.is_skill_current(bundled_dir, install_dir):
        findings.append("installed skill differs from the bundled skill")
    extras = sorted(_relative_files(install_dir) - _relative_files(bundled_dir))
    findings += [f"extra file in skill dir (will be pruned): {p}" for p in extras]
    fix_summary = "reinstall bundled skill and prune extra files (package-owned directory)"
    return findings, fix_summary


def fix_skill() -> None:
    skills.install_skill(force=True, prune_extra=True)


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


def run_checks(
    cfg: Config,
    config_file: Path,
    dry_run: bool = False,
    confirm: Optional[Callable[[str], bool]] = None,
) -> List[CheckResult]:
    """Run the four checks in spec order, fixing behind per-check confirmation.

    Declining one fix never blocks the remaining checks (spec R-DR-8).
    """
    if confirm is None:
        confirm = questionary.confirm
    results: List[CheckResult] = []

    # 1. Template store
    findings, fix_summary = check_templates(cfg)
    results.append(
        _apply(
            "template store", findings, fix_summary, lambda: fix_templates(cfg), dry_run, confirm
        )
    )

    # 2. Config
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

    # 3. Skill
    findings, fix_summary = check_skill()
    results.append(_apply("skill", findings, fix_summary, fix_skill, dry_run, confirm))

    # 4. Project identity
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

    return results


def _apply(
    name: str,
    findings: List[str],
    fix_summary: str,
    fix: Callable[[], None],
    dry_run: bool,
    confirm: Callable[[str], bool],
) -> CheckResult:
    healthy = not findings
    result = CheckResult(name=name, healthy=healthy, findings=findings, fix_summary=fix_summary)
    if healthy:
        return result
    if dry_run:
        return result
    if not confirm(f"doctor: fix {name}? {fix_summary}"):
        return result
    fix()
    result.fixed = True
    result.healthy = True  # healthy at end of run: finding fixed (spec R-DR-1)
    return result
