"""Tests for `templates.source` (issue #3 part 3c).

No test reaches the network: git is either a fake runner or a real `git` acting on a
local `file://` repository built inside `tmp_path`.
"""

import json
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import List

import pytest
from typer.testing import CliRunner

from metaproject.cli import app
from metaproject.config import get_config_dir
from metaproject.identity import IDENTITY_FILE, Identity, write_identity
from metaproject.review import backfill_missing, review_project
from metaproject.template_source import (
    ORIGIN_BUNDLED,
    ORIGIN_EXPLICIT,
    ORIGIN_SOURCE,
    ORIGIN_STORE,
    TemplateSource,
    TemplateSourceError,
    cache_dir,
    fetch_template_source,
    parse_template_source,
    read_template_source,
    resolve_templates,
)
from metaproject.templates import get_bundled_templates_dir

CUSTOM_LINE = "Custom store rule: every PR names its issue."


def make_project(tmp_path: Path, source: object = None, name: str = "proj") -> Path:
    proj = tmp_path / name
    proj.mkdir()
    write_identity(
        proj,
        Identity(
            title="Proj",
            description="A project.",
            author="Pat Doe",
            created=date(2026, 1, 2),
            metaproject_version="0.9.0",
        ),
    )
    if source is not None:
        data = json.loads((proj / IDENTITY_FILE).read_text(encoding="utf-8"))
        data["templates"] = {"source": source}
        (proj / IDENTITY_FILE).write_text(json.dumps(data), encoding="utf-8")
    return proj


def custom_store(root: Path) -> Path:
    """A copy of the bundled store whose AGENTS.md carries one extra line."""
    shutil.copytree(get_bundled_templates_dir(), root)
    agents = root / "AGENTS.template.md"
    agents.write_text(agents.read_text(encoding="utf-8") + f"\n{CUSTOM_LINE}\n", encoding="utf-8")
    return root


class FakeGit:
    """Stands in for `subprocess.run`: records git calls and materialises a store."""

    def __init__(self, store: Path, fail_on: str = "") -> None:
        self.store = store
        self.fail_on = fail_on
        self.calls: List[List[str]] = []

    def __call__(self, cmd, cwd=None, **kwargs):
        assert cmd[0] == "git"
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert kwargs["timeout"]
        self.calls.append(cmd[1:])
        verb = cmd[1]
        if verb == self.fail_on:
            return subprocess.CompletedProcess(cmd, 128, "", "fatal: unable to access host\n")
        if verb == "init":
            (Path(cwd) / ".git").mkdir()
        if verb == "checkout":
            for item in self.store.iterdir():
                dest = Path(cwd) / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)
        return subprocess.CompletedProcess(cmd, 0, "", "")


# ----------------------------------------------------------------------- declaration


@pytest.mark.parametrize(
    "value, expected",
    [
        ("https://github.com/me/t.git", TemplateSource("git", "https://github.com/me/t.git")),
        ("git@github.com:me/t.git", TemplateSource("git", "git@github.com:me/t.git")),
        ("tools/templates", TemplateSource("path", "tools/templates")),
        ({"path": "tools/templates"}, TemplateSource("path", "tools/templates")),
        (
            {"url": "https://h/me/t", "ref": "v3", "subdir": "templates/"},
            TemplateSource("git", "https://h/me/t", ref="v3", subdir="templates"),
        ),
    ],
)
def test_parse_template_source(value, expected) -> None:
    assert parse_template_source(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        42,
        {"url": "ext::sh -c touch% /tmp/pwned"},
        {"url": "-uhttps://h/x"},
        {"url": "https://h/x", "ref": "--upload-pack=evil"},
        {"url": "https://h/x", "subdir": "../outside"},
        {"url": "https://h/x", "path": "also"},
        {"ref": "main"},
    ],
)
def test_malformed_template_source_is_refused(value) -> None:
    with pytest.raises(TemplateSourceError):
        parse_template_source(value)


def test_read_template_source(tmp_path: Path) -> None:
    assert read_template_source(make_project(tmp_path, name="none")) is None
    assert read_template_source(tmp_path / "missing") is None
    proj = make_project(tmp_path, source="tools/t")
    assert read_template_source(proj) == TemplateSource("path", "tools/t")


def test_cache_dir_is_stable_and_keyed_by_ref(tmp_path: Path) -> None:
    a = TemplateSource("git", "https://h/me/templates.git", ref="v1")
    b = TemplateSource("git", "https://h/me/templates.git", ref="v2")
    assert cache_dir(a) == cache_dir(a)
    assert cache_dir(a) != cache_dir(b)
    assert cache_dir(a).parent == get_config_dir() / "cache" / "templates"
    assert cache_dir(a).name.startswith("templates-")


# ------------------------------------------------------------------------ resolution


