"""Template discovery, extraction, stripping, and rendering for MetaProject."""

import importlib.resources
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Set

import jinja2

from metaproject.exceptions import TemplateError

WHITELISTED_VARS: Set[str] = {
    "ProjectTitle",
    "ProjectSlug",
    "ProjectDescription",
    "Author",
    "Date",
    "Year",
    "Name",
    "ProjectName",
}


def get_bundled_templates_dir() -> Path:
    """Return filesystem path to bundled seed templates using importlib.resources."""
    try:
        traversable = importlib.resources.files("metaproject").joinpath("templates")
        return Path(str(traversable))
    except Exception as exc:
        raise TemplateError(f"Failed to access bundled template resources: {exc}") from exc


def seed_templates(target_dir: Path, force: bool = False) -> List[Path]:
    """Copy bundled seed templates to target directory (e.g. ~/.metaproject/templates).

    Returns list of copied file paths.
    """
    bundled_dir = get_bundled_templates_dir()
    if not bundled_dir.exists():
        raise TemplateError(f"Bundled template directory does not exist: {bundled_dir}")

    target_dir.mkdir(parents=True, exist_ok=True)
    copied: List[Path] = []

    for item in bundled_dir.rglob("*"):
        rel_path = item.relative_to(bundled_dir)
        dest_item = target_dir / rel_path

        if item.is_dir():
            dest_item.mkdir(parents=True, exist_ok=True)
        else:
            if dest_item.exists() and not force:
                continue
            dest_item.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest_item)
            copied.append(dest_item)

    return copied


def transform_template_name(name: str) -> str:
    """Transform template filenames and directories by stripping '.template'.

    Rules:
    - '<name>.template.<ext>' -> '<name>.<ext>' (e.g. 'AGENTS.template.md' -> 'AGENTS.md')
    - '.<name>.template'      -> '.<name>'      (e.g. '.gitignore.template' -> '.gitignore')
    - '<name>.template'       -> '<name>'       (e.g. 'docs.template' -> 'docs')
    """
    # Dotfile case: e.g. '.gitignore.template' -> '.gitignore'
    if name.startswith(".") and name.endswith(".template"):
        return name[:-9]

    # Infix case: e.g. 'AGENTS.template.md' -> 'AGENTS.md'
    if ".template." in name:
        return name.replace(".template.", ".")

    # Suffix case: e.g. 'docs.template' -> 'docs'
    if name.endswith(".template"):
        return name[:-9]

    return name


def is_binary_file(file_path: Path, sample_size: int = 8192) -> bool:
    """Detect if a file is binary by checking for null bytes in initial chunk."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(sample_size)
            return b"\x00" in chunk
    except Exception:
        return False


def preprocess_template_string(content: str) -> str:
    """Convert whitelisted {Var} placeholders to Jinja2 {{ Var }} expressions.

    Strictly preserves all other braces (JSON, CSS, shell ${VAR}, etc.).
    """
    pattern = re.compile(r"(?<!\{)\{([a-zA-Z0-9_]+)\}(?!\})")

    def replace_whitelisted(match: re.Match) -> str:
        var_name = match.group(1)
        if var_name in WHITELISTED_VARS:
            return f"{{{{ {var_name} }}}}"
        return match.group(0)

    return pattern.sub(replace_whitelisted, content)


def render_template_string(template_str: str, variables: Dict[str, Any]) -> str:
    """Preprocess whitelisted variables and render via Jinja2."""
    preprocessed = preprocess_template_string(template_str)
    env = jinja2.Environment(
        autoescape=False,
        keep_trailing_newline=True,
        undefined=jinja2.Undefined,
    )
    try:
        template = env.from_string(preprocessed)
        return template.render(**variables)
    except Exception as exc:
        raise TemplateError(f"Failed to render template: {exc}") from exc


def render_template_tree(
    source_dir: Path,
    target_dir: Path,
    variables: Dict[str, Any],
    dry_run: bool = False,
) -> List[Path]:
    """Walk source_dir, transform names, mirror empty directories, and render files.

    Returns list of paths created/written within target_dir.
    """
    if not source_dir.exists() or not source_dir.is_dir():
        raise TemplateError(
            f"Template directory does not exist or is not a directory: {source_dir}"
        )

    created_paths: List[Path] = []

    # Walk directory tree top-down
    for item in sorted(source_dir.rglob("*")):
        rel_path = item.relative_to(source_dir)
        # Transform each path component: e.g. docs.template/guide.template.md -> docs/guide.md
        transformed_parts = [transform_template_name(part) for part in rel_path.parts]
        dest_item = target_dir.joinpath(*transformed_parts)

        if item.is_dir():
            if not dry_run:
                dest_item.mkdir(parents=True, exist_ok=True)
            created_paths.append(dest_item)
        else:
            if not dry_run:
                dest_item.parent.mkdir(parents=True, exist_ok=True)

            if is_binary_file(item):
                if not dry_run:
                    shutil.copy2(item, dest_item)
            else:
                raw_text = item.read_text(encoding="utf-8")
                rendered_text = render_template_string(raw_text, variables)
                if not dry_run:
                    dest_item.write_text(rendered_text, encoding="utf-8")

            created_paths.append(dest_item)

    return created_paths
