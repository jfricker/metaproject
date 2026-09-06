"""Tests for template drift auditing, missing deliverable detection, and the review board."""

import inspect
import io
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Callable, List

import pytest
from rich.console import Console
from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.exceptions import MetaProjectError
from metaproject.review import (
    deploy_entry,
    ignore_project,
    is_ignored,
    load_ignored,
    review_project,
    review_workspace,
    unignore_project,
    update_entry,
)
from metaproject.review_tui import (
    COUNT_NONE,
    GLYPH_CLEAN,
    GLYPH_DRIFTED,
    GLYPH_INCOMPLETE,
    STATE_CLEAN,
    STATE_DRIFTED,
    STATE_INCOMPLETE,
    BoardResult,
    compliance_cell,
    count_cell,
    detail_entries,
    detail_table,
    parse_board_command,
    parse_detail_command,
    render_detail,
    review_table,
    run_board,
    run_detail,
)
from metaproject.scaffold import scaffold_project


@pytest.fixture
def quiet_console(tmp_path: Path) -> Console:
    """A console whose output goes nowhere, so board tests assert on state, not paint."""
    return Console(file=open(tmp_path / "console.log", "w", encoding="utf-8"), width=100)


@pytest.fixture
def recording_console() -> Console:
    """A console that keeps every frame it painted, for tests that assert on the screen."""
    return Console(file=io.StringIO(), width=100, record=True)


def scripted(commands: List[str]) -> Callable[[], str]:
    """A board/detail reader that replays a fixed command script."""
    pending = iter(commands)
    return lambda: next(pending, "q")


def one_drifted_project(root: Path, name: str = "one_drift") -> Path:
    """A scaffolded project with exactly one drifted file and nothing missing."""
    proj = root / name
    scaffold_project(project_name=name, output=proj, interactive=False, no_git=True)
    (proj / "AGENTS.md").write_text("# local rules\nNever use make!\n", encoding="utf-8")
    return proj


