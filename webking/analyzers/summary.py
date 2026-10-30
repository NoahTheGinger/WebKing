"""Session summarization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from webking.artifacts import ArtifactIndex, SessionManifest


@dataclass(slots=True)
class SessionSummary:
    """Simple heuristic summary for a session."""

    headline: str
    details: str

    def as_markdown(self) -> str:
        return f"# {self.headline}\n\n{self.details}"

    def as_plain_text(self) -> str:
        return f"{self.headline}\n\n{self.details}"


def build_session_summary(
    manifest: SessionManifest, capture_summary: dict[str, Any], artifacts: ArtifactIndex
) -> SessionSummary:
    """Generate a descriptive summary of the session from available artifacts."""
    counts = capture_summary.get("counts", {})
    bullet_lines = [
        f"- Network entries captured: {counts.get('network_entries', 0)}",
        f"- Script bundles stored: {counts.get('script_bundles', 0)}",
        f"- DOM snapshot saved: {'Yes' if counts.get('dom_snapshot') else 'No'}",
        f"- Storage state captured: {'Yes' if counts.get('storage_captured') else 'No'}",
    ]

    recipe_lines = []
    for step in capture_summary.get("recipes", []):
        recipe_lines.append(
            f"  - Recipe '{step.get('recipe')}': {step.get('status')} ({step.get('message')})"
        )

    summary_text = "\n".join(
        [
            f"Target URL: {manifest.target_url}",
            f"Session ID: {manifest.session_id}",
            "",
            "Artifacts captured:",
            *bullet_lines,
            "",
            "Recipe execution:",
            *(recipe_lines or ["  - No recipe executed"]),
        ]
    )

    if manifest.summary:
        summary_text += f"\n\nUser Notes:\n{manifest.summary}"

    headline = f"Session summary for {manifest.target_url}"
    return SessionSummary(headline=headline, details=summary_text)
