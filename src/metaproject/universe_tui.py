"""The Textual universe browser: read-only list → project detail → worktree detail.

Screens follow the approved mockup (`universe-tui-mockup.html`). The app never scans
on open — rows come straight from `universe.db`, and `r` is the only scan trigger in
interactive use. It performs no writes of its own: no editor, no `cd`, no review run;
the DB write in a refresh is the same `scan_universe` call the CLI's table path makes
(R-UNV-2, R-UNV-7, R-UNV-9). Details are fetched live at selection time through
`gitinfo`, cached in-session, and invalidated by the refresh action.
"""

from pathlib import Path
from typing import Dict, Optional

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from metaproject.db import get_db, query_projects
from metaproject.gitinfo import (
    ProjectDetails,
    WorktreeInfo,
    age_score,
    behind_score,
    inspect_project,
    inspect_worktree,
    last_commit,
    uncommitted_files,
)
from metaproject.universe import scan_universe

SDLC_LETTERS = (
    ("has_agents_md", "A"),
    ("has_intent_md", "I"),
    ("has_state_md", "S"),
    ("has_handoff_md", "H"),
)

LIST_COLUMNS = ("Classification", "Project", "Path", "Last Modified", "Git", "SDLC")
WORKTREE_COLUMNS = ("Branch", "Age", "Behind", "Uncommitted", "Verdict")


def sdlc_badges(project: dict) -> str:
    """The AISH letter set from the DB flags, `-` when none (same shape as the table)."""
    badges = "".join(letter for flag, letter in SDLC_LETTERS if project.get(flag))
    return badges or "-"


def list_row(project: dict) -> tuple:
    """One list-screen row from a DB record only — no subprocess on open (R-UNV-2)."""
    git = project["git_branch"] or ("git" if project["is_git"] else "no")
    return (
        project["classification"],
        project["title"] or project["name"],
        project["relative_path"],
        project["last_modified"][:10],
        git,
        sdlc_badges(project),
    )


def format_age(days: Optional[float]) -> str:
    if days is None:
        return "?"
    if days < 1.0:
        return "<1d"
    return f"{days:.0f}d"


def verdict_label(wt: WorktreeInfo) -> str:
    """`ACTIVE`/`STALE`, with the neutral marker when the base was undeterminable."""
    verdict = "STALE" if wt.stale else "ACTIVE"
    return f"{verdict} · neutral" if wt.neutral else verdict


def score_line(wt: WorktreeInfo) -> str:
    """The visible score behind the verdict (mockup screen 3): why it says what it says."""
    if wt.neutral:
        return "neutral · base undeterminable (verdict from age only)"
    age = age_score(wt.head_age_days)
    behind = behind_score(wt.behind_count)
    return f"score {age + behind} (age {age}, behind {behind})"


def worktree_row(wt: WorktreeInfo) -> tuple:
    uncommitted = f"{wt.uncommitted_count} file(s) ⚠" if wt.flag else "—"
    return (
        wt.branch or "detached",
        format_age(wt.head_age_days),
        str(wt.behind_count) if not wt.neutral else "?",
        uncommitted,
        verdict_label(wt),
    )


class NavDataTable(DataTable):
    """DataTable with vim keys added (R-UNV-2b) — same widget otherwise."""

    BINDINGS = [
        *DataTable.BINDINGS,
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
    ]