def make_drifting_project(root: Path, name: str = "drifting_proj") -> Path:
    """A project root with one custom governance file and most deliverables missing."""
    proj = root / name
    proj.mkdir()
    (proj / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    (proj / "AGENTS.md").write_text("# Custom rules\nNever use make!\n", encoding="utf-8")
    return proj


# ------------------------------------------------------------------------------ auditing


def test_review_compliant_project(tmp_path: Path) -> None:
    """Verify that a freshly scaffolded project reports 100% compliance."""
    proj = tmp_path / "compliant_proj"
    scaffold_project(
        project_name="compliant_proj",
        output=proj,
        interactive=False,
        no_git=True,
    )

    review = review_project(proj)
    assert review.is_compliant is True
    assert len(review.missing_files) == 0
    assert review.deployable == []


def test_review_scaffolded_project_reports_no_drift(tmp_path: Path) -> None:
    """A project straight out of `new` must not appear drifted from its own templates.

    Guards the "render before diffing" invariant: the templates carry `{ProjectTitle}`
    placeholders, and comparing raw template text to a rendered file makes every project
    look drifted.
    """
    proj = tmp_path / "fresh_proj"
    scaffold_project(project_name="fresh_proj", output=proj, interactive=False, no_git=True)

    review = review_project(proj)
    assert review.updatable == []
    assert review.diffs == {}


def test_review_missing_files_and_drift(tmp_path: Path) -> None:
    """Verify detection of missing deliverables and template content drift."""
    proj = make_drifting_project(tmp_path)

    review = review_project(proj)
    assert review.is_compliant is False
    assert "HANDOFF.md" in review.missing_files
    assert "STATE.md" in review.missing_files
    assert "CLAUDE.md" in review.missing_files
    assert ".gitignore" in review.missing_files
    assert "docs" in review.missing_files

    # AGENTS.md should report content drift, and be offered for Update rather than Deploy
    assert "AGENTS.md" in review.diffs
    assert "AGENTS.md" in review.updatable
    assert "AGENTS.md" not in review.deployable
    assert "STATE.md" in review.deployable


def test_review_workspace_and_cli(runner: CliRunner, tmp_path: Path) -> None:
    """Verify multi-project workspace review and CLI command output."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Project 1: valid scaffolded
    proj1 = workspace / "app_one"
    scaffold_project(
        project_name="app_one",
        output=proj1,
        interactive=False,
        no_git=True,
    )

    # Project 2: minimal git repo missing SDLC files
    proj2 = workspace / "app_two"
    proj2.mkdir()
    (proj2 / ".git").mkdir()
    (proj2 / "main.py").write_text("print('hello')", encoding="utf-8")

    results = review_workspace(workspace)
    assert len(results) == 2

    # CLI invocation with --all
    cli_result = runner.invoke(
        app,
        ["review", str(workspace), "--all"],
    )
    assert cli_result.exit_code == 0
    # app_one comes straight from `new`, so it is clean; app_two is missing everything.
    assert "CLEAN" in cli_result.output
    assert "INCOMPLETE" in cli_result.output
    assert "app_one" in cli_result.output
    assert "app_two" in cli_result.output


def test_review_all_descends_nested_subdirs_when_root_is_project(
    runner: CliRunner, tmp_path: Path
) -> None:
    """Verify that 'review --all' descends into subdirectories even when root is a project."""
    parent_repo = tmp_path / "ParentProject"
    parent_repo.mkdir()
    (parent_repo / ".git").mkdir()
    (parent_repo / "README.md").write_text("# Parent", encoding="utf-8")

    # Create nested subproject inside ParentProject
    nested_proj = parent_repo / "subproject"
    nested_proj.mkdir()
    (nested_proj / ".git").mkdir()
    (nested_proj / "README.md").write_text("# Nested Project", encoding="utf-8")

    results = review_workspace(parent_repo)
    project_names = [r.project_name for r in results]
    assert "ParentProject" in project_names
    assert "subproject" in project_names

    cli_result = runner.invoke(app, ["review", str(parent_repo), "--all"])
    assert cli_result.exit_code == 0
    assert "ParentProject" in cli_result.output
    assert "subproject" in cli_result.output


def test_review_depth_bounds_the_scan(tmp_path: Path) -> None:
    """`--depth` bounds descent: the default of 1 covers only immediate subdirectories."""
    workspace = tmp_path / "workspace"
    deep = workspace / "a" / "b" / "deep_proj"
    deep.mkdir(parents=True)
    (deep / "AGENTS.md").write_text("# deep\n", encoding="utf-8")
    shallow = workspace / "shallow_proj"
    shallow.mkdir()
    (shallow / "AGENTS.md").write_text("# shallow\n", encoding="utf-8")

    shallow_only = [r.project_name for r in review_workspace(workspace)]
    assert shallow_only == ["shallow_proj"]

    deeper = {r.project_name for r in review_workspace(workspace, max_depth=3)}
    assert deeper == {"shallow_proj", "deep_proj"}


# --------------------------------------------------------------------------- ignore list


def test_ignore_round_trip_excludes_project_from_review(tmp_path: Path) -> None:
    """An ignored project is recorded, dropped from reviews, and can be restored."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    proj = make_drifting_project(workspace, "ignorable")

    assert is_ignored(proj) is False
    assert ignore_project(proj) is True
    assert ignore_project(proj) is False  # already there
    assert str(proj.resolve()) in load_ignored()
    assert is_ignored(proj) is True

    assert review_workspace(workspace) == []
    included = review_workspace(workspace, include_ignored=True)
    assert [r.project_name for r in included] == ["ignorable"]
    assert included[0].is_ignored is True

    assert unignore_project(proj) is True
    assert unignore_project(proj) is False
    assert [r.project_name for r in review_workspace(workspace)] == ["ignorable"]


def test_ignore_cli_list_and_unignore(runner: CliRunner, tmp_path: Path) -> None:
    """`--list-ignored` prints the ledger and `--unignore` removes an entry."""
    proj = make_drifting_project(tmp_path, "cli_ignorable")
    ignore_project(proj)

    listed = runner.invoke(app, ["review", "--list-ignored"])
    assert listed.exit_code == 0
    assert "cli_ignorable" in listed.output

    removed = runner.invoke(app, ["review", str(proj), "--unignore"])
    assert removed.exit_code == 0
    assert load_ignored() == []

    empty = runner.invoke(app, ["review", "--list-ignored"])
    assert "No projects are being ignored" in empty.output


def test_malformed_ignore_ledger_is_treated_as_empty(tmp_path: Path, monkeypatch) -> None:
    """A ledger that cannot be parsed must not break a review."""
    from metaproject.review import get_ignore_file

    get_ignore_file().parent.mkdir(parents=True, exist_ok=True)
    get_ignore_file().write_text("{not json", encoding="utf-8")
    assert load_ignored() == []


# -------------------------------------------------------------------------- remediation


def test_deploy_entry_writes_missing_file_and_refuses_to_overwrite(tmp_path: Path) -> None:
    """Deploy creates a missing deliverable; it never clobbers one that exists."""
    proj = make_drifting_project(tmp_path)

    written = deploy_entry(proj, "STATE.md")
    assert (proj / "STATE.md").exists()
    assert written == [proj / "STATE.md"]

    with pytest.raises(MetaProjectError, match="already exists"):
        deploy_entry(proj, "STATE.md")


def test_deploy_entry_renders_a_directory_deliverable(tmp_path: Path) -> None:
    """`docs` is a template directory, so deploying it renders a tree, not a file."""
    proj = make_drifting_project(tmp_path)

    deploy_entry(proj, "docs")
    assert (proj / "docs").is_dir()


def test_update_entry_overwrites_drift_and_refuses_a_missing_file(tmp_path: Path) -> None:
    """Update rewrites a drifted file from its template; deploy handles missing ones."""
    proj = make_drifting_project(tmp_path)
    assert "AGENTS.md" in review_project(proj).updatable

    update_entry(proj, "AGENTS.md")
    assert "Never use make!" not in (proj / "AGENTS.md").read_text(encoding="utf-8")
    assert "AGENTS.md" not in review_project(proj).updatable

    with pytest.raises(MetaProjectError, match="does not exist"):
        update_entry(proj, "HANDOFF.md")


def test_deployed_files_do_not_immediately_report_as_drifted(tmp_path: Path) -> None:
    """A full deploy must reach a fixed point, not report the files it just wrote.

    The batch resolves template variables once up front; resolving per file lets an
    early write change how a later one renders (`review.resolve_variables`).
    """
    proj = make_drifting_project(tmp_path)
    review = review_project(proj)

    from metaproject.review import resolve_variables

    variables = resolve_variables(proj)
    for name in review.deployable:
        deploy_entry(proj, name, variables=variables)

    after = review_project(proj)
    assert after.missing_files == []
    # The two files that were already there stay drifted; deploy never touches them, and
    # nothing it wrote reports as drifted.
    assert set(after.updatable) == {"AGENTS.md", "README.md"}


# ------------------------------------------------------------------------- command input


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Verb-first is the grammar both key bars teach.
        ("u 1", (0, "u")),
        ("d 2", (1, "d")),
        ("i 3", (2, "i")),
        ("o 3", (2, "o")),
        ("u1", (0, "u")),
        # A bare row number still opens it; update is the default verb.
        ("2", (1, "u")),
        ("q", (None, "q")),
        # Help is its own answer: the board must not read `?` as an unparseable command.
        ("?", (None, "?")),
        # Empty input is its own answer: repaint, neither quit nor a complaint.
        ("", (None, "")),
        ("   ", (None, "")),
        # Out of range, and the coercions that used to run a verb against the wrong row.
        ("9", (None, None)),
        ("0", (None, None)),
        ("u 9", (None, None)),
        ("1 2", (None, None)),
        ("1x2u", (None, None)),
        ("1x", (None, None)),
        ("x 1", (None, None)),
        ("1uu", (None, None)),
        ("uu 1", (None, None)),
        ("uu", (None, None)),
        ("u", (None, None)),
        ("u 1 2", (None, None)),
        ("1 u 2", (None, None)),
    ],
)
def test_parse_board_command(raw: str, expected: tuple) -> None:
    """Row selection accepts `u 3` and a bare `3`; anything else is refused.

    Quit, empty and unparseable are three distinct returns so the loop can quit, repaint
    silently, or explain itself — never guess.
    """
    assert parse_board_command(raw, total=3) == expected


