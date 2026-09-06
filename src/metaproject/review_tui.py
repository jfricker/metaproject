"""The `review --all` compliance board (spec.md §5.3) — a `rich` remediation loop.

Two screens, both painted with `rich` and driven by typed commands rather than a widget
framework's event loop, matching `learn`'s reviewer (plan.md R9):

**The board** is the `Project Drift & Governance Review` table: one row per project,
answering *which project do I open next* and nothing finer. It opens with the aggregate
score and the scan context, names the defect (`CLEAN` / `DRIFTED` / `INCOMPLETE`) and
counts what is wrong; the file names themselves live on the detail screen one keystroke
away, because a triage view that comma-joins eight deliverables into a wrapping cell
stops being scannable at exactly the moment it matters.

**The detail screen** is where the writes happen. It lists the project's missing and
drifted deliverables, numbered, and each write goes through `review.deploy_entry` or
`review.update_entry` — the same functions the non-interactive path would call, so the
board is an interface to the engine and never a second implementation of it.

Both screens read **verb first** — `u 3`, `d 2`, `i 4` — so one grammar survives the
transition between them; the board still accepts the number-first `3u` it used to
require, because muscle memory outlives a redesign. Commands take an optional argument
(`u 2`, `d all`), so this reads a *line* rather than the single keystroke `learn` uses.
Everything is durable the moment it is typed; quitting loses nothing because there is
nothing buffered.

Two rules govern how the screens are painted. **State is never signalled by colour
alone** — every state word carries a glyph, so a colourblind operator, a `NO_COLOR`
terminal and a piped log all read the same verdict. And the palette is deliberately
narrow: cyan is the one structural accent, red/yellow/green mean compliance state and
nothing else, and bold marks the key an operator types rather than the label beside it.
Emphasis spent everywhere is emphasis that says nothing.
"""

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Sequence, Tuple

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from metaproject.exceptions import MetaProjectError
from metaproject.review import (
    ReviewResult,
    deploy_entry,
    ignore_project,
    resolve_variables,
    update_entry,
)

ACTION_UPDATE = "u"
ACTION_DEPLOY = "d"
ACTION_IGNORE = "i"
ACTION_OK = "o"
ACTION_HELP = "?"
ACTION_QUIT = "q"
# Empty input. Distinct from "unparseable" so a stray Enter repaints in silence instead of
# being scolded, and distinct from quit because Enter must never tear down the session.
ACTION_NOOP = ""

ACTION_VIEW = "v"
ACTION_CLOSE = "c"
ACTION_BACK = "b"

# The state word names the defect, not a grade. `PASS`/`DRIFT` did neither: `PASS` was
# shown for a project that had drifted, `DRIFT` for one that was missing files, and
# `Drift` was also a column heading — three ways to say the wrong thing at once.
#
# The glyph is what makes the word survive `NO_COLOR`, a piped board and a colourblind
# reader; rich strips the style and the meaning stays behind in the character.
GLYPH_CLEAN = "✓"
GLYPH_DRIFTED = "~"
GLYPH_INCOMPLETE = "!"

STATE_CLEAN = f"[green]{GLYPH_CLEAN} CLEAN[/green]"
STATE_DRIFTED = f"[yellow]{GLYPH_DRIFTED} DRIFTED[/yellow]"
STATE_INCOMPLETE = f"[red]{GLYPH_INCOMPLETE} INCOMPLETE[/red]"

BOARD_TITLE = "Project Drift & Governance Review"

# Zero is the answer the eye should skip. A count of `0` reads as data worth checking;
# an em-dash reads as "nothing here", which is what it means.
COUNT_NONE = "[dim]—[/dim]"

# How much of the detail screen the diff does *not* get: the project panel, the file
# table, the notice line and the key bar. Only a diff that overflows what is left is
# worth handing to a pager.
SCREEN_CHROME_LINES = 14

BOARD_KEY_BAR = (
    "[dim]Select a row:[/dim] [bold]u[/bold] <n> update  [bold]d[/bold] <n> deploy  "
    "[bold]i[/bold] <n> ignore  [bold]o[/bold] <n> ok  [bold]<n>[/bold] open  "
    "[bold]?[/bold] help  [bold]q[/bold] quit"
)

