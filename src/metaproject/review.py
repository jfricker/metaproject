"""Template drift auditing and project compliance verification engine."""

import difflib
from pathlib import Path
from typing import Any, Dict, List, Optional

from metaproject.config import load_config
from metaproject.templates import (
    get_bundled_templates_dir,
    transform_template_name,
)
from metaproject.universe import is_project_root

STANDARD_DELIVERABLES = [
    "README.md",
    "AGENTS.md",
    "intent.md",
    "STATE.md",
    "HANDOFF.md",
    "CLAUDE.md",
    ".gitignore",
    "docs",
]


def get_template_source(template_name: str, templates_dir: Path) -> Optional[Path]:
    """Find source template matching target file name."""
    # Direct check
    for item in templates_dir.iterdir():
        if transform_template_name(item.name) == template_name:
            return item
    return None


def review_project(
    project_dir: Path,
    templates_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Audit single project against central templates for missing files and content drift."""
    resolved_proj = project_dir.expanduser().resolve()
    cfg = load_config()

    if templates_dir:
        resolved_templates = Path(templates_dir).expanduser().resolve()
    else:
        try:
            tmpl_path = Path(cfg.templates_dir)
            if tmpl_path.exists() and any(tmpl_path.iterdir()):
                resolved_templates = tmpl_path.resolve()
            else:
                resolved_templates = get_bundled_templates_dir()
        except (PermissionError, OSError):
            resolved_templates = get_bundled_templates_dir()

    missing_files: List[str] = []
    diffs: Dict[str, str] = {}
    recommendations: List[str] = []

    # 1. Check for standard deliverables
    for deliverable in STANDARD_DELIVERABLES:
        target_path = resolved_proj / deliverable
        if not target_path.exists():
            missing_files.append(deliverable)
            recommendations.append(f"Add missing standard deliverable: {deliverable}")

    # 2. Content diffing on critical shared governance files (e.g. AGENTS.md)
    agents_proj = resolved_proj / "AGENTS.md"
    agents_tmpl = get_template_source("AGENTS.md", resolved_templates)

    if agents_proj.exists() and agents_tmpl and agents_tmpl.exists():
        try:
            proj_lines = [
                line.rstrip() + "\n"
                for line in agents_proj.read_text(encoding="utf-8", errors="ignore").splitlines()
            ]
            tmpl_lines = [
                line.rstrip() + "\n"
                for line in agents_tmpl.read_text(encoding="utf-8", errors="ignore").splitlines()
            ]
            diff = list(
                difflib.unified_diff(
                    tmpl_lines,
                    proj_lines,
                    fromfile="templates/AGENTS.md",
                    tofile=f"{project_dir.name}/AGENTS.md",
                )
            )
            if diff:
                diffs["AGENTS.md"] = "".join(diff)
                recommendations.append(
                    "Review modifications in AGENTS.md against standard template."
                )
        except Exception:
            pass

    return {
        "project_name": resolved_proj.name,
        "project_path": str(resolved_proj),
        "missing_files": missing_files,
        "diffs": diffs,
        "recommendations": recommendations,
        "is_compliant": len(missing_files) == 0,
    }


def review_workspace(
    root_dir: Path,
    templates_dir: Optional[Path] = None,
    max_depth: int = 4,
) -> List[Dict[str, Any]]:
    """Audit all projects found within root_dir and its subdirectories."""
    resolved_root = root_dir.expanduser().resolve()
    results: List[Dict[str, Any]] = []

    # If root_dir itself is a project root, include it
    if is_project_root(resolved_root):
        results.append(review_project(resolved_root, templates_dir))

    # Scan subdirectories
    for current, dirs, _ in os_walk_with_depth(resolved_root, max_depth):
        if current != resolved_root and is_project_root(current):
            results.append(review_project(current, templates_dir))

    return results


def os_walk_with_depth(root: Path, max_depth: int):
    """Walk directories limiting traversal depth and skipping cache/vendor dirs."""
    root_depth = len(root.parts)
    import os

    from metaproject.universe import IGNORED_DIRECTORIES

    for dirpath, dirnames, filenames in os.walk(root):
        curr_path = Path(dirpath)
        depth = len(curr_path.parts) - root_depth
        if depth >= max_depth:
            dirnames.clear()
        # Skip vendor/cache and hidden directories
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and d not in IGNORED_DIRECTORIES
        ]
        yield curr_path, dirnames, filenames
