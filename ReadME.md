Context Management Layer: local-first desktop AI workspace for turning a user's vault of files, links, screenshots, notes, and chat transcripts into clustered context, searchable source memory, compulsory per-cluster local experts, and structured context packets that can feed a larger synthesis model or external local LLM tools through a Context Bridge.

## Repo map

- `apps/desktop/` - Electron desktop shell and React/TanStack UI adapted from the V0 prototype.
- `backend/` - local FastAPI service for vaults, clusters, sources, bridge requests, and future ingestion/model jobs.
- `docs/PRODUCT_PRD.md` - product requirements for the local Context Management Layer.
- `docs/UI_PRD.md` - UI requirements for the chat-centered desktop workspace, map, sources, clusters, and bridge.
- `docs/PROJECT_CONTEXT.md` - living progress file with phase progress bars, week-by-week goals, completed work, and open work.
- `docs/ARCHITECTURE.md` - current architecture notes for the desktop app, backend, storage, bridge, and model lifecycle.
- `UI-CML-V0/` - preserved first UI prototype/reference; useful for visual direction, not the production workspace.
- `data/` - ignored local runtime data, SQLite database files, and development vault artifacts.

## Product shape

The app is designed as a local downloadable desktop app, not a web-first product. V1 uses vault mode: the user explicitly chooses a local vault and adds files, folders, links, pasted text, screenshots, notes, and chat transcripts. The system stores source metadata locally, extracts text, clusters related material, and makes those clusters available to chat.

The core product contract is:

- Chat stays at the center of the workspace.
- Sources remain inspectable and removable.
- Clusters are user-correctable spaces of context.
- Every cluster has a visible local expert lifecycle.
- Retrieval-backed context works before expert fine-tuning is ready.
- The Context Bridge lets other local LLM tools ask the vault for selected context.

## Current state

Stage 1 is in progress. The repo currently has a working Electron/Vite desktop workspace, a local FastAPI backend, SQLite-backed CRUD routes for vaults/clusters/sources, TXT/Markdown/DOCX/PDF/pasted-text/link ingestion, drag-and-drop document import in the desktop shell, local synced-folder import for Drive/Dropbox/OneDrive/iCloud-style folders, per-file batch import failure reporting, generated source summaries/tags, link title/image metadata, local chunk/embedding storage, semantic search, vector-based cluster move suggestions, retrieval-grounded chat context routing with citations, persisted chat sessions, local model registry/runtime endpoints, a bridge status/request API, backend-aware Settings/Sources/Clusters/Chat screens, and a redesigned map prototype with cluster anchors, unlabeled data points, hover previews, and in-map cluster detail.

The next major build target is improving chat synthesis and wiring Context Bridge to semantic retrieval.

## Prerequisites

- Node.js 18+.
- Python 3.11+ recommended for future ML libraries. The current environment is using Python 3.14 for the lightweight backend.
- Windows is the first development target.
- Optional later dependencies: local model runtime, embedding model, and OCR libraries.

Recommended Python virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Install frontend dependencies:

```bash
npm install
```

Install backend dependencies if the virtual environment is new:

```bash
pip install fastapi uvicorn pydantic pydantic-settings
```

The backend reads local settings from the root `.env` file. Use `.env.example` as the committed template and keep machine-specific values in `.env`.

## Quick start: local development

Run the backend:

```bash
npm run backend
```

Run the desktop app:

```bash
npm run dev
```

Useful checks:

```bash
curl http://127.0.0.1:7343/health
curl http://127.0.0.1:7343/api/v1/vaults
curl http://127.0.0.1:7343/api/v1/sources
curl http://127.0.0.1:7343/api/v1/bridge/status
```

The Vite development view is available at:

```text
http://127.0.0.1:5173/
```

The Electron shell opens the same local UI through `npm run dev`.

## Backend API surface

