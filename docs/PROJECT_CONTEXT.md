# Project Context And Progress

Last updated: 2026-05-29

## Project Goal

Build a local downloadable desktop app for a Context Management Layer. The app lets users create a local vault, add files/links/notes/screenshots/chat transcripts, cluster them by similarity, train a compulsory local expert for each cluster, and use those cluster experts to feed structured context into a larger synthesis model.

The target user is a general second-brain user. The product should open on a memory-board/search surface, with chat as a core workspace supported by Mindly-like visual organization and an Obsidian-like graph/map.

Target completion: **end of July 2026**.

## Current Product Decisions

- App type: local downloadable desktop app, not a web app.
- V1 data mode: vault mode only. No full-device silent scanning.
- V1 cloud storage mode: import from local synced folders such as Google Drive Desktop, Dropbox, OneDrive, and iCloud Drive. OAuth/API connectors are later.
- UI direction: memory-board landing page, welcoming visual map, and chat as a core workspace rather than the first tab.
- Cluster experts: compulsory for every cluster.
- Cluster expert behavior: expert lifecycle exists immediately; retrieval-backed bootstrapping can answer before fine-tuning completes.
- Local synthesis model ladder: Qwen3-4B Q4_K_M as the default recommended model, Phi-4-mini-instruct Q4_K_M as the low-spec fallback, Qwen3-8B Q4_K_M as the higher-quality option, and Gemma 3 4B/12B as optional later long-context/vision-adjacent candidates.
- Model packaging: do not bundle LLM weights in the first installer. Ship CML smaller and let users download/select local models during setup.
- External integrations: Context Bridge via MCP, local HTTP API, CLI, and copy/export helpers.
- Privacy: local-first by default.
- Existing UI prototype: `UI-CML-V0/context-whisperer-suite-main`.
- First desktop shell: Electron, chosen because Node is available and Rust/Tauri tooling is not installed in the current environment.
- Real app workspace: `apps/desktop`.
- Local backend workspace: `backend`.

## Local LLM Model Decisions

The first CML model ladder is saved for local synthesis. These are free, local-first, reproducible GGUF targets that the app can download/select during setup. Model weights should not be bundled into the first installer.

| Role | Model | Backend ID | Hugging Face repo | Quantization | Approx download | Recommended RAM | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Default | Qwen3 4B Q4_K_M | `qwen3-4b-q4_k_m` | `Qwen/Qwen3-4B-GGUF` | `Q4_K_M` | ~2.5 GB | 8+ GB | Main recommended local synthesis model for V1. |
| Low-spec fallback | Phi-4 Mini Instruct Q4_K_M | `phi-4-mini-instruct-q4_k_m` | `unsloth/Phi-4-mini-instruct-GGUF` | `Q4_K_M` | ~2.5 GB | 8+ GB | Fallback for weaker machines if Qwen3 4B is not suitable. |
| Quality option | Qwen3 8B Q4_K_M | `qwen3-8b-q4_k_m` | `Qwen/Qwen3-8B-GGUF` | `Q4_K_M` | ~4.8 GB | 16+ GB | Better answer quality for users with more memory. |
| Optional later | Gemma 3 4B IT Q4_K_M | `gemma-3-4b-it-q4_k_m` | `Aldaris/gemma-3-4b-it-Q4_K_M-GGUF` | `Q4_K_M` | ~2.5 GB | 8+ GB | Later comparison candidate. |
| Optional larger later | Gemma 3 12B IT Q4_K_M | `gemma-3-12b-it-q4_k_m` | `nocturne23/gemma-3-12b-it-Q4_K_M-GGUF` | `Q4_K_M` | ~6.9 GB | 24+ GB | Larger later experiment for higher-quality local synthesis. |

Runtime boundary:

