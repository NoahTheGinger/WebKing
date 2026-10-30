"""Artifact storage helpers for WebKing sessions."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from slugify import slugify

DEFAULT_SESSIONS_DIR = Path("sessions")


class ArtifactMeta(BaseModel):
    """Metadata describing an individual artifact produced during a session."""

    type: str = Field(description="Artifact type identifier, e.g., 'network_log', 'dom_snapshot'.")
    path: str = Field(description="Relative path to the artifact file within the session directory.")
    description: str | None = Field(
        default=None,
        description="Human-readable description of the artifact.",
    )
    content_type: str | None = Field(
        default=None,
        description="Optional MIME type associated with the artifact.",
    )


class ArtifactIndex(BaseModel):
    """Index of artifacts grouped by category."""

    network: list[ArtifactMeta] = Field(default_factory=list)
    dom: list[ArtifactMeta] = Field(default_factory=list)
    storage: list[ArtifactMeta] = Field(default_factory=list)
    scripts: list[ArtifactMeta] = Field(default_factory=list)
    analysis: list[ArtifactMeta] = Field(default_factory=list)


class SessionManifest(BaseModel):
    """Manifest describing a recorded session and its artifacts."""

    session_id: str = Field(description="Unique slug for the session.")
    target_url: str = Field(description="Primary URL visited during the session.")
    recipe: str | None = Field(default=None, description="Optional session recipe identifier.")
    created_at: float = Field(description="Unix timestamp when the session was captured.")
    summary: str | None = Field(default=None, description="Optional human-readable summary.")
    artifact_index: ArtifactIndex = Field(
        default_factory=ArtifactIndex, description="Collections of captured artifacts."
    )


@dataclass(slots=True)
class ArtifactPaths:
    """Convenience dataclass with resolved directories for a session."""

    root: Path
    network_dir: Path
    dom_dir: Path
    storage_dir: Path
    scripts_dir: Path
    analysis_dir: Path
    manifest_path: Path


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_artifact_paths(session_slug: str, base_dir: Path | None = None) -> ArtifactPaths:
    """Prepare the file system structure for a session."""
    base_dir = base_dir or DEFAULT_SESSIONS_DIR
    root = _ensure_dir(base_dir / session_slug)
    return ArtifactPaths(
        root=root,
        network_dir=_ensure_dir(root / "network"),
        dom_dir=_ensure_dir(root / "dom"),
        storage_dir=_ensure_dir(root / "storage"),
        scripts_dir=_ensure_dir(root / "scripts"),
        analysis_dir=_ensure_dir(root / "analysis"),
        manifest_path=root / "manifest.json",
    )


def persist_text(path: Path, content: str) -> None:
    """Persist text content to disk, ensuring parent directories exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def persist_json(path: Path, payload: Any) -> None:
    """Persist JSON payload to disk with nice formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def persist_binary(path: Path, data: bytes) -> None:
    """Persist binary data to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def save_manifest(manifest: SessionManifest, path: Path) -> None:
    """Write manifest to disk (json)."""
    persist_json(path, manifest.model_dump())


def load_manifest(path: Path) -> SessionManifest:
    """Load manifest from disk."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return SessionManifest.model_validate(data)


def slugify_session_name(target_url: str, timestamp: float) -> str:
    """Create a deterministic slug for session directories."""
    host = slugify(target_url.split("//")[-1].split("/")[0])
    suffix = str(int(timestamp))
    return slugify(f"{host}-{suffix}")


def find_manifests(base_dir: Path | None = None) -> list[SessionManifest]:
    """Discover existing session manifests."""
    base_dir = base_dir or DEFAULT_SESSIONS_DIR
    if not base_dir.exists():
        return []

    manifests: list[SessionManifest] = []
    for child in base_dir.iterdir():
        manifest_path = child / "manifest.json"
        if manifest_path.exists():
            try:
                manifests.append(load_manifest(manifest_path))
            except Exception:  # pragma: no cover - tolerant discovery
                continue
    return manifests


def _resolve_within(base: Path, name: str) -> Path:
    """Join ``name`` onto ``base``, rejecting anything that escapes ``base``."""
    base = base.resolve()
    candidate = (base / name).resolve()
    if candidate == base or not candidate.is_relative_to(base):
        raise ValueError(f"Invalid path '{name}'.")
    return candidate


def resolve_session_path(session_id: str, base_dir: Path | None = None) -> Path:
    """Resolve a session directory, raising if missing or outside the sessions directory."""
    base_dir = base_dir or DEFAULT_SESSIONS_DIR
    session_dir = _resolve_within(base_dir, session_id)
    if not session_dir.is_dir():
        raise FileNotFoundError(f"Session '{session_id}' not found under {base_dir}")
    return session_dir


def resolve_artifact_path(session_dir: Path, subdir: str, name: str) -> Path:
    """Resolve an artifact file inside a session subdirectory, rejecting path traversal."""
    return _resolve_within(session_dir / subdir, name)


__all__ = [
    "ArtifactMeta",
    "ArtifactIndex",
    "SessionManifest",
    "ArtifactPaths",
    "build_artifact_paths",
    "persist_text",
    "persist_json",
    "persist_binary",
    "save_manifest",
    "load_manifest",
    "slugify_session_name",
    "find_manifests",
    "resolve_session_path",
    "resolve_artifact_path",
    "DEFAULT_SESSIONS_DIR",
]
