# Overall Context

Last updated: 2026-06-05

## Fallback Context Rule

This document preserves the pre-pruned long-form project context as a fallback for continuity. It must follow the same maintenance discipline as `PROJECT_CONTEXT.md`: update changed decisions, progress, blockers, completed work, and running notes when relevant; prune duplicated or stale material instead of only appending; and keep `PROJECT_CONTEXT.md` as the compact source-of-truth operating brief.

Latest compact truth after the 2026-06-05 decision pass lives in `docs/PROJECT_CONTEXT.md`. Current product decision: V1 is Windows-only, public-release-only, and must include a working high-quality verified LoRA function; there is no private-demo fallback. Model policy is now explicit: one approved model family contract for both chat and expert workflows, current Qwen/Phi/Gemma defaults remain the default recommendations, custom models are only `accepted` or `rejected`, and expert-capable onboarding requires one app-managed approved local checkpoint rather than a loose runtime alias. Claude Desktop-specific smoke is deferred for now; clean Windows VM validation, real LoRA trainer/runtime smoke, and hardware-aware model recommendations remain current external gates. Refresh this fallback as a deliberate snapshot, not as an append-only task log.

## 2026-06-05 Approved Model Policy Snapshot

Completed decision:

- Public V1 will use a single approved model family contract across normal chat and LoRA expert workflows.
- Current default families remain the current Qwen/Phi/Gemma defaults for recommendation purposes.
- Setup must require one approved model download or import before expert-capable onboarding is complete.
- Custom model registration has only two outcomes: `accepted` or `rejected`.
- Acceptance requires a real app-managed local checkpoint that passes both Vault runtime and LoRA runtime compatibility checks on the current machine.
- A connected OpenAI-compatible endpoint, GGUF-only alias, Ollama name, or llama.cpp runtime alone is not enough for LoRA acceptance.

Current compatibility research baseline:

- Hugging Face Transformers integrates directly with PEFT for non-prompt-learning methods including LoRA, and adapters are loaded onto `PreTrainedModel` classes rather than arbitrary runtime endpoints.
- Qwen3 official Hugging Face checkpoints are documented for `transformers` use and also separately exposed through local-app quantizations; that means CML should distinguish direct-checkpoint acceptance from endpoint-only usage.
- Microsoft Phi-4-mini-instruct official Hugging Face assets expose both `Transformers` usage and quantized local-app variants, so the same direct-checkpoint-versus-quantized-runtime distinction applies.
- Google Gemma 3 official Hugging Face checkpoints are documented for `Transformers` usage and also have quantized local-app paths; acceptance for LoRA must require the compatible checkpoint path, not only the quantized runtime.
- Additional official compatible families worth evaluating later include Qwen2.5, Llama 3.x, and Mistral Nemo, but the current product defaults remain the existing Qwen/Phi/Gemma ladder unless explicitly changed.

Implementation status after the 2026-06-05 pass:

- Backend now has a formal model compatibility report, approved-family detection, active approved-model selection, custom checkpoint import, and readiness gating for accepted models.
- Expert training now chooses an accepted local base model instead of blindly using the generic runtime alias.
- Onboarding and Settings now expose accepted/rejected model validation and custom checkpoint import flows instead of treating runtime aliases as sufficient for expert setup.
- Packaging now stages a separate bundled expert Python runtime and package validation expects that runtime to exist.

## 2026-06-04 Compulsory Cluster Expert Build Snapshot

Completed:

- LoRA graduation contract now includes source count, estimated token count, validation-record count, minimum quality, required adapter files, richer failure codes, and a plain graduation-gate statement.
- Cluster datasets now report total text characters, estimated token count, unique-content count, duplicate count, and duplicate ratio.
- Graduation now enforces unique-source/diversity, maximum duplicate ratio, and minimum adapter quality delta over retrieval.
- Added deterministic expert evaluation categories and retrieval-vs-adapter delta scoring for repeatable benchmark scaffolding.
- Added `scripts/backend/smoke-lora-expert.ps1`, `scripts/backend/smoke-lora-runtime.ps1`, and `docs/LORA_CLUSTER_EXPERT_MVP_POLICY.md`.
- Adapter validation now rejects missing directories, missing files, malformed `adapter_config.json`, non-LoRA configs, missing base model metadata, and empty adapter weights.
- Training jobs now fail with typed expert failure codes for insufficient dataset, invalid adapter, runtime-load contract failure, and quality-gate failure.
- Successful training metrics now include dataset gate details, adapter validation details, and runtime-load plan metadata.
- Added `/api/v1/clusters/{cluster_id}/expert/status` for UI-facing expert state: searchable, trained, stale, active artifact, dataset hash, runtime-load readiness, failure code, and user status.
- Active adapters are marked stale when the current cluster dataset hash no longer matches the adapter's training dataset hash.
- Desktop cluster expert status mapping now shows `Searchable now`, `Learning`, `Ready`, `Needs update`, and `Issue` instead of collapsing unknown backend states to `Setting up`.
- Cluster detail now includes a backend-backed Expert tab showing searchable/trained/stale state, hashes, active artifact, runtime-load readiness, jobs, and artifacts.

Verification:

- Focused backend/source suites: 102 tests OK, 1 skipped.
- Full backend unittest discovery: 178 tests OK, 1 skipped.
- `ruff check backend`: passed.
- `npm run lint`: passed with existing warnings only.
- `npm run build`: passed.

Still not completed:

- Real LLaMA Factory trainer smoke needs an actual `CML_LORA_TRAINER_COMMAND` and local base model path.
- Runtime adapter loading still needs a live local inference runtime smoke, not only the load-plan contract.
- Live retrieval-vs-adapter quality benchmark remains to run against a real trained adapter.
- Hardware matrix and training time/cost reporting remain to expand.

## 2026-06-04 Full Post-Review Implementation Snapshot

Completed:

- Background jobs now claim queued work atomically with a status-guarded update, preventing concurrent `run-once` callers from executing the same job.
- Local API auth now fails closed by default when no `CML_API_TOKEN` is configured; unauthenticated API startup is explicit opt-in via `CML_ALLOW_UNAUTHENTICATED_API=1`.
- Added authenticated backend identity probing through `/api/v1/system/backend-identity`; Electron and frontend backend selection now verify token-authenticated identity instead of trusting health alone.
- Root backend dev startup now uses `scripts/backend/start-dev-backend.ps1`, which generates a per-process local API token when one is not already supplied.
- FastAPI startup/shutdown moved to lifespan while keeping callable startup/shutdown helpers for tests.
- LoRA trainer launch no longer uses `shell=True`; commands use argv/env path passing and support Windows paths with spaces.
- Desktop lint was narrowed to source/electron/script inputs so generated package output no longer dominates lint execution.
- Ruff unused-import cleanup completed.

Verification:

- Full backend unittest discovery: 175 tests OK, 1 skipped.
- Electron main behavior tests: 8 tests OK.
- Electron token-store tests: 4 tests OK.
- `ruff check backend`: passed.
- `npm run lint`: passed with existing warnings only.
- `npm run build`: passed.
- `scripts/packaging/package-windows.ps1`: passed and produced `apps/desktop/release/win-unpacked` plus `apps/desktop/release/CML-0.1.0-Setup.exe`.
- Packaged runtime smoke: passed, including local API token enforcement, pre-vault route blocking, OCR availability, and model/embedding setup endpoints.
- Packaged full-vault smoke: passed, including vault creation, text ingestion, semantic search, generated image OCR, scanned-PDF OCR, cache prune, startup phase registry check, and diagnostics export.
- Packaged dynamic-link smoke: passed with browser runtime available.
- Packaged migration drill: passed.
- Packaged app launch smoke: passed, pre-vault startup reached ready.
- Clean-machine package structure validator: passed on the dev machine; a true clean VM run remains required because host Python/Node/Ghostscript were detected.

Remaining gates:

- Clean Windows VM validation with no dev Python, Node, preinstalled OCR, or helpful PATH tools.
- Hardware-aware model recommendation by detected RAM/CPU/GPU/disk/runtime conditions.
- Claude Desktop MCP smoke is deferred; keep external-client claims conservative until resumed.
- Real LoRA adapter training, runtime adapter loading, quality win over retrieval baseline, rollback, and supported-hardware proof before public V1 expert claims.

## 2026-06-03 Package Gate Closure Snapshot

Completed without touching LoRA:

- Rebuilt valid Windows artifacts: `apps/desktop/release/win-unpacked` and `apps/desktop/release/CML-0.1.0-Setup.exe`.
- Added packaged Playwright runtime staging under `resources/ms-playwright`; Electron sets `PLAYWRIGHT_BROWSERS_PATH` for packaged backend browser fallback.
- Full-vault package smoke now generates its own image and scanned-image PDF OCR fixtures and fails if OCR text is not produced.
- Packaged dynamic-link smoke passed against `https://example.com/` with browser runtime importable and dynamic fallback available.
- `docs/model-integrity-manifest.json` now pins exact managed GGUF filenames, SHA-256 hashes, sizes, and repo commits.
- Added `scripts/backend/benchmark-user-owned-vault.ps1` for larger real vault retrieval threshold tuning.
- Settings now exposes user-facing evidence retention controls for chat retrieval snapshots and query evidence cache pruning.
- Added `docs/UPDATE_MIGRATION_POLICY.md` and `scripts/packaging/smoke-packaged-migration-drill.ps1`; the packaged drill reports synthetic interrupted migrations without mutating recovery state.
- Ghostscript release path is AGPL-compatible public release, documented in `docs/GHOSTSCRIPT_AGPL_RELEASE_POLICY.md`.
- Hardened installer smoke to wait for asynchronous NSIS cleanup; silent install/uninstall now passes.

Verification:

- Focused backend module: 60 tests OK.
- Frontend `npm run build`: passed.
- Package rebuild: completed and produced a 537 MB setup exe plus blockmap.
- Packaged generated OCR smoke: image and PDF fixture extraction passed.
- Packaged dynamic-link smoke: passed with browser runtime available.
- Packaged migration drill: passed.
- Clean-machine validator: passed on dev machine, with Python/Node detected on PATH; clean VM remains required.
- Packaged app launch smoke: passed, pre-vault startup reached ready.
- Installer smoke: passed after hardening uninstall wait.
- Security audit: npm production audit found 0 vulnerabilities; pip check passed; pip-audit reported no known third-party vulnerabilities; Electron behavior/token tests and focused backend security tests passed.

Remaining gates:

- Clean Windows VM package validation is still required before public clean-machine claims.
- Real Claude Desktop MCP smoke remains deferred until Claude is installed and user resumes that path.
- Verified LoRA remains untouched and still required for public V1 positioning.

## 2026-06-03 Non-Claude Build Completion Snapshot

Completed without touching LoRA:

- Clean-machine validation now records host Python, Node, Tesseract, and Ghostscript PATH findings so clean VM validation can prove the package is not leaning on contributor-machine tools.
- Full-vault packaged smoke was executed against refreshed `apps/desktop/release/win-unpacked` and passed vault creation, text ingestion, reindex, semantic search, query-cache pruning, startup phase validation, and diagnostics export.
- Full-vault smoke now accepts optional OCR image/PDF fixture paths; fixture ingestion was not executed because no fixture paths were supplied.
- Trusted model integrity manifest support exists through `CML_MODEL_INTEGRITY_MANIFEST_PATH`, `CML_MODEL_INTEGRITY_MANIFEST_URL`, `docs/model-integrity-manifest.json`, and `/api/v1/models/integrity-manifest`.
- Cluster merge rollback exists through `POST /api/v1/clusters/merge-artifacts/{artifact_id}/rollback`, restoring the source cluster and moving recorded sources/chats back from `cluster_merge_artifacts`.
- Retrieval benchmark output now includes 1k/low-spec target fields: index seconds, query latency, compact seconds, SQLite bytes, and target pass/fail.
- Chat evidence retention now has a policy and enforce API for compacting snapshots, tombstoning deleted-source citations, and trimming excerpts.
- Startup recovery drills now expose stale startup state, interrupted migrations/jobs, and interrupted generation recovery through `/api/v1/system/recovery-drills`.
- First-run readiness now exposes explicit setup gates through `/api/v1/system/first-run/readiness`: vault path, non-hash embeddings, OCR runtime, model provenance, and startup phase registry.
- Packaged fallback bug fixed: Python startup phase fallback now contains the full startup vocabulary when `shared/startup-phases.json` is absent from package resources.

Historical package caveat now resolved:

- An earlier 2026-06-03 package run timed out and produced only small `.partial` setup files.
- The later package gate closure rebuilt a valid `apps/desktop/release/CML-0.1.0-Setup.exe`; keep `.partial` files treated as non-distributable leftovers.

Verification:

- Focused backend module: 60 tests OK.
- Full backend discovery: 170 tests OK, 1 skipped.
- `python -m compileall backend/app`: passed.
- PowerShell parser validation for package/benchmark scripts: passed.
- Small retrieval benchmark smoke: passed.
- Dev-machine package validator: passed, with Python/Node detected on PATH; clean VM validation remains required.

## 2026-06-03 Backend Gate Closure Snapshot

Completed without touching LoRA:

- Written security baseline: `docs/THREAT_MODEL.md` now covers local API, Bridge, extension/MCP clients, diagnostics, model downloads, local filesystem boundaries, and required security regressions.
- Managed model integrity: local model downloads now compute SHA-256, write `integrity.json`, report integrity status, and fail when a configured expected SHA-256 mismatches.
- Clean-machine package validation: `scripts/packaging/validate-clean-machine-package.ps1` checks package root, resources, packaged backend, packaged Python runtime, OCR manifest, and package smoke scripts. It passed against `apps/desktop/release/win-unpacked`.
- Full-vault package smoke automation: `scripts/packaging/smoke-packaged-full-vault.ps1` starts packaged backend in full-vault mode and exercises vault creation, text ingestion, reindex, semantic search, query-cache pruning, startup phase validation, and diagnostics bundle export.
- Startup status hardening: startup phases are validated from `shared/startup-phases.json`; non-terminal startup phases now report stale timeout state.
- Scale/retrieval harness: `scripts/backend/benchmark-1k-vault.ps1` runs the retrieval benchmark at 1k sources by default and writes to `T:\CML-build-smoke\retrieval-1k`.
- Watched-folder back-pressure: local folder scans now report scan limits, truncation, and `backpressure_required`; the integrations API exposes watched-folder limits.
- Cluster merge provenance: `cluster_merge_artifacts` records source/target snapshots, moved source IDs, moved chat IDs, reversibility, and timestamp before destructive merge operations. Policy lives in `docs/CLUSTER_MERGE_POLICY.md`.
- Query/evidence cache lifecycle: cache pruning removes old, invalidated, oversized, and over-limit entries through core logic and `POST /api/v1/search/query-cache/prune`.
- Verification: focused backend unittest module ran 56 tests OK; full backend unittest discovery ran 166 tests OK with 1 skipped; `python -m compileall backend/app` passed; PowerShell parser validation passed for the new smoke/benchmark scripts.

Still not completed:

- Real Claude Desktop MCP smoke remains the main Bridge verification gap.
- Clean Windows VM execution remains required before clean-machine package claims are public quality.
- Full-vault packaged smoke passed for text/search/diagnostics, but OCR image/PDF fixture coverage still needs to be staged and executed against the package.
- Model integrity supports local/HTTPS manifests, but release engineering still needs to pin real expected SHA-256 values for exact managed GGUF files.
- Valid NSIS installer rebuild remains required after the timeout; do not treat `.partial` setup files as distributable.

## 2026-06-03 Devil's Advocate Review Lessons

