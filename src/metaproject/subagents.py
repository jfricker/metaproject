"""The bundled project subagents: their installation, inspection and update.

Project agents ship as package data (`agents/<name>.md`) and are installed into
`<home>/.claude/agents/<name>.md`, where `<home>` is `skills.skills_home(project)`. This
module is the only writer of those files and of the manifest's `agents` section, through
one atomic write path (`_write_agent`). Classification follows the skills vocabulary
(`current`, `outdated`, `modified`, `missing`, plus `disabled`): a file is replaced only
when it is a pristine copy of some release or the operator names it with `--force`. A
user's own agent files, and files for agents that `agents.enabled` excludes, are never
read for writing, replaced, moved or deleted.

The internal `learn-synthesizer` agent (`learn/agents/`) is never installed; its body is
read through `internal_agent_body`.

Dependency direction: `subagents` imports `skills`; `skills` must never import
`subagents`.
"""

import hashlib
import importlib.resources
import os
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

from metaproject import skills
from metaproject.exceptions import MetaProjectError
from metaproject.skills import (
    CURRENT,
    FORCED,
    INSTALLED,
    KEPT,
    MANIFEST_NEWER,
    MANIFEST_PRESENT,
    MISSING,
    MODIFIED,
    OUTDATED,
    RECORDED,
    UPDATED,
    Manifest,
)

if TYPE_CHECKING:
    from metaproject.scaffold import TransactionalTracker

DISABLED = "disabled"  # a file for a bundled agent that `agents.enabled` excludes; report-only
TEMP_SUFFIX = ".metaproject-tmp"
HISTORY_SECTION = "agents"


@dataclass(frozen=True)
class BundledAgent:
    name: str
    path: Path  # the package file


@dataclass(frozen=True)
class AgentStatus:
    name: str
    state: str
    installed_release: Optional[str]
    action: Optional[str] = None
    note: Optional[str] = None


@dataclass
class AgentsReport:
    """What one agent pass found and did. `notice` is set only for the no-home refusal."""

    target: Path
    statuses: Tuple[AgentStatus, ...] = ()
    warnings: List[str] = field(default_factory=list)
    notice: Optional[str] = None
    manifest_state: Optional[str] = None


# ------------------------------------------------------------------------ bundle


def _agents_package_dir() -> Path:
    return skills._package_dir("agents")


def bundled_agents() -> Tuple[BundledAgent, ...]:
    """The project agents shipped in `agents/`, sorted by name. Never `learn-synthesizer`."""
    root = _agents_package_dir()
    if not root.is_dir():
        return ()
    return tuple(
        BundledAgent(path.stem, path)
        for path in sorted(root.glob("*.md"), key=lambda p: p.name)
        if path.stem != "learn-synthesizer"
    )


def internal_agent_body(name: str) -> str:
    """The body of an internal agent (`learn/agents/<name>.md`) without its frontmatter."""
    text = (
        importlib.resources.files("metaproject")
        .joinpath("learn", "agents", f"{name}.md")
        .read_text(encoding="utf-8")
    )
    lines = text.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                return "".join(lines[index + 1 :])
    return text


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def enabled_agents(home: Path) -> Tuple[Tuple[BundledAgent, ...], List[str]]:
    """The agents `agents.enabled` selects in `home`'s config, and any warnings.

    Absent selects all, `[]` none. An unknown name warns once and is ignored; a value
    that is not a list warns and is treated as absent.
    """
    from metaproject.identity import IDENTITY_FILE, read_settings

    declared = bundled_agents()
    settings = read_settings(home).get("agents")
    if settings is None:
        return declared, []
    if not isinstance(settings, dict):
        return declared, [f'{IDENTITY_FILE} "agents" is not an object; ignored.']
    if "enabled" not in settings:
        return declared, []
    value = settings["enabled"]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return declared, [f"{IDENTITY_FILE} agents.enabled is not a list of names; ignored."]
    by_name = {agent.name: agent for agent in declared}
    warnings: List[str] = []
    chosen: List[str] = []
    seen_unknown: set = set()
    for name in value:
        if name in by_name:
            if name not in chosen:
                chosen.append(name)
        elif name not in seen_unknown:
            seen_unknown.add(name)
            warnings.append(
                f"{IDENTITY_FILE} agents.enabled names unknown agent '{name}'; ignored "
                f"(bundled: {', '.join(sorted(by_name))})."
            )
    return tuple(a for a in declared if a.name in chosen), warnings


# ---------------------------------------------------------------- classification


