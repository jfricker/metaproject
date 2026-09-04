"""`metaproject learn` subcommand tests (spec.md §5.4.4), plan.md Phase 4.

The queue subcommands and the (Phase 5) TUI are two interfaces to one queue, so every
assertion here is about the state transition the subcommand performs, not about its
prose.

**No test in this file invokes a model.** `synth.run_claude` is replaced wherever a
scan is exercised, and any `claude` argv detonates.
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

import pytest
from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.db import get_db
from metaproject.learn import synth
from metaproject.learn.store import ProposalDraft, get_proposal, upsert_proposal
from tests.fixtures.learn_workspace.build import build_workspace

C2_LINE = "- Run `make check` before every commit."
C2_PROJECTS = ("atlas", "kiln", "beacon")

RESPONSE = json.dumps(
    {
        "proposals": [
            {
                "title": "Require a green check before every commit",
                "rationale": "Every contributing project states the same convention.",
                "proposed_body": C2_LINE,
                "target_section": "## Testing instructions",
                "source_lines": [C2_LINE],
            }
        ]
    }
)


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


def mock_model(monkeypatch: pytest.MonkeyPatch, response: str = RESPONSE) -> List[str]:
    """Stand in for the `claude` binary and record every prompt sent."""
    prompts: List[str] = []

    def fake_resolve(binary: Optional[str] = None) -> str:
        return "/usr/bin/claude"

    def fake_run(prompt: str, claude_path: str, model: Optional[str] = None, **kwargs) -> str:
        prompts.append(prompt)
        return response

    monkeypatch.setattr(synth, "resolve_claude", fake_resolve)
    monkeypatch.setattr(synth, "run_claude", fake_run)
    return prompts


def git(cwd: Path, *args: str) -> str:
    """Run a git command in `cwd` and return its stdout."""
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)
    return res.stdout


def scan_argv(workspace) -> List[str]:
    """The `learn scan` argv every scan test invokes."""
    return [
        "learn",
        "scan",
        str(workspace.projects),
        "--templates",
        str(workspace.templates),
        "--yes",
    ]


def snapshot(root: Path) -> Dict[str, bytes]:
    """Byte-level snapshot of every non-git file under `root`."""
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.parts
    }


@pytest.fixture
def workspace(tmp_path: Path):
    """A git-backed template store plus the three C12 projects."""
    return build_workspace(tmp_path, git_init_templates=True, only=list(C2_PROJECTS))


def ledger():
    """The ledger the CLI writes to, resolved exactly as the CLI resolves it."""
    from metaproject.config import load_config

    return get_db(load_config().universe_db)


def seed(
    templates: Path,
    target_section: Optional[str] = "## Testing instructions",
    body: str = C2_LINE,
) -> int:
    """Persist one pending proposal directly, bypassing the model."""
    db = ledger()
    return upsert_proposal(
        db,
        ProposalDraft(
            content_hash=f"seeded-{target_section}-{body}",
            target_file="AGENTS.md",
            kind="edit",
            title="Require a green check before every commit",
            rationale="Three projects state the same pre-commit convention.",
            proposed_body=body,
            evidence_count=3,
            evidence_score=2.5,
            template_path=str(templates / "AGENTS.template.md"),
            target_section=target_section,
        ),
    )


# ------------------------------------------------------------------------ learn scan


def test_scan_writes_proposals_and_leaves_the_template_store_clean(
    runner: CliRunner, workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scan invariant, asserted at the process boundary."""
    mock_model(monkeypatch)
    before = snapshot(workspace.templates)

    res = runner.invoke(
        app,
        scan_argv(workspace),
    )
    assert res.exit_code == 0, res.output
    assert snapshot(workspace.templates) == before
    assert git(workspace.templates, "status", "--porcelain").strip() == ""

    rows = ledger().conn.execute("SELECT COUNT(*) FROM learn_proposals").fetchone()
    assert rows[0] == 1