Source response doc: `docs/DEVILS_ADVOCATE_RESPONSES_2026-06-03.md`.

Q100 is intentionally excluded from decision-making per user instruction. The useful lesson from the review is not that CML is a bad idea; it is that the project must stop equating "prototype works" with "public V1 gate passed."

Current decision overriding earlier fallback language:

- V1 is Windows-only.
- V1 is public-release-only; if verified LoRA or other public gates are not ready, delay release rather than ship a private demo.
- Model setup must recommend safe choices for low-, mid-, and high-spec machines based on actual system conditions.
- Claude Desktop-specific Bridge smoke is deferred for now.

Core lessons to preserve:

- Public V1 remains conditional on verified LoRA. If real adapter training, artifact validation, runtime load, rollback, hardware support, and quality win over retrieval are not proven, the release must slip.
- LoRA should be framed as graduated expertise, not blind success for every cluster. Small or low-evidence clusters should remain retrieval-backed with explicit status.
- Clean-machine validation matters more than dev-machine confidence. Package smoke now passes locally, but a Windows VM without dev Python, Node, preinstalled OCR, or helpful environment variables is still required.
- Security needs a written threat model. Local API tokens, Bridge tokens, extension tokens, MCP clients, diagnostics, model downloads, and local-attacker limits must be described in one attacker/mitigation matrix.
- Managed model downloads need integrity verification. HTTPS plus domain validation is not enough; use SHA-256 or signed manifests before registering a model usable.
- Bridge privacy language must be explicit: CML is local by default, but enabled Bridge clients can receive selected vault context and may send it to external providers.
- Startup repair is not complete until full-vault repair drills, stale-phase timeout behavior, backup/export options, and packaged diagnostics are proven.
- Scale claims need benchmarks: 1k-source indexing/retrieval, watched-folder limits, vector fragmentation/compaction, long chat histories, and low-spec query latency.
- First-run onboarding must be honest about model sizes, embedding setup, hardware requirements, and degraded/context-only mode.
- Context docs should remain compact and operational. Long reviews and history belong in dated docs, not the primary operating brief.

---
# Project Context And Progress

Last updated: 2026-06-04

## Document Map

- `Project Goal` and `Current Product Decisions`: stable direction and release assumptions.
- `Phase Progress`: current progress bars, critical path, and concise phase snapshots.
- `Week-By-Week Goals`: original delivery plan and exit criteria.
- `Completed Work`: implementation history.
- `Open Work`: remaining build items and public-V1 blockers.
- `Running Notes`: decisions and constraints that should not be lost.
- `Update Protocol`: rules for keeping this file current after each build pass.

## Project Goal

Build a local downloadable desktop app for a Context Management Layer. The app lets users create a local vault, add files/links/notes/screenshots/chat transcripts, cluster them by similarity, train a compulsory local expert for each cluster, and use those cluster experts to feed structured context into a larger synthesis model.

The target user is a general second-brain user. The product should open on a memory-board/search surface, with chat as a core workspace supported by Mindly-like visual organization and an Obsidian-like graph/map.

Target completion: **end of July 2026**.

## Current Product Decisions

- App type: local downloadable desktop app, not a web app.
- Public V1 platform: Windows only.
- Release stance: public release only; no private alpha/demo fallback. If verified LoRA or other public gates fail, delay release.
- V1 data mode: vault mode only. No full-device silent scanning.
- V1 cloud storage mode: import from local synced folders such as Google Drive Desktop, Dropbox, OneDrive, and iCloud Drive. OAuth/API connectors are later.
- UI direction: memory-board landing page, welcoming visual map, and chat as a core workspace rather than the first tab.
- UI responsive scope: no dedicated mobile screen for public V1; build a polished dark version and a usable minimized/narrow desktop window version.
- Cluster experts: compulsory for every cluster.
- Cluster expert behavior: expert lifecycle exists immediately; retrieval-backed bootstrapping can answer before fine-tuning completes.
- Local synthesis model ladder: Qwen3-4B Q4_K_M as the default recommended model, Phi-4-mini-instruct Q4_K_M as the low-spec fallback, Qwen3-8B Q4_K_M as the higher-quality option, and Gemma 3 4B/12B as optional later long-context/vision-adjacent candidates.
- Model packaging: do not bundle LLM weights in the first installer. Ship CML smaller and let users download/select local models during setup.
- First-run model setup: after Vault is installed, users should be able to either use CML's recommended local model set or connect their own already-installed local models for synthesis, embeddings, clustering, and later expert workflows.
- Model recommendation: CML must recommend models from detected system conditions, including RAM, CPU, GPU/CUDA availability, free disk, and runtime availability, so low-spec users are not pushed into high-end defaults.
- Embedding product direction: deterministic/hash embeddings are a development fallback only. V1 should default to a real local LLM embedding model path, with user-selectable model configuration during setup/settings.
- External integrations: Context Bridge via MCP, local HTTP API, CLI, and copy/export helpers.
- Privacy: local-first by default.
- UI reference material: `UI-ref`.
- First desktop shell: Electron, chosen because Node is available and Rust/Tauri tooling is not installed in the current environment.
- Real app workspace: `apps/desktop`.
- Local backend workspace: `backend`.

## Local LLM Model Decisions

The first CML model ladder is saved for local synthesis. These are free, local-first, reproducible GGUF targets that the app can download/select during setup. Model weights should not be bundled into the first installer.

| Role                  | Model                      | Backend ID                   | Hugging Face repo                       | Quantization | Approx download | Recommended RAM | Notes                                                       |
| --------------------- | -------------------------- | ---------------------------- | --------------------------------------- | ------------ | --------------- | --------------- | ----------------------------------------------------------- |
| Default               | Qwen3 4B Q4_K_M            | `qwen3-4b-q4_k_m`            | `Qwen/Qwen3-4B-GGUF`                    | `Q4_K_M`     | ~2.5 GB         | 8+ GB           | Main recommended local synthesis model for V1.              |
| Low-spec fallback     | Phi-4 Mini Instruct Q4_K_M | `phi-4-mini-instruct-q4_k_m` | `unsloth/Phi-4-mini-instruct-GGUF`      | `Q4_K_M`     | ~2.5 GB         | 8+ GB           | Fallback for weaker machines if Qwen3 4B is not suitable.   |
| Quality option        | Qwen3 8B Q4_K_M            | `qwen3-8b-q4_k_m`            | `Qwen/Qwen3-8B-GGUF`                    | `Q4_K_M`     | ~4.8 GB         | 16+ GB          | Better answer quality for users with more memory.           |
| Optional later        | Gemma 3 4B IT Q4_K_M       | `gemma-3-4b-it-q4_k_m`       | `Aldaris/gemma-3-4b-it-Q4_K_M-GGUF`     | `Q4_K_M`     | ~2.5 GB         | 8+ GB           | Later comparison candidate.                                 |
| Optional larger later | Gemma 3 12B IT Q4_K_M      | `gemma-3-12b-it-q4_k_m`      | `nocturne23/gemma-3-12b-it-Q4_K_M-GGUF` | `Q4_K_M`     | ~6.9 GB         | 24+ GB          | Larger later experiment for higher-quality local synthesis. |

Runtime boundary:

- CML expects an OpenAI-compatible local runtime endpoint for synthesis.
- For llama.cpp, run `llama-server` with the selected GGUF.
- Ollama can be used if it exposes an OpenAI-compatible local API for the selected model.
- Retrieval-backed extractive drafts remain the fallback when no local synthesis runtime is available.
- Cluster experts are still a separate lifecycle; these synthesis models are the larger answer-composition layer, not the per-cluster expert adapters.
- Recommendations must separate normal chat requirements from LoRA expert-training requirements.

## Phase Progress

Use this section for fast status checks. Detailed historical notes remain in the later "Completed Work", "Open Work", and "Running Notes" sections.

| Phase | Status | Progress | Main Remaining Blocker |
| --- | --- | --- | --- |
| Product definition | In progress | `[##########] 99%` | Windows-only public release decision record. |
| UI prototype cleanup | In progress | `[##########] 99%` | Minimized/narrow desktop shell repair, dark-version QA, packaged-flow polish, broader visual QA. |
| Desktop app foundation | In progress | `[##########] 98%` | Clean VM launch validation and broader packaged startup repair QA. |
| Local backend foundation | Complete for current scope | `[##########] 100%` | Future service-layer cleanup only. |
| Vault ingestion | Complete for current scope | `[##########] 100%` | Clean VM confirmation only. |
| Embeddings and clustering | In progress | `[##########] 99%` | Broader threshold tuning on real user vaults. |
| Chat and context routing | In progress | `[##########] 96%` | Complete-scope map/reduce answering, token budgets, runtime failure UI. |
| Compulsory cluster experts | In progress | `[#######---] 70%` | Real LLaMA Factory smoke and live runtime adapter loading against a real local model. |
| Context Bridge | In progress | `[#########-] 94%` | Full extension package, capture UX polish, and later external-client smoke. |
| Packaging and installer | In progress | `[##########] 98%` | Clean Windows VM validation. |
| QA and hardening | In progress | `[##########] 99%` | Clean VM package validation, larger scale/performance benchmarks, model recommendation QA. |

### Current Critical Path

- Execute clean Windows VM validation against the 2026-06-04 package: no dev Python, no Node, no preinstalled OCR, cold first-run.
- Keep Windows-only public V1 criteria; if blockers remain, delay release rather than ship a private demo.
- Verify real adapter training/loading before using "trained expert" language in user-facing surfaces; current gates are stronger but still need real trainer/runtime proof.
- Build hardware-aware model recommendation for low-, mid-, and high-spec users.
- Tune retrieval thresholds and run larger backend benchmarks on real vault-shaped data.
- Defer Claude Desktop-specific Bridge smoke for now; keep external-client claims conservative.

### Phase Detail Snapshot

Product definition:

- Done: PRDs, UI PRD, onboarding PRD, connector/extension architecture, model ladder, runtime boundary, model storage decision, installer direction, production-gap notes, job/maintenance architecture, expanded-V1 notes, and public-V1 blocker list.
- Remaining: final production installer/update policy and explicit release cut line.

UI prototype cleanup:

- Done: core routes, generated-reference Vault shell/sidebar, Home/Mind, Sources, Clusters, Map, cluster detail, Chat, Settings/Profile, Tasks, Timeline/Activity, onboarding, Bridge controls, diagnostics UI, runtime/degraded states, retriable-generation UI, user footer, backend-first cleanup, command-palette accessibility fix, and Playwright audit.
- Remaining: minimized/narrow desktop shell repair, exact-match polish for Chat detail/Bridge/onboarding packaged flow, dark-version QA, and broader visual QA.

Desktop app foundation:

- Done: Electron workspace, Vite dev server, build, file IPC, authenticated backend identity probing, dev backend process handling, single-instance handling, encrypted backend token store, active vault folder config, pre-vault/full-vault env wiring, onboarding vault activation, startup failure page, vault-lock override action, failure copy-details action, embedding folder picker, and unpacked packaged launch.
- Remaining: clean VM launch validation and broader packaged startup repair QA.

Local backend foundation:

- Done: SQLite CRUD, ingestion routes, Bridge token auth, atomic background worker claim path, startup integrity/schema checks, migration tracking, vault ownership lock, fail-closed token middleware, authenticated backend identity route, Electron token handoff, startup-status readback, pre-vault guard, FastAPI lifespan migration, vector reconciliation queueing, startup repair summary, scheduler synthesis gate, runtime reporting, local generation paths, retriable generation recovery, expanded diagnostics export, expert scaffold, system preflight routes, extension/integration/model/embedding routes, and Bridge token rotation history.
- Remaining: future service-layer cleanup around raw route/database operations and continued recovery drills as schema changes.

Vault ingestion:

- Done: text/DOCX/PDF/code/common structured file ingestion, Windows-1252 fallback, OCRmyPDF plus Tesseract scanned-PDF path, PyMuPDF fallback, OCR health checks, OCR job policy, image OCR hooks, audio/video metadata, pasted text validation, static/dynamic links, URL credential stripping, drag/drop, local folder import, Obsidian metadata extraction, watched refresh jobs, reconciliation, batch outcomes, extension capture scaffold, chat attachments as sources, indexing blocks when embeddings are unavailable, page/chunk schema, tombstones, deletion cleanup, checksum dedupe, large-batch regression coverage, fallback OCR smoke, and full local OCRmyPDF smoke with staged Ghostscript/qpdf/Tesseract.
- Remaining: clean VM confirmation only.

Embeddings and clustering:

- Done: keyword clustering, chunking, required local embedding setup path, model/cache folder validation, folder picker, managed embedding download status/start/cancel API with byte/progress/speed/ETA fields, disk preflight, concurrent-download guard, local-only sentence-transformers attempts, MiniLM-first config, dev-only hash fallback, memory-search test UI, SQLite vector storage, semantic search, embedding health checks, broad-query scoring, vector repair plan/repair/compaction endpoints, active embedding-index transition policy, map search, suggestions, dismissals, merge controls, reconciliation job work, and chat coverage ledgers.
- Remaining: broader threshold tuning on real user vault data.

Chat and context routing:

- Done: global-by-default chat, LLM-first intent routing, small-talk handling, direct local runtime chat, prompt-zero attachments, attachment-to-source ingestion, persisted sessions/messages, pending generation records, retriable startup recovery, combined timeline endpoint, retrieval snapshots/items, streaming, page-aware citations, stale/deleted citation labels, source actions, runtime status, coverage-ledger accounting, expanded-analysis evidence jobs, degraded-runtime notes, reserved `complete_analysis` rejection, answer actions, transcript indexing, and local runtime adapter.
- Remaining: complete-scope map/reduce answering, token budgets, richer runtime failure UI, and long-running analysis UI.

Compulsory cluster experts:

- Done: expert lifecycle states, graduation contract API, deterministic dataset generation, source/token/validation/diversity gates, duplicate-ratio gate, train/validation split, dataset/config hashes, shell-free trainer process boundary, stdout/stderr capture, strict adapter config/weight validation, runtime-load plan metadata, metrics/quality-delta scaffold, deterministic evaluation harness, smoke scripts, active adapter selection, stale-adapter detection, rollback support, delete guardrails, artifact version metadata, backend/Desktop status surfaces, Expert tab, trainer dependency endpoint, contributor requirements, hardware gate, and Windows-path tests.
- Remaining: real LLaMA Factory smoke, runtime adapter loading against a live local model, richer metrics/rollback/failure UI states, hardware matrix expansion, retrieval-vs-adapter quality benchmark, and packaging/runtime QA.

Context Bridge:

- Done: Bridge UI, settings/history, HTTP context endpoint, token-gated access, constant-time token checks, per-client Bridge tokens, permission allowlists, permission refresh, semantic retrieval, denied-request logging, token rotation history, explicit no-active-vault behavior, MCP notification correctness, app error-code registry, extension token/capture scaffold, same-vault validation, and first CLI/MCP prototypes.
- Remaining: full extension package, capture UX polish, later external-client smoke when reprioritized.

Packaging and installer:

- Done: Windows packaging scaffold, Python runtime staging, NSIS build path, icon, unpacked launch smoke, post-install onboarding UI, disk preflight API/UI, non-bundled embedding setup direction, encrypted token-store abstraction, model download scripts, OCR runtime staging, auto-detected Tesseract staging, auto-detected Ghostscript staging, qpdf/tessdata verification, OCR benchmark command, OCRmyPDF/PyMuPDF packaged-runtime install, packaged loopback CORS allowlist, OCR runtime status visibility, silent install/uninstall smoke, packaged OCR/model staging verification, dynamic-link smoke, full-vault OCR smoke, migration drill, and valid 2026-06-04 package rebuild.
- Remaining: clean Windows VM validation.

