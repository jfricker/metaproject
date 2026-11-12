"""Issue #6: the bundled shipit skill covers every shipping step."""

from metaproject.skills import get_bundled_sdlc_skills_dir


def test_shipit_covers_the_shipping_steps() -> None:
    text = (get_bundled_sdlc_skills_dir() / "shipit" / "SKILL.md").read_text(encoding="utf-8")
    for needle in (
        "make format && make lint && make test",
        "--ff-only",
        "push origin main",
        "Makefile",
        "wrangler",
        "PM2",
        "/health",
        "worktree remove",
        "push origin --delete",
        "manual-verification",
    ):
        assert needle in text, needle
