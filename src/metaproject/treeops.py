"""Directory-tree primitives shared by the skills installer: hashing, copying and the
crash-safe staged swap.

Imports nothing from `skills`, so any module may use it.
"""

import hashlib
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from metaproject.exceptions import MetaProjectError

if TYPE_CHECKING:
    from metaproject.scaffold import TransactionalTracker

# The hash of anything inside a tree that is not a regular file. It matches no
# sha256 digest, so such a tree never classifies as pristine.
NON_REGULAR = "symlink"


def hash_content(data: bytes) -> str:
    """sha256 of one file's bytes; text has `\\r\\n` normalised so autocrlf is not an edit."""
    if b"\0" not in data:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def file_map(directory: Path) -> Dict[str, str]:
    """`{posix relpath: sha256}` for every non-junk entry under `directory`, sorted.

    The same filter applies to the bundle and to an installed copy, so an extra file in
    the installed directory makes the maps differ. A symlink or other non-regular entry
    hashes as `NON_REGULAR`, which never matches. Symlinked directories are not entered.
    """
    from metaproject.templates import is_junk_file_name

    directory = Path(directory)
    out: Dict[str, str] = {}
    for root, dirs, files in os.walk(directory, followlinks=False):
        root_path = Path(root)
        rel_root = root_path.relative_to(directory)
        kept = []
        for name in dirs:
            if is_junk_file_name(name):
                continue
            if (root_path / name).is_symlink():
                out[(rel_root / name).as_posix()] = NON_REGULAR
                continue
            kept.append(name)
        dirs[:] = kept
        for name in files:
            if is_junk_file_name(name):
                continue
            path = root_path / name
            rel = (rel_root / name).as_posix()
            if path.is_symlink() or not path.is_file():
                out[rel] = NON_REGULAR
            else:
                out[rel] = hash_content(path.read_bytes())
    return dict(sorted(out.items()))


def _fingerprint(dest: Path) -> Tuple:
    """What `dest` looks like now, for the classify-then-swap (TOCTOU) comparison."""
    if dest.is_symlink():
        return ("symlink", os.readlink(dest))
    if not dest.exists():
        return ("absent",)
    if not dest.is_dir():
        return ("other",)
    return ("dir", tuple(file_map(dest).items()))


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _bundled_files(source_dir: Path) -> List[Path]:
    from metaproject.templates import is_junk_file_name

    return sorted(
        item
        for item in source_dir.rglob("*")
        if item.is_file()
        and not any(is_junk_file_name(part) for part in item.relative_to(source_dir).parts)
    )


def _copy_tree(source_dir: Path, dest: Path) -> None:
    for item in _bundled_files(source_dir):
        out = dest / item.relative_to(source_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, out)


def _record_tree(dest: Path, tracker: "TransactionalTracker") -> None:
    tracker.record_created_dir(dest)
    for item in sorted(dest.rglob("*")):
        if item.is_dir():
            tracker.record_created_dir(item)
        else:
            tracker.record_created_file(item)


def swap_tree(
    source: Path,
    dest: Path,
    expected: Dict[str, str],
    snapshot: Tuple,
    staging: Path,
    key: str,
    tracker: "Optional[TransactionalTracker]",
    warnings: List[str],
) -> bool:
    """Swap a copy of `source` into `dest` atomically. False when `dest` changed meanwhile.

    The copy is built and verified (`file_map == expected`) in `staging`, the old tree is
    renamed aside, the new one renamed in; a failed rename puts the old one back and
    raises. `<staging>/<key>.dest.txt` records `dest` while the old tree is aside so
    `recover_staging` can restore it after a crash. `key` may contain `/`.
    """
    new = staging / f"{key}.new"
    old = staging / f"{key}.old"
    marker = staging / f"{key}.dest.txt"
    new.parent.mkdir(parents=True, exist_ok=True)
    for leftover in (new, old, marker):
        if leftover.exists() or leftover.is_symlink():
            _remove(leftover)
    _copy_tree(source, new)
    if file_map(new) != expected:
        _remove(new)
        raise MetaProjectError(f"the staged copy of {key} does not match its source")

    if _fingerprint(dest) != snapshot:
        _remove(new)
        return False
    existed = dest.exists() or dest.is_symlink()
    if existed:
        marker.write_text(str(Path(dest).absolute()), encoding="utf-8")
        os.rename(dest, old)
    try:
        os.rename(new, dest)
    except OSError as exc:
        if existed:
            try:
                os.rename(old, dest)
            except OSError:
                pass
        raise MetaProjectError(f"could not replace {key}: {exc}") from exc
    if existed:
        try:
            _remove(old)
        except OSError as exc:
            warnings.append(f"could not remove the previous copy of {key}: {exc}")
        try:
            _remove(marker)
        except OSError:
            pass
    if tracker is not None and not existed:
        _record_tree(dest, tracker)
    return True


def recover_staging(staging: Path, default_target: Path) -> None:
    """Undo a crash mid-swap: restore each `*.old` whose destination is gone, then clean.

    The destination is the matching `.dest.txt`'s content when present, else
    `default_target / <name without .old>`.
    """
    if not staging.exists():
        return
    for old in sorted(staging.rglob("*.old")):
        marker = old.with_name(old.name[: -len(".old")] + ".dest.txt")
        dest: Optional[Path] = None
        if marker.is_file():
            try:
                text = marker.read_text(encoding="utf-8").strip()
            except OSError:
                text = ""
            if text:
                dest = Path(text)
        if dest is None:
            dest = default_target / old.name[: -len(".old")]
        if not dest.exists() and not dest.is_symlink():
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.rename(old, dest)
    shutil.rmtree(staging, ignore_errors=True)
