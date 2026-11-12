"""Claude Code hooks: the `.claude/settings.json` deliverable and its bundled hook script.

`.claude/settings.json` is the one deliverable that is *merged*, never rendered or
overwritten (DeliverableClass.SETTINGS). The operator's settings file is theirs: every
key in it is preserved, and metaproject only ever adds hook entries to
`hooks.<Event>[]`. Each entry is keyed by its `command` string, so a second run finds
the entry already present and writes nothing (idempotent). An existing file that is not
valid JSON — or whose `hooks` is not the shape Claude Code expects — is refused and
reported, never rewritten.

`merge_hooks(settings_path, entries)` is the single write path for hook entries; a later
hook (e.g. a `SessionStart` entry) is added by passing one more `HookEntry` through it.

The hooks themselves run the bundled script `.claude/hooks/metaproject_hook.py`, copied
into the project create-only (an existing copy is never written into, only compared,
like the project skills). It is stdlib-only Python and reads `.metaproject.json` at run
time, so a project's lint command can change without re-running metaproject:

- `post-edit` (PostToolUse, `Edit|Write`) runs `commands.lint` then
  `commands.typecheck`; silent and exit 0 when neither is configured or both pass.
- `pre-bash` (PreToolUse, `Bash`) stops stale listeners on `e2e_port` before a command
  that mentions playwright; always exit 0.
"""

import filecmp
import importlib.resources
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

from metaproject.exceptions import MetaProjectError

if TYPE_CHECKING:
    from metaproject.scaffold import TransactionalTracker

SETTINGS_PATH = ".claude/settings.json"
HOOK_SCRIPT_PATH = ".claude/hooks/metaproject_hook.py"
_BUNDLED_SCRIPT = "metaproject_hook.py"

# Script states, mirroring the project-skill install states.
INSTALLED = "installed"
CURRENT = "current"
STALE = "stale"
MISSING = "missing"


class SettingsError(MetaProjectError):
    """An existing settings file that cannot be merged into without losing content."""


class HooksWriteDenied(SettingsError):
    """The hooks could not be written at all (e.g. Claude Code's `.claude/` protection).

    Not a defect in the project: the operator installs them by running `backfill`
    themselves, so a default-mode backfill reports it as a notice, not a refusal.
    """


@dataclass(frozen=True)
class HookEntry:
    """One hook metaproject owns: an event, an optional tool matcher, and a command.

    The `command` string is the identity of the entry — two entries with the same command
    under the same event are the same hook, whatever their matcher or timeout.
    """

    event: str
    command: str
    matcher: Optional[str] = None
    timeout: Optional[int] = None

    def as_group(self) -> Dict[str, Any]:
        """The `hooks.<event>[]` element Claude Code reads for this entry."""
        hook: Dict[str, Any] = {"type": "command", "command": self.command}
        if self.timeout is not None:
            hook["timeout"] = self.timeout
        group: Dict[str, Any] = {}
        if self.matcher is not None:
            group["matcher"] = self.matcher
        group["hooks"] = [hook]
        return group


def _script_command(mode: str) -> str:
    """The hook command: a no-op (exit 0) when the script file is absent.

    Without the guard, `python3 <missing file>` exits 2, and exit 2 from a PreToolUse
    hook blocks the tool call — so a deleted, gitignored or not-yet-checked-out script
    would block every Bash call. The string is the entry's identity; never change it
    casually, or re-runs add a second entry beside the old one.
    """
    return f'f="$CLAUDE_PROJECT_DIR/{HOOK_SCRIPT_PATH}"; [ -f "$f" ] || exit 0; python3 "$f" {mode}'


POST_EDIT_HOOK = HookEntry(
    event="PostToolUse", matcher="Edit|Write", command=_script_command("post-edit"), timeout=150
)
PRE_BASH_HOOK = HookEntry(
    event="PreToolUse", matcher="Bash", command=_script_command("pre-bash"), timeout=15
)


def project_hook_entries() -> Tuple[HookEntry, ...]:
    """The hook entries every scaffolded project carries."""
    return (POST_EDIT_HOOK, PRE_BASH_HOOK)


# ----------------------------------------------------------------------- settings merge