QA and hardening:

- Done: broad backend regression suite, atomic job concurrency tests, local API auth/identity tests, OCR preference/fallback/status tests, dynamic-link/security tests, IPv4-mapped URL blocking tests, vault-safety tests, deletion/search cleanup tests, citation tests, duplicate/reconciliation/retrieval snapshot tests, vector repair/compaction/policy tests, chat attachment/routing tests, Bridge/MCP/token tests, diagnostic redaction/runtime-summary tests, migration/startup repair tests, disk/model preflight tests, extension tests, cancellation/progress contract tests, expert lifecycle tests, vault-lock tests, hardware-gate smoke, backend benchmark script smoke, Electron token-store regression, desktop UI build verification, clean Python/npm audits, packaged smoke suite, and Playwright UI audits.
- Remaining: real adapter smoke, adapter runtime-load smoke, retrieval-vs-adapter quality benchmark, clean VM package validation, larger scale/performance benchmarks, map benchmarks, real MCP client smoke, disposable-vault destructive UI tests, and more failure-state tests.

## Week-By-Week Goals

### Week 1: May 27 - May 31, 2026

Goal: lock project direction and convert V0 into a usable local-app foundation plan.

- Finalize product PRD and UI PRD.
- Add this project context/progress document.
- Review UI reference material and identify UI cleanup requirements.
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

- Completed the lean repository cleanup pass:
  - removed the tracked stale `UI-CML-V0` prototype copy; `UI-ref/` remains the preserved reference folder
  - removed the stale root `main.cjs` and replaced the duplicate root Node manifest with a lean workspace command shim; `apps/desktop/package.json` remains the live desktop manifest
  - deleted ignored generated artifacts and runtime files from the workspace, including desktop `dist`, `release`, packaging output, Wrangler/TanStack/Lovable caches, Playwright logs, dev logs, and local runtime `data`
  - updated README, architecture, working-command, requirements, and project-context docs so root npm commands forward to the real desktop workspace without duplicating dependencies
  - preserved contributor dependency environments (`.venv`, root `node_modules`, and `apps/desktop/node_modules`) so local verification stays runnable
- Completed the local-folder ingestion reconciliation pass:
  - extended integration refresh with an opt-in import/reconcile mode that imports new files, updates changed files, detects moved files by checksum, tombstones missing files when requested, and reports imported/updated/moved/unchanged/tombstoned/failed counts
  - added persistent integration import counters and `last_import_at` metadata
  - kept scan-only refresh backward-compatible for existing callers while wiring Settings to use `Refresh + import`
  - added batch failure reporting so one unreadable file does not abort the rest of the folder import
  - added regression tests for import/update/move/tombstone behavior and partial-failure reporting
- Completed the vault-ingestion finish pass:
  - added watch-enabled integration imports with bounded polling intervals and scheduled `integration_refresh` background jobs
  - wired Settings to toggle watched refresh and show next refresh plus recent failure metadata
  - persisted import failure details, watch state, interval, and next-watch timestamps
  - added Obsidian/Markdown frontmatter, wiki-link, embedded-attachment, and Markdown-link metadata extraction
  - corrected OCR readiness UI to show image OCR, PDF OCR, Ghostscript, qpdf, missing components, and runtime paths from the actual backend status contract
  - added regression coverage for watched refresh scheduling, Obsidian metadata extraction, 160-file batch import, and deletion graph cleanup from integration tombstones
  - verified the pass with full backend tests, Electron behavior/token tests, Python compile, desktop build, `pip check`, `pip-audit`, npm audit, and diff checks
- Completed the LoRA dependency/reproducibility pass plus README update:
  - split backend and LoRA trainer requirements so backend/OCR/test dependencies remain in `requirements/contributors-backend.txt` and LLaMA Factory/Gradio stay in `requirements/contributors-lora-trainer.txt`
  - kept `pydantic==2.13.4` for backend/OCR compatibility while moving Gradio's older Pydantic constraint out of the backend env
  - upgraded the active backend env to `pillow==12.2.0` and `starlette==1.0.1`
  - added `/api/v1/system/lora-trainer` to report installed trainer packages, CLI path, trainer-command configuration, test-trainer state, and issues
  - added `requirements/contributors-backend.txt`, `requirements/contributors-lora-trainer.txt`, and `requirements/README.md`
  - added `scripts/dev/update-requirements.ps1` and a continuous-update rule for dependency changes
  - added tests for LoRA trainer status and contributor requirements coverage
  - updated [README.md](../README.md) with contributor setup, split LoRA trainer environment instructions, expert states, and expert API surfaces
  - verified `pip check` has no broken requirements and `pip-audit` reports no known vulnerabilities in the active backend env; real LLaMA Factory smoke should run in the separate trainer env
- Completed the verified-LoRA foundation pass for public V1:
  - reviewed the merged contributor work and kept the useful dataset/profile/evaluation/artifact scaffold while replacing fake-success adapter behavior with a real training contract
  - added the public LoRA graduation contract with supported statuses, minimum dataset/quality gates, required adapter files, failure codes, and rollback behavior
  - encoded the expert lifecycle toward `retrieval_ready`, `training_pending`, `training_running`, `training_ready`, `training_failed`, `hardware_unsupported`, and `rollback_ready`
  - added deterministic cluster training dataset export with dedupe, train/validation split, dataset manifest, and dataset hash
  - added LoRA training configuration hashing and a LLaMA-Factory-compatible trainer process wrapper with stdout/stderr capture
  - made adapter success require required adapter files, quality metrics, and a positive quality delta before activation
  - expanded expert artifacts with dataset/config hashes, metrics JSON, active flag, rollback timestamp, and soft-delete timestamp
  - added API/client surfaces for expert contract, artifact activation, rollback, and deletion guardrails
  - added regression tests for verified adapter creation, activation metrics, rollback, and active-artifact delete blocking
  - checked the active `.venv`: `llamafactory` and `peft` are not installed, so real external LLaMA Factory smoke remains blocked on ML dependency/runtime installation
  - verified backend tests, Electron tests, and desktop build without rebuilding the package
- Completed the second 2026-06-02 ten-step hardening pass without starting a full package rebuild:
  - made dependent jobs enter `blocked_by_dependency` on enqueue and recover to queued when the parent succeeds
  - added missing-dependency cancellation handling for blocked jobs
  - recorded `PRAGMA user_version` during migration completion
  - stripped URL credentials before link fetch and before storing ingested source URLs
  - stripped credentials from redirect targets before validating/following redirects
  - tombstoned retrieval snapshot items before source page/chunk deletion so historical citations keep the correct deleted-source state
  - cancelled active source-scoped jobs when the source is deleted
  - strengthened diagnostic log redaction for bearer tokens, secrets/passwords, and local paths
  - added diagnostic-bundle regression coverage proving source text and secrets are excluded/redacted
  - verified full backend tests, Electron behavior/token tests, desktop Vite build, and diff checks; full package rebuild was intentionally skipped
- Completed the 2026-06-02 ten-step hardening pass without starting a full package rebuild:
  - fixed Windows-1252 plain-text ingestion fallback and removed that expected-failure test
  - completed the vault-lock override audit sequence with detection, dialog, user-choice, startup-result, and acquired events
  - blocked concurrent managed model downloads before a second download can start
  - added same-vault validation coverage for browser-extension capture cluster assignment
  - added Electron token-store plaintext regression coverage for the encrypted/safeStorage token path
  - verified targeted backend tests, the full backend unit suite, Electron behavior/token tests, and the desktop Vite production build
- Completed the 2026-06-01 six-step build/audit pass:
  - removed remaining production-shaped mock fallbacks from Map, Clusters, Chat, Timeline, and command-palette paths so core surfaces now rely on backend/vault state instead of seeded demo records
  - added dedicated Bridge client tokens with independent permission scopes, token rotation history, disable/revoke behavior, and Bridge UI management
  - added managed embedding-model download status/start/cancel backend routes plus onboarding/settings controls for the recommended memory-search model path
  - tightened startup repair UX with native confirmation before lock override and copyable diagnostic details on startup failure
  - extended deletion/Bridge/embedding tests for per-client Bridge permissions, embedding download failure handling, and chat transcript source/chunk cleanup
  - ran a thorough Playwright UI interaction audit and documented findings in [UI_INTERACTION_AUDIT_2026-06-01.md](UI_INTERACTION_AUDIT_2026-06-01.md)
- Added Electron-facing vault-lock Open-anyway recovery from the startup repair page, with one-shot backend override env wiring and backend audit records that capture the explicit `open_anyway` user choice.
- Added an Electron embedding-model folder picker and wired it into onboarding and Settings so required SentenceTransformers setup can be selected and tested from the app instead of only typed manually.
- Removed seeded mock-data fallbacks from the shared sidebar, Home/Mind summary, Sources, and Settings storage/profile surfaces so missing backend/vault states stay visibly empty and honest.
- Hardened Bridge MVP behavior: denied requests are logged, missing/ambiguous vault scope now returns explicit `no_active_vault`, token rotations are stored/readable, `/bridge/clusters` is token-gated, MCP notifications produce no response, and MCP app error codes are stable.
- Added regression coverage for Bridge no-active-vault behavior, token rotation history, MCP notification/error-code behavior, and deleted-source citation tombstones; verified backend tests and desktop production build.
- Created [PRODUCT_PRD.md](PRODUCT_PRD.md).
- Created [UI_PRD.md](UI_PRD.md).
- Created [ONBOARDING_PRD.md](ONBOARDING_PRD.md) for the minimal Apple-like first-run setup flow, current OKLCH color scheme, vault-path behavior, required embedding setup, local chat setup, startup repair states, and acceptance criteria.
- Added Context Bridge requirements to both PRDs.
- Reviewed the initial UI reference material.
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
- Added a unified brighter Vault UI system inspired by the current moodboard direction: warm neutral shell, coral/mint/lilac/amber accents, graphite-ready dark tokens, Aptos/SF-style type stack, shared card/panel/shell utilities, refreshed buttons/inputs, and consistent cluster/status styling.
- Refactored the app shell/sidebar, chat landing surface, onboarding visuals, cluster list, and cluster detail surfaces to use the new UI system.
- Rebuilt the clusters page as a real memory-space workspace with overview stats, stronger cluster identity cards, source-density rails, and a cleaner suggested-move review queue.
- Verified the redesigned onboarding and clusters pages in the Vite shell with Playwright screenshots, then verified desktop production build with `npm run build --workspace @cml/desktop`.
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
- Added generated-reference UI pass for Vault:
  - AppShell now matches the reference desktop frame with Home/Timeline/Tasks/Activity navigation, recent clusters, saved chats, bottom user tab, and bottom status/privacy footer.
  - Mock data now mirrors the reference world: Design Research, Product Strategy, Health & Longevity, Travel Japan 2025, Meeting Notes, realistic sources, and saved chats.
  - Home/Mind uses the reference prompt workspace with backend chat routing, recent memories, unsorted sources, suggested clusters, right health/actions/activity rail, and scrollable content.
  - Map now follows the specified old reference image `ig_015215293cf7ae25016a1c50a99ff881918f421c3047c44a24.png`: card-node graph, search/filter/fit/list controls, list fallback, and right cluster inspector.
  - Cluster detail now follows the specified reference image `ig_015215293cf7ae25016a1c4fef23608191ac77b9fc2c4bc45a.png`: back link, title/actions, tabs, top-memory/recent-source tables, learning status, recent sources/chats, and right detail rail.
  - Prompt-zero Chat now has the reference three-column layout with chat list, central Ask Vault composer, attachment button, global/cluster scope selector, backend-first session creation, and right context inspector.
  - Settings now includes a real Profile section matching the generated profile/settings direction, while keeping local model, embedding, OCR, disk, diagnostics, privacy, and device readiness surfaces.
  - Visual smoke screenshots were taken for Home, Settings, Map, cluster detail, and Chat; `npm run build --workspace @cml/desktop` passes after the redesign changes.
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
- Added [JOB_AND_MAINTENANCE_ARCHITECTURE.md](JOB_AND_MAINTENANCE_ARCHITECTURE.md) as the target scheduler/maintenance architecture:
  - fixed write-scope vocabulary
  - concrete timeout policy structure
  - separate `user_visible` and `user_initiated`
  - preemption rules
  - V1 dependency model
  - filled job type registry
  - scheduler rules and startup recovery state tables
- Started Phase 1 scheduler implementation:
  - extended `app_jobs` with scheduler policy fields, dependency fields, scope/concurrency fields, lifecycle timestamps, and status detail
  - added a code-level job registry for `reindex_source` and `chat_transcript_memory`
  - made enqueued jobs persist resolved policy metadata
  - replaced FIFO claim with priority, dependency, write-scope, and concurrency-group aware claiming under the V1 single-worker assumption
  - added startup recovery for interrupted `running` jobs based on restart policy
  - added `manual_review`, `cancelled`, and `blocked_by_dependency` queue accounting
  - added checkpoint tests for priority order, dependency cancellation, restart requeue, unknown job safety, and same-scope waiting
- Started Phase 2 backend ownership/auth hardening:
  - added SQLite startup integrity/schema checks with `PRAGMA integrity_check`
  - added optional local API token middleware that protects private routes when `CML_API_TOKEN` is configured while keeping `/health` and docs public
  - added backend vault ownership through a `.vault.lock` file with PID/process verification and reclaim of dead/reused locks
  - added Electron single-instance handling that focuses/restores the first window and refuses a second vault writer
  - added Electron backend-token handoff through preload IPC and persisted token storage under the app data directory
  - queued lightweight vector reconciliation during startup after ownership, integrity, and schema checks
  - manual dev backends remain unauthenticated when `CML_API_TOKEN` is absent; Electron-managed backends now receive and require a token
- Started Phase 3 ingestion/indexing rework:
  - added `source_pages` table with page number, raw text, extraction version, and SHA-256 content hash
  - extended `source_chunks` with `page_id`, `embedding_model_id`, chunk content hash, index version, and indexed timestamp
  - changed reindexing to create/use source pages and write page-linked chunks
  - changed path ingestion to preserve per-page PDF text when available
  - added source-level checksum storage and conservative same-vault duplicate detection
  - changed source deletion to tombstone immediately, exclude from search immediately, and queue cleanup for derived page/chunk data
  - made MiniLM the default embedding backend and moved hash embeddings behind an explicit dev/test flag
  - added focused test coverage for page-linked chunk creation, source deletion/search exclusion, cleanup, duplicate detection, incremental vector reconciliation queueing, and scheduler checkpoints
- Continued Phase 3 ingestion expansion:
  - expanded local ingestion to CSV, JSON/JSONL, HTML/HTM, XML, YAML, RTF, logs, common source-code files, images, and small audio/video files
  - image ingestion uses OCR if `pytesseract`/Pillow are present and otherwise stores file metadata with an explicit OCR-not-configured note
  - small audio/video files currently ingest as metadata records; transcription remains a separate model/runtime feature
  - expanded Electron file picker and folder scan allowlist to match the broader backend ingestion allowlist
- Added runtime/generation durability foundations:
  - local model runtime status now reports `missing`, `checking`, `ready`, `busy`, or `unreachable`, plus in-flight generation count
  - chat requests persist user prompts and `chat_generations` before synthesis/streaming begins
  - backend startup marks interrupted `in_flight` generations as `retriable`
