# Architecture

## Stage 1 Direction

CML is being built as a local desktop app with a React UI, an Electron shell, and a local Python backend service.

Electron is the first desktop shell choice because Node is already available in the development environment and Rust is not currently installed. This keeps the first runnable desktop build close. Tauri remains a future option if installer size and memory footprint become a bigger priority.

## Workspaces

- `apps/desktop`: Electron + React desktop app.
- `backend`: local Python service for vault indexing, clustering, retrieval, model orchestration, Odin project context, and Context Bridge.
- `docs`: product, UI, project context, and architecture documents.
- `UI-ref`: preserved UI reference material outside the production workspace.

Key architecture references:

- [JOB_AND_MAINTENANCE_ARCHITECTURE.md](JOB_AND_MAINTENANCE_ARCHITECTURE.md) defines the target background job taxonomy, scheduler rules, dependency model, and startup recovery state transitions for ingestion, indexing, diagnostics, cleanup, and merge repair. Its legacy expert-training rows are historical and not part of the live RAG-only product.
- Odin project context is implemented through `backend/app/core/projects.py`, `backend/app/core/project_graph.py`, `backend/app/api/routes/projects.py`, and the desktop project workspace. Scoped authentication, asynchronous sync lifecycle, broader parser coverage, and supporting UI remain release work.

## Odin Project Context

Odin adds a project layer without creating a separate knowledge store. `projects` own a primary cluster, project sources remain ordinary encrypted/retrievable CML sources, and completed `project_snapshots` identify the structural graph queried by chat and CLI. `code_nodes` and `code_edges` store deterministic structure with source/line evidence; unresolved relationships stay in `relationship_suggestions` and are excluded from authoritative traversal.

Project chat persists `scope_project_id` and resolves it to the project's primary cluster before retrieval. Bridge context accepts `project_id`, and the authenticated project API exposes summary, node, neighbor, bounded path, and context operations.

## Runtime Shape

During development:

1. Electron launches the desktop window.
2. Vite serves the React UI on `127.0.0.1:5173`.
3. The Python backend runs on `127.0.0.1:7343` by default. The desktop shell can choose another open loopback port in the `7343-7355` range when needed.
4. The UI talks to the backend over local HTTP/WebSocket APIs.

In packaged builds:

1. Electron loads the bundled UI assets.
2. The app starts or connects to the bundled local backend service.
3. Runtime data stays under the selected local vault and app data directories.

## Context Layer Shape

Public V1 architecture should be understood as a layered context system, not only as storage plus retrieval:

1. Capture layer: files, links, OCR, internal chats, external conversations, and external artifacts enter the vault.
2. Evidence layer: sources, pages, chunks, embeddings, retrieval snapshots, and citations remain the source of truth.
3. Routing layer: chat defaults to vault retrieval for natural prompts, with direct chat reserved for explicit conversational/no-vault cases and graceful ungrounded fallback when retrieval has no usable context.
4. Memory layer: distilled facts, preferences, decisions, constraints, goals, and open loops are extracted from evidence.
5. Working-memory layer: compact vault/cluster summaries describe current state, recent changes, and next actions.
6. Packet layer: internal chat and Bridge/MCP should consume one shared token-budgeted context-packet builder that assembles memory plus evidence for the target prompt. Bridge/MCP should default to model-readable packet text with trust, citation, limit, and expansion instructions; raw JSON should be diagnostics-only.
7. Safety layer: chat synthesis should consume compact, trust-classified evidence packets through an extraction-first path, not large raw source blobs by default. Low-trust, conflicting, or insufficient evidence should downgrade or refuse synthesis explicitly.

This layered shape is required for the V1 claim that CML reduces context loss and token cost instead of only acting as a searchable vault.

## Local Model Runtime

The first implementation should use an external local runtime boundary rather than hard-coding one model library into chat logic. CML should talk to a local OpenAI-compatible endpoint first, with llama.cpp `llama-server` and Ollama as the practical adapters.

Initial model ladder:

1. Qwen3-4B Q4_K_M: default recommended synthesis model, roughly 2.3-2.5 GB.
2. Phi-4-mini-instruct Q4_K_M: low-spec fallback, roughly 2.5 GB.
3. Qwen3-8B Q4_K_M: higher-quality option, roughly 4.8 GB download and about 5.3 GB loaded weights.
4. Gemma 3 4B/12B Q4_K_M: optional later candidates for long-context or vision-adjacent experiments.

The first installer should not bundle model weights. The app should expose setup/status around model download or local runtime connection after the core app shell is stable.

## Near-Term Technical Priorities

1. Replace mock store data with backend-backed state.
2. Add desktop-native file/folder picking.
3. Implement vault creation/opening.
4. Add backend health status in the UI.
5. Add source ingestion API.
6. Add local storage schema.