DETAIL_KEY_BAR = (
    "[bold]u[/bold] <n> update  [bold]d[/bold] <n> deploy  [bold]v[/bold] <n> diff  "
    "[bold]c[/bold] close diff  [bold]o[/bold] ok  [bold]i[/bold] ignore  "
    "[bold]?[/bold] help  [bold]b[/bold] back  [bold]q[/bold] quit"
)

BOARD_HELP = (
    "u <n>    open project n — its drifted files are listed there\n"
    "d <n>    open project n — its missing deliverables are listed there\n"
    "<n>      the same as u <n>\n"
    "i <n>    ignore project n — recorded; it is not reviewed again until --unignore\n"
    "o <n>    ok — drop project n from this board; it is audited again next review\n"
    "?        this help\n"
    "q        quit\n"
    "\n"
    "Verb first (u 3) or number first (3u) — both select the same row."
)

DETAIL_HELP = (
    "u <n>    update just the numbered drifted file\n"
    "u all    update every drifted file from its rendered template (asks first)\n"
    "d <n>    deploy just the numbered missing deliverable\n"
    "d all    deploy every missing deliverable from its template (asks first)\n"
    "v <n>    show the unified diff for a drifted file; it stays up until c\n"
    "v        the same, when exactly one file has drifted\n"
    "c        close the pinned diff\n"
    "o        ok — dismiss this project for now; it is checked again next review\n"
    "i        ignore this project — it is not checked again until --unignore\n"
    "?        this help\n"
    "b        back to the board\n"
    "q        quit"
)


@dataclass
class BoardResult:
    """What one board session did. Every entry is already durable on disk."""

    deployed: List[Tuple[str, str]] = field(default_factory=list)
    updated: List[Tuple[str, str]] = field(default_factory=list)
    ignored: List[str] = field(default_factory=list)
    dismissed: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    quit_early: bool = False

    @property
    def actioned(self) -> int:
        """How many durable writes and decisions the operator made.

        `dismissed` is deliberately excluded: OK is a session-local "not now", not a
        recorded judgment, and counting it would overstate what the review changed.
        """
        return len(self.deployed) + len(self.updated) + len(self.ignored)


# ------------------------------------------------------------------------------ painting


def compliance_cell(result: ReviewResult) -> str:
    """The `Compliance` column: three states, each named for the defect it reports.

    `CLEAN` matches the templates exactly, `DRIFTED` has every deliverable but has
    diverged in content, `INCOMPLETE` is missing one. A project that is both incomplete
    and drifted reads `INCOMPLETE`, because the missing file is the defect that has to be
    fixed first — a file that is not there cannot be reconciled.
    """
    if not result.is_compliant:
        return STATE_INCOMPLETE
    return STATE_CLEAN if result.is_clean else STATE_DRIFTED


def count_cell(count: int, style: str) -> str:
    """One `Missing`/`Drifted` count, quiet at zero."""
    return f"[{style}]{count}[/{style}]" if count else COUNT_NONE


