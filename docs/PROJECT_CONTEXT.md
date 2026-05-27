# Project Context And Progress

Last updated: 2026-05-27

## Project Goal

Build a local downloadable desktop app for a Context Management Layer. The app lets users create a local vault, add files/links/notes/screenshots/chat transcripts, cluster them by similarity, train a compulsory local expert for each cluster, and use those cluster experts to feed structured context into a larger synthesis model.

The target user is a general second-brain user. The product should feel like a full AI workspace where chat is central, supported by Mindly-like visual organization and an Obsidian-like graph/map.

Target completion: **end of July 2026**.

## Current Product Decisions

- App type: local downloadable desktop app, not a web app.
- V1 data mode: vault mode only. No full-device silent scanning.
- UI direction: chat-centered, welcoming, consumer second-brain experience.
- Cluster experts: compulsory for every cluster.
- Cluster expert behavior: expert lifecycle exists immediately; retrieval-backed bootstrapping can answer before fine-tuning completes.
- External integrations: Context Bridge via MCP, local HTTP API, CLI, and copy/export helpers.
- Privacy: local-first by default.
- Existing UI prototype: `UI-CML-V0/context-whisperer-suite-main`.
- First desktop shell: Electron, chosen because Node is available and Rust/Tauri tooling is not installed in the current environment.
- Real app workspace: `apps/desktop`.
- Local backend workspace: `backend`.

## Phase Progress

Progress bar legend:

- `[----------] 0%`
- `[#---------] 10%`
- `[##--------] 20%`
- `[###-------] 30%`
- `[####------] 40%`
- `[#####-----] 50%`
- `[######----] 60%`
- `[#######---] 70%`
- `[########--] 80%`
- `[#########-] 90%`
- `[##########] 100%`

| Phase | Status | Progress | Notes |
| --- | --- | --- | --- |
| Product definition | In progress | `[#####-----] 50%` | Product PRD, UI PRD, project context, and architecture doc created. Needs technical spike details. |
| UI prototype cleanup | In progress | `[######----] 60%` | V0 reviewed. Cross-platform shortcuts fixed. Map moved to a minimal cartographic atlas with in-tab cluster detail and hover previews. Needs broader chat/source/settings polish. |
| Desktop app foundation | In progress | `[######----] 60%` | Electron workspace created, frontend build passes, Vite dev server verified, file-opening IPC primitives added, and UI routes can call backend APIs. Needs Electron window verification and packaging. |
| Local backend foundation | In progress | `[######----] 60%` | SQLite config/storage foundation and CRUD route groups are working, with frontend API helpers now wired. Needs app-level services and tests. |
| Vault ingestion | In progress | `[###-------] 30%` | Source metadata/text records can be created and viewed from the Sources UI. TXT/Markdown path ingestion works. Needs PDF/DOCX/link/OCR extraction. |
| Embeddings and clustering | Not started | `[----------] 0%` | Need local embedding model, chunking, vector store, cluster suggestions. |
| Chat and context routing | Not started | `[----------] 0%` | Need router, retrieval, context packet builder, citations. |
| Compulsory cluster experts | Not started | `[----------] 0%` | Need expert lifecycle, training queue, local fine-tuning spike. |
| Context Bridge | In progress | `[####------] 40%` | Bridge UI route now reads backend status and request history. Needs MCP server, CLI, permissions, and semantic retrieval. |
| Packaging and installer | Not started | `[----------] 0%` | Need local downloadable build for Windows first, then macOS/Linux. |
| QA and hardening | Not started | `[----------] 0%` | Need tests, reliability checks, failure states, performance review. |

## Week-By-Week Goals

### Week 1: May 27 - May 31, 2026

Goal: lock project direction and convert V0 into a usable local-app foundation plan.

- Finalize product PRD and UI PRD.
- Add this project context/progress document.
- Review `UI-CML-V0` and identify UI cleanup requirements.
- Remove obvious Mac-only shortcut assumptions.
- Decide Tauri vs Electron for the desktop shell.
- Create architecture plan for desktop UI plus local backend.
- Define repo structure for the real app.
- Create first buildable desktop app workspace.
- Add first local backend skeleton.

