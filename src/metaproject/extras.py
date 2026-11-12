"""Optional dependencies, imported only when a command actually needs them.

`textual`, `questionary` and `sqlite-utils` ship in the `tui` extra
(`metaproject[tui]`), not in the core install, so the commands a fresh container needs
(`--version`, `backfill`, `adopt`, `review --no-tui`) import none of them. Every other
use goes through `require` (or a `LazyModule` proxy over it), which turns a missing
extra into one actionable `MissingExtraError` instead of an `ImportError` traceback.
"""

import importlib
from types import ModuleType
from typing import Any

from metaproject.exceptions import MissingExtraError

TUI_EXTRA = "tui"
INSTALL_HINT = 'pip install "metaproject[tui]"'

# The distribution name differs from the import name for sqlite-utils.
_DISTRIBUTIONS = {"sqlite_utils": "sqlite-utils"}


def require(module: str, feature: str) -> ModuleType:
    """Import `module`, or raise `MissingExtraError` naming the extra that provides it."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        dist = _DISTRIBUTIONS.get(module, module)
        raise MissingExtraError(
            f"{feature} needs {dist}, which ships in the optional '{TUI_EXTRA}' extra. "
            f"Install it with: {INSTALL_HINT}"
        ) from exc


def available(module: str) -> bool:
    """Can `module` be imported? (Is the extra that provides it installed?)"""
    try:
        importlib.import_module(module)
    except ImportError:
        return False
    return True


class LazyModule:
    """A module-shaped proxy that imports its module on first attribute access.

    Lets a core module keep `questionary.confirm(...)` call sites (and lets tests
    monkeypatch `module.questionary`) without importing the extra at import time.
    """

    def __init__(self, module: str, feature: str) -> None:
        self._module = module
        self._feature = feature

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(require(self._module, self._feature), name)