- Added chat retrieval durability:
  - added `retrieval_snapshots` and `retrieval_snapshot_items` tables separate from `chat_messages`
  - retrieval snapshot items store source/chunk/page IDs, page number, source title at answer time, snippet hash, short excerpt, score, rank, and state
  - assistant message save and retrieval snapshot writes happen in the same SQLite transaction
  - added tests for snapshot writes and interrupted generation recovery
- Added bundled-local OCR foundations:
  - added a local OCR adapter that runs `backend/bin/ocr/tesseract.exe` directly with local `tessdata`
  - scanned PDFs now prefer OCRmyPDF plus bundled Tesseract when embedded text is missing
  - scanned PDFs fall back to page-by-page local OCR through PyMuPDF rendering when OCRmyPDF is unavailable during development
  - added `/api/v1/system/ocr` so Settings can report Tesseract, OCRmyPDF, tessdata, Ghostscript, qpdf, full-PDF OCR readiness, fallback-PDF OCR readiness, and selected OCR engine
  - registered an `ocr_source` background job policy/runner so OCR-heavy reprocessing can show up in the visible job queue
  - images run through the bundled OCR engine when present and otherwise vault as metadata with an explicit local-OCR-unavailable note
  - packaging now includes `backend/bin/**/*` and the packaged Python runtime installs PyMuPDF and OCRmyPDF
  - added `scripts/packaging/stage-ocr-runtime.ps1`; installed Tesseract and Ghostscript are now auto-detected and staged as full local runtime folders, and qpdf plus `eng.traineddata` stage successfully
  - added `scripts/ocr/benchmark-ocr.ps1` for repeatable OCR similarity, recall, and precision reports
  - bundled-runtime fallback OCR smoke on the generated scanned `PROJECT_CONTEXT` PDF reached 0.9891 normalized similarity, 0.9896 source-word recall, and 0.9884 source-vocabulary precision
  - bundled-runtime full OCRmyPDF smoke on the same generated scanned `PROJECT_CONTEXT` PDF reached 0.9769 normalized similarity, 0.9840 word recall, and 0.9880 word precision after local Ghostscript staging
  - live public GitHub OCR sample smoke reached 1.0000 similarity against the PDF text layer and 0.9834 word recall / 0.9647 word precision against the repository output text; low 0.0948 sequence similarity against the repository text is due table reading-order differences, not missing words
  - remaining OCR packaging caveat: full OCRmyPDF is verified in the local bundled runtime, but not yet in a fresh packaged app install smoke
  - `docs/WORKING_COMMANDS.md` records the expected OCR bundle location and common dev commands
- Completed the OCR/package-readiness ten-step build sprint:
  - made OCR staging auto-detect an installed Tesseract binary from PATH, `%LOCALAPPDATA%`, and Program Files
  - made OCR staging copy the full Tesseract install folder so packaged fallback OCR has the required DLLs, not just `tesseract.exe`
  - made OCR staging auto-detect an installed Ghostscript binary from PATH and Program Files, then copy the Ghostscript runtime root so OCRmyPDF has `bin`, `lib`, and `Resource`
  - added executable verification for the staged Tesseract runtime
  - added package-time flags for `-TesseractExePath`, `-GhostscriptExePath`, `-SkipGhostscriptInstaller`, and `-AllowPartialOcrRuntime`
  - staged the local app OCR runtime under `backend/bin/ocr` with working Tesseract, `eng.traineddata`, qpdf, and Ghostscript
  - verified backend bundled-runtime OCR status without `CML_OCR_BINARY_PATH`: image OCR ready, full OCRmyPDF scanned-PDF OCR ready, fallback scanned-PDF OCR also ready, no missing components
  - added `scripts/ocr/benchmark-ocr.ps1` for repeatable OCR similarity/recall/precision checks
  - reran generated scanned `PROJECT_CONTEXT` OCR benchmark through the bundled runtime: 0.9891 sequence similarity, 0.9896 word recall, 0.9884 word precision
  - reran generated scanned `PROJECT_CONTEXT` OCR benchmark through full OCRmyPDF after Ghostscript staging: 0.9769 sequence similarity, 0.9840 word recall, 0.9880 word precision
  - reran the public GitHub OCR sample benchmark through the bundled runtime: 0.9834 word recall and 0.9647 word precision against repository text
  - verified full backend tests, Electron tests, desktop build, dependency checks, Python audit, npm audit, and diff checks
- Completed the non-LoRA backend hardening build pass:
  - added normalized embedding and local-model download progress fields: `bytes_total`, `progress_percent`, `download_speed_bps`, `eta_seconds`, `started_at`, and `updated_at`
  - added vector maintenance helpers and backend endpoints for repair planning, repair execution, compaction, and active embedding-index transitions
  - wired startup vector reconciliation through the new repair planner so missing chunks, stale model IDs, stale index versions, and missing `indexed_at` are handled consistently
  - added `/api/v1/system/startup-repair` for read-only startup repair summary and opt-in interrupted-job recovery
  - expanded diagnostic bundles with runtime, startup repair, and vector summaries while keeping raw user content out
  - added `/api/v1/sources/link-diagnostics` for backend-only link sanitization, security, timeout, byte-limit, and dynamic-fallback readiness checks
  - hardened URL validation for direct IP literals and IPv4-mapped IPv6 loopback/private addresses
  - tightened Bridge token checks with constant-time comparisons and overlong-token rejection
  - added `scripts/backend/benchmark-backend.ps1` for repeatable backend ingestion/index/search/repair timing
  - verified the benchmark smoke with 25 sources and full backend unittest suite: 143 tests run, 1 skipped
- Added page/citation visibility:
  - added `/sources/{source_id}/pages`
  - Sources detail sheet now shows extracted pages
  - chat citation chips show page numbers and stale/deleted source labels from retrieval snapshots
- Added chat attachment ingestion:
  - chat requests now accept local file attachments
  - desktop chat composer can attach local files with the existing supported file picker
  - prompt-zero chat now exposes the attachment control before the first user message
  - chat accepts drag/drop attachments and shows ready/storing/stored/failure states around the send flow
  - attached files are extracted, stored as normal `sources`, page/chunk indexed immediately, and linked to the user message through `chat_attachments`
  - selected chat cluster is used as the target cluster for attachments, so "read/store/combine this with this cluster" works through the current scope picker
  - chat transcript memory includes attachment source references so attachment-backed context survives transcript indexing
  - added backend test coverage proving chat attachments become indexed cluster sources
- Added first complete-scope answering foundation:
  - chat retrieval now returns a coverage ledger with sources considered, sources analyzed, and low-relevance source count
  - streaming chat surfaces the ledger before synthesis so broad answers can explain scope before writing
  - source-level broad-query scoring now scores all indexed chunks in scope, ranks distinct sources, and only analyzes the selected top source set
  - added `analysis_evidence_packets` and an `expanded_analysis` job that writes per-source evidence packet records for the current expanded-analysis path
  - coverage is still pre-map/reduce; evidence packets, threshold tuning, partial-failure accounting, and cache policy remain to build
- Improved chat runtime/citation transparency:
  - chat header now shows local LLM runtime availability
  - streaming notes make local-runtime fallback visible rather than silent
  - citation popovers can open the original file, reveal it in Explorer, or jump to Sources; stale/deleted citations continue to show the saved excerpt
  - greetings and small-talk prompts now answer directly without vault retrieval, so chat behaves like a chatbot first
  - chat transcript sources are excluded from normal retrieval unless the user explicitly asks about prior chats or conversation history
  - added a regression test for the `Hello` prompt so it cannot be answered with old transcript snippets again
- Completed the LLM-first chat routing pass:
  - general conversation is now routed to the configured local OpenAI-compatible LLM runtime first instead of defaulting to semantic retrieval
  - vault retrieval is only used when the prompt asks for vault/source/cluster/context knowledge, includes attachments, scopes to a cluster, or explicitly runs complete analysis
  - streaming responses expose `intent` and `runtime_state` metadata so the UI can distinguish local LLM chat, retrieval-backed answers, complete analysis, and degraded runtime states
  - when the local LLM runtime is unavailable, general chat shows an explicit degraded answer instead of disguising retrieval output as normal chatbot behavior
  - the chat detail UI now shows a local-runtime offline banner and a visible `Complete analysis` action that reruns the last prompt through broader source accounting
  - added backend regression coverage for general-chat degraded routing and explicit complete-analysis routing
- Improved attachment result visibility:
  - chat responses and streams now return the sources created from attachments
  - the chat UI shows stored attachment source names after ingestion completes
- Fixed saved-chat sidebar freshness:
  - the global app sidebar now reads saved chats from backend sessions instead of the old mock store when the backend is online
  - save/delete/title-generating chat flows dispatch a shared refresh event and the sidebar also polls periodically
- Improved Bridge permission freshness:
  - Bridge status returns a refresh timestamp
  - backend status sanitizes deleted vault/cluster allowlist IDs and persists the cleaned allowlist
  - Bridge UI filters permissions against current vaults/clusters, refreshes every minute, and exposes a manual refresh action
- Added local-first diagnostics:
  - backend startup configures rotating local logs under `data/logs` with a 5MB x 10-file policy
  - added `POST /api/v1/diagnostics/bundle`, which writes a local zip with manifest, app/backend/schema versions, database counts, integrity-check result, and redacted logs
  - Settings now exposes a diagnostic bundle export action and shows the local bundle path
  - added backend tests for stale Bridge permissions and diagnostic bundle creation
- Repository hygiene:
  - removed `codex-skills` from Git tracking and added it to `.gitignore` so local Codex skill material does not publish to GitHub
- Audio/video transcription remains a V1 todo. Current audio/video ingestion intentionally stores metadata only until a local transcription runtime is selected and benchmarked.
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
- Fixed the first UI audit cleanup pass:
  - removed remaining mojibake/oversized serif UI copy from active desktop routes
  - centralized backend record-to-UI mapping in `apps/desktop/src/lib/recordAdapters.ts`
  - made command palette new-chat creation backend-aware with a mock fallback
  - changed app-shell shortcuts so they route to backend-aware screens instead of silently creating mock-only records
  - improved map cluster opening from hidden double-click to click/keyboard activation while preserving drag behavior
  - made map source previews focusable and reduced decorative glow styling
  - added accessible labels to key icon controls
  - converted nonfunctional Bridge, cluster expert, attachment, save/regenerate, and cluster source-picker controls into explicit pending/setup states
  - stopped Settings from saving vault path on input blur
  - fixed the onboarding Windows path placeholder
  - verified the desktop production build with `npm run build`
- Activated the local development stack after the UI audit pass: backend health is responding at `http://127.0.0.1:7342/health` and the desktop UI dev server is responding at `http://127.0.0.1:5173/`.
- Fixed the local Electron launch issue for this session by starting Electron with `ELECTRON_RUN_AS_NODE` removed; the inherited environment had `ELECTRON_RUN_AS_NODE=1`, which made Electron behave like Node and crash before opening a window.
- Wired the cluster detail route to real backend data:
  - added frontend `getCluster` and `updateCluster` helpers
  - cluster detail now loads backend cluster metadata, vault sources, and scoped chat sessions
  - cluster rename persists through the backend when available
  - "Chat with cluster" creates a backend chat session scoped to the selected cluster
  - cluster source, chat, expert, and map tabs now render backend-backed data with mock fallback only if the backend lookup fails
  - verified current cluster/source API compatibility against the running backend
  - verified production build with `npm run build`
- Completed the next chat-action pass:
  - app-shell and Chat index `New chat` now create a backend chat session when a vault exists, so the user lands on a real chat composer instead of a dead created-chat state
  - Chat index and Chat detail now expose backend chat deletion
  - assistant answer `useful` and `saved` actions persist through `PATCH /api/v1/chat/messages/{message_id}`
  - regenerate reuses the prior user prompt in the current chat view
  - every persisted chat turn is converted into an indexed transcript source
  - transcript memory is attached to each cluster used by the chat; unscoped chats fall back to a dedicated `Chats` cluster
  - deleting a chat also deletes its generated transcript source records
  - refreshed chat context after answers so newly indexed transcript memory appears in the UI-backed source/cluster state
- Completed the first semantic Context Bridge backend pass:
  - `POST /api/v1/bridge/context` now accepts an optional `vault_id` and `limit`
  - bridge context retrieval uses local semantic search instead of arbitrary latest-source metadata
  - bridge responses preserve ranked source order and selected matching clusters
  - bridge requests continue to be logged for the Bridge UI request history
- Verified backend syntax with `.venv\Scripts\python.exe -m compileall backend\app`.
- Verified production desktop build with `npm run build`.
- Smoke-tested chat transcript memory directly against the backend: created a chat, persisted a turn, saved/marked the assistant answer useful, confirmed one transcript source was created, deleted the chat, and confirmed transcript cleanup.
- Smoke-tested semantic Bridge retrieval with a temporary indexed source; the Bridge returned the matching source through semantic search and the temporary source was removed after verification.
- Added configurable desktop backend targeting:
  - desktop API helpers now default to `http://127.0.0.1:7343`
  - added `VITE_CML_BACKEND_URL` to `.env.example`
  - updated root backend npm scripts and quick-start checks to use `7343`
  - backend health now checks for current chat routes and reports a degraded state if an old backend is reachable but missing them
- Added first Bridge permission system:
  - created a `bridge_settings` SQLite table
  - added `PATCH /api/v1/bridge/settings`
  - `GET /api/v1/bridge/status` now returns enabled state, allowed vaults/clusters, and raw/style/expert permissions
  - `POST /api/v1/bridge/context` now blocks requests when Bridge is off, enforces vault and cluster allowlists, and redacts raw source text unless explicitly allowed
  - Bridge UI can enable/disable Bridge, choose allowed vaults/clusters, toggle raw text/style/expert access, and copy a local HTTP example
- Added chat memory status polish:
  - added `memory_status` and `memory_updated_at` to chat sessions
  - chat context responses now report memory indexing status
  - Chat view shows memory saved/saving/idle state
  - backend answers progressively render in the chat view after retrieval/synthesis completes
- Restarted the current-code backend on `http://127.0.0.1:7343`.
- Verified the live backend exposes `/api/v1/bridge/settings`, current Bridge routes, and current Chat routes.
- Smoke-tested Bridge permissions against the live backend: disabled Bridge blocked access, enabled allowlisted Bridge returned a semantic match, and raw source text was redacted.
- Smoke-tested chat memory status against the live backend: a persisted chat turn returned `memory_status=indexed` and stored `memory_updated_at`.
- Verified backend syntax with `.venv\Scripts\python.exe -m compileall backend\app`.
- Verified production desktop build with `npm run build`.
- Added true chat streaming path:
  - added OpenAI-compatible SSE parsing in the local LLM runtime adapter
  - added `POST /api/v1/chat/context/stream`
  - stream endpoint emits `meta`, `token`, and `done` events
  - fallback retrieval drafts stream as chunks when the local model runtime is unavailable
  - Chat UI now consumes the streaming endpoint instead of revealing a fully completed answer after the fact
- Added Bridge client token auth:
  - added `bridge_token` to Bridge settings
  - Bridge context now requires `x-cml-bridge-token` when Bridge is enabled
  - Bridge UI can copy and rotate the local Bridge token
  - copied HTTP examples now include the token header
- Added real cluster source management:
  - cluster detail can remove a source from a cluster
  - cluster detail can add another vault source to the current cluster
  - selected cluster sources can be moved into a newly created cluster
  - source changes mark affected local experts as needing an update through the expert lifecycle scaffold