Exit criteria:

- PRDs and project context are current.
- Desktop shell choice is documented.
- V0 issues are listed.
- Implementation repo structure is agreed.

### Week 2: June 1 - June 7, 2026

Goal: create the real app skeleton.

- Scaffold desktop app.
- Move or adapt V0 React UI into the app shell.
- Add basic app navigation: Chat, Clusters, Sources, Map, Search, Bridge, Settings.
- Add local backend service skeleton.
- Add local storage folder structure.
- Add health check between UI and backend.
- Add developer run command.

Exit criteria:

- App launches locally as a desktop app in dev mode.
- UI can detect backend status.
- Basic navigation works.

### Week 3: June 8 - June 14, 2026

Goal: implement vault mode and ingestion basics.

- Create/open local vault.
- Add files by picker and drag/drop.
- Add pasted text.
- Add links.
- Store raw source metadata in SQLite.
- Extract text from TXT, MD, DOCX, PDF.
- Add source processing states.
- Show source list and extracted preview in UI.

Exit criteria:

- User can create a vault and add mixed source items.
- Extracted text is visible in the app.
- Failed extraction has a visible error state.

### Week 4: June 15 - June 21, 2026

Goal: add embeddings, vector search, and cluster suggestions.

- Add local embedding model.
- Chunk extracted text.
- Store embeddings in local vector store.
- Implement semantic search.
- Suggest clusters based on similarity.
- Let user confirm, rename, merge, and move items.
- Add cluster summaries and tags.

Exit criteria:

- User can drop a batch of files and get suggested clusters.
- User can search globally and inside a cluster.
- Cluster/source assignment is editable.

### Week 5: June 22 - June 28, 2026

Goal: make chat work with real local context.

- Implement chat sessions.
- Implement prompt routing to cluster(s).
- Retrieve relevant chunks from selected clusters.
- Build context packets.
- Generate answer through selected model runtime.
- Show citations/source snippets.
- Let user manually override cluster routing.

Exit criteria:

- User can ask a question and receive an answer grounded in local sources.
- UI shows clusters and sources used.
- User can ask within one selected cluster.

### Week 6: June 29 - July 5, 2026

Goal: implement compulsory cluster expert lifecycle.

- Add cluster expert records and statuses.
- Add expert state UI: Setting up, Learning, Ready, Needs update, Paused, Issue.
- Define training data format.
- Implement first local training/fine-tuning spike.
- Add training queue and model lock.
- Keep expert versions and rollback metadata.

Exit criteria:

- Every cluster has an expert lifecycle record.
- At least one cluster can run a local expert training job.
- Failed training does not break cluster chat.

### Week 7: July 6 - July 12, 2026

Goal: connect cluster experts into the answer pipeline.

- Implement `ask_cluster_expert`.
- Produce structured expert context packets.
- Feed expert outputs into final synthesis model.
- Add style profile extraction and usage.
- Add answer feedback: useful/not useful.
- Add "add answer to cluster memory".
- Mark clusters stale when new data arrives.

Exit criteria:

- User can request a cluster style and get answers shaped by that cluster.
- Final answer uses cluster expert output plus retrieved citations.
- Cluster expert status affects routing transparency.

### Week 8: July 13 - July 19, 2026

Goal: implement Context Bridge and improve the workspace UI.

- Add Bridge page.
- Add local HTTP context API.
- Add CLI context retrieval.
- Add MCP server prototype.
- Add bridge permissions.
- Add recent external request log.
- Improve chat, clusters, sources, and map UI polish.

Exit criteria:

- External client can list clusters and request context.
- Terminal user can retrieve context through CLI.
- Bridge can be enabled/disabled from UI.

### Week 9: July 20 - July 26, 2026

Goal: package and harden the app.

