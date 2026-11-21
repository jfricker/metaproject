"""Tests for `.metaproject/config.json` identity: round-trip, fallback order, and tolerance
(spec.md R-ID-1, R-ID-1a, R-ID-2, R-ID-3, AC-6)."""

import json
from datetime import date
from pathlib import Path

from metaproject.identity import (
    IDENTITY_FILE,
    LEGACY_IDENTITY_FILE,
    Identity,
    config_path,
    fallback_identity,
    find_project_root,
    find_repo_root,
    has_config,
    is_legacy_only,
    read_identity,
    read_settings,
    resolve_project_dir,
    write_identity,
)
from metaproject.variables import project_variables, titlecase

# ------------------------------------------------------------------------ round-trip


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    identity = Identity(
        title="Orbit",
        description="Satellite telemetry ingest.",
        author="Ada Lovelace",
        created=date(2026, 1, 15),
        metaproject_version="0.7.0",
    )

    written_path = write_identity(tmp_path, identity)

    assert written_path == tmp_path / IDENTITY_FILE
    result = read_identity(tmp_path)
    assert result == identity


def test_written_file_is_pretty_sorted_json_with_trailing_newline(tmp_path: Path) -> None:
    identity = Identity(
        title="Orbit",
        description="Satellite telemetry ingest.",
        author="Ada Lovelace",
        created=date(2026, 1, 15),
        metaproject_version="0.7.0",
    )
    write_identity(tmp_path, identity)

    raw = (tmp_path / IDENTITY_FILE).read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert not raw.endswith("\n\n")

    data = json.loads(raw)
    assert data == {
        "title": "Orbit",
        "description": "Satellite telemetry ingest.",
        "author": "Ada Lovelace",
        "created": "2026-01-15",
        "metaproject_version": "0.7.0",
    }
    # sorted keys
    assert list(json.loads(raw).keys()) == sorted(data.keys())


# ------------------------------------------------------------------------ read tolerance


def test_read_identity_missing_file_returns_none(tmp_path: Path) -> None:
    assert read_identity(tmp_path) is None


def test_read_identity_bad_json_returns_none(tmp_path: Path) -> None:
    (tmp_path / ".metaproject").mkdir(parents=True, exist_ok=True)
    (tmp_path / IDENTITY_FILE).write_text("{not valid json", encoding="utf-8")
    assert read_identity(tmp_path) is None


def test_read_identity_missing_fields_returns_none(tmp_path: Path) -> None:
    (tmp_path / ".metaproject").mkdir(parents=True, exist_ok=True)
    (tmp_path / IDENTITY_FILE).write_text(
        json.dumps({"title": "Orbit", "description": ""}), encoding="utf-8"
    )
    assert read_identity(tmp_path) is None


def test_read_identity_bad_created_date_returns_none(tmp_path: Path) -> None:
    (tmp_path / ".metaproject").mkdir(parents=True, exist_ok=True)
    (tmp_path / IDENTITY_FILE).write_text(
        json.dumps(
            {
                "title": "Orbit",
                "description": "",
                "author": "Ada",
                "created": "not-a-date",
                "metaproject_version": "0.7.0",
            }
        ),
        encoding="utf-8",
    )
    assert read_identity(tmp_path) is None


def test_read_identity_wrong_field_type_returns_none(tmp_path: Path) -> None:
    (tmp_path / ".metaproject").mkdir(parents=True, exist_ok=True)
    (tmp_path / IDENTITY_FILE).write_text(
        json.dumps(
            {
                "title": 42,
                "description": "",
                "author": "Ada",
                "created": "2026-01-15",
                "metaproject_version": "0.7.0",
            }
        ),
        encoding="utf-8",
    )
    assert read_identity(tmp_path) is None


def test_read_identity_non_object_json_returns_none(tmp_path: Path) -> None:
    (tmp_path / ".metaproject").mkdir(parents=True, exist_ok=True)
    (tmp_path / IDENTITY_FILE).write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert read_identity(tmp_path) is None


# ------------------------------------------------------------------------ fallback order


def test_fallback_from_readme_heading_and_paragraph(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "# Orbit\n\nSatellite telemetry ingest.\n\n## Quick Start\n```bash\nmake help\n```\n",
        encoding="utf-8",
    )
    title, description = fallback_identity(tmp_path)
    assert title == "Orbit"
    assert description == "Satellite telemetry ingest."


def test_fallback_readme_title_not_truncated_at_hyphen(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "# Orbit - Satellite Telemetry Platform\n\nDescription here.\n",
        encoding="utf-8",
    )
    title, _description = fallback_identity(tmp_path)
    assert title == "Orbit - Satellite Telemetry Platform"


def test_fallback_readme_skips_code_fence_for_description(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "# Orbit\n```bash\nmake help\n```\nReal description.\n",
        encoding="utf-8",
    )
    title, description = fallback_identity(tmp_path)
    assert title == "Orbit"
    assert description == "Real description."