def summary_header(
    results: Sequence[ReviewResult],
    scan_root: Optional[Path] = None,
    templates_dir: Optional[Path] = None,
    ignored_count: Optional[int] = None,
) -> Panel:
    """The score and the scan context, above the table.

    A board that opens with a bare row count makes the operator total the column
    themselves, and the total is the first thing a governance tool is asked for. The
    context is the other half of a verdict: "two drifted" means nothing until it says
    *what was audited* and *which template store it was measured against*.

    Every argument is optional and the header degrades one line at a time, because the
    board is also rendered by callers that know none of this. The store falls back to the
    one the results themselves record, so the header can never name a different store
    from the audit it heads.
    """
    states = [compliance_cell(res) for res in results]
    tally = " · ".join(
        (
            f"[bold]{len(results)}[/bold] projects",
            f"{STATE_CLEAN} {states.count(STATE_CLEAN)}",
            f"{STATE_DRIFTED} {states.count(STATE_DRIFTED)}",
            f"{STATE_INCOMPLETE} {states.count(STATE_INCOMPLETE)}",
        )
    )
    if ignored_count is not None:
        tally += f" · [dim]{ignored_count} on the ignore list[/dim]"

    lines = [Text.from_markup(tally)]

    store = templates_dir or (results[0].templates_dir if results else None)
    context: List[str] = []
    if scan_root is not None:
        context.append(f"[dim]scanned[/dim] [cyan]{scan_root}[/cyan]")
    if store is not None:
        context.append(f"[dim]against[/dim] [cyan]{store}[/cyan]")
    if context:
        # Truncated rather than wrapped: two deep paths would otherwise turn the header
        # into a paragraph, and the tail of a path is not what identifies it.
        where = Text.from_markup(" ".join(context))
        where.no_wrap = True
        where.overflow = "ellipsis"
        lines.append(where)

    return Panel(Group(*lines), title=BOARD_TITLE, title_align="left", border_style="cyan")


def review_table(
    results: Sequence[ReviewResult],
    scan_root: Optional[Path] = None,
    templates_dir: Optional[Path] = None,
    ignored_count: Optional[int] = None,
) -> Group:
    """The board: the summary header over the table. Row numbers are the selection handles.

    Counts, not file names: the board answers "which project do I open next", and the
    comma-joined name lists it used to carry wrapped every row into a ragged block while
    duplicating the detail screen, which lists the same names numbered and actionable.

    Returned as one renderable so the interactive loop and the `--no-tui` printout cannot
    drift into showing different boards.
    """
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Project", style="cyan")
    table.add_column("Compliance", justify="center")
    table.add_column("Missing", justify="right")
    table.add_column("Drifted", justify="right")

    for index, res in enumerate(results, start=1):
        table.add_row(
            str(index),
            res.project_name,
            compliance_cell(res),
            count_cell(len(res.missing_files), "red"),
            count_cell(len(res.diffs), "yellow"),
        )

    return Group(summary_header(results, scan_root, templates_dir, ignored_count), table)


def detail_table(result: ReviewResult) -> Table:
    """The numbered file list on the detail screen: what is missing, and what has drifted.

    Numbering is continuous across both sections so `v 4` is unambiguous; `Action` says
    which verb applies to each row, because only one of them ever does.
    """
    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("#", justify="right", style="dim")
    table.add_column("File")
    table.add_column("State")
    # The accent, not `dim`: with the focus concept gone every verb here is live, and a
    # dimmed column reads as disabled.
    table.add_column("Action", style="cyan")

    missing = set(result.missing_files)
    for index, name in enumerate(detail_entries(result), start=1):
        state, verb = (
            (f"[red]{GLYPH_INCOMPLETE} missing[/red]", "Deploy")
            if name in missing
            else (f"[yellow]{GLYPH_DRIFTED} drifted[/yellow]", "Update")
        )
        table.add_row(str(index), name, Text.from_markup(state), verb)

    return table


def detail_entries(result: ReviewResult) -> List[str]:
    """The numbered rows of the detail screen: missing files first, then drifted ones."""
    return [*result.missing_files, *result.updatable]


def diff_panel(name: str, diff: str, max_lines: Optional[int] = None) -> Panel:
    """One drifted file's unified diff, optionally cut to what the screen can hold.

    The cut is a head, not a sample: a diff reads from the top, and the pager has the
    rest. `max_lines=None` renders it whole, which is what the pager itself wants.
    """
    lines = diff.splitlines()
    if max_lines is not None and len(lines) > max_lines:
        body = Group(
            Syntax("\n".join(lines[:max_lines]), "diff", theme="ansi_dark", word_wrap=True),
            Text.from_markup(
                f"[dim]… {len(lines) - max_lines} more lines — v <n> reopens the pager[/dim]"
            ),
        )
    else:
        body = Group(Syntax(diff, "diff", theme="ansi_dark", word_wrap=True))
    return Panel(body, title=name, title_align="left", border_style="cyan")