- CML expects an OpenAI-compatible local runtime endpoint for synthesis.
- For llama.cpp, run `llama-server` with the selected GGUF.
- Ollama can be used if it exposes an OpenAI-compatible local API for the selected model.
- Retrieval-backed extractive drafts remain the fallback when no local synthesis runtime is available.
- Cluster experts are still a separate lifecycle; these synthesis models are the larger answer-composition layer, not the per-cluster expert adapters.

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
| Product definition | In progress | `[########--] 80%` | Product PRD, UI PRD, project context, architecture doc, first local model ladder, runtime boundary, and model storage decision are documented. Needs packaging/runtime launch UX details. |
| UI prototype cleanup | In progress | `[#########-] 90%` | V0 reviewed. Cross-platform shortcuts fixed. CML Mind workspace, clickable source cards, setup flow, and cleaned-up blob map are in place. Needs broader chat/settings polish. |
| Desktop app foundation | In progress | `[########--] 80%` | Electron workspace created, frontend build passes, Vite dev server verified, file-opening IPC/file picker primitives added, UI routes can call backend APIs, and Settings can read model/runtime status. Needs Electron window verification and packaging. |
| Local backend foundation | In progress | `[#######---] 70%` | SQLite config/storage foundation, CRUD route groups, ingestion endpoints, and first-pass clustering service are working. Needs app-level services and tests. |
| Vault ingestion | In progress | `[#########-] 90%` | Source metadata/text records can be created and viewed from the Sources UI. TXT/Markdown/DOCX/PDF, pasted text, static link ingestion, setup import, desktop drag/drop import, local synced-folder import, per-file batch import failure reporting, link title/image metadata, generated summaries/tags, and in-app capture dialogs work. Needs screenshots/OCR extraction and dynamic-page parsing. |
| Embeddings and clustering | In progress | `[#####-----] 50%` | First-pass keyword auto-clustering, local chunking, deterministic local embeddings, SQLite vector storage, semantic search API, semantic Mind search, and reviewable cluster move suggestions are working. Need stronger embedding model and richer split/merge suggestions. |
| Chat and context routing | In progress | `[#######---] 70%` | Retrieval-grounded chat context, persisted backend chat sessions/messages, backend chat sidebar loading, local model runtime adapter, model setup UI, llama.cpp runtime helper scripts, fallback drafts, cluster usage, warnings, and citations are working. Needs streaming and manual routing polish. |
| Compulsory cluster experts | Not started | `[----------] 0%` | Need expert lifecycle, training queue, local fine-tuning spike. |
| Context Bridge | In progress | `[####------] 40%` | Bridge UI route now reads backend status and request history. Needs MCP server, CLI, permissions, and semantic retrieval. |
| Packaging and installer | In progress | `[#---------] 10%` | Windows llama.cpp runtime download/start scripts exist for local testing. Need app packaging, bundled service process management, and installer flow. |
| QA and hardening | In progress | `[##--------] 20%` | Security pass completed across backend, Electron shell, frontend dynamic CSS, and dependency audit. Needs Python CVE audit, broader tests, reliability checks, failure states, and performance review. |

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
- Added `/api/v1/sources/from-text` for pasted text ingestion.
- Added `/api/v1/sources/from-url` for basic HTTP/HTTPS link text ingestion.
- Added lightweight HTML-to-text extraction for link ingestion using the Python standard library.
- Replaced the placeholder Sources `Add source` action with `Paste text` and added an `Add link` action.
- Smoke-tested pasted text ingestion; it created an indexed note source.
- Smoke-tested link ingestion with `https://example.com/`; it created an indexed link source.
- Verified the Sources page shows `Add files`, `Paste text`, `Add link`, and the newly indexed text/link rows with no browser console errors.
- Updated [ReadME.md](../ReadME.md) to document the new ingestion endpoints and current state.
- Reviewed `t:\csshl\m2-res_480p.mp4` as an ingestion/storage reference video.
- Added [INGESTION_REFERENCE_NOTES.md](INGESTION_REFERENCE_NOTES.md) with observed ingest types, inferred normalized memory-card storage model, and CML implications.
- Added first-pass keyword-based automatic cluster assignment during indexed source creation.
- Added conservative automatic cluster creation when a new indexed source does not match an existing cluster.
- Updated the map to render unclustered sources as standalone loose data points.
- Updated the map route to load real backend vault clusters and sources instead of only mock store data.
- Added map health rail reporting for loose memory items.
- Smoke-tested auto-clustering with a new text source; it created an `Attention Encoder` cluster and assigned the source to it.
- Verified `/map` renders backend clusters, backend source points, loose points, and no browser console errors.
- Replaced temporary prompt-based pasted text capture with an in-app Add Text dialog.
- Replaced temporary prompt-based link capture with an in-app Add Link dialog.
- Verified Add Text dialog creates a real backend source and auto-clusters it.
- Verified Add Link dialog renders correctly and browser console errors are clear.
- Added a `tags` field to the SQLite source model with automatic migration for existing databases.
- Added local first-pass source summary generation during ingestion.
- Added local first-pass source tag generation during ingestion.
- Updated source API responses so tags are returned as arrays instead of storage JSON.
- Updated the Sources detail sheet to display generated tag chips and summaries.
- Smoke-tested generated summary/tags through `/api/v1/sources/from-text`.
- Verified the Sources detail sheet shows generated tags and summary with no browser console errors.
- Updated [ReadME.md](../ReadME.md) to mention generated summaries/tags.
- Changed the primary app navigation so the `Mind` memory board is first and Chat is no longer the landing tab.
- Updated the root route to open `/search` after onboarding instead of `/chat`.
- Rebuilt the Search tab into a Mindly-inspired "What's on Your Mind Today?" board with large search, type filters, sorting controls, add-content menu, and memory cards.
- Added an add-content menu with Note, Link, File, Voice note, Task, and future integration entries; Note and Link can ingest into the backend vault.
- Added a tag preview section to the link add dialog to carry the Mindly tag-management concept into CML.
- Changed the visual palette from warm/yellow neutrals to a cooler lavender/sky workspace palette with brighter cluster accents.
- Reworked the Map tab into a Mindly-style blob map: cluster blobs have no overview connection lines, can be dragged, can be zoomed, and open a cluster memory view on double-click.
- Added a cluster memory view inside the map with source spokes, connected source labels, local expert status, and learning activity.
- Kept loose/unclustered sources visible as small standalone data points with hover previews.
- Fixed a map SSR issue by avoiding direct `window` access during server render.
- Verified `/search` and `/map` with Playwright after restarting the dev server; both pages load with zero browser console errors.
- Verified production build with `npm run build` after the Mindly-style UI pass.
- Updated [UI_PRD.md](UI_PRD.md) so the PRD now reflects the memory-board landing page, Mindly-style blob map, tag-aware add flow, and revised navigation order.
- Installed the requested `uncodixfy` skill via `npx skills add cyxzdev/Uncodixfy`.
- Reworked the Mind page again to avoid a direct Mindly copy: removed the oversized copied headline, removed fake integration entries, restored a normal CML workspace layout, and kept only functional add actions.
- Added clickable source cards on the Mind page that open a source detail dialog with preview, tags, cluster link, and file/link actions where available.
- Restored the warm neutral palette from the earlier app direction after the blue/lavender pass was rejected.
- Cleaned up the map overview so cluster text sits below blobs, every cluster has visible text, and cluster labels use normal UI sizing instead of oversized blob text.
- Fixed the Mind page hydration mismatch by rendering a stable shell until client-side vault data is ready.
- Added dialog descriptions to remove Radix accessibility warnings.
- Verified the corrected Mind page source-detail flow and Map page in Playwright with zero browser console errors or warnings.
- Verified production build with `npm run build` after the correction pass.
- Added `pypdf` and `python-docx` backend dependencies for richer document ingestion.
- Extended local path extraction from TXT/Markdown to TXT/Markdown/DOCX/PDF.
- Added DOCX paragraph and table text extraction.
- Added PDF page text extraction.
- Updated source type inference so DOCX/PDF imports are treated as file sources.
- Updated the Electron file picker to allow TXT, Markdown, DOCX, and PDF documents.
- Updated Sources UI copy so file imports are described as document imports.
- Installed the new document extraction dependencies into the local `.venv`.
- Verified direct DOCX and PDF extraction with temporary smoke fixtures.
- Verified DOCX and PDF ingestion through `/api/v1/sources/from-path` on a clean backend running at `127.0.0.1:7343`.
- Verified backend syntax with `.venv\Scripts\python.exe -m compileall backend\app`.
- Verified desktop production build with `npm run build` after the ingestion changes.
- Added `cover_image_url` to source storage with automatic SQLite migration for existing databases.
- Improved link ingestion so `/api/v1/sources/from-url` extracts readable page text, page title metadata, and `og:image`/`twitter:image` metadata when present.
- Resolved relative link preview image URLs against the source page URL before storing them.
- Added card header image support to Mind source cards.
- Added card image editing in the Mind source detail dialog with image URL/local path save and remove actions.
- Added Electron IPC/preload support for choosing a local cover image file.
- Verified link ingestion against a local smoke HTML page with title, body text, and `og:image`.
- Verified source card image updates through the source PATCH route.
- Verified `/search` in the browser after the card image changes with zero console warnings/errors.
- Added Electron preload support for converting dropped desktop files into local file paths.
- Added drag-and-drop document import to the Mind memory board.
- Added drag-and-drop document import to the Sources view.
- Reused the existing `/api/v1/sources/from-path` path ingestion flow for dropped files.
- Added simple drop overlays that appear only during file hover.
- Verified production build with `npm run build` after drag/drop ingestion changes.
- Verified backend syntax with `.venv\Scripts\python.exe -m compileall backend\app`.
- Verified `/search` and `/sources` in the browser after drag/drop changes with zero console warnings/errors.
- Decided V1 cloud storage ingestion will use local synced folders instead of direct OAuth/API connectors.
- Added Electron folder picker support for importing synced folders.
- Added recursive local folder scanning for supported source types: TXT, Markdown, DOCX, and PDF.
- Added guardrails to recursive folder scanning: skips common build/system folders and caps each import scan at 500 files.
- Added folder import action to the Mind memory board.
- Added folder import action to the Sources view.
- Updated folder/drop ingestion so dropped folders are scanned recursively before calling `/api/v1/sources/from-path`.
- Verified Electron main/preload syntax with `node --check`.
- Verified production build with `npm run build` after synced-folder import changes.
- Verified backend syntax with `.venv\Scripts\python.exe -m compileall backend\app`.
- Verified `/search` and `/sources` return 200 and load in browser with zero console warnings/errors.
- Improved frontend backend error handling so API error details are shown instead of only HTTP status codes.
- Updated Mind batch file/folder/drop imports to continue after individual file failures.
- Added Mind import result messaging with imported count, failed count, first failed file, and reason.
- Updated Sources batch file/folder/drop imports to continue after individual file failures.
- Added Sources import result messaging with imported count, failed count, first failed file, and reason.
- Verified production build with `npm run build` after batch import failure reporting.
- Verified backend syntax with `.venv\Scripts\python.exe -m compileall backend\app`.
- Verified `/search` and `/sources` return 200 after batch import failure reporting.
- Verified Electron main/preload syntax with `node --check`.
- Added `source_chunks` SQLite table with vault/source/cluster indexes for local vector retrieval.
- Added dependency-free local embedding foundation using deterministic hashed vectors.
- Added source text chunking with overlap for retrieval.
- Indexed source chunks automatically when indexed sources are created.
- Reindexed source chunks automatically when source text, state, or cluster assignment changes.
- Added `/api/v1/search/semantic` for local semantic source-chunk search.
- Added `/api/v1/search/reindex/{vault_id}` to rebuild chunks for existing indexed sources.
- Added frontend API helpers for semantic search and vault search reindexing.
- Wired the Mind search box to use semantic ranking when a backend vault is active.
- Kept normal text filtering as fallback when semantic search is unavailable or returns no results.
- Smoke-tested semantic search with two local sources; the matching transformer/attention source ranked first.
- Verified production build with `npm run build` after semantic search changes.
- Verified backend syntax with `.venv\Scripts\python.exe -m compileall backend\app`.
- Verified `/search` returns 200 after semantic search wiring.
- Added vector-based source-to-cluster suggestion service.
- Fixed suggestion scoring so the source being evaluated is excluded from its current cluster centroid.
- Added `/api/v1/clusters/suggestions` for reviewable source move suggestions.
- Added frontend API helpers for cluster creation and cluster suggestions.
- Replaced the mock-only Clusters route with a backend-aware Clusters page.
- Added a Suggested moves panel on the Clusters page.
- Added per-suggestion Accept action that moves a source to the suggested cluster through the source update API.
- Kept cluster suggestions review-only; the app does not silently move user context.
- Smoke-tested suggestions with a deliberately misplaced transformer source; the correct research cluster was suggested.
- Verified backend syntax with `.venv\Scripts\python.exe -m compileall backend\app`.
- Verified production build with `npm run build` after cluster suggestion changes.
- Verified `/clusters` returns 200.
- Added `/api/v1/chat/context` for retrieval-grounded chat context routing.
- Added chat request/response schemas with prompt, answer draft, clusters used, citations, and warnings.
- Wired chat context routing to the semantic search layer.
- Added extractive local answer drafts based on retrieved snippets so chat can work before a synthesis model is wired.
- Added cluster usage calculation for retrieved cited sources.
- Added frontend API helper for chat context routing.
- Updated Chat route to load backend vault clusters and sources when available.
- Updated Chat route to send prompts through backend semantic retrieval when a backend vault is active.
- Kept mock chat fallback when backend context is unavailable.
- Updated Chat route scope selector to use backend clusters when available.
- Updated Chat route answer cards to show backend cluster usage and source citations.
- Smoke-tested chat context routing with a local transformer source; the answer returned the correct cluster and citation.
- Verified backend syntax with `.venv\Scripts\python.exe -m compileall backend\app`.
- Verified production build with `npm run build` after chat context routing.
- Verified `/chat/chat-welcome` returns 200.
- Added `chat_sessions` and `chat_messages` SQLite tables with indexes and vault/cluster foreign keys.
- Added persisted chat API routes: list/create/get/update/delete sessions.
- Updated `/api/v1/chat/context` so prompts can create or append to a backend chat session.
- Persisted user messages, assistant answers, clusters used, citations, and warnings for every saved chat turn.
- Added frontend backend API helpers for persisted chat sessions.
- Updated the Chat route to keep using the same backend session while the user continues a conversation in one chat view.
- Smoke-tested persisted chat routing with two prompts in one session; the session stored four messages and retained citations.
- Verified backend syntax with `.venv\Scripts\python.exe -m compileall backend\app` after chat persistence.
- Verified production build with `npm run build` after chat persistence.
- Saved the initial local LLM choices: Qwen3-4B Q4_K_M default, Phi-4-mini-instruct Q4_K_M low-spec fallback, Qwen3-8B Q4_K_M quality option, and Gemma 3 4B/12B as optional later candidates.
- Documented that model weights should be downloaded during setup rather than bundled into the first installer.
- Wired the Chat index page to load backend chat sessions from the active vault.
- Updated Chat `New chat` to create a backend chat session when a backend vault is available.
- Updated backend chat routes so existing persisted sessions open directly in the Chat view.
- Hydrated persisted backend chat messages into the Chat view, including cluster usage and citation metadata.
- Updated Chat scope changes to save the selected backend cluster scope.
- Updated Chat save/unsave to persist to the backend session.
- Added inline backend chat title editing in the Chat header.
- Kept the local mock chat path as fallback when the backend or vault is unavailable.
- Added frontend helper for deleting backend chat sessions for later UI use.
- Smoke-tested backend chat create, rename, save, list, and load on an isolated database.
- Verified production build with `npm run build` after persisted Chat UI wiring.
- Added backend local model registry for Qwen3-4B, Phi-4-mini-instruct, Qwen3-8B, Gemma 3 4B, and Gemma 3 12B Q4_K_M choices.
- Added model storage convention under `data/models`.
- Added `/api/v1/models` for model registry/status.
- Added `/api/v1/models/runtime` for local runtime connection status.
- Added `/api/v1/models/{model_id}` for per-model install/download status.
- Added `/api/v1/models/{model_id}/download` to start a controlled GGUF download into local app data.
- Added Hugging Face model-file resolution so downloads find the matching Q4_K_M GGUF filename from the model repo metadata instead of hard-coding filenames.
- Added backend LLM runtime config: `CML_LLM_PROVIDER`, `CML_LLM_BASE_URL`, `CML_LLM_MODEL`, and `CML_LLM_TIMEOUT_SECONDS`.
- Added root `.env` for local machine config and `.env.example` as the committed template.
- Updated backend settings to read from the root `.env` explicitly instead of depending on the shell working directory.
- Added OpenAI-compatible local runtime adapter for llama.cpp `llama-server`, Ollama-compatible OpenAI endpoints, or any compatible local server.
- Wired chat context generation to try local synthesis first when a runtime is configured and reachable.
- Kept retrieval-grounded extractive drafts as fallback when the local model runtime is disabled or unavailable.
- Smoke-tested model registry, runtime status, default model status, and chat fallback behavior on an isolated database.
- Verified backend syntax with `.venv\Scripts\python.exe -m compileall backend\app` after model runtime wiring.
- Updated [ReadME.md](../ReadME.md) with the model registry/runtime endpoints, current model ladder, and local runtime environment variables.
- Updated [ReadME.md](../ReadME.md) to point developers to `.env` and `.env.example`.
- Ran a security pass across backend routes, ingestion, model downloads, Electron shell access, frontend dynamic CSS, and package audits.
- Added public URL validation for link ingestion to block localhost, private IP ranges, loopback, link-local, multicast, reserved, and unspecified addresses.
- Added safe redirect handling for link ingestion so redirected URLs are revalidated before content is fetched.
- Added local file and link response size caps to reduce denial-of-service risk during ingestion.
- Hardened model downloads by validating Hugging Face URLs, requiring HTTPS `huggingface.co`, encoding resolved filenames, and blocking path traversal or non-GGUF model filenames.
- Hardened Electron external URL and local path opening so only expected external protocols and supported local document/image files can be opened from the app.
- Updated Electron folder scanning to skip symlinks during recursive synced-folder imports.
- Disabled credentialed wildcard CORS behavior on the local backend.
- Added explicit SQL update allowlists for vault, cluster, source, and chat session PATCH routes.
- Added identifier validation to the internal SQLite migration helper.
- Sanitized chart dynamic CSS identifiers and color values before injecting style rules.
- Verified `npm audit` and `npm audit --omit=dev` both report zero vulnerabilities.
- Verified security smoke checks for SSRF blocking, model filename traversal blocking, and allowlisted update routes.
- Verified `docs/` is not ignored by root `.gitignore` or local Git exclude rules.
- Verified all current docs are already tracked by Git and pushed the current `main` branch to GitHub.
- Added a dedicated Local LLM Model Decisions section with the selected model ladder, backend IDs, Hugging Face repos, quantization, estimated download sizes, RAM targets, and runtime boundary.
- Updated the Phi and Gemma model registry entries to public repos that expose matching `Q4_K_M` GGUF files.
- Added `CML_MODELS_DIR` so model storage can be configured separately from the app database/data folder.
- Pointed the local machine `.env` at `T:\LLM` for model testing downloads.
- Added frontend backend helpers for local model listing, runtime status, and starting model downloads.
- Added a Settings local models section showing model role, quantization, repo, size/RAM target, installed path, runtime status, and download progress.
- Downloaded all selected local synthesis GGUF models into `T:\LLM`:
  - `qwen3-4b-q4_k_m`: `T:\LLM\qwen3-4b-q4_k_m\Qwen3-4B-Q4_K_M.gguf`
  - `phi-4-mini-instruct-q4_k_m`: `T:\LLM\phi-4-mini-instruct-q4_k_m\Phi-4-mini-instruct-Q4_K_M.gguf`
  - `qwen3-8b-q4_k_m`: `T:\LLM\qwen3-8b-q4_k_m\Qwen3-8B-Q4_K_M.gguf`
  - `gemma-3-4b-it-q4_k_m`: `T:\LLM\gemma-3-4b-it-q4_k_m\gemma-3-4b-it-q4_k_m.gguf`
  - `gemma-3-12b-it-q4_k_m`: `T:\LLM\gemma-3-12b-it-q4_k_m\gemma-3-12b-it-q4_k_m.gguf`
