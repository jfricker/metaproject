"""The `learn` acceptance TUI (spec.md §5.4.5) — a `rich` review loop.

Built on `rich`, which is already an approved dependency: side-by-side and unified
diffs are `rich` tables and `Syntax` blocks, and the loop reads single keystrokes and
repaints rather than running a widget framework's event loop (plan.md R9).

**One queue, two interfaces** (plan.md §1.3.2). Every keystroke performs exactly the
subcommand named in its Action column and writes through to `universe.db` immediately:

| Key | Action     | Equivalent          |
|-----|------------|---------------------|
| `a` | Accept     | `learn apply <id>`  |
| `e` | Edit       | `learn edit <id>`   |
| `d` | Discard    | `learn reject <id>` |
| `s` | Skip       | —                   |

`a` and `e` call `plan_apply` / `apply_plan`, `d` calls `store.reject_proposal`, and `e`
calls the same `open_in_editor` that `learn edit` uses — this module owns that helper
and `cli.py` delegates to it, so there is one implementation rather than two that can
drift. Nothing is buffered in the session: a review can be abandoned at any point and
finished from the CLI without loss or divergence.
"""

import difflib
import os
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import sqlite_utils
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from metaproject.exceptions import MetaProjectError
from metaproject.learn.apply import (
    PLACEMENT_APPEND,
    PLACEMENT_NEW_FILE,
    ApplyPlan,
    apply_plan,
    plan_apply,
    proposal_body,
)
from metaproject.learn.score import order_queue
from metaproject.learn.store import (
    get_evidence,
    get_proposal,
    reject_proposal,
    set_edited_body,
)

VIEW_SIDE_BY_SIDE = "side-by-side"
VIEW_UNIFIED = "unified"

# Below this the two diff columns cannot both hold a useful amount of a Markdown line,
# so the unified view is the honest rendering (spec.md §5.4.10).
SIDE_BY_SIDE_MIN_WIDTH = 100

# Lines of unchanged context kept around each hunk in the side-by-side view.
DIFF_CONTEXT = 3

KEY_ACCEPT = "a"
KEY_EDIT = "e"
KEY_DISCARD = "d"
KEY_SKIP = "s"
KEY_VIEW = "u"
KEY_PROVENANCE = "p"
KEY_HELP = "?"
KEY_QUIT = "q"

KEY_BAR = (
    "[bold]\\[a][/bold]ccept  [bold]\\[e][/bold]dit  [bold]\\[d][/bold]iscard  "
    "[bold]\\[s][/bold]kip  [bold]\\[u][/bold]nified  [bold]\\[p][/bold]rovenance  "
    "[bold]\\[?][/bold]  [bold]\\[q][/bold]uit"
)

HELP_TEXT = (
    "a  accept — write the proposal into the template, commit, mark applied, advance\n"
    "e  edit   — open the body in $EDITOR; saving applies the edited text\n"
    "d  discard— mark rejected; suppressed by content hash, resurfaces on stronger evidence\n"
    "s  skip   — leave pending and advance; the candidate reappears next review\n"
    "u  toggle the side-by-side and unified diff views\n"
    "p  expand the full contributing-project list with absolute paths\n"
    "q  quit   — everything already actioned is persisted; the rest stays pending"
)


@dataclass(frozen=True)
class SessionResult:
    """What one review session did. Every field is already durable in `universe.db`."""

    applied: Tuple[int, ...] = ()
    rejected: Tuple[int, ...] = ()
    skipped: Tuple[int, ...] = ()
    edited: Tuple[int, ...] = ()
    remaining: Tuple[int, ...] = ()
    quit_early: bool = False
    errors: Tuple[str, ...] = ()

    @property
    def actioned(self) -> int:
        """How many candidates the operator resolved one way or another."""
        return len(self.applied) + len(self.rejected)


# ------------------------------------------------------------------------- degradation


def stdout_is_a_terminal(stream: Optional[Any] = None) -> bool:
    """Is output going to a terminal? A separate seam so `TERM=dumb` is testable alone."""
    stream = sys.stdout if stream is None else stream
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def tui_enabled(
    no_tui: bool = False,
    stream: Optional[Any] = None,
    env: Optional[Dict[str, str]] = None,
) -> bool:
    """Should the interactive loop be opened at all? (spec.md §5.4.5 "Degradation")

    Three triggers, all of them non-errors: `--no-tui`, `TERM=dumb`, and stdout not
    being a TTY. Scripted and CI use therefore needs no special flag.
    """
    if no_tui:
        return False

    env = os.environ if env is None else env
    if str(env.get("TERM", "") or "").strip().lower() == "dumb":
        return False

    return stdout_is_a_terminal(stream)


