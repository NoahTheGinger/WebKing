# WebKing MCP Server Architecture

> **Status:** this is the design document. `webking_get_source_map` and `webking_analyze_entrypoints` (tools 5 and 6 below) and YAML session recipes are planned but not implemented yet. See the README for the tools available today.

## Overview

This document outlines the architecture for the WebKing MCP server, designed to help users reverse engineer web applications by integrating an LLM with tools that capture critical runtime signals (network requests, code, DOM state, storage) in a structured, repeatable way.

## Core Goals

1. Rapidly capture actionable context from target web apps (network, source, DOM, storage).
2. Provide configurable headless-browser workflows to reproduce sessions consistently.
3. Offer tooling for LLM orchestration, enabling multi-step analysis and summarization.
4. Expose results through stable MCP tools with both markdown and JSON outputs.
5. Persist session artifacts so humans or agents can revisit findings anytime.

## High-Level Components

- **Browser Orchestrator** (Playwright-based)
  - Launch and manage Chromium sessions (headless/headful).
  - Expose configurable navigation flows (URL, cookies, auth headers).
  - Capture network traffic, DOM snapshots, and storage.

- **Artifact Store**
  - Structured directory per session storing network logs, DOM dumps, script bundles, etc.
  - Indexed manifest for quick retrieval (IDs + metadata).

- **Analysis Engine**
  - Parsers for network logs (group by endpoint, detect GraphQL/REST, infer payload structure).
  - JS bundle inspector (pretty-print/minification aware, find exported functions, heuristics for entry points).
  - DOM/state diff utilities for before/after interactions.
  - Session summarizers powered by the connected LLM.

- **MCP Tool Layer**
  - Tools to orchestrate sessions, retrieve artifacts, run analyses, and generate LLM-ready briefs.
  - JSON Schema validation (Pydantic) to ensure precise inputs.
  - Rich docstrings describing workflows, outputs, and limits.

- **Session Recipes**
  - The server ships with reusable recipes (YAML) describing navigation & actions required to reach interesting app states (e.g., login, open specific dashboard).
  - Users can author new recipes to automate repetitive setups.

## Key MCP Tools

1. **webking_launch_session**
   - Arguments: target URL, optional auth headers/cookies, recipe reference, capture options.
   - Behavior: spin up Playwright session, execute recipe, capture full artifact set.
   - Output: session ID, summary of captured artifacts, warnings/errors.

2. **webking_list_sessions**
   - List stored sessions with metadata (timestamp, domain, recipe, notes).

3. **webking_get_network_insights**
   - Filter by session, domain, path pattern, method, status range.
   - Summaries: grouped endpoints, typical payload shapes, suspected auth tokens.

4. **webking_get_dom_snapshot**
   - Retrieve DOM snapshot for a session state (initial vs post-recipe steps).

5. **webking_get_source_map**
   - Access prettified JS bundle segments, highlight exports, references, and suspected module boundaries.

6. **webking_analyze_entrypoints**
   - Heuristic analysis of SPA routers, API clients, and key functions.
   - LLM-assisted commentary pointing towards likely extension hook points.

7. **webking_generate_userscript_stub**
   - Based on artifacts & heuristics, produce Tampermonkey-compatible skeleton with instrumentation hooks and TODO sections tailored to the session findings.

8. **webking_summarize_session**
   - LLM summary of the session: main API patterns, critical JS modules, suggested next steps.
   - Output includes call graph hints, storage usage, security headers, etc.

## Data Flow

1. **Launch Session**
   1. User invokes webking_launch_session with URL and recipe.
   2. Playwright orchestrator runs the flow, capturing artifacts.
   3. Artifacts persisted to /sessions/<session_id>/... with index JSON.

2. **Explore Artifacts**
   - Other tools reference the session manifest to retrieve and analyze stored data without re-running the browser.
   - Analyses produce markdown & JSON results for direct consumption or further processing.

3. **Iterative Reverse Engineering**
   - Re-run sessions with modified recipes, compare diffs.
   - Use summarizer to highlight newly discovered endpoints or modules.
   - Generate updated userscript stub incorporating new findings.

## Technology Choices

- **Language**: Python 3.11+, leveraging FastMCP for rapid server scaffolding.
- **Browser Automation**: Playwright (async, robust cross-browser support).
- **Data Storage**: Local filesystem with JSON manifests; optional sqlite index for advanced queries.
- **Analysis**: Python libraries (beautifulsoup4, networkx, jsbeautifier, esprima via py_mini_racer) plus custom heuristics.

## Security & Ethics Considerations

- Tools are read-only: they capture and analyze but never attempt to modify remote targets.
- Recipes should be authored with respect for target terms of service and rate limits.
- Sessions run locally; no remote data exfiltration beyond user environment.
- Provide disclaimers encouraging responsible use.

## Extensibility

- Plugin system for new analyzers (e.g., GraphQL schema inference, WebSocket stream decoding).
- Custom recipe scripting (Python/JS) for complex multi-step flows.
- Optional integration with local proxies (mitmproxy) for deeper inspection.

## Next Steps

1. ~~Implement project scaffold with FastMCP server (webking_mcp.py).~~ Done.
2. ~~Build Playwright orchestration module (webking/browser/session_manager.py).~~ Done.
3. ~~Define artifact schemas and manifest handling (webking/artifacts).~~ Done.
4. ~~Implement initial set of MCP tools (launch, list, summarize).~~ Done.
5. Add advanced analyzers incrementally (bundle analysis, entry-point detection, GraphQL/WebSocket).
6. Implement session recipes (scripted login and navigation flows).