def diff_overflows(console: Console, diff: str, interactive: bool) -> bool:
    """Is this diff tall enough to be worth a pager, on a terminal that has one?

    Never outside an interactive session: `clear=False` and a non-TTY stdout are how the
    tests and every scripted caller drive these loops, and a pager there blocks forever.
    """
    if not interactive or not console.is_terminal:
        return False
    return len(diff.splitlines()) > max(console.size.height - SCREEN_CHROME_LINES, 1)


def render_detail(
    console: Console,
    result: ReviewResult,
    notice: Optional[str] = None,
    diff_for: Optional[str] = None,
    show_help: bool = False,
    max_diff_lines: Optional[int] = None,
) -> None:
    """Paint the detail screen. Nothing here writes; the loop performs every action."""
    console.print()
    console.print(
        Panel.fit(
            f"[bold]{result.project_name}[/bold] [dim]·[/dim] {result.project_path}",
            border_style="cyan",
        )
    )

    if not detail_entries(result):
        console.print(
            f"{STATE_CLEAN} — nothing missing, nothing drifted. "
            "[dim]Press o to dismiss it for now; it is checked again next review.[/dim]",
            highlight=False,
        )
    else:
        console.print(detail_table(result))

    if diff_for:
        diff = result.diffs.get(diff_for)
        if diff:
            console.print(diff_panel(diff_for, diff, max_diff_lines))
        else:
            console.print(f"[dim]No diff recorded for {diff_for}.[/dim]")

    if show_help:
        console.print(Panel(DETAIL_HELP, title="Commands", title_align="left", border_style="cyan"))
    # `highlight=False` throughout: rich's auto-highlighter paints the `n` inside `<n>` as a
    # variable and leaves the brackets unstyled, so instructional lines arrive miscoloured.
    #
    # The notice line is printed whether or not there is a notice, so the key bar sits at
    # the same height every frame and an error does not shove it down the screen.
    console.print(notice or "", highlight=False)
    console.print(DETAIL_KEY_BAR, highlight=False)


# ------------------------------------------------------------------------ command input


def read_command(console: Console, prompt: str = "> ") -> str:
    """Read one command line. A closed stdin ends the session rather than looping."""
    try:
        return console.input(prompt)
    except (EOFError, KeyboardInterrupt):
        return "q"


# Verb-first (`u 3`) is the grammar both screens teach; number-first (`3u`) is the one the
# board used to require and still answers to, identically. One optional space, one verb,
# one number, nothing else — the alternation is anchored by `fullmatch`.
BOARD_COMMAND = re.compile(r"([a-z])\s*(\d+)|(\d+)\s*([a-z])?")


def confirm_write(console: Console, question: str) -> bool:
    """Ask before a batch write, defaulting to no.

    Empty input and a closed stdin both decline: the answer that overwrites files is
    never the one an operator can give by reflex.
    """
    try:
        answer = console.input(f"{question} [y/N] ")
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in ("y", "yes")


def parse_board_command(raw: str, total: int) -> Tuple[Optional[int], Optional[str]]:
    """Parse `u 3`, `3u`, `3`, `?` or `q` into a (row index, action) pair.

    Both grammars round-trip to the same pair. Verb-first is what the key bars teach and
    what the detail screen has always used — `u 3` reads like vim and like git, and one
    grammar across both screens means muscle memory survives the screen transition — but
    number-first is what this board used to require, so it keeps working silently.

    Four non-selections, deliberately told apart: `(None, ACTION_QUIT)` for a literal
    `q`, `(None, ACTION_HELP)` for `?`, `(None, ACTION_NOOP)` for empty input, and
    `(None, None)` for anything else. The match is strict — one verb, one number, nothing
    else — because a lenient reading of `1 2` as row 12 would run a destructive verb
    against a project the operator never picked.
    """
    text = (raw or "").strip().lower()
    if not text:
        return None, ACTION_NOOP
    if text == ACTION_QUIT:
        return None, ACTION_QUIT
    if text == ACTION_HELP:
        return None, ACTION_HELP

    match = BOARD_COMMAND.fullmatch(text)
    if match is None:
        return None, None

    verb, number = (
        (match.group(1), match.group(2))
        if match.group(1) is not None
        else (match.group(4), match.group(3))
    )

    index = int(number)
    if not 1 <= index <= total:
        return None, None

    action = verb or ACTION_UPDATE
    if action not in (ACTION_UPDATE, ACTION_DEPLOY, ACTION_IGNORE, ACTION_OK):
        return None, None
    return index - 1, action


