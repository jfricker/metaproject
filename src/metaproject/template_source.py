"""Which template store a project renders from, and the optional `templates.source`.

A Claude Code on the web container starts with no `~/.metaproject/templates`, so
without help every web session renders the bundled defaults and `review` then reports
drift against the operator's customised store that is not real. A project can declare
where its store lives in `.metaproject.json`:

    {"templates": {"source": "https://github.com/me/templates.git"}}
    {"templates": {"source": {"url": "git@github.com:me/templates.git", "ref": "v3",
                              "subdir": "templates"}}}
    {"templates": {"source": "tools/templates"}}           # a path in the repository
    {"templates": {"source": {"path": "tools/templates"}}}

`resolve_templates` is the single answer to "which store?", in this order:

1. an explicit `--templates` directory;
2. the configured store (`config.templates_dir`, default `~/.metaproject/templates`)
   when it exists and is not empty — a declared source never shadows a local store;
3. the declared `templates.source`: a repository path is used in place; a git source
   is shallow-fetched once into a cache under the config directory
   (`<config dir>/cache/templates/`) and reused from there without the network;
4. the bundled templates — also the fallback whenever a declared source is malformed,
   missing or cannot be fetched (offline), so a source never turns into a failure.

`fetch_template_source` refreshes a git source's cache (`metaproject templates fetch`,
which the web SessionStart script runs). Every git call is non-interactive
(`GIT_TERMINAL_PROMPT=0`), bounded by a timeout, and acts only on the cache directory,
never on the project's own repository.
"""

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from metaproject.config import Config, get_config_dir, load_config
from metaproject.exceptions import MetaProjectError

ORIGIN_EXPLICIT = "explicit"
ORIGIN_STORE = "store"
ORIGIN_SOURCE = "source"
ORIGIN_BUNDLED = "bundled"

GIT_TIMEOUT_SECONDS = 120

# Git transports a declared source may use. `ext::` (runs a command) and anything else
# exotic is refused: `.metaproject.json` arrives with the repository, so its contents
# are data, never a way to run something.
_URL_SCHEMES = ("https://", "http://", "ssh://", "git://", "file://")
_SCP_LIKE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[^:]")
_REF = re.compile(r"^[A-Za-z0-9._/+-]+$")

# Variables that would point git at another repository than the cache directory.
_GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
)

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class TemplateSourceError(MetaProjectError):
    """A `templates.source` declaration that cannot be used as written."""


@dataclass(frozen=True)
class TemplateSource:
    """A declared template store: a git repository (`url`, `ref`, `subdir`) or a path."""

    kind: str  # "git" or "path"
    location: str
    ref: Optional[str] = None
    subdir: Optional[str] = None

    @property
    def label(self) -> str:
        if self.kind == "path":
            return self.location
        text = self.location + (f"@{self.ref}" if self.ref else "")
        return text + (f" ({self.subdir})" if self.subdir else "")


@dataclass(frozen=True)
class TemplateResolution:
    """The store a command renders from, and why it was chosen."""

    path: Path
    origin: str
    detail: str
    # True when the project declares `templates.source`, whether or not it was used.
    source_declared: bool = False

    def describe(self) -> str:
        return f"Templates: {self.detail}"


@dataclass(frozen=True)
class FetchResult:
    """One fetch of a git source: the usable store path, or why there is none."""

    ok: bool
    path: Optional[Path]
    message: str


# ----------------------------------------------------------------------- declaration


def _looks_like_git_url(text: str) -> bool:
    return text.startswith(_URL_SCHEMES) or bool(_SCP_LIKE.match(text)) or text.endswith(".git")


def _validate_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise TemplateSourceError("templates.source has an empty url")
    if url.startswith("-") or not (url.startswith(_URL_SCHEMES) or _SCP_LIKE.match(url)):
        raise TemplateSourceError(
            f"templates.source url {url!r} is not an https, http, ssh, git or file URL "
            "(or user@host:path)"
        )
    return url


def _validate_ref(ref: Any) -> Optional[str]:
    if ref is None or (isinstance(ref, str) and not ref.strip()):
        return None
    if not isinstance(ref, str) or ref.strip().startswith("-") or not _REF.match(ref.strip()):
        raise TemplateSourceError(f"templates.source ref {ref!r} is not a branch, tag or commit")
    return ref.strip()


def _validate_subdir(subdir: Any) -> Optional[str]:
    if subdir is None or (isinstance(subdir, str) and not subdir.strip()):
        return None
    if not isinstance(subdir, str):
        raise TemplateSourceError("templates.source subdir must be a string")
    clean = subdir.strip().strip("/")
    if Path(clean).is_absolute() or ".." in Path(clean).parts:
        raise TemplateSourceError(f"templates.source subdir {subdir!r} must stay inside the repo")
    return clean