def test_fallback_readme_placeholder_title_is_treated_as_absent(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# <Title>\n\nSome description.\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fallback-pkg"\ndescription = "From pyproject."\n',
        encoding="utf-8",
    )
    title, description = fallback_identity(tmp_path)
    assert title == "Fallback Pkg"
    assert description == "From pyproject."


def test_fallback_from_pyproject_when_no_readme(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "widget-factory"\ndescription = "Builds widgets."\n',
        encoding="utf-8",
    )
    title, description = fallback_identity(tmp_path)
    assert title == "Widget Factory"
    assert description == "Builds widgets."


def test_fallback_from_package_json_when_no_readme_or_pyproject(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "widget-ui", "description": "UI for widgets."}),
        encoding="utf-8",
    )
    title, description = fallback_identity(tmp_path)
    assert title == "Widget Ui"
    assert description == "UI for widgets."


def test_fallback_to_directory_name_when_nothing_else(tmp_path: Path) -> None:
    project_dir = tmp_path / "my-cool-app"
    project_dir.mkdir()
    title, description = fallback_identity(project_dir)
    assert title == "My Cool App"
    assert description == ""


def test_fallback_pyproject_placeholder_falls_through_to_package_json(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "<name>"\ndescription = "unused"\n',
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "real-package", "description": "Real one."}),
        encoding="utf-8",
    )
    title, description = fallback_identity(tmp_path)
    assert title == "Real Package"
    assert description == "Real one."


def test_fallback_never_reads_intent_md(tmp_path: Path) -> None:
    (tmp_path / "intent.md").write_text(
        "# Intent Title\n\n## Problem\n{Problem description}\n", encoding="utf-8"
    )
    title, description = fallback_identity(tmp_path)
    # No README/pyproject/package.json present: must fall through to directory name,
    # never picking up "Intent Title" from intent.md.
    assert title == titlecase(tmp_path.name)
    assert description == ""


def test_fallback_readme_present_never_reads_intent_md(tmp_path: Path) -> None:
    (tmp_path / "intent.md").write_text(
        "# Intent Title\n\n## Problem\nIntent description.\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# Real Title\n\nReal description.\n", encoding="utf-8")
    title, description = fallback_identity(tmp_path)
    assert title == "Real Title"
    assert description == "Real description."


# ------------------------------------------------------------------------ project_variables


def test_project_variables_renders_date_and_year_from_identity_created(tmp_path: Path) -> None:
    identity = Identity(
        title="Orbit",
        description="Satellite telemetry ingest.",
        author="Ada Lovelace",
        created=date(2020, 6, 1),
        metaproject_version="0.7.0",
    )
    write_identity(tmp_path, identity)

    variables = project_variables(tmp_path)

    assert variables["Date"] == "2020-06-01"
    assert variables["Year"] == "2020"
    assert variables["ProjectTitle"] == "Orbit"
    assert variables["ProjectDescription"] == "Satellite telemetry ingest."
    assert variables["Author"] == "Ada Lovelace"


def test_project_variables_without_identity_falls_back_and_uses_today(tmp_path: Path) -> None:
    import datetime

    (tmp_path / "README.md").write_text(
        "# Orbit\n\nSatellite telemetry ingest.\n", encoding="utf-8"
    )

    variables = project_variables(tmp_path)

    assert variables["ProjectTitle"] == "Orbit"
    assert variables["ProjectDescription"] == "Satellite telemetry ingest."
    today = datetime.datetime.now().date()
    assert variables["Date"] == today.strftime("%Y-%m-%d")
    assert variables["Year"] == str(today.year)


# ------------------------------------------------------------------- project root (#18)


def _anchor(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".metaproject").mkdir(parents=True, exist_ok=True)
    (path / IDENTITY_FILE).write_text("{}", encoding="utf-8")
    return path.resolve()


def test_find_project_root_at_self_and_from_a_deep_subdirectory(tmp_path: Path) -> None:
    proj = _anchor(tmp_path / "p")
    deep = proj / "a" / "b"
    deep.mkdir(parents=True)
    assert find_project_root(proj) == proj
    assert find_project_root(deep) == proj


def test_find_project_root_takes_the_nearest_of_two(tmp_path: Path) -> None:
    outer = _anchor(tmp_path / "o")
    inner = _anchor(outer / "packages" / "i")
    (inner / "src").mkdir()
    assert find_project_root(inner / "src") == inner
    assert find_project_root(outer / "packages") == outer


def test_find_project_root_stops_at_the_git_boundary(tmp_path: Path) -> None:
    _anchor(tmp_path / "above")
    repo = tmp_path / "above" / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "src").mkdir()
    assert find_project_root(repo / "src") is None
    worktree = tmp_path / "above" / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    assert find_project_root(worktree) is None
    assert find_repo_root(repo / "src") == repo.resolve()
    assert find_repo_root(worktree) == worktree.resolve()


