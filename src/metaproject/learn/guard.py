"""Egress guard for the `learn` pipeline (spec.md §5.4.1 stage 2, §7.4).

Nothing leaves the machine that this module has not seen. It answers three questions,
in order:

1. May this path be sent at all?  `.gitignore` match, hard denylist, binary sniff.
2. What must be removed from the text that survives?  Known token shapes, secret-shaped
   assignments, and high-entropy strings.
3. What exactly would be sent?  The send manifest, confirmed once per session.

The guard is deliberately implemented and tested before any model code exists (plan.md
risk R1). It is stdlib-only and involves no model.

Two rules deserve explanation because they are the difference between a guard that
works and one that merely looks strict:

*`.gitignore` is parsed, not delegated.* Not every scanned directory is a git
repository, so shelling out to `git check-ignore` would silently stop protecting plain
directories (acceptance case C24).

*The denylist is split hard/soft.* `.env*`, `*.pem`, `*.key` and `id_*` are excluded on
name alone. `*credentials*` and `*secret*` also match ordinary documentation about
handling secrets — a `secrets.md` that explains the policy is exactly the kind of
content `learn` exists to find — so for documentation files those patterns exclude only
when the content actually carries something credential-shaped (acceptance case C20).
Over-redaction destroys the signal; it is not a safe default.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from metaproject.learn.collect import EvidenceRecord

REDACTION_PLACEHOLDER = "[REDACTED]"

# spec.md §7.4: excluded on filename alone, regardless of content or .gitignore.
HARD_DENYLIST = (".env", ".env.*", "*.pem", "*.key", "id_*")

# spec.md §7.4: excluded too, but a documentation file bearing no credential survives.
SOFT_DENYLIST = ("*credentials*", "*secret*")

DOCUMENT_SUFFIXES = frozenset({".md", ".rst", ".txt", ".adoc"})

ENTROPY_MIN_LENGTH = 32
ENTROPY_THRESHOLD = 4.2

_HEX_RE = re.compile(r"[0-9a-fA-F]+")
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_TOKEN_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+/=_-]{%d,}" % ENTROPY_MIN_LENGTH)

_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN[^\n]*PRIVATE KEY-----.*?-----END[^\n]*PRIVATE KEY-----",
    re.DOTALL,
)

_SECRET_KEY_WORDS = (
    r"(?:secret|token|passwd|password|pwd|api[_-]?key|apikey|access[_-]?key|"
    r"private[_-]?key|credentials?|auth[_-]?token)"
)
_ASSIGNMENT_RE = re.compile(
    rf"(?i)\b([A-Za-z0-9_.\-]*{_SECRET_KEY_WORDS}[A-Za-z0-9_.\-]*)(\s*[:=]\s*)([^\s'\"]+)"
)

_TOKEN_SHAPE_RES = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{16,}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
)


# --------------------------------------------------------------------------- .gitignore


def _translate(pattern: str) -> str:
    """Translate one gitignore glob into a regular expression anchored at both ends."""
    out: List[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        char = pattern[i]
        if char == "*":
            if pattern[i : i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
                continue
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
        elif char == "?":
            out.append("[^/]")
            i += 1
        elif char == "[":
            j = i + 1
            if j < n and pattern[j] in "!^":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape("["))
                i += 1
            else:
                inner = pattern[i + 1 : j]
                if inner.startswith("!"):
                    inner = "^" + inner[1:]
                out.append(f"[{inner}]")
                i = j + 1
        else:
            out.append(re.escape(char))
            i += 1
    return "^" + "".join(out) + "$"


@dataclass(frozen=True)
class _Rule:
    """One compiled gitignore pattern."""

    regex: re.Pattern
    negated: bool
    dir_only: bool
    anchored: bool


class GitignoreMatcher:
    """A dependency-free `.gitignore` matcher.

    Supports the subset git users actually write: comments, blank lines, negation,
    directory-only patterns, leading-slash anchoring, character classes, `*` (which
    does not cross a separator) and `**`.
    """

    def __init__(self, patterns: Iterable[str]) -> None:
        self.rules: List[_Rule] = []
        for raw in patterns:
            rule = self._compile(raw)
            if rule is not None:
                self.rules.append(rule)

    @staticmethod
    def _compile(raw: str) -> Optional[_Rule]:
        pattern = raw.rstrip()
        if not pattern or pattern.lstrip().startswith("#"):
            return None

        negated = pattern.startswith("!")
        if negated:
            pattern = pattern[1:]

        dir_only = pattern.endswith("/")
        if dir_only:
            pattern = pattern[:-1]
        if not pattern:
            return None

        anchored = pattern.startswith("/") or "/" in pattern
        pattern = pattern.lstrip("/")
        if not pattern:
            return None

        return _Rule(
            regex=re.compile(_translate(pattern)),
            negated=negated,
            dir_only=dir_only,
            anchored=anchored,
        )

    @classmethod
    def from_project(cls, project_dir: Path) -> "GitignoreMatcher":
        """Read a project's root `.gitignore`, with no git repository required."""
        ignore_file = Path(project_dir) / ".gitignore"
        if not ignore_file.is_file():
            return cls([])
        try:
            text = ignore_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return cls([])
        return cls(text.splitlines())

    def match(self, rel_path: str, is_dir: bool = False) -> bool:
        """Report whether a project-relative path is ignored."""
        parts = PurePosixPath(rel_path).parts
        if not parts:
            return False

        ignored = False
        for rule in self.rules:
            if self._matches(rule, parts, is_dir):
                ignored = not rule.negated
        return ignored

    @staticmethod
    def _matches(rule: _Rule, parts: Sequence[str], is_dir: bool) -> bool:
        total = len(parts)
        # Anchored patterns match the path or one of its ancestors; unanchored ones may
        # also match any interior run of components, as git's basename rule allows.
        starts = (0,) if rule.anchored else range(total)
        for start in starts:
            for end in range(start + 1, total + 1):
                if rule.dir_only and end == total and not is_dir:
                    continue
                if rule.regex.match("/".join(parts[start:end])):
                    return True
        return False