def test_explicit_templates_win(tmp_path: Path) -> None:
    proj = make_project(tmp_path, source="nowhere")
    res = resolve_templates(proj, tmp_path)
    assert (res.origin, res.path) == (ORIGIN_EXPLICIT, tmp_path.resolve())


def test_configured_store_shadows_a_declared_source(tmp_path: Path) -> None:
    store = get_config_dir() / "templates"
    custom_store(store)
    runner = FakeGit(tmp_path)
    proj = make_project(tmp_path, source="https://h/me/t.git")
    res = resolve_templates(proj, runner=runner)
    assert (res.origin, res.path) == (ORIGIN_STORE, store.resolve())
    assert runner.calls == []


def test_no_source_falls_back_to_bundled_silently(tmp_path: Path) -> None:
    res = resolve_templates(make_project(tmp_path))
    assert res.origin == ORIGIN_BUNDLED and not res.source_declared
    assert res.path == get_bundled_templates_dir()


def test_path_source_is_used_in_place(tmp_path: Path) -> None:
    proj = make_project(tmp_path, source="tools/templates")
    custom_store(proj / "tools" / "templates")
    res = resolve_templates(proj)
    assert res.origin == ORIGIN_SOURCE and res.source_declared
    assert res.path == (proj / "tools" / "templates").resolve()
    assert "templates.source path" in res.describe()


def test_missing_path_source_falls_back_to_bundled_and_says_so(tmp_path: Path) -> None:
    res = resolve_templates(make_project(tmp_path, source="tools/templates"))
    assert res.origin == ORIGIN_BUNDLED and res.source_declared
    assert "not found" in res.detail


@pytest.mark.parametrize("location", ["../outside", "/etc", "~/templates", "a/../../outside"])
def test_path_source_outside_the_project_is_refused(tmp_path: Path, location: str) -> None:
    proj = make_project(tmp_path, source=location)
    custom_store(tmp_path / "outside")
    res = resolve_templates(proj)
    assert res.origin == ORIGIN_BUNDLED and res.source_declared
    assert "outside the project" in res.detail


def test_path_source_symlinked_out_of_the_project_is_refused(tmp_path: Path) -> None:
    proj = make_project(tmp_path, source="tpl")
    custom_store(tmp_path / "outside")
    (proj / "tpl").symlink_to(tmp_path / "outside", target_is_directory=True)
    res = resolve_templates(proj)
    assert res.origin == ORIGIN_BUNDLED
    assert "outside the project" in res.detail


@pytest.mark.parametrize("url", ["http://example.com/t.git", "git://example.com/t.git"])
def test_unauthenticated_url_schemes_are_refused(tmp_path: Path, url: str) -> None:
    res = resolve_templates(make_project(tmp_path, source={"url": url}))
    assert res.origin == ORIGIN_BUNDLED and res.source_declared


def test_malformed_source_falls_back_to_bundled(tmp_path: Path) -> None:
    res = resolve_templates(make_project(tmp_path, source={"ref": "main"}))
    assert res.origin == ORIGIN_BUNDLED and res.source_declared
    assert "url" in res.detail


def test_git_source_is_fetched_once_then_reused_from_cache(tmp_path: Path) -> None:
    store = custom_store(tmp_path / "remote")
    git = FakeGit(store)
    proj = make_project(tmp_path, source={"url": "https://h/me/t.git", "ref": "v3"})

    first = resolve_templates(proj, runner=git)
    assert first.origin == ORIGIN_SOURCE and "fetched" in first.detail
    assert (first.path / "AGENTS.template.md").is_file()
    verbs = [call[0] for call in git.calls]
    assert verbs == ["init", "fetch", "checkout"]
    fetch = git.calls[1]
    assert fetch[-3:] == ["--", "https://h/me/t.git", "v3"] and "--depth" in fetch

    git.calls.clear()
    again = resolve_templates(proj, runner=git)
    assert again.path == first.path and "cached" in again.detail
    assert git.calls == []


