"""Tests for the universe TUI: screen-content builders and the degradation gate."""

from pathlib import Path

from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.gitinfo import WorktreeInfo
from metaproject.universe_tui import (
    format_age,
    list_row,
    score_line,
    sdlc_badges,
    verdict_label,
    worktree_row,
)
from tests.test_universe import write_project_home


def _project(**overrides) -> dict:
    record = {
        "name": "proj",
        "path": "/tmp/Projects/proj",
        "relative_path": "proj",
        "title": "Proj",
        "classification": "Active Now",
        "last_modified": "2026-09-15T10:00:00+00:00",
        "is_git": 1,
        "git_branch": "main",
        "has_agents_md": 1,
        "has_intent_md": 1,
        "has_state_md": 1,
        "has_handoff_md": 0,
    }
    record.update(overrides)
    return record


def _worktree(**overrides) -> WorktreeInfo:
    fields = dict(
        path="/tmp/Projects/proj/.claude/worktrees/feat",
        branch="feat/x",
        head_age_days=2.0,
        behind_count=0,
        uncommitted_count=2,
        stale=False,
        flag=True,
        ahead_count=3,
        base_branch="main",
    )
    fields.update(overrides)
    return WorktreeInfo(**fields)


class TestScreenContent:
    """Pure builders — no Textual app is launched (spec NFR)."""

    def test_list_row_reads_db_record_only(self) -> None:
        row = list_row(_project())
        assert row == ("Active Now", "Proj", "proj", "2026-09-15", "main", "AIS")

    def test_list_row_title_fallback_and_no_git(self) -> None:
        row = list_row(_project(title="", is_git=0, git_branch=None))
        assert row[1] == "proj"
        assert row[4] == "no"

    def test_sdlc_badges_dash_when_none(self) -> None:
        project = _project()
        for flag, _letter in (
            ("has_agents_md", "A"),
            ("has_intent_md", "I"),
            ("has_state_md", "S"),
            ("has_handoff_md", "H"),
        ):
            project[flag] = 0
        assert sdlc_badges(project) == "-"

    def test_verdict_label_never_folds_the_flag_in(self) -> None:
        # Active verdict with a dirty tree: two separate signals (AC-6)
        assert verdict_label(_worktree()) == "ACTIVE"
        assert verdict_label(_worktree(stale=True)) == "STALE"
        assert verdict_label(_worktree(neutral=True)) == "ACTIVE · neutral"

    def test_score_line_shows_its_work(self) -> None:
        # age 2d → 0, behind 0 → 0
        assert score_line(_worktree()) == "score 0 (age 0, behind 0)"
        # age 40d → 2, behind 6 → 2
        assert score_line(_worktree(head_age_days=40.0, behind_count=6)) == (
            "score 4 (age 2, behind 2)"
        )
        assert "undeterminable" in score_line(_worktree(neutral=True))

    def test_worktree_row(self) -> None:
        row = worktree_row(_worktree())
        assert row == ("feat/x", "2d", "0", "2 file(s) ⚠", "ACTIVE")
        # Neutral worktrees hide the behind count rather than inventing one
        neutral = worktree_row(_worktree(branch=None, neutral=True))
        assert neutral[0] == "detached"
        assert neutral[2] == "?"

    def test_format_age(self) -> None:
        assert format_age(None) == "?"
        assert format_age(0.2) == "<1d"
        assert format_age(38.4) == "38d"


class TestDegradationGate:
    """All four triggers print the static table and exit 0 (R-UNV-5, AC-10)."""

    def _catalog(self, tmp_path: Path) -> Path:
        home = tmp_path / "Projects"
        home.mkdir()
        proj = home / "proj"
        proj.mkdir()
        (proj / ".git").mkdir()
        (proj / "README.md").write_text("# Gated Project\n", encoding="utf-8")
        write_project_home(home)
        return tmp_path / "universe.db"

    def test_no_tui_flag_prints_table(self, runner: CliRunner, tmp_path: Path) -> None:
        db_path = self._catalog(tmp_path)
        result = runner.invoke(app, ["universe", "--db", str(db_path), "--no-tui"])
        assert result.exit_code == 0
        assert "Project Universe Catalog" in result.output

    def test_piped_stdout_prints_table(self, runner: CliRunner, tmp_path: Path) -> None:
        # CliRunner's stdout is not a TTY: the default invocation degrades
        db_path = self._catalog(tmp_path)
        result = runner.invoke(app, ["universe", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Project Universe Catalog" in result.output

    def test_term_dumb_prints_table(self, runner: CliRunner, tmp_path: Path) -> None:
        db_path = self._catalog(tmp_path)
        result = runner.invoke(app, ["universe", "--db", str(db_path)], env={"TERM": "dumb"})
        assert result.exit_code == 0
        assert "Project Universe Catalog" in result.output

    def test_agent_session_prints_table(self, runner: CliRunner, tmp_path: Path) -> None:
        db_path = self._catalog(tmp_path)
        result = runner.invoke(
            app, ["universe", "--db", str(db_path)], env={"METAPROJECT_AGENT": "claude"}
        )
        assert result.exit_code == 0
        assert "Project Universe Catalog" in result.output

    def test_display_flags_keep_text_interface(self, runner: CliRunner, tmp_path: Path) -> None:
        db_path = self._catalog(tmp_path)
        for extra in (["--list"], ["--format", "json"], ["--quiet"]):
            result = runner.invoke(app, ["universe", "--db", str(db_path), *extra])
            assert result.exit_code == 0

    def test_tui_opens_when_enabled_without_scanning(
        self, runner: CliRunner, tmp_path: Path, monkeypatch
    ) -> None:
        home = tmp_path / "Projects"
        home.mkdir()
        write_project_home(home)
        db_path = tmp_path / "universe.db"

        calls: dict = {}

        def fake_run_tui(db_path, project_home, classification_filter=None, depth=4):
            calls["project_home"] = str(project_home)
            calls["filter"] = classification_filter

        monkeypatch.setattr("metaproject.learn.tui.tui_enabled", lambda **kwargs: True)
        monkeypatch.setattr("metaproject.universe_tui.run_tui", fake_run_tui)

        result = runner.invoke(app, ["universe", "--db", str(db_path), "--filter", "Active Now"])
        assert result.exit_code == 0
        assert calls["project_home"] == str(home.resolve())
        assert calls["filter"] == "Active Now"
        # No scan on open: the TUI branch returns before the DB is touched (AC-8)
        assert not db_path.exists()
        assert "Project Universe Catalog" not in result.output
