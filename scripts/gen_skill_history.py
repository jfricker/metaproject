#!/usr/bin/env python3
"""Regenerate `src/metaproject/skill_history.json`, the ledger of released skill digests.

`metaproject skills sync` replaces an installed skill only when it is a pristine copy of
some release. For installs that predate the install manifest, "pristine" is decided by
looking the installed skill's digest up in this ledger.

The ledger is append-only: every `v<X.Y.Z>` tag from 0.8.0 on is read with
`git archive` (a tag missing a skill directory is tolerated), then the current tree is
added under the version in `pyproject.toml`. A digest already present for a skill is
never relabelled or removed, so a rerun is idempotent.

Usage: scripts/gen_skill_history.py [--ledger PATH] [--check]
"""

import argparse
import io
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from metaproject.skills import file_map, skill_digest, skills_in  # noqa: E402

LEDGER = ROOT / "src" / "metaproject" / "skill_history.json"
SKILL_PATHS = ("src/metaproject/skill", "src/metaproject/sdlc_skills")
FIRST_RELEASE = (0, 8, 0)
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def release_tags() -> list:
    try:
        out = subprocess.run(
            ["git", "tag", "--list", "v*"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        return []
    tags = []
    for tag in out:
        match = TAG.match(tag)
        if match and tuple(int(g) for g in match.groups()) >= FIRST_RELEASE:
            tags.append((tuple(int(g) for g in match.groups()), tag))
    return [tag for _, tag in sorted(tags)]


def extract(tag: str, dest: Path) -> None:
    for path in SKILL_PATHS:
        result = subprocess.run(
            ["git", "archive", "--format=tar", tag, path], cwd=ROOT, capture_output=True
        )
        if result.returncode != 0:
            continue  # this release did not ship that directory
        with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
            archive.extractall(dest, filter="data")


def digests_of(root: Path) -> dict:
    skill_dir = root / "src" / "metaproject" / "skill"
    sdlc_dir = root / "src" / "metaproject" / "sdlc_skills"
    return {
        skill.name: skill_digest(file_map(skill.source_dir))
        for skill in skills_in(skill_dir, sdlc_dir)
    }


def current_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE).group(1)


def build(existing: dict) -> dict:
    skills = {name: list(entries) for name, entries in existing.get("skills", {}).items()}

    def add(release: str, digests: dict) -> None:
        for name, digest in digests.items():
            entries = skills.setdefault(name, [])
            if not any(entry["digest"] == digest for entry in entries):
                entries.append({"digest": digest, "release": release})

    for tag in release_tags():
        with tempfile.TemporaryDirectory() as tmp:
            extract(tag, Path(tmp))
            add(tag[1:], digests_of(Path(tmp)))
    add(current_version(), digests_of(ROOT))
    return {"version": 1, "skills": dict(sorted(skills.items()))}


def render(ledger: dict) -> str:
    import json

    return json.dumps(ledger, indent=2) + "\n"


def main() -> int:
    import json

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--check", action="store_true", help="exit 1 if the ledger would change")
    args = parser.parse_args()

    existing = json.loads(args.ledger.read_text(encoding="utf-8")) if args.ledger.exists() else {}
    text = render(build(existing))
    current = args.ledger.read_text(encoding="utf-8") if args.ledger.exists() else None
    if text == current:
        print(f"{args.ledger}: up to date")
        return 0
    if args.check:
        print(f"{args.ledger}: out of date; run `make skill-history`", file=sys.stderr)
        return 1
    args.ledger.write_text(text, encoding="utf-8")
    print(f"{args.ledger}: written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