- Added compulsory expert lifecycle scaffold:
  - added `cluster_expert_jobs` table
  - added expert lifecycle helpers for refresh-needed and queued jobs
  - added `GET /api/v1/clusters/{cluster_id}/expert/jobs`
  - added `POST /api/v1/clusters/{cluster_id}/expert/retrain`
  - added `POST /api/v1/clusters/{cluster_id}/expert/pause`
  - cluster detail Expert tab can queue learning, pause learning, and show recent expert jobs
  - new indexed sources, source moves/changes, and chat transcript memory now create expert refresh-needed jobs
- Restarted the current-code backend on `http://127.0.0.1:7343`.
- Smoke-tested all four new areas against the live backend:
  - source move/remove
  - expert retrain/pause/jobs
  - Bridge token blocking and token-authorized semantic retrieval with raw text redaction
  - chat stream `token`/`done` events and persisted memory status
- Verified backend syntax with `.venv\Scripts\python.exe -m compileall backend\app`.
- Verified production desktop build with `npm run build`.
- Added Electron backend service management:
  - Electron checks for an existing current backend before spawning a new one
  - if needed, Electron starts FastAPI on an open loopback port in the `7343-7355` range
  - the selected backend URL is passed to the renderer through query params and IPC
  - spawned backend processes are stopped when the Electron app quits
- Added frontend backend URL handoff so the desktop app can use the Electron-managed backend while still falling back to configured/probed local URLs.
- Added configurable embedding runtime support:
  - default remains deterministic hash embeddings for dependency-light local runs
  - optional `sentence-transformers` provider can be enabled through `CML_EMBEDDING_PROVIDER=sentence-transformers`
  - added `CML_EMBEDDING_MODEL` and `CML_EMBEDDING_DIMENSIONS`
  - added `GET /api/v1/models/embeddings`
  - Settings now shows embedding provider, model, dimensions, and availability
- Added first Windows packaging scaffold:
  - electron-builder config in the desktop package
  - root `npm run package:win`
  - `scripts/packaging/package-windows.ps1`
  - backend source staging into the desktop package resources
- Updated `.env.example` with embedding provider settings.
- Updated `package-lock.json` after adding packaging dependencies.
- Verified the latest desktop/service/embedding pass with backend compile, Electron syntax checks, desktop production build, and backend smoke checks for `/health`, `/openapi.json`, and `/api/v1/models/embeddings`.
- Added a SQLite-backed background job queue:
  - new `app_jobs` table with queued/running/succeeded/failed states
  - backend startup starts a lightweight daemon worker
  - added `GET /api/v1/jobs/status`
  - added `POST /api/v1/jobs/run-once` for deterministic local testing
- Moved source chunk reindexing into queued background jobs.
- Moved chat transcript memory indexing into queued background jobs:
  - persisted chat turns now return `memory_status = indexing`
  - the worker creates/updates transcript source records
  - the worker marks the chat session `indexed` after transcript chunks are stored
- Added shared `backend/app/core/chat_memory.py` so transcript memory is handled outside the chat route.
- Strengthened the Windows packaging scaffold:
  - packaged Electron now expects the backend Python runtime under `resources/python-runtime`
  - packaging script creates a Windows venv runtime and installs backend dependencies into it
  - electron-builder now includes both backend source and the staged Python runtime
- Added `CML_EMBEDDING_CACHE_DIR`.
- Added `scripts/llm/install-embedding-model.ps1` to install/download `sentence-transformers/all-MiniLM-L6-v2` into `T:\LLM\embeddings` or a chosen target folder.
- Restarted the current backend on `http://127.0.0.1:7343`.
- Smoke-tested queued source indexing: created a source, saw a queued job, ran jobs once, and semantic search returned the indexed chunk.
- Smoke-tested queued chat memory: persisted a chat turn, received `memory_status = indexing`, ran jobs once, and confirmed the session moved to `indexed`.
- Verified this pass with backend compile, Electron syntax checks, desktop production build, PowerShell script syntax checks, `git diff --check`, and embedding status smoke test.
- Reworked the Chat index tab into a usable chat entry surface:
  - added a real prompt textarea instead of an empty-state-only panel
  - added global/cluster scope selection
  - creates a backend chat session from the first prompt
  - forwards the pending prompt into the chat detail route and auto-sends it after the session loads
  - keeps Ctrl/Cmd Enter as the quick-send shortcut
- Installed and validated the optional local embedding model:
  - installed `sentence-transformers` into the local Python environment
  - downloaded `sentence-transformers/all-MiniLM-L6-v2` into `T:\LLM\embeddings`
  - set local `.env` embedding values for provider, model, dimensions, and cache directory
  - verified the live backend can report the SentenceTransformers provider when launched with the local `.env`
  - smoke-tested MiniLM semantic search against a temporary indexed source
- Hardened the Electron developer launch path by adding `apps/desktop/scripts/start-electron.cjs`, which clears `ELECTRON_RUN_AS_NODE` before starting Electron.
- Updated `.gitignore` so generated desktop packaging runtime/source staging stays out of git.
- Finished the first real Windows package pass:
  - fixed the desktop packaging script to use `npm exec electron-builder`
  - added required desktop app metadata for electron-builder
  - disabled local code-signing/editing for unsigned development builds to avoid Windows symlink extraction failures
  - bumped Electron to `39.8.10` after audit flagged the older pinned version
  - rebuilt the NSIS installer at `apps/desktop/release/CML Setup 0.1.0.exe`
  - launched `apps/desktop/release/win-unpacked/CML.exe` and verified its bundled backend returns `/health` on `127.0.0.1:7343`
- Verified this pass with backend compile, Electron script syntax checks, desktop production build, Windows package build, unpacked packaged-app launch smoke, `npm audit`, and `git diff --check`.
- Reworked the Windows installer toward a cleaner setup experience:
  - switched electron-builder NSIS to one-click, per-user, no-elevation install
  - removed the install-directory wizard step and desktop shortcut default
  - added a generated CML app icon so the installer and packaged app no longer fall back to Electron branding
  - rebuilt the branded installer at `apps/desktop/release/CML-0.1.0-Setup.exe`
- Added packaged embedding setup controls:
  - added `POST /api/v1/models/embeddings/configure`
  - added runtime embedding provider overrides stored under local app data
  - updated Settings so users can choose lightweight hash embeddings or MiniLM/SentenceTransformers with an optional cache folder
  - changed embedding status checks so Settings does not load model weights just to display availability
  - added `-IncludeEmbeddingRuntime` to the Windows packaging script for builds that intentionally bundle optional SentenceTransformers dependencies
- Added first Context Bridge external-client prototypes:
  - added `backend.app.bridge_cli`
  - added `scripts/bridge/cml-bridge.ps1`
  - added `backend.app.bridge_mcp` with `list_clusters` and `get_cluster_context` tools over stdio JSON-RPC
  - added Bridge UI copy actions for HTTP, CLI, token, and MCP config examples
- Tightened frontend/Electron backend freshness probes so the app rejects stale backends missing the current embedding setup route.
- Verified this pass with backend compile, desktop production build, embedding configure smoke, Bridge CLI/MCP syntax checks, Windows package build, and unpacked packaged-app backend launch smoke.
- Fixed the unpacked packaged app blank screen by serving the TanStack Start production renderer through a local Electron-owned loopback renderer server instead of trying to load a missing `dist/client/index.html` file through `file://`.
- Added cancellable model downloads:
  - added `POST /api/v1/models/{model_id}/download/cancel`
  - added cooperative cancellation and partial-file cleanup in the model download worker
  - added a Settings `Cancel` button while a model download is resolving or downloading
- Restarted the current backend on `http://127.0.0.1:7343` and verified the new cancel and embedding setup routes.
- Rebuilt and smoke-tested `apps/desktop/release/win-unpacked/CML.exe`; the window now opens to `Mind` and the packaged renderer server listens on a local loopback port.
- Fixed Settings local scrolling and narrow-window overflow without rebuilding the release package.
- Reworked Chat toward a context-first workspace:
  - the Chat index now defaults to all vault context instead of asking the user to choose global vs cluster first
  - cluster scope remains available as an optional context selector
  - chat detail now includes a session list, context-used rail, runtime notes, stop/retry controls, and route reload handling when switching chat IDs
  - local model synthesis now uses a shorter interactive timeout and falls back to retrieval drafts instead of hanging when the runtime is slow or unavailable
- Fixed Chat route nesting so generated and existing `/chat/{id}` sessions open the real chat detail instead of leaving the user on the starter composer.
- Fixed a Chat send race where the pending first prompt could complete before the backend session was attached, leaving no assistant reply in the UI.
- Tightened Bridge permission freshness:
  - the backend now prunes deleted/stale vault and cluster IDs from Bridge settings
  - the Bridge page refreshes full backend status, vaults, clusters, and request history after saves and on a one-minute timer
- Improved cluster organization:
  - suggested cluster moves can be accepted or dismissed
  - clusters can be merged into another cluster, moving sources and scoped chats and marking the target expert stale
- Added app-wide background job visibility in the footer with queued/running/failed counts and a run-once action.
- Captured the May 30 product-gap pass in project context:
  - broaden ingestion requirements to common local memory types, bounded small video/audio, OCR, scanned PDFs, and dynamic links
  - require PDF pagination/page-level context storage
  - require 1,000+ document cluster storage/retrieval planning with bounded cache usage
  - require Bridge permission freshness, saved-chat refresh, and cluster/map visual/data-point fixes
  - mark deterministic/hash embeddings as development fallback only, with real local embedding setup as the product default
- Captured the final production-risk review in project context:
  - public V1 now has an explicit blocker list; if these are not complete, the release slips and must not be treated as public-ready
  - vault data path correctness is a product blocker: user-selected vault folders must own the real SQLite database and derived local data, not only a metadata display path
  - pre-vault backend mode must be route-restricted and must not create real vault/source/chat/cluster records before the full vault backend starts
  - startup failure reporting needs a shared startup phase registry, startup-status file, and Electron repair/startup error surface
  - scheduler synthesis gating must account for active/retriable generations and expose running job detail before the UI promises background work will pause
  - current "complete analysis" behavior must be renamed to "expanded analysis"; `complete_analysis` is reserved for future map/reduce and must be rejected if requested
  - expert/training language must remain honest: public V1 requires verified LoRA adapter training, metrics, rollback, and supported-hardware language before claiming a cluster expert is trained
  - MCP bridge needs strict JSON-RPC notification handling, app error code registry, no-active-vault errors, and later external-client smoke before broad advertising
  - transcript memory retrieval needs source-class weighting and separate compare-source-classes handling, not only keyword inclusion/exclusion
- Completed the first public-V1 blocker implementation pass:
  - added canonical startup phase data at `shared/startup-phases.json`
  - added backend startup status writes through `CML_STARTUP_STATUS_PATH`
  - added `CML_BACKEND_MODE=pre_vault | full_vault` and route middleware that blocks vault/source/chat/search/cluster/Bridge APIs in pre-vault mode
  - wired Electron to store an active vault folder, create `<vault>/.vault`, and start full-vault backends with `CML_DATA_DIR=<vault>/.vault` and `CML_DATABASE_PATH=<vault>/.vault/cml.sqlite3`
  - onboarding now asks Electron to activate the chosen vault folder before creating the backend vault record
  - embedding health now gates semantic search, vault reindexing, source ingestion, chat attachment ingestion, and background vector/chat-memory jobs with explicit `409` errors instead of silent hash/empty-context behavior
  - retrieval-intent chat now returns an explicit degraded memory answer when embeddings are unavailable instead of falling through to LLM-only context
  - background job claiming now respects `can_run_during_synthesis` by checking active/recent retriable chat generations before claiming non-synthesis-safe jobs
  - job status now exposes running jobs with elapsed and estimated remaining seconds
  - added a combined chat timeline endpoint that includes retriable generation placeholders
  - chat UI renders interrupted/retriable generations as explicit retry states
  - renamed current broad analysis API/UI path to `expanded_analysis`; `complete_analysis` is now reserved and rejected with `501`
  - verified with backend compile, backend unit tests, and desktop production build
- Rebuilt the onboarding route as a minimal animated Vault setup flow:
  - signup method step with email and a Google OAuth placeholder path for the future auth backend
  - display name, vault name, welcome, vault location, local chat model, memory-search model, and final welcome steps
  - brighter animated background wash, subtle moving grid, animated rotating text, reduced-motion fallback, and project-native rounded/bordered controls
  - vault location step shows the resolved `<selected folder>\.vault` data path and calls Electron vault activation before backend vault creation
  - chat model step reuses the model registry, model download, and cancel APIs
  - embedding step requires a successful memory-search test through the existing embedding configuration/status API before continuing
  - final setup state stores local profile/runtime choices and opens the Mind workspace
  - verified the desktop production build with `npm run build --workspace @cml/desktop`
- Completed the next public-V1 hardening pass:
  - added schema migration tracking with a baseline migration and interrupted-running migration detection before job recovery
  - added `/api/v1/system/startup-status` and `/api/v1/system/preflight/disk`
  - allowed system setup/status endpoints in pre-vault mode
  - added onboarding disk preflight before vault creation with a 5 GB default safety requirement
  - changed embedding setup direction to non-bundled compulsory setup: users download/link a model after install and setup cannot finish until the embedding test passes
  - expanded embedding status with `setup_required` and cache path reporting
  - upgraded Electron startup failure UI to show phase-specific repair guidance for integrity, schema/migration, lock, and generic backend failures
  - strengthened source deletion so raw/extracted text, pages, chunks, attachments, queued source jobs, checksums, paths, URLs, summaries, and citation pointers are removed or marked immediately
  - added tests for migration baseline, disk preflight, and immediate deletion/content removal
  - verified with backend compile, backend unit tests, and desktop production build
- Completed the next expanded-V1 foundation pass:
  - added an Electron `TokenStore` seam so backend API token storage is isolated behind `get/set/clear` instead of spreading file/DPAPI logic through `main.cjs`
  - hardened vault lock handling so a live but unverifiable lock owner is treated as unsafe instead of silently stale
  - changed embedding runtime configuration to require a local model/cache folder and load sentence-transformers in local-files-only mode
  - updated onboarding and Settings copy/validation so the embedding model path is compulsory and no embedding weights are implied to be bundled
  - added `/api/v1/integrations/local-folder/scan` for local folders, synced folders, and Obsidian-vault detection without ingesting automatically
  - added `/api/v1/system/hardware` with AVX2, memory, CPU count, hardware tier, and adapter-training support fields
  - extended expert job records with `failure_code`, `artifact_path`, and `hardware_tier`, including first `hardware_unsupported` classification for training attempts
  - created [CONNECTOR_AND_EXTENSION_ARCHITECTURE.md](CONNECTOR_AND_EXTENSION_ARCHITECTURE.md) for synced folders, Obsidian, browser extension capture, and future cloud OAuth connector boundaries
  - added tests for required embedding path validation, local folder scan detection, and hardware gate fields
  - verified with backend compile, 25 backend unit tests, and desktop production build
- Completed the next expanded-V1 implementation pass:
  - added `vault_lock_audit` records for lock acquire/release, live-owner conflicts, unverifiable owners, and stale-owner reclaim events
  - included lock audit, integration import, extension capture, and expert artifact counts in diagnostic database summaries
  - added durable `integration_imports` history when a local folder/Obsidian/synced-folder scan is associated with a vault
  - added `extension_clients` and `extension_captures` tables plus a local extension API scaffold:
    - `POST /api/v1/extension/clients`
    - `GET /api/v1/extension/status`
    - `POST /api/v1/extension/capture`
  - extension capture uses a separate extension token and stores captured text/page/selection content through the same normal source path
  - added `expert_artifacts` and registered `train_cluster_adapter` as a heavy, synthesis-blocking, manual-review/reconciliation job type
  - expert retrain now queues a training scaffold job when hardware passes the first gate, or marks unsupported hardware as manual review
  - added regression tests for integration import history, extension capture, expert adapter job scaffold, and vault-lock audit records
  - verified with backend compile, 29 backend unit tests, and desktop production build
