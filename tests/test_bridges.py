import json
import os
import subprocess
from pathlib import Path

import pytest

from metaproject import bridges
from metaproject.bridges import (
    ABSENT,
    COPY,
    CURRENT,
    DIRECTORY,
    FOREIGN,
    FOREIGN_FILE,
    FOREIGN_LINK,
    LEGACY,
    MISSING,
    MODIFIED,
    OUTDATED,
    SYMLINK,
    classify_entry,
    claude_skills_shape,
    configured_link_mode,
    configured_targets,
    inspect_bridges,
    link_text,
    lost_user_skills,
    migrate_legacy_link,
    resolve_link_mode,
    shadowing,
    sync_bridges,
)
from metaproject.exceptions import MetaProjectError
from metaproject.treeops import file_map


@pytest.fixture(autouse=True)
def _clear_cache():
    bridges._clear_mode_cache()
    yield
    bridges._clear_mode_cache()


def make_skill(home: Path, name: str, body: str = "one") -> Path:
    d = home / ".agents" / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")
    return d


def write_config(project: Path, skills: dict) -> None:
    (project / ".metaproject").mkdir(parents=True, exist_ok=True)
    (project / ".metaproject" / "config.json").write_text(
        json.dumps({"skills": skills}), encoding="utf-8"
    )


def entry_of(project: Path, name: str) -> Path:
    return project / ".claude" / "skills" / name


def sync(project, names, records, **kw):
    kw.setdefault("manifest_newer", False)
    kw.setdefault("update", False)
    return sync_bridges(project, project, names, records, **kw)


def force_mode(project: Path, mode: str) -> None:
    write_config(project, {"link_mode": mode})


# ------------------------------------------------------------------ configuration


def test_configured_targets(tmp_path):
    assert configured_targets(tmp_path) == (["claude"], False, [])
    write_config(tmp_path, {"targets": ["claude", "vim", "claude"]})
    targets, recorded, warns = configured_targets(tmp_path)
    assert targets == ["claude"] and recorded and len(warns) == 1 and "vim" in warns[0]
    write_config(tmp_path, {"targets": []})
    assert configured_targets(tmp_path) == ([], True, [])
    write_config(tmp_path, {"targets": "claude"})
    targets, recorded, warns = configured_targets(tmp_path)
    assert targets == ["claude"] and recorded and len(warns) == 1


def test_configured_link_mode(tmp_path):
    assert configured_link_mode(tmp_path) == ("auto", [])
    write_config(tmp_path, {"link_mode": "copy"})
    assert configured_link_mode(tmp_path) == ("copy", [])
    write_config(tmp_path, {"link_mode": "hardlink"})
    mode, warns = configured_link_mode(tmp_path)
    assert mode == "auto" and len(warns) == 1


# ------------------------------------------------------------------ resolve_link_mode


def test_resolve_explicit(tmp_path):
    force_mode(tmp_path, "symlink")
    assert resolve_link_mode(tmp_path) == ("symlink", "skills.link_mode")
    force_mode(tmp_path, "copy")
    assert resolve_link_mode(tmp_path) == ("copy", "skills.link_mode")


def test_resolve_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(bridges, "_is_windows", lambda: True)
    assert resolve_link_mode(tmp_path) == ("copy", "Windows")


def test_resolve_default_and_patched_git(tmp_path, monkeypatch):
    monkeypatch.setattr(bridges, "read_only_query", lambda cwd, key: None)
    assert resolve_link_mode(tmp_path) == ("symlink", "default")


def test_resolve_git_core_symlinks_false(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "core.symlinks", "false"], check=True)
    assert resolve_link_mode(tmp_path) == ("copy", "core.symlinks=false")


def test_resolve_memoised(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bridges, "read_only_query", lambda c, k: calls.append(1))
    resolve_link_mode(tmp_path)
    resolve_link_mode(tmp_path)
    assert len(calls) == 1


# ------------------------------------------------------------------ shapes