def test_subdir_selects_the_store_inside_the_repository(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    custom_store(remote / "templates")
    proj = make_project(tmp_path, source={"url": "https://h/me/t.git", "subdir": "templates"})
    res = resolve_templates(proj, runner=FakeGit(remote))
    assert res.path.name == "templates" and (res.path / "AGENTS.template.md").is_file()


def test_offline_git_source_falls_back_to_bundled_and_leaves_no_cache(tmp_path: Path) -> None:
    git = FakeGit(tmp_path, fail_on="fetch")
    proj = make_project(tmp_path, source="https://h/me/t.git")
    res = resolve_templates(proj, runner=git)
    assert res.origin == ORIGIN_BUNDLED and res.source_declared
    assert "unable to access" in res.detail
    source = read_template_source(proj)
    assert not cache_dir(source).exists()
    assert not any(cache_dir(source).parent.glob(".*tmp-*"))


def test_missing_git_binary_falls_back(tmp_path: Path) -> None:
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    proj = make_project(tmp_path, source="https://h/me/t.git")
    res = resolve_templates(proj, runner=no_git)
    assert res.origin == ORIGIN_BUNDLED and "git is not installed" in res.detail


def test_no_fetch_mode_never_runs_git(tmp_path: Path) -> None:
    git = FakeGit(tmp_path)
    res = resolve_templates(make_project(tmp_path, source="https://h/t.git"), fetch=False)
    assert res.origin == ORIGIN_BUNDLED and git.calls == []


def test_refresh_failure_keeps_the_cached_copy(tmp_path: Path) -> None:
    source = TemplateSource("git", "https://h/me/t.git")
    store = custom_store(tmp_path / "remote")
    assert fetch_template_source(source, runner=FakeGit(store)).ok
    failed = fetch_template_source(source, runner=FakeGit(store, fail_on="fetch"))
    assert not failed.ok and failed.path is not None
    assert "kept the cached copy" in failed.message
    refreshed = fetch_template_source(source, runner=FakeGit(store))
    assert refreshed.ok and "refreshed" in refreshed.message


# ---------------------------------------------------------- backfill / review / CLI


def test_backfill_renders_from_a_path_source_and_review_reports_no_drift(
    tmp_path: Path,
) -> None:
    proj = make_project(tmp_path, source="tools/templates")
    custom_store(proj / "tools" / "templates")
    backfill_missing(proj)
    assert CUSTOM_LINE in (proj / "AGENTS.md").read_text(encoding="utf-8")

    result = review_project(proj)
    assert result.diffs == {}
    assert any("templates.source path" in note for note in result.notes)


def test_backfill_cli_prints_which_source_was_used(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("METAPROJECT_AGENT", "1")
    proj = make_project(tmp_path, source="tools/templates")
    custom_store(proj / "tools" / "templates")
    result = runner.invoke(app, ["backfill", "--dir", str(proj)])
    assert result.exit_code == 0, result.output
    assert "Templates:" in result.output and "templates.source path" in result.output


def test_backfill_cli_says_when_a_source_fell_back(runner: CliRunner, tmp_path: Path) -> None:
    proj = make_project(tmp_path, source="tools/templates")
    result = runner.invoke(app, ["backfill", "--dir", str(proj), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "bundled defaults" in result.output and "not found" in result.output


def test_backfill_cli_is_silent_about_templates_without_a_source(
    runner: CliRunner, tmp_path: Path
) -> None:
    result = runner.invoke(app, ["backfill", "--dir", str(make_project(tmp_path)), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Templates:" not in result.output


def test_templates_fetch_without_a_source_is_a_no_op(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(app, ["templates", "fetch", "--dir", str(make_project(tmp_path))])
    assert result.exit_code == 0 and "nothing to fetch" in result.output


def test_templates_fetch_reports_a_malformed_source(runner: CliRunner, tmp_path: Path) -> None:
    proj = make_project(tmp_path, source={"url": "ext::sh"})
    result = runner.invoke(app, ["templates", "fetch", "--dir", str(proj)])
    assert result.exit_code == 1


def test_templates_fetch_uses_the_fetcher(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = custom_store(tmp_path / "remote")
    git = FakeGit(store)
    monkeypatch.setattr("metaproject.template_source.subprocess.run", git)
    proj = make_project(tmp_path, source="https://h/me/t.git")
    result = runner.invoke(app, ["templates", "fetch", "--dir", str(proj)])
    assert result.exit_code == 0, result.output
    assert "fetched" in result.output and [c[0] for c in git.calls] == ["init", "fetch", "checkout"]

    failing = FakeGit(store, fail_on="fetch")
    monkeypatch.setattr("metaproject.template_source.subprocess.run", failing)
    result = runner.invoke(app, ["templates", "fetch", "--dir", str(proj)])
    assert result.exit_code == 1 and "kept the cached copy" in result.output


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_fresh_container_backfill_from_a_git_source_has_no_false_drift(
    runner: CliRunner, tmp_path: Path
) -> None:
    """Acceptance: with templates.source set and no store, backfill renders from the
    source and `review --no-tui` reports no drift. Real git, local file:// remote."""
    remote = custom_store(tmp_path / "remote")
    git = ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-C", str(remote)]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "store"], check=True)

    proj = make_project(tmp_path, source={"url": remote.as_uri(), "ref": "main"})
    assert not (get_config_dir() / "templates").exists()

    result = runner.invoke(app, ["backfill", "--dir", str(proj)])
    assert result.exit_code == 0, result.output
    assert "templates.source" in result.output
    assert CUSTOM_LINE in (proj / "AGENTS.md").read_text(encoding="utf-8")

    review = runner.invoke(app, ["review", str(proj), "--no-tui"])
    assert review.exit_code == 0, review.output
    assert "cached" in review.output
    assert review_project(proj).diffs == {}