- Completed the next visibility/UI pass:
  - added read APIs for integration import history, extension clients, extension captures, and per-cluster expert artifacts
  - wired desktop backend helpers and types for those APIs
  - added compact Settings surfaces for local import scanning/history, browser-extension token creation, extension capture counts, and hardware/adapter readiness
  - added adapter artifact visibility to the cluster Expert tab so scaffolded LoRA artifacts are inspectable
  - expanded regression coverage so integration history, extension listing, and expert artifact listing are checked through their read APIs
  - verified with backend compile, 29 backend unit tests, and desktop production build
- Completed the next control/hardening pass:
  - added extension client `allowed_vault_ids`, update, and revoke/disable support
  - enforced extension vault allowlists before capture so extension clients cannot write into arbitrary vaults when restricted
  - added Settings revoke controls for extension clients
  - added integration import refresh API for previously recorded local folder/Obsidian/synced-folder scans
  - added Settings refresh controls for local import history
  - added `/api/v1/system/vault-lock/audit` so the lock audit trail is visible for diagnostics/support
  - added cancellable background job cancellation through `/api/v1/jobs/{job_id}/cancel`
  - added Settings visibility for running jobs, rough remaining time, cancellability, and cancellation
  - added tests for extension permissions/revoke, integration refresh, lock audit read, and cancellable jobs
  - verified with backend compile, 30 backend unit tests, and desktop production build

## Public V1 Blockers

These items are not ordinary polish. If they are not implemented and verified, the release slips and should not be positioned as a public product for real user data.

- Vault data location correctness:
  - Electron must set the full-vault backend data paths from the user-selected vault folder: `CML_DATA_DIR=<vault>/.vault` and `CML_DATABASE_PATH=<vault>/.vault/cml.sqlite3`.
  - Onboarding must show the exact resolved vault data path before finish.
  - User-selected `vaults.path` cannot remain only display metadata.
- Pre-vault/full-vault backend lifecycle:
  - Add `CML_BACKEND_MODE=pre_vault | full_vault`.
  - Default developer mode can be `full_vault`, but startup must log mode, data dir, database path, startup status path, and whether the data dir was explicit or defaulted.
  - In `pre_vault`, middleware must reject all vault/source/chat/cluster/search/bridge write/read routes with `409 Vault not initialized`.
  - Pre-vault mode may handle only health, setup/status, model/embedding validation, startup status, app-level config, and diagnostics.
  - Pre-vault mode must not ingest sources, index chunks, create chats, create clusters, or write real vault records.
- Startup failure and repair surface:
  - Add `shared/startup-phases.json` as the canonical startup phase vocabulary, with hardcoded Python/Electron fallback phases for broken installs.
  - Electron must set `CML_STARTUP_STATUS_PATH=<appData>/startup-status.json` before every backend launch.
  - Python must write structured startup status for lock, DB init, integrity/schema/migration, job recovery, reconciliation, runtime detection, ready, and failure phases.
  - Electron must show structured startup failure/repair UI instead of generic backend unavailable when integrity/schema/lock startup fails.
- Migration runner and schema versioning:
- Schema version tracking and a baseline migration runner exist. Remaining work is deeper migration interruption/recovery tests and real migration scripts as schema changes continue.
- Disk preflight:
  - Add disk-space checks before installer/model downloads, OCR/model staging, indexing, and large ingestion jobs.
  - Show required/available space before multi-GB downloads.
- Local API auth hardening:
  - Token-gate private backend APIs for Electron-managed backends.
  - Validate renderer origins from observed dev/packaged origins.
  - Keep Bridge token permissions separate from core local API auth.
- Embedding setup gate and degraded boundary:
  - First-run setup must require a real embedding backend or existing compatible model path before normal vault use.
  - On every launch, embedding health must be rechecked; do not trust `embedding-runtime.json` alone.
  - If embeddings are missing, allow source list/page previews/raw text/general LLM chat, but block semantic search, retrieval chat, Bridge retrieval, clustering, new indexing, and re-embedding with explicit messages.
- Scheduler synthesis protection:
  - `_claim_next_job()` must enforce `can_run_during_synthesis`.
  - Treat `in_flight` generations as active and recent/dismissal-pending `retriable` generations as synthesis-protected according to the final retry policy.
  - Retry must re-acquire synthesis protection before starting a new generation.
  - `/jobs/status` must expose running job type, started time, timeout, cancellable status, elapsed time, and rough remaining estimate before UI promises background work will pause shortly.
- Chat recovery and timeline:
  - Add one combined chat timeline endpoint that returns user messages, assistant messages, and retriable generation placeholders in chronological order.
  - Retriable generation placeholders must be rendered as explicit interrupted states, not blank gaps or fake assistant messages.
  - Partial streamed text remains ephemeral in V1; offer retry using stored prompt/scope and copy partial text, not durable partial assistant messages.
- Complete-scope naming and validation:
  - Current broad rerun mode should be `expanded_analysis`.
  - Reserve `complete_analysis` for future evidence-packet map/reduce.
  - Valid JSON requests containing `complete_analysis` must return `501 Not Implemented`; malformed JSON keeps normal parse/validation behavior.
- Deletion and retention graph:
  - Source deletion must cover raw text, extracted pages, chunks, vectors, citation states, transcript sources, training examples, expert artifacts, and derived caches according to explicit ownership rules.
  - Deleted sensitive content must be excluded from search/retrieval immediately, before async cleanup.
- Diagnostic redaction and support:
  - Diagnostic bundles now have tested redaction, bundle format version, app/backend/schema versions, and generated timestamp.
  - Remaining diagnostic support work is a clear local log rotation policy and broader packaged-path diagnostic smoke.
- MCP Bridge production readiness:
  - JSON-RPC notifications must not emit responses.
  - Define app error codes such as `1001 no_active_vault`, `1002 permission_denied`, `1003 vault_not_found`, `1004 cluster_not_allowed`, `1005 cml_backend_unreachable`, and `1006 invalid_bridge_configuration`.
  - Distinguish dead stdio bridge process from live bridge with unreachable CML HTTP backend.
  - Add external-client end-to-end smoke before broad Bridge/MCP advertising; Claude Desktop-specific smoke is deferred for now.
- Expert/product claim hardening:
  - V1 user-facing language may claim trained cluster experts only after the verified LoRA graduation criteria pass for that cluster.
  - Adapter graduation requires supported hardware matrix, AVX2 detection, reliable failure codes, rollback/versioning, cleanup, quality win over retrieval baseline, and verified runtime on supported tiers.

## Current Open Work

- Preserve Windows-only public V1 as the first downloadable target.
- Run installer install/uninstall smoke on a clean path, not only the unpacked packaged app.
- Decide whether release builds should include optional embedding dependencies by default or keep them behind `-IncludeEmbeddingRuntime`.
- Replace user-facing deterministic/hash embedding selection with real local embedding setup. Hash embeddings may remain a hidden development fallback, but the product default must be an LLM embedding model.
- Finish the first-run setup from [ONBOARDING_PRD.md](ONBOARDING_PRD.md): add real Google OAuth/backend profile persistence if auth remains in V1, add first-source import after full-vault readiness, and visually QA startup repair states in packaged Electron.
- Reminder: revisit onboarding after the next backend pass. The current animated flow is good enough for local review, but it still needs a focused polish/fix pass for real Electron behavior, OAuth truthfulness, model setup edge cases, startup repair states, and packaged-app visual QA.
- Build first-run setup for model choices: recommended CML-managed downloads after install, or connect existing user-installed local models/endpoints for embeddings, synthesis, clustering, and later expert workflows.
- Add one-click local embedding dependency/model install from setup/settings. Backend download state now exposes byte/progress/speed/ETA fields, but setup/settings still need the end-to-end user-facing flow and a real network-backed cancellation smoke.
- Add integration roadmap work in priority order:
  - synced folder scan/import is now started for Google Drive Desktop, Dropbox, OneDrive, iCloud Drive, and normal local folders; next work is persisted import history and manual/watched refresh
  - Obsidian local vault scan detection is now started; next work is frontmatter parsing, attachment linking, and import-history UI
  - add Google Drive OAuth after local ingestion is stable, using narrow scoped access rather than full-drive access
  - add Dropbox OAuth after Drive, also with narrow scoped file permissions
  - add OneDrive/Microsoft 365 via Microsoft Graph as a Windows-first V1.1 candidate
  - add Notion after file/link ingestion is robust because it needs page/database ingestion rather than normal file ingestion
  - add browser extension capture as a public-V1 scope item for saving pages, selections, files/PDFs, and later screenshots into Vault through an extension-scoped local API identity
  - add later import/connectors for Apple Notes/Windows notes exports, Readwise/Reader, and Slack/Discord exports
- Finish hardening LLM-first chat after the first routing pass:
  - tune the retrieval-intent classifier on real prompts so vault questions route to context while normal conversation stays with the local LLM
  - add richer local-runtime recovery actions for missing, busy, crashed, and hung model states
  - replace the current complete-analysis foreground rerun with the planned long-running map/reduce job once evidence packets and token budgets are implemented
  - keep deterministic/rule handling minimal and only for obvious offline greetings/errors, not as the core chat engine
- Run a real long-download cancellation test against model and embedding downloads before calling cancellation production-ready. The backend now blocks concurrent managed downloads and exposes normalized progress/cancel fields, but real network-backed cancellation still needs smoke.
- Add job retry/backoff policy, cancellation, and UI-facing job failure states.
- Persist synced-folder import history and optionally add watched folder refresh.
- Synced-folder/Obsidian scan history is now persisted when tied to a vault, visible in Settings, manually refreshable, watch-refreshable, and can reconcile imported sources for new/changed/moved/deleted files with batch outcome counts. Obsidian Markdown frontmatter/wiki links/embedded attachment references are extracted into source text. Remaining ingestion work is packaged-runtime verification, not core ingestion behavior.
- Persist real source paths from ingestion so the map preview Vault/Explorer actions work on user-added files.
- Add backend service layer around raw route/database operations.
- Expand ingestion beyond the current narrow document set. Support common user-thrown local memory types where safe and bounded: images/screenshots, PDFs, DOCX, Markdown/TXT, notes, links, chat exports, audio clips, and small video files. Reject or gate unsafe/oversized formats such as executables, archives that exceed limits, and large movie files.
- Implement OCR for screenshots/images and scanned PDFs, including CPU throughput limits, visible job progress, and clear failure states.
- OCR direction is now OCRmyPDF + Tesseract, fully local. The backend exposes OCR runtime health and has an OCR job runner. Remaining work: stage Windows Tesseract/OCRmyPDF/Ghostscript/qpdf binaries, run real scanned-PDF and image OCR smoke tests through the packaged app, and add per-page progress rather than job-level status only.
- Fix PDF reader/storage behavior with working pagination. Store page-level extracted text, page metadata, and source/page references so chat citations and previews can open the right page.
- Add a large-cluster storage/retrieval plan for 1,000+ documents in one cluster: compact source metadata, chunk/page indexes, summarized context layers, lazy loading, pagination, and bounded cache usage.
- Design and implement complete-scope answering for large clusters in stages:
  - first build a coverage ledger and BM25/embedding relevance scoring across every document in scope, without any LLM map pass
  - benchmark and tune relevance thresholds on real vault data before depending on them for latency or correctness
  - then add LLM map passes only for above-threshold or coverage-required documents
  - then add reduce/reconcile/final synthesis phases
  - add derived-artifact caching only after the pipeline reveals which queries/artifacts are worth caching
- Expanded analysis now has persisted evidence-packet records and a queueable job, but this is not yet full complete-scope answering. The real V1 complete-scope path still needs threshold benchmarks, LLM map packets, partial-failure classification, reduce/synthesis prompts, and derived-cache pruning.
- Implement the source-of-truth/index consistency model before shipping real embedding transitions:
  - SQLite is authoritative; vector indexes are derived and rebuildable
  - embedding writes must use a SQLite transactional outbox and idempotent vector keys
  - failed/running/stuck embedding jobs must recover without leaving chunks permanently unsearchable
  - search must gracefully handle chunks that exist in SQLite but do not yet have vectors
  - add startup incremental reconciliation, periodic reconciliation, and manual full "repair vault" reconciliation
  - add deletion cleanup that prevents deleted sensitive content from surfacing even before async orphan cleanup completes
  - add vector/index compaction and storage accounting policy
- Replace static-only link ingestion with backend page capture/extraction that can open a URL, extract readable text, page metadata, images/media references, and handle dynamic pages through a browser/readability path where safe.
- Static link ingestion now attempts an optional Playwright-rendered fallback when the static HTML looks like a thin client-side app. Remaining work: package/browser-runtime decision, stricter dynamic-page sandboxing, richer readability extraction, and real dynamic-site smoke tests.
- Add task/list item ingestion as a first-class source type.
- Continue generated-reference exact-match polishing on Chat detail, Bridge, Timeline/Activity, Tasks, and packaged onboarding edge states. Home, Sources, Clusters, Map, cluster detail, prompt-zero Chat, Settings/Profile, shared shell, bottom user tab, and footer now have the new reference structure; the remaining pass should focus on typography, spacing, component finish, and route-specific edge states rather than a new visual direction.
- Keep the specified old Map reference image as the Map source of truth: `C:\Users\csshl\.codex\generated_images\019e7411-c67b-7ff3-a47b-5a8bb086f1c0\ig_015215293cf7ae25016a1c50a99ff881918f421c3047c44a24.png`.
- Keep the specified cluster-detail reference image as the cluster-detail source of truth: `C:\Users\csshl\.codex\generated_images\019e7411-c67b-7ff3-a47b-5a8bb086f1c0\ig_015215293cf7ae25016a1c4fef23608191ac77b9fc2c4bc45a.png`.
- Preserve backend-first data loading and keep mock/demo data out of production-shaped core surfaces. The shared shell, Home/Mind summary, Sources, and Settings now avoid seeded fallback data; remaining route-specific mock fallback still needs review in Map, Clusters, Chat, Timeline/Activity, and command palette paths.
- Continue applying remaining UI audit recommendations: shared page header/toolbar patterns, visual QA on Bridge controls, dark-version QA, and minimized/narrow desktop window QA.
- Continue replacing remaining V0 visual language in chat, settings, onboarding, and footer copy.
- Replace remaining copied/inspired-too-literally UI surfaces with CML-specific workflows.
- Finish packaged ingestion edge-case verification: real scanned-PDF/image OCR smoke with staged Windows OCR binaries, and packaged dynamic-link/browser-runtime QA.
- Expand embedding-based suggestions to include split workflows and batch review.
- Do a qualitative answer comparison across the downloaded GGUF models using representative CML prompts and local context.
- Add manual cluster override polish against backend state.
- Decide whether multi-cluster chat transcripts should also create a separate linked chat-memory cluster later.
- Replace expert lifecycle scaffold with real local training, adapter storage, evaluation, and rollback.
- Because LoRA is now required in public V1, continue from the verified adapter-training foundation: run a real LLaMA Factory training smoke, verify runtime adapter loading, expand the hardware/failure matrix, add richer UI states, and benchmark quality against retrieval-only answers before any broad user-facing expert claim.
- Adapter artifact storage, training job registration, process runner boundary, dataset export, artifact layout, metrics, activation, rollback, cleanup guardrails, and tests now exist. Remaining LoRA work: real external trainer smoke, runtime adapter loading, broader evaluation harness, packaged QA, UI controls, and quality comparison on representative prompts.
- Because cloud connectors and a full browser extension are now required in the expanded V1 scope, split connector work into local synced-folder import, extension local API identity/capture, and first OAuth connector rather than treating them as post-V1 nice-to-haves.
- Browser extension local API identity/capture scaffolding now exists; Settings can create and revoke a local extension token, clients can be restricted by allowed vault IDs, and extension capture now rejects cross-vault cluster assignments. Remaining extension work: actual extension package, safer pairing flow, capture-current-page/readability extraction, screenshot/PDF handling, and richer per-client permissions.
- Add a real backend profile/settings record for setup fields like user name and default vault instead of keeping them only in local storage.
- Add Python dependency CVE auditing to the toolchain, such as `pip-audit`, and run it in QA.
- Add local backend access hardening before exposing it beyond trusted loopback desktop use.
- Continue Bridge permission hardening. Permissions now prune stale vault/cluster IDs, token rotations are tracked, and extension capture enforces same-vault cluster scope, but malformed-client hardening and real MCP client smoke remain.
- Fix saved chats sidebar/tab refresh below Settings so it reflects created, renamed, deleted, and newly indexed chats without requiring a hard reload.
- Implement chat retention/evidence integrity before chat history grows large:
  - separate user-facing citation snapshots from internal retrieval audit logs
  - write assistant message, citation snapshot, and denormalized fallback citation fields atomically at message save/finalization time
  - add cursor pagination for chat sessions and messages with cursors that encode ordering/filter state
  - add stale/deleted/reindexed citation states with user-facing actions
  - compact old retrieval evidence into minimal tombstones instead of deleting citation records outright
  - define ownership for chat transcript sources before deletion work: either chat-owned transcript sources cascade forward on chat deletion, or transcript sources become independent vault sources with explicit unlink semantics
  - track chat-related storage as a breakdown across message text, citation snapshots, retrieval audit logs, transcript source chunks, and any chat-derived training examples
