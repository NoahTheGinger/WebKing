"""FastMCP server exposing advanced reverse-engineering workflows."""

from __future__ import annotations

import json
import textwrap
from enum import Enum
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, ConfigDict, Field

from webking.analyzers import NetworkInsightRequest, analyze_network_log, build_session_summary
from webking.artifacts import (
    DEFAULT_SESSIONS_DIR,
    ArtifactMeta,
    SessionManifest,
    find_manifests,
    load_manifest,
    resolve_session_path,
)
from webking.browser import SessionConfig, SessionManager
from webking.utils import load_json, load_text

CHARACTER_LIMIT = 25_000

mcp = FastMCP("webking_mcp")


class ResponseFormat(str, Enum):
    """Output formats supported by tools."""

    MARKDOWN = "markdown"
    JSON = "json"


class LaunchSessionInput(BaseModel):
    """Input payload for launching a capture session."""

    model_config = ConfigDict(extra="forbid")

    session: SessionConfig = Field(..., description="Complete configuration for the capture session.")


class ListSessionsInput(BaseModel):
    """Filter options when listing sessions."""

    model_config = ConfigDict(extra="forbid")

    limit: int | None = Field(
        default=20,
        ge=1,
        le=200,
        description="Maximum number of sessions to return (default 20).",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Offset used for pagination (default 0).",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Choose 'json' for structured output or 'markdown' for human-readable.",
    )


