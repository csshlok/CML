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
| UI prototype cleanup | In progress | `[##--------] 20%` | V0 reviewed. Cross-platform shortcut labels and handlers started. Needs visual/product polish. |
| Desktop app foundation | In progress | `[####------] 40%` | Electron workspace created at `apps/desktop`; frontend build passes; Vite dev server verified. Needs Electron window verification and packaging. |
| Local backend foundation | In progress | `[##--------] 20%` | FastAPI skeleton added, venv installed, `/health` verified, and UI health status wired. Needs storage and app APIs. |
| Vault ingestion | Not started | `[----------] 0%` | Need file/link/text ingestion and extraction pipeline. |
| Embeddings and clustering | Not started | `[----------] 0%` | Need local embedding model, chunking, vector store, cluster suggestions. |
| Chat and context routing | Not started | `[----------] 0%` | Need router, retrieval, context packet builder, citations. |
| Compulsory cluster experts | Not started | `[----------] 0%` | Need expert lifecycle, training queue, local fine-tuning spike. |
| Context Bridge | In progress | `[#---------] 10%` | Bridge UI route added. Needs backend endpoints, MCP server, CLI, and permissions. |
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

## Current Open Work

- Verify Electron dev launch visually.
- Decide first supported OS for downloadable app.
- Decide backend service packaging approach.
- Add backend storage/config foundation.
- Add backend API route groups for vaults, sources, clusters, and bridge.
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