- Verified the backend model registry sees all five models as installed from `T:\LLM`.
- Verified backend syntax with `.venv\Scripts\python.exe -m compileall backend\app` after configurable model storage and registry updates.
- Verified production build with `npm run build` after the model setup UI.
- Downloaded llama.cpp Windows CPU x64 runtime `b9374` into `T:\LLM\runtimes\llama.cpp\b9374`.
- Verified `llama-server.exe` and `llama-cli.exe` are available from the downloaded llama.cpp runtime.
- Added `scripts/llm/download-llama-cpp.ps1` for reproducible llama.cpp runtime download/extraction.
- Added `scripts/llm/start-llama-server.ps1` to launch any downloaded GGUF model through a local OpenAI-compatible `/v1` endpoint.
- Added `scripts/llm/test-local-model.ps1` to test the running local model endpoint.
- Added `scripts/llm/benchmark-local-models.ps1` to benchmark the selected local model ladder through llama.cpp.
- Updated `.env.example`, local `.env`, and [ReadME.md](../ReadME.md) to use the helper default endpoint `http://127.0.0.1:8084/v1` and model alias `cml-local`.
- Smoke-tested Qwen3 4B through `llama-server` with the OpenAI-compatible endpoint; generation was about 15.9 tokens/sec on CPU for the short test prompt.
- Stopped the hidden llama.cpp test server after verification so no background model process remained on port `8084`.
- Ran the short benchmark harness across all five downloaded GGUF models on CPU with 8 threads and 4096 context:
  - Qwen3 4B Q4_K_M: ~44.2 prompt tokens/sec, ~15.1 generated tokens/sec.
  - Phi-4 Mini Instruct Q4_K_M: ~49.5 prompt tokens/sec, ~16.1 generated tokens/sec.
  - Qwen3 8B Q4_K_M: ~25.0 prompt tokens/sec, ~8.2 generated tokens/sec.
  - Gemma 3 4B IT Q4_K_M: ~47.9 prompt tokens/sec, ~9.0 generated tokens/sec.
  - Gemma 3 12B IT Q4_K_M: ~14.3 prompt tokens/sec, ~4.4 generated tokens/sec.
