"""Issue #11: the bundled verify-browser skill reproduces in WebKit before it fixes."""

from metaproject.skills import get_bundled_sdlc_skills_dir


def _skill() -> str:
    return (get_bundled_sdlc_skills_dir() / "verify-browser" / "SKILL.md").read_text(
        encoding="utf-8"
    )


def test_verify_browser_covers_the_loop() -> None:
    text = _skill()
    for needle in (
        "PLAYWRIGHT_BROWSERS_PATH",
        ".playwright-browsers/",
        "git check-ignore .playwright-browsers",
        "webkit",
        "chromium",
        "mobile-safari",
        "e2e_port",
        "fails on current `main`",
        "chrome-devtools",
        "docs/TODO.md",
        "Needs manual verification",
        "metaproject backfill docs/TODO.md",
        "real device",
        "cannot be reproduced",
    ):
        assert needle in text, needle


def test_reproduce_precedes_fix_precedes_commit() -> None:
    text = _skill()
    reproduce = text.index("5. **Reproduce in WebKit first.**")
    fix = text.index("7. **Fix and iterate**")
    commit = text.index("9. **Commit**")
    assert reproduce < fix < commit


def test_commit_is_gated_on_all_three_projects() -> None:
    stops = _skill().split("## Stop conditions", 1)[1]
    assert "Do not commit until" in stops
    for project in ("`webkit`", "`chromium`", "`mobile-safari`"):
        assert project in stops, project
    assert "Never weaken, skip or delete the regression test" in stops
    assert 'Never claim "verified in Safari"' in stops


def test_lock_procedure_is_referenced_not_restated() -> None:
    # The Playwright-lock handling lives in execute-tests (#10); this skill points at it.
    text = _skill()
    assert "`execute-tests` step 2" in text
    assert "__dirlock" not in text


def test_skill_is_generic_across_projects() -> None:
    text = _skill().lower()
    for app_specific in ("turnstile", "piece-slide", "cloudflare", "vite"):
        assert app_specific not in text, app_specific


def test_todo_entry_is_skipped_when_nothing_is_outstanding() -> None:
    text = _skill()
    assert "add no entry when nothing is outstanding" in text