def classify_agent(
    agent: BundledAgent,
    dest: Path,
    entry: Optional[Dict],
    history_digests: Dict[str, str],
    running: str,
) -> AgentStatus:
    """The state of one agent file: absent -> missing; bytes == bundle -> current;
    sha256 == its manifest entry or a ledger digest -> outdated; otherwise modified."""
    if not dest.exists() and not dest.is_symlink():
        return AgentStatus(agent.name, MISSING, None)
    recorded = entry.get("release") if entry else None
    if dest.is_symlink() or not dest.is_file():
        return AgentStatus(agent.name, MODIFIED, recorded, note="not a regular file")
    try:
        digest = _sha256(dest.read_bytes())
    except OSError:
        return AgentStatus(agent.name, MODIFIED, recorded, note="unreadable")
    if digest == _sha256(agent.path.read_bytes()):
        return AgentStatus(agent.name, CURRENT, recorded or running)
    if entry and entry.get("sha256") == digest:
        return AgentStatus(agent.name, OUTDATED, recorded)
    if digest in history_digests:
        return AgentStatus(agent.name, OUTDATED, history_digests[digest])
    return AgentStatus(agent.name, MODIFIED, recorded)


# ---------------------------------------------------------------------- context


@dataclass
class _Context:
    home: Optional[Path]
    agents_dir: Optional[Path]
    enabled: Tuple[BundledAgent, ...]
    disabled: Tuple[BundledAgent, ...]
    warnings: List[str]
    refusal: Optional[str] = None


def _context(project_dir: Path) -> _Context:
    home = skills.skills_home(project_dir)
    if home is None:
        refusal = skills.project_skills_dir(project_dir).refusal
        return _Context(None, None, (), (), [], refusal)
    enabled, warnings = enabled_agents(home)
    names = {a.name for a in enabled}
    disabled = tuple(a for a in bundled_agents() if a.name not in names)
    return _Context(home, home / ".claude" / "agents", enabled, disabled, warnings)


def _symlinked(home: Path) -> Optional[Path]:
    for path in (home / ".claude", home / ".claude" / "agents"):
        if path.is_symlink():
            return path
    return None


def _history(name: str) -> Dict[str, str]:
    """`{digest: release}` for `name` from the ledger's agents section."""
    return skills.load_history(HISTORY_SECTION).get(name, {})


def _disabled_statuses(ctx: _Context) -> List[AgentStatus]:
    out = []
    for agent in ctx.disabled:
        dest = ctx.agents_dir / f"{agent.name}.md"  # type: ignore[operator]
        if dest.exists() or dest.is_symlink():
            out.append(
                AgentStatus(agent.name, DISABLED, None, KEPT, "disabled by agents.enabled; kept")
            )
    return out


def inspect_project_agents(project_dir: Path) -> AgentsReport:
    """Classify every enabled agent in a project. Read-only."""
    ctx = _context(Path(project_dir))
    if ctx.refusal is not None:
        return AgentsReport(Path(project_dir), notice=ctx.refusal)
    assert ctx.home is not None and ctx.agents_dir is not None
    loaded = skills.load_manifest(ctx.home / ".agents" / "skills")
    running = skills.running_release()
    statuses = [
        classify_agent(
            a,
            ctx.agents_dir / f"{a.name}.md",
            loaded.agents.get(a.name),
            _history(a.name),
            running,
        )
        for a in ctx.enabled
    ]
    statuses += _disabled_statuses(ctx)
    warnings = list(ctx.warnings)
    note = skills._manifest_warning(loaded.state, writing=False)
    if note:
        warnings.append(note)
    return AgentsReport(ctx.agents_dir, tuple(statuses), warnings, None, loaded.state)


# ----------------------------------------------------------------------- writing


def _write_agent(
    agent: BundledAgent,
    dest: Path,
    tracker: "Optional[TransactionalTracker]",
) -> None:
    """Atomically put the bundled bytes at `dest`; the previous file survives any failure."""
    data = agent.path.read_bytes()
    want = _sha256(data)
    existed = dest.exists() or dest.is_symlink()
    skills._ensure_target(dest.parent, tracker)
    # mkstemp: an unpredictable name opened O_EXCL, so a pre-placed symlink cannot
    # redirect the write; the hash is re-read through the same descriptor, not the path.
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=f".{agent.name}.", suffix=TEMP_SUFFIX)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w+b") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o644)
            handle.seek(0)
            if _sha256(handle.read()) != want:
                raise OSError("staged agent file does not match the bundle")
        if tracker is not None and existed and dest.is_file() and not dest.is_symlink():
            tracker.record_modified_file(dest)
        os.replace(tmp, dest)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise MetaProjectError(f"could not write agent {agent.name}: {exc}") from exc
    if tracker is not None and not existed:
        tracker.record_created_file(dest)