def test_shapes(tmp_path):
    make_skill(tmp_path, "a")
    assert claude_skills_shape(tmp_path, tmp_path) == ABSENT
    path = tmp_path / ".claude" / "skills"
    path.parent.mkdir()
    path.mkdir()
    assert claude_skills_shape(tmp_path, tmp_path) == DIRECTORY
    path.rmdir()
    path.symlink_to("../.agents/skills")
    assert claude_skills_shape(tmp_path, tmp_path) == LEGACY
    path.unlink()
    (tmp_path / "other").mkdir()
    path.symlink_to("../other")
    assert claude_skills_shape(tmp_path, tmp_path) == FOREIGN_LINK
    path.unlink()
    path.write_text("../.agents/skills\n")
    assert claude_skills_shape(tmp_path, tmp_path) == LEGACY
    path.write_text("something else")
    assert claude_skills_shape(tmp_path, tmp_path) == FOREIGN_FILE


def test_lost_user_skills(tmp_path):
    src = tmp_path / "skills"
    for name in ("bundled", "mine", ".hidden"):
        (src / name).mkdir(parents=True)
        (src / name / "SKILL.md").write_text("x")
    (src / "nodoc").mkdir()
    (src / "file.txt").write_text("x")
    assert lost_user_skills(src, ["bundled"]) == ["mine"]
    assert lost_user_skills(tmp_path / "absent", []) == []


# ------------------------------------------------------------------ classify_entry


def setup_entry(tmp_path):
    src = make_skill(tmp_path, "a")
    entry = entry_of(tmp_path, "a")
    entry.parent.mkdir(parents=True)
    return src, entry


def test_classify_no_record(tmp_path):
    src, entry = setup_entry(tmp_path)
    assert classify_entry(entry, src, None, "symlink", None) == (MISSING, False)
    entry.symlink_to(link_text(entry, src))
    assert classify_entry(entry, src, None, "symlink", None) == (FOREIGN, True)
    entry.unlink()
    entry.mkdir()
    (entry / "SKILL.md").write_text("one")
    assert classify_entry(entry, src, None, "symlink", None) == (FOREIGN, True)
    (entry / "SKILL.md").write_text("different")
    assert classify_entry(entry, src, None, "symlink", None) == (FOREIGN, False)
    (entry / "SKILL.md").unlink()
    entry.rmdir()
    entry.write_text("file")
    assert classify_entry(entry, src, None, "symlink", None) == (FOREIGN, False)


def test_classify_recorded_absent(tmp_path):
    src, entry = setup_entry(tmp_path)
    rec = {"mode": "symlink", "link": "x"}
    assert classify_entry(entry, src, rec, "symlink", None) == (MISSING, False)


def test_classify_symlink_branches(tmp_path):
    src, entry = setup_entry(tmp_path)
    text = link_text(entry, src)
    rec = {"mode": "symlink", "link": text}
    entry.symlink_to(text)
    assert classify_entry(entry, src, rec, "symlink", None)[0] == CURRENT
    assert classify_entry(entry, src, rec, "symlink", "symlink")[0] == CURRENT
    assert classify_entry(entry, src, rec, "copy", "copy")[0] == OUTDATED
    # a working symlink under auto stays current even if the resolved mode is copy
    assert classify_entry(entry, src, rec, "copy", None)[0] == CURRENT
    # stale text
    assert (
        classify_entry(entry, src, {"mode": "symlink", "link": "old"}, "symlink", None)[0]
        == OUTDATED
    )
    # dangling
    entry.unlink()
    entry.symlink_to(text + "-gone")
    gone = {"mode": "symlink", "link": text + "-gone"}
    assert classify_entry(entry, src, gone, "symlink", None)[0] == OUTDATED
    # unmaterialised
    entry.unlink()
    entry.write_text(text + "\n")
    assert classify_entry(entry, src, rec, "symlink", None)[0] == OUTDATED
    entry.write_text("edited")
    assert classify_entry(entry, src, rec, "symlink", None)[0] == MODIFIED
    entry.unlink()
    entry.mkdir()
    assert classify_entry(entry, src, rec, "symlink", None)[0] == MODIFIED