@pytest.mark.parametrize("verb", ["u", "d", "i", "o"])
def test_board_still_accepts_the_old_number_first_grammar(verb: str) -> None:
    """`3u` and `3 u` mean exactly what `u 3` means — muscle memory outlives a redesign."""
    expected = parse_board_command(f"{verb} 3", total=3)
    assert expected == (2, verb)
    assert parse_board_command(f"3{verb}", total=3) == expected
    assert parse_board_command(f"3 {verb}", total=3) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("u", ("u", None)),
        ("u 2", ("u", "2")),
        ("v3", ("v", "3")),
        ("d all", ("d", "all")),
        ("b", ("b", None)),
        ("", ("", None)),
    ],
)
def test_parse_detail_command(raw: str, expected: tuple) -> None:
    """Detail commands are a verb plus an optional row number or `all`."""
    assert parse_detail_command(raw) == expected


# --------------------------------------------------------------------------- the board


def test_the_state_word_names_the_defect(tmp_path: Path) -> None:
    """CLEAN / DRIFTED / INCOMPLETE, and the worse of the two defects wins."""
    clean_dir = tmp_path / "clean_proj"
    scaffold_project(project_name="clean_proj", output=clean_dir, interactive=False, no_git=True)
    clean = review_project(clean_dir)
    assert clean.is_clean is True
    assert compliance_cell(clean) == STATE_CLEAN

    # Same project, one file edited: still compliant (nothing missing) but now drifted.
    (clean_dir / "AGENTS.md").write_text("# local rules\n", encoding="utf-8")
    drifted = review_project(clean_dir)
    assert drifted.is_compliant is True
    assert drifted.is_clean is False
    assert compliance_cell(drifted) == STATE_DRIFTED

    # Missing *and* drifted: the missing deliverable is the defect that has to be fixed
    # first, so it is the one the row is named for.
    both = review_project(make_drifting_project(tmp_path))
    assert both.missing_files and both.updatable
    assert compliance_cell(both) == STATE_INCOMPLETE


