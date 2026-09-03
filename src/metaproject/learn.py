"""Template learning engine: inspects projects, extracts improvements,
and updates central templates.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from metaproject.config import load_config
from metaproject.review import get_template_source, os_walk_with_depth
from metaproject.templates import get_bundled_templates_dir
from metaproject.universe import is_project_root

LEARNABLE_TARGETS = [
    "AGENTS.md",
    ".gitignore",
    "Makefile",
]


def extract_file_additions(project_file: Path, template_file: Path) -> List[str]:
    """Find non-empty lines present in project_file that do not exist in template_file."""
    if not project_file.exists() or not template_file.exists():
        return []

    try:
        proj_lines = [
            line.strip()
            for line in project_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        tmpl_lines = set(
            line.strip()
            for line in template_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip()
        )

        additions = [line for line in proj_lines if line not in tmpl_lines]
        return additions
    except Exception:
        return []


def learn_from_project(
    project_dir: Path,
    templates_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Inspect a project for candidate improvements to feed back into central templates."""
    resolved_proj = project_dir.expanduser().resolve()
    cfg = load_config()

    if templates_dir:
        resolved_templates = Path(templates_dir).expanduser().resolve()
    elif Path(cfg.templates_dir).exists():
        resolved_templates = Path(cfg.templates_dir).resolve()
    else:
        resolved_templates = get_bundled_templates_dir()

    candidates: List[Dict[str, Any]] = []

    for target_name in LEARNABLE_TARGETS:
        proj_file = resolved_proj / target_name
        tmpl_file = get_template_source(target_name, resolved_templates)

        if proj_file.exists() and tmpl_file and tmpl_file.exists():
            additions = extract_file_additions(proj_file, tmpl_file)
            if additions:
                candidates.append(
                    {
                        "target_file": target_name,
                        "template_path": str(tmpl_file),
                        "project_path": str(proj_file),
                        "additions": additions,
                        "count": len(additions),
                    }
                )

    return {
        "project_name": resolved_proj.name,
        "project_path": str(resolved_proj),
        "candidates": candidates,
        "total_additions": sum(c["count"] for c in candidates),
    }


def apply_learned_enhancement(template_path: Path, new_lines: List[str]) -> int:
    """Append new lines to template file if not already present. Returns count of added lines."""
    if not template_path.exists():
        return 0

    try:
        existing_text = template_path.read_text(encoding="utf-8", errors="ignore")
        existing_lines = set(line.strip() for line in existing_text.splitlines())

        to_add = [line for line in new_lines if line.strip() not in existing_lines]
        if not to_add:
            return 0

        with open(template_path, "a", encoding="utf-8") as f:
            if not existing_text.endswith("\n"):
                f.write("\n")
            f.write("\n# Added via metaproject learn\n")
            for line in to_add:
                f.write(f"{line}\n")

        return len(to_add)
    except Exception:
        return 0


def learn_workspace(
    root_dir: Path,
    templates_dir: Optional[Path] = None,
    max_depth: int = 3,
) -> List[Dict[str, Any]]:
    """Scan all projects within root_dir and extract improvements."""
    resolved_root = root_dir.expanduser().resolve()
    results: List[Dict[str, Any]] = []

    if is_project_root(resolved_root):
        return [learn_from_project(resolved_root, templates_dir)]

    for current, dirs, _ in os_walk_with_depth(resolved_root, max_depth):
        if current != resolved_root and is_project_root(current):
            res = learn_from_project(current, templates_dir)
            if res["total_additions"] > 0:
                results.append(res)
            dirs.clear()

    return results
