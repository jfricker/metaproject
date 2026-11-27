"""The bundled subagent definitions are well formed and carry no repo-specific content."""

from __future__ import annotations

import re
from importlib import resources

from metaproject.learn.synth import EVIDENCE_BEGIN, EVIDENCE_END
from metaproject.skills import bundled_skills

PROJECT_AGENTS = {"spec-reviewer", "backlog-worker", "project-auditor"}
FORBIDDEN = ("R-AGT", "Checks D", "/Users/", "MetaProject")
REQ_ID = re.compile(r"\bR-[A-Z]{2,4}-\d")


def _project_files():
    root = resources.files("metaproject") / "agents"
    return sorted((f for f in root.iterdir() if f.name.endswith(".md")), key=lambda f: f.name)


def _learn_file():
    return resources.files("metaproject") / "learn" / "agents" / "learn-synthesizer.md"


def _parse(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    assert lines[0] == "---"
    end = lines.index("---", 1)
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, "\n".join(lines[end + 1 :])


def test_project_agent_set():
    assert {f.name[:-3] for f in _project_files()} == PROJECT_AGENTS


def test_project_agent_frontmatter():
    for f in _project_files():
        meta, _ = _parse(f.read_text(encoding="utf-8"))
        for key in ("name", "description", "tools", "effort"):
            assert meta.get(key), (f.name, key)
        assert "model" not in meta
        assert meta["name"] == f.name[:-3]


def test_no_repo_specific_content():
    for f in [*_project_files(), _learn_file()]:
        text = f.read_text(encoding="utf-8")
        for bad in FORBIDDEN:
            assert bad not in text, (f.name, bad)
        assert not REQ_ID.search(text), f.name


def test_names_disjoint_from_skills():
    skill_names = {s.name if hasattr(s, "name") else str(s) for s in bundled_skills()}
    assert not (PROJECT_AGENTS & skill_names)


def test_learn_synthesizer():
    text = _learn_file().read_text(encoding="utf-8")
    meta, _ = _parse(text)
    assert "model" not in meta and "tools" not in meta
    assert EVIDENCE_BEGIN in text and EVIDENCE_END in text