- Verified no benchmark server process remained listening on port `8094`.
- Confirmed the machine has an NVIDIA GeForce RTX 3060 Laptop GPU visible through `nvidia-smi`.
- Downloaded llama.cpp Windows CUDA 12.4 runtime and matching CUDA DLL bundle into `T:\LLM\runtimes\llama.cpp\b9374-cuda-12.4`.
- Updated llama.cpp helper scripts to support CPU/CUDA runtime selection and configurable GPU layer offload.
- Smoke-tested Qwen3 4B through CUDA `llama-server`; generation improved to about 35.0 tokens/sec on the short prompt.
- Ran the short CUDA benchmark harness across all five downloaded GGUF models on the RTX 3060 Laptop GPU:
  - Qwen3 4B Q4_K_M: ~173.8 prompt tokens/sec, ~34.7 generated tokens/sec.
  - Phi-4 Mini Instruct Q4_K_M: ~346.1 prompt tokens/sec, ~33.3 generated tokens/sec.
  - Qwen3 8B Q4_K_M: ~199.8 prompt tokens/sec, ~18.1 generated tokens/sec.
  - Gemma 3 4B IT Q4_K_M: ~271.7 prompt tokens/sec, ~36.8 generated tokens/sec.
  - Gemma 3 12B IT Q4_K_M: ~16.9 prompt tokens/sec, ~2.8 generated tokens/sec.
