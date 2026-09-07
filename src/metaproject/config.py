"""Configuration manager and persistent settings for MetaProject."""

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from metaproject.exceptions import ConfigError

DEFAULT_CONFIG_DIR = Path.home() / ".metaproject"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_TEMPLATES_DIR = DEFAULT_CONFIG_DIR / "templates"
DEFAULT_UNIVERSE_DB = DEFAULT_CONFIG_DIR / "universe.db"

DEFAULT_LEARN_TARGETS = [
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "intent.md",
    "STATE.md",
    "HANDOFF.md",
    ".gitignore",
    "docs/",
    "Makefile",
    "pyproject.toml",
]

# The `learn` pipeline's default model: fast and cheap, since each scan can issue one
# call per target file (spec.md §5.4.3). Set `learn.model` to override.
DEFAULT_LEARN_MODEL = "claude-haiku-4-5-20251001"

DEFAULT_ACTIVITY_WEIGHTS = {
    "Active Now": 1.0,
    "Active Near": 0.8,
    "Active Far": 0.6,
    "Idle": 0.4,
    "Ancient": 0.2,
    "Archived": 0.1,
}


def detect_git_user_name() -> str:
    """Attempt to detect user name from git global configuration."""
    try:
        res = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return os.environ.get("USER", "Developer")


@dataclass
class LearnConfig:
    """Configuration for the `learn` proposal pipeline. See spec.md §4.2."""

    targets: list[str] = field(default_factory=lambda: list(DEFAULT_LEARN_TARGETS))
    resurface_factor: float = 2.0
    model: str | None = DEFAULT_LEARN_MODEL
    activity_weights: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_ACTIVITY_WEIGHTS)
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LearnConfig":
        """Construct LearnConfig from a dictionary, filtering unknown keys."""
        valid_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class Config:
    """User configuration schema for MetaProject."""

    version: int = 1
    author: str = ""
    default_branch: str = "main"
    project_home: str = str(Path.home() / "Projects")
    templates_dir: str = ""
    universe_db: str = ""
    auto_git_init: bool = True
    default_license: str = "MIT"
    learn: LearnConfig = field(default_factory=LearnConfig)

    def __post_init__(self) -> None:
        if isinstance(self.learn, dict):
            self.learn = LearnConfig.from_dict(self.learn)
        if not self.author:
            self.author = detect_git_user_name()
        if not self.templates_dir:
            self.templates_dir = str(get_config_dir() / "templates")
        if not self.universe_db:
            self.universe_db = str(get_config_dir() / "universe.db")
        # Expand user in paths
        self.project_home = str(Path(self.project_home).expanduser().resolve())
        self.templates_dir = str(Path(self.templates_dir).expanduser().resolve())
        self.universe_db = str(Path(self.universe_db).expanduser().resolve())

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Construct Config instance from a dictionary."""
        # Filter unexpected keys for forwards compatibility
        valid_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


def get_config_dir(custom_path: Path | str | None = None) -> Path:
    """Return resolved configuration directory."""
    if custom_path:
        return Path(custom_path).expanduser().resolve()
    env_dir = os.environ.get("METAPROJECT_CONFIG_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return DEFAULT_CONFIG_DIR.resolve()


def get_config_file_path(config_dir: Path | None = None) -> Path:
    """Return path to config.json within the resolved configuration directory."""
    base_dir = config_dir or get_config_dir()
    return base_dir / "config.json"


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from disk, falling back to defaults if not found."""
    target_path = config_path or get_config_file_path()
    try:
        if not target_path.exists():
            return Config()
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ConfigError(f"Malformed config file (expected JSON object): {target_path}")
        return Config.from_dict(data)
    except PermissionError:
        return Config()
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Failed to parse config file {target_path}: {exc}") from exc
    except Exception as exc:
        raise ConfigError(f"Error reading config {target_path}: {exc}") from exc


def save_config(config: Config, config_path: Path | None = None) -> Path:
    """Save configuration to disk, creating parent directories if needed."""
    target_path = config_path or get_config_file_path()
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=2)
        return target_path
    except Exception as exc:
        raise ConfigError(f"Failed to write configuration to {target_path}: {exc}") from exc