def parse_detail_command(raw: str) -> Tuple[str, Optional[str]]:
    """Parse `u`, `u 2`, `v 3`, `b`, `q` into a (verb, argument) pair."""
    parts = (raw or "").strip().lower().split()
    if not parts:
        return "", None
    verb = parts[0][:1]
    argument = parts[1] if len(parts) > 1 else (parts[0][1:] or None)
    return verb, argument


def _selected_entries(
    result: ReviewResult,
    argument: Optional[str],
    candidates: Sequence[str],
) -> Tuple[List[str], Optional[str]]:
    """Resolve `u 2` / `u all` to the file names the verb should act on.

    A missing argument selects *nothing*. Folding it into `all` is how a bare `u` came to
    overwrite every drifted file in a project unasked; the caller now has to ask.
    """
    if argument is None:
        return [], None
    if argument == "all":
        return list(candidates), None

    if not argument.isdigit():
        return [], f"[dim]Not a row number: {argument!r}[/dim]"

    entries = detail_entries(result)
    index = int(argument) - 1
    if not 0 <= index < len(entries):
        return [], f"[dim]No row {argument} on this screen.[/dim]"

    name = entries[index]
    if name not in set(candidates):
        return [], f"[yellow]{name} is not available for that action.[/yellow]"
    return [name], None


# --------------------------------------------------------------------------- the loops


@contextmanager
def alt_screen(console: Console, clear: bool) -> Iterator[None]:
    """Run a loop on the terminal's alternate screen, restoring what was there on exit.

    `console.clear()` scrolls the operator's session history away for good; the alternate
    screen hands it back intact when the review ends. The cursor stays visible because
    these screens are typed at, not watched.

    `clear=False` — how every test and every non-TTY caller drives the loops — is the
    old inline behaviour untouched, and a nested call is a no-op because rich's alternate
    screen is not re-entrant: an inner exit would drop the outer loop back to the normal
    screen mid-session.
    """
    if not clear or console.is_alt_screen:
        yield
        return
    with console.screen(hide_cursor=False):
        yield


def _page(console: Console, renderable: RenderableType) -> None:
    """Hand a renderable to the operator's pager, styles intact."""
    with console.pager(styles=True):
        console.print(renderable)