def should_open_tui(
    rows: Sequence[Dict[str, Any]],
    no_tui: bool = False,
    stream: Optional[Any] = None,
    env: Optional[Dict[str, str]] = None,
) -> bool:
    """`tui_enabled`, plus the rule that an empty queue never opens the reviewer."""
    if not rows:
        return False
    return tui_enabled(no_tui=no_tui, stream=stream, env=env)


def effective_view(view: str, width: int) -> str:
    """The view actually painted: side-by-side degrades to unified on a narrow terminal."""
    if view == VIEW_SIDE_BY_SIDE and width < SIDE_BY_SIDE_MIN_WIDTH:
        return VIEW_UNIFIED
    return view


def toggle_view(view: str) -> str:
    """What `u` does."""
    return VIEW_UNIFIED if view == VIEW_SIDE_BY_SIDE else VIEW_SIDE_BY_SIDE


# ---------------------------------------------------------------------------- ordering


def order_for_review(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Candidates loop within a template; templates rank by their best candidate.

    The base ordering is `score.order_queue`, the same one `learn list` and
    `learn review` read, so the three interfaces can never disagree about what is next.
    Grouping is a stable re-sort on top of it, never a second ORDER BY.
    """
    ordered = order_queue(list(rows))
    first_seen: Dict[str, int] = {}
    for position, row in enumerate(ordered):
        target = str(row.get("target_file") or "")
        first_seen.setdefault(target, position)
    return sorted(ordered, key=lambda row: first_seen[str(row.get("target_file") or "")])


# ------------------------------------------------------------------------------ editor


def open_in_editor(text: str, suffix: str = ".md") -> Optional[str]:
    """Open `text` in `$EDITOR` and return the saved result, or None if the edit aborted.

    Returning None covers every failure spec.md §5.4.10 folds together — `$EDITOR`
    unset, the editor exiting non-zero, or the operator leaving the text unchanged —
    because the caller's response to all three is the same: keep the candidate pending.
    In the TUI that means staying on the candidate; from `learn edit` it means saying so
    and exiting zero. Neither is an error, and both are the same code path.
    """
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        return None

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"proposal{suffix}"
        path.write_text(text, encoding="utf-8")
        result = subprocess.run([*shlex.split(editor), str(path)], check=False)
        if result.returncode != 0:
            return None
        edited = path.read_text(encoding="utf-8")

    return edited if edited.strip() and edited != text else None


# ------------------------------------------------------------------------- keystrokes


def read_key(stream: Optional[Any] = None) -> str:
    """Read one keystroke, unbuffered on a real terminal and line-wise elsewhere."""
    stream = sys.stdin if stream is None else stream

    try:
        interactive = stream.isatty()
        fd = stream.fileno()
    except Exception:
        interactive = False
        fd = -1

    if not interactive:  # pragma: no cover - exercised only outside a terminal
        line = stream.readline()
        return line.strip()[:1].lower() if line else KEY_QUIT

    import termios
    import tty

    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        char = stream.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    if char in ("\x03", "\x04"):  # Ctrl-C / Ctrl-D end the session, they never act.
        return KEY_QUIT
    return char.lower()


# ---------------------------------------------------------------------------- painting


def diff_rows(
    original: str,
    updated: str,
    context: int = DIFF_CONTEXT,
) -> List[Tuple[str, str, str]]:
    """Aligned `(left, right, style)` rows for the side-by-side view.

    Unchanged text beyond `context` lines from a hunk collapses to a single `…` marker,
    so a one-line insertion into a long template does not paint the whole file.
    """
    left_lines = original.splitlines()
    right_lines = updated.splitlines()
    matcher = difflib.SequenceMatcher(None, left_lines, right_lines, autojunk=False)

    rows: List[Tuple[str, str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            block = [
                (f"  {left_lines[k]}", f"  {right_lines[j1 + k - i1]}", "") for k in range(i1, i2)
            ]
            if len(block) > 2 * context + 1:
                head = block[:context] if rows else []
                rows.extend(head)
                rows.append(("…", "…", "dim"))
                rows.extend(block[-context:])
            else:
                rows.extend(block)
            continue
        for k in range(i1, i2):
            rows.append((f"- {left_lines[k]}", "", "red"))
        for k in range(j1, j2):
            rows.append(("", f"+ {right_lines[k]}", "green"))

    # A trailing all-equal tail after the last hunk is noise; `…` already stands for it.
    while rows and rows[-1][2] == "" and rows[-1][0] == rows[-1][1] == "":  # pragma: no cover
        rows.pop()
    return rows


def side_by_side_table(plan: ApplyPlan) -> Table:
    """The default diff view: template on the left, the proposal's result on the right."""
    table = Table(show_header=True, header_style="bold magenta", expand=True, box=None)
    table.add_column("template (current)", ratio=1, overflow="fold")
    table.add_column("proposed", ratio=1, overflow="fold")
    for left, right, style in diff_rows(plan.original, plan.updated):
        table.add_row(Text(left, style=style or ""), Text(right, style=style or ""))
    return table


def unified_view(plan: ApplyPlan):
    """The narrow-terminal and `u` view: the unified diff, `Syntax`-highlighted."""
    diff = plan.diff()
    if not diff:
        return Text("The template already carries this content; nothing to write.", style="dim")
    return Syntax(diff, "diff", theme="ansi_dark", word_wrap=True)


def header_line(row: Dict[str, Any], index: int, total: int) -> str:
    """`AGENTS.md · candidate 3 of 11 · score 8.4 · seen in 6 projects`."""
    score = float(row.get("evidence_score") or 0.0)
    return (
        f"[bold]{row.get('target_file')}[/bold] · candidate {index + 1} of {total} · "
        f"score {score:.2f} · seen in {int(row.get('evidence_count') or 0)} projects"
    )


def provenance_lines(
    evidence: Sequence[Dict[str, Any]],
    expanded: bool,
    limit: int = 3,
) -> List[str]:
    """The rationale strip's `From:` line, or the full absolute-path list under `p`."""
    paths = [str(item["project_path"]) for item in evidence]
    if not paths:
        return ["From: —"]
    if expanded:
        return ["From:"] + [f"  {path}" for path in paths]
    shown = paths[:limit]
    suffix = f"  (+{len(paths) - len(shown)}, press p)" if len(paths) > len(shown) else ""
    return ["From: " + " · ".join(Path(p).name for p in shown) + suffix]


def render_candidate(
    console: Console,
    row: Dict[str, Any],
    plan: Optional[ApplyPlan],
    plan_error: Optional[str],
    index: int,
    total: int,
    view: str,
    provenance: bool,
    evidence: Sequence[Dict[str, Any]],
    notice: Optional[str] = None,
    show_help: bool = False,
) -> None:
    """Paint one candidate. Nothing here writes; the loop does every state transition."""
    console.print()
    console.print(Panel.fit(header_line(row, index, total), border_style="cyan"))

    if plan is None:
        console.print(f"[bold red]Cannot plan this proposal:[/bold red] {plan_error}")
        console.print(Syntax(str(proposal_body(row)), "markdown", theme="ansi_dark"))
    else:
        # R7: the operator must see *why* a write is landing where it is, before it
        # lands. Dropping this turns a reviewed append back into a silent misplacement.
        if plan.fallback_reason:
            console.print(f"[bold yellow]Warning:[/bold yellow] {plan.fallback_reason}")
        elif plan.placement == PLACEMENT_NEW_FILE:
            console.print(f"[cyan]This creates a new template file: {plan.template_file}[/cyan]")
        elif plan.placement == PLACEMENT_APPEND:
            console.print("[dim]No target section was proposed; appending at end of file.[/dim]")

        if effective_view(view, console.width) == VIEW_SIDE_BY_SIDE:
            console.print(side_by_side_table(plan))
        else:
            console.print(unified_view(plan))

    console.print(f"[bold]Why:[/bold] {row.get('rationale') or '—'}", soft_wrap=True)
    for line in provenance_lines(evidence, provenance):
        console.print(f"[cyan]{line}[/cyan]", soft_wrap=True, highlight=False)

    if show_help:
        console.print(Panel(HELP_TEXT, title="Keys", border_style="dim"))
    if notice:
        console.print(notice)
    console.print(KEY_BAR)


# -------------------------------------------------------------------------- the loop


def _plan_for(
    db: sqlite_utils.Database,
    proposal_id: int,
    templates_dir: Path,
    edited_body: Optional[str] = None,
) -> Tuple[Optional[ApplyPlan], Optional[str]]:
    """Compute what an accept would write, or say why it cannot be computed."""
    try:
        return (
            plan_apply(db, proposal_id, templates_dir=templates_dir, edited_body=edited_body),
            None,
        )
    except MetaProjectError as exc:
        return None, str(exc)


def run_review(
    db: sqlite_utils.Database,
    rows: Sequence[Dict[str, Any]],
    templates_dir: Path,
    console: Optional[Console] = None,
    key_reader: Optional[Callable[[], str]] = None,
    editor: Optional[Callable[[str], Optional[str]]] = None,
    view: str = VIEW_SIDE_BY_SIDE,
    clear: bool = True,
) -> SessionResult:
    """Walk the queue, one keystroke at a time. Every action is durable when pressed."""
    console = console or Console()
    key_reader = key_reader or read_key
    editor = editor or open_in_editor
    templates_dir = Path(templates_dir).expanduser().resolve()

    queue = order_for_review(rows)
    applied: List[int] = []
    rejected: List[int] = []
    skipped: List[int] = []
    edited: List[int] = []
    errors: List[str] = []

    provenance = False
    show_help = False
    notice: Optional[str] = None
    quit_early = False
    index = 0

    while index < len(queue):
        proposal_id = int(queue[index]["id"])
        # Re-read the ledger rather than trusting the snapshot the session opened with:
        # the queue is shared with the subcommands, and the ledger is the truth.
        row = get_proposal(db, proposal_id) or queue[index]
        plan, plan_error = _plan_for(db, proposal_id, templates_dir)

        if clear:
            console.clear()
        render_candidate(
            console,
            row,
            plan,
            plan_error,
            index,
            len(queue),
            view,
            provenance,
            get_evidence(db, proposal_id),
            notice=notice,
            show_help=show_help,
        )
        notice = None
        show_help = False

        key = (key_reader() or "").strip().lower()[:1]

        if key in ("", KEY_QUIT):
            quit_early = True
            break

        if key == KEY_VIEW:
            view = toggle_view(view)
            continue
        if key == KEY_PROVENANCE:
            provenance = not provenance
            continue
        if key == KEY_HELP:
            show_help = True
            continue

        if key == KEY_SKIP:
            skipped.append(proposal_id)
            index += 1
            provenance = False
            continue

        if key == KEY_DISCARD:
            # Exactly `learn reject <id>`: a judgment that is remembered.
            reject_proposal(db, proposal_id)
            rejected.append(proposal_id)
            index += 1
            provenance = False
            continue

        if key == KEY_ACCEPT:
            if plan is None:
                notice = f"[bold red]Cannot apply:[/bold red] {plan_error}"
                errors.append(str(plan_error))
                continue
            try:
                apply_plan(db, plan, templates_dir)
            except MetaProjectError as exc:
                # A refused write leaves the candidate pending and the session running.
                notice = f"[bold red]Apply failed:[/bold red] {exc}"
                errors.append(str(exc))
                continue
            applied.append(proposal_id)
            index += 1
            provenance = False
            continue

        if key == KEY_EDIT:
            # Exactly `learn edit <id>`: store the operator's text, then apply it in
            # preference to the model's. Aborting stays on the candidate (§5.4.10).
            text = editor(proposal_body(row))
            if text is None:
                notice = (
                    "[yellow]Edit aborted (no $EDITOR, a non-zero exit, or no change "
                    "saved). The proposal stays pending.[/yellow]"
                )
                continue
            set_edited_body(db, proposal_id, text)
            edit_plan, edit_error = _plan_for(db, proposal_id, templates_dir, edited_body=text)
            if edit_plan is None:
                notice = f"[bold red]Cannot apply:[/bold red] {edit_error}"
                errors.append(str(edit_error))
                continue
            try:
                apply_plan(db, edit_plan, templates_dir, edited_body=text)
            except MetaProjectError as exc:
                notice = f"[bold red]Apply failed:[/bold red] {exc}"
                errors.append(str(exc))
                continue
            edited.append(proposal_id)
            applied.append(proposal_id)
            index += 1
            provenance = False
            continue

        notice = f"[dim]Unrecognized key {key!r}. Press ? for help.[/dim]"

    remaining = tuple(int(item["id"]) for item in queue[index:]) if quit_early else ()
    return SessionResult(
        applied=tuple(applied),
        rejected=tuple(rejected),
        skipped=tuple(skipped),
        edited=tuple(edited),
        remaining=remaining,
        quit_early=quit_early,
        errors=tuple(errors),
    )
