# Architecture

## Stage 1 Direction

CML is being built as a local desktop app with a React UI, an Electron shell, and a local Python backend service.

Electron is the first desktop shell choice because Node is already available in the development environment and Rust is not currently installed. This keeps the first runnable desktop build close. Tauri remains a future option if installer size and memory footprint become a bigger priority.

## Workspaces

- `apps/desktop`: Electron + React desktop app.
- `backend`: local Python service for vault indexing, clustering, retrieval, expert training, model orchestration, and Context Bridge.
- `docs`: product, UI, project context, and architecture documents.
- `UI-CML-V0`: preserved reference copy of the initial UI prototype.

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