def run_detail(
    console: Console,
    result: ReviewResult,
    templates_dir: Optional[Path],
    outcome: BoardResult,
    reader: Optional[Callable[[], str]] = None,
    confirm: Optional[Callable[[str], bool]] = None,
    refresh: Optional[Callable[[], ReviewResult]] = None,
    clear: bool = True,
) -> str:
    """Run the detail screen for one project.

    Returns `'back'`, `'quit'`, `'dismissed'` (OK — leave the board for now) or
    `'ignored'` (recorded; not checked again). `confirm` is injected the same way
    `reader` is, so a test can answer the batch-write gate without a TTY.

    A viewed diff stays **pinned** until `c` closes it or the update it argued for lands.
    Clearing it on the next repaint meant the evidence vanished at the exact moment the
    operator typed the `u 3` it justified.
    """
    reader = reader or (lambda: read_command(console))
    confirm = confirm or (lambda question: confirm_write(console, question))
    project_path = Path(result.project_path)
    notice: Optional[str] = None
    diff_for: Optional[str] = None
    show_help = False

    with alt_screen(console, clear):
        while True:
            if clear:
                console.clear()
            render_detail(
                console,
                result,
                notice,
                diff_for,
                show_help,
                max_diff_lines=max(console.size.height - SCREEN_CHROME_LINES, 1) if clear else None,
            )
            show_help = False

            verb, argument = parse_detail_command(reader())

            if verb == ACTION_NOOP:
                continue
            if verb == ACTION_QUIT:
                outcome.quit_early = True
                return "quit"
            if verb == ACTION_BACK:
                return "back"
            if verb == ACTION_HELP:
                show_help = True
                continue
            if verb == ACTION_CLOSE:
                diff_for = None
                continue

            if verb == ACTION_OK:
                # Session-local: nothing is written, and the project is reviewed again next
                # time. That is the whole difference between OK and Ignore.
                outcome.dismissed.append(str(project_path))
                return "dismissed"

            if verb == ACTION_IGNORE:
                if ignore_project(project_path):
                    outcome.ignored.append(str(project_path))
                return "ignored"

            if verb == ACTION_VIEW:
                drifted = result.updatable
                if argument is None and len(drifted) == 1:
                    # One drifted file is not an ambiguous request. Demanding a row number
                    # for the only row on offer is a rule enforced against nobody.
                    diff_for, notice = drifted[0], None
                elif argument is None:
                    notice = (
                        "[dim]Name a row: v <n>[/dim]"
                        if drifted
                        else "[dim]Nothing has drifted here.[/dim]"
                    )
                else:
                    names, problem = _selected_entries(result, argument, drifted)
                    if problem:
                        notice = problem
                    elif names and argument.isdigit():
                        diff_for, notice = names[0], None
                    else:
                        notice = "[dim]Name a row: v <n>[/dim]"

                # A 400-line diff painted onto the screen takes the screen with it, so
                # one that will not fit goes to the pager first and stays pinned after.
                diff = result.diffs.get(diff_for or "")
                if diff and diff_overflows(console, diff, clear):
                    _page(console, diff_panel(diff_for or "", diff))
                continue

            if verb in (ACTION_DEPLOY, ACTION_UPDATE):
                deploying = verb == ACTION_DEPLOY
                if argument is None:
                    notice = (
                        f"[dim]Say which: {verb} <n> for one file, {verb} all for every one.[/dim]"
                    )
                    continue

                pool = result.deployable if deploying else result.updatable
                names, problem = _selected_entries(result, argument, pool)
                if problem:
                    notice = problem
                    continue
                if not names:
                    notice = (
                        "[dim]Nothing to deploy here.[/dim]"
                        if deploying
                        else "[dim]Nothing has drifted here.[/dim]"
                    )
                    continue

                # A batch is the only irreversible shape on this screen, so it is the only
                # one that asks. Update names the damage explicitly: it discards whatever
                # the operator wrote in those files, while deploy only fills in what is
                # absent.
                if argument == "all":
                    question = (
                        f"Deploy {len(names)} missing file(s) into {result.project_name}?"
                        if deploying
                        else f"Overwrite {len(names)} file(s) in {result.project_name} with "
                        "template content, discarding local edits?"
                    )
                    if not confirm(question):
                        notice = "[dim]Cancelled — nothing was written.[/dim]"
                        continue

                # One variable resolution for the whole batch: see `review.resolve_variables`.
                variables = resolve_variables(project_path)
                done: List[str] = []
                for name in names:
                    try:
                        if deploying:
                            deploy_entry(project_path, name, templates_dir, variables=variables)
                            outcome.deployed.append((str(project_path), name))
                        else:
                            update_entry(project_path, name, templates_dir, variables=variables)
                            outcome.updated.append((str(project_path), name))
                        done.append(name)
                    except MetaProjectError as exc:
                        # A refused write leaves the rest of the screen usable, exactly as a
                        # refused apply does in the `learn` reviewer.
                        outcome.errors.append(f"{result.project_name}/{name}: {exc}")
                        notice = f"[bold red]Failed:[/bold red] {exc}"

                if done:
                    word = "Deployed" if deploying else "Updated"
                    notice = f"[green]{word}:[/green] {', '.join(done)}"
                    if refresh is not None:
                        result = refresh()
                    # The pinned diff argued for a write that has now landed; keeping it
                    # up would show the operator a difference that no longer exists.
                    if diff_for not in result.diffs:
                        diff_for = None
                continue

            notice = f"[dim]Unrecognized command {verb!r}. Press ? for help.[/dim]"