def test_classify_copy_branches(tmp_path):
    src, entry = setup_entry(tmp_path)
    entry.mkdir()
    (entry / "SKILL.md").write_text("one")
    rec = {"mode": "copy", "files": file_map(src)}
    assert classify_entry(entry, src, rec, "symlink", None)[0] == CURRENT
    # auto leaves a working copy alone on a symlink-capable machine
    assert classify_entry(entry, src, rec, "symlink", "copy")[0] == CURRENT
    assert classify_entry(entry, src, rec, "symlink", "symlink")[0] == OUTDATED
    # source moved on, copy pristine
    (src / "SKILL.md").write_text("two")
    assert classify_entry(entry, src, rec, "symlink", None)[0] == OUTDATED
    # hand edit
    (entry / "SKILL.md").write_text("hand")
    assert classify_entry(entry, src, rec, "symlink", None)[0] == MODIFIED
    # not a directory
    import shutil

    shutil.rmtree(entry)
    entry.write_text("x")
    assert classify_entry(entry, src, rec, "symlink", None)[0] == MODIFIED
    entry.unlink()
    entry.symlink_to(src)
    assert classify_entry(entry, src, rec, "symlink", None)[0] == MODIFIED


# ------------------------------------------------------------------ sync


def test_sync_creates_symlinks_and_is_idempotent(tmp_path):
    make_skill(tmp_path, "a")
    make_skill(tmp_path, "b")
    report, recs = sync(tmp_path, ["a", "b"], {})
    assert report.mode == "symlink"
    assert entry_of(tmp_path, "a").is_symlink()
    assert os.readlink(entry_of(tmp_path, "a")) == "../../.agents/skills/a"
    assert recs["entries"]["a"] == {"mode": "symlink", "link": "../../.agents/skills/a"}
    assert recs["created"] == [".claude/skills", ".claude"]
    assert report.entries["a"] == {"state": MISSING, "action": "created", "note": None}
    report2, recs2 = sync(tmp_path, ["a", "b"], recs)
    assert recs2 == recs
    assert report2.entries["a"]["state"] == CURRENT and report2.entries["a"]["action"] is None
    assert inspect_bridges(tmp_path, tmp_path, ["a"], recs, False).entries["a"]["state"] == CURRENT


def test_sync_creates_copies_and_is_idempotent(tmp_path):
    make_skill(tmp_path, "a")
    force_mode(tmp_path, "copy")
    report, recs = sync(tmp_path, ["a"], {})
    entry = entry_of(tmp_path, "a")
    assert entry.is_dir() and not entry.is_symlink()
    assert (entry / "SKILL.md").read_text() == "one"
    assert recs["entries"]["a"]["mode"] == "copy"
    assert recs["entries"]["a"]["files"] == file_map(entry)
    _, recs2 = sync(tmp_path, ["a"], recs)
    assert recs2 == recs
    assert not (
        tmp_path / ".agents" / ".metaproject-skills-tmp" / "bridges" / "_home" / "a.new"
    ).exists()


def test_sync_existing_claude_dir_not_recorded_as_created(tmp_path):
    make_skill(tmp_path, "a")
    (tmp_path / ".claude" / "skills").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "mine").mkdir()
    _, recs = sync(tmp_path, ["a"], {})
    assert recs["created"] == []
    assert (tmp_path / ".claude" / "skills" / "mine").is_dir()