def test_a_result_derives_its_verdicts_rather_than_storing_them(tmp_path: Path) -> None:
    """Nothing a review concludes can disagree with what it observed, because none of it
    is stored: the verdicts are computed from `missing_files` and `diffs`, and the record
    itself refuses to be edited into a state where they would not be."""
    result = review_project(make_drifting_project(tmp_path))

    assert result.updatable == sorted(result.diffs)
    assert result.is_compliant is False and result.missing_files
    assert result.is_clean is False

    with pytest.raises(FrozenInstanceError):
        result.missing_files = []  # type: ignore[misc]


def test_board_columns_count_rather_than_list(tmp_path: Path) -> None:
    """Missing and Drifted are counts; zero is quiet, and no file name reaches the board."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    make_drifting_project(workspace)
    clean_dir = workspace / "clean_proj"
    scaffold_project(project_name="clean_proj", output=clean_dir, interactive=False, no_git=True)

    results = review_workspace(workspace)
    assert count_cell(0, "red") == COUNT_NONE
    assert count_cell(6, "red") == "[red]6[/red]"

    console = Console(width=120, record=True)
    console.print(review_table(results))
    rendered = console.export_text()

    assert "Missing" in rendered and "Drifted" in rendered
    # The counts stand in for the names, which live on the detail screen.
    assert "HANDOFF.md" not in rendered
    assert "Actions" not in rendered
    assert "6" in rendered


def test_board_shows_a_long_project_name_in_full(tmp_path: Path) -> None:
    """The width the Actions column used to eat is what truncated project names."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    name = "a_deliberately_long_project_name_here"
    make_drifting_project(workspace, name)

    console = Console(width=120, record=True)
    console.print(review_table(review_workspace(workspace)))
    assert name in console.export_text()


