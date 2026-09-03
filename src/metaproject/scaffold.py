"""Scaffolding engine: path resolution, collision guards, transactional rollback,
and project generation.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from metaproject.config import Config, load_config
from metaproject.exceptions import CollisionError, MetaProjectError
from metaproject.git import init_repository
from metaproject.templates import get_bundled_templates_dir, render_template_tree
from metaproject.variables import collect_variables


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
    config: Optional[Config] = None,
) -> Dict[str, Any]:
    """Execute complete scaffolding lifecycle for metaproject new."""
    cfg = config or load_config()
    target_dir = resolve_output(output, project_name)

    # 1. Collision check
    if not force and not is_directory_empty(target_dir):
        raise CollisionError(
            f"Target directory '{target_dir}' exists and is not empty. Use --force to proceed."
        )

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
        project_name=project_name,
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

        # Render template files
        rendered_paths = render_template_tree(
            source_dir=resolved_templates_dir,
            target_dir=target_dir,
            variables=variables,
            dry_run=dry_run,
        )

        for path in rendered_paths:
            if path.is_dir():
                tracker.record_created_dir(path)
            else:
                tracker.record_created_file(path)

        # 5. Git initialisation
        git_initialized = False
        if not no_git and not dry_run and cfg.auto_git_init:
            git_initialized = init_repository(
                target_dir=target_dir,
                branch=cfg.default_branch,
                commit_message="chore: initial scaffold from metaproject",
                author_name=variables["Author"],
            )

        return {
            "target_dir": target_dir,
            "variables": variables,
            "rendered_files": rendered_paths,
            "git_initialized": git_initialized,
            "dry_run": dry_run,
        }

    except Exception as exc:
        if not dry_run:
            tracker.rollback()
        raise MetaProjectError(f"Scaffolding failed: {exc}") from exc
