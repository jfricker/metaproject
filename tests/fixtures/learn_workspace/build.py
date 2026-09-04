"""Materialize the learn acceptance-criteria workspace into a temporary directory.

Git does not preserve mtimes, but `universe` classifies projects by them, so the
fixture tree is copied out and stamped from `expectations.json` on every use.

Typical use from a test::

    from tests.fixtures.learn_workspace.build import build_workspace

    def test_collect_ignores_pristine_render(tmp_path):
        ws = build_workspace(tmp_path)
        evidence = collect(ws.projects / "orbit", ws.templates)
        assert evidence == []
"""

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

FIXTURE_ROOT = Path(__file__).parent
EXPECTATIONS_PATH = FIXTURE_ROOT / "expectations.json"


@dataclass
class Workspace:
    """A materialized copy of the fixture workspace."""

    root: Path
    projects: Path
    templates: Path
    expectations: Dict[str, Any]

    def project(self, name: str) -> Path:
        """Return the path to one fixture project."""
        return self.projects / name

    def case(self, case_id: str) -> Dict[str, Any]:
        """Return one acceptance case by id (e.g. "C2")."""
        for case in self.expectations["cases"]:
            if case["id"] == case_id:
                return case
        raise KeyError(f"No such acceptance case: {case_id}")

    def cases_for_phase(self, phase: int) -> List[Dict[str, Any]]:
        """Return every acceptance case gated on a given plan.md phase."""
        return [c for c in self.expectations["cases"] if c["phase"] == phase]


def load_expectations() -> Dict[str, Any]:
    """Read the machine-readable acceptance criteria."""
    return json.loads(EXPECTATIONS_PATH.read_text(encoding="utf-8"))


# Credential-shaped fixture files are written at build time rather than stored in the
# repository. Two reasons: this repo's own .gitignore excludes `.env`, so a committed
# fixture would silently vanish and take case C6 with it; and a committed file named
# `id_rsa` containing a PEM block trips secret scanners on push. Every value below is
# fabricated and inert — the AWS key is Amazon's published documentation example. They
# exist only to be caught by the redactor and the denylist.
SYNTHETIC_FILES: Dict[str, Dict[str, str]] = {
    "vault": {
        # C6: matched by vault/.gitignore, must never reach the model.
        ".env": (
            "DATABASE_URL=postgres://vault:hunter2@localhost:5432/vault\n"
            "STRIPE_SECRET_KEY=sk_live_51H8xQ2LkdIwHu7ixNCDdVQnpFakeKeyForFixtures\n"
        ),
        # C6: also gitignored.
        "secrets.yaml": (
            "# Ignored by .gitignore. Must never reach the model.\n"
            "github_token: ghp_FakeFixtureTokenNeverRealAAAAAAAAAAAA\n"
        ),
        # C7: deliberately NOT in vault/.gitignore. Only the hard denylist catches it.
        "id_rsa": (
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAABFwAAAAdzc2gtcn\n"
            "FIXTUREKEYNOTREALDONOTUSEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n"
            "-----END OPENSSH PRIVATE KEY-----\n"
        ),
    },
}


def _write_synthetic_files(project_dir: Path, name: str) -> None:
    """Write the credential-shaped files that are deliberately not committed."""
    for rel, content in SYNTHETIC_FILES.get(name, {}).items():
        (project_dir / rel).write_text(content, encoding="utf-8")


def _stamp_mtimes(project_dir: Path, age_days: float) -> None:
    """Backdate every file in a project so `universe` classifies it as intended."""
    target = time.time() - (age_days * 86400.0)
    for path in sorted(project_dir.rglob("*"), reverse=True):
        os.utime(path, (target, target))
    os.utime(project_dir, (target, target))


def build_workspace(
    dest: Path,
    git_init_templates: bool = False,
    only: Optional[List[str]] = None,
) -> Workspace:
    """Copy the fixture tree to `dest` and stamp mtimes from expectations.json.

    Args:
        dest: Directory to build into. Created if absent.
        git_init_templates: Initialize the template store as a git repository, as
            `metaproject init` does. Needed for cases that assert on commits or on
            a clean worktree (C14).
        only: Restrict to these project names. Useful for narrowing a failing case.
    """
    expectations = load_expectations()
    dest = Path(dest)
    root = dest / "learn_workspace"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    templates = root / "templates"
    shutil.copytree(FIXTURE_ROOT / "templates", templates)

    projects = root / "projects"
    projects.mkdir()

    wanted = set(only) if only else set(expectations["projects"])
    for name, meta in expectations["projects"].items():
        if name not in wanted:
            continue
        src = FIXTURE_ROOT / "projects" / name
        if not src.exists():
            raise FileNotFoundError(f"expectations.json names {name!r} but {src} is missing")
        shutil.copytree(src, projects / name)
        _write_synthetic_files(projects / name, name)
        _stamp_mtimes(projects / name, meta["age_days"])

    if git_init_templates:
        _git(templates, "init", "--initial-branch=main")
        _git(templates, "add", "-A")
        _git(
            templates,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-m",
            "chore: initial template store",
        )

    return Workspace(root=root, projects=projects, templates=templates, expectations=expectations)


def _git(cwd: Path, *args: str) -> None:
    """Run a git command in `cwd`, raising on failure."""
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