def test_the_header_leads_with_the_score_and_the_scan_context(tmp_path: Path) -> None:
    """The board opens with the aggregate and what was audited, not a bare row count."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    scaffold_project(
        project_name="clean_proj",
        output=workspace / "clean_proj",
        interactive=False,
        no_git=True,
    )
    one_drifted_project(workspace, "drifted_proj")
    make_drifting_project(workspace, "incomplete_proj")

    results = review_workspace(workspace)
    templates = Path(results[0].templates_dir)

    # Wide enough that the context line is not the ellipsis it becomes on a real terminal.
    console = Console(width=400, record=True)
    console.print(
        review_table(results, scan_root=workspace, templates_dir=templates, ignored_count=2)
    )
    rendered = console.export_text()

    assert "3 projects" in rendered
    assert f"{GLYPH_CLEAN} CLEAN 1" in rendered
    assert f"{GLYPH_DRIFTED} DRIFTED 1" in rendered
    assert f"{GLYPH_INCOMPLETE} INCOMPLETE 1" in rendered
    assert "2 on the ignore list" in rendered
    assert str(workspace) in rendered
    assert str(templates) in rendered


def test_the_board_renders_without_any_scan_context(tmp_path: Path) -> None:
    """A caller that knows none of the context still gets a board, one line shorter."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    make_drifting_project(workspace)

    console = Console(width=120, record=True)
    console.print(review_table(review_workspace(workspace)))
    rendered = console.export_text()

    assert "1 projects" in rendered
    assert "on the ignore list" not in rendered


def test_state_is_legible_without_colour(tmp_path: Path) -> None:
    """Colour is an accent, never the signal: the glyph has to survive `NO_COLOR`."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    make_drifting_project(workspace, "incomplete_proj")
    one_drifted_project(workspace, "drifted_proj")

    console = Console(width=120, record=True, no_color=True, force_terminal=True)
    console.print(review_table(review_workspace(workspace)))
    rendered = console.export_text(styles=False)

    assert f"{GLYPH_INCOMPLETE} INCOMPLETE" in rendered
    assert f"{GLYPH_DRIFTED} DRIFTED" in rendered
    # And the same glyphs name the per-file states on the detail screen.
    console.print(detail_table(review_project(workspace / "drifted_proj")))
    assert f"{GLYPH_DRIFTED} drifted" in console.export_text(styles=False)


def test_ok_dismisses_a_row_without_recording_anything(
    tmp_path: Path, quiet_console: Console
) -> None:
    """OK drops the row for this session only; the project is audited again next review."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    proj = workspace / "clean_proj"
    scaffold_project(project_name="clean_proj", output=proj, interactive=False, no_git=True)

    outcome = run_board(
        review_workspace(workspace),
        console=quiet_console,
        reader=scripted(["o 1"]),
        clear=False,
    )

    assert outcome.dismissed == [str(proj)]
    assert outcome.ignored == []
    assert outcome.actioned == 0
    assert is_ignored(proj) is False
    # The decisive difference from Ignore: it comes straight back on the next review.
    assert [r.project_name for r in review_workspace(workspace)] == ["clean_proj"]