def sync_project_agents(
    project_dir: Path,
    *,
    update: bool = True,
    force: Sequence[str] = (),
    dry_run: bool = False,
    tracker: "Optional[TransactionalTracker]" = None,
    only: Optional[Sequence[str]] = None,
) -> AgentsReport:
    """Install missing agents and, with `update`, replace outdated unmodified ones.

    `only` limits the pass to those enabled agent names (`backfill` with named files
    touches exactly the named files); None means every enabled agent.

    Modified agents are kept unless named in `force`. Disabled agents and files this
    module does not bundle are never touched. The manifest's `agents` section records
    every agent written or found current. Raises `MetaProjectError` for an unknown
    `force` name (before any write), for a manifest from a newer metaproject when
    `update` is set, and for an I/O failure after cleaning up the temp file.
    """
    project_dir = Path(project_dir)
    ctx = _context(project_dir)
    if ctx.refusal is not None:
        return AgentsReport(project_dir, notice=ctx.refusal)
    assert ctx.home is not None and ctx.agents_dir is not None

    names = {a.name for a in bundled_agents()}
    unknown = sorted(set(force) - names)
    if unknown:
        raise MetaProjectError(
            "unknown agent name(s) for --force: "
            + ", ".join(unknown)
            + f" (bundled: {', '.join(sorted(names))})"
        )

    skills_dir = ctx.home / ".agents" / "skills"
    loaded = skills.load_manifest(skills_dir)
    if loaded.state == MANIFEST_NEWER and update:
        raise MetaProjectError(
            f"{skills.manifest_path(skills_dir)} was written by a newer metaproject; upgrade "
            "metaproject before syncing agents (the file was left untouched)."
        )
    running = skills.running_release()
    warnings = list(ctx.warnings)
    note = skills._manifest_warning(loaded.state, writing=not dry_run)
    if note:
        warnings.append(note)

    blocked = _symlinked(ctx.home)
    if blocked is not None:
        warnings.append(f"{blocked} is a symlink; agents were not written.")
    writable = not dry_run and blocked is None

    new_agents: Dict[str, Dict] = {n: dict(e) for n, e in loaded.agents.items()}
    forced = set(force)
    statuses: List[AgentStatus] = []
    try:
        for agent in ctx.enabled:
            if only is not None and agent.name not in only:
                continue
            dest = ctx.agents_dir / f"{agent.name}.md"
            status = classify_agent(
                agent, dest, loaded.agents.get(agent.name), _history(agent.name), running
            )
            digest = _sha256(agent.path.read_bytes())
            if status.state == MISSING:
                action = INSTALLED
            elif agent.name in forced and status.state != CURRENT:
                action = FORCED
            elif status.state == OUTDATED and update:
                action = UPDATED
            elif status.state == CURRENT:
                entry = loaded.agents.get(agent.name) or {}
                action = KEPT if entry.get("sha256") == digest else RECORDED
            else:
                action = KEPT
            if blocked is not None and action in (INSTALLED, UPDATED, FORCED):
                action = KEPT
            if action in (INSTALLED, UPDATED, FORCED) and writable:
                _write_agent(agent, dest, tracker)
            if action in (INSTALLED, UPDATED, FORCED, RECORDED):
                new_agents[agent.name] = {"release": running, "sha256": digest}
            statuses.append(replace(status, action=action))
    finally:
        if writable and loaded.state != MANIFEST_NEWER and new_agents != loaded.agents:
            if new_agents or skills.manifest_path(skills_dir).exists():
                if not skills_dir.exists():
                    skills._ensure_target(skills_dir, tracker)
                skills._write_manifest(
                    skills_dir,
                    Manifest(MANIFEST_PRESENT, loaded.skills, loaded.bridges, new_agents),
                    tracker,
                )
    statuses += _disabled_statuses(ctx)
    return AgentsReport(ctx.agents_dir, tuple(statuses), warnings, None, loaded.state)


def install_project_agents(
    project_dir: Path,
    dry_run: bool = False,
    tracker: "Optional[TransactionalTracker]" = None,
    only: Optional[Sequence[str]] = None,
) -> AgentsReport:
    """Install missing agents only (`new`, `backfill`, `adopt`); never replaces a file."""
    return sync_project_agents(
        project_dir, update=False, dry_run=dry_run, tracker=tracker, only=only
    )
