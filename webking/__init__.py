"""WebKing package for reverse-engineering oriented MCP tooling."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("webking")
except PackageNotFoundError:  # pragma: no cover - during local development
    __version__ = "0.0.0"

__all__ = ["__version__"]