- Build local downloadable app package.
- Add first-run setup flow.
- Add model download/setup flow if needed.
- Add indexing reliability checks.
- Add disk space checks.
- Add local backend restart/reconnect behavior.
- Run UX pass to reduce prototype/AI-generated feel.
- Add basic automated tests.

Exit criteria:

- App can be installed and launched locally.
- Core flow works from fresh install to first grounded answer.
- Main error states are visible and recoverable.

### Final Buffer: July 27 - July 31, 2026

Goal: stabilize the July-end build.

- Fix critical bugs.
- Improve performance on representative hardware.
- Verify ingestion with 100 mixed items.
- Verify chat with selected and auto-routed clusters.
- Verify one local expert training run.
- Verify Context Bridge basic flow.
- Prepare demo script and known limitations.

Exit criteria:

- A demoable local desktop build exists.
- The app demonstrates vault ingestion, clustering, chat, cluster experts, and Context Bridge.
- Known limitations are documented.

## Current Completed Work

- Created [PRODUCT_PRD.md](PRODUCT_PRD.md).
- Created [UI_PRD.md](UI_PRD.md).
- Added Context Bridge requirements to both PRDs.
- Reviewed `UI-CML-V0`.
- Updated visible shortcut labels from Mac-only to cross-platform wording.
- Added cross-platform shortcut handlers in the V0 app shell for:
  - Ctrl/Cmd K: command palette
  - Ctrl/Cmd N: new chat
  - Ctrl/Cmd Shift N: new cluster
  - Ctrl/Cmd L: sources/add link area
  - Ctrl/Cmd O: settings/open vault area
  - Ctrl/Cmd Enter: send message hint
