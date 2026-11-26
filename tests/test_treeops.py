"""treeops: the staged swap and crash recovery."""

import os
from pathlib import Path

import pytest

from metaproject import treeops
from metaproject.exceptions import MetaProjectError
from metaproject.treeops import _fingerprint, file_map, recover_staging, swap_tree


def _tree(root: Path, files: dict) -> Path:
    for rel, text in files.items():
        out = root / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    return root


def test_swap_tree_replaces_dest(tmp_path: Path) -> None:
    src = _tree(tmp_path / "src", {"a.txt": "new", "d/b.txt": "b"})
    dest = _tree(tmp_path / "dest", {"a.txt": "old", "stale.txt": "x"})
    staging = tmp_path / "stage"
    warnings: list = []
    ok = swap_tree(
        src, dest, file_map(src), _fingerprint(dest), staging, "k", None, warnings, tmp_path
    )
    assert ok and not warnings
    assert file_map(dest) == file_map(src)
    assert not (staging / "k.old").exists()
    assert not (staging / "k.dest.txt").exists()


def test_swap_tree_creates_missing_dest_and_nested_key(tmp_path: Path) -> None:
    src = _tree(tmp_path / "src", {"a.txt": "new"})
    dest = tmp_path / "out" / "dest"
    dest.parent.mkdir()
    ok = swap_tree(
        src, dest, file_map(src), _fingerprint(dest), tmp_path / "s", "x/y", None, [], tmp_path
    )
    assert ok
    assert (dest / "a.txt").read_text(encoding="utf-8") == "new"


def test_swap_tree_mismatch_raises_and_keeps_dest(tmp_path: Path) -> None:
    src = _tree(tmp_path / "src", {"a.txt": "new"})
    dest = _tree(tmp_path / "dest", {"a.txt": "old"})
    with pytest.raises(MetaProjectError):
        swap_tree(
            src,
            dest,
            {"a.txt": "bogus"},
            _fingerprint(dest),
            tmp_path / "s",
            "k",
            None,
            [],
            tmp_path,
        )
    assert (dest / "a.txt").read_text(encoding="utf-8") == "old"


def test_swap_tree_rename_in_failure_restores_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _tree(tmp_path / "src", {"a.txt": "new"})
    dest = _tree(tmp_path / "dest", {"a.txt": "old"})
    real = os.rename

    def flaky(a, b, *args, **kwargs):
        if str(a).endswith(".new"):
            raise OSError("boom")
        return real(a, b, *args, **kwargs)

    monkeypatch.setattr(treeops.os, "rename", flaky)
    with pytest.raises(MetaProjectError):
        swap_tree(
            src, dest, file_map(src), _fingerprint(dest), tmp_path / "s", "k", None, [], tmp_path
        )
    assert (dest / "a.txt").read_text(encoding="utf-8") == "old"


def test_swap_tree_snapshot_mismatch_returns_false(tmp_path: Path) -> None:
    src = _tree(tmp_path / "src", {"a.txt": "new"})
    dest = _tree(tmp_path / "dest", {"a.txt": "old"})
    snapshot = _fingerprint(dest)
    (dest / "a.txt").write_text("edited", encoding="utf-8")
    assert not swap_tree(
        src, dest, file_map(src), snapshot, tmp_path / "s", "k", None, [], tmp_path
    )
    assert (dest / "a.txt").read_text(encoding="utf-8") == "edited"


def test_recover_staging_uses_relative_dest_marker(tmp_path: Path) -> None:
    root = tmp_path / "home"
    staging = root / "stage"
    _tree(staging / "grp" / "k.old", {"a.txt": "kept"})
    (staging / "grp" / "k.dest.txt").write_text("sub/k", encoding="utf-8")
    recover_staging(staging, root / "default", root)
    assert (root / "sub" / "k" / "a.txt").read_text(encoding="utf-8") == "kept"
    assert not staging.exists()


def _hostile(tmp_path: Path, marker: str) -> tuple:
    root = tmp_path / "home"
    outside = tmp_path / "outside"
    outside.mkdir()
    staging = root / "stage"
    _tree(staging / "k.old", {"a.txt": "kept"})
    (staging / "k.dest.txt").write_text(marker, encoding="utf-8")
    return root, outside, staging


def test_recover_staging_ignores_absolute_marker(tmp_path: Path) -> None:
    root, outside, staging = _hostile(tmp_path, str(tmp_path / "outside" / "k"))
    recover_staging(staging, root / "default", root)
    assert not (outside / "k").exists()


def test_recover_staging_ignores_dotdot_marker(tmp_path: Path) -> None:
    root, outside, staging = _hostile(tmp_path, "../outside/k")
    recover_staging(staging, root / "default", root)
    assert not (outside / "k").exists()


def test_recover_staging_ignores_symlink_escape(tmp_path: Path) -> None:
    root, outside, staging = _hostile(tmp_path, "link/k")
    (root / "link").symlink_to(outside)
    recover_staging(staging, root / "default", root)
    assert not (outside / "k").exists()


def test_swap_tree_rejects_dest_outside_root(tmp_path: Path) -> None:
    src = _tree(tmp_path / "src", {"a.txt": "new"})
    dest = tmp_path / "elsewhere" / "d"
    dest.parent.mkdir()
    root = tmp_path / "home"
    root.mkdir()
    with pytest.raises(MetaProjectError):
        swap_tree(src, dest, file_map(src), _fingerprint(dest), root / "s", "k", None, [], root)


def test_recover_staging_falls_back_to_default_target(tmp_path: Path) -> None:
    staging = tmp_path / "stage"
    _tree(staging / "k.old", {"a.txt": "kept"})
    default = tmp_path / "default"
    recover_staging(staging, default, tmp_path)
    assert (default / "k" / "a.txt").read_text(encoding="utf-8") == "kept"
    assert not staging.exists()


def test_recover_staging_does_not_clobber_existing_dest(tmp_path: Path) -> None:
    staging = tmp_path / "stage"
    _tree(staging / "k.old", {"a.txt": "old"})
    default = _tree(tmp_path / "default" / "k", {"a.txt": "live"})
    recover_staging(staging, default.parent, tmp_path)
    assert (default / "a.txt").read_text(encoding="utf-8") == "live"
    assert not staging.exists()