def test_ok_from_the_detail_screen(tmp_path: Path, quiet_console: Console) -> None:
    """`o` on the detail screen is the same session-local dismissal as `o <n>`."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    proj = make_drifting_project(workspace, "dismiss_me")

    outcome = run_board(
        review_workspace(workspace),
        console=quiet_console,
        reader=scripted(["u 1", "o"]),
        clear=False,
    )

    assert outcome.dismissed == [str(proj)]
    assert is_ignored(proj) is False
    assert outcome.quit_early is False


def test_detail_entries_list_missing_then_drifted(tmp_path: Path) -> None:
    """The detail screen numbers missing files first, then drifted ones."""
    result = review_project(make_drifting_project(tmp_path))
    entries = detail_entries(result)
    assert entries[: len(result.missing_files)] == result.missing_files
    assert entries[len(result.missing_files) :] == result.updatable


def test_a_viewed_diff_stays_pinned_until_it_is_dismissed(
    tmp_path: Path, recording_console: Console
) -> None:
    """The evidence must outlive the frame that produced it.

    A diff that vanished on the next repaint disappeared at exactly the moment the
    operator typed the `u <n>` it had just argued for.
    """
    proj = one_drifted_project(tmp_path)
    marker = "--- templates/AGENTS.md"

    run_detail(
        recording_console,
        review_project(proj),
        None,
        BoardResult(),
        reader=scripted(["v 1", "", "b"]),
        clear=False,
    )
    # Painted for the frame that asked for it and for the repaint after the next command.
    assert recording_console.export_text().count(marker) == 2


def test_c_closes_the_pinned_diff(tmp_path: Path, recording_console: Console) -> None:
    """Pinning is only tolerable with a way out, so `c` puts the screen back."""
    proj = one_drifted_project(tmp_path)

    run_detail(
        recording_console,
        review_project(proj),
        None,
        BoardResult(),
        reader=scripted(["v 1", "c", "b"]),
        clear=False,
    )

    assert recording_console.export_text().count("--- templates/AGENTS.md") == 1


def test_bare_v_shows_the_only_drifted_file(tmp_path: Path, recording_console: Console) -> None:
    """One drifted file is not an ambiguous request; asking for a row number scolds nobody."""
    proj = one_drifted_project(tmp_path)

    run_detail(
        recording_console,
        review_project(proj),
        None,
        BoardResult(),
        reader=scripted(["v", "b"]),
        clear=False,
    )
    rendered = recording_console.export_text()

    assert "--- templates/AGENTS.md" in rendered
    assert "Name a row" not in rendered


def test_bare_v_still_asks_which_when_several_files_have_drifted(
    tmp_path: Path, recording_console: Console
) -> None:
    """With more than one candidate there is nothing to guess, so it asks."""
    proj = make_drifting_project(tmp_path)
    assert len(review_project(proj).updatable) > 1

    run_detail(
        recording_console,
        review_project(proj),
        None,
        BoardResult(),
        reader=scripted(["v", "b"]),
        clear=False,
    )
    rendered = recording_console.export_text()

    assert "Name a row" in rendered
    assert "--- templates/" not in rendered


def test_the_board_explains_itself(tmp_path: Path, recording_console: Console) -> None:
    """`?` is advertised on both key bars, so the board has to answer it."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    make_drifting_project(workspace)

    run_board(
        review_workspace(workspace),
        console=recording_console,
        reader=scripted(["?", "q"]),
        clear=False,
    )
    rendered = recording_console.export_text()

    assert "not reviewed again until --unignore" in rendered
    # Both accepted grammars are documented where the operator asks for help.
    assert "number first" in rendered
    assert "? help" in rendered


def test_the_detail_screen_has_no_focus(tmp_path: Path) -> None:
    """`d 1` and `u 1` open the same screen: a focus that dimmed a column bought nothing."""
    for func in (run_detail, render_detail, detail_table):
        assert "focus" not in inspect.signature(func).parameters


def test_board_deploy_action_writes_missing_files(tmp_path: Path, quiet_console: Console) -> None:
    """`d 1` opens the detail screen, a confirmed `d all` deploys everything missing."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    proj = make_drifting_project(workspace)

    outcome = run_board(
        review_workspace(workspace),
        console=quiet_console,
        reader=scripted(["d 1", "d all", "b", "q"]),
        confirm=lambda question: True,
        clear=False,
    )

    assert outcome.errors == []
    assert {name for _, name in outcome.deployed} == {
        "intent.md",
        "STATE.md",
        "HANDOFF.md",
        "CLAUDE.md",
        ".gitignore",
        "docs",
    }
    assert (proj / "HANDOFF.md").exists()
    assert review_project(proj).missing_files == []


def test_board_update_action_rewrites_one_drifted_file(
    tmp_path: Path, quiet_console: Console
) -> None:
    """`u 1` then `u 7` updates exactly the numbered drifted file."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    proj = make_drifting_project(workspace)
    result = review_project(proj)
    row = detail_entries(result).index("AGENTS.md") + 1

    outcome = run_board(
        review_workspace(workspace),
        console=quiet_console,
        reader=scripted(["u 1", f"u {row}", "b", "q"]),
        clear=False,
    )

    assert outcome.updated == [(str(proj), "AGENTS.md")]
    assert "Never use make!" not in (proj / "AGENTS.md").read_text(encoding="utf-8")


