"""Scaffolding engine: path resolution, collision guards, transactional rollback,
and project generation.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from metaproject import __version__
from metaproject import variables as variables_module
from metaproject.config import FALLBACK_AUTHOR, Config, load_config
from metaproject.deliverables import DELIVERABLES, DeliverableClass
from metaproject.exceptions import CollisionError, MetaProjectError
from metaproject.git import init_repository, is_git_repository
from metaproject.hooks import install_hooks
from metaproject.identity import IDENTITY_FILE, Identity, config_path, has_config, write_identity
from metaproject.skills import install_project_skills
from metaproject.templates import get_bundled_templates_dir, render_template_tree
from metaproject.variables import collect_variables

if TYPE_CHECKING:
    from metaproject.review import BackfillResult

# Argument forms that mean "scaffold into this directory" rather than naming a project.
CWD_ALIASES = {".", "./", ".\\", "..", "../", "..\\"}

# On-demand deliverables (`.metaproject/docs/{HANDOFF,TODO}.md`) are never scaffolded (R-CLS-5).
_ON_DEMAND_PATHS = tuple(d.path for d in DELIVERABLES if d.cls is DeliverableClass.ON_DEMAND)


def resolve_output(
    output: Optional[str | Path],
    project_name: str,
    base_dir: Optional[Path] = None,
) -> Path:
    """Resolve target directory based on spec.md algorithm.

    - No output provided -> ./<project-name> (or <base_dir>/<project-name>)
    - output is an existing directory -> <output>/<project-name>
    - output does not exist or ends in '/' -> create <output> as exact root
    """
    cwd = (base_dir or Path.cwd()).resolve()

    if not output:
        return (cwd / project_name).resolve()

    out_str = str(output).strip()
    is_trailing_slash = out_str.endswith("/") or out_str.endswith("\\")
    out_path = Path(out_str).expanduser()
    if not out_path.is_absolute():
        out_path = (cwd / out_path).resolve()

    if is_trailing_slash:
        return out_path

    if out_path.exists() and out_path.is_dir():
        return (out_path / project_name).resolve()

    return out_path


def is_directory_empty(target_dir: Path) -> bool:
    """Check if target_dir is empty or contains only non-hidden files.

    Per spec.md §7: permits a solitary .git/ directory and .DS_Store.
    """
    if not target_dir.exists():
        return True

    for entry in target_dir.iterdir():
        if entry.name in {".git", ".DS_Store"}:
            continue
        # If any other file or folder is found, it is not considered empty
        return False

    return True


def resolve_project_name(project_name: str, target_dir: Path) -> str:
    """Resolve the effective project name for variable collection.

    `metaproject new .` names a destination, not a project; in that case the target
    directory's own name is the project name.
    """
    name = project_name.strip()
    if name in CWD_ALIASES:
        return target_dir.name or name
    return name


def list_directory_entries(target_dir: Path) -> List[str]:
    """Return the visible entry names occupying target_dir, sorted.

    Used to show the operator what a backfill would be landing on top of.
    """
    if not target_dir.exists() or not target_dir.is_dir():
        return []
    return sorted(
        entry.name for entry in target_dir.iterdir() if entry.name not in {".git", ".DS_Store"}
    )


class TransactionalTracker:
    """Tracks filesystem entities created during a scaffolding operation for rollback safety."""

    def __init__(self) -> None:
        self.created_files: List[Path] = []
        self.created_dirs: List[Path] = []
        self.existing_paths_before: Set[Path] = set()
        self.modified_files: List[Tuple[Path, bytes]] = []

    def record_existing(self, path: Path) -> None:
        """Snapshot an existing path so rollback never touches it."""
        self.existing_paths_before.add(path.resolve())

    def record_created_dir(self, path: Path) -> None:
        """Record directory created during scaffold."""
        res = path.resolve()
        if res not in self.existing_paths_before and res not in self.created_dirs:
            self.created_dirs.append(res)

    def record_created_file(self, path: Path) -> None:
        """Record file created during scaffold. A symlink is recorded as itself, never
        as the path it points to, so rollback removes the link and not its target."""
        res = path.parent.resolve() / path.name if path.is_symlink() else path.resolve()
        if res not in self.existing_paths_before and res not in self.created_files:
            self.created_files.append(res)

    def record_modified_file(self, path: Path) -> None:
        """Snapshot a pre-existing file about to be merged into, so rollback restores it."""
        res = path.resolve()
        if any(existing == res for existing, _ in self.modified_files):
            return
        self.modified_files.append((res, res.read_bytes()))

    def rollback(self) -> None:
        """Undo only items created during this operation; never touch pre-existing paths.

        A pre-existing file merged into (`record_modified_file`) is restored to the bytes
        it had before, never deleted.
        """
        for file_path, original in reversed(self.modified_files):
            try:
                file_path.write_bytes(original)
            except Exception:
                pass

        for file_path in reversed(self.created_files):
            try:
                if file_path.is_file() or file_path.is_symlink():
                    file_path.unlink(missing_ok=True)
            except Exception:
                pass

        for dir_path in reversed(self.created_dirs):
            try:
                if dir_path.is_dir() and dir_path not in self.existing_paths_before:
                    # Only remove if directory is empty
                    if not any(dir_path.iterdir()):
                        dir_path.rmdir()
            except Exception:
                pass


def prepare_agent_skills(
    target_dir: Path,
    tracker: TransactionalTracker,
    dry_run: bool = False,
    home: Optional[Path] = None,
) -> Optional[Path]:
    """Create `<home or target>/.agents/skills/` and its `.gitkeep` (create-only, tracked).

    Never creates `.claude/skills` (R-BRG-2): the per-skill bridge pass behind
    `skills.install_project_skills` owns that directory. `home` (from
    `skills.skills_home`) is where the skills live; for a delegating sub-project it is
    another directory and only that home receives the layout. `.gitkeep` is written
    whenever missing so a clone keeps the otherwise-empty directory. Existing files are
    never overwritten. Returns the skills directory (or that it would create).
    """
    base = Path(home) if home is not None else Path(target_dir)
    skills_dir = base / ".agents" / "skills"
    gitkeep_path = skills_dir / ".gitkeep"
    if not dry_run:
        for directory in (base / ".agents", skills_dir):
            if not directory.exists():
                directory.mkdir(parents=True, exist_ok=True)
                tracker.record_created_dir(directory)
        if not gitkeep_path.exists():
            gitkeep_path.write_text("", encoding="utf-8")
            tracker.record_created_file(gitkeep_path)
    return skills_dir


def record_skills_targets(
    project_dir: Path, tracker: TransactionalTracker, dry_run: bool = False
) -> Optional[str]:
    """Record `skills.targets: ["claude"]` when absent (R-BRG-4); a warning string, never a failure.

    The config file is snapshotted on `tracker` first so rollback restores it. Writes
    nothing under `dry_run`.
    """
    if dry_run:
        return None
    from metaproject.identity import update_settings

    path = config_path(project_dir)
    if path.is_file():
        tracker.record_modified_file(path)
    return update_settings(project_dir, ("skills", "targets"), ["claude"])


def scaffold_project(
    project_name: str,
    output: Optional[str | Path] = None,
    templates_dir: Optional[str | Path] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    author: Optional[str] = None,
    interactive: bool = False,
    force: bool = False,
    dry_run: bool = False,
    no_git: bool = False,
    backfill: bool = False,
    config: Optional[Config] = None,
) -> Dict[str, Any]:
    """Execute complete scaffolding lifecycle for metaproject new.

    `backfill=True` permits scaffolding into an occupied directory while preserving every
    file already there: colliding template files are skipped, not overwritten. `force=True`
    also permits an occupied directory but overwrites colliding files.
    """
    cfg = config or load_config()
    target_dir = resolve_output(output, project_name)
    occupied = not is_directory_empty(target_dir)

    # 1. Collision check
    if occupied and not force and not backfill:
        raise CollisionError(
            f"Target directory '{target_dir}' exists and is not empty. "
            f"Re-run interactively to confirm scaffolding into an existing directory, "
            f"or use --force to overwrite."
        )
    is_backfill = occupied and not force

    # 2. Template directory resolution
    resolved_templates_dir: Path
    if templates_dir:
        resolved_templates_dir = Path(templates_dir).expanduser().resolve()
    else:
        try:
            tmpl_path = Path(cfg.templates_dir)
            if tmpl_path.exists() and any(tmpl_path.iterdir()):
                resolved_templates_dir = tmpl_path.resolve()
            else:
                resolved_templates_dir = get_bundled_templates_dir()
        except (PermissionError, OSError):
            resolved_templates_dir = get_bundled_templates_dir()

    # 3. Variable resolution. `created` is fixed here so it is the single date used both
    # for the rendered `{Date}`/`{Year}` and for `.metaproject/config.json`'s `created` field.
    created = variables_module._today()
    variables = collect_variables(
        project_name=resolve_project_name(project_name, target_dir),
        title=title,
        description=description,
        author=author,
        config=cfg,
        interactive=interactive,
        created=created,
    )

    # 4. Scaffolding with transactional rollback
    tracker = TransactionalTracker()
    if target_dir.exists():
        tracker.record_existing(target_dir)

    try:
        if not dry_run:
            if not target_dir.exists():
                target_dir.mkdir(parents=True, exist_ok=True)
                tracker.record_created_dir(target_dir)

        # Plan the tree first so pre-existing paths are known before anything is written:
        # rollback must never delete a file the operator already had.
        planned_paths = render_template_tree(
            source_dir=resolved_templates_dir,
            target_dir=target_dir,
            variables=variables,
            dry_run=True,
            exclude=_ON_DEMAND_PATHS,
        ).paths
        preserved_paths = [path for path in planned_paths if path.exists()]
        for path in preserved_paths:
            tracker.record_existing(path)

        # Render template files
        render_report = render_template_tree(
            source_dir=resolved_templates_dir,
            target_dir=target_dir,
            variables=variables,
            dry_run=dry_run,
            skip_existing=is_backfill,
            exclude=_ON_DEMAND_PATHS,
        )
        rendered_paths = render_report.paths

        for path in rendered_paths:
            if path.is_dir():
                tracker.record_created_dir(path)
            else:
                tracker.record_created_file(path)

        # 4a. Project identity (`.metaproject/config.json`), written before git init so
        # the initial commit includes it (R-ID-1). A backfill never overwrites an existing
        # identity file (new or legacy); dry-run lists the path it would create but
        # writes nothing.
        identity_path = target_dir / IDENTITY_FILE
        identity_file: Optional[Path] = None
        if not has_config(target_dir) and not identity_path.exists():
            identity_file = identity_path
            rendered_paths.append(identity_path)
            if not dry_run:
                if not identity_path.parent.exists():
                    identity_path.parent.mkdir(parents=True)
                    tracker.record_created_dir(identity_path.parent)
                write_identity(
                    target_dir,
                    Identity(
                        title=variables["ProjectTitle"],
                        description=variables["ProjectDescription"],
                        author=variables["Author"],
                        created=created,
                        metaproject_version=__version__,
                    ),
                )
                tracker.record_created_file(identity_path)

        # 5. Agent-skills layout: .agents/skills/ only; `.claude/skills` is bridged per
        # skill by the install below (R-BRG-2). Then record `skills.targets` (R-BRG-4).
        prepare_agent_skills(target_dir, tracker, dry_run=dry_run)
        targets_warning = record_skills_targets(target_dir, tracker, dry_run=dry_run)

        # 5a. Project skills, copied into .agents/skills before git init so the initial
        # commit includes them (R-SKL-2, R-SKL-6). Create-only, rollback-tracked.
        skills_report = install_project_skills(target_dir, dry_run=dry_run, tracker=tracker)

        # 5b. Claude Code hooks: the hook script (create-only) and its entries merged into
        # .claude/settings.json (merge, never overwrite). An unmergeable settings file is
        # reported, not fatal: nothing is written for hooks and the scaffold goes on.
        hooks_report = install_hooks(target_dir, dry_run=dry_run, tracker=tracker)

        # 6. Git initialisation. A backfill never touches an existing repository: staging
        # and committing there would sweep the operator's own working tree into a commit
        # they did not ask for.
        already_git = is_git_repository(target_dir)
        git_initialized = False
        if no_git or not cfg.auto_git_init:
            git_status = "skipped"
        elif is_backfill and already_git:
            git_status = "existing"
        elif dry_run:
            git_status = "pending"
        else:
            git_initialized = init_repository(
                target_dir=target_dir,
                branch=cfg.default_branch,
                commit_message="chore: initial scaffold from metaproject",
                author_name=variables["Author"],
            )
            git_status = "initialized" if git_initialized else "skipped"

        return {
            "target_dir": target_dir,
            "variables": variables,
            "rendered_files": rendered_paths,
            "preserved_files": (
                [path for path in preserved_paths if path.is_file()] if is_backfill else []
            ),
            "backfilled": is_backfill,
            "skills_bridges": skills_report.bridges.get("claude"),
            "skills": skills_report,
            "hooks": hooks_report,
            "git_initialized": git_initialized,
            "git_status": git_status,
            "dry_run": dry_run,
            "warnings": [
                *render_report.warnings,
                *([targets_warning] if targets_warning else []),
                *skills_report.warnings,
            ],
            "identity_file": identity_file,
        }

    except Exception as exc:
        if not dry_run:
            tracker.rollback()
        raise MetaProjectError(f"Scaffolding failed: {exc}") from exc


@dataclass(frozen=True)
class AdoptResult:
    """What one `adopt_project` call did, or would do under `dry_run`."""

    target_dir: Path
    identity: Identity
    # True when `.metaproject/config.json` was (or would be) written; False when one existed.
    identity_written: bool
    backfill: "BackfillResult"
    # The Claude bridge report from the skills install, None when not bridged.
    skills_bridges: Any = None
    warnings: Tuple[str, ...] = ()


def adopt_project(
    project_dir: Path,
    title: Optional[str] = None,
    description: Optional[str] = None,
    author: Optional[str] = None,
    templates_dir: Optional[Path] = None,
    dry_run: bool = False,
    config: Optional[Config] = None,
) -> AdoptResult:
    """Adopt an existing repository: identity, agent-skills layout, every missing deliverable.

    The agent-safe counterpart to `new .` (no confirmation, permitted under CLAUDECODE).
    Create-only end to end: an existing `.metaproject/config.json` is kept as written, an
    existing `.claude/skills` entry is left alone, and deliverables and skills go through
    `review.backfill_missing`, which never overwrites. It never changes the repository
    (read-only `git config` only).

    Identity is resolved the way `variables.project_variables` would render a project
    with no `.metaproject/config.json` (`--title` > README / manifest > directory name), so
    recording it does not change how `review` renders the project. Author: `--author`
    > config > `git config user.name` (never a container identity such as "Claude").
    When none of those yields a real name, adopt refuses before writing anything rather
    than record the `FALLBACK_AUTHOR` placeholder in `.metaproject/config.json`.
    """
    from metaproject.identity import fallback_identity, read_identity
    from metaproject.review import backfill_missing

    cfg = config or load_config()
    target_dir = Path(project_dir).expanduser().resolve()
    if not target_dir.is_dir():
        raise MetaProjectError(f"Not a directory: {target_dir}")

    existing = read_identity(target_dir)
    identity_path = config_path(target_dir)
    if existing is not None:
        identity = existing
        identity_written = False
    elif identity_path.exists():
        # Present but unreadable: never overwrite an operator's file, even a broken one.
        raise MetaProjectError(
            f"{identity_path} exists but is not a valid identity file; fix or remove it "
            "and run adopt again."
        )
    else:
        resolved_author = variables_module.resolve_author(author, cfg)
        if resolved_author == FALLBACK_AUTHOR and not (author or "").strip():
            # The project config is create-only and outranks config and git, so a
            # placeholder recorded here would outlive every real author set later.
            raise MetaProjectError(
                "No author found (no config author; git user.name and $USER are unset "
                'or a container identity). Pass --author "Your Name".'
            )
        fallback_title, fallback_description = fallback_identity(target_dir)
        identity = Identity(
            title=(title or "").strip() or fallback_title,
            description=(description or "").strip() or fallback_description,
            author=resolved_author,
            created=variables_module._today(),
            metaproject_version=__version__,
        )
        identity_written = True
        if not dry_run:
            write_identity(target_dir, identity)

    tracker = TransactionalTracker()
    tracker.record_existing(target_dir)
    # Only the skills home gets the `.agents/skills` layout; with no home (a delegating
    # sub-project with no ancestor and no git root) none is written and the skills install
    # below reports the refusal. `backfill_missing` records `skills.targets` and rolls
    # that write back if the install fails.
    from metaproject.skills import LOCATION_ROOT, skills_home, skills_location

    home = skills_home(target_dir)
    if home is not None or skills_location(target_dir)[0] != LOCATION_ROOT:
        prepare_agent_skills(target_dir, tracker, dry_run=dry_run, home=home)

    try:
        backfill = backfill_missing(
            target_dir, templates_dir=templates_dir, dry_run=dry_run, config=cfg
        )
    except Exception:
        if not dry_run:
            tracker.rollback()
        raise
    return AdoptResult(
        target_dir=target_dir,
        identity=identity,
        identity_written=identity_written,
        backfill=backfill,
        skills_bridges=backfill.skills_bridges,
        warnings=tuple(backfill.warnings),
    )
