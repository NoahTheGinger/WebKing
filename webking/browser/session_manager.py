"""Playwright-based session capture for WebKing."""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, validator
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_fixed

from webking.artifacts import (
    ArtifactIndex,
    ArtifactMeta,
    ArtifactPaths,
    SessionManifest,
    build_artifact_paths,
    persist_json,
    persist_text,
    save_manifest,
    slugify_session_name,
)

CHARACTER_LIMIT = 25_000


class CaptureOptions(BaseModel):
    """Flags describing which artifacts to capture during a session."""

    model_config = ConfigDict(extra="forbid")

    capture_dom: bool = Field(default=True, description="Capture DOM snapshot after navigation.")
    capture_network: bool = Field(default=True, description="Record network requests/responses.")
    capture_scripts: bool = Field(
        default=True,
        description="Persist fetched JavaScript bundle bodies when available.",
    )
    capture_storage: bool = Field(
        default=True,
        description="Capture local/session storage and cookies after session completes.",
    )


class BrowserLaunchOptions(BaseModel):
    """Playwright browser launch options."""

    model_config = ConfigDict(extra="forbid")

    headless: bool = Field(
        default=True,
        description="Run Chromium in headless mode. Set false for debugging/visual runs.",
    )
    slow_mo_ms: int | None = Field(
        default=None,
        description="Optional slow-mo delay between actions to help ensure network settles.",
        ge=0,
        le=5_000,
    )
    timeout_ms: int = Field(
        default=45_000,
        description="Default timeout for navigation and wait operations.",
        ge=5_000,
        le=120_000,
    )


class SessionConfig(BaseModel):
    """Top-level configuration for a session capture."""

    model_config = ConfigDict(extra="forbid")

    target_url: HttpUrl = Field(description="Initial URL to open during the session.")
    recipe: str | None = Field(
        default=None,
        description="Optional recipe identifier controlling scripted steps.",
    )
    cookies: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional list of cookie dicts to set before navigation.",
    )
    extra_headers: dict[str, str] | None = Field(
        default=None,
        description="Optional headers to add to every request.",
    )
    capture: CaptureOptions = Field(default_factory=CaptureOptions)
    browser: BrowserLaunchOptions = Field(default_factory=BrowserLaunchOptions)
    notes: str | None = Field(default=None, description="Optional free-form notes stored in manifest.")

    @validator("cookies")
    def validate_cookies(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, list):
            raise ValueError("cookies must be a list of Playwright cookie dictionaries")
        return value


@dataclass(slots=True)
class SessionResult:
    """Result of running a session."""

    manifest: SessionManifest
    artifact_paths: ArtifactPaths
    capture_summary: dict[str, Any]


