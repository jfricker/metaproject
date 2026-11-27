"""`subagents.py`: classification, the single agent write path, config, ledger and manifest."""

import hashlib
import json
from pathlib import Path

import pytest

from metaproject import deliverables, skills, subagents
from metaproject.exceptions import MetaProjectError
from metaproject.scaffold import TransactionalTracker
from metaproject.skills import (
    CURRENT,
    FORCED,
    INSTALLED,
    KEPT,
    MANIFEST_NAME,
    MISSING,
    MODIFIED,
    OUTDATED,
    RECORDED,
    UPDATED,
    sync_project_skills,
)
from metaproject.subagents import (
    DISABLED,
    bundled_agents,
    enabled_agents,
    inspect_project_agents,
    install_project_agents,
    internal_agent_body,
    sync_project_agents,
)

NAMES = {"spec-reviewer", "backlog-worker", "project-auditor"}


def _proj(tmp_path: Path, name: str = "proj", config: dict | None = None) -> Path:
    proj = tmp_path / name
    (proj / ".metaproject").mkdir(parents=True)
    (proj / ".metaproject" / "config.json").write_text(json.dumps(config or {}), encoding="utf-8")
    return proj


def _agents_dir(proj: Path) -> Path:
    return proj / ".claude" / "agents"


def _manifest(proj: Path) -> dict:
    path = proj / ".agents" / "skills" / MANIFEST_NAME
    return json.loads(path.read_text(encoding="utf-8"))


def _by_name(report) -> dict:
    return {s.name: s for s in report.statuses}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bundle(name: str) -> bytes:
    return next(a for a in bundled_agents() if a.name == name).path.read_bytes()


def _snapshot(*paths: Path) -> dict:
    return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) if p.exists() else None for p in paths}


# ----------------------------------------------------------------------- bundle


def test_bundled_agents_are_the_three_project_agents() -> None:
    assert {a.name for a in bundled_agents()} == NAMES
    assert [a.name for a in bundled_agents()] == sorted(NAMES)


def test_internal_agent_body_strips_frontmatter() -> None:
    body = internal_agent_body("learn-synthesizer")
    assert not body.lstrip().startswith("---")
    assert "name: learn-synthesizer" not in body
    assert body.strip()


def test_subagent_paths_are_not_scaffolded_or_learn_targets() -> None:
    paths = deliverables.subagent_paths()
    assert paths == tuple(f".claude/agents/{n}.md" for n in sorted(NAMES))
    assert deliverables.DeliverableClass.SUBAGENT.value == "subagent"
    for path in paths:
        assert path not in deliverables.scaffolded()
        assert path not in deliverables.learn_targets()
    assert not any(".claude/agents" in p for p in deliverables.scaffolded())
    assert not any(".claude/agents" in p for p in deliverables.learn_targets())


# ----------------------------------------------------------------- agents.enabled


def test_enabled_absent_empty_subset_and_unknown(tmp_path: Path) -> None:
    home = _proj(tmp_path, "a")
    agents, warnings = enabled_agents(home)
    assert {a.name for a in agents} == NAMES and warnings == []

    home = _proj(tmp_path, "b", {"agents": {"enabled": []}})
    assert enabled_agents(home) == ((), [])

    home = _proj(tmp_path, "c", {"agents": {"enabled": ["spec-reviewer"]}})
    agents, warnings = enabled_agents(home)
    assert [a.name for a in agents] == ["spec-reviewer"] and warnings == []

    home = _proj(tmp_path, "d", {"agents": {"enabled": ["spec-reviewer", "nope", "nope"]}})
    agents, warnings = enabled_agents(home)
    assert [a.name for a in agents] == ["spec-reviewer"]
    assert len(warnings) == 1 and "nope" in warnings[0]


def test_enabled_non_list_warns_and_is_absent(tmp_path: Path) -> None:
    home = _proj(tmp_path, "e", {"agents": {"enabled": "all"}})
    agents, warnings = enabled_agents(home)
    assert {a.name for a in agents} == NAMES and len(warnings) == 1


def test_unknown_enabled_name_is_a_report_warning(tmp_path: Path) -> None:
    proj = _proj(tmp_path, config={"agents": {"enabled": ["nope"]}})
    report = sync_project_agents(proj)
    assert [w for w in report.warnings if "nope" in w] and report.statuses == ()
    assert not _agents_dir(proj).exists()


# --------------------------------------------------------------------- states


