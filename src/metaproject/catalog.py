"""The set of cataloged, metaproject-managed projects.

`doctor`'s per-project checks and `skills status|sync --all` act on exactly the same
projects: rows in `universe.db` that still exist on disk and carry `.metaproject.json`.
Declaring that set once keeps the two from drifting apart.

The catalog lives in SQLite (`sqlite-utils`, the `tui` extra). `db.get_db` imports it
only when called, so importing this module costs nothing in a core install; calling
`managed_projects` without the extra raises `MissingExtraError`.
"""

from pathlib import Path
from typing import List

from metaproject import db, identity
from metaproject.config import Config


def is_managed(project_dir: Path) -> bool:
    """`project_dir` exists and carries `.metaproject.json` (R-DRX-3/4 scope)."""
    return project_dir.is_dir() and (project_dir / identity.IDENTITY_FILE).is_file()


def managed_projects(cfg: Config) -> List[Path]:
    """Cataloged projects that exist and carry `.metaproject.json` (R-DRX-3/4).

    An absent `universe.db` is an empty catalog; it is not created here.
    """
    if not Path(cfg.universe_db).is_file():
        return []
    database = db.get_db(cfg.universe_db)
    return [
        project_dir
        for project_dir in (Path(row["path"]) for row in db.query_projects(database))
        if is_managed(project_dir)
    ]
