"""Acceptance TUI tests (spec.md §5.4.5), plan.md Phase 5.

The governing principle is plan.md §1.3.2 — "one queue, two interfaces". Every
keybinding assertion here is therefore an assertion about the **state transition**, and
the headline ones compare the TUI's transition against the equivalent subcommand's
transition on an identically-seeded proposal rather than trusting that both call the
same function.

**No test in this file invokes a model.** Any `claude` argv detonates; `git` is left
alone because the fixture builder and the commit path both need it.
"""

import io
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pytest
from rich.console import Console
from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.db import get_db
from metaproject.learn import tui
from metaproject.learn.store import ProposalDraft, get_proposal, upsert_proposal
from tests.fixtures.learn_workspace.build import build_workspace

C2_LINE = "- Run `make check` before every commit."
C2_PROJECTS = ("atlas", "kiln", "beacon")
SECTION = "## Testing instructions"


@pytest.fixture(autouse=True)
def no_model_ever(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any `claude` argv is a test failure; `git` is left alone."""
    real_run = subprocess.run

    def guarded_run(argv, *args, **kwargs):
        parts = argv if isinstance(argv, (list, tuple)) else [argv]
        if any("claude" in str(part) for part in parts):  # pragma: no cover
            raise AssertionError("a test tried to invoke `claude`; the model must be mocked")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded_run)


def ledger():
    """The ledger every interface writes to, resolved exactly as the CLI resolves it."""
    from metaproject.config import load_config

    return get_db(load_config().universe_db)


def seed(
    templates: Path,
    tag: str = "one",
    target_section: Optional[str] = SECTION,
    body: str = C2_LINE,
    score: float = 2.5,
) -> int:
    """Persist one pending proposal directly, bypassing the model."""
    return upsert_proposal(
        ledger(),
        ProposalDraft(
            content_hash=f"seeded-{tag}-{target_section}-{body}",
            target_file="AGENTS.md",
            kind="edit",
            title="Require a green check before every commit",
            rationale="Three projects state the same pre-commit convention.",
            proposed_body=body,
            evidence_count=3,
            evidence_score=score,
            template_path=str(templates / "AGENTS.template.md"),
            target_section=target_section,
        ),
    )


def keys(*sequence: str) -> Callable[[], str]:
    """A deterministic keystroke source; exhausting it quits, as EOF does."""
    pending = list(sequence)

    def reader() -> str:
        return pending.pop(0) if pending else "q"

    return reader


def console(width: int = 120) -> Console:
    """A `rich` console that renders into a buffer instead of a terminal."""
    return Console(file=io.StringIO(), width=width, height=40, force_terminal=False)


def git(cwd: Path, *args: str) -> str:
    """Run a git command in `cwd` and return its stdout."""
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)
    return res.stdout


def snapshot(root: Path) -> Dict[str, bytes]:
    """Byte-level snapshot of every non-git file under `root`."""
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.parts
    }


def rows_for(pid: int) -> List[Dict[str, object]]:
    """The one-proposal queue the TUI is handed."""
    return [get_proposal(ledger(), pid)]


def transition(pid: int) -> Dict[str, object]:
    """The part of a proposal row that a state transition is allowed to change."""
    row = get_proposal(ledger(), pid)
    if row is None:
        return {"status": None}
    return {
        "status": row["status"],
        "edited_body": row["edited_body"],
        "committed": bool(row["applied_commit"]),
        "rejected_score": row["rejected_score"],
    }


@pytest.fixture
def workspace(tmp_path: Path):
    """A git-backed template store plus the three C12 projects."""
    return build_workspace(tmp_path / "a", git_init_templates=True, only=list(C2_PROJECTS))


@pytest.fixture
def mirror(tmp_path: Path):
    """A second, identical template store, so two interfaces can be compared."""
    return build_workspace(tmp_path / "b", git_init_templates=True, only=list(C2_PROJECTS))


# ------------------------------------------------- keybinding / subcommand equivalence


def test_accept_key_matches_the_learn_apply_subcommand(
    runner: CliRunner, workspace, mirror
) -> None:
    """Gate: `a` produces the same state transition as `learn apply <id>`."""
    tui_id = seed(workspace.templates, tag="tui")
    cli_id = seed(mirror.templates, tag="cli")

    result = tui.run_review(
        ledger(),
        rows_for(tui_id),
        workspace.templates,
        console=console(),
        key_reader=keys("a"),
    )
    res = runner.invoke(
        app, ["learn", "apply", str(cli_id), "--templates", str(mirror.templates), "--yes"]
    )
    assert res.exit_code == 0, res.output

    assert result.applied == (tui_id,)
    assert transition(tui_id) == transition(cli_id)
    assert (workspace.templates / "AGENTS.template.md").read_text(encoding="utf-8") == (
        mirror.templates / "AGENTS.template.md"
    ).read_text(encoding="utf-8")
    assert f"#{tui_id}" in git(workspace.templates, "log", "-1", "--format=%B")


def test_discard_key_matches_the_learn_reject_subcommand(
    runner: CliRunner, workspace, mirror
) -> None:
    """Gate: `d` produces the same state transition as `learn reject <id>`."""
    tui_id = seed(workspace.templates, tag="tui")
    cli_id = seed(mirror.templates, tag="cli")

    result = tui.run_review(
        ledger(),
        rows_for(tui_id),
        workspace.templates,
        console=console(),
        key_reader=keys("d"),
    )
    assert runner.invoke(app, ["learn", "reject", str(cli_id)]).exit_code == 0

    assert result.rejected == (tui_id,)
    assert transition(tui_id) == transition(cli_id)
    assert transition(tui_id)["status"] == "rejected"
    # Discard is a judgment that is remembered: nothing was written to the template.
    assert git(workspace.templates, "status", "--porcelain").strip() == ""


def test_edit_key_matches_the_learn_edit_subcommand(
    runner: CliRunner, workspace, mirror, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gate: `e` produces the same state transition as `learn edit <id>`."""
    from metaproject import cli

    edited = "- Run `make audit` first."
    tui_id = seed(workspace.templates, tag="tui")
    cli_id = seed(mirror.templates, tag="cli")

    result = tui.run_review(
        ledger(),
        rows_for(tui_id),
        workspace.templates,
        console=console(),
        key_reader=keys("e"),
        editor=lambda _text: edited,
    )
    monkeypatch.setattr(cli, "open_in_editor", lambda _text: edited)
    res = runner.invoke(
        app, ["learn", "edit", str(cli_id), "--templates", str(mirror.templates), "--yes"]
    )
    assert res.exit_code == 0, res.output

    assert result.edited == (tui_id,)
    assert transition(tui_id) == transition(cli_id)
    assert transition(tui_id)["edited_body"] == edited
    assert edited in (workspace.templates / "AGENTS.template.md").read_text(encoding="utf-8")
    assert C2_LINE not in (workspace.templates / "AGENTS.template.md").read_text(encoding="utf-8")


def test_skip_leaves_the_proposal_pending(workspace) -> None:
    """Gate: Skip is deferral, not judgment — no status change, no write."""
    pid = seed(workspace.templates)
    before = snapshot(workspace.templates)

    result = tui.run_review(
        ledger(), rows_for(pid), workspace.templates, console=console(), key_reader=keys("s")
    )

    assert result.skipped == (pid,)
    assert transition(pid)["status"] == "pending"
    assert transition(pid)["rejected_score"] is None
    assert snapshot(workspace.templates) == before


def test_discard_marks_rejected_and_skip_does_not(workspace) -> None:
    """The Discard/Skip distinction, asserted side by side (spec.md §5.4.5)."""
    skipped_id = seed(workspace.templates, tag="skipped", score=3.0)
    discarded_id = seed(workspace.templates, tag="discarded", score=2.0)

    result = tui.run_review(
        ledger(),
        [get_proposal(ledger(), skipped_id), get_proposal(ledger(), discarded_id)],
        workspace.templates,
        console=console(),
        key_reader=keys("s", "d"),
    )

    assert result.skipped == (skipped_id,)
    assert result.rejected == (discarded_id,)
    assert get_proposal(ledger(), skipped_id)["status"] == "pending"
    assert get_proposal(ledger(), discarded_id)["status"] == "rejected"


# ---------------------------------------------------------------------------- quitting


def test_quitting_mid_session_persists_everything_already_actioned(workspace) -> None:
    """Gate: quit loses nothing; the remainder simply stays pending."""
    first = seed(workspace.templates, tag="first", score=9.0)
    second = seed(
        workspace.templates,
        tag="second",
        target_section="## Process",
        body="Tag before release.",
        score=8.0,
    )
    third = seed(workspace.templates, tag="third", body="Keep the changelog current.", score=7.0)

    result = tui.run_review(
        ledger(),
        [get_proposal(ledger(), pid) for pid in (first, second, third)],
        workspace.templates,
        console=console(),
        key_reader=keys("a", "d", "q"),
    )

    assert result.quit_early is True
    assert result.applied == (first,)
    assert result.rejected == (second,)
    assert result.remaining == (third,)
    assert get_proposal(ledger(), first)["status"] == "applied"
    assert get_proposal(ledger(), second)["status"] == "rejected"
    assert get_proposal(ledger(), third)["status"] == "pending"
    # The accept was committed before the quit, so it survives the session ending.
    assert git(workspace.templates, "status", "--porcelain").strip() == ""
    assert f"#{first}" in git(workspace.templates, "log", "-1", "--format=%B")


def test_an_exhausted_key_source_ends_the_session_like_quit(workspace) -> None:
    """EOF on the keystroke source is a quit, not a crash."""
    pid = seed(workspace.templates)
    result = tui.run_review(
        ledger(), rows_for(pid), workspace.templates, console=console(), key_reader=keys()
    )
    assert result.quit_early is True
    assert get_proposal(ledger(), pid)["status"] == "pending"


# --------------------------------------------------------------------------- the edit


def test_an_aborted_edit_keeps_the_candidate_pending_and_stays_in_the_tui(workspace) -> None:
    """spec.md §5.4.10: no `$EDITOR`, or no change — abort, stay, keep pending."""
    pid = seed(workspace.templates)
    before = snapshot(workspace.templates)

    result = tui.run_review(
        ledger(),
        rows_for(pid),
        workspace.templates,
        console=console(),
        key_reader=keys("e", "s"),
        editor=lambda _text: None,
    )

    # The `e` did not advance: the following `s` is what moved past the candidate.
    assert result.skipped == (pid,)
    assert result.applied == ()
    assert get_proposal(ledger(), pid)["status"] == "pending"
    assert snapshot(workspace.templates) == before


def test_open_in_editor_returns_none_when_no_editor_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one implementation both interfaces use (`cli.open_in_editor` delegates here)."""
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    assert tui.open_in_editor("body") is None


def test_the_cli_edit_command_delegates_to_the_tui_editor_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One implementation, two entry points — not two copies that can diverge."""
    from metaproject import cli

    monkeypatch.setattr(tui, "open_in_editor", lambda text, suffix=".md": f"edited:{text}")
    assert cli.open_in_editor("body") == "edited:body"


# ------------------------------------------------------------------------- view / keys


def test_a_narrow_terminal_falls_back_to_the_unified_view() -> None:
    """Gate: too narrow for side-by-side is a view change, not an error."""
    assert tui.effective_view(tui.VIEW_SIDE_BY_SIDE, tui.SIDE_BY_SIDE_MIN_WIDTH) == (
        tui.VIEW_SIDE_BY_SIDE
    )
    assert tui.effective_view(tui.VIEW_SIDE_BY_SIDE, tui.SIDE_BY_SIDE_MIN_WIDTH - 1) == (
        tui.VIEW_UNIFIED
    )


def test_a_narrow_console_never_renders_the_side_by_side_header(workspace) -> None:
    """The fallback is observable in what is painted, not only in a helper."""
    pid = seed(workspace.templates)
    wide = console(width=140)
    tui.run_review(ledger(), rows_for(pid), workspace.templates, console=wide, key_reader=keys("s"))
    assert "proposed" in wide.file.getvalue()

    narrow = console(width=60)
    tui.run_review(
        ledger(), rows_for(pid), workspace.templates, console=narrow, key_reader=keys("s")
    )
    assert "template (current)" not in narrow.file.getvalue()


def test_the_view_key_toggles_between_side_by_side_and_unified(workspace) -> None:
    """`u` is a view toggle and writes nothing."""
    pid = seed(workspace.templates)
    buffer = console(width=140)
    tui.run_review(
        ledger(), rows_for(pid), workspace.templates, console=buffer, key_reader=keys("u", "s")
    )
    text = buffer.file.getvalue()
    assert "template (current)" in text
    assert "@@" in text or "--- a/" in text
    assert get_proposal(ledger(), pid)["status"] == "pending"


def test_the_provenance_key_expands_absolute_contributing_paths(workspace) -> None:
    """`p` expands the full contributing-project list with absolute paths."""
    from metaproject.learn.store import EvidenceDraft, replace_evidence

    pid = seed(workspace.templates)
    project = str(workspace.project("atlas"))
    replace_evidence(
        ledger(), pid, [EvidenceDraft(project_path=project, excerpt=C2_LINE, weight=1.5)]
    )
    buffer = console(width=200)
    tui.run_review(
        ledger(), rows_for(pid), workspace.templates, console=buffer, key_reader=keys("p", "s")
    )
    assert project in buffer.file.getvalue()


def test_an_unknown_key_repaints_without_acting(workspace) -> None:
    """A stray keystroke must never be a silent accept."""
    pid = seed(workspace.templates)
    before = snapshot(workspace.templates)
    result = tui.run_review(
        ledger(), rows_for(pid), workspace.templates, console=console(), key_reader=keys("z", "s")
    )
    assert result.skipped == (pid,)
    assert snapshot(workspace.templates) == before


def test_accept_surfaces_the_fallback_reason_before_writing(workspace) -> None:
    """R7: an unresolvable section is a *reviewed* append, never a silent one."""
    pid = seed(workspace.templates, target_section="## Deployment")
    buffer = console(width=140)
    tui.run_review(
        ledger(), rows_for(pid), workspace.templates, console=buffer, key_reader=keys("a")
    )
    assert "Deployment" in buffer.file.getvalue()
    text = (workspace.templates / "AGENTS.template.md").read_text(encoding="utf-8")
    assert "## Deployment" not in text
    assert text.rstrip().endswith(C2_LINE)


def test_a_failed_accept_keeps_the_candidate_pending_and_stays(workspace) -> None:
    """A dirty template repository refuses the write without ending the session."""
    (workspace.templates / "AGENTS.template.md").write_text("dirtied\n", encoding="utf-8")
    pid = seed(workspace.templates)
    result = tui.run_review(
        ledger(), rows_for(pid), workspace.templates, console=console(), key_reader=keys("a", "s")
    )
    assert result.applied == ()
    assert result.skipped == (pid,)
    assert result.errors
    assert get_proposal(ledger(), pid)["status"] == "pending"


# ---------------------------------------------------------------------------- ordering


def test_candidates_loop_within_a_template_before_advancing(workspace) -> None:
    """spec.md §5.4.5 ordering: templates ranked by their best candidate."""
    rows = [
        {"id": 1, "target_file": "AGENTS.md", "evidence_score": 5.0, "evidence_count": 3},
        {"id": 2, "target_file": "README.md", "evidence_score": 9.0, "evidence_count": 4},
        {"id": 3, "target_file": "AGENTS.md", "evidence_score": 8.0, "evidence_count": 2},
        {"id": 4, "target_file": "README.md", "evidence_score": 1.0, "evidence_count": 1},
    ]
    assert [row["id"] for row in tui.order_for_review(rows)] == [2, 4, 3, 1]


# ------------------------------------------------------------------------ degradation


def test_tui_is_disabled_without_a_tty_by_no_tui_and_by_dumb_terminals() -> None:
    """Gate: the three degradation triggers of spec.md §5.4.5, at the helper."""

    class FakeTTY(io.StringIO):
        def isatty(self) -> bool:
            return True

    assert tui.tui_enabled(stream=FakeTTY(), env={"TERM": "xterm-256color"}) is True
    assert tui.tui_enabled(no_tui=True, stream=FakeTTY(), env={"TERM": "xterm"}) is False
    assert tui.tui_enabled(stream=FakeTTY(), env={"TERM": "dumb"}) is False
    assert tui.tui_enabled(stream=io.StringIO(), env={"TERM": "xterm"}) is False


def test_an_empty_queue_never_opens_the_tui() -> None:
    """Gate: nothing pending means nothing to review."""

    class FakeTTY(io.StringIO):
        def isatty(self) -> bool:
            return True

    assert tui.should_open_tui([], stream=FakeTTY(), env={"TERM": "xterm"}) is False
    assert tui.should_open_tui([{"id": 1}], stream=FakeTTY(), env={"TERM": "xterm"}) is True
