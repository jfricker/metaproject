"""Domain-specific exception types for MetaProject."""


class MetaProjectError(Exception):
    """Base exception for all MetaProject errors."""

    pass


class ConfigError(MetaProjectError):
    """Raised when configuration loading, saving, or validation fails."""

    pass


class TemplateError(MetaProjectError):
    """Raised when template discovery, stripping, or rendering fails."""

    pass


class CollisionError(MetaProjectError):
    """Raised when the target directory is not empty and force is not specified."""

    pass


class GitError(MetaProjectError):
    """Raised when git inspection, initialization, or commit operations fail."""

    pass


class ScannerError(MetaProjectError):
    """Raised when workspace scanning or database operations fail."""

    pass


class ModelUnavailableError(MetaProjectError):
    """Raised when the `claude` binary `learn` shells out to is not on PATH."""

    pass


class ModelOutputError(MetaProjectError):
    """Raised when model output cannot be parsed as the structured proposal schema."""

    pass


class ApplyError(MetaProjectError):
    """Raised when a proposal cannot be written into the template store.

    Covers a dirty template repository, an unresolvable template file, and a refused
    R7 fallback. Every one of them leaves the template store untouched.
    """

    pass