- Regrouped the development plan against the current implementation state before choosing the next build step.
- Replaced the mock onboarding flow with a real setup sequence:
  - ask for the user's name
  - ask for vault name
  - ask for vault storage location
  - create the backend vault
  - let the user drop files/folders, choose files/folders, add a link, or paste text to seed the vault
- Added Electron IPC/preload support for choosing a dedicated vault folder.
- Wired setup content import to real backend ingestion routes for files, folders, links, and pasted text.
- Changed onboarding completion to open the Mind/search workspace instead of Chat.
- Stored setup user/vault display values in local storage for now.
- Verified production build with `npm run build` after the setup flow replacement.
- Verified Electron main/preload syntax with `node --check` after adding vault-folder picker IPC.
- Installed the external `vipulgupta2048/codex-skills` repo under `C:\Users\csshl\.agents\skills\codex-skills`.
- Confirmed the cloned skills repo currently exposes a `frontend-design` skill at `C:\Users\csshl\.agents\skills\codex-skills\skills\frontend-design\SKILL.md`.
- Used the `frontend-design` skill to run a deep UI/interaction audit across the desktop app shell, Mind/search, Sources, Clusters, Map, Chat, Bridge, Settings, onboarding, shared components, and global styling.
- Identified the main UI cleanup themes: remove remaining mojibake text, unify page headers/toolbars, replace disabled/inert controls with working or clearly staged states, connect mock-backed commands/details to backend data, improve map accessibility and interaction clarity, and reduce inconsistent typography.

