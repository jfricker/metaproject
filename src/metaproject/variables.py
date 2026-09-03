"""Variable resolution, normalization, and metadata collection for MetaProject."""

import datetime
import os
import re
from typing import Any, Dict, Optional

import questionary

from metaproject.config import Config, detect_git_user_name


def titlecase(name: str) -> str:
    """Convert an arbitrary identifier (e.g. 'my-cool-app' or 'api_service') to Title Case."""
    clean = re.sub(r"[_\-]+", " ", name).strip()
    words = [w.capitalize() for w in clean.split() if w]
    return " ".join(words) if words else name


def slugify(name: str) -> str:
    """Convert an arbitrary string into a URL/directory-safe lowercase slug."""
    clean = name.strip().lower()
    clean = re.sub(r"[\s_]+", "-", clean)
    clean = re.sub(r"[^a-z0-9\-]", "", clean)
    clean = re.sub(r"-+", "-", clean).strip("-")
    return clean or "project"


def resolve_author(
    cli_author: Optional[str] = None,
    config: Optional[Config] = None,
) -> str:
    """Resolve author name following precedence: CLI flag > Config > Git config > $USER."""
    if cli_author and cli_author.strip():
        return cli_author.strip()
    if config and config.author and config.author.strip():
        return config.author.strip()
    git_author = detect_git_user_name()
    if git_author and git_author.strip():
        return git_author.strip()
    return os.environ.get("USER", "Developer")


def collect_variables(
    project_name: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    author: Optional[str] = None,
    config: Optional[Config] = None,
    interactive: bool = False,
) -> Dict[str, Any]:
    """Collect and resolve all whitelisted template variables."""
    slug = slugify(project_name)
    resolved_title = title.strip() if title and title.strip() else titlecase(project_name)
    resolved_desc = description.strip() if description and description.strip() else ""
    resolved_author = resolve_author(author, config)

    if interactive:
        if not title:
            prompt_title = questionary.text(
                "Project Title:",
                default=resolved_title,
            ).ask()
            if prompt_title:
                resolved_title = prompt_title.strip()

        if not description:
            prompt_desc = questionary.text(
                "Project Description (one-line summary):",
                default=resolved_desc,
            ).ask()
            if prompt_desc:
                resolved_desc = prompt_desc.strip()

        if not author:
            prompt_author = questionary.text(
                "Author:",
                default=resolved_author,
            ).ask()
            if prompt_author:
                resolved_author = prompt_author.strip()

    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    year_str = str(now.year)

    variables: Dict[str, Any] = {
        "ProjectTitle": resolved_title,
        "ProjectSlug": slug,
        "ProjectDescription": resolved_desc,
        "Author": resolved_author,
        "Date": date_str,
        "Year": year_str,
        # Backward compatibility aliases
        "Name": resolved_author,
        "ProjectName": resolved_title,
    }

    return variables
