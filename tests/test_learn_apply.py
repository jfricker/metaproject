"""Apply tests: structural splicing, edit precedence, commits, and the scan invariant.

plan.md Phase 4 gate and spec.md §5.4.1 stage 6, §5.4.5, §5.4.10, §7.5. Acceptance
cases asserted here: C12, C14, C21, C27.

**No test in this file invokes a model.** An autouse fixture detonates on any `claude`
argv; `git` is untouched because the fixture builder and the commit path both need it.
"""

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
import sqlite_utils

from metaproject.config import Config
from metaproject.db import get_db
from metaproject.exceptions import ApplyError
from metaproject.learn import apply as apply_mod
from metaproject.learn import review as review_queue
from metaproject.learn import scan
from metaproject.learn.apply import (
    PLACEMENT_APPEND,
    PLACEMENT_NEW_FILE,
    PLACEMENT_REMOVE,
    PLACEMENT_SECTION,
    apply_proposal,
    commit_message,
    iter_sections,
    normalize_heading,
    plan_apply,
    resolve_section,
    splice,
    template_destination,
)
from metaproject.learn.collect import collect_workspace
from metaproject.learn.store import (
    STATUS_APPLIED,
    EvidenceDraft,
    ProposalDraft,
    get_proposal,
    upsert_proposal,
)
from metaproject.templates import transform_template_name
from tests.fixtures.learn_workspace.build import build_workspace

C2_LINE = "- Run `make check` before every commit."
C2_PROJECTS = ("atlas", "kiln", "beacon")