# --------------------------------------------------------------------------- redaction


def _shannon_entropy(value: str) -> float:
    """Shannon entropy in bits per character."""
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def _looks_like_a_secret(token: str) -> bool:
    """Decide whether a long opaque token is credential-shaped rather than content.

    Git SHAs, UUIDs, and short base64 test vectors are all high-entropy and all
    legitimate; excluding them is what keeps redaction precise (acceptance case C20).
    """
    if len(token) < ENTROPY_MIN_LENGTH:
        return False
    if _HEX_RE.fullmatch(token) or _UUID_RE.fullmatch(token):
        return False
    if not (any(c.isdigit() for c in token) and any(c.isalpha() for c in token)):
        return False
    return _shannon_entropy(token) >= ENTROPY_THRESHOLD


def redact(text: str) -> str:
    """Remove credentials from text bound for the model, preserving everything else."""
    if not text:
        return text

    redacted = _PRIVATE_KEY_RE.sub(REDACTION_PLACEHOLDER, text)

    for shape in _TOKEN_SHAPE_RES:
        redacted = shape.sub(REDACTION_PLACEHOLDER, redacted)

    redacted = _ASSIGNMENT_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{REDACTION_PLACEHOLDER}", redacted
    )

    return _TOKEN_CANDIDATE_RE.sub(
        lambda m: REDACTION_PLACEHOLDER if _looks_like_a_secret(m.group(0)) else m.group(0),
        redacted,
    )


def contains_secret(text: str) -> bool:
    """Predicate form of `redact`: does this text carry anything credential-shaped?"""
    return redact(text) != text


# --------------------------------------------------------------------------- exclusion


def _fnmatch(name: str, pattern: str) -> bool:
    return re.compile(_translate(pattern)).match(name) is not None


def is_denylisted(rel_path: str, content: Optional[str] = None) -> bool:
    """Report whether a path is denylisted by spec.md §7.4.

    `content`, when supplied, is used only to spare documentation files that match a
    soft pattern but carry no credential.
    """
    name = PurePosixPath(rel_path).name
    if any(_fnmatch(name, pattern) for pattern in HARD_DENYLIST):
        return True
    if not any(_fnmatch(name, pattern) for pattern in SOFT_DENYLIST):
        return False
    if content is None:
        return True
    if PurePosixPath(name).suffix.lower() not in DOCUMENT_SUFFIXES:
        return True
    return contains_secret(content)


def _is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return b"\x00" in handle.read(8192)
    except OSError:
        return False


def exclusion_reason(
    project_dir: Path,
    rel_path: str,
    matcher: Optional[GitignoreMatcher] = None,
) -> Optional[str]:
    """Return why a project-relative path must not be sent, or None if it may be.

    Order matters for auditability: the cheapest, most explicit reason wins, so an
    operator reading the manifest sees `gitignore` for a path the project itself
    already excludes rather than an incidental denylist match.
    """
    project_dir = Path(project_dir)
    path = project_dir / rel_path

    if matcher is None:
        matcher = GitignoreMatcher.from_project(project_dir)
    if matcher.match(rel_path, is_dir=path.is_dir()):
        return "gitignore"

    if _hard_denied(rel_path):
        return "denylist"

    if path.is_file() and _is_binary(path):
        return "binary"

    content: Optional[str] = None
    if path.is_file():
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = None
    if is_denylisted(rel_path, content=content):
        return "denylist"

    return None


def _hard_denied(rel_path: str) -> bool:
    name = PurePosixPath(rel_path).name
    return any(_fnmatch(name, pattern) for pattern in HARD_DENYLIST)


