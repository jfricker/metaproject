"""End-to-end lifecycle integration and performance tests for MetaProject."""

import time
from pathlib import Path

from typer.testing import CliRunner

from metaproject.cli import app


def test_full_lifecycle_and_performance(runner: CliRunner, tmp_path: Path) -> None:
    """Validate full end-to-end workflow: init -> new -> universe -> review -> learn."""
    config_dir = tmp_path / ".metaproject"
    workspaces_dir = tmp_path / "workspaces"
    workspaces_dir.mkdir()

    # 1. INIT
    init_res = runner.invoke(
        app,
        [
            "init",
            "--config-dir",
            str(config_dir),
            "--project-home",
            str(workspaces_dir),
            "--force",
        ],
    )
    assert init_res.exit_code == 0
    assert (config_dir / "config.json").exists()
    assert (config_dir / "templates" / "AGENTS.template.md").exists()

    # 2. NEW (with sub-second benchmark)
    project_target = workspaces_dir / "rover_mission"
    start_time = time.perf_counter()

    new_res = runner.invoke(
        app,
        [
            "new",
            "rover_mission",
            "--output",
            str(project_target),
            "--title",
            "Mars Rover Mission",
            "--description",
            "Autonomous planetary robotics",
            "--templates",
            str(config_dir / "templates"),
            "--yes",
        ],
    )
    elapsed = time.perf_counter() - start_time

    assert new_res.exit_code == 0
    # Verify sub-second performance requirement (spec §2.1)
    assert elapsed < 1.0, f"Scaffolding took {elapsed:.3f}s, expected < 1.0s"

    assert (project_target / "README.md").exists()
    assert (project_target / "AGENTS.md").exists()
    assert (project_target / "intent.md").exists()
    assert (project_target / "STATE.md").exists()
    assert (project_target / "HANDOFF.md").exists()
    assert (project_target / "CLAUDE.md").exists()
    assert (project_target / ".gitignore").exists()
    assert (project_target / "docs").exists()
    assert (project_target / ".git").exists()

    # 3. UNIVERSE
    db_path = config_dir / "universe.db"
    universe_res = runner.invoke(
        app,
        [
            "universe",
            str(workspaces_dir),
            "--db",
            str(db_path),
            "--format",
            "json",
        ],
    )
    assert universe_res.exit_code == 0
    assert "rover_mission" in universe_res.output
    assert "Active Now" in universe_res.output

    # 4. REVIEW
    review_res = runner.invoke(
        app,
        [
            "review",
            str(project_target),
            "--templates",
            str(config_dir / "templates"),
        ],
    )
    assert review_res.exit_code == 0
    assert "PASS" in review_res.output

    # 5. LEARN
    # The legacy line-diff harvester is deleted (plan.md §1.1) and the replacement
    # pipeline is not wired to the CLI until Phase 4. `learn` must fail loudly and,
    # critically, must not mutate the template store on the way out.
    agents_file = project_target / "AGENTS.md"
    with open(agents_file, "a", encoding="utf-8") as f:
        f.write("\n### Robotics Rule\nAlways test motor calibration before telemetry.\n")

    central_tmpl = config_dir / "templates" / "AGENTS.template.md"
    template_before = central_tmpl.read_bytes()

    learn_res = runner.invoke(
        app,
        [
            "learn",
            str(project_target),
            "--templates",
            str(config_dir / "templates"),
        ],
    )
    assert learn_res.exit_code == 1
    assert "being rebuilt" in learn_res.output
    assert central_tmpl.read_bytes() == template_before
