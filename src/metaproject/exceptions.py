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