def _load_settings(settings_path: Path) -> Dict[str, Any]:
    """The parsed settings object; `{}` when the file is absent. Raises `SettingsError`."""
    path = Path(settings_path)
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SettingsError(f"{path} could not be read ({exc}); it was left untouched.") from exc
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SettingsError(
            f"{path} is not valid JSON ({exc.msg}, line {exc.lineno}); it was left untouched. "
            "Fix it and run `metaproject backfill` to add the metaproject hooks."
        ) from exc
    if not isinstance(data, dict):
        raise SettingsError(f"{path} is not a JSON object; it was left untouched.")
    hooks = data.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        raise SettingsError(f'{path}: "hooks" is not an object; it was left untouched.')
    for event, groups in (hooks or {}).items():
        if not isinstance(groups, list):
            raise SettingsError(f'{path}: "hooks.{event}" is not a list; it was left untouched.')
    return data


def _has_command(groups: Sequence[Any], command: str) -> bool:
    for group in groups:
        if not isinstance(group, dict):
            continue
        for hook in group.get("hooks") or []:
            if isinstance(hook, dict) and hook.get("command") == command:
                return True
    return False


def missing_hooks(settings_path: Path, entries: Sequence[HookEntry]) -> List[HookEntry]:
    """The entries not yet present in `settings_path`. Read-only; raises `SettingsError`."""
    hooks = _load_settings(settings_path).get("hooks") or {}
    return [
        entry for entry in entries if not _has_command(hooks.get(entry.event, []), entry.command)
    ]


def merge_hooks(
    settings_path: Path, entries: Sequence[HookEntry], dry_run: bool = False
) -> List[HookEntry]:
    """Add every entry not already present to `settings_path`; return those added.

    Merge, never overwrite: the existing object is loaded, each absent entry is appended
    as its own group under `hooks.<event>`, and every other key — including the
    operator's own hooks, in their order — is written back unchanged. Nothing is written
    when nothing is missing, so a re-run leaves the file byte-for-byte as it was. An
    absent file is created. Raises `SettingsError` (and writes nothing) for a file that is
    not a JSON object with an object-of-lists `hooks`.
    """
    path = Path(settings_path)
    data = _load_settings(path)
    hooks = data.get("hooks") or {}
    added: List[HookEntry] = []
    for entry in entries:
        groups = hooks.setdefault(entry.event, [])
        if _has_command(groups, entry.command):
            continue
        groups.append(entry.as_group())
        added.append(entry)
    if added and not dry_run:
        data["hooks"] = hooks
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return added


# --------------------------------------------------------------------- project config


@dataclass(frozen=True)
class HookConfig:
    """The hook settings a project declares in `.metaproject.json` (all optional).

    `{"commands": {"lint": "make lint", "typecheck": "..."}, "e2e_port": 4173}`. The hook
    script reads the same keys itself at run time; this is metaproject's own view of them.
    """

    lint: Optional[str] = None
    typecheck: Optional[str] = None
    e2e_port: Optional[int] = None

    @property
    def has_commands(self) -> bool:
        return bool(self.lint or self.typecheck)


