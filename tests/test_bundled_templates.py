"""Tests for the bundled template store itself (spec.md R-NF-4, AC-7, AC-9).

These tests audit `src/metaproject/templates/` — the store `new`/`review`/`backfill`
fall back to when no `~/.metaproject/templates` override is configured — rather than any
project scaffolded from it.
"""

from pathlib import Path

import pytest

from metaproject.deliverables import DELIVERABLES, DeliverableClass
from metaproject.review import resolve_template_entry
from metaproject.scaffold import scaffold_project
from metaproject.templates import (
    find_unknown_placeholders,
    get_bundled_templates_dir,
    is_binary_file,
    render_template_string,
)

TEMPLATES_DIR = get_bundled_templates_dir()

CYCLE_TEMPLATES = (
    "intent.template.md",
    "spec.template.md",
    "design.template.md",
    "plan.template.md",
)


def test_repo_root_templates_directory_is_gone() -> None:
    """R-TPL-1: the repo-root `templates/` tree is removed; the bundled store is the
    only in-repo template tree."""
    repo_root = Path(__file__).resolve().parent.parent
    assert not (repo_root / "templates").exists()


def test_no_bundled_template_has_an_unknown_placeholder() -> None:
    """R-NF-4: every single-braced `{identifier}` in the store is whitelisted."""
    offenders = []
    for path in sorted(TEMPLATES_DIR.rglob("*")):
        if path.is_dir() or ".git" in path.parts:
            continue
        if is_binary_file(path):
            continue
        text = path.read_text(encoding="utf-8")
        unknown = find_unknown_placeholders(text)
        if unknown:
            offenders.append((path.relative_to(TEMPLATES_DIR), unknown))
    assert offenders == []


def test_every_scaffolded_deliverable_has_a_bundled_template() -> None:
    """R-TPL-4/R-NF-4: every deliverable `new`/`backfill` scaffold resolves to a
    template in the bundled store, except on-demand ones."""
    missing = []
    for deliverable in DELIVERABLES:
        if deliverable.cls is DeliverableClass.ON_DEMAND:
            continue
        entry = resolve_template_entry(deliverable.path, TEMPLATES_DIR)
        if entry is None:
            missing.append(deliverable.path)
    assert missing == []


def test_handoff_has_a_bundled_template_despite_being_on_demand() -> None:
    """R-CLS-5: HANDOFF.md is never scaffolded by `new`, but its template still lives
    in the store so `backfill HANDOFF.md` can create it by name."""
    entry = resolve_template_entry("HANDOFF.md", TEMPLATES_DIR)
    assert entry is not None
    assert entry.is_file()


@pytest.mark.parametrize("template_name", CYCLE_TEMPLATES)
def test_cycle_templates_share_the_header(template_name: str) -> None:
    """R-TPL-5: intent/spec/design/plan templates share `Author`/`Last updated`/
    `Status`/`Approved by` (intent omits `Derived from`)."""
    text = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
    assert "**Author**: {Author}." in text
    assert "**Last updated**: {Date}." in text
    assert "**Status**: Draft." in text
    assert "**Approved by**: —" in text
    if template_name != "intent.template.md":
        assert "**Derived from**:" in text


@pytest.mark.parametrize("template_name", CYCLE_TEMPLATES)
def test_cycle_templates_are_blank_by_the_title_rule(template_name: str) -> None:
    """R-TPL-6: a cycle document is blank iff its first `# ` heading contains `<Title>`."""
    text = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
    first_heading = next(line for line in text.splitlines() if line.startswith("# "))
    assert "<Title>" in first_heading


def test_state_template_has_exactly_seven_process_items() -> None:
    """R-TPL-7: STATE.md's Process list is the 7-stage cycle, no more, no less."""
    text = (TEMPLATES_DIR / "STATE.template.md").read_text(encoding="utf-8")
    items = [line for line in text.splitlines() if line.strip().startswith("- [ ]")]
    assert len(items) == 7
    for stage in (
        "write-intent",
        "generate-spec",
        "generate-design",
        "generate-plan",
        "implement-plan",
        "execute-tests",
        "wrapup",
    ):
        assert stage in text


def test_state_template_sections_each_carry_a_stage_comment() -> None:
    """R-TPL-7: each STATE.md section names, in a one-line HTML comment, which stage
    writes it."""
    text = (TEMPLATES_DIR / "STATE.template.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    # `## ` sections only — the top-level `# {ProjectTitle} — State` title isn't one.
    headings = [i for i, line in enumerate(lines) if line.startswith("## ")]
    for index in headings:
        following = [line for line in lines[index + 1 : index + 3] if line.strip()]
        assert following, f"heading with no content: {lines[index]!r}"
        assert following[0].strip().startswith("<!--"), f"no stage comment under {lines[index]!r}"


def test_claude_template_renders_with_no_stray_blank_line_on_empty_description() -> None:
    """AC-9: CLAUDE.md starts with `@AGENTS.md` context and has no double blank line
    when rendered with an empty description."""
    text = (TEMPLATES_DIR / "CLAUDE.template.md").read_text(encoding="utf-8")
    rendered = render_template_string(
        text,
        {
            "ProjectTitle": "Demo",
            "ProjectDescription": "",
            "Author": "A",
            "Date": "2026-09-14",
            "Year": "2026",
        },
    )
    assert "\n\n\n" not in rendered
    assert "@AGENTS.md" in rendered


def test_gitignore_template_ignores_claude_worktrees() -> None:
    """AC-9: `.gitignore` includes `.claude/worktrees/`."""
    text = (TEMPLATES_DIR / ".gitignore.template").read_text(encoding="utf-8")
    assert ".claude/worktrees/" in text


def test_new_dry_run_lists_every_r_tpl_4_file_and_not_handoff(tmp_path: Path) -> None:
    """AC-7: `new --dry-run` lists every R-TPL-4 file and never HANDOFF.md."""
    target = tmp_path / "dry_run_proj"
    res = scaffold_project(
        project_name="dry_run_proj",
        output=target,
        dry_run=True,
        interactive=False,
    )
    rendered = {path.relative_to(target).as_posix() for path in res["rendered_files"]}

    for expected in (
        "spec.md",
        "design.md",
        "plan.md",
        "ARCHITECTURE.md",
        "docs/DESIGN-INVARIANTS.md",
        "docs/VERIFIED-FACTS.md",
        "docs/archive/.gitkeep",
    ):
        assert expected in rendered, f"{expected} missing from dry-run listing"

    assert "HANDOFF.md" not in rendered