def test_sync_in_subproject_uses_home_source(tmp_path):
    home = tmp_path
    make_skill(home, "a")
    sub = home / "pkg" / "app"
    sub.mkdir(parents=True)
    _, recs = sync_bridges(sub, home, ["a"], {}, manifest_newer=False, update=False)
    entry = entry_of(sub, "a")
    assert entry.resolve() == (home / ".agents" / "skills" / "a").resolve()
    assert os.readlink(entry) == "../../../../.agents/skills/a"
    force_mode(sub, "copy")
    bridges._clear_mode_cache()
    entry.unlink()
    _, recs = sync_bridges(sub, home, ["a"], {}, manifest_newer=False, update=False)
    assert recs["entries"]["a"]["mode"] == "copy"


def test_outdated_rewritten_only_with_update(tmp_path):
    src = make_skill(tmp_path, "a")
    force_mode(tmp_path, "copy")
    _, recs = sync(tmp_path, ["a"], {})
    (src / "SKILL.md").write_text("two")
    report, recs2 = sync(tmp_path, ["a"], recs)
    assert report.entries["a"]["state"] == OUTDATED and report.entries["a"]["action"] is None
    assert (entry_of(tmp_path, "a") / "SKILL.md").read_text() == "one"
    assert recs2 == recs
    report, recs3 = sync(tmp_path, ["a"], recs, update=True)
    assert report.entries["a"]["action"] == "updated"
    assert (entry_of(tmp_path, "a") / "SKILL.md").read_text() == "two"
    assert recs3["entries"]["a"]["files"] == file_map(src)


def test_dangling_symlink_rewritten(tmp_path):
    make_skill(tmp_path, "a")
    _, recs = sync(tmp_path, ["a"], {})
    entry = entry_of(tmp_path, "a")
    entry.unlink()
    entry.symlink_to("nowhere")
    recs["entries"]["a"]["link"] = "nowhere"
    report, recs2 = sync(tmp_path, ["a"], recs, update=True)
    assert report.entries["a"]["state"] == OUTDATED
    assert os.readlink(entry) == "../../.agents/skills/a"
    assert recs2["entries"]["a"]["link"] == "../../.agents/skills/a"


def test_unmaterialised_symlink_rewritten(tmp_path):
    make_skill(tmp_path, "a")
    _, recs = sync(tmp_path, ["a"], {})
    entry = entry_of(tmp_path, "a")
    entry.unlink()
    entry.write_text("../../.agents/skills/a")
    report, _ = sync(tmp_path, ["a"], recs, update=True)
    assert report.entries["a"]["state"] == OUTDATED
    assert entry.is_symlink()


def test_modified_only_with_force(tmp_path):
    make_skill(tmp_path, "a")
    force_mode(tmp_path, "copy")
    _, recs = sync(tmp_path, ["a"], {})
    (entry_of(tmp_path, "a") / "SKILL.md").write_text("hand")
    report, _ = sync(tmp_path, ["a"], recs, update=True)
    info = report.entries["a"]
    assert info["state"] == MODIFIED and info["action"] is None
    assert "Copilot" in info["note"]
    assert (entry_of(tmp_path, "a") / "SKILL.md").read_text() == "hand"
    report, recs2 = sync(tmp_path, ["a"], recs, update=True, force=["a"])
    assert report.entries["a"]["action"] == "updated"
    assert (entry_of(tmp_path, "a") / "SKILL.md").read_text() == "one"
    assert recs2["entries"]["a"]["files"] == file_map(entry_of(tmp_path, "a"))


def test_foreign_skipped_recorded_or_replaced(tmp_path):
    make_skill(tmp_path, "same")
    make_skill(tmp_path, "diff")
    for name in ("same", "diff"):
        e = entry_of(tmp_path, name)
        e.parent.mkdir(parents=True, exist_ok=True)
        e.mkdir()
        (e / "SKILL.md").write_text("one" if name == "same" else "user text")
    report, recs = sync(tmp_path, ["same", "diff"], {}, update=True)
    assert report.entries["same"]["state"] == FOREIGN
    assert report.entries["same"]["note"] == "identical"
    assert report.entries["same"]["action"] == "skipped"
    assert report.entries["diff"]["action"] == "skipped"
    assert len(report.warnings) == 2
    assert recs == {}
    assert (entry_of(tmp_path, "diff") / "SKILL.md").read_text() == "user text"
    report, recs = sync(tmp_path, ["same", "diff"], {}, force=["same"])
    assert report.entries["same"]["action"] == "recorded"
    assert recs["entries"]["same"]["mode"] == "copy"
    assert entry_of(tmp_path, "diff").joinpath("SKILL.md").read_text() == "user text"
    report, recs = sync(tmp_path, ["same", "diff"], recs, force=["diff"])
    assert report.entries["diff"]["action"] == "updated"
    assert entry_of(tmp_path, "diff").is_symlink()
    assert recs["entries"]["diff"]["mode"] == "symlink"