def test_every_state(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    assert {s.state for s in inspect_project_agents(proj).statuses} == {MISSING}

    sync_project_agents(proj)
    report = inspect_project_agents(proj)
    assert {s.state for s in report.statuses} == {CURRENT}
    assert {p.name for p in _agents_dir(proj).iterdir()} == {f"{n}.md" for n in NAMES}

    # outdated via the manifest entry
    old = b"an older release\n"
    (_agents_dir(proj) / "spec-reviewer.md").write_bytes(old)
    manifest = _manifest(proj)
    manifest["agents"]["spec-reviewer"] = {"release": "0.0.1", "sha256": _sha(old)}
    (proj / ".agents" / "skills" / MANIFEST_NAME).write_text(json.dumps(manifest))
    # outdated via the ledger only (no manifest entry), modified, current
    ledger_old = b"ledger release\n"
    (_agents_dir(proj) / "backlog-worker.md").write_bytes(ledger_old)
    (_agents_dir(proj) / "project-auditor.md").write_bytes(b"my edit\n")
    manifest = _manifest(proj)
    del manifest["agents"]["backlog-worker"]
    (proj / ".agents" / "skills" / MANIFEST_NAME).write_text(json.dumps(manifest))
    skills.load_history.cache_clear()
    try:
        orig = skills.load_history
        skills.load_history = lambda section="skills": (  # type: ignore[assignment]
            {"backlog-worker": {_sha(ledger_old): "0.0.2"}} if section == "agents" else {}
        )
        by = _by_name(inspect_project_agents(proj))
    finally:
        skills.load_history = orig  # type: ignore[assignment]
        skills.load_history.cache_clear()
    assert by["spec-reviewer"].state == OUTDATED
    assert by["spec-reviewer"].installed_release == "0.0.1"
    assert by["backlog-worker"].state == OUTDATED
    assert by["backlog-worker"].installed_release == "0.0.2"
    assert by["project-auditor"].state == MODIFIED


def test_unrecorded_unknown_file_is_modified(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    _agents_dir(proj).mkdir(parents=True)
    (_agents_dir(proj) / "spec-reviewer.md").write_text("hand written\n")
    report = sync_project_agents(proj)
    status = _by_name(report)["spec-reviewer"]
    assert (status.state, status.action) == (MODIFIED, KEPT)
    assert (_agents_dir(proj) / "spec-reviewer.md").read_text() == "hand written\n"


def test_install_writes_and_records(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    report = sync_project_agents(proj)
    assert {s.action for s in report.statuses} == {INSTALLED}
    manifest = _manifest(proj)
    assert manifest["version"] == 3
    for name in NAMES:
        assert manifest["agents"][name] == {
            "release": skills.running_release(),
            "sha256": _sha(_bundle(name)),
        }
        assert (_agents_dir(proj) / f"{name}.md").read_bytes() == _bundle(name)
    assert not list(_agents_dir(proj).glob("*tmp*"))


def test_planted_temp_symlink_is_not_followed(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    agents_dir = _agents_dir(proj)
    agents_dir.mkdir(parents=True)
    for name in NAMES:
        (agents_dir / f".{name}.md.metaproject-tmp").symlink_to(victim)
    sync_project_agents(proj)
    assert victim.read_text() == "keep me"
    for name in NAMES:
        assert (agents_dir / f"{name}.md").read_bytes() == _bundle(name)
        assert (agents_dir / f"{name}.md").stat().st_mode & 0o777 == 0o644


def test_outdated_replaced_only_with_update(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    sync_project_agents(proj)
    dest = _agents_dir(proj) / "spec-reviewer.md"
    old = b"older\n"
    dest.write_bytes(old)
    manifest = _manifest(proj)
    manifest["agents"]["spec-reviewer"] = {"release": "0.0.1", "sha256": _sha(old)}
    (proj / ".agents" / "skills" / MANIFEST_NAME).write_text(json.dumps(manifest))

    kept = install_project_agents(proj)
    assert _by_name(kept)["spec-reviewer"].action == KEPT and dest.read_bytes() == old
    updated = sync_project_agents(proj)
    assert _by_name(updated)["spec-reviewer"].action == UPDATED
    assert dest.read_bytes() == _bundle("spec-reviewer")


def test_current_but_unrecorded_is_recorded(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    _agents_dir(proj).mkdir(parents=True)
    for name in NAMES:
        (_agents_dir(proj) / f"{name}.md").write_bytes(_bundle(name))
    report = sync_project_agents(proj)
    assert {s.action for s in report.statuses} == {RECORDED}
    assert set(_manifest(proj)["agents"]) == NAMES


# ------------------------------------------------------------------- force / safety


def test_force_replaces_only_the_named_modified_file(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    sync_project_agents(proj)
    a, b = _agents_dir(proj) / "spec-reviewer.md", _agents_dir(proj) / "backlog-worker.md"
    a.write_text("edit a\n")
    b.write_text("edit b\n")
    report = sync_project_agents(proj, force=["spec-reviewer"])
    assert _by_name(report)["spec-reviewer"].action == FORCED
    assert a.read_bytes() == _bundle("spec-reviewer")
    assert b.read_text() == "edit b\n"
    assert _manifest(proj)["agents"]["spec-reviewer"]["sha256"] == _sha(_bundle("spec-reviewer"))


def test_unknown_force_raises_before_any_write(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    with pytest.raises(MetaProjectError, match="nope"):
        sync_project_agents(proj, force=["spec-reviewer", "nope"])
    assert not _agents_dir(proj).exists()
    assert not (proj / ".agents").exists()


def test_disabled_file_is_reported_and_untouched(tmp_path: Path) -> None:
    proj = _proj(tmp_path, config={"agents": {"enabled": ["spec-reviewer"]}})
    _agents_dir(proj).mkdir(parents=True)
    dest = _agents_dir(proj) / "backlog-worker.md"
    dest.write_text("kept as is\n")
    before = _snapshot(dest)
    report = sync_project_agents(proj, force=["backlog-worker"])
    assert _by_name(report)["backlog-worker"].state == DISABLED
    assert _snapshot(dest) == before
    assert not (_agents_dir(proj) / "project-auditor.md").exists()
    assert "backlog-worker" not in _manifest(proj)["agents"]
    assert _by_name(inspect_project_agents(proj))["backlog-worker"].state == DISABLED


def test_user_agent_file_untouched(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    _agents_dir(proj).mkdir(parents=True)
    mine = _agents_dir(proj) / "my-agent.md"
    mine.write_text("mine\n")
    before = _snapshot(mine)
    report = sync_project_agents(proj, force=list(NAMES))
    assert "my-agent" not in _by_name(report)
    assert _snapshot(mine) == before


def test_symlinked_agents_dir_is_refused_without_error(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (proj / ".claude").mkdir()
    (proj / ".claude" / "agents").symlink_to(elsewhere, target_is_directory=True)
    report = sync_project_agents(proj)
    assert any("symlink" in w for w in report.warnings)
    assert list(elsewhere.iterdir()) == []
    assert not (proj / ".agents").exists()


def test_symlinked_claude_dir_is_refused_without_error(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (proj / ".claude").symlink_to(elsewhere, target_is_directory=True)
    report = sync_project_agents(proj)
    assert any("symlink" in w for w in report.warnings)
    assert list(elsewhere.iterdir()) == []


def test_failed_replace_keeps_original_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = _proj(tmp_path)
    sync_project_agents(proj)
    dest = _agents_dir(proj) / "spec-reviewer.md"
    old = b"older\n"
    dest.write_bytes(old)
    manifest = _manifest(proj)
    manifest["agents"]["spec-reviewer"] = {"release": "0.0.1", "sha256": _sha(old)}
    mpath = proj / ".agents" / "skills" / MANIFEST_NAME
    mpath.write_text(json.dumps(manifest))
    manifest_before = mpath.read_bytes()

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(subagents.os, "replace", boom)
    with pytest.raises(MetaProjectError, match="spec-reviewer"):
        sync_project_agents(proj)
    monkeypatch.undo()
    assert dest.read_bytes() == old
    assert mpath.read_bytes() == manifest_before
    assert not list(_agents_dir(proj).glob("*tmp*"))


def test_tracker_records_created_files(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    tracker = TransactionalTracker()
    sync_project_agents(proj, tracker=tracker)
    created = {p.name for p in tracker.created_files}
    assert {f"{n}.md" for n in NAMES} <= created and MANIFEST_NAME in created
    assert _agents_dir(proj).resolve() in tracker.created_dirs


# ------------------------------------------------------------ home, idempotence


def test_delegating_subproject_writes_to_its_home(tmp_path: Path) -> None:
    root = tmp_path / "mono"
    (root / ".git").mkdir(parents=True)
    (root / ".metaproject").mkdir()
    (root / ".metaproject" / "config.json").write_text(
        json.dumps({"agents": {"enabled": ["spec-reviewer"]}})
    )
    sub = _proj(root / "packages", "a", {"skills": {"location": "root"}})
    report = sync_project_agents(sub)
    assert report.target == root.resolve() / ".claude" / "agents"
    assert [s.name for s in report.statuses] == ["spec-reviewer"]
    assert (root / ".claude" / "agents" / "spec-reviewer.md").is_file()
    assert not (sub / ".claude").exists() and not (sub / ".agents").exists()
    assert "spec-reviewer" in _manifest(root)["agents"]


def test_no_home_refusal_matches_skills_and_writes_nothing(tmp_path: Path) -> None:
    proj = _proj(tmp_path, "nohome", {"skills": {"location": "root"}})
    report = sync_project_agents(proj)
    assert report.notice == skills.project_skills_dir(proj).refusal
    assert report.notice and report.statuses == ()
    assert sorted(p.name for p in proj.iterdir()) == [".metaproject"]


def test_second_sync_writes_nothing(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    sync_project_skills(proj)
    sync_project_agents(proj)
    paths = [_agents_dir(proj) / f"{n}.md" for n in NAMES]
    paths.append(proj / ".agents" / "skills" / MANIFEST_NAME)
    before = _snapshot(*paths)
    report = sync_project_agents(proj)
    assert {s.action for s in report.statuses} == {KEPT}
    assert _snapshot(*paths) == before


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    report = sync_project_agents(proj, dry_run=True)
    assert {s.action for s in report.statuses} == {INSTALLED}
    assert sorted(p.name for p in proj.iterdir()) == [".metaproject"]


def test_sync_preserves_skills_and_bridges(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    sync_project_skills(proj)
    before = _manifest(proj)
    assert before["skills"] and before["bridges"]
    sync_project_agents(proj)
    after = _manifest(proj)
    assert after["skills"] == before["skills"] and after["bridges"] == before["bridges"]
    assert set(after["agents"]) == NAMES
    sync_project_skills(proj)
    assert set(_manifest(proj)["agents"]) == NAMES


def test_v2_manifest_syncs_to_v3(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    sync_project_skills(proj)
    path = proj / ".agents" / "skills" / MANIFEST_NAME
    data = json.loads(path.read_text())
    data["version"] = 2
    del data["agents"]
    path.write_text(json.dumps(data))
    sync_project_agents(proj)
    after = _manifest(proj)
    assert after["version"] == 3 and set(after["agents"]) == NAMES
    assert after["skills"] == data["skills"]


def test_newer_manifest_reports_and_raises_on_update(tmp_path: Path) -> None:
    proj = _proj(tmp_path)
    path = proj / ".agents" / "skills" / MANIFEST_NAME
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 99}))
    before = path.read_bytes()
    with pytest.raises(MetaProjectError, match="newer"):
        sync_project_agents(proj)
    report = install_project_agents(proj)
    assert any("newer" in w for w in report.warnings)
    assert path.read_bytes() == before


def test_no_manifest_written_when_nothing_to_record(tmp_path: Path) -> None:
    proj = _proj(tmp_path, config={"agents": {"enabled": []}})
    sync_project_agents(proj)
    assert not (proj / ".agents").exists() and not (proj / ".claude").exists()


# ------------------------------------------------------------------------ ledger


def test_agents_ledger_covers_every_current_agent() -> None:
    import importlib.resources

    text = importlib.resources.files("metaproject").joinpath("skill_history.json").read_text()
    ledger = skills.parse_history(text, "agents")
    for agent in bundled_agents():
        assert _sha(agent.path.read_bytes()) in ledger.get(agent.name, {}), (
            f"{agent.name} changed since the ledger was generated; run `make skill-history`"
        )


def test_parse_history_tolerates_missing_agents_section() -> None:
    assert skills.parse_history('{"version": 1, "skills": {}}', "agents") == {}
    assert skills.parse_history('{"version": 1, "skills": {}}') == {}


def test_only_subagents_and_deliverables_declare_the_agents_path() -> None:
    src = Path(subagents.__file__).parent
    assert "subagents" not in (src / "skills.py").read_text(encoding="utf-8")
    assert "subagents" not in (src / "bridges.py").read_text(encoding="utf-8")
    allowed = {"subagents.py", "deliverables.py"}
    # Narration (docstrings, user-facing messages) may name the directory; a path join or
    # a literal `.claude/agents/` prefix used as a write target may not live elsewhere.
    narration = {"cli.py", "doctor.py"}
    for path in sorted(src.rglob("*.py")):
        if path.name in allowed | narration:
            continue
        text = path.read_text(encoding="utf-8")
        assert '".claude" / "agents"' not in text, path
        assert '".claude/agents' not in text, path