## Current Open Work

- Verify Electron dev launch visually.
- Decide first supported OS for downloadable app.
- Decide backend service packaging approach.
- Persist synced-folder import history and optionally add watched folder refresh.
- Persist real source paths from ingestion so the map preview Vault/Explorer actions work on user-added files.
- Add backend service layer around raw route/database operations.
- Extend extraction beyond TXT/Markdown/DOCX/PDF/static links to screenshots, OCR, and dynamic-page parsing.
- Add task/list item ingestion as a first-class source type.
- Connect frontend cluster/chat screens more deeply to backend APIs.
- Continue UI polish for chat, sources, settings, and onboarding.
- Apply the UI audit recommendations: shared page header/toolbar patterns, consistent user-facing status labels, backend-aware command palette actions, map selection/accessibility fixes, and cleanup of disabled placeholder controls.
- Continue replacing remaining V0 visual language in chat, settings, onboarding, and footer copy.
- Replace remaining copied/inspired-too-literally UI surfaces with CML-specific workflows.
- Add real local backend.
- Finish vault ingestion edge cases: screenshots/OCR, dynamic links, and watched folder refresh.
- Add clustering and retrieval.
- Expand embedding-based suggestions to include split/merge workflows and batch review.
- Do a qualitative answer comparison across the downloaded GGUF models using representative CML prompts and local context.
- Add streaming responses and manual cluster override polish against backend state.
- Add cluster expert training lifecycle.
- Add a real backend profile/settings record for setup fields like user name and default vault instead of keeping them only in local storage.
- Add Python dependency CVE auditing to the toolchain, such as `pip-audit`, and run it in QA.
- Add local backend access hardening before exposing it beyond trusted loopback desktop use.