def test_foreign_identical_symlink_recorded(tmp_path):
    src = make_skill(tmp_path, "a")
    e = entry_of(tmp_path, "a")
    e.parent.mkdir(parents=True)
    e.symlink_to(link_text(e, src))
    _, recs = sync(tmp_path, ["a"], {}, force=["a"])
    assert recs["entries"]["a"] == {"mode": "symlink", "link": os.readlink(e)}


def test_symlink_oserror_falls_back_to_copy(tmp_path, monkeypatch):
    make_skill(tmp_path, "a")

    def boom(*a, **k):
        raise OSError("no privilege")

    monkeypatch.setattr(os, "symlink", boom)
    report, recs = sync(tmp_path, ["a"], {})
    assert recs["entries"]["a"]["mode"] == "copy"
    assert any("copy" in w for w in report.warnings)
    assert entry_of(tmp_path, "a").is_dir()


def test_permission_error_stops_pass_keeps_partial(tmp_path, monkeypatch):
    for n in ("a", "b", "c"):
        make_skill(tmp_path, n)
    real = os.symlink

    def deny_b(text, path, *a, **k):
        if Path(path).name == "b":
            raise PermissionError("denied")
        return real(text, path, *a, **k)

    monkeypatch.setattr(os, "symlink", deny_b)
    report, recs = sync(tmp_path, ["a", "b", "c"], {})
    assert report.notice == bridges.DENIED_NOTICE
    assert "metaproject skills sync" in report.notice
    assert list(recs["entries"]) == ["a"]
    assert not entry_of(tmp_path, "c").exists() and not entry_of(tmp_path, "c").is_symlink()