- Continue the cross-system failure coordination contract before implementing the remaining runtime/auth/expert/write-lock hardening:
  - startup order must be vault ownership, SQLite integrity/schema/migrations, job recovery, vector/index reconciliation, runtime detection, then API/UI traffic
  - long generations need persisted heartbeat fields so slow inference is not mistaken for a hung runtime
  - every background job type needs an explicit restart policy: `requeue`, `reconcile_then_retry`, or `manual_review`
  - runtime crash and backend restart during indexing still need state transition diagrams; vault lock contention now has an Electron Open-anyway path plus a complete backend override audit sequence, but still needs packaged visual QA
- Use the clean-slate schema window before any user data ships:
  - design `RetrievalSnapshot` and retrieval audit tables now instead of storing long-term retrieval metadata only as JSON on `chat_messages`
  - encode the expert lifecycle state machine now: `retrieval_ready`, `expert_training_pending`, `expert_training_ready`, `expert_training_failed`, and `hardware_unsupported`
  - define `sources`, `source_pages`, and `source_chunks` so every chunk references a page and every citation can navigate chunk -> page -> source -> file
  - document SHA-256 of normalized text as the stable content-hash algorithm; changing it later requires full re-embedding
  - put reconciliation job types in the job registry before reconciliation code can queue them
  - hide hash embeddings behind an explicit development flag; production setup should not silently fall back to hash embeddings

## Next Build Checkpoints

### Phase 1: Job Scheduler

- Completed: high-priority job queued behind a running low-priority job runs next after the low-priority job completes.
- Completed: dependent job with `dependency_failure_policy = cancel` transitions to `cancelled` when its dependency fails.
- Completed: backend restart with a `running` job and `restart_policy = requeue` transitions that job back to `queued`.
- Completed: unknown job type transitions to `manual_review`; worker does not crash.
- Completed: two jobs with the same write scope do not run concurrently under the V1 single-worker assumption.
- Completed: dependent jobs start as `blocked_by_dependency` and missing blocked dependencies resolve through dependency failure policy.

### Phase 2: Backend Ownership And Auth

- Private API route without token returns 401 and exposes no data.
- Private API route with valid token returns 200.
- Second app launch focuses/restores first window and exits cleanly.
- Startup with corrupt SQLite halts at integrity check, surfaces repair flow, and does not open private API traffic.
- Startup with stale vault lock from dead process reclaims lock and proceeds.
- Startup with valid live vault lock refuses write access and surfaces the correct message.

### Phase 3: Ingestion And Indexing Rework

- Ingest a 10-page PDF and verify one source, ten `source_pages`, chunks with non-null `page_id`, chunk `content_hash`, and queued embedding jobs.
- Delete a source and verify SQLite marks it deleted immediately, search excludes it through joins/filters immediately, and vector cleanup is queued.
- Run reconciliation with a chunk missing a vector and verify a correctly scoped re-embed job is queued.
- Run reconciliation with stale `embedding_model_id` and verify stale chunks are detected without duplicate active jobs.
- Ingest the same file twice and verify checksum-based duplicate detection plus user-facing deduplication behavior.

## Running Notes