- Created root npm workspace.
- Created `apps/desktop` as the real Electron desktop workspace, copied from the V0 UI.
- Added Electron `main` and `preload` entry points.
- Added root `npm run dev`, `npm run build`, `npm run lint`, and `npm run backend` scripts.
- Added `backend` FastAPI skeleton with `/health`.
- Added [ARCHITECTURE.md](ARCHITECTURE.md).
- Installed Node workspace dependencies.
- Verified desktop UI production build with `npm run build`.
- Started and verified the desktop UI dev server at `http://127.0.0.1:5173`.
- Verified backend Python syntax with `python -m compileall backend`.
- Added root `.gitignore` patterns for Lovable-generated metadata and folders.
- Added backend health hook in the desktop UI.
- Added Bridge navigation and command palette entry.
- Added first Bridge page with MCP, CLI, copy-context, privacy, and backend status sections.
- Removed obvious Lovable-generated root page metadata from the copied app.
- Added local SVG favicon and verified browser console errors are clear.
- Created `.venv` and installed backend dependencies.
- Updated `npm run backend` to use the local virtual environment.
- Started backend at `http://127.0.0.1:7342` and verified `/health`.
- Verified `/bridge` in browser with Playwright; page loads and shows `Backend online`.
- Added ignore rules for Playwright verification artifacts and Python editable-install metadata.
- Added backend settings via `CML_` environment prefix.
- Added SQLite initialization for vaults, clusters, sources, and bridge request logs.
- Added `/api/v1/vaults` list/create/get routes.
- Added `/api/v1/clusters` list/create routes.
- Added `/api/v1/sources` list/create routes.
- Added `/api/v1/bridge/status` and `/api/v1/bridge/context` routes.
- Restarted the backend cleanly after route changes.
- Ran backend compile check with `.venv\Scripts\python -m compileall backend\app`.
- Smoke-tested API flow: create vault, create cluster, create source, request bridge context.
- Replaced the juvenile force-directed map with a calmer deterministic context landscape.
- Added crisp cluster nodes, source pills, subtle SVG relationship lines, soft grid, and a cluster health rail.
- Verified the redesigned `/map` route in browser with Playwright and confirmed no console errors.
- Reworked the map again into a cleaner cartographic atlas: proportional cluster anchors, small data points, and fine source/similarity lines.
- Removed permanent source labels from the map to reduce clutter; source names are available on hover.
- Fixed the map hydration mismatch by rendering the measured SVG layer after mount.
- Added typed frontend bridge API helpers for status and request history.
- Wired the Bridge page to real backend bridge status and recent context requests.
- Rebuilt the desktop app successfully after map and Bridge changes.
- Updated the map so only main cluster anchors show names on the overview.
- Added hover previews for data points with file name, type/state, text preview, and vault/explorer actions.
- Changed cluster clicks to open an in-map cluster detail panel instead of navigating away.
- Added in-map cluster detail with connected data, adapter status, learning activity, and disabled future retrain/settings actions.
- Added Electron IPC primitives for opening a path and revealing a file in the OS file explorer.
- Added desktop preload typings for future vault/source file opening.
- Rebuilt successfully after the map interaction and Electron IPC changes.
- Added optional source location metadata to the frontend source model for vault/local file actions.
- Wired map hover preview actions to Electron open/reveal IPC when running inside the desktop shell.
- Verified `/map` after the latest interaction changes; browser console has no errors.
- Rebuilt successfully after adding desktop-aware map preview actions.
- Added PATCH and DELETE routes for vaults, clusters, and sources.
- Added GET routes for individual clusters and sources.
- Added `/api/v1/bridge/requests` for recent external context request history.
- Restarted backend and smoke-tested vault update, cluster update, source update, bridge context, and bridge request history.
- Added typed frontend API helpers for vaults, clusters, and sources.
- Wired Settings to load, create, and update the first backend vault.
- Wired Sources to load backend vault sources and clusters, with fallback to mock data when no backend vault is available.
- Wired Sources add/reindex/remove actions to backend source create/update/delete routes.
- Synced the active backend vault into the shared UI shell state.
- Verified the Sources page in browser: backend rows render, Add source creates a real backend row, footer shows active vault, and console errors are clear.
- Verified backend source/vault state through direct API calls.
- Rewrote [ReadME.md](../ReadME.md) in the same practical repo-operator style as the referenced `csshlok/4994-Research-Project` README.
- Added backend text extraction foundation for `.txt`, `.md`, and `.markdown` files.
- Added `/api/v1/sources/from-path` to create an indexed source from a local file path.
- Added Electron file picker IPC and preload bridge for selecting source files.
- Added a Sources `Add files` action that uses the desktop file picker and imports selected TXT/Markdown files into the active vault.
- Smoke-tested path ingestion by importing `ReadME.md`; it created an indexed backend source with extracted text.
- Verified the Sources page shows the imported source and the new `Add files` action with no browser console errors.

## Current Open Work

- Verify Electron dev launch visually.
- Decide first supported OS for downloadable app.
- Decide backend service packaging approach.
- Persist real source paths from ingestion so the map preview Vault/Explorer actions work on user-added files.
- Add backend service layer around raw route/database operations.
- Extend extraction beyond TXT/Markdown to PDF, DOCX, links, screenshots, and OCR.
- Connect frontend cluster/map/chat screens to backend APIs.
- Continue UI polish for chat, sources, settings, and onboarding.
- Clean up V0 visual language.
- Add real local backend.
- Add vault ingestion.
- Add clustering and retrieval.
- Add cluster expert training lifecycle.

## Running Notes

- The July-end target is achievable for a demoable MVP if we keep V1 focused.
- The riskiest feature is local fine-tuning, not the desktop shell.
- The app should remain useful during expert bootstrapping through retrieval-backed context.
- We should avoid silent full-device scans in V1.
- Every task should end by updating this file with completed work and remaining work.
- Electron is the pragmatic first shell. Tauri can be reconsidered after the app flow is proven.
- Python 3.14 is installed locally; ML libraries may later require a separate Python 3.11/3.12 environment.

## Update Protocol

At the end of every task:

1. Update `Last updated`.
2. Update relevant phase progress bars.
3. Add completed work to `Current Completed Work`.
4. Add or remove items from `Current Open Work`.
5. Add important decisions or risks to `Running Notes`.