async def _attach_network_listeners(
    page: Page,
    capture_scripts: bool,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Attach listeners to capture network requests & script bodies."""
    network_log: list[dict[str, Any]] = []
    script_payloads: dict[str, str] = {}

    async def handle_request_finished(request) -> None:
        try:
            response = await request.response()
            if response is None:
                return

            entry: dict[str, Any] = {
                "url": request.url,
                "method": request.method,
                "headers": await request.all_headers(),
                "post_data": request.post_data,
                "resource_type": request.resource_type,
                "status": response.status,
                "status_text": response.status_text(),
                "response_headers": await response.all_headers(),
                "request_timing": request.timing,
            }

            if capture_scripts:
                content_type = (await response.header_value("content-type")) or ""
                if "javascript" in content_type or request.url.endswith((".js", ".mjs")):
                    try:
                        text = await response.text()
                        total_length = len(text)
                        if total_length > CHARACTER_LIMIT:
                            text = (
                                text[:CHARACTER_LIMIT]
                                + f"\\n/* truncated {total_length - CHARACTER_LIMIT} chars */"
                            )
                        script_payloads[request.url] = text
                        entry["captured_script"] = True
                    except Exception:
                        entry["captured_script"] = False

            network_log.append(entry)
        except Exception:  # pragma: no cover - best effort capture
            return

    page.on("requestfinished", lambda request: asyncio.create_task(handle_request_finished(request)))
    return network_log, script_payloads


async def _capture_storage(context: BrowserContext) -> dict[str, Any]:
    """Extract local/session storage and cookies."""
    storage_state = await context.storage_state()
    return storage_state


async def _run_recipe(page: Page, recipe_name: str | None) -> list[dict[str, Any]]:
    """Execute a scripted recipe against the page, returning step logs."""
    # Placeholder - future extension. For now, simply log that no recipe was executed.
    steps: list[dict[str, Any]] = []
    if recipe_name:
        steps.append(
            {
                "recipe": recipe_name,
                "status": "noop",
                "message": "Recipe support not yet implemented; manual navigation required.",
            }
        )
    return steps


@asynccontextmanager
async def _launch_browser(
    launch_options: BrowserLaunchOptions,
) -> AsyncIterator[tuple[Browser, Any]]:
    """Launch Playwright and yield an active browser instance."""
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=launch_options.headless,
        slow_mo=launch_options.slow_mo_ms,
    )
    try:
        yield browser, playwright
    finally:
        await browser.close()
        await playwright.stop()


class SessionManager:
    """Orchestrates browser sessions and artifact capture."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir

    async def run_session(self, config: SessionConfig) -> SessionResult:
        """Launch a browser session, capture artifacts, and persist manifest."""
        timestamp = time.time()
        session_slug = slugify_session_name(str(config.target_url), timestamp)

        paths = build_artifact_paths(session_slug, base_dir=self.base_dir)
        manifest = SessionManifest(
            session_id=session_slug,
            target_url=str(config.target_url),
            recipe=config.recipe,
            created_at=timestamp,
            summary=config.notes,
        )

        async with _launch_browser(config.browser) as (browser, _playwright):
            context = await browser.new_context()

            if config.extra_headers:
                await context.set_extra_http_headers(config.extra_headers)
            if config.cookies:
                await context.add_cookies(config.cookies)

            page = await context.new_page()
            page.set_default_timeout(config.browser.timeout_ms)

            network_log: list[dict[str, Any]] = []
            script_payloads: dict[str, str] = {}
            if config.capture.capture_network:
                network_log, script_payloads = await _attach_network_listeners(
                    page, capture_scripts=config.capture.capture_scripts
                )

            # Navigate with retries to handle flaky loads.
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_fixed(3),
                retry=retry_if_exception_type(Exception),
            ):
                with attempt:
                    await page.goto(str(config.target_url), wait_until="networkidle")

            recipe_steps = await _run_recipe(page, config.recipe)

            dom_snapshot: str | None = None
            if config.capture.capture_dom:
                dom_snapshot = await page.content()
                persist_text(paths.dom_dir / "snapshot.html", dom_snapshot)
                manifest.artifact_index.dom.append(
                    ArtifactMeta(
                        type="dom_snapshot",
                        path=str(Path("dom") / "snapshot.html"),
                        description="Full HTML snapshot after navigation.",
                        content_type="text/html",
                    )
                )

            if config.capture.capture_network:
                persist_json(paths.network_dir / "network_log.json", network_log)
                manifest.artifact_index.network.append(
                    ArtifactMeta(
                        type="network_log",
                        path=str(Path("network") / "network_log.json"),
                        description="Captured request/response metadata for the session.",
                        content_type="application/json",
                    )
                )

            if config.capture.capture_scripts and script_payloads:
                for idx, (url, payload) in enumerate(script_payloads.items(), start=1):
                    slug = f"bundle_{idx:03d}.js"
                    persist_text(paths.scripts_dir / slug, payload)
                    manifest.artifact_index.scripts.append(
                        ArtifactMeta(
                            type="script_bundle",
                            path=str(Path("scripts") / slug),
                            description=f"JavaScript bundle fetched from {url}",
                            content_type="application/javascript",
                        )
                    )

            storage_state: dict[str, Any] | None = None
            if config.capture.capture_storage:
                storage_state = await _capture_storage(context)
                persist_json(paths.storage_dir / "storage_state.json", storage_state)
                manifest.artifact_index.storage.append(
                    ArtifactMeta(
                        type="storage_state",
                        path=str(Path("storage") / "storage_state.json"),
                        description="Local/session storage & cookies post-session.",
                        content_type="application/json",
                    )
                )

            await context.close()

        capture_summary: dict[str, Any] = {
            "session_id": session_slug,
            "target_url": str(config.target_url),
            "recipes": recipe_steps,
            "counts": {
                "network_entries": len(network_log),
                "script_bundles": len(script_payloads),
                "dom_snapshot": bool(dom_snapshot),
                "storage_captured": bool(storage_state),
            },
        }

        persist_json(paths.analysis_dir / "capture_summary.json", capture_summary)
        save_manifest(manifest, paths.manifest_path)
        return SessionResult(manifest=manifest, artifact_paths=paths, capture_summary=capture_summary)


__all__ = [
    "SessionManager",
    "SessionConfig",
    "CaptureOptions",
    "BrowserLaunchOptions",
    "SessionResult",
]