def test_missing_claude_exits_non_zero_having_written_nothing(
    runner: CliRunner, workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gate: no binary, non-zero exit, nothing written anywhere (spec.md §5.4.10)."""
    monkeypatch.setattr("shutil.which", lambda _name: None)
    before = snapshot(workspace.templates)

    res = runner.invoke(
        app,
        scan_argv(workspace),
    )
    assert res.exit_code != 0
    assert "claude" in res.output
    assert snapshot(workspace.templates) == before

    count = ledger().conn.execute("SELECT COUNT(*) FROM learn_proposals").fetchone()[0]
    assert count == 0


def test_scan_since_narrows_the_projects_scanned(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--since` limits a run to recently-changed projects (R5)."""
    ws = build_workspace(tmp_path, git_init_templates=True, only=["atlas", "relic"])
    prompts = mock_model(monkeypatch)

    res = runner.invoke(
        app,
        [
            "learn",
            "scan",
            str(ws.projects),
            "--templates",
            str(ws.templates),
            "--since",
            "30",
            "--yes",
        ],
    )
    assert res.exit_code == 0, res.output
    assert prompts, "the scan should still have run"
    assert "relic" not in "".join(prompts)


# ------------------------------------------------------------------------ learn list


def test_list_on_an_empty_queue_exits_zero(runner: CliRunner) -> None:
    """No proposals is a clean report, not an error (spec.md §5.4.10)."""
    res = runner.invoke(app, ["learn", "list"])
    assert res.exit_code == 0


def test_list_shows_a_pending_proposal_and_filters_by_status(runner: CliRunner, workspace) -> None:
    """The table is the fallback interface for scripting and CI."""
    pid = seed(workspace.templates)
    res = runner.invoke(app, ["learn", "list"])
    assert res.exit_code == 0
    assert str(pid) in res.output
    assert "AGENTS.md" in res.output

    rejected = runner.invoke(app, ["learn", "list", "--status", "rejected"])
    assert rejected.exit_code == 0
    assert "AGENTS.md" not in rejected.output


# ------------------------------------------------------------------------ learn show


def test_show_prints_rationale_and_contributing_paths(runner: CliRunner, workspace) -> None:
    """`show` is the provenance view (spec.md §5.4.4)."""
    from metaproject.learn.store import EvidenceDraft, replace_evidence

    pid = seed(workspace.templates)
    replace_evidence(
        ledger(),
        pid,
        [EvidenceDraft(project_path=str(workspace.project("atlas")), excerpt=C2_LINE, weight=1.5)],
    )
    res = runner.invoke(app, ["learn", "show", str(pid)])
    assert res.exit_code == 0
    assert "pre-commit convention" in res.output
    assert str(workspace.project("atlas")) in res.output


def test_show_on_an_unknown_id_exits_non_zero(runner: CliRunner) -> None:
    """An id that is not in the ledger is an error, not an empty panel."""
    res = runner.invoke(app, ["learn", "show", "4242"])
    assert res.exit_code != 0


# ----------------------------------------------------------------------- learn apply


def test_apply_writes_the_template_and_commits(runner: CliRunner, workspace) -> None:
    """The `a` keybinding's equivalent subcommand (spec.md §5.4.5)."""
    pid = seed(workspace.templates)
    res = runner.invoke(
        app,
        ["learn", "apply", str(pid), "--templates", str(workspace.templates), "--yes"],
    )
    assert res.exit_code == 0, res.output
    text = (workspace.templates / "AGENTS.template.md").read_text(encoding="utf-8")
    lines = text.split("\n")
    assert lines.index("## Testing instructions") < lines.index(C2_LINE) < lines.index("## Process")
    assert f"#{pid}" in git(workspace.templates, "log", "-1", "--format=%B")
    assert get_proposal(ledger(), pid)["status"] == "applied"


def test_apply_refuses_on_a_dirty_template_repository(runner: CliRunner, workspace) -> None:
    """Gate: refuse and explain (spec.md §5.4.10)."""
    (workspace.templates / "AGENTS.template.md").write_text("dirtied\n", encoding="utf-8")
    pid = seed(workspace.templates)
    res = runner.invoke(
        app,
        ["learn", "apply", str(pid), "--templates", str(workspace.templates), "--yes"],
    )
    assert res.exit_code != 0
    assert "dirt" in res.output.lower() or "uncommitted" in res.output.lower()
    assert get_proposal(ledger(), pid)["status"] == "pending"


def test_apply_declined_at_the_prompt_writes_nothing(runner: CliRunner, workspace) -> None:
    """Confirmation is required; declining leaves the candidate pending."""
    before = snapshot(workspace.templates)
    pid = seed(workspace.templates)
    res = runner.invoke(
        app,
        ["learn", "apply", str(pid), "--templates", str(workspace.templates)],
        input="n\n",
    )
    assert res.exit_code == 0
    assert snapshot(workspace.templates) == before
    assert get_proposal(ledger(), pid)["status"] == "pending"


def test_apply_warns_before_an_unresolvable_section_falls_back(
    runner: CliRunner, workspace
) -> None:
    """R7/C21: the operator is told the heading does not exist before any write."""
    pid = seed(workspace.templates, target_section="## Deployment")
    res = runner.invoke(
        app,
        ["learn", "apply", str(pid), "--templates", str(workspace.templates), "--yes"],
    )
    assert res.exit_code == 0, res.output
    assert "Deployment" in res.output
    text = (workspace.templates / "AGENTS.template.md").read_text(encoding="utf-8")
    assert "## Deployment" not in text
    assert text.rstrip().endswith(C2_LINE)


def test_apply_all_applies_every_pending_proposal_as_its_own_commit(
    runner: CliRunner, workspace
) -> None:
    """Accepts are never batched (spec.md §7.5)."""
    first = seed(workspace.templates)
    second = seed(
        workspace.templates,
        target_section="## Process",
        body="Document the release checklist before tagging.",
    )
    before = len(git(workspace.templates, "log", "--format=%H").strip().split("\n"))

    res = runner.invoke(
        app,
        ["learn", "apply", "--all", "--templates", str(workspace.templates), "--yes"],
    )
    assert res.exit_code == 0, res.output
    after = len(git(workspace.templates, "log", "--format=%H").strip().split("\n"))
    assert after == before + 2
    db = ledger()
    assert get_proposal(db, first)["status"] == "applied"
    assert get_proposal(db, second)["status"] == "applied"


def test_apply_requires_an_id_or_all(runner: CliRunner, workspace) -> None:
    """Ambiguity is refused rather than guessed at."""
    res = runner.invoke(app, ["learn", "apply", "--templates", str(workspace.templates)])
    assert res.exit_code != 0


# ------------------------------------------------------------------------ learn edit


def test_edit_applies_the_edited_body(
    runner: CliRunner, workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`edit` stores the operator's text and applies it in preference."""
    from metaproject import cli

    monkeypatch.setattr(cli, "open_in_editor", lambda text: "- Run `make audit` first.")
    pid = seed(workspace.templates)
    res = runner.invoke(
        app,
        ["learn", "edit", str(pid), "--templates", str(workspace.templates), "--yes"],
    )
    assert res.exit_code == 0, res.output
    text = (workspace.templates / "AGENTS.template.md").read_text(encoding="utf-8")
    assert "- Run `make audit` first." in text
    assert C2_LINE not in text
    row = get_proposal(ledger(), pid)
    assert row["edited_body"] == "- Run `make audit` first."
    assert row["status"] == "applied"


def test_edit_aborted_leaves_the_candidate_pending(
    runner: CliRunner, workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`$EDITOR` unset or exiting non-zero aborts the edit (spec.md §5.4.10)."""
    from metaproject import cli

    before = snapshot(workspace.templates)
    monkeypatch.setattr(cli, "open_in_editor", lambda text: None)
    pid = seed(workspace.templates)
    res = runner.invoke(
        app,
        ["learn", "edit", str(pid), "--templates", str(workspace.templates), "--yes"],
    )
    assert res.exit_code != 0
    assert snapshot(workspace.templates) == before
    assert get_proposal(ledger(), pid)["status"] == "pending"


# ---------------------------------------------------------------------- learn reject


def test_reject_suppresses_by_content_hash(runner: CliRunner, workspace) -> None:
    """The `d` keybinding's equivalent: a judgment that is remembered."""
    pid = seed(workspace.templates)
    res = runner.invoke(app, ["learn", "reject", str(pid)])
    assert res.exit_code == 0
    row = get_proposal(ledger(), pid)
    assert row["status"] == "rejected"
    assert row["rejected_score"] == pytest.approx(2.5)


def test_reject_forget_clears_the_record(runner: CliRunner, workspace) -> None:
    """`--forget` clears the suppression entirely (spec.md §5.4.7)."""
    pid = seed(workspace.templates)
    runner.invoke(app, ["learn", "reject", str(pid)])
    res = runner.invoke(app, ["learn", "reject", str(pid), "--forget"])
    assert res.exit_code == 0
    assert get_proposal(ledger(), pid) is None


def test_reject_on_an_unknown_id_exits_non_zero(runner: CliRunner) -> None:
    """Rejecting nothing is an error, not a silent success."""
    res = runner.invoke(app, ["learn", "reject", "4242"])
    assert res.exit_code != 0


# ------------------------------------------------------------------ command surface


def test_learn_help_lists_every_phase_four_subcommand(runner: CliRunner) -> None:
    """spec.md §5.4.4's command surface, minus the Phase 5 TUI entries."""
    res = runner.invoke(app, ["learn", "--help"])
    assert res.exit_code == 0
    for name in ("scan", "list", "show", "apply", "edit", "reject"):
        assert name in res.output
