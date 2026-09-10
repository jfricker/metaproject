"""Scaffolding engine: path resolution, collision guards, transactional rollback,
and project generation.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from metaproject.config import Config, load_config
from metaproject.exceptions import CollisionError, MetaProjectError
from metaproject.git import init_repository, is_git_repository
from metaproject.templates import get_bundled_templates_dir, render_template_tree
from metaproject.variables import collect_variables

# Argument forms that mean "scaffold into this directory" rather than naming a project.
CWD_ALIASES = {".", "./", ".\\", "..", "../", "..\\"}


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

    def record_existing(self, path: Path) -> None:
        """Snapshot an existing path so rollback never touches it."""
        self.existing_paths_before.add(path.resolve())

    def record_created_dir(self, path: Path) -> None:
        """Record directory created during scaffold."""
        res = path.resolve()
        if res not in self.existing_paths_before and res not in self.created_dirs:
            self.created_dirs.append(res)

    def record_created_file(self, path: Path) -> None:
        """Record file created during scaffold."""
        res = path.resolve()
        if res not in self.existing_paths_before and res not in self.created_files:
            self.created_files.append(res)

    def rollback(self) -> None:
        """Undo only items created during this operation; never touch pre-existing paths."""
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


def link_agent_skills(
    target_dir: Path,
    tracker: TransactionalTracker,
    dry_run: bool = False,
    skip_existing: bool = False,
) -> Optional[Path]:
    """Create the agent-skills layout: .agents/skills/ plus a .claude/skills symlink to it.

    Equivalent to `mkdir -p .claude && mkdir -p .agents/skills &&
    ln -s ../.agents/skills .claude/skills`, but tracked for rollback and
    skipped on backfill when the operator already has a .claude/skills entry.
    """
    agents_skills_dir = target_dir / ".agents" / "skills"
    claude_dir = target_dir / ".claude"
    skills_link = claude_dir / "skills"

    if skip_existing and (skills_link.exists() or skills_link.is_symlink()):
        return None

    if not dry_run:
        for directory in (agents_skills_dir, claude_dir):
            if not directory.exists():
                directory.mkdir(parents=True, exist_ok=True)
                tracker.record_created_dir(directory)
        if not (skills_link.exists() or skills_link.is_symlink()):
            skills_link.symlink_to(Path("..") / ".agents" / "skills")
            tracker.record_created_file(skills_link)
    return skills_link


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
            f"Re-run interactively to confirm a backfill, or use --force to overwrite."
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

    # 3. Variable resolution
    variables = collect_variables(
        project_name=resolve_project_name(project_name, target_dir),
        title=title,
        description=description,
        author=author,
        config=cfg,
        interactive=interactive,
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
        )
        preserved_paths = [path for path in planned_paths if path.exists()]
        for path in preserved_paths:
            tracker.record_existing(path)

        # Render template files
        rendered_paths = render_template_tree(
            source_dir=resolved_templates_dir,
            target_dir=target_dir,
            variables=variables,
            dry_run=dry_run,
            skip_existing=is_backfill,
        )

        for path in rendered_paths:
            if path.is_dir():
                tracker.record_created_dir(path)
            else:
                tracker.record_created_file(path)

        # 5. Agent-skills layout: .agents/skills/ with .claude/skills symlinked to it.
        skills_link = link_agent_skills(
            target_dir=target_dir,
            tracker=tracker,
            dry_run=dry_run,
            skip_existing=is_backfill,
        )

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
            "skills_link": skills_link,
            "git_initialized": git_initialized,
            "git_status": git_status,
            "dry_run": dry_run,
        }

    except Exception as exc:
        if not dry_run:
            tracker.rollback()
        raise MetaProjectError(f"Scaffolding failed: {exc}") from exc
