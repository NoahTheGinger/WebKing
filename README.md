# WebKing 🕸️👑

An MCP-powered laboratory for reverse-engineering modern web applications. WebKing pairs a Playwright-driven capture pipeline with rich MCP tools so an LLM (or you) can:

- Launch reproducible browser sessions that collect network logs, DOM snapshots, storage dumps, and script bundles
- Analyze captured traffic for high-signal endpoints and payload patterns
- Extract prettified JavaScript bundles and generate Tampermonkey-ready userscript stubs
- Summarize each session’s key findings and keep everything organized for iterative deep dives

> **Status**: MVP — the scaffolding is complete and ready for experimentation. Extend it with custom recipes, analyzers, or storage adaptors to suit your reverse-engineering style.

---

## Features

- 🌐 **Headless capture** — Playwright-based sessions with optional recipes, cookies, headers, and selective artifact capture
- 📁 **Session vault** — Structured artifact tree (`sessions/<id>/`) plus manifest metadata for quick discovery
- 🔍 **Network insights** — Filter and aggregate captured requests/responses (hosts, methods, payload previews)
- 🧠 **Summaries & stubs** — Heuristic session summaries and Tampermonkey skeletons seeded with captured insights
- 🧰 **Extensible analyzers** — Modular architecture for adding new content inspectors (GraphQL, WebSocket, etc.)

---

## Getting Started

1. **Install dependencies**

   ```bash
   pip install .
   playwright install chromium
   ```

2. **Run the MCP server (stdio transport)**

   ```bash
   python webking_mcp.py
   ```

   Or point the evaluation harness at it:

   ```bash
   python scripts/evaluation.py \
     -t stdio \
     -c python \
     -a webking_mcp.py \
     my_eval.xml
   ```

3. **Call tools**

   - `webking_launch_session` — capture a new browsing session
   - `webking_list_sessions` — browse recorded runs
   - `webking_get_network_insights` — filter and summarize traffic
   - `webking_get_dom_snapshot` / `webking_get_script_bundle` — pull raw artifacts
   - `webking_generate_userscript_stub` — bootstrap a Tampermonkey script
   - `webking_summarize_session` — quick human-readable recap

---

## Project Structure

```
webking_mcp.py             # FastMCP server with tool definitions
webking/
  browser/session_manager.py  # Playwright orchestration & capture
  artifacts/storage.py        # Manifest + artifact persistence helpers
  analyzers/                  # Network & summary heuristics
docs/architecture.md          # High-level system design
sessions/                     # Populated at runtime with captured artifacts
```

---

## Extending WebKing

- **Recipes**: Implement scripted flows inside `SessionManager._run_recipe` (e.g., login sequences)
- **Analyzers**: Add modules under `webking/analyzers/` for bundle dissection, GraphQL schema inference, etc.
- **Outputs**: Introduce additional tools for exporting results (e.g., to Markdown reports or obsidian vaults)

Pull requests, forks, and wild experiments welcome.

---

## License

Apache 2.0 — see `LICENSE.txt`.