@pytest.fixture(autouse=True)
def no_model_ever(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make it impossible for a test in this file to reach the real `claude`."""
    real_run = subprocess.run

    def guarded_run(argv, *args, **kwargs):
        parts = argv if isinstance(argv, (list, tuple)) else [argv]
        if any("claude" in str(part) for part in parts):  # pragma: no cover
            raise AssertionError("a test tried to invoke `claude`; the model must be mocked")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded_run)


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


def make_proposal(
    db: sqlite_utils.Database,
    templates_dir: Path,
    body: str = C2_LINE,
    target_section: Optional[str] = "## Testing instructions",
    target_file: str = "AGENTS.md",
    kind: str = "edit",
    title: str = "Require a green check before every commit",
) -> int:
    """Persist a proposal the way a scan would, and return its id."""
    template_path = templates_dir / "AGENTS.template.md"
    draft = ProposalDraft(
        content_hash=f"hash-{target_file}-{len(body)}-{target_section}",
        target_file=target_file,
        kind=kind,
        title=title,
        rationale="Three projects state the same pre-commit convention.",
        proposed_body=body,
        evidence_count=len(C2_PROJECTS),
        evidence_score=2.5,
        template_path=str(template_path) if kind == "edit" else None,
        target_section=target_section,
    )
    return upsert_proposal(db, draft)


@pytest.fixture
def workspace(tmp_path: Path):
    """A git-backed fixture template store plus the three C12 projects."""
    return build_workspace(tmp_path, git_init_templates=True, only=list(C2_PROJECTS))


@pytest.fixture
def db(tmp_path: Path) -> sqlite_utils.Database:
    """A fresh ledger."""
    return get_db(tmp_path / "universe.db")


# --------------------------------------------------------------- section resolution


def test_normalize_heading_ignores_hashes_case_and_spacing() -> None:
    """`## Testing Instructions` and `testing instructions` name the same section."""
    assert normalize_heading("## Testing Instructions") == normalize_heading(
        "testing   instructions"
    )
    assert normalize_heading("###  Release process  ") == normalize_heading("Release process")


def test_iter_sections_reports_level_and_extent() -> None:
    """Sections extend to the next heading of the same or shallower level."""
    text = "# Title\n\n## One\nalpha\n\n### One-a\nbeta\n\n## Two\ngamma\n"
    sections = iter_sections(text)
    titles = [(s.title, s.level) for s in sections]
    assert titles == [("Title", 1), ("One", 2), ("One-a", 3), ("Two", 2)]
    one = sections[1]
    lines = text.split("\n")
    assert lines[one.end] == "## Two"


def test_iter_sections_ignores_headings_inside_fenced_code() -> None:
    """A `#` inside a code fence is a comment, not a heading."""
    text = "# Title\n\n```sh\n# not a heading\n```\n\n## Real\n"
    assert [s.title for s in iter_sections(text)] == ["Title", "Real"]


def test_resolve_section_returns_none_for_an_absent_heading() -> None:
    """R7: an unresolvable section must be reported, never guessed at."""
    text = "# AGENTS.md\n\n## Testing instructions\n"
    assert resolve_section(text, "## Testing instructions") is not None
    assert resolve_section(text, "## Deployment") is None


# ------------------------------------------------------------------------ splicing


def test_splice_inserts_under_the_named_section_not_at_eof() -> None:
    """The headline gate: content lands inside its section."""
    text = "# AGENTS.md\n\n## Testing instructions\n\n## Process\nprose\n"
    updated, placement, reason = splice(text, C2_LINE, "## Testing instructions")
    assert placement == PLACEMENT_SECTION
    assert reason is None
    lines = updated.split("\n")
    assert lines[lines.index("## Testing instructions") + 1] == C2_LINE
    assert lines.index(C2_LINE) < lines.index("## Process")
    assert not updated.rstrip().endswith(C2_LINE)


def test_splice_appends_after_the_last_line_of_a_populated_section() -> None:
    """Existing section content is kept; the addition follows it."""
    text = "## Testing instructions\n- Use `pytest`.\n\n## Process\nprose\n"
    updated, placement, _reason = splice(text, C2_LINE, "Testing instructions")
    assert placement == PLACEMENT_SECTION
    assert "- Use `pytest`.\n" + C2_LINE in updated


def test_splice_falls_back_to_append_when_the_section_is_absent() -> None:
    """R7: fall back to a reviewed append rather than a silent misplacement."""
    text = "# AGENTS.md\n\n## Testing instructions\n"
    updated, placement, reason = splice(text, "- Deploy on green.", "## Deployment")
    assert placement == PLACEMENT_APPEND
    assert reason and "Deployment" in reason
    assert updated.rstrip().endswith("- Deploy on green.")
    assert "## Deployment" not in updated


def test_splice_never_writes_a_banner() -> None:
    """C12's regression: the legacy harvester appended under a comment banner."""
    text = "# AGENTS.md\n"
    updated, _placement, _reason = splice(text, C2_LINE, None)
    assert "metaproject learn" not in updated
    assert "<!--" not in updated


def test_splice_is_a_no_op_when_the_body_is_already_present() -> None:
    """Convergence: applying content a template already carries changes nothing."""
    text = f"# AGENTS.md\n\n## Testing instructions\n{C2_LINE}\n"
    updated, _placement, _reason = splice(text, C2_LINE, "## Testing instructions")
    assert updated == text


def test_template_destination_round_trips_through_transform_template_name() -> None:
    """A `new_template` proposal names a file the template walker will recognize."""
    for target in ("AGENTS.md", ".gitignore", "Makefile", "docs/guide.md"):
        dest = template_destination(target, Path("/templates"))
        rel = dest.relative_to(Path("/templates"))
        assert "/".join(transform_template_name(part) for part in rel.parts) == target


# ---------------------------------------------------------------- apply, end to end


def test_c12_proposal_lands_under_its_target_section(workspace, db: sqlite_utils.Database) -> None:
    """C12: structural insertion, not an EOF append under a banner."""
    pid = make_proposal(db, workspace.templates)
    apply_proposal(db, pid, templates_dir=workspace.templates)

    text = (workspace.templates / "AGENTS.template.md").read_text(encoding="utf-8")
    lines = text.split("\n")
    assert C2_LINE in lines
    assert lines.index("## Testing instructions") < lines.index(C2_LINE) < lines.index("## Process")
    assert not text.rstrip().endswith(C2_LINE)
    assert "Added via metaproject learn" not in text


def test_edited_body_takes_precedence_over_proposed_body(
    workspace, db: sqlite_utils.Database
) -> None:
    """Gate: the operator's text wins."""
    pid = make_proposal(db, workspace.templates)
    result = apply_proposal(
        db,
        pid,
        templates_dir=workspace.templates,
        edited_body="- Run `make verify` before every commit.",
    )
    text = (workspace.templates / "AGENTS.template.md").read_text(encoding="utf-8")
    assert "- Run `make verify` before every commit." in text
    assert C2_LINE not in text
    assert result.plan.body == "- Run `make verify` before every commit."
    assert get_proposal(db, pid)["edited_body"] == "- Run `make verify` before every commit."


def test_stored_edited_body_is_preferred_without_being_passed_again(
    workspace, db: sqlite_utils.Database
) -> None:
    """An edit stored by `learn edit` applies even when apply is called plainly."""
    from metaproject.learn.store import set_edited_body

    pid = make_proposal(db, workspace.templates)
    set_edited_body(db, pid, "- Run `make audit` before every commit.")
    apply_proposal(db, pid, templates_dir=workspace.templates)
    text = (workspace.templates / "AGENTS.template.md").read_text(encoding="utf-8")
    assert "- Run `make audit` before every commit." in text


def test_each_accept_is_one_commit_carrying_id_and_project_names(
    workspace, db: sqlite_utils.Database
) -> None:
    """Gate: one commit per accept, with provenance in the message (R6)."""
    before = len(git(workspace.templates, "log", "--format=%H").strip().split("\n"))
    pid = make_proposal(db, workspace.templates)
    result = apply_proposal(
        db,
        pid,
        templates_dir=workspace.templates,
        contributing_projects=C2_PROJECTS,
    )

    log = git(workspace.templates, "log", "--format=%H").strip().split("\n")
    assert len(log) == before + 1
    assert result.commit == log[0]

    message = git(workspace.templates, "log", "-1", "--format=%B")
    assert f"#{pid}" in message
    for name in C2_PROJECTS:
        assert name in message
    assert git(workspace.templates, "status", "--porcelain").strip() == ""


def test_apply_marks_the_proposal_applied_with_its_commit(
    workspace, db: sqlite_utils.Database
) -> None:
    """The ledger records where the change landed."""
    pid = make_proposal(db, workspace.templates)
    result = apply_proposal(db, pid, templates_dir=workspace.templates)
    row = get_proposal(db, pid)
    assert row["status"] == STATUS_APPLIED
    assert row["applied_commit"] == result.commit


def test_apply_refuses_on_a_dirty_template_repository(workspace, db: sqlite_utils.Database) -> None:
    """Gate: refuse, write nothing, and say what to do (spec.md §5.4.10)."""
    (workspace.templates / "AGENTS.template.md").write_text("dirtied\n", encoding="utf-8")
    before = snapshot(workspace.templates)
    head = git(workspace.templates, "rev-parse", "HEAD").strip()

    pid = make_proposal(db, workspace.templates)
    with pytest.raises(ApplyError) as exc:
        apply_proposal(db, pid, templates_dir=workspace.templates)

    assert "commit" in str(exc.value).lower() or "stash" in str(exc.value).lower()
    assert snapshot(workspace.templates) == before
    assert git(workspace.templates, "rev-parse", "HEAD").strip() == head
    assert get_proposal(db, pid)["status"] == "pending"


def test_apply_is_a_no_op_when_the_template_already_carries_the_body(
    workspace, db: sqlite_utils.Database
) -> None:
    """Nothing to write means no commit, and no empty commit either."""
    pid = make_proposal(db, workspace.templates)
    apply_proposal(db, pid, templates_dir=workspace.templates)
    head = git(workspace.templates, "rev-parse", "HEAD").strip()

    second = make_proposal(db, workspace.templates)
    result = apply_proposal(db, second, templates_dir=workspace.templates)
    assert result.changed is False
    assert result.commit is None
    assert git(workspace.templates, "rev-parse", "HEAD").strip() == head


def test_r7_absent_section_falls_back_to_a_reviewed_append(
    workspace, db: sqlite_utils.Database
) -> None:
    """C21/R7: the plan says plainly that the section did not resolve."""
    pid = make_proposal(
        db,
        workspace.templates,
        body="- Deploys are gated on a green `make check` and a signed tag.",
        target_section="## Deployment",
    )
    plan = plan_apply(db, pid, templates_dir=workspace.templates)
    assert plan.placement == PLACEMENT_APPEND
    assert plan.fallback_reason and "Deployment" in plan.fallback_reason

    apply_proposal(db, pid, templates_dir=workspace.templates)
    text = (workspace.templates / "AGENTS.template.md").read_text(encoding="utf-8")
    assert "## Deployment" not in text
    assert text.rstrip().endswith("- Deploys are gated on a green `make check` and a signed tag.")


# ------------------------------------------------------ heading proposals (plan.md C3)

AGENTS_COLLAPSE_TEXT = (
    "# AGENTS.md\n\n## Overview\nnotes\n\n\n## Constraints\n\ncontent\n\n## Risks\ndetails\n"
)

STATE_WITH_CHILD_TEXT = (
    "# STATE.md\n"
    "\n"
    "## Overview\n"
    "notes\n"
    "\n"
    "## Constraints\n"
    "\n"
    "### Budget\n"
    "details\n"
    "\n"
    "## Risks\n"
    "details\n"
)


def make_heading_proposal(
    db: sqlite_utils.Database,
    templates_dir: Path,
    kind: str,
    target_file: str,
    target_section: Optional[str],
    body: str,
    title: str,
    evidence: Optional[List[EvidenceDraft]] = None,
) -> int:
    """Persist an `add_heading`/`remove_heading` proposal the way `structure.propose`
    would, with its own evidence rows so the child-heading refusal has something to
    check `get_evidence` against."""
    draft = ProposalDraft(
        content_hash=f"hash-{kind}-{target_file}-{target_section}-{body}",
        target_file=target_file,
        kind=kind,
        title=title,
        rationale="Evidence-backed structural proposal.",
        proposed_body=body,
        evidence_count=len(evidence) if evidence else 0,
        evidence_score=2.0,
        template_path=None,
        target_section=target_section,
    )
    return upsert_proposal(db, draft, evidence=evidence)


def commit_git(templates_dir: Path, *, message: str) -> None:
    """Stage everything and commit, so a test-modified fixture starts clean."""
    subprocess.run(
        ["git", "-C", str(templates_dir), "add", "-A"], check=True, capture_output=True, text=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(templates_dir),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-m",
            message,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def state_template_workspace(workspace):
    """`workspace` plus a `STATE.template.md` with a nested `### Budget` child heading,
    committed so the store starts clean."""
    (workspace.templates / "STATE.template.md").write_text(STATE_WITH_CHILD_TEXT, encoding="utf-8")
    commit_git(workspace.templates, message="chore: add STATE template for C3 tests")
    return workspace


def test_add_heading_lands_after_its_resolved_anchor_section(
    workspace, db: sqlite_utils.Database
) -> None:
    """AC-11a: an applied heading addition lands after its nearest shared heading —
    a new sibling section, never content spliced inside the anchor's own body."""
    pid = make_heading_proposal(
        db,
        workspace.templates,
        kind="add_heading",
        target_file="AGENTS.md",
        target_section="Testing instructions",
        body="## Risks",
        title='Add "## Risks" to AGENTS.md',
    )
    plan = plan_apply(db, pid, templates_dir=workspace.templates)
    assert plan.placement == PLACEMENT_SECTION
    assert plan.fallback_reason is None

    apply_proposal(db, pid, templates_dir=workspace.templates, contributing_projects=("atlas",))
    text = (workspace.templates / "AGENTS.template.md").read_text(encoding="utf-8")
    lines = text.split("\n")
    i_test = lines.index("## Testing instructions")
    i_risks = lines.index("## Risks")
    i_process = lines.index("## Process")
    assert i_test < i_risks < i_process
    assert lines[i_risks - 1] == ""
    assert lines[i_risks + 1] == ""


def test_add_heading_with_no_anchor_appends_at_end_of_file(
    workspace, db: sqlite_utils.Database
) -> None:
    """No contributor resolved to an anchor: append, with no `fallback_reason` — this
    is silence about placement, not a failure to resolve a named section."""
    pid = make_heading_proposal(
        db,
        workspace.templates,
        kind="add_heading",
        target_file="AGENTS.md",
        target_section=None,
        body="## Risks",
        title='Add "## Risks" to AGENTS.md',
    )
    plan = plan_apply(db, pid, templates_dir=workspace.templates)
    assert plan.placement == PLACEMENT_APPEND
    assert plan.fallback_reason is None

    apply_proposal(db, pid, templates_dir=workspace.templates)
    text = (workspace.templates / "AGENTS.template.md").read_text(encoding="utf-8")
    assert text.rstrip().endswith("## Risks")


def test_add_heading_with_unresolved_section_falls_back_to_append(
    workspace, db: sqlite_utils.Database
) -> None:
    """R7, same as `splice`: a named section that does not exist falls back to a
    reviewed append and says so."""
    pid = make_heading_proposal(
        db,
        workspace.templates,
        kind="add_heading",
        target_file="AGENTS.md",
        target_section="Deployment",
        body="## Risks",
        title='Add "## Risks" to AGENTS.md',
    )
    plan = plan_apply(db, pid, templates_dir=workspace.templates)
    assert plan.placement == PLACEMENT_APPEND
    assert plan.fallback_reason and "Deployment" in plan.fallback_reason

    apply_proposal(db, pid, templates_dir=workspace.templates)
    text = (workspace.templates / "AGENTS.template.md").read_text(encoding="utf-8")
    assert text.rstrip().endswith("## Risks")


def test_add_heading_fallback_can_be_refused_without_writing(
    workspace, db: sqlite_utils.Database
) -> None:
    """`allow_fallback=False` refuses an addition's misplacement exactly like an edit's."""
    before = snapshot(workspace.templates)
    pid = make_heading_proposal(
        db,
        workspace.templates,
        kind="add_heading",
        target_file="AGENTS.md",
        target_section="Deployment",
        body="## Risks",
        title='Add "## Risks" to AGENTS.md',
    )
    with pytest.raises(ApplyError):
        apply_proposal(db, pid, templates_dir=workspace.templates, allow_fallback=False)
    assert snapshot(workspace.templates) == before
    assert get_proposal(db, pid)["status"] == "pending"


def test_add_heading_already_present_is_unchanged(workspace, db: sqlite_utils.Database) -> None:
    """Convergence (`body_is_present`'s analogue): a heading the template already has
    is not duplicated."""
    pid = make_heading_proposal(
        db,
        workspace.templates,
        kind="add_heading",
        target_file="AGENTS.md",
        target_section="Testing instructions",
        body="## Process",
        title='Add "## Process" to AGENTS.md',
    )
    plan = plan_apply(db, pid, templates_dir=workspace.templates)
    assert plan.changed is False

    result = apply_proposal(db, pid, templates_dir=workspace.templates)
    assert result.changed is False
    assert result.commit is None


def test_remove_heading_excises_the_subtree_and_collapses_blank_lines(
    workspace, db: sqlite_utils.Database
) -> None:
    """The whole subtree goes, and a resulting run of blank lines collapses to one."""
    (workspace.templates / "AGENTS.template.md").write_text(AGENTS_COLLAPSE_TEXT, encoding="utf-8")
    commit_git(workspace.templates, message="chore: reshape AGENTS template for C3 tests")

    pid = make_heading_proposal(
        db,
        workspace.templates,
        kind="remove_heading",
        target_file="AGENTS.md",
        target_section="Constraints",
        body="## Constraints",
        title='Remove "## Constraints" from AGENTS.md',
    )
    plan = plan_apply(db, pid, templates_dir=workspace.templates)
    assert plan.placement == PLACEMENT_REMOVE

    apply_proposal(db, pid, templates_dir=workspace.templates)
    text = (workspace.templates / "AGENTS.template.md").read_text(encoding="utf-8")
    assert "## Constraints" not in text
    assert "notes\n\n## Risks" in text
    assert "\n\n\n" not in text


def test_remove_heading_refuses_when_a_contributor_still_has_a_child_heading(
    state_template_workspace, db: sqlite_utils.Database, tmp_path: Path
) -> None:
    """A child heading a contributor still relies on refuses the removal outright —
    no fallback, nothing written, ever."""
    ws = state_template_workspace
    keeper = tmp_path / "keeper"
    keeper.mkdir()
    (keeper / "STATE.md").write_text(
        "# STATE.md\n\n## Overview\n\n### Budget\ndetails\n", encoding="utf-8"
    )

    pid = make_heading_proposal(
        db,
        ws.templates,
        kind="remove_heading",
        target_file="STATE.md",
        target_section="Constraints",
        body="## Constraints",
        title='Remove "## Constraints" from STATE.md',
        evidence=[EvidenceDraft(project_path=str(keeper), excerpt="## Constraints", weight=1.0)],
    )
    before = snapshot(ws.templates)
    head = git(ws.templates, "rev-parse", "HEAD").strip()

    with pytest.raises(ApplyError, match="Budget"):
        plan_apply(db, pid, templates_dir=ws.templates)

    assert snapshot(ws.templates) == before
    assert git(ws.templates, "rev-parse", "HEAD").strip() == head
    assert get_proposal(db, pid)["status"] == "pending"


def test_remove_heading_excises_when_no_contributor_still_has_the_child(
    state_template_workspace, db: sqlite_utils.Database, tmp_path: Path
) -> None:
    """A contributor without the child heading, and one missing the file entirely
    (which never counts as containing it), do not block the removal."""
    ws = state_template_workspace
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "STATE.md").write_text("# STATE.md\n\n## Overview\n\n## Risks\n", encoding="utf-8")
    missing = tmp_path / "no_state_file"
    missing.mkdir()

    pid = make_heading_proposal(
        db,
        ws.templates,
        kind="remove_heading",
        target_file="STATE.md",
        target_section="Constraints",
        body="## Constraints",
        title='Remove "## Constraints" from STATE.md',
        evidence=[
            EvidenceDraft(project_path=str(clean), excerpt="## Constraints", weight=1.0),
            EvidenceDraft(project_path=str(missing), excerpt="## Constraints", weight=1.0),
        ],
    )
    result = apply_proposal(
        db, pid, templates_dir=ws.templates, contributing_projects=("clean", "no_state_file")
    )
    assert result.changed

    text = (ws.templates / "STATE.template.md").read_text(encoding="utf-8")
    assert "## Constraints" not in text
    assert "### Budget" not in text
    assert "## Overview" in text
    assert "## Risks" in text
    assert get_proposal(db, pid)["status"] == STATUS_APPLIED


def test_remove_heading_with_unresolved_section_raises_and_store_untouched(
    workspace, db: sqlite_utils.Database
) -> None:
    """No fallback for a removal (module docstring): an unresolved section is an
    `ApplyError` raised before any plan exists, and nothing is written."""
    before = snapshot(workspace.templates)
    head = git(workspace.templates, "rev-parse", "HEAD").strip()

    pid = make_heading_proposal(
        db,
        workspace.templates,
        kind="remove_heading",
        target_file="AGENTS.md",
        target_section="Deployment",
        body="## Deployment",
        title='Remove "## Deployment" from AGENTS.md',
    )
    with pytest.raises(ApplyError, match="Deployment"):
        plan_apply(db, pid, templates_dir=workspace.templates)

    assert snapshot(workspace.templates) == before
    assert git(workspace.templates, "rev-parse", "HEAD").strip() == head
    assert get_proposal(db, pid)["status"] == "pending"


def test_each_heading_accept_is_one_commit_with_the_expected_subject(
    workspace, db: sqlite_utils.Database
) -> None:
    """One accept, one commit — for both an addition and a removal — with the wording
    plan.md C3 specifies in the subject line."""
    before = len(git(workspace.templates, "log", "--format=%H").strip().split("\n"))

    add_pid = make_heading_proposal(
        db,
        workspace.templates,
        kind="add_heading",
        target_file="AGENTS.md",
        target_section="Testing instructions",
        body="## Risks",
        title='Add "## Risks" to AGENTS.md',
    )
    apply_proposal(db, add_pid, templates_dir=workspace.templates, contributing_projects=("atlas",))

    remove_pid = make_heading_proposal(
        db,
        workspace.templates,
        kind="remove_heading",
        target_file="AGENTS.md",
        target_section="Process",
        body="## Process",
        title='Remove "## Process" from AGENTS.md',
    )
    apply_proposal(
        db, remove_pid, templates_dir=workspace.templates, contributing_projects=("atlas",)
    )

    log = git(workspace.templates, "log", "--format=%H").strip().split("\n")
    assert len(log) == before + 2

    subjects = git(workspace.templates, "log", "--format=%s", "-2").strip().split("\n")
    assert any(s == f'learn: add "## Risks" to AGENTS.md (proposal #{add_pid})' for s in subjects)
    assert any(
        s == f'learn: remove "## Process" from AGENTS.md (proposal #{remove_pid})' for s in subjects
    )


def test_r7_fallback_can_be_refused_without_writing_anything(
    workspace, db: sqlite_utils.Database
) -> None:
    """`allow_fallback=False` is how a reviewer declines a misplacement."""
    before = snapshot(workspace.templates)
    pid = make_proposal(db, workspace.templates, target_section="## Deployment")
    with pytest.raises(ApplyError):
        apply_proposal(db, pid, templates_dir=workspace.templates, allow_fallback=False)
    assert snapshot(workspace.templates) == before
    assert get_proposal(db, pid)["status"] == "pending"


def test_new_template_proposal_creates_a_template_file(
    workspace, db: sqlite_utils.Database
) -> None:
    """A `new_template` accept lands as a new file the template walker can render."""
    pid = make_proposal(
        db,
        workspace.templates,
        body="# Makefile\n\ncheck:\n\truff check .\n",
        target_section=None,
        target_file="Makefile",
        kind="new_template",
        title="Add a Makefile template",
    )
    plan = plan_apply(db, pid, templates_dir=workspace.templates)
    assert plan.placement == PLACEMENT_NEW_FILE
    apply_proposal(db, pid, templates_dir=workspace.templates)
    assert (workspace.templates / "Makefile.template").exists()


def test_commit_message_names_the_proposal_and_its_projects() -> None:
    """The message is the audit trail a revert reads (R6)."""
    message = commit_message(
        proposal_id=7,
        title="Require a green check",
        target_file="AGENTS.md",
        rationale="Three projects agree.",
        projects=("atlas", "kiln"),
        content_hash="abcdef0123456789",
    )
    assert message.splitlines()[0].startswith("learn:")
    assert "#7" in message
    assert "AGENTS.md" in message
    assert "atlas, kiln" in message


# ------------------------------------------------------- the primary safety property


def fake_runner(payload: Dict[str, Any]):
    """A `claude` stand-in that returns a fixed structured response."""

    def runner(prompt: str, model: Optional[str] = None) -> str:
        return json.dumps(payload)

    return runner


def test_c14_a_full_scan_leaves_the_template_store_byte_identical_and_clean(
    tmp_path: Path,
) -> None:
    """C14: the primary safety property. A scan never mutates a template."""
    ws = build_workspace(tmp_path, git_init_templates=True)
    db = get_db(tmp_path / "universe.db")
    before = snapshot(ws.templates)

    payload = {
        "proposals": [
            {
                "title": "Require a green check before every commit",
                "rationale": "Many projects state the same pre-commit convention.",
                "proposed_body": C2_LINE,
                "target_section": "## Testing instructions",
                "source_lines": [C2_LINE],
            }
        ]
    }

    result = scan(
        ws.projects,
        templates_dir=ws.templates,
        db=db,
        yes=True,
        runner=fake_runner(payload),
    )

    assert result.projects_scanned > 0
    assert snapshot(ws.templates) == before
    assert git(ws.templates, "status", "--porcelain").strip() == ""


def test_scan_persists_proposals_with_provenance(tmp_path: Path) -> None:
    """Stage 4: proposals and their contributing projects reach the ledger."""
    ws = build_workspace(tmp_path, git_init_templates=True, only=list(C2_PROJECTS))
    db = get_db(tmp_path / "universe.db")
    payload = {
        "proposals": [
            {
                "title": "Require a green check before every commit",
                "rationale": "Every project states the same pre-commit convention.",
                "proposed_body": C2_LINE,
                "target_section": "## Testing instructions",
                "source_lines": [C2_LINE],
            }
        ]
    }
    result = scan(
        ws.projects,
        templates_dir=ws.templates,
        db=db,
        yes=True,
        runner=fake_runner(payload),
    )
    assert result.created == 1
    from metaproject.learn import review
    from metaproject.learn.store import get_evidence

    queue = review(db)
    assert len(queue) == 1
    row = queue[0]
    assert row["target_file"] == "AGENTS.md"
    assert row["evidence_score"] > 0
    paths = {Path(e["project_path"]).name for e in get_evidence(db, row["id"])}
    assert paths == set(C2_PROJECTS)


def test_scan_declined_at_the_manifest_sends_nothing(tmp_path: Path) -> None:
    """The egress confirmation is a real gate: declining ends the run."""
    ws = build_workspace(tmp_path, git_init_templates=True, only=["atlas"])
    db = get_db(tmp_path / "universe.db")

    def detonate(prompt: str, model: Optional[str] = None) -> str:  # pragma: no cover
        raise AssertionError("evidence was sent after the operator declined")

    result = scan(
        ws.projects,
        templates_dir=ws.templates,
        db=db,
        yes=False,
        confirm_fn=lambda _prompt: False,
        runner=detonate,
    )
    assert result.aborted is True
    assert result.created == 0


def test_c27_applied_content_is_not_re_proposed(tmp_path: Path) -> None:
    """C27: after an accept, the contributing projects match the template again."""
    ws = build_workspace(tmp_path, git_init_templates=True, only=list(C2_PROJECTS))
    db = get_db(tmp_path / "universe.db")

    def added_lines_for_c2() -> List[Tuple[str, str]]:
        records = collect_workspace(ws.projects, ws.templates, config=Config())
        return [
            (r.project_name, line)
            for r in records
            if r.target_file == "AGENTS.md"
            for line in r.added_lines
            if line.strip() == C2_LINE
        ]

    assert added_lines_for_c2(), "fixture precondition: the C2 line is drift before applying"

    pid = make_proposal(db, ws.templates)
    apply_proposal(db, pid, templates_dir=ws.templates, contributing_projects=C2_PROJECTS)

    assert added_lines_for_c2() == []


def test_apply_never_runs_during_a_scan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Mutation happens only via apply, from a persisted proposal (spec.md §7.5)."""
    ws = build_workspace(tmp_path, git_init_templates=True, only=["atlas"])
    db = get_db(tmp_path / "universe.db")

    def detonate(*args, **kwargs):  # pragma: no cover
        raise AssertionError("a scan reached the apply path")

    monkeypatch.setattr(apply_mod, "apply_proposal", detonate)
    monkeypatch.setattr(apply_mod, "apply_plan", detonate)
    payload = {"proposals": []}
    scan(
        ws.projects,
        templates_dir=ws.templates,
        db=db,
        yes=True,
        runner=fake_runner(payload),
    )


# ---------------------------------------------------- `new_template`, end to end (C9)


MAKEFILE_PROJECTS = ("kiln", "beacon", "quarry")
MAKEFILE_BODY = ".PHONY: help check test lint\ncheck: lint test\nlint:\n\truff check .\n"


def test_c9_a_recurring_untemplated_file_becomes_a_new_file_in_the_template_store(
    tmp_path: Path,
) -> None:
    """The Phase 6 gate: no template, three projects, one `new_template` accept.

    The whole path is exercised — collect classifies the target as untemplated, synth
    bundles it as `new_template`, the ledger records it, and the accept creates a file
    the template walker will render for the next `metaproject new`.
    """
    ws = build_workspace(tmp_path, git_init_templates=True, only=list(MAKEFILE_PROJECTS))
    db = get_db(tmp_path / "universe.db")
    assert not list(ws.templates.glob("Makefile*")), "the fixture has no Makefile template"

    payload = {
        "proposals": [
            {
                "title": "Add a Makefile with the standard check target",
                "rationale": "Three projects carry the same lint/test entry points.",
                "proposed_body": MAKEFILE_BODY,
                "target_section": None,
                "source_lines": ["check: lint test", "lint:", "\truff check ."],
            }
        ]
    }

    result = scan(
        ws.projects,
        templates_dir=ws.templates,
        db=db,
        targets=["Makefile"],
        yes=True,
        runner=fake_runner(payload),
    )
    assert result.created == 1

    (row,) = list(review_queue(db))
    assert row["kind"] == "new_template"
    assert row["target_file"] == "Makefile"
    assert row["evidence_count"] == len(MAKEFILE_PROJECTS)

    plan = plan_apply(db, int(row["id"]), templates_dir=ws.templates)
    assert plan.placement == PLACEMENT_NEW_FILE
    assert plan.template_file == ws.templates / "Makefile.template"
    assert plan.original == ""

    applied = apply_proposal(db, int(row["id"]), templates_dir=ws.templates)
    assert applied.changed and applied.commit

    created = ws.templates / "Makefile.template"
    assert created.is_file()
    assert "ruff check ." in created.read_text(encoding="utf-8")
    assert transform_template_name(created.name) == "Makefile"

    # One accept, one commit, one file — and a clean worktree afterwards.
    assert git(ws.templates, "status", "--porcelain").strip() == ""
    changed = git(ws.templates, "show", "--name-only", "--format=", "HEAD").split()
    assert changed == ["Makefile.template"]
    assert get_proposal(db, int(row["id"]))["status"] == STATUS_APPLIED


def test_c28_directory_and_config_shaped_targets_survive_a_scan(tmp_path: Path) -> None:
    """C28: `docs/` and `pyproject.toml` are scanned without crashing the collector."""
    ws = build_workspace(tmp_path, git_init_templates=True, only=["spire"])
    db = get_db(tmp_path / "universe.db")
    before = snapshot(ws.templates)

    payload = {"proposals": []}
    result = scan(
        ws.projects,
        templates_dir=ws.templates,
        db=db,
        targets=["docs/", "pyproject.toml"],
        yes=True,
        runner=fake_runner(payload),
    )

    assert result.projects_scanned == 1
    assert result.files_scanned >= 2
    assert snapshot(ws.templates) == before
