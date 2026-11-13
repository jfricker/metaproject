"""Tests for the bundled SDLC cycle skills' text and packaging (R-IMP, R-SKL-7, R-TXT)."""

import re
import zipfile
from pathlib import Path

import pytest

from metaproject.skills import bundled_skills, get_bundled_sdlc_skills_dir

REPO_ROOT = Path(__file__).resolve().parent.parent

SDLC_SKILLS = (
    "backlog-new",
    "write-intent",
    "generate-spec",
    "generate-design",
    "generate-plan",
    "implement-plan",
    "execute-tests",
    "wrapup",
    "shipit",
    "verify-browser",
    "backlog-factory",
)

PRECONDITION = (
    "> **Precondition.** This project must be metaproject-managed: the nearest "
    "`.metaproject.json`\n> (this directory or an ancestor) and `metaproject` on `PATH`. "
    "If either is missing, stop and tell the\n> operator to run `metaproject new .` "
    "(agents may run only `metaproject new . --dry-run`)."
)

# Retired plugin plumbing (R-TXT-1/2).
FORBIDDEN = ("sdlc-skills:", "SessionStart", "Session assumption", "this plugin", "/plugin")


def _skill_text(name: str) -> str:
    return (get_bundled_sdlc_skills_dir() / name / "SKILL.md").read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict:
    assert text.startswith("---\n")
    block = text.split("---", 2)[1]
    fields = {}
    for line in block.strip().splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def test_all_twelve_skills_are_bundled() -> None:
    """AC-1: eleven SDLC skills plus the metaproject skill."""
    assert {s.name for s in bundled_skills()} == {*SDLC_SKILLS, "metaproject"}


@pytest.mark.parametrize("name", SDLC_SKILLS)
def test_frontmatter_name_matches_directory_and_has_description(name: str) -> None:
    """R-SKL-7: skills are invoked by bare name, which is the directory name."""
    fields = _frontmatter(_skill_text(name))
    assert fields["name"] == name
    assert fields.get("description")


@pytest.mark.parametrize("name", SDLC_SKILLS)
def test_precondition_preamble_directly_under_the_title(name: str) -> None:
    """R-TXT-1: the same preamble opens every SDLC skill's body."""
    body = _skill_text(name).split("---", 2)[2]
    after_title = body.split(f"# {name}\n", 1)[1]
    assert after_title.lstrip("\n").startswith(PRECONDITION)


@pytest.mark.parametrize("name", SDLC_SKILLS)
def test_no_plugin_plumbing(name: str) -> None:
    text = _skill_text(name)
    for needle in FORBIDDEN:
        assert needle not in text, f"{name}: {needle!r}"


@pytest.mark.parametrize("name", SDLC_SKILLS)
def test_no_root_location_reference_to_a_relocated_document(name: str) -> None:
    """R-TXT-3: relocated documents are named by their new names and `docs/` paths."""
    text = _skill_text(name)
    assert not re.search(r"\b(intent|spec|design|plan)\.md\b", text), name
    assert "repo root" not in text
    assert not re.search(r"backfill (?!docs/)[A-Za-z-]+\.md", text), name
    assert not re.search(r"`(INTENT|SPEC|TECH-DESIGN|PLAN|STATE|HANDOFF|ARCHITECTURE)\.md`", text)


def test_wrapup_archives_from_docs_and_resets_with_backfill() -> None:
    text = _skill_text("wrapup")
    assert "`docs/INTENT.md`, `docs/SPEC.md`" in text
    assert "{INTENT,SPEC,TECH-DESIGN,PLAN,STATE}.md" in text
    assert "`metaproject backfill` (no file arguments)" in text


def test_wrapup_hands_branch_cleanup_to_shipit_and_flags_unrelated_changes() -> None:
    text = _skill_text("wrapup")
    assert "/shipit" in text
    assert "Fallback if `/shipit` is not installed" in text
    assert "fast-forward merged to `main`" in text
    assert "Flag unrelated changes" in text
    assert "git branch -d" in text
    assert "git push origin --delete" in text
    assert ".agents/skills/shipit/" in text
    # Branch wrap-up definition (issue #5): five parts, stated in step 10.
    assert "A branch is *wrapped up* when" in text
    for part in (
        "passed the gate",
        "fast-forward merged to `main`",
        "pushed",
        "deployed and\n   verified (where the project deploys)",
        "worktree and local and remote branch\n   are gone",
    ):
        assert part in text, part
    assert "Wrapup owns the documents; `/shipit` owns that sequence." in text
    # Fallback stops on an unmerged branch.
    assert "if it is not merged, stop and report to the operator" in text
    # Frontmatter scope covers branches and remote.
    assert "the cycle's local and remote branches" in text.split("---", 2)[1]
    # Ordering: archive (7), reset (8), commit (9) all precede the /shipit handoff (10).
    pos = [text.index(m) for m in ("\n7. ", "\n8. ", "\n9. ", "\n10. ")]
    assert pos == sorted(pos)


def test_metaproject_skill_has_no_plugin_plumbing_and_new_paths() -> None:
    skill_dir = next(s.source_dir for s in bundled_skills() if s.name == "metaproject")
    for path in [skill_dir / "SKILL.md", *sorted((skill_dir / "references").glob("*.md"))]:
        text = path.read_text(encoding="utf-8")
        for needle in FORBIDDEN:
            assert needle not in text, f"{path.name}: {needle!r}"
        assert "`sdlc-skills`" not in text
    assert "docs/INTENT.md" in (skill_dir / "SKILL.md").read_text(encoding="utf-8")


def test_wheel_contains_every_skill(tmp_path: Path) -> None:
    """AC-1 (R-IMP-4): the built wheel carries all SDLC skills and the metaproject skill."""
    from hatchling.builders.wheel import WheelBuilder

    wheel = Path(next(WheelBuilder(str(REPO_ROOT)).build(directory=str(tmp_path))))
    names = set(zipfile.ZipFile(wheel).namelist())
    for name in SDLC_SKILLS:
        assert f"metaproject/sdlc_skills/{name}/SKILL.md" in names
    assert "metaproject/skill/SKILL.md" in names
    assert "metaproject/skill/references/commands.md" in names
    assert "metaproject/templates/docs.template/INTENT.template.md" in names


def test_import_staging_and_plugin_scaffolding_are_gone() -> None:
    """AC-2 (R-IMP-3)."""
    assert not (REPO_ROOT / "sdlc-skills-import").exists()
    assert not (REPO_ROOT / ".claude-plugin").exists()
    assert not list(REPO_ROOT.glob("**/check-metaproject.sh"))


def test_wrapup_records_manual_verification_in_todo() -> None:
    text = _skill_text("wrapup")
    assert "Needs manual verification" in text
    assert "metaproject backfill docs/TODO.md" in text
    assert "never\n   archived or reset" in text
    assert "exact steps" in text
    # The entry is written in step 9, before the commit and the /shipit handoff.
    step9 = text[text.index("\n9. ") : text.index("\n10. ")]
    assert "docs/TODO.md" in step9 and "Then commit" in step9
    # TODO.md is not among the archived documents.
    assert "{INTENT,SPEC,TECH-DESIGN,PLAN,STATE}.md" in text