def filter_paths(
    project_dir: Path,
    rel_paths: Sequence[str],
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Split project-relative paths into those that may be sent and those that may not."""
    matcher = GitignoreMatcher.from_project(Path(project_dir))
    kept: List[str] = []
    excluded: List[Tuple[str, str]] = []
    for rel in rel_paths:
        reason = exclusion_reason(project_dir, rel, matcher=matcher)
        if reason:
            excluded.append((rel, reason))
        else:
            kept.append(rel)
    return kept, excluded


# --------------------------------------------------------------------------- manifest


@dataclass(frozen=True)
class ManifestEntry:
    """One unit of evidence that would be sent to the model."""

    project_name: str
    project_path: str
    target_file: str
    kind: str
    added_lines: int
    size_bytes: int


@dataclass(frozen=True)
class ExcludedEntry:
    """One path the guard refused to send, and why."""

    project_path: str
    path: str
    reason: str


@dataclass(frozen=True)
class SendManifest:
    """Exactly what would leave the machine, and what was withheld."""

    entries: Tuple[ManifestEntry, ...]
    excluded: Tuple[ExcludedEntry, ...]

    @property
    def total_bytes(self) -> int:
        """Total redacted diff bytes across every entry."""
        return sum(entry.size_bytes for entry in self.entries)

    def render(self) -> str:
        """Render the manifest for operator confirmation."""
        lines = [
            f"Send manifest: {len(self.entries)} diffs, {self.total_bytes} bytes "
            "(redacted diffs only, never whole files)",
        ]
        for entry in sorted(self.entries, key=lambda e: (e.project_name, e.target_file)):
            lines.append(
                f"  {entry.project_name}  {entry.target_file}  "
                f"[{entry.kind}] +{entry.added_lines} lines, {entry.size_bytes} B"
            )
        if self.excluded:
            lines.append(f"Withheld: {len(self.excluded)} paths")
            for item in sorted(self.excluded, key=lambda e: (e.project_path, e.path)):
                lines.append(f"  {Path(item.project_path).name}  {item.path}  ({item.reason})")
        return "\n".join(lines)


def build_manifest(
    records: Sequence[EvidenceRecord],
    excluded: Sequence[Tuple[str, str, str]],
) -> SendManifest:
    """Build the send manifest from guarded evidence and the paths that were withheld."""
    entries = tuple(
        ManifestEntry(
            project_name=record.project_name,
            project_path=record.project_path,
            target_file=record.target_file,
            kind=record.kind,
            added_lines=len(record.added_lines),
            size_bytes=len(record.diff.encode("utf-8")),
        )
        for record in records
    )
    withheld = tuple(
        ExcludedEntry(project_path=project_path, path=path, reason=reason)
        for project_path, path, reason in excluded
    )
    return SendManifest(entries=entries, excluded=withheld)


@dataclass(frozen=True)
class GuardResult:
    """Redacted evidence, the paths withheld, and the manifest describing both."""

    records: Tuple[EvidenceRecord, ...]
    excluded: Tuple[Tuple[str, str, str], ...]
    manifest: SendManifest


def guard_evidence(records: Sequence[EvidenceRecord]) -> GuardResult:
    """Filter and redact collected evidence, and describe exactly what survives.

    Path exclusion is re-checked here rather than trusted from the collector: this is
    the single place every byte passes through before egress, so it is the place the
    guarantee belongs.
    """
    matchers: Dict[str, GitignoreMatcher] = {}
    kept: List[EvidenceRecord] = []
    excluded: List[Tuple[str, str, str]] = []

    for record in records:
        project_path = record.project_path
        if project_path not in matchers:
            matchers[project_path] = GitignoreMatcher.from_project(Path(project_path))
        reason = exclusion_reason(
            Path(project_path), record.target_file, matcher=matchers[project_path]
        )
        if reason:
            excluded.append((project_path, record.target_file, reason))
            continue
        kept.append(
            replace(
                record,
                diff=redact(record.diff),
                added_lines=tuple(redact(line) for line in record.added_lines),
            )
        )

    return GuardResult(
        records=tuple(kept),
        excluded=tuple(excluded),
        manifest=build_manifest(kept, excluded),
    )


def _default_confirm(prompt: str) -> bool:
    """Ask on the terminal without pulling in a prompt library."""
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")


def _ask_to_send(
    prompt_text: str,
    assume_yes: bool = False,
    confirm_fn: Optional[Callable[[str], bool]] = None,
) -> bool:
    """Ask once, unless `--yes` bypasses the prompt entirely."""
    if assume_yes:
        return True
    ask = confirm_fn or _default_confirm
    return bool(ask(prompt_text))


def confirm_send(
    manifest: SendManifest,
    assume_yes: bool = False,
    confirm_fn: Optional[Callable[[str], bool]] = None,
) -> bool:
    """Show the manifest and ask whether to proceed. `--yes` bypasses the prompt.

    Callers are responsible for asking only once per session (spec.md §7.4); this
    function does not remember, so that a refusal is never cached into an approval.
    """
    return _ask_to_send(f"{manifest.render()}\nSend this to the model?", assume_yes, confirm_fn)


def confirm_file_send(
    target_file: str,
    manifest: SendManifest,
    assume_yes: bool = False,
    confirm_fn: Optional[Callable[[str], bool]] = None,
) -> bool:
    """Show one target file's slice of the manifest and ask whether to send it.

    The per-file counterpart to `confirm_send`: same manifest rendering, same `--yes`
    bypass, but scoped to one bundle and asked once per file instead of once per run.
    """
    return _ask_to_send(
        f"{manifest.render()}\nSend `{target_file}` to the model?", assume_yes, confirm_fn
    )