def test_permission_error_in_copy(tmp_path, monkeypatch):
    make_skill(tmp_path, "a")
    force_mode(tmp_path, "copy")

    def deny(*a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr(bridges, "swap_tree", deny)
    report, recs = sync(tmp_path, ["a"], {})
    assert report.notice == bridges.DENIED_NOTICE
    assert recs["entries"] == {}


def test_swap_tree_false_skips(tmp_path, monkeypatch):
    make_skill(tmp_path, "a")
    force_mode(tmp_path, "copy")
    monkeypatch.setattr(bridges, "swap_tree", lambda *a, **k: False)
    report, recs = sync(tmp_path, ["a"], {})
    assert report.entries["a"]["action"] == "skipped"
    assert recs["entries"] == {}


def test_manifest_newer_writes_nothing(tmp_path):
    make_skill(tmp_path, "a")
    report, recs = sync(tmp_path, ["a"], {}, manifest_newer=True, update=True)
    assert "newer metaproject" in report.notice
    assert not (tmp_path / ".claude").exists()
    assert recs == {}


def test_legacy_and_foreign_shapes_write_nothing(tmp_path):
    make_skill(tmp_path, "a")
    (tmp_path / ".claude").mkdir()
    path = tmp_path / ".claude" / "skills"
    path.symlink_to("../.agents/skills")
    report, recs = sync(tmp_path, ["a"], {})
    assert "legacy link" in report.notice and "metaproject doctor" in report.notice
    assert recs == {}
    assert sorted(p.name for p in (tmp_path / ".agents" / "skills").iterdir()) == ["a"]
    path.unlink()
    (tmp_path / "x").mkdir()
    path.symlink_to("../x")
    report, _ = sync(tmp_path, ["a"], {})
    assert str(path) in report.notice
    assert list((tmp_path / "x").iterdir()) == []
    path.unlink()
    path.write_text("junk")
    report, _ = sync(tmp_path, ["a"], {})
    assert str(path) in report.notice and path.read_text() == "junk"


def test_dry_run_writes_nothing(tmp_path):
    make_skill(tmp_path, "a")
    report, recs = sync(tmp_path, ["a"], {}, dry_run=True)
    assert report.entries["a"]["action"] == "created"
    assert recs == {}
    assert not (tmp_path / ".claude").exists()


def test_missing_source_skipped(tmp_path):
    report, recs = sync(tmp_path, ["ghost"], {})
    assert report.entries["ghost"]["action"] == "skipped"
    assert recs == {}


class Tracker:
    def __init__(self):
        self.dirs, self.files = [], []

    def record_created_dir(self, p):
        self.dirs.append(Path(p))

    def record_created_file(self, p):
        self.files.append(Path(p))


def test_tracker_records(tmp_path):
    make_skill(tmp_path, "a")
    t = Tracker()
    sync(tmp_path, ["a"], {}, tracker=t)
    assert tmp_path / ".claude" in t.dirs and tmp_path / ".claude" / "skills" in t.dirs
    assert entry_of(tmp_path, "a") in t.files


# ------------------------------------------------------------------ removal


def test_removal(tmp_path):
    for n in ("a", "b"):
        make_skill(tmp_path, n)
    force_mode(tmp_path, "copy")
    _, recs = sync(tmp_path, ["a", "b"], {})
    write_config(tmp_path, {"targets": [], "link_mode": "copy"})
    (entry_of(tmp_path, "b") / "SKILL.md").write_text("hand")
    report, recs2 = sync(tmp_path, ["a", "b"], recs)
    assert report.removed == ["a"]
    assert not entry_of(tmp_path, "a").exists()
    assert "b" in recs2["entries"] and "a" not in recs2["entries"]
    assert any("b" in w for w in report.warnings)
    assert (tmp_path / ".claude" / "skills").is_dir()
    # once b is gone too, the created directories go
    (entry_of(tmp_path, "b") / "SKILL.md").write_text("one")
    report, recs3 = sync(tmp_path, ["a", "b"], recs2)
    assert report.removed == ["b"]
    assert not (tmp_path / ".claude").exists()
    assert recs3 == {"created": [], "entries": {}}


def test_removal_keeps_unrecorded_dirs(tmp_path):
    make_skill(tmp_path, "a")
    (tmp_path / ".claude" / "skills").mkdir(parents=True)
    _, recs = sync(tmp_path, ["a"], {})
    write_config(tmp_path, {"targets": []})
    report, recs2 = sync(tmp_path, ["a"], recs)
    assert report.removed == ["a"]
    assert (tmp_path / ".claude" / "skills").is_dir()


def test_removal_keeps_nonempty_dirs(tmp_path):
    make_skill(tmp_path, "a")
    _, recs = sync(tmp_path, ["a"], {})
    (tmp_path / ".claude" / "skills" / "mine").mkdir()
    write_config(tmp_path, {"targets": []})
    sync(tmp_path, ["a"], recs)
    assert (tmp_path / ".claude" / "skills" / "mine").is_dir()


def test_removal_inspect_and_dry_run_write_nothing(tmp_path):
    make_skill(tmp_path, "a")
    _, recs = sync(tmp_path, ["a"], {})
    write_config(tmp_path, {"targets": []})
    report = inspect_bridges(tmp_path, tmp_path, ["a"], recs, False)
    assert report.removed == [] and entry_of(tmp_path, "a").is_symlink()
    report, recs2 = sync(tmp_path, ["a"], recs, dry_run=True)
    assert report.removed == ["a"] and entry_of(tmp_path, "a").is_symlink()
    assert recs2 == recs


def test_target_warnings_reported(tmp_path):
    make_skill(tmp_path, "a")
    write_config(tmp_path, {"targets": ["claude", "zed"], "link_mode": "bogus"})
    report, _ = sync(tmp_path, ["a"], {})
    assert len(report.warnings) == 2


# ------------------------------------------------------------------ migrate


def make_legacy(tmp_path, as_file: bool):
    make_skill(tmp_path, "a")
    make_skill(tmp_path, "b")
    make_skill(tmp_path, "mine")
    (tmp_path / ".claude").mkdir()
    path = tmp_path / ".claude" / "skills"
    if as_file:
        path.write_bytes(b"../.agents/skills\n")
    else:
        path.symlink_to("../.agents/skills")
    return path


@pytest.mark.parametrize("as_file", [False, True])
def test_migrate_success(tmp_path, as_file):
    path = make_legacy(tmp_path, as_file)
    report, recs = migrate_legacy_link(tmp_path, tmp_path, ["a", "b"])
    assert report.lost == ["mine"]
    assert path.is_dir() and not path.is_symlink()
    assert entry_of(tmp_path, "a").is_symlink() and entry_of(tmp_path, "b").is_symlink()
    assert not entry_of(tmp_path, "mine").exists()
    assert recs["created"] == [".claude/skills"]
    assert set(recs["entries"]) == {"a", "b"}
    assert report.entries["a"]["action"] == "created"


def test_migrate_requires_legacy(tmp_path):
    make_skill(tmp_path, "a")
    with pytest.raises(MetaProjectError):
        migrate_legacy_link(tmp_path, tmp_path, ["a"])


@pytest.mark.parametrize("as_file", [False, True])
def test_migrate_failure_restores(tmp_path, monkeypatch, as_file):
    path = make_legacy(tmp_path, as_file)

    def boom(*a, **k):
        (tmp_path / ".claude" / "skills" / "junk").write_text("x")
        raise RuntimeError("kaboom")

    monkeypatch.setattr(bridges, "sync_bridges", boom)
    with pytest.raises(MetaProjectError, match="kaboom"):
        migrate_legacy_link(tmp_path, tmp_path, ["a", "b"])
    if as_file:
        assert path.is_file() and not path.is_symlink()
        assert path.read_bytes() == b"../.agents/skills\n"
    else:
        assert path.is_symlink() and os.readlink(path) == "../.agents/skills"


def test_migrate_denied_restores(tmp_path, monkeypatch):
    path = make_legacy(tmp_path, False)

    def deny(*a, **k):
        raise PermissionError("denied")

    real = os.symlink

    def selective(text, p, *a, **k):
        if Path(p) == path:
            return real(text, p, *a, **k)
        raise PermissionError("denied")

    monkeypatch.setattr(os, "symlink", selective)
    with pytest.raises(MetaProjectError):
        migrate_legacy_link(tmp_path, tmp_path, ["a", "b"])
    assert path.is_symlink() and os.readlink(path) == "../.agents/skills"


# ------------------------------------------------------------------ shadowing


def test_shadowing(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    (fake_home / ".claude" / "skills" / "x").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    project = tmp_path / "proj"
    (project / ".github" / "skills" / "x").mkdir(parents=True)
    out = shadowing(project, ["x", "y"])
    assert len(out) == 2
    assert "~/.claude/skills/x overrides the project's x in Claude Code" in out[0]
    assert ".github/skills/x is loaded before .agents/skills by Copilot" in out[1]
    assert shadowing(project, ["y"]) == []


def test_drift_note():
    assert bridges.drift_note(MODIFIED, COPY).startswith("differs from .agents/skills")
    assert bridges.drift_note(MODIFIED, SYMLINK) is None
    assert bridges.drift_note(CURRENT, COPY) is None
    assert FOREIGN == "foreign" and FOREIGN_FILE == "foreign_file"