## Running Notes

- The July-end target is achievable for a demoable MVP if we keep V1 focused.
- The riskiest feature is local fine-tuning, not the desktop shell.
- The app should remain useful during expert bootstrapping through retrieval-backed context.
- We should avoid silent full-device scans in V1.
- Every task should end by updating this file with completed work and remaining work.
- Electron is the pragmatic first shell. Tauri can be reconsidered after the app flow is proven.
- Python 3.14 is installed locally; ML libraries may later require a separate Python 3.11/3.12 environment.
- The actual cluster hit target should stay stable; any blob movement should be visual-only so double-click and drag remain reliable.
- Avoid direct UI copying from reference products. Use references only for interaction principles, then translate them into CML-specific layouts and working controls.
- Port `7342` was still responding with stale pre-DOCX/PDF backend behavior during the ingestion smoke test, so document ingestion was verified on a clean temporary backend at `7343`. Restart the normal backend/session before testing DOCX/PDF through the desktop app.
- Current link ingestion is static HTTP/HTML extraction. JavaScript-rendered pages, authenticated pages, and richer article readability cleanup need a later browser/readability extraction pass.
- Direct Drive/Dropbox/OneDrive cloud APIs are intentionally out of V1. Synced folders provide the free local path now; OAuth connectors can come after the core local context flow works.
- Current local embeddings are deterministic hashed vectors so the app stays free and dependency-light. They establish the vector/search architecture, but we should later swap in a stronger local embedding model when packaging constraints are clearer.
- Cluster suggestions are intentionally review-only. User confirmation should remain the default until confidence, undo, and source provenance are stronger.
- Chat persistence now stores retrieval metadata first. This gives the later local model/runtime a durable place to attach model choice, token usage, streaming chunks, and answer feedback without changing the whole chat API.
- Expected model download sizes: Phi-4-mini-instruct Q4_K_M about 2.5 GB, Qwen3-4B Q4_K_M about 2.3-2.5 GB, Qwen3-8B Q4_K_M about 4.8 GB download / about 5.3 GB loaded weights, Gemma 3 4B Q4_K_M about 2.3-2.5 GB, and Gemma 3 12B Q4_K_M about 6.8-6.9 GB.
- Local model downloads are explicit. The backend exposes a download endpoint, but the app should not automatically pull multi-GB weights without a clear user action.
- Local synthesis currently expects an OpenAI-compatible endpoint. For llama.cpp this means running `llama-server` with the selected GGUF; for Ollama this means using its compatible local API surface when available.
- Current llama.cpp runtime test uses `llama-server --api-prefix /v1` because the latest downloaded server exposes `/chat/completions` by default unless a prefix is provided.
- Port `8080` is already used locally by another dev server, so the CML llama.cpp helper defaults to `8084`.
- Early CPU speed result: Phi-4 Mini and Qwen3 4B are the fastest usable V1 candidates on this machine; Qwen3 8B is slower but plausible for quality mode; Gemma 12B is likely too slow for default local chat without GPU/offload.
- Early CUDA speed result on the RTX 3060 Laptop GPU: Gemma 3 4B, Qwen3 4B, and Phi-4 Mini are all fast enough for interactive local chat; Qwen3 8B is usable as quality mode; Gemma 12B performs poorly with full offload on this 6 GB GPU and should not be a default.
- Setup now creates a real backend vault and can seed it with real sources. User profile details are still local UI metadata until a backend profile/settings table is added.
- The local backend still assumes trusted loopback desktop use. Before any wider network exposure, add an app token, stricter origin checks, and per-vault permission boundaries.
- Python dependency CVE auditing was not completed because `pip-audit` is not installed in the current environment.
- UI audit risk: several visible actions still look production-ready but are not wired yet, especially Bridge controls, chat attachments/save/regenerate actions, cluster expert controls, and some command palette actions. These should either become functional or be presented as setup/preview states before user testing.

## Update Protocol

At the end of every task:

1. Update `Last updated`.
2. Update relevant phase progress bars.
3. Add completed work to `Current Completed Work`.
4. Add or remove items from `Current Open Work`.
5. Add important decisions or risks to `Running Notes`.
