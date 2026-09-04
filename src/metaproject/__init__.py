"""MetaProject: A CLI tool for scaffolding and managing agentic projects and templates."""

try:
    from importlib.metadata import version

    __version__ = version("metaproject")
except Exception:
    __version__ = "0.6.0"