def read_hook_config(project_dir: Path) -> HookConfig:
    """Read `commands.lint`, `commands.typecheck` and `e2e_port`. Tolerant: never raises."""
    from metaproject.identity import IDENTITY_FILE

    try:
        data = json.loads((Path(project_dir) / IDENTITY_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return HookConfig()
    if not isinstance(data, dict):
        return HookConfig()
    commands = data.get("commands") if isinstance(data.get("commands"), dict) else {}

    def command(key: str) -> Optional[str]:
        value = commands.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    port = data.get("e2e_port")
    if isinstance(port, str) and port.strip().isdigit():
        port = int(port.strip())
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
        port = None
    return HookConfig(lint=command("lint"), typecheck=command("typecheck"), e2e_port=port)


# -------------------------------------------------------------------------- hook script


def get_bundled_hook_script() -> Path:
    """The hook script shipped inside this package."""
    try:
        return Path(
            str(importlib.resources.files("metaproject").joinpath("hook_scripts", _BUNDLED_SCRIPT))
        )
    except Exception as exc:
        raise MetaProjectError(f"Failed to access the bundled hook script: {exc}") from exc


def hook_script_state(project_dir: Path) -> str:
    """`missing`, `current` (byte-identical to the bundled copy) or `stale`."""
    dest = Path(project_dir) / HOOK_SCRIPT_PATH
    if not dest.exists() and not dest.is_symlink():
        return MISSING
    if dest.is_file() and filecmp.cmp(get_bundled_hook_script(), dest, shallow=False):
        return CURRENT
    return STALE


# ------------------------------------------------------------------------- installation


@dataclass(frozen=True)
class HooksReport:
    """What one install pass did, or would do under `dry_run`."""

    script: str = MISSING
    added: List[HookEntry] = field(default_factory=list)
    settings_created: bool = False
    notice: Optional[str] = None
    # True when `notice` is a write failure (sandbox/permissions), not unmergeable JSON.
    write_denied: bool = False

    @property
    def wrote(self) -> bool:
        return self.script == INSTALLED or bool(self.added)


def hooks_installed(project_dir: Path) -> bool:
    """Is the hook script present and every project hook entry merged? Never raises."""
    if hook_script_state(project_dir) == MISSING:
        return False
    try:
        return not missing_hooks(Path(project_dir) / SETTINGS_PATH, project_hook_entries())
    except SettingsError:
        return False


def settings_problem(project_dir: Path) -> Optional[str]:
    """Why the settings file cannot be merged into, or None when it can (or is absent)."""
    try:
        _load_settings(Path(project_dir) / SETTINGS_PATH)
    except SettingsError as exc:
        return str(exc)
    return None


def install_hooks(
    project_dir: Path,
    dry_run: bool = False,
    tracker: "Optional[TransactionalTracker]" = None,
    entries: Optional[Sequence[HookEntry]] = None,
) -> HooksReport:
    """Copy the hook script (create-only) and merge the hook entries into settings.json.

    An unmergeable settings file is checked *first*, so a refusal writes nothing at all —
    not even the script — and comes back as `notice`. Paths created are recorded on
    `tracker`, and an existing settings file is snapshotted there before it is merged
    into, so a failed `new` restores it byte-for-byte.
    """
    project_dir = Path(project_dir)
    settings_path = project_dir / SETTINGS_PATH
    wanted = tuple(entries) if entries is not None else project_hook_entries()

    try:
        pending = missing_hooks(settings_path, wanted)
    except SettingsError as exc:
        return HooksReport(script=hook_script_state(project_dir), notice=str(exc))

    script = hook_script_state(project_dir)
    created = not settings_path.exists()
    try:
        if script == MISSING:
            if not dry_run:
                _copy_script(project_dir, tracker)
            script = INSTALLED

        if pending and not dry_run:
            if tracker is not None:
                if created:
                    _make_parents(settings_path, tracker)
                else:
                    tracker.record_modified_file(settings_path)
            merge_hooks(settings_path, pending)
            if tracker is not None and created:
                tracker.record_created_file(settings_path)
    except OSError as exc:
        # Claude Code's sandbox can deny the agent it runs writes to `.claude/settings.json`
        # and `.claude/hooks/`, so an agent-driven backfill lands here: report, never crash.
        return HooksReport(
            script=hook_script_state(project_dir),
            write_denied=True,
            notice=(
                f"Could not write the metaproject hooks ({exc}). Claude Code's sandbox can "
                "deny agents writes to .claude/settings.json and .claude/hooks; run "
                "`metaproject backfill` yourself to install them."
            ),
        )

    return HooksReport(
        script=script, added=list(pending), settings_created=created and bool(pending)
    )


def _make_parents(path: Path, tracker: "Optional[TransactionalTracker]") -> None:
    for parent in reversed(path.parents):
        if not parent.exists():
            parent.mkdir()
            if tracker is not None:
                tracker.record_created_dir(parent)


def _copy_script(project_dir: Path, tracker: "Optional[TransactionalTracker]") -> None:
    dest = project_dir / HOOK_SCRIPT_PATH
    _make_parents(dest, tracker)
    if tracker is not None:
        tracker.record_created_file(dest)
    shutil.copyfile(get_bundled_hook_script(), dest)
    dest.chmod(0o755)