def test_board_ignore_action_drops_the_row_and_persists(
    tmp_path: Path, quiet_console: Console
) -> None:
    """`i 1` records the project and removes it from the board immediately."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    proj = make_drifting_project(workspace, "ignore_me")

    outcome = run_board(
        review_workspace(workspace),
        console=quiet_console,
        reader=scripted(["i 1"]),
        clear=False,
    )

    assert outcome.ignored == [str(proj)]
    assert is_ignored(proj) is True
    # The board emptied itself rather than waiting for a quit.
    assert outcome.quit_early is False


def test_board_loop_still_answers_the_old_number_first_grammar(
    tmp_path: Path, quiet_console: Console
) -> None:
    """`1i` reaches the same code path as `i 1` — the transition is silent, not documented."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    proj = make_drifting_project(workspace, "legacy_keys")

    outcome = run_board(
        review_workspace(workspace),
        console=quiet_console,
        reader=scripted(["1i"]),
        clear=False,
    )

    assert outcome.ignored == [str(proj)]
    assert outcome.quit_early is False


def test_board_ignore_from_the_detail_screen(tmp_path: Path, quiet_console: Console) -> None:
    """`i` on the detail screen is the same decision as `i` on the board."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    proj = make_drifting_project(workspace, "detail_ignore")

    outcome = run_board(
        review_workspace(workspace),
        console=quiet_console,
        reader=scripted(["u 1", "i"]),
        clear=False,
    )

    assert outcome.ignored == [str(proj)]
    assert is_ignored(proj) is True


def test_board_reports_a_refused_write_without_ending_the_session(
    tmp_path: Path, quiet_console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed deploy is recorded and the loop keeps running, as in the learn reviewer."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    make_drifting_project(workspace)

    def boom(*args, **kwargs):
        raise MetaProjectError("template store unreadable")

    monkeypatch.setattr("metaproject.review_tui.deploy_entry", boom)

    outcome = run_board(
        review_workspace(workspace),
        console=quiet_console,
        reader=scripted(["d 1", "d all", "b", "q"]),
        confirm=lambda question: True,
        clear=False,
    )

    assert outcome.deployed == []
    assert any("template store unreadable" in problem for problem in outcome.errors)
    assert outcome.quit_early is True


def test_enter_repaints_instead_of_quitting(tmp_path: Path, quiet_console: Console) -> None:
    """A stray Enter on either screen repaints; only a literal `q` ends the session."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    make_drifting_project(workspace)

    outcome = run_board(
        review_workspace(workspace),
        console=quiet_console,
        reader=scripted(["", "u 1", "", "b", "", "q"]),
        clear=False,
    )

    assert outcome.actioned == 0
    assert outcome.errors == []
    assert outcome.quit_early is True


