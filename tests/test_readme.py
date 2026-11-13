"""Guards on the README's Install and Update sections (#4)."""

import re
import tomllib
from pathlib import Path

import typer

from metaproject import __version__
from metaproject.cli import app

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _section(heading: str) -> str:
    start = README.index(f"\n{heading}\n")
    end = README.index("\n## ", start + 1)
    return README[start:end]


def _commands(group: typer.Typer, prefix: str = "") -> set:
    names = set()
    for command in group.registered_commands:
        name = command.name or command.callback.__name__.replace("_", "-")
        names.add(f"{prefix}{name}")
    for sub in group.registered_groups:
        names.add(f"{prefix}{sub.name}")
        names |= _commands(sub.typer_instance, f"{prefix}{sub.name} ")
    return names


def test_install_and_update_come_first_and_in_order() -> None:
    install = README.index("\n## Install\n")
    update = README.index("\n## Update\n")
    tutorial = README.index("\n## Tutorial")
    assert install < update < tutorial


def test_every_pinned_install_ref_names_the_running_release() -> None:
    refs = re.findall(r"github\.com/jfricker/metaproject(?:\.git)?@v(\d+\.\d+\.\d+)", README)
    assert refs, "README documents no tag-pinned install"
    assert set(refs) == {__version__}


def test_no_pypi_install_and_no_wrong_owner() -> None:
    bare = re.compile(
        r"(?:pip|pipx|uv tool) install(?: -U| --upgrade| --force)* \"?metaproject\b(?!\[tui\] @)"
    )
    assert not bare.search(README)
    assert "johnfricker/metaproject" not in README
    assert "test.pypi.org" not in README


def test_install_and_update_name_only_registered_commands() -> None:
    known = _commands(app)
    text = _section("## Install") + _section("## Update")
    named = re.findall(r"`metaproject ([a-z][a-z-]*(?: [a-z][a-z-]*)?)", text)
    assert named
    for phrase in named:
        words = phrase.split()
        assert words[0] in known, phrase
        if len(words) == 2 and words[0] in {"skills", "learn", "universe"}:
            assert phrase in known, phrase


def test_core_dependencies_and_tui_extra_match_the_table() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    core = {re.split(r"[<>=\[ ]", dep)[0] for dep in project["dependencies"]}
    assert core == {"typer", "rich", "jinja2"}
    tui = {re.split(r"[<>=\[ ]", dep)[0] for dep in project["optional-dependencies"]["tui"]}
    assert tui == {"textual", "questionary", "sqlite-utils"}
