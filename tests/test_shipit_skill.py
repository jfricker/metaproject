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


def _shipit() -> str:
    return (get_bundled_sdlc_skills_dir() / "shipit" / "SKILL.md").read_text(encoding="utf-8")


def test_production_deploy_is_gated_on_a_five_line_plan_and_operator_ok() -> None:
    text = _shipit()
    assert "Zero-downtime plan (production only)" in text
    assert "exactly five lines" in text
    for needle in ("alongside the old one", "health check", "swap step", "rollback command"):
        assert needle in text, needle
    assert "explicit OK" in text
    assert "downtime observed" in text


def test_plan_gate_precedes_deploy_execution_and_verification() -> None:
    text = _shipit()
    gate = text.index("4a. **Zero-downtime plan")
    ok = text.index("execute the plan exactly as written")
    verify = text.index("5. **Verify live.**")
    assert text.index("4. **Deploy") < gate < ok < verify
    assert "Do not run any deploy command until the operator" in text


def test_preview_and_staging_skip_the_plan_and_classification_is_documented() -> None:
    text = _shipit()
    assert "preview or staging deploy goes straight ahead" in text
    assert "## Production or preview" in text
    assert "No new configuration is introduced" in text
    assert "deploy-staging" in text and "deploy-prod" in text
    assert "treat the target as production" in text