class UniverseListScreen(Screen):
    """The project list (mockup screen 1): DB read on open, no scan."""

    BINDINGS = [
        Binding("r", "app.refresh_universe", "Refresh"),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self, owner: "UniverseTui") -> None:
        super().__init__()
        self._owner = owner

    def compose(self) -> ComposeResult:
        yield Header()
        table = NavDataTable(cursor_type="row", id="projects")
        table.add_columns(*LIST_COLUMNS)
        yield table
        yield Footer()

    def on_mount(self) -> None:
        self.reload_rows()

    def reload_rows(self) -> None:
        """(Re)draw the list from universe.db — the only thing this screen reads."""
        db = get_db(self._owner.db_path)
        projects = query_projects(
            db,
            path_prefix=str(self._owner.project_home),
            classification=self._owner.classification_filter,
            include_missing=False,
        )
        table = self.query_one("#projects", DataTable)
        table.clear()
        for project in projects:
            table.add_row(*list_row(project), key=project["path"])
        self._owner.sub_title = (
            f"{self._owner.project_home} · {len(projects)} projects · r to rescan"
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        path = event.row_key.value
        if path:
            self.app.push_screen(ProjectDetailScreen(self._owner, path))


class ProjectDetailScreen(Screen):
    """A project's live state (mockup screen 2), fetched at selection time."""

    BINDINGS = [
        Binding("escape,backspace", "app.pop_screen", "Back"),
        Binding("enter", "open_worktree", "Worktree detail"),
        Binding("r", "app.refresh_universe", "Refresh"),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self, owner: "UniverseTui", project: dict) -> None:
        super().__init__()
        self._owner = owner
        self._project = project
        self.details: Optional[ProjectDetails] = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self._head(), id="detail-head")
        yield Static("", id="detail-status")
        yield Static("", id="detail-commit")
        table = NavDataTable(cursor_type="row", id="worktrees")
        table.add_columns(*WORKTREE_COLUMNS)
        yield table
        yield Static("", id="detail-version")
        yield Footer()

    def _head(self) -> str:
        title = self._project.get("title") or self._project.get("name") or ""
        return f"[bold]{title}[/bold]\n[dim]{self._project['path']}[/dim]"

    def on_mount(self) -> None:
        self.load_details()

    @work(thread=True, exclusive="project-details")
    def load_details(self) -> None:
        path = self._project["path"]
        cached = self._owner.details_cache.get(path)
        if cached is None:
            cached = inspect_project(path, base_branch=self._project.get("git_branch"))
            self._owner.details_cache[path] = cached
        self.app.call_from_thread(self.render_details, cached)

    def render_details(self, details: ProjectDetails) -> None:
        self.details = details
        if not details.is_git:
            self.query_one("#detail-status", Static).update("[yellow]no git[/yellow]")
            self.query_one("#detail-commit", Static).update("")
            self.query_one("#detail-version", Static).update(
                f"Metaproject version: {details.metaproject_version}"
            )
            return

        status = details.status_short.strip() if details.status_short else ""
        status_body = status if status else "clean — no uncommitted changes"
        self.query_one("#detail-status", Static).update(
            f"[bold]Status[/bold]\n{status_body or '(unavailable)'}"
        )
        self.query_one("#detail-commit", Static).update(
            f"[bold]Last commit[/bold]\n{details.last_commit or '(unavailable)'}"
        )

        table = self.query_one("#worktrees", DataTable)
        table.clear()
        if details.worktrees:
            for wt in details.worktrees:
                table.add_row(*worktree_row(wt), key=wt.path)
        else:
            table.display = False

        self.query_one("#detail-version", Static).update(
            f"Metaproject version: {details.metaproject_version}"
        )

    def action_open_worktree(self) -> None:
        if self.details is None or not self.details.worktrees:
            return
        table = self.query_one("#worktrees", DataTable)
        if not table.display or table.row_count == 0:
            return
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        for wt in self.details.worktrees:
            if wt.path == key:
                self.app.push_screen(WorktreeDetailScreen(self._owner, wt))
                return