def test_find_project_root_none_found_and_corrupt_nearest_still_wins(tmp_path: Path) -> None:
    (tmp_path / "x" / ".git").mkdir(parents=True)
    assert find_project_root(tmp_path / "x") is None
    outer = _anchor(tmp_path / "y")
    (outer / ".git").mkdir()
    inner = outer / "in"
    inner.mkdir()
    (inner / ".metaproject").mkdir(parents=True, exist_ok=True)
    (inner / IDENTITY_FILE).write_text("{not json", encoding="utf-8")
    assert find_project_root(inner) == inner.resolve()
    assert read_settings(inner) == {}


def test_resolve_project_dir_explicit_wins_and_falls_back_to_cwd(tmp_path: Path) -> None:
    outer = _anchor(tmp_path / "o")
    (outer / ".git").mkdir()
    sub = outer / "sub"
    sub.mkdir()
    assert resolve_project_dir(sub) == sub.resolve()
    assert resolve_project_dir(None, cwd=sub) == outer
    bare = tmp_path / "bare"
    (bare / ".git").mkdir(parents=True)
    assert resolve_project_dir(None, cwd=bare) == bare.resolve()


# ------------------------------------------------------- legacy .metaproject.json (R-CFG)


def _write_legacy(path: Path, data: object) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / LEGACY_IDENTITY_FILE).write_text(json.dumps(data), encoding="utf-8")
    return path.resolve()


def _write_new(path: Path, data: object) -> Path:
    (path / ".metaproject").mkdir(parents=True, exist_ok=True)
    (path / IDENTITY_FILE).write_text(json.dumps(data), encoding="utf-8")
    return path.resolve()


IDENTITY_DATA = {
    "title": "Legacy",
    "description": "Old layout.",
    "author": "Ada",
    "created": "2026-01-02",
    "metaproject_version": "0.9.1",
}


def test_identity_file_is_under_dot_metaproject() -> None:
    assert IDENTITY_FILE == ".metaproject/config.json"
    assert LEGACY_IDENTITY_FILE == ".metaproject.json"


def test_legacy_only_project_is_still_read_and_anchors(tmp_path: Path) -> None:
    proj = _write_legacy(tmp_path / "p", {**IDENTITY_DATA, "commands": {"lint": "x"}})
    (proj / "src").mkdir()
    assert has_config(proj)
    assert is_legacy_only(proj)
    assert config_path(proj) == proj / LEGACY_IDENTITY_FILE
    assert find_project_root(proj / "src") == proj
    identity = read_identity(proj)
    assert identity is not None and identity.title == "Legacy"
    assert read_settings(proj)["commands"] == {"lint": "x"}


def test_new_file_wins_over_legacy(tmp_path: Path) -> None:
    proj = _write_legacy(tmp_path / "p", IDENTITY_DATA)
    _write_new(proj, {**IDENTITY_DATA, "title": "Current"})
    assert not is_legacy_only(proj)
    assert config_path(proj) == proj / IDENTITY_FILE
    identity = read_identity(proj)
    assert identity is not None and identity.title == "Current"


def test_bare_dot_metaproject_dir_is_not_an_anchor(tmp_path: Path) -> None:
    proj = tmp_path / "p"
    (proj / ".metaproject" / "docs").mkdir(parents=True)
    (proj / ".git").mkdir()
    assert not has_config(proj)
    assert find_project_root(proj) is None


def test_user_store_dir_is_never_an_anchor(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    store = home / ".metaproject"
    store.mkdir(parents=True)
    (store / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("METAPROJECT_CONFIG_DIR", str(store))
    (home / "work").mkdir()
    assert not has_config(home)
    assert find_project_root(home / "work") is None


def test_write_identity_updates_a_legacy_file_in_place(tmp_path: Path) -> None:
    proj = _write_legacy(tmp_path / "p", {**IDENTITY_DATA, "e2e_port": 4321})
    path = write_identity(
        proj,
        Identity(
            title="Renamed",
            description="d",
            author="Ada",
            created=date(2026, 1, 2),
            metaproject_version="0.10.0",
        ),
    )
    assert path == proj / LEGACY_IDENTITY_FILE
    assert not (proj / IDENTITY_FILE).exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["title"] == "Renamed" and data["e2e_port"] == 4321


def test_write_identity_creates_dot_metaproject_for_a_new_project(tmp_path: Path) -> None:
    path = write_identity(
        tmp_path,
        Identity(
            title="New",
            description="d",
            author="Ada",
            created=date(2026, 1, 2),
            metaproject_version="0.10.0",
        ),
    )
    assert path == tmp_path / IDENTITY_FILE
    assert not (tmp_path / LEGACY_IDENTITY_FILE).exists()
