"""Utility helpers for WebKing MCP server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    """Load JSON from a path."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_text(path: Path) -> str:
    """Load text from a path."""
    return path.read_text(encoding="utf-8")