class SessionScopedInput(BaseModel):
    """Base model for tools operating on a single session."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., description="Session ID slug (from manifest).")
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format preference.",
    )


class NetworkInsightsInput(SessionScopedInput):
    """Input payload for network insight tool."""

    filters: NetworkInsightRequest = Field(
        default_factory=NetworkInsightRequest,
        description="Filtering rules for network log analysis.",
    )


class DomSnapshotInput(SessionScopedInput):
    """Input payload for DOM snapshot retrieval."""

    snapshot_name: str = Field(
        default="snapshot.html",
        description="Filename of the snapshot within the session (default 'snapshot.html').",
    )


class ScriptContentInput(SessionScopedInput):
    """Retrieve a specific script bundle."""

    script_name: str = Field(
        ...,
        description="Filename of the script within the session's 'scripts' directory.",
    )


class UserscriptStubInput(SessionScopedInput):
    """Generate a starter userscript based on session findings."""

    include_storage: bool = Field(
        default=True,
        description="Include storage instrumentation helpers if storage was captured.",
    )
    include_network_hooks: bool = Field(
        default=True,
        description="Include fetch/XHR monkey patches referencing captured endpoints.",
    )


def _format_response(payload: Any, response_format: ResponseFormat) -> str:
    if response_format == ResponseFormat.JSON:
        return json.dumps(payload, indent=2, ensure_ascii=False)
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict) and "markdown" in payload:
        return payload["markdown"]
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _load_network_entries(session_dir: Path) -> list[dict[str, Any]]:
    network_path = session_dir / "network" / "network_log.json"
    if not network_path.exists():
        raise FileNotFoundError("No network log available for this session.")
    return load_json(network_path)


def _load_script_list(manifest: SessionManifest) -> list[ArtifactMeta]:
    return manifest.artifact_index.scripts


@mcp.tool(
    name="webking_launch_session",
    annotations={
        "title": "Launch Capture Session",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def webking_launch_session(params: LaunchSessionInput, ctx: Context) -> str:
    """Capture a new web session, storing network logs, DOM snapshots, scripts, and storage state.

    Args:
        params (LaunchSessionInput): The session configuration wrapper. See SessionConfig for details.
            - session.target_url (HttpUrl): URL to capture.
            - session.recipe (Optional[str]): Optional recipe identifier for scripted flows.
            - session.cookies (Optional[List[Dict]]): Initial cookies to set.
            - session.extra_headers (Optional[Dict[str, str]]): Headers appended to each request.
            - session.capture (CaptureOptions): Flags controlling artifact capture.
            - session.browser (BrowserLaunchOptions): Chromium launch configuration.
            - session.notes (Optional[str]): Notes stored alongside the manifest.

    Returns:
        str: JSON payload containing the session ID and capture summary, truncated if necessary.
    """
    manager = SessionManager(base_dir=DEFAULT_SESSIONS_DIR)
    await ctx.log_info("Launching session", params.session.model_dump())
    result = await manager.run_session(params.session)

    summary = {
        "session_id": result.manifest.session_id,
        "target_url": result.manifest.target_url,
        "artifact_counts": result.capture_summary["counts"],
        "manifest_path": str(result.artifact_paths.manifest_path),
    }

    payload = json.dumps(summary, indent=2)
    if len(payload) > CHARACTER_LIMIT:
        payload = payload[:CHARACTER_LIMIT] + "\n/* truncated */"
    return payload


@mcp.tool(
    name="webking_list_sessions",
    annotations={
        "title": "List Captured Sessions",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def webking_list_sessions(params: ListSessionsInput) -> str:
    """List captured sessions stored on disk.

    Args:
        params (ListSessionsInput): Pagination and formatting controls.

    Returns:
        str: Markdown or JSON list of sessions with metadata.
    """
    manifests = find_manifests(DEFAULT_SESSIONS_DIR)
    manifests.sort(key=lambda m: m.created_at, reverse=True)
    sliced = manifests[params.offset : params.offset + (params.limit or len(manifests))]

    if params.response_format == ResponseFormat.JSON:
        payload = [
            {
                "session_id": m.session_id,
                "target_url": m.target_url,
                "recipe": m.recipe,
                "created_at": m.created_at,
                "summary": m.summary,
            }
            for m in sliced
        ]
        return json.dumps(
            {
                "total": len(manifests),
                "count": len(sliced),
                "offset": params.offset,
                "sessions": payload,
            },
            indent=2,
        )

    lines = ["# Captured Sessions", ""]
    for manifest in sliced:
        lines.append(f"## {manifest.session_id}")
        lines.append(f"- URL: {manifest.target_url}")
        lines.append(f"- Recipe: {manifest.recipe or 'none'}")
        lines.append(f"- Created: {manifest.created_at}")
        lines.append(f"- Summary: {manifest.summary or 'n/a'}")
        lines.append("")
    lines.append(f"_Total stored sessions: {len(manifests)}_")
    return "\n".join(lines)


@mcp.tool(
    name="webking_get_network_insights",
    annotations={
        "title": "Analyze Network Log",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def webking_get_network_insights(params: NetworkInsightsInput) -> str:
    """Analyze captured network logs for a session.

    Args:
        params (NetworkInsightsInput): Session ID plus filtering instructions.

    Returns:
        str: Markdown or JSON containing aggregated network insights.
    """
    session_dir = resolve_session_path(params.session_id, DEFAULT_SESSIONS_DIR)
    manifest = load_manifest(session_dir / "manifest.json")
    network_entries = _load_network_entries(session_dir)
    insights = analyze_network_log(network_entries, params.filters)

    if params.response_format == ResponseFormat.JSON:
        return json.dumps({"session_id": params.session_id, "insights": insights}, indent=2)

    lines = [
        f"# Network Insights for {manifest.target_url}",
        f"Session ID: `{params.session_id}`",
        "",
        f"Total entries matching filters: **{insights['total_filtered']}**",
        "",
        "## Top Hosts",
    ]
    if insights["top_hosts"]:
        for host_info in insights["top_hosts"]:
            lines.append(f"- **{host_info['host']}**: {host_info['request_count']} requests")
            lines.append(f"  - Methods: {', '.join(host_info['methods'])}")
            lines.append(f"  - Status Codes: {', '.join(map(str, host_info['status_codes']))}")
    else:
        lines.append("- No hosts matched the filters.")

    lines.append("")
    lines.append("## Method Usage")
    for method, count in insights["methods_count"].items():
        lines.append(f"- `{method}`: {count} requests")

    if params.filters.include_bodies and insights["sample_payloads"]:
        lines.append("")
        lines.append("## Sample Payloads")
        for payload in insights["sample_payloads"]:
            snippet = json.dumps(payload["post_data"], indent=2) if payload["post_data"] else "None"
            if len(snippet) > 400:
                snippet = snippet[:400] + "... (truncated)"
            lines.append(f"- **{payload['method']} {payload['url']}**\n```json\n{snippet}\n```")

    markdown = "\n".join(lines)
    if len(markdown) > CHARACTER_LIMIT:
        markdown = markdown[:CHARACTER_LIMIT] + "\n\n_Section truncated for length._"
    return markdown


@mcp.tool(
    name="webking_get_dom_snapshot",
    annotations={
        "title": "Retrieve DOM Snapshot",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def webking_get_dom_snapshot(params: DomSnapshotInput) -> str:
    """Load a stored DOM snapshot."""
    session_dir = resolve_session_path(params.session_id, DEFAULT_SESSIONS_DIR)
    snapshot_path = session_dir / "dom" / params.snapshot_name
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot '{params.snapshot_name}' not found for session.")

    html = load_text(snapshot_path)
    if params.response_format == ResponseFormat.JSON:
        payload = {
            "session_id": params.session_id,
            "snapshot_name": params.snapshot_name,
            "html": html[:CHARACTER_LIMIT],
            "truncated": len(html) > CHARACTER_LIMIT,
        }
        return json.dumps(payload, indent=2)

    truncated = html
    if len(truncated) > CHARACTER_LIMIT:
        truncated = truncated[:CHARACTER_LIMIT] + "\n<!-- truncated -->"
    return truncated


@mcp.tool(
    name="webking_get_script_bundle",
    annotations={
        "title": "Fetch Captured Script",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def webking_get_script_bundle(params: ScriptContentInput) -> str:
    """Return the contents of a stored JavaScript bundle captured during a session."""
    session_dir = resolve_session_path(params.session_id, DEFAULT_SESSIONS_DIR)
    script_path = session_dir / "scripts" / params.script_name
    if not script_path.exists():
        raise FileNotFoundError(f"Script '{params.script_name}' not found.")
    content = load_text(script_path)
    if params.response_format == ResponseFormat.JSON:
        payload = {
            "session_id": params.session_id,
            "script_name": params.script_name,
            "content": content[:CHARACTER_LIMIT],
            "truncated": len(content) > CHARACTER_LIMIT,
        }
        return json.dumps(payload, indent=2)

    if len(content) > CHARACTER_LIMIT:
        content = content[:CHARACTER_LIMIT] + "\n/* truncated */"
    return content


@mcp.tool(
    name="webking_generate_userscript_stub",
    annotations={
        "title": "Generate Userscript Stub",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def webking_generate_userscript_stub(params: UserscriptStubInput) -> str:
    """Generate a Tampermonkey-compatible userscript skeleton based on session artifacts."""
    session_dir = resolve_session_path(params.session_id, DEFAULT_SESSIONS_DIR)
    manifest = load_manifest(session_dir / "manifest.json")
    network_entries = []
    try:
        network_entries = _load_network_entries(session_dir)
    except FileNotFoundError:
        pass

    script_comment_lines = [f"Target: {manifest.target_url}", f"Session: {manifest.session_id}"]
    if manifest.recipe:
        script_comment_lines.append(f"Recipe: {manifest.recipe}")
    if manifest.summary:
        script_comment_lines.append(f"Notes: {manifest.summary}")

    key_endpoints: list[str] = []
    for entry in network_entries[:10]:
        key_endpoints.append(f"{entry['method']} {entry['url']}")

    network_hook_block = ""
    if params.include_network_hooks and key_endpoints:
        hook_lines = [
            "// Example fetch hook capturing request bodies",
            "const originalFetch = window.fetch;",
            "window.fetch = async (...args) => {",
            "  const response = await originalFetch(...args);",
            "  console.log('[WebKing] fetch call', args[0]);",
            "  return response;",
            "};",
        ]
        network_hook_block = "\n  ".join(hook_lines)

    storage_hook_block = ""
    if params.include_storage and manifest.artifact_index.storage:
        storage_hook_block = textwrap.dedent(
            """
            // Example helper to inspect storage snapshot captured by WebKing.
            function logCapturedStorage() {
              console.table(WEBKING_STORAGE_STATE.cookies || []);
              console.log('Local Storage:', WEBKING_STORAGE_STATE.origins?.[0]?.localStorage);
            }
            """
        ).strip()

    header_block = textwrap.dedent(
        f"""
        // ==UserScript==
        // @name         WebKing Stub - {manifest.session_id}
        // @namespace    https://webking.local/
        // @match        {manifest.target_url}
        // @grant        none
        // ==/UserScript==

        (function() {{
          'use strict';

          const WEBKING_METADATA = {json.dumps(script_comment_lines, indent=2)};
          const KEY_ENDPOINTS = {json.dumps(key_endpoints, indent=2)};
        """
    ).strip()

    footer_block = textwrap.dedent(
        """
          console.info('[WebKing] Userscript stub loaded', WEBKING_METADATA);
        })();
        """
    ).strip()

    script_sections = [header_block]
    if network_hook_block:
        script_sections.append("  " + network_hook_block)
    if storage_hook_block:
        script_sections.append("  " + storage_hook_block)
    script_sections.append(footer_block)

    script_body = "\n\n".join(script_sections)
    if params.response_format == ResponseFormat.JSON:
        payload = {
            "session_id": params.session_id,
            "userscript": script_body[:CHARACTER_LIMIT],
            "truncated": len(script_body) > CHARACTER_LIMIT,
        }
        return json.dumps(payload, indent=2)

    if len(script_body) > CHARACTER_LIMIT:
        script_body = script_body[:CHARACTER_LIMIT] + "\n// truncated"
    return script_body


@mcp.tool(
    name="webking_summarize_session",
    annotations={
        "title": "Summarize Session",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def webking_summarize_session(params: SessionScopedInput) -> str:
    """Summarize the captured artifacts for a session."""
    session_dir = resolve_session_path(params.session_id, DEFAULT_SESSIONS_DIR)
    manifest = load_manifest(session_dir / "manifest.json")
    capture_summary_path = session_dir / "analysis" / "capture_summary.json"

    if capture_summary_path.exists():
        capture_summary = load_json(capture_summary_path)
    else:
        capture_summary = {
            "session_id": manifest.session_id,
            "counts": {
                "network_entries": len(manifest.artifact_index.network),
                "script_bundles": len(manifest.artifact_index.scripts),
                "dom_snapshot": bool(manifest.artifact_index.dom),
                "storage_captured": bool(manifest.artifact_index.storage),
            },
            "recipes": [],
        }

    summary = build_session_summary(manifest, capture_summary, manifest.artifact_index)
    if params.response_format == ResponseFormat.JSON:
        payload = {
            "headline": summary.headline,
            "details": summary.details,
        }
        return json.dumps(payload, indent=2)
    return summary.as_markdown()


if __name__ == "__main__":
    mcp.run()