- UI redesign direction as of 2026-05-31 after review: avoid colorful AI-dashboard treatment. Use premium utilitarian minimalism across onboarding and app routes: warm off-white canvas, flat document-like surfaces, 1px dividers, restrained sage/clay/blue cluster accents, fewer cards, no glow/gradient decoration, and stronger typography/spacing. Behance references are moodboard inputs only; do not copy layouts/assets directly.
- Current exact-match UI source of truth is the generated Vault image set in `C:\Users\csshl\.codex\generated_images\019e7411-c67b-7ff3-a47b-5a8bb086f1c0`. Use those files for implementation decisions, with the older Map reference and specified cluster-detail reference overriding later generated variants.
- The biggest remaining UI risk is not page coverage but finish: typography scale, whitespace, hairline divider subtlety, icon lightness, and component softness. Avoid rigid/default card styling and keep pages closer to the reference's paper-like desktop product feel.
- UI implementation rule: keep the app shell restrained and functional, use animation only where it helps state changes, and make clusters feel like an organized memory ledger/table with optional inspector panels rather than decorative cards.
- The July-end target is achievable for a demoable MVP if we keep V1 focused.
- The riskiest feature is local fine-tuning, not the desktop shell.
- The app should remain useful during expert bootstrapping through retrieval-backed context.
- First-time onboarding must require a real embedding backend before the user reaches the main vault. The user can either download Vault's recommended embedding model or point Vault at an existing compatible local embedding model/cache path. Hash embeddings are dev/test only and must never satisfy production onboarding.
- The onboarding design spec is now [ONBOARDING_PRD.md](ONBOARDING_PRD.md). It defines the Apple-like minimal flow, current OKLCH palette, one-decision-per-screen rule, exact selected-folder-to-`.vault` storage contract, compulsory memory-search setup, optional local chat setup, and startup repair requirements.
- Onboarding should be revisited later rather than treated as final. Current known gaps: dev/browser flow differs from packaged Electron, Google OAuth is placeholder-only, model setup needs stronger progress states, and startup repair states need packaged visual QA.
- We should avoid silent full-device scans in V1.
- Every task should end by updating this file with completed work and remaining work.
- Electron is the pragmatic first shell. Tauri can be reconsidered after the app flow is proven.
- Python 3.14 is installed locally; ML libraries may later require a separate Python 3.11/3.12 environment.
- The actual cluster hit target should stay stable; any blob movement should be visual-only so double-click and drag remain reliable.
- Avoid direct UI copying from reference products. Use references only for interaction principles, then translate them into CML-specific layouts and working controls.
- Port `7342` was still responding with stale pre-DOCX/PDF backend behavior during the ingestion smoke test, so document ingestion was verified on a clean temporary backend at `7343`. Restart the normal backend/session before testing DOCX/PDF through the desktop app.
- Current link ingestion is static HTTP/HTML extraction. The target behavior is backend-driven URL opening/extraction that captures readable text, metadata, and image/media references, with a browser/readability path for safe dynamic pages. Authenticated pages remain a later explicit-connector problem.
- Direct Drive/Dropbox/OneDrive cloud APIs are intentionally out of V1. Synced folders provide the free local path now; OAuth connectors can come after the core local context flow works.
- Integration priority is local-first first: synced folders and Obsidian import before OAuth. Cloud OAuth order should be Google Drive, Dropbox, OneDrive/Microsoft Graph, then Notion. Browser extension is a high-value later capture surface once ingestion and deletion guarantees are stable.
- Current local embeddings include deterministic hashed vectors for development/bootstrap only. This must not remain the user-facing product option because it undermines the core promise of semantic local context. V1 should default to a real local embedding model with setup-time user choice and explicit model storage.
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
- The local backend still assumes trusted loopback desktop use. Before any wider network exposure, add stricter origin checks and per-client Bridge identities. Bridge now has local enabled state, token auth, allowlists, and redaction permissions.
- Python dependency CVE auditing was not completed because `pip-audit` is not installed in the current environment.
- Electron launch note: if the window does not open but Vite is reachable, check `ELECTRON_RUN_AS_NODE`. It must be unset for the Electron shell process.
- UI audit risk reduced: Bridge controls, chat attachment/save/regenerate actions, cluster expert controls, cluster source-picker actions, and command palette new chat are no longer misleading production-looking dead controls. Cluster detail now uses backend data. Chat answer feedback/save/delete/regenerate controls now have backend behavior. Remaining risk is backend completeness, especially Bridge permissions, MCP/CLI setup, and direct source move controls inside cluster detail.
- Chat transcript memory now uses the background job queue. Persisted chat turns are stored immediately, then transcript sources/chunks are indexed by the worker and the session moves from `indexing` to `indexed`.
- Context Bridge HTTP retrieval is now semantic, local, and permission-gated by enabled state, token auth, vault/cluster allowlists, and raw-text redaction. Token rotations are recorded, missing/ambiguous vault scope returns `no_active_vault`, and MCP notifications now correctly produce no response. Before exposing it to external clients beyond trusted local testing, keep claims conservative and add external-client smoke when reprioritized; Claude Desktop-specific smoke is deferred for now.
- Current-code backend is running on `http://127.0.0.1:7343` because `7342` is occupied by stale Windows listeners with non-existent PIDs. The `7343` backend exposes the new chat session/message routes, Bridge settings route, and semantic Bridge routes.
- Chat streaming now uses `/api/v1/chat/context/stream`. When a local OpenAI-compatible runtime is available, CML parses runtime SSE chunks; otherwise retrieval fallback text is streamed in local chunks.
- Expert lifecycle now has a verified LoRA training foundation. The deterministic test trainer can produce adapter-shaped artifacts for CI, while public V1 still requires a real LLaMA Factory run and runtime adapter-loading smoke before claiming production training.
- Diagnosed the `{"detail":"Not Found"}` UI issue: `7342` is an older stale backend that lacks `/api/v1/chat/messages/{message_id}` and `/api/v1/bridge/settings`, while `7343` has the current routes. The desktop API client now probes configured URL, `7343`, then `7342`, and only uses a backend with the current chat routes. Also set local `.env` `VITE_CML_BACKEND_URL=http://127.0.0.1:7343`.
- Restarted the desktop dev stack after unsetting `ELECTRON_RUN_AS_NODE`; Vite is reachable at `http://127.0.0.1:5173/` and the current backend routes are reachable on `7343`.
- Electron now has a backend process manager for dev and packaged mode. Packaged mode now expects staged backend source plus a staged Python venv runtime under app resources.
- Packaged installs must move away from hash embeddings as the default. Until setup-time model selection is wired, hash embeddings are only an implementation fallback. The intended V1 path is a real local embedding model, with `sentence-transformers/all-MiniLM-L6-v2` as the current development candidate cached locally through `CML_EMBEDDING_CACHE_DIR`.
- `sentence-transformers/all-MiniLM-L6-v2` is installed and cached locally at `T:\LLM\embeddings` for development testing. Windows may warn about Hugging Face cache symlinks unless Developer Mode/admin symlink privileges are enabled; the cache still works but can use more disk.
- The local development `.env` is configured for SentenceTransformers/MiniLM, but the packaged backend currently starts without that local `.env` and can report the hash embedding provider. The setup flow needs to write packaged-user embedding settings before a real embedding model becomes the packaged default.
- The Windows NSIS installer build previously succeeded, but local `apps/desktop/release` artifacts were removed during the lean cleanup. Run `npm run package:win` only when a fresh installer artifact is needed.
- Electron has been bumped to `39.8.10`; `npm audit` currently reports zero vulnerabilities.
- Dev Electron launch now goes through `apps/desktop/scripts/start-electron.cjs` so `ELECTRON_RUN_AS_NODE` is removed before opening the window.
- The latest installer configuration uses electron-builder's one-click NSIS mode, which removes the old wizard-style path chooser and is the cleanest installer experience available without replacing NSIS with a custom installer.
- Packaged launch smoke requires `ELECTRON_RUN_AS_NODE` to be unset. If that environment variable is set globally, packaged Electron exits as Node before the app can start.
- Embedding provider selection is now runtime-configurable, but the product setup should not present deterministic/hash embeddings as a normal choice. Users should choose between CML's recommended embedding model download and their own compatible local embedding model/runtime.
- Onboarding and Settings now have an Electron folder picker for local embedding model selection and test the chosen SentenceTransformers model before enabling memory search. This is still a select/test flow, not a managed embedding download.
- Onboarding and Settings now also expose a managed recommended embedding model download action. The backend can start/cancel/report the download, but byte-level progress and packaged dependency validation still need QA.
- The first Bridge MCP server is a prototype stdio JSON-RPC bridge around the existing local HTTP permissions model. Dedicated Bridge client tokens and permissions now exist; Claude Desktop-specific smoke is deferred for now.
- The 2026-06-01 Playwright UI audit found the current desktop layout is usable, but narrow desktop/minimized-window behavior is broken on `/search` because the shell/content retain full-width assumptions. Do not build a dedicated mobile screen for public V1; treat minimized/narrow desktop shell repair and the dark version as the UI hardening target.
- Vault lock contention now has a first Electron override path: the startup repair screen can trigger a one-shot `CML_VAULT_LOCK_OVERRIDE=open_anyway` backend restart, and the backend writes a structured override audit sequence. This still needs packaged visual QA and clearer user-facing corruption copy before public release.
- Packaged Electron now serves the production TanStack renderer through an internal loopback server because the build is SSR-shaped and does not emit a normal `dist/client/index.html`.
- Model download cancellation is cooperative. It can stop active chunked downloads and remove partial files, but should still be tested against a real multi-GB transfer.
- Chat should remain global-by-default and context-first. Cluster selection is a refinement control, not a setup step before asking.
- Local synthesis must not make Chat feel broken. If the configured OpenAI-compatible runtime is unavailable or slow, the app should quickly return a retrieval-backed answer with citations and a visible runtime note.
- Complete-scope answering for large clusters must not mean raw stuffing or an LLM call for every document. The intended contract is: every document in the selected scope is scored and accounted for; above-threshold or coverage-required documents are analyzed in detail; low-relevance and unreadable documents are explicitly recorded.
- Relevance threshold tuning is the critical first benchmark for complete-scope answering. Too high silently misses relevant documents; too low causes unacceptable local inference latency. Start with explicit BM25 + embedding scoring ledgers and tune on real vaults before adding expensive LLM map passes.
- Query cache keys should use exact query fingerprints initially. Semantic cache reuse can improve hit rate later, but it creates correctness risk when similar-looking prompts require different evidence.
- Broad-query routing should default to a fast answer path with a visible "Run expanded analysis" action for the current broader-scoring mode. Automatic breadth detection can be added later, but the first version should explain the latency tradeoff before launching a long job.
- The current implemented broad rerun is not complete-scope answering and must not be labeled complete analysis. Use `expanded_analysis` for current code. Reserve `complete_analysis` for a future evidence-packet map/reduce path that can account for every source in scope, handle partial failures, and synthesize only after the evidence set is complete.
- Requests containing `complete_analysis` should be rejected with `501 Not Implemented` after JSON parse succeeds and before intent routing. Malformed JSON should keep normal parse/validation behavior. This prevents accidental silent aliasing to `expanded_analysis`.
- Complete-analysis background jobs should show progress and document accounting, but should not stream partial synthesized answers from incomplete evidence sets. Showing a partial answer that later changes creates trust problems. Stream only the final synthesis once the evidence set is complete.
- Cache invalidation for large-cluster answers must track contributing documents, not only a blunt cluster membership version. If a newly added or moved document was scored low-relevance for a cached query, prior query-level artifacts may remain valid; if it contributed to `docs_analyzed` or relevant evidence, invalidate the affected reduce/final artifacts.
- Map packet `read_errors` need a reducer contract. The reducer must classify each failed/partial document as skipped, retried, metadata-only, cached-text-only, OCR-failed, timeout, or unsupported, and the final answer must report those counts rather than ignoring the field.
- Derived cache controls should be granular and plain-language: clear query-level cache, clear cluster summaries, or clear all derived artifacts. The UI must explain rebuild cost before clearing because broad questions may take several minutes again after cache removal.
- Vector/index consistency model: SQLite is the source of truth and vectors are derived indexes. This requires a transactional outbox for embedding jobs, idempotent vector keys, reconciliation, and rebuild/repair controls before MiniLM or any real embedding model transition ships broadly.
- Embedding worker failure must be handled explicitly. A job can be committed in SQLite, marked running, then fail during vector write because of disk full, lock contention, or process death. Stuck-job recovery and reconciliation must detect `running` jobs with no corresponding vector row and requeue them. Search must degrade gracefully for chunks missing vectors instead of making them permanently invisible.
- Verify LanceDB upsert semantics before committing to the vector key design. If LanceDB cannot atomically upsert by a deterministic composite key, the implementation must use a safe delete/insert or versioned-write pattern that avoids long invisibility windows during searches.
- Reconciliation cannot full-scan large vaults on every app launch. Keep per-vault/index watermarks such as `last_reconciled_at` and reconcile incrementally by modified rows by default. Full cross-check reconciliation should be a manual "repair vault" action or an occasional background maintenance job, not a startup blocker.
- Embedding model transitions need an active-index policy. When moving from hash embeddings to MiniLM or another model, keep old vectors readable until the new model index is complete enough, then atomically switch the active embedding model/index version for the vault. Do not mix similarity scores from different embedding models in one ranked result set.
- Delete semantics must protect user trust. When a source is deleted or marked deleted in SQLite, search/retrieval must exclude it immediately at the SQLite/filter layer even if async vector cleanup has not completed. Deletion cleanup jobs should be high priority, with synchronous vector delete attempted for direct user deletes when practical.
- Index size reporting needs a measurement policy. Per-vault size can use actual index directory size; per-cluster/source size may be an estimate based on chunk/vector counts unless the vector store exposes precise accounting. The UI should label estimated numbers honestly.
- Vector indexes need compaction policy, not only orphan cleanup. LanceDB/columnar stores can fragment after many writes/deletes. Add scheduled or threshold-based compaction after bulk cleanup/reindexing and expose it as part of vault repair/maintenance.
- Chat history model: chat text is durable user data; retrieval evidence is derived and versioned. Do not conflate user-facing citation display with internal retrieval debugging. Use separate storage/retention for citation snapshots and retrieval audit logs.
- Citation snapshots must be written atomically with assistant message finalization. If streaming is cancelled or the backend crashes, the saved message and its citation display data should not diverge. Avoid follow-up jobs for core citation snapshot writes.
- Chat pagination cursors need to encode ordering and filter state, not only timestamp/row ID. Future filters by source, cluster, date, or search term must not return inconsistent pages when new messages are inserted between requests.
- Old citation snapshots should be compacted, not hard-deleted. If message text includes inline citations, deleting the snapshot leaves historical answer text pointing nowhere. Compact to minimal tombstones with source title, source ID if still present, page/location, snippet hash, and stale/deleted state.
- Stale citation labels need actions. Deleted-source citations should show stored excerpt/fallback metadata. Re-indexed citations should link to the current source/chunk/page when possible with a note that the source changed after the answer.
- Chat transcript memory creates a reference-cycle risk because chats can be indexed as sources and later cited by other chats. Decide ownership before schema work: chat-owned transcript source with forward cascade on chat deletion, or independent source after indexing with explicit unlink/delete behavior. Avoid bidirectional implicit cascades.
- Chat storage reporting must include all chat-related footprint, not only `ChatMessage` rows: message text, citation snapshots, retrieval audit logs, transcript source chunks, and chat-derived training examples. Show the breakdown before adding archive/compact controls.
- Cross-system failure sequencing rule: acquire/verify vault ownership first; verify SQLite integrity, schema version, and migrations second; recover jobs third; reconcile vector/index state fourth; detect runtime fifth; accept API/UI traffic last. Do not run job recovery against a database that has not passed integrity/schema checks.
- SQLite startup checks must run before job recovery mutates state. At minimum use `PRAGMA integrity_check`, schema version validation, and a migration runner that can detect/handle interrupted migrations. If integrity or migration fails, halt startup into a repair flow instead of accepting traffic.
- Generation heartbeat storage should be explicit. Store `last_heartbeat_at` on the generation record in SQLite, updated roughly every 10 seconds during active inference as a low-priority write outside the main job queue. Hung detection should require both repeated runtime health failures and heartbeat silence to avoid false positives on slow hardware.
- Background job types need restart policy metadata before restart recovery is implemented. Initial classification: extraction, embedding generation, OCR, link fetch, cluster suggestions, and expert status updates are `requeue`; expert training, cluster merges, vault migrations, and delete/cleanup jobs are `reconcile_then_retry`; unknown or partially implemented jobs are `manual_review`.
- Runtime crash during generation should mark the active generation `retriable` or `failed_runtime`, show restart/retry/context-only actions, and leave indexing jobs running unless they explicitly depend on the runtime. Vault lock state should not be touched by runtime recovery.
- Scheduler synthesis gating decision: for V1, keep chat generation state in `chat_generations` rather than migrating it into `app_jobs`, but `_claim_next_job()` must query generation state before claiming jobs with `can_run_during_synthesis = false`. This is deliberate technical debt; the long-term cleaner path is to unify long-running generation work under the job system.
- Synthesis-active gating should treat `in_flight` generations as active. Retriable generations should stay visible indefinitely in the UI, but only block non-synthesis-safe jobs while they are recent or awaiting user decision according to the final policy. Retry starts a new generation and must re-acquire synthesis protection before streaming.
- The UI must not promise "pausing shortly" unless `/jobs/status` exposes running job type, start time, timeout, cancellable state, elapsed time, and estimated remaining time. If a long non-preemptable job is running, the UI should say retry will start after the current background task finishes and offer cancellation only when the job is cancellable.
- Interrupted streaming answers are not durable assistant messages unless `_complete_chat_generation()` commits. V1 should show partial frontend text as ephemeral, with `Retry` using the persisted prompt/scope and `Copy partial text`; after restart, render a durable retriable-generation placeholder from `chat_generations`.
- Chat timelines should come from one combined endpoint that returns `user_message`, `assistant_message`, and `retriable_generation` items in chronological order. Do not make the frontend merge separate `chat_messages` and `chat_generations` queries.
- Backend restart during active indexing should mark old-session `running` jobs as interrupted, then apply each job type's restart policy. Old `in_flight` generations become `retriable`; runtime state is re-detected from process/port/model rather than trusted from memory.
- Vault lock contention on launch should refuse a second write owner when the lock owner process is verified alive. If Electron receives a second-instance launch, focus/restore the existing window. If a different vault path is requested, V1 should refuse and explain rather than opening another writer.
- Backend startup hard gates: acquire vault lock, run `PRAGMA integrity_check` and parse result rows, validate schema version/run migrations, recover jobs, run lightweight vector reconciliation scan that only queues jobs, detect runtime without waiting for it, then open API traffic. If integrity check returns anything other than `ok`, halt into repair flow. If integrity check exceeds 60 seconds, surface a slow-vault startup message rather than a blank window.
- Vault lock process verification currently depends on Windows CIM/PowerShell command-line inspection. If verification fails because access is restricted, treat the lock as `unverifiable`, not simply stale or live. The UI must offer Cancel/Open anyway with explicit corruption warning. Lock override audit logs now record detection, dialog display, user choice, startup result, and lock acquisition; interrupted-before-choice remains a future packaged-flow edge case.
- Startup status contract: Electron sets `CML_STARTUP_STATUS_PATH` to an app-data JSON file before backend launch. Python writes structured phases there. Use `shared/startup-phases.json` as canonical phase vocabulary, with hardcoded fallback phases in Python/Electron for broken installs where the shared file is missing or malformed.
- Startup status phase names must be stable values such as `starting`, `pre_vault_mode`, `vault_lock_acquiring`, `vault_lock_failed`, `database_initializing`, `integrity_check_running`, `integrity_check_failed`, `schema_check_running`, `schema_check_failed`, `job_recovery_running`, `reconciliation_queued`, `runtime_detection_running`, `ready`, and `startup_failed`.
- Pre-vault/full-vault lifecycle: first launch without an active vault starts a restricted pre-vault backend using app-data only and no vault lock. After vault folder selection, Electron shuts that backend down and starts a full-vault backend with data/database paths under the chosen vault folder. Ingestion/indexing/chat/clusters are only allowed after the full-vault backend owns the vault path.
- Token storage uses the `TokenStore.get()`, `TokenStore.set(token)`, and `TokenStore.clear()` interface. Electron `safeStorage` is wired when available, with an encrypted local fallback for test/non-Electron contexts; OS-specific secure-storage logic must stay behind this interface.
- CORS allowlist must be based on observed renderer origins. Before implementing the allowlist, add temporary dev/package logging for the `Origin` header and record actual values for Vite dev and packaged loopback renderer.
- Electron single-instance handler product rule: a second launch focuses/restores the existing window. If the second launch requests a different vault path, V1 shows "Vault is already open. Close the current vault before opening another." No second writer and no silent ignore.
- Ingestion schema target: `sources` store source-level identity/status/checksum; `source_pages` store page number, raw/extracted text, extraction version, and page content hash; `source_chunks` store source/page IDs, chunk index, text, embedding model ID, normalized-text content hash, index version, and indexed timestamp. Chunks without a page ID should not exist in the clean schema.
- Content hash decision: use SHA-256 of normalized chunk text as the stable hash for chunks/indexing. Do not use MD5 or a rolling hash. Changing the algorithm later is a full re-embedding migration.
- Production builds should not expose hash embeddings as a user-selectable fallback. Hash embeddings are development-only behind an explicit flag. If a real embedding model is unavailable in production setup, the UI should say embeddings are not configured rather than silently using hash vectors.
- Embedding health boundary: existing source lists, page previews, raw text, and general LLM chat can continue when embeddings are unavailable. Semantic search, retrieval chat, Bridge retrieval, clustering, new indexing, and re-embedding must block or degrade with explicit messages because query embedding still requires the embedding provider.
- Retrieval-intent chat must check embedding health before context assembly. If a vault/source/cluster/context question needs memory and embeddings are missing, return an explicit degraded retrieval state instead of silently falling back to LLM-only with empty context.
- Chat transcript memory policy: transcript sources should not dominate retrieval. Current keyword exclusion is a guardrail, not the final model. Add source-class weighting calibrated against transcript-win, transcript-lose, and mixed document+transcript cases before relying on transcript retrieval broadly.
- Comparison queries such as "compare my notes and our chat about X" require a separate `compare_source_classes` intent. This should retrieve top evidence independently per source class and use a grouped synthesis prompt, not a single mixed ranked context block.
- MCP Bridge protocol notes: JSON-RPC notifications must produce no response. Use positive app error codes for Bridge/application failures. `1005` means the stdio bridge is alive but the CML HTTP backend is unreachable; a dead stdio bridge process is an OS/process-manager failure outside JSON-RPC and should be surfaced by process startup/stderr behavior.
- MCP `list_clusters` and context calls must not silently choose the first vault. If no active/allowed vault is configured, return a JSON-RPC application error such as `1001 no_active_vault`, not a successful text response or empty list.
- Expert/product-language rule: public V1 keeps verified LoRA as the main selling point, but the UI must only call a cluster expert "trained" after that cluster has a ready active adapter with metrics, versioning, rollback, and supported-hardware provenance.
- Adapter graduation criteria: publish a hardware matrix with AVX2 requirement, GPU tier, CPU high-spec tier, and CPU minimum tier. Training must meet reliability, quality, runtime, recovery, storage, and failure-code criteria on supported tiers before leaving experimental status. If AVX2 detection fails, mark hardware as `unknown`, allow one explicit warned attempt, and convert illegal-instruction/runtime failure into `hardware_unsupported`.
- Public V1 gate: auth hardening, vault-lock override UX, packaged startup repair QA, vault data path correctness, embedding setup polish, deletion graph edge cases, scheduler synthesis gate, diagnostic packaging/log-rotation policy, hardware-aware model recommendation, and verified LoRA are blockers. If incomplete, release slips.
- Expanded V1 scope now explicitly includes LoRA, cloud connectors, and a full browser extension. This makes the earlier tight-MVP step count obsolete; the roadmap must be treated as a broader Windows-only public-V1 build.
- Token storage now has an Electron interface seam, Electron `safeStorage` support, encrypted fallback storage, and plaintext regression coverage.
- Vault lock reclaim is now safer for unverifiable live processes, and the Electron-facing Open-anyway override plus backend user-choice/startup-result audit sequence exist. Remaining work is packaged visual QA and the interrupted-before-choice edge case.
- Vault lock audit rows now exist for backend lock events and override flow events.
- Embedding setup now requires a local model/cache folder and uses local-files-only loading. The remaining UX gap is a clean model download/link flow with real byte progress, network-backed cancellation smoke, and clear destination paths.
- Local integrations now have a backend scan primitive. It intentionally does not ingest automatically; import history, watched refresh, and source-to-folder reconciliation are the next implementation layer.
- Local integration scans can now persist import history when a vault ID is supplied. Watched refresh and reconciliation are still not implemented.
- LoRA readiness now has hardware status gates, expert job metadata, a trainer process boundary, dataset export, artifact schema, metrics, active adapter state, rollback, delete guardrails, and tests. Real external LLaMA Factory training and runtime adapter loading still need smoke verification.
- The extension API scaffold creates tokened local extension clients and captures text into Vault sources. It is not a full browser extension yet, and it still needs pairing UI plus per-client permission controls before user exposure.
- Job cancellation is now available for jobs marked cancellable, but it is cooperative. A running non-preemptable task may still finish its current operation; cancellation prevents final success marking where the worker observes the cancelled state.
- Integration refresh is scan-only. It updates counts and status for a watched root, but it does not yet diff, import, delete, or move sources.

## Update Protocol

At the end of every task:

1. Update `Last updated`.
2. Update relevant phase progress bars.
3. Add completed work to `Current Completed Work`.
4. Add or remove items from `Current Open Work`.
5. Add important decisions or risks to `Running Notes`.