def parse_template_source(value: Any) -> TemplateSource:
    """Parse a `templates.source` value. Raises `TemplateSourceError` when malformed."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise TemplateSourceError("templates.source is empty")
        if _looks_like_git_url(text):
            return TemplateSource(kind="git", location=_validate_url(text))
        return TemplateSource(kind="path", location=text)
    if isinstance(value, dict):
        url = value.get("url", value.get("git"))
        path = value.get("path")
        if url is not None and path is not None:
            raise TemplateSourceError("templates.source names both a url and a path")
        if isinstance(path, str) and path.strip():
            return TemplateSource(kind="path", location=path.strip())
        if isinstance(url, str):
            return TemplateSource(
                kind="git",
                location=_validate_url(url),
                ref=_validate_ref(value.get("ref")),
                subdir=_validate_subdir(value.get("subdir")),
            )
        raise TemplateSourceError('templates.source needs a "url" (git) or a "path"')
    raise TemplateSourceError("templates.source must be a string or an object")


def read_template_source(project_dir: Path) -> Optional[TemplateSource]:
    """The project's declared `templates.source`, or None when it declares none.

    A missing or unparseable `.metaproject.json` is "none" (identity handling reports
    that elsewhere); a present but malformed `templates.source` raises
    `TemplateSourceError`, so the caller can say why it fell back.
    """
    import json

    from metaproject.identity import IDENTITY_FILE

    try:
        data = json.loads((Path(project_dir) / IDENTITY_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    templates = data.get("templates")
    if templates is None:
        return None
    if not isinstance(templates, dict):
        raise TemplateSourceError('"templates" in .metaproject.json is not an object')
    if templates.get("source") is None:
        return None
    return parse_template_source(templates["source"])


# ------------------------------------------------------------------------------ cache


def cache_root(config_dir: Optional[Path] = None) -> Path:
    """Where fetched git sources live: `<config dir>/cache/templates/`."""
    return (config_dir or get_config_dir()) / "cache" / "templates"


def cache_dir(source: TemplateSource, config_dir: Optional[Path] = None) -> Path:
    """The checkout directory for one (url, ref) pair; stable across runs."""
    key = hashlib.sha256(f"{source.location}\n{source.ref or ''}".encode()).hexdigest()[:16]
    base = re.sub(r"\.git$", "", source.location.rstrip("/").rsplit("/", 1)[-1])
    base = re.sub(r"[^A-Za-z0-9._-]", "-", base.rsplit(":", 1)[-1]) or "templates"
    return cache_root(config_dir) / f"{base}-{key}"


def store_usable(path: Path) -> bool:
    """A directory holding at least one entry other than `.git`. Never raises."""
    try:
        return path.is_dir() and any(entry.name != ".git" for entry in path.iterdir())
    except OSError:
        return False


def _store_path(source: TemplateSource, checkout: Path) -> Path:
    return checkout / source.subdir if source.subdir else checkout


def _git_env() -> Dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in _GIT_LOCATION_VARS}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git(runner: Runner, *args: str, cwd: Optional[Path] = None) -> Optional[str]:
    """Run one git command; return its error text, or None on success."""
    try:
        result = runner(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            env=_git_env(),
            check=False,
        )
    except FileNotFoundError:
        return "git is not installed"
    except subprocess.TimeoutExpired:
        return f"git timed out after {GIT_TIMEOUT_SECONDS}s"
    except OSError as exc:
        return str(exc)
    if result.returncode != 0:
        lines = (result.stderr or result.stdout or "").strip().splitlines()
        return lines[-1] if lines else f"git exited {result.returncode}"
    return None


def _shallow_checkout(runner: Runner, source: TemplateSource, checkout: Path) -> Optional[str]:
    """Fetch `ref` (default HEAD) at depth 1 into `checkout` and check it out."""
    ref = source.ref or "HEAD"
    fetch = ("fetch", "--quiet", "--depth", "1", "--no-tags", "--", source.location, ref)
    error = _git(runner, *fetch, cwd=checkout)
    if error is None:
        error = _git(
            runner, "checkout", "--quiet", "--force", "--detach", "FETCH_HEAD", cwd=checkout
        )
    return error


def fetch_template_source(
    source: TemplateSource,
    config_dir: Optional[Path] = None,
    runner: Optional[Runner] = None,
) -> FetchResult:
    """Shallow-fetch a git source into its cache; refresh it when already cached.

    A first fetch goes into a temporary sibling directory and is renamed into place only
    once it succeeded, so a failed or interrupted fetch never leaves a half-written
    cache that a later run would mistake for a store. A failed refresh keeps the cache
    it already had (and says so). Never raises.
    """
    if source.kind != "git":
        return FetchResult(ok=False, path=None, message="not a git source")
    run = runner or subprocess.run
    checkout = cache_dir(source, config_dir)
    store = _store_path(source, checkout)

    if (checkout / ".git").is_dir():
        error = _shallow_checkout(run, source, checkout)
        if error is None and store_usable(store):
            return FetchResult(ok=True, path=store, message=f"refreshed {source.label}")
        if store_usable(store):
            return FetchResult(
                ok=False, path=store, message=f"refresh failed ({error}); kept the cached copy"
            )
        return FetchResult(ok=False, path=None, message=error or f"no templates in {store}")

    staging = checkout.with_name(f".{checkout.name}.tmp-{os.getpid()}")
    try:
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
    except OSError as exc:
        return FetchResult(ok=False, path=None, message=f"cannot create {staging} ({exc})")
    error = _git(run, "init", "--quiet", cwd=staging) or _shallow_checkout(run, source, staging)
    if error is None and not store_usable(_store_path(source, staging)):
        error = f"no templates found in {source.label}"
    if error is not None:
        shutil.rmtree(staging, ignore_errors=True)
        return FetchResult(ok=False, path=None, message=error)
    try:
        shutil.rmtree(checkout, ignore_errors=True)
        staging.rename(checkout)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return FetchResult(ok=False, path=None, message=f"cannot move the fetch into place ({exc})")
    return FetchResult(ok=True, path=store, message=f"fetched {source.label}")


# ------------------------------------------------------------------------- resolution


def _bundled(detail: str, declared: bool) -> TemplateResolution:
    from metaproject.templates import get_bundled_templates_dir

    return TemplateResolution(
        path=get_bundled_templates_dir(),
        origin=ORIGIN_BUNDLED,
        detail=detail,
        source_declared=declared,
    )


def _configured_store(config: Optional[Config]) -> Optional[Path]:
    try:
        cfg = config or load_config()
        store = Path(cfg.templates_dir)
        if store.exists() and any(store.iterdir()):
            return store.resolve()
    except (OSError, MetaProjectError):
        pass
    return None


def resolve_templates(
    project_dir: Optional[Path] = None,
    templates_dir: Optional[Path] = None,
    config: Optional[Config] = None,
    fetch: bool = True,
    runner: Optional[Runner] = None,
) -> TemplateResolution:
    """The template store to render from, and a one-line account of the choice.

    See the module docstring for the order. `fetch=False` never touches the network: a
    git source that is not cached yet falls back to the bundled templates. Never raises.
    """
    if templates_dir:
        path = Path(templates_dir).expanduser().resolve()
        return TemplateResolution(path=path, origin=ORIGIN_EXPLICIT, detail=f"{path} (--templates)")

    store = _configured_store(config)
    if store is not None:
        return TemplateResolution(path=store, origin=ORIGIN_STORE, detail=f"{store} (store)")

    bundled_detail = "bundled defaults (no template store)"
    if project_dir is None:
        return _bundled(bundled_detail, declared=False)
    project = Path(project_dir).expanduser().resolve()
    try:
        source = read_template_source(project)
    except TemplateSourceError as exc:
        return _bundled(f"bundled defaults ({exc})", declared=True)
    if source is None:
        return _bundled(bundled_detail, declared=False)

    if source.kind == "path":
        path = (project / Path(source.location).expanduser()).resolve()
        if store_usable(path):
            return TemplateResolution(
                path=path,
                origin=ORIGIN_SOURCE,
                detail=f"{path} (templates.source path)",
                source_declared=True,
            )
        return _bundled(
            f"bundled defaults (templates.source path {source.location} not found)", True
        )

    cached = _store_path(source, cache_dir(source))
    if (cache_dir(source) / ".git").is_dir() and store_usable(cached):
        return TemplateResolution(
            path=cached,
            origin=ORIGIN_SOURCE,
            detail=f"{source.label} (templates.source, cached at {cached})",
            source_declared=True,
        )
    if not fetch:
        return _bundled(f"bundled defaults (templates.source {source.label} not fetched)", True)
    result = fetch_template_source(source, runner=runner)
    if result.path is not None:
        return TemplateResolution(
            path=result.path,
            origin=ORIGIN_SOURCE,
            detail=f"{source.label} (templates.source, fetched into {result.path})",
            source_declared=True,
        )
    return _bundled(
        f"bundled defaults (templates.source {source.label} unavailable: {result.message})", True
    )
