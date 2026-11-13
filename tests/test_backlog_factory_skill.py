"""Issue #11: the bundled backlog-factory skill fans out, then merges only on approval."""

from metaproject.skills import get_bundled_sdlc_skills_dir


def _skill() -> str:
    return (get_bundled_sdlc_skills_dir() / "backlog-factory" / "SKILL.md").read_text(
        encoding="utf-8"
    )


def test_backlog_factory_covers_the_orchestration() -> None:
    text = _skill()
    for needle in (
        "docs/backlog/",
        "gh issue list",
        "gh auth status",
        "git worktree add",
        "failing tests",
        "Up to 3 attempts",
        "git check-ignore",
        "git-ignored",
        "--force-with-lease",
        "/shipit",
        "preview",
        "PLAYWRIGHT_BROWSERS_PATH",
        "verify-browser",
        "docs/TODO.md",
        "Needs manual verification",
    ):
        assert needle in text, needle


def test_final_table_has_the_required_columns() -> None:
    text = _skill()
    assert "| item | PR | gate | CI attempts | screenshots | open questions |" in text


def test_merge_is_gated_on_an_explicit_ok() -> None:
    text = _skill()
    ok = text.index("Only on an explicit OK in chat")
    merge = text.index("merge the first green PR")
    assert ok < merge
    stops = text.split("## Stop conditions", 1)[1]
    assert "explicit OK in chat" in stops
    assert "Never deploy to production" in stops
    assert "Never force-push `main`" in stops


def test_overlap_is_checked_when_picking_and_before_merging() -> None:
    text = _skill()
    pick = text.split("3. **Pick independent items.**", 1)[1].split("\n4. ", 1)[0]
    recheck = text.split("7. **Re-check overlap**", 1)[1].split("\n8. ", 1)[0]
    assert "overlap" in pick
    assert "overlap" in recheck
    assert "git diff --name-only main...<branch>" in recheck


def test_build_plugin_rule_avoids_the_plugin_path_trap() -> None:
    # The parametrised plumbing test forbids "/plugin"; the build-time-code rule must be
    # phrased without a path such as a Vite plugins directory.
    text = _skill()
    assert "/plugin" not in text
    assert "build-time code (for example Vite plugins)" in text


def test_backlog_status_and_issues_are_left_alone() -> None:
    text = _skill()
    assert "Do not change a backlog doc's Status" in text
    assert "do not close issues by hand" in text


def test_backlog_factory_gates_push_merge_and_deploy_separately() -> None:
    text = " ".join(_skill().split())
    assert "authorises each subagent to push its branch and open a PR, and nothing more" in text
    assert "never `--admin`" in text
    assert "the merge approval in step 8 does not cover the deploy" in text
    assert "no local-merge path" in text