def run_board(
    results: Sequence[ReviewResult],
    templates_dir: Optional[Path] = None,
    console: Optional[Console] = None,
    reader: Optional[Callable[[], str]] = None,
    confirm: Optional[Callable[[str], bool]] = None,
    clear: bool = True,
    reviewer: Optional[Callable[..., ReviewResult]] = None,
    scan_root: Optional[Path] = None,
    ignored_count: Optional[int] = None,
) -> BoardResult:
    """Paint the board and act on selections until the operator quits.

    Three of the actions remove a row. **Ignore** records the project as permitted to
    stay out of compliance and it is never reviewed again; **OK** dismisses it for this
    session only and it is audited again next review; a project remediated to `CLEAN`
    stays on the board, re-audited, so the operator can see the result of the write.

    `scan_root` and `ignored_count` are the parts of the scan context the board cannot
    know — the caller ran the scan — and both are optional so the board still renders for
    a caller that has neither.
    """
    from metaproject.review import review_project

    console = console or Console()
    reader = reader or (lambda: read_command(console))
    reviewer = reviewer or review_project
    rows = list(results)
    outcome = BoardResult()
    notice: Optional[str] = None
    show_help = False

    with alt_screen(console, clear):
        while rows:
            if clear:
                console.clear()
            console.print(review_table(rows, scan_root, templates_dir, ignored_count))
            if show_help:
                console.print(
                    Panel(BOARD_HELP, title="Commands", title_align="left", border_style="cyan")
                )
                show_help = False
            # Printed every frame, notice or not, so the key bar never moves and a notice
            # survives until a command replaces it rather than for one repaint.
            console.print(notice or "", highlight=False)
            console.print(BOARD_KEY_BAR, highlight=False)

            index, action = parse_board_command(reader(), len(rows))

            if action == ACTION_QUIT:
                outcome.quit_early = True
                break
            if action == ACTION_NOOP:
                continue
            if action == ACTION_HELP:
                show_help = True
                continue
            if index is None or action is None:
                notice = "[dim]Name a verb and a row, e.g. u 2, d 2, i 2 or o 2. ? for help.[/dim]"
                continue

            selected = rows[index]
            project_path = Path(selected.project_path)

            if action == ACTION_OK:
                # OK dismisses the row for this session only — no ledger entry, so the
                # project is audited again on the next review.
                outcome.dismissed.append(str(project_path))
                rows.pop(index)
                notice = f"[dim]OK:[/dim] {selected.project_name} — checked again next review"
                continue

            if action == ACTION_IGNORE:
                if ignore_project(project_path):
                    outcome.ignored.append(str(project_path))
                rows.pop(index)
                notice = f"[green]Ignored:[/green] {selected.project_name}"
                continue

            # `u <n>` and `d <n>` both open the same screen. They were once two "focuses"
            # that dimmed a different column and changed no behaviour at all.
            outcome_of_detail = run_detail(
                console,
                selected,
                templates_dir,
                outcome,
                reader=reader,
                confirm=confirm,
                refresh=lambda: reviewer(project_path, templates_dir),
                clear=clear,
            )

            if outcome_of_detail == "quit":
                break
            if outcome_of_detail == "dismissed":
                rows.pop(index)
                notice = f"[dim]OK:[/dim] {selected.project_name} — checked again next review"
                continue
            if outcome_of_detail == "ignored":
                rows.pop(index)
                notice = f"[green]Ignored:[/green] {selected.project_name}"
                continue

            # Re-audit the project we just left so the board reflects what was written. A
            # failure here leaves a stale row, which is exactly the state an operator would
            # misread as "the write landed" — so it is recorded and said out loud, though it
            # never ends the session.
            try:
                rows[index] = reviewer(project_path, templates_dir)
                notice = None
            except Exception as exc:
                outcome.errors.append(f"{selected.project_name}: re-audit failed: {exc}")
                notice = (
                    f"[bold red]Re-audit failed:[/bold red] {selected.project_name} — {exc} "
                    "[dim](the row below may be stale)[/dim]"
                )

    return outcome