- `GET /health` - backend health.
- `GET /api/v1/vaults` - list local vault records.
- `POST /api/v1/vaults` - create a vault record.
- `GET /api/v1/vaults/{vault_id}` - fetch one vault.
- `PATCH /api/v1/vaults/{vault_id}` - update vault name/path.
- `DELETE /api/v1/vaults/{vault_id}` - remove a vault record.
- `GET /api/v1/clusters` - list clusters, optionally by `vault_id`.
- `POST /api/v1/clusters` - create a cluster.
- `GET /api/v1/clusters/{cluster_id}` - fetch one cluster.
- `PATCH /api/v1/clusters/{cluster_id}` - update cluster metadata or expert status.
- `DELETE /api/v1/clusters/{cluster_id}` - remove a cluster.
- `GET /api/v1/sources` - list sources, optionally by `vault_id` or `cluster_id`.
- `POST /api/v1/sources` - create a source record.
- `POST /api/v1/sources/from-path` - import a local TXT/Markdown/DOCX/PDF file path.
- `POST /api/v1/sources/from-text` - import pasted text.
- `POST /api/v1/sources/from-url` - fetch and import readable link text.
- `GET /api/v1/sources/{source_id}` - fetch one source.
- `PATCH /api/v1/sources/{source_id}` - update source assignment, text, state, or summary.
- `DELETE /api/v1/sources/{source_id}` - remove a source.
- `POST /api/v1/search/semantic` - search indexed source chunks by local semantic similarity.
- `POST /api/v1/search/reindex/{vault_id}` - rebuild local search chunks for indexed sources.
- `GET /api/v1/clusters/suggestions` - review vector-based source-to-cluster move suggestions.
- `POST /api/v1/chat/context` - build a retrieval-grounded chat draft with clusters used and citations.
- `GET /api/v1/models` - list recommended local model options and install status.
- `GET /api/v1/models/runtime` - check whether a local OpenAI-compatible model runtime is reachable.
- `GET /api/v1/models/embeddings` - inspect the active local embedding provider.
- `POST /api/v1/models/embeddings/configure` - switch between hash embeddings and optional SentenceTransformers/MiniLM.
- `GET /api/v1/models/{model_id}` - inspect one model option.
- `POST /api/v1/models/{model_id}/download` - start an explicit GGUF model download into local app data.
- `POST /api/v1/models/{model_id}/download/cancel` - cancel an active GGUF model download and clean up the partial file.
- `GET /api/v1/bridge/status` - Context Bridge status.
- `POST /api/v1/bridge/context` - request selected context for an external local client.
- `GET /api/v1/bridge/requests` - recent bridge request history.

## Development workflow

Frontend build:

```bash
npm run build
```

Backend syntax check:

```bash
.venv\Scripts\python -m compileall backend\app
```

Current progress is tracked in `docs/PROJECT_CONTEXT.md`. At the end of each task, update the progress bars, completed work, open work, and important running notes.

## Context Bridge

The bridge is the external access layer. It is intended to let tools like local Claude terminal workflows, MCP-compatible clients, CLIs, or developer tools request selected vault context without exposing the full vault by default.

Planned bridge surfaces:

- MCP server for compatible AI tools.
- Local HTTP API for developer workflows.
- CLI for terminal use.
- Copy-context helper for manual paste.

V1 bridge work currently has status, request logging, semantic retrieval, permissions, and first CLI/MCP prototypes. Per-client setup and deeper MCP client testing are still open.

Current development helpers:

```powershell
$env:CML_BRIDGE_TOKEN="token-from-bridge-settings"
.\scripts\bridge\cml-bridge.ps1 "retrieve context for my assignment"
.venv\Scripts\python.exe -m backend.app.bridge_mcp
```

## Local expert model plan

Current synthesis model ladder:

- Qwen3-4B Q4_K_M as the default local synthesis model.
- Phi-4-mini-instruct Q4_K_M as the low-spec fallback.
- Qwen3-8B Q4_K_M as the higher-quality option.
- Gemma 3 4B/12B Q4_K_M as optional later candidates.

The app should not bundle model weights in the first installer. Model downloads are explicit and stored under local app data. Chat can call a local OpenAI-compatible endpoint when configured in `.env`:

```bash
CML_LLM_PROVIDER=openai-compatible
CML_LLM_BASE_URL=http://127.0.0.1:8084/v1
CML_LLM_MODEL=cml-local
```

If no local model runtime is configured or reachable, chat keeps using the retrieval-grounded extractive draft fallback.

For local Windows GGUF testing:

```powershell
.\scripts\llm\download-llama-cpp.ps1
.\scripts\llm\start-llama-server.ps1 -ModelId qwen3-4b-q4_k_m
.\scripts\llm\test-local-model.ps1
```

For NVIDIA CUDA testing on Windows:

```powershell
.\scripts\llm\download-llama-cpp.ps1 -Runtime cuda -CudaVersion 12.4
.\scripts\llm\start-llama-server.ps1 -Runtime cuda -ModelId qwen3-4b-q4_k_m
.\scripts\llm\benchmark-local-models.ps1 -Runtime cuda
```

The current local test machine stores downloaded GGUFs under `T:\LLM` via `CML_MODELS_DIR`. Use `.\scripts\llm\benchmark-local-models.ps1` to compare the downloaded model ladder through llama.cpp.

Every cluster must have a local expert lifecycle. For V1, the practical approach is:

- Use retrieval and style profiles immediately so clusters are useful before fine-tuning.
- Maintain expert status records for every cluster: Setting up, Learning, Ready, Needs update, Paused, Issue.
- Treat fine-tuning as a queued background job, not a blocking chat dependency.
- Start with lightweight adapter artifacts and reproducible local training experiments.
- Feed expert outputs plus retrieved citations into a larger synthesis model.

The riskiest project area is local fine-tuning under free, reproducible, lightweight constraints. Retrieval-backed bootstrapping keeps the product usable while that system matures.

## Notes and defaults

- This is local-first and offline-first where possible.
- V1 should avoid silent full-device scanning. Users explicitly choose vaults/folders/files.
- `data/`, `.venv/`, generated build output, logs, and local databases should stay ignored.
- Electron is the pragmatic first shell. Tauri can be reconsidered after the core flow is proven.
- The first packaging target is Windows, then macOS/Linux.