class WorktreeDetailScreen(Screen):
    """Detail-of-detail (mockup screen 3): the flag names its files; the score shows."""

    BINDINGS = [
        Binding("escape,backspace", "app.pop_screen", "Back to project"),
        Binding("r", "app.refresh_universe", "Refresh"),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self, owner: "UniverseTui", worktree: WorktreeInfo) -> None:
        super().__init__()
        self._owner = owner
        self._worktree = worktree

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self._head(), id="worktree-head")
        yield Static("", id="worktree-body")
        yield Static("", id="worktree-files")
        yield Static("", id="worktree-commit")
        yield Footer()

    def _head(self) -> str:
        branch = self._worktree.branch or "detached"
        return (
            f"[bold]{branch}[/bold]  [dim]·[/dim]  {self._worktree.path}\n"
            f"{verdict_label(self._worktree)} [dim]·[/dim] {score_line(self._worktree)}\n"
            f"ahead {self._worktree.ahead_count} · behind {self._worktree.behind_count}"
        )

    def on_mount(self) -> None:
        self.load_worktree()

    @work(thread=True, exclusive="worktree-details")
    def load_worktree(self) -> None:
        wt = inspect_worktree(self._worktree)
        files = uncommitted_files(wt.path)
        commit = last_commit(wt.path)
        self.app.call_from_thread(self.render_worktree, wt, files, commit)

    def render_worktree(self, wt: WorktreeInfo, files: list, commit: Optional[str]) -> None:
        self.query_one("#worktree-head", Static).update(self._head_for(wt))
        age = format_age(wt.head_age_days)
        base = f"base {wt.base_branch}" if wt.base_branch else "base undeterminable"
        self.query_one("#worktree-body", Static).update(
            f"Age {age} · {base} · ahead {wt.ahead_count} / behind {wt.behind_count}\n"
            f"{verdict_label(wt)} [dim]·[/dim] {score_line(wt)}"
        )
        if wt.flag:
            listing = "\n".join(f"  {line}" for line in files) if files else "  (unavailable)"
            self.query_one("#worktree-files", Static).update(
                f"[bold]⚠ Uncommitted files ({wt.uncommitted_count})[/bold]\n{listing}"
            )
        else:
            self.query_one("#worktree-files", Static).update("[dim]No uncommitted changes[/dim]")
        self.query_one("#worktree-commit", Static).update(
            f"[bold]Last commit[/bold]\n{commit or '(unavailable)'}"
        )

    def _head_for(self, wt: WorktreeInfo) -> str:
        branch = wt.branch or "detached"
        return f"[bold]{branch}[/bold]  [dim]·[/dim]  {wt.path}"


class UniverseTui(App):
    """The read-only universe browser (R-UNV-2)."""

    TITLE = "metaproject universe"
    BINDINGS = [
        Binding("r", "refresh_universe", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        db_path: Path,
        project_home: Path,
        classification_filter: Optional[str] = None,
        depth: int = 4,
    ) -> None:
        super().__init__()
        self.db_path = Path(db_path)
        self.project_home = Path(project_home)
        self.classification_filter = classification_filter
        self.depth = depth
        self.details_cache: Dict[str, ProjectDetails] = {}

    def on_mount(self) -> None:
        self.push_screen(UniverseListScreen(self))

    def action_refresh_universe(self) -> None:
        self._rescan()

    @work(thread=True, exclusive="rescan")
    def _rescan(self) -> None:
        """The explicit scan trigger (R-UNV-2e): the same call the CLI table path makes."""
        db = get_db(self.db_path)
        scan_universe(self.project_home, max_depth=self.depth, interactive=False, db=db)
        self.details_cache.clear()  # the refresh invalidates the in-session cache
        self.call_from_thread(self._after_rescan)

    def _after_rescan(self) -> None:
        screen = self.screen
        if isinstance(screen, UniverseListScreen):
            screen.reload_rows()
        elif isinstance(screen, ProjectDetailScreen):
            screen.load_details()
        elif isinstance(screen, WorktreeDetailScreen):
            screen.load_worktree()


def run_tui(
    db_path: Path,
    project_home: Path,
    classification_filter: Optional[str] = None,
    depth: int = 4,
) -> None:
    """Open the browser. The caller has gated on `tui_enabled` (R-UNV-5)."""
    UniverseTui(
        db_path=db_path,
        project_home=project_home,
        classification_filter=classification_filter,
        depth=depth,
    ).run()