def test_bare_update_refuses_to_write_anything(tmp_path: Path, quiet_console: Console) -> None:
    """`u` with no argument is a question, not a licence to overwrite every drifted file."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    proj = make_drifting_project(workspace)
    before = (proj / "AGENTS.md").read_text(encoding="utf-8")

    def refuse(question: str) -> bool:
        raise AssertionError(f"bare u must not reach a confirmation: {question}")

    outcome = run_board(
        review_workspace(workspace),
        console=quiet_console,
        reader=scripted(["u 1", "u", "d", "b", "q"]),
        confirm=refuse,
        clear=False,
    )

    assert outcome.updated == []
    assert outcome.deployed == []
    assert (proj / "AGENTS.md").read_text(encoding="utf-8") == before
    assert not (proj / "HANDOFF.md").exists()


def test_update_all_is_gated_on_a_typed_confirmation(
    tmp_path: Path, quiet_console: Console
) -> None:
    """`u all` writes only once the operator agrees to the overwrite it names."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    proj = make_drifting_project(workspace)
    before = (proj / "AGENTS.md").read_text(encoding="utf-8")
    asked: List[str] = []

    def decline(question: str) -> bool:
        asked.append(question)
        return False

    declined = run_board(
        review_workspace(workspace),
        console=quiet_console,
        reader=scripted(["u 1", "u all", "b", "q"]),
        confirm=decline,
        clear=False,
    )

    assert declined.updated == []
    assert (proj / "AGENTS.md").read_text(encoding="utf-8") == before
    # The question has to state the stakes: how many files, which project, and that the
    # operator's own content goes away.
    assert len(asked) == 1
    assert "drifting_proj" in asked[0]
    assert "2" in asked[0]
    assert "discarding local edits" in asked[0]

    accepted = run_board(
        review_workspace(workspace),
        console=quiet_console,
        reader=scripted(["u 1", "u all", "b", "q"]),
        confirm=lambda question: True,
        clear=False,
    )

    assert {name for _, name in accepted.updated} == {"AGENTS.md", "README.md"}
    assert "Never use make!" not in (proj / "AGENTS.md").read_text(encoding="utf-8")


def test_a_failed_re_audit_is_recorded_not_swallowed(
    tmp_path: Path, quiet_console: Console
) -> None:
    """A stale row is indistinguishable from a successful write, so the failure is logged."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    make_drifting_project(workspace)
    rows = review_workspace(workspace)

    calls = {"n": 0}

    def flaky(project_path: Path, templates_dir=None):
        calls["n"] += 1
        raise RuntimeError("template store vanished")

    outcome = run_board(
        rows,
        console=quiet_console,
        reader=scripted(["u 1", "b", "q"]),
        reviewer=flaky,
        clear=False,
    )

    assert calls["n"] == 1
    assert outcome.errors == ["drifting_proj: re-audit failed: template store vanished"]
    # The session survived it: the board came back and quit on its own terms.
    assert outcome.quit_early is True


def test_board_quits_without_acting(tmp_path: Path, quiet_console: Console) -> None:
    """`q` on the board leaves every project untouched."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    proj = make_drifting_project(workspace)

    outcome = run_board(
        review_workspace(workspace),
        console=quiet_console,
        reader=scripted(["q"]),
        clear=False,
    )

    assert outcome.actioned == 0
    assert outcome.quit_early is True
    assert not (proj / "HANDOFF.md").exists()


# ---------------------------------------------------------------------------------- CLI


def test_cli_shows_the_board_and_no_recommendations_panel(
    runner: CliRunner, tmp_path: Path
) -> None:
    """The board replaces the old Actionable Recommendations panel."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    make_drifting_project(workspace)

    result = runner.invoke(app, ["review", str(workspace), "--all"])
    assert result.exit_code == 0
    assert "Compliance" in result.output
    assert "Actionable Recommendations" not in result.output


def test_cli_no_tui_prints_the_board_and_exits(runner: CliRunner, tmp_path: Path) -> None:
    """`--no-tui` degrades to a printed board, so scripted use needs no terminal.

    Nothing on it advertises a verb: a board that cannot be typed at must not offer
    Update or Deploy as if it could.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    make_drifting_project(workspace, "scripted_proj")

    result = runner.invoke(app, ["review", str(workspace), "--all", "--no-tui"])
    assert result.exit_code == 0
    assert "scripted_proj" in result.output
    assert "INCOMPLETE" in result.output
    for verb in ("Update", "Deploy", "Ignore"):
        assert verb not in result.output


def test_cli_hides_ignored_projects_unless_asked(runner: CliRunner, tmp_path: Path) -> None:
    """An ignored project disappears from `--all` and returns under `--show-ignored`."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    proj = make_drifting_project(workspace, "hidden_proj")
    ignore_project(proj)

    hidden = runner.invoke(app, ["review", str(workspace), "--all"])
    assert "hidden_proj" not in hidden.output
    assert "No projects discovered" in hidden.output

    shown = runner.invoke(app, ["review", str(workspace), "--all", "--show-ignored"])
    assert "hidden_proj" in shown.output
